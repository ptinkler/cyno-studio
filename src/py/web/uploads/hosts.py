"""Host local source media for providers that accept only a URL.

Per-user preferences select the host (litterbox, uguu, tmpfiles, or self-host) and
retention; the primary host is tried before the backup.
"""

import logging
import threading
import time
from collections.abc import Mapping
from http import HTTPStatus
from pathlib import Path

import httpx
import requests
from bs4 import BeautifulSoup
from pydantic import TypeAdapter

from web.core import net_guard
from web.media.public import selfhost_url
from web.types import JsonValue
from web.uploads.settings import UploadPrefs, current_upload_prefs

log = logging.getLogger(__name__)

LITTERBOX_URL = "https://litterbox.catbox.moe/resources/internals/api.php"
TMPFILES_URL = "https://tmpfiles.org/api/v1/upload"
UGUU_URL = "https://uguu.se/upload"
# uguu.se: anonymous, serves the raw file at its URL, max 128 MiB, deleted after 3h.
UGUU_MAX_BYTES = 128 * 1024 * 1024
_UGUU_RESPONSE = TypeAdapter(dict[str, JsonValue])
# Litterbox only offers these fixed retentions; map any requested span to the
# nearest. Keys are minutes.
_LITTERBOX_BUCKETS = {60: "1h", 720: "12h", 1440: "24h", 4320: "72h"}
_TMPFILES_RESPONSE = TypeAdapter(dict[str, JsonValue])


class UploadError(ValueError):
    """A source file could not be hosted publicly (the message is shown to the user)."""


class HostedFileUnreachableError(UploadError):
    """The uploaded file's public URL could not be fetched."""

    def __init__(self, cause: Exception) -> None:
        """Name the kind of network failure."""
        super().__init__(f"hosted file isn't reachable ({type(cause).__name__})")


class HostedFileStatusError(UploadError):
    """The uploaded file's public URL answered with an error status."""

    def __init__(self, status: int) -> None:
        """Give the HTTP status."""
        super().__init__(f"hosted file answered HTTP {status}")


class HostedFileIsPageError(UploadError):
    """The public URL serves a web page instead of the file."""

    def __init__(self, suffix: str) -> None:
        """Name the file type that was expected (its extension, if any)."""
        super().__init__(f"hosted file served a web page, not {suffix.lstrip('.') or 'the file'}")


class UnknownHostError(UploadError):
    """The chosen upload host is not one we support."""

    def __init__(self, host: str) -> None:
        """Name the host."""
        super().__init__(f"Unknown upload host {host!r}")


class FileTooLargeForUguuError(UploadError):
    """The file is over uguu.se's size cap."""

    def __init__(self, size_bytes: int) -> None:
        """Give the file's size."""
        super().__init__(f"uguu.se takes files up to 128 MiB; this one is {size_bytes / 1024 / 1024:.0f} MiB")


class UploadFailedError(UploadError):
    """The request to a host failed at the network level."""

    def __init__(self, service: str, cause: Exception) -> None:
        """Name the service and what went wrong."""
        super().__init__(f"{service} upload failed — {type(cause).__name__}: {cause}")


class UploadRejectedError(UploadError):
    """A host answered, but not with a hosted file."""

    def __init__(self, service: str, detail: object) -> None:
        """Name the service and what it said."""
        super().__init__(f"{service} upload failed — {detail}")


class UploadUnexpectedReplyError(UploadError):
    """A host's reply could not be understood."""

    def __init__(self, service: str, body: str) -> None:
        """Name the service and show the start of its reply."""
        super().__init__(f"{service} upload failed — unexpected reply: {body[:200]}")


class UploadHttpError(UploadError):
    """A host answered with an HTTP error."""

    def __init__(self, service: str, status: int, body: str) -> None:
        """Name the service, the status and (if any) the start of its reply."""
        detail = body[:200].strip()
        super().__init__(f"{service} upload failed — HTTP {status}" + (f" — {detail}" if detail else ""))


class LitterboxTimeoutError(UploadError):
    """Litterbox did not answer in time."""

    def __init__(self) -> None:
        """Build the fixed message."""
        super().__init__("Litterbox upload timed out — cycle VPN if blocked")


class TmpfilesNoUrlError(TypeError):
    """tmpfiles.org's upload reply carried no file URL."""

    def __init__(self) -> None:
        """Build the fixed message."""
        super().__init__("tmpfiles.org upload response has no URL")


class TmpfilesNoDirectLinkError(UploadError):
    """tmpfiles.org's file page had no direct download link."""

    def __init__(self, page_url: str) -> None:
        """Give the page that was searched."""
        super().__init__(f"tmpfiles.org upload succeeded but no direct download link found on {page_url}")


# A retry (or a second model on the same source media) re-runs the whole submit
# and would otherwise re-upload the same local file — pure wasted bandwidth,
# since the hosted URL is still live. Remember each successful upload keyed by
# (file identity, host, requested span) and reuse it until shortly before it
# expires. In-memory and per-process, so it helps the common case (consecutive
# retries on the same worker) without any shared state; a cold worker just
# re-uploads. Keyed on size+mtime so editing the file forces a fresh upload.
# (resolved path, size, mtime_ns, host, expiry minutes) of an uploaded file
_CacheKey = tuple[str, int, int, str, int]
_url_cache: dict[_CacheKey, tuple[str, float]] = {}
_url_cache_lock = threading.Lock()
# Stop handing out a cached URL this long before it truly lapses, so Pollo never
# fetches one that dies mid-job: 10% of the span, capped at 5 minutes.
_CACHE_MARGIN_FRAC = 0.1
_CACHE_MARGIN_MAX_S = 300
_URL_CACHE_MAX = 256  # bound the dict; prune expired first, then oldest
# Hosts that ignore the requested span and keep files for a fixed time (minutes).
_FIXED_RETENTION_MIN = {"tmpfiles": 60, "uguu": 180}


def clear_url_cache() -> None:
    """Forget every remembered upload (tests, and after upload settings change)."""
    with _url_cache_lock:
        _url_cache.clear()


def expire_cached_urls() -> None:
    """Make every remembered upload look lapsed, so the next upload goes out afresh."""
    with _url_cache_lock:
        for key, (url, _) in list(_url_cache.items()):
            _url_cache[key] = (url, time.time() - 1)


def cached_url_expiries() -> list[float]:
    """When each remembered upload's URL lapses (monotonic seconds)."""
    with _url_cache_lock:
        return [expires for _, expires in _url_cache.values()]


def _cache_key(filepath: Path, host: str, expiry_minutes: int) -> _CacheKey | None:
    """Build the cache key for this file, host, and retention period.

    Return None when the file cannot be inspected.
    """
    try:
        st = Path(filepath).stat()
    except OSError:
        return None
    return (str(Path(filepath).resolve()), st.st_size, st.st_mtime_ns, host, expiry_minutes)


def _cached_url(key: _CacheKey | None) -> str | None:
    if key is None:
        return None
    with _url_cache_lock:
        hit = _url_cache.get(key)
        if hit and hit[1] > time.time():
            return hit[0]
        if hit:  # lapsed — drop it
            _url_cache.pop(key, None)
    return None


def _drop_url(key: _CacheKey | None) -> None:
    if key is None:
        return
    with _url_cache_lock:
        _url_cache.pop(key, None)


def _store_url(key: _CacheKey | None, url: str, expiry_minutes: int) -> None:
    if key is None:
        return
    lifetime = max(expiry_minutes, 1) * 60
    good_until = time.time() + lifetime - min(_CACHE_MARGIN_MAX_S, lifetime * _CACHE_MARGIN_FRAC)
    with _url_cache_lock:
        now = time.time()
        for k in [k for k, (_, exp) in _url_cache.items() if exp <= now]:
            _url_cache.pop(k, None)
        if len(_url_cache) >= _URL_CACHE_MAX:  # still full — evict the soonest-to-expire
            _url_cache.pop(min(_url_cache, key=lambda k: _url_cache[k][1]), None)
        _url_cache[key] = (url, good_until)


def _host_order(resolved: UploadPrefs) -> list[str]:
    """The hosts to try, primary first, then the backup when it is a different host."""
    order: list[str] = [resolved["primary"]]
    backup = resolved.get("backup")
    if backup and backup != resolved["primary"]:
        order.append(backup)
    return order


def _reuse_cached(host: str, key: _CacheKey | None, filepath: Path) -> str | None:
    """The URL of a still-live earlier upload of this file, or None.

    The file is reused, never re-uploaded while it lives — but the link handed
    out is re-derived (tmpfiles' download links die after ~5 minutes) and
    re-checked, since Pollo charges for a job whose source URL it can't fetch.
    """
    cached = _cached_url(key)
    if not cached:
        return None
    try:
        url = _served_url(host, cached, filepath)
    except (ValueError, requests.RequestException) as exc:
        log.warning("%s: cached upload no longer served (%s), re-uploading", host, exc)
        _drop_url(key)
        return None
    log.info("%s: reused still-live upload, no re-upload: %s", host, url)
    return url


def _upload_fresh(host: str, key: _CacheKey | None, filepath: Path, resolved: UploadPrefs, expiry: int) -> str:
    """Upload the file to one host, remember it, and return its public URL."""
    stored = _dispatch(host, filepath, resolved)
    url = _served_url(host, stored, filepath)
    _store_url(key, stored, min(expiry, _FIXED_RETENTION_MIN.get(host, expiry)))
    log.info("%s: uploaded %s", host, url)
    return url


def upload_file(filepath: Path, prefs: UploadPrefs | None = None) -> str:
    """Upload a source file and return its public URL.

    Try the primary host before the backup. If omitted, ``prefs`` uses the
    current user's resolved preferences; a live cached URL is reused.
    """
    resolved = prefs if prefs is not None else current_upload_prefs()
    expiry = resolved.get("expiry_minutes", 60)
    order = _host_order(resolved)
    errors: list[str] = []
    for host in order:
        key = _cache_key(filepath, host, expiry)
        url = _reuse_cached(host, key, filepath)
        if url is None:
            try:
                url = _upload_fresh(host, key, filepath, resolved, expiry)
            except (ValueError, requests.RequestException) as exc:
                log.warning("%s failed (%s), trying the next host", host, exc)
                errors.append(f"{_HOST_LABEL.get(host, host)}: {exc}")
                continue
        _note_fallback(order, host, errors)
        return url
    raise ValueError("All upload hosts failed — " + "; ".join(errors))


_HOST_LABEL = {"litterbox": "Litterbox", "uguu": "uguu.se", "tmpfiles": "tmpfiles.org", "selfhost": "self-host"}
# Fallbacks during the current submit, so the provider can show the user that
# (and why) the backup host was used. Per thread: each chat turn runs on its own.
_notes = threading.local()


def take_upload_notes() -> list[str]:
    """Return and clear this thread's upload notes (backup-host fallbacks)."""
    notes = getattr(_notes, "items", [])
    _notes.items = []
    return notes


def _note_fallback(order: list[str], used: str, errors: list[str]) -> None:
    if used == order[0] or not errors:
        return
    note = f"Used backup host {_HOST_LABEL.get(used, used)} — " + "; ".join(errors)
    log.warning("%s", note)
    items = getattr(_notes, "items", [])
    if note not in items:
        items.append(note)
    _notes.items = items


def _served_url(host: str, stored: str, filepath: Path) -> str:
    """Turn a stored upload URL into a link to hand out now, and check it's served.

    tmpfiles stores its stable file-page URL; its ``dl/`` link is signed and
    expires about 5 minutes after the page is fetched, so a fresh one is
    derived each time.
    """
    url = _tmpfiles_direct_url(stored) if host == "tmpfiles" else stored
    _verify_served(host, url, filepath)
    return url


# A host can accept the upload and still not serve the file to a plain HTTP
# client — a temp host hands an interstitial page to anything that doesn't look
# like a browser, say. The provider then fetches HTML where a video should be
# and rejects it ("Invalid video_url") *after* charging for the job, so the URL
# is checked here instead, and a host that doesn't serve it falls through to
# the backup. Self-hosting is skipped: this instance can reach itself whatever
# the outside world sees.
_VERIFY_HOSTS = ("litterbox", "uguu", "tmpfiles")
_VERIFY_TIMEOUT = httpx.Timeout(15, connect=8)
_VERIFY_MAX_BYTES = 64 * 1024  # a ranged request for one byte: anything bigger is a host ignoring the range


def _verify_served(host: str, url: str, filepath: Path) -> None:
    if host not in _VERIFY_HOSTS:
        return
    try:
        resp = net_guard.get_public(
            net_guard.public_http,
            url,
            timeout=_VERIFY_TIMEOUT,
            headers={"Range": "bytes=0-0"},
            max_bytes=_VERIFY_MAX_BYTES,
        )
    except (httpx.HTTPError, net_guard.UnsafeURLError) as exc:
        raise HostedFileUnreachableError(exc) from exc
    content_type = (resp.headers.get("content-type") or "").split(";")[0].strip().lower()
    if resp.status_code not in (200, 206):
        raise HostedFileStatusError(resp.status_code)
    # Only an HTML answer is treated as wrong: hosts serve files as all sorts of
    # octet-stream/text types, and rejecting those would break working uploads.
    if content_type in ("text/html", "application/xhtml+xml"):
        raise HostedFileIsPageError(filepath.suffix)


def _dispatch(host: str, filepath: Path, prefs: UploadPrefs) -> str:
    expiry = prefs.get("expiry_minutes", 60)
    if host == "litterbox":
        return _upload_to_litterbox(filepath, expiry)
    if host == "tmpfiles":
        return _upload_to_tmpfiles(filepath, expiry)
    if host == "uguu":
        return upload_to_uguu(filepath)
    if host == "selfhost":
        return selfhost_url(filepath, prefs.get("selfhost_base", ""), ttl_seconds=expiry * 60)
    raise UnknownHostError(host)


def upload_to_uguu(filepath: Path) -> str:
    """Upload a file to uguu.se and return its direct URL.

    uguu keeps files for a fixed 3 hours and rejects anything over 128 MiB, so
    an oversized file fails here, before uploading, and falls to the backup.
    """
    size = filepath.stat().st_size
    if size > UGUU_MAX_BYTES:
        raise FileTooLargeForUguuError(size)
    try:
        with filepath.open("rb") as f:
            resp = requests.post(UGUU_URL, files={"files[]": (filepath.name, f)}, timeout=(8, 60))
    except requests.RequestException as exc:
        raise UploadFailedError("uguu.se", exc) from exc
    if resp.status_code != HTTPStatus.OK:
        raise _http_failure("uguu.se", resp)
    try:
        data = _UGUU_RESPONSE.validate_json(resp.text)
    except ValueError as exc:
        raise UploadUnexpectedReplyError("uguu.se", resp.text) from exc
    files = data.get("files")
    first = files[0] if isinstance(files, list) and files else None
    url = first.get("url") if isinstance(first, dict) else None
    if data.get("success") is not True or not isinstance(url, str) or not url.startswith("https://"):
        raise UploadRejectedError("uguu.se", data.get("description") or data)
    return url


def _http_failure(service: str, resp: requests.Response) -> UploadHttpError:
    return UploadHttpError(service, resp.status_code, resp.text)


def litterbox_time(expiry_minutes: int) -> str:
    """Litterbox's retention label (1h/12h/24h/72h) nearest to the request."""
    return _LITTERBOX_BUCKETS[min(_LITTERBOX_BUCKETS, key=lambda v: abs(v - expiry_minutes))]


def _upload_to_litterbox(filepath: Path, expiry_minutes: int = 60) -> str:
    """Upload a file to litterbox.catbox.moe and return the public URL.

    Fails fast (no retry) so VPN/Cloudflare blocks surface immediately.
    """
    try:
        with filepath.open("rb") as f:
            resp = requests.post(
                LITTERBOX_URL,
                data={"reqtype": "fileupload", "time": litterbox_time(expiry_minutes)},
                files={"fileToUpload": (filepath.name, f)},
                timeout=(8, 15),  # (connect, read) — read is server response time only, not upload duration
            )
    except requests.exceptions.Timeout as exc:
        log.warning("litterbox upload timed out (%s)", exc)
        raise LitterboxTimeoutError from exc
    except (requests.exceptions.SSLError, requests.exceptions.ConnectionError) as exc:
        log.warning("litterbox upload failed — %s: %s", type(exc).__name__, exc)
        raise UploadFailedError("Litterbox", exc) from exc
    if resp.status_code != HTTPStatus.OK or not resp.text.startswith("https://"):
        err = _http_failure("Litterbox", resp)
        log.warning("%s", err)
        raise err
    return resp.text.strip()


def _upload_to_tmpfiles(filepath: Path, expiry_minutes: int = 60) -> str:
    """Upload a file to tmpfiles.org and return its direct download URL.

    tmpfiles applies its own retention; the requested span is passed as a hint.
    """
    try:
        with filepath.open("rb") as f:
            resp = requests.post(
                TMPFILES_URL,
                data={"expire": expiry_minutes * 60},
                files={"file": (filepath.name, f)},
                timeout=(8, 30),
            )
        data = _TMPFILES_RESPONSE.validate_json(resp.text)
    except (requests.RequestException, ValueError) as exc:
        raise UploadRejectedError("tmpfiles.org", exc) from exc
    if resp.status_code != HTTPStatus.OK:
        raise _http_failure("tmpfiles.org", resp)
    if data.get("status") != "success":
        raise UploadRejectedError("tmpfiles.org", data)
    upload_data = data.get("data")
    url = upload_data.get("url") if isinstance(upload_data, Mapping) else None
    if not isinstance(url, str):
        raise TmpfilesNoUrlError
    # The stable file page, not the dl/ link: that one expires in ~5 minutes
    # (see _served_url, which derives a fresh one each time it's handed out).
    return url


def _tmpfiles_direct_url(page_url: str) -> str:
    """Extract tmpfiles.org's direct-download URL from the file page.

    The upload API omits the ``{timestamp}.{hash}`` segment required by ``dl/``.
    That segment is a signed expiry ~5 minutes after the page is fetched, so the
    link must be derived just before it's handed to a provider, never cached.
    """
    try:
        page = net_guard.get_public(
            net_guard.public_http, page_url, timeout=httpx.Timeout(30, connect=8), max_bytes=net_guard.MAX_PAGE_BYTES
        )
        page.raise_for_status()
    except (httpx.HTTPError, net_guard.UnsafeURLError) as exc:
        raise HostedFileUnreachableError(exc) from exc
    soup = BeautifulSoup(page.text, "html.parser")
    link = soup.find("a", class_="download") or soup.find("img", id="img_preview")
    raw_url = (link.get("href") or link.get("src")) if link else None
    direct_url = raw_url if isinstance(raw_url, str) else None
    if not direct_url:
        raise TmpfilesNoDirectLinkError(page_url)
    return direct_url

"""SSRF guard for server-side fetches of URLs we don't fully control.

A provider's API response can hand us a URL to download (e.g. an image the
model generated). Before fetching, confirm it's a public http(s) address so a
crafted response can't point the server at loopback, the cloud metadata
endpoint, or the LAN.

Three things make the check hold:

* The address that was checked is the address connected to. The host is resolved once, every answer must be
  public, and the request goes to that IP (with the real name as Host and for TLS), so a name that answers
  differently the second time (DNS rebinding) can't slip past.
* Every redirect hop goes through the same check; none is followed blindly.
* What comes back is read with a size cap, so a link to something enormous can't fill memory or the disk.
"""

import ipaddress
import socket
from collections.abc import Callable, Generator, Mapping
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx2

MAX_IMAGE_BYTES = 64 * 1024**2
MAX_VIDEO_BYTES = 2 * 1024**3
MAX_PAGE_BYTES = 2 * 1024**2
CHUNK = 1 << 16
DEFAULT_REDIRECTS = 3

# For fetches that have no client of their own: no credentials, no cookies, no redirect following
public_http = httpx2.Client(follow_redirects=False)


class UnsafeURLError(ValueError):
    """The URL is not a fetchable public http(s) address."""


class UnsupportedSchemeError(UnsafeURLError):
    """The URL is not http or https."""

    def __init__(self, scheme: str) -> None:
        """Name the scheme that was refused."""
        super().__init__(f"Unsupported URL scheme: {scheme!r}")


class MissingHostError(UnsafeURLError):
    """The URL has no host to connect to."""

    def __init__(self) -> None:
        """Build the fixed message."""
        super().__init__("URL has no host")


class UnresolvableHostError(UnsafeURLError):
    """The URL's host does not resolve."""

    def __init__(self, host: str, cause: Exception) -> None:
        """Name the host and why resolution failed."""
        super().__init__(f"Cannot resolve host {host!r}: {cause}")


class NonPublicAddressError(UnsafeURLError):
    """The URL's host resolves to a private, loopback or otherwise non-public address."""

    def __init__(self, host: str, ip: str) -> None:
        """Name the host and the address it resolved to."""
        super().__init__(f"Host {host!r} resolves to non-public address {ip}")


class ResponseTooLargeError(UnsafeURLError):
    """The answer is bigger than the most we will take for this kind of fetch."""

    def __init__(self, limit: int) -> None:
        """Give the cap."""
        super().__init__(f"Response larger than {limit // 1024**2} MB")


class TooManyRedirectsError(UnsafeURLError):
    """The redirect limit was reached before a final response."""

    def __init__(self) -> None:
        """Build the fixed message."""
        super().__init__("Too many redirects")


def _is_public_ip(ip: str) -> bool:
    """Whether `ip` is a globally routable address.

    `is_global` rules out private and loopback ranges, link-local (including the cloud metadata address),
    shared address space (100.64.0.0/10, which Tailscale and carrier NAT use), documentation and other
    reserved ranges, and multicast. An IPv6 address that wraps an IPv4 one is judged as that IPv4 address.
    """
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped
    return addr.is_global and not addr.is_multicast


def public_address(url: str) -> str:
    """The IP to connect to for `url`: it is http(s), has a host, and every address the host resolves to is public.

    Raises:
        UnsafeURLError: If the scheme, host, or any resolved address is unsafe.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise UnsupportedSchemeError(parsed.scheme)
    host = parsed.hostname
    if not host:
        raise MissingHostError
    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror as exc:
        raise UnresolvableHostError(host, exc) from exc
    addresses = [str(info[4][0]) for info in infos]
    for ip in addresses:
        if not _is_public_ip(ip):
            raise NonPublicAddressError(host, ip)
    return addresses[0]


def assert_public_url(url: str) -> None:
    """Require an HTTP(S) URL whose resolved addresses are all public.

    Raises:
        UnsafeURLError: If the scheme, host, or any resolved address is unsafe.
    """
    public_address(url)


@contextmanager
def open_public(
    client: httpx2.Client,
    url: str,
    *,
    timeout: float | httpx2.Timeout | None,
    headers: Mapping[str, str] | None = None,
    max_redirects: int = DEFAULT_REDIRECTS,
) -> Generator[httpx2.Response]:
    """Stream a GET of a public URL, checking and pinning the address on every redirect hop."""
    for _ in range(max_redirects + 1):
        target = httpx2.URL(url)
        ip = public_address(url)
        request_headers = {**(headers or {}), "Host": target.netloc.decode()}
        with client.stream(
            "GET",
            target.copy_with(host=ip),
            headers=request_headers,
            timeout=timeout,
            follow_redirects=False,
            extensions={"sni_hostname": target.host},
        ) as resp:
            if resp.is_redirect and "location" in resp.headers:
                url = urljoin(url, resp.headers["location"])
                continue
            yield resp
            return
    raise TooManyRedirectsError


def _read_capped(resp: httpx2.Response, max_bytes: int, sink: Callable[[bytes], object]) -> None:
    """Feed the body to `sink` a chunk at a time, refusing one bigger than `max_bytes`."""
    declared: str = resp.headers.get("content-length") or ""
    if declared.isdigit() and int(declared) > max_bytes:
        raise ResponseTooLargeError(max_bytes)
    total = 0
    for chunk in resp.iter_bytes(CHUNK):
        total += len(chunk)
        if total > max_bytes:
            raise ResponseTooLargeError(max_bytes)
        sink(chunk)


def get_public(
    client: httpx2.Client,
    url: str,
    *,
    timeout: float | httpx2.Timeout | None,
    headers: Mapping[str, str] | None = None,
    max_bytes: int = MAX_IMAGE_BYTES,
) -> httpx2.Response:
    """GET a public URL (each redirect target checked and pinned) and return the whole, size-capped answer.

    Raises:
        UnsafeURLError: If a URL is unsafe, the redirect limit is exceeded, or the answer is over `max_bytes`.
    """
    with open_public(client, url, timeout=timeout, headers=headers) as resp:
        chunks: list[bytes] = []
        _read_capped(resp, max_bytes, chunks.append)
        kept = {k: v for k, v in resp.headers.items() if k.lower() not in ("content-encoding", "content-length")}
        return httpx2.Response(resp.status_code, headers=kept, content=b"".join(chunks), request=resp.request)


def download_public(
    client: httpx2.Client,
    url: str,
    dest: Path,
    *,
    timeout: float | httpx2.Timeout | None,
    max_bytes: int = MAX_VIDEO_BYTES,
) -> None:
    """Download a public URL to `dest` (through a .part file, so a failed download leaves nothing at `dest`).

    Raises:
        UnsafeURLError: If a URL is unsafe or the file is over `max_bytes`.
        httpx2.HTTPError: On an error status or a network failure.
    """
    tmp = dest.with_suffix(dest.suffix + ".part")
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open_public(client, url, timeout=timeout) as resp, tmp.open("wb") as out:
            resp.raise_for_status()
            _read_capped(resp, max_bytes, out.write)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    tmp.replace(dest)

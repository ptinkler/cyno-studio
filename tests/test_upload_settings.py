"""Per-user source-media hosting: prefs resolution, host dispatch order, and.

the signed self-host serving route.
"""

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import NoReturn

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import web.api as api_mod
from tests.errors import NoRouteError
from tests.jsonpath import seq, text
from tests.stubs import stub
from web import image_hosts, public_media, upload_settings
from web.core import config
from web.core.metadata.models import User
from web.image_hosts import HostedFileStatusError, LitterboxTimeoutError
from web.upload_settings import UploadPrefs


def _same_page(page: str) -> str:
    """Stand in for the tmpfiles page lookup: hand the stored URL straight back."""
    return page


def _no_upload_check(host: str, url: str, filepath: Path) -> str:
    """Skip deriving and checking the served link; return the stored URL."""
    return url


def _no_verify(host: str, url: str, filepath: Path) -> None:
    """Skip the served-file check."""


def _prefs(primary: str, backup: str | None, expiry_minutes: int = 60, selfhost_base: str = "") -> UploadPrefs:
    """Upload preferences with the given hosts and expiry."""
    return {"primary": primary, "backup": backup, "expiry_minutes": expiry_minutes, "selfhost_base": selfhost_base}


def _user(upload_prefs_json: str | None = None) -> User:
    """A user whose stored upload preferences are ``upload_prefs_json``."""
    return User(id="u1", upload_prefs_json=upload_prefs_json)


@dataclass
class _Reply:
    """A stand-in HTTP reply: status, body text and headers, with a no-op ``close``."""

    status_code: int
    text: str = ""
    headers: dict[str, str] = field(default_factory=dict)

    def close(self) -> None:
        """Release the connection (nothing is held)."""


def _served(status: int = 200, content_type: str = "video/mp4") -> _Reply:
    """A reply to the served-file check, with the given status and content type."""
    return _Reply(status, headers={"content-type": content_type})


class TestPrefsResolution:
    """Tests for prefs resolution."""

    def test_default_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that default from env."""
        monkeypatch.setenv("UPLOAD_PRIMARY", "tmpfiles")
        monkeypatch.setenv("UPLOAD_BACKUP", "litterbox")
        monkeypatch.setenv("UPLOAD_EXPIRY_MINUTES", "1440")
        d = upload_settings.default_prefs()
        assert d["primary"] == "tmpfiles"
        assert d["backup"] == "litterbox"
        assert d["expiry_minutes"] == 1440

    def test_unset_user_gets_default(self) -> None:
        """Test that unset user gets default."""
        assert upload_settings.resolve_prefs(_user())["primary"] == upload_settings.default_prefs()["primary"]

    def test_stored_overrides_default(self) -> None:
        """Test that stored overrides default."""
        prefs = upload_settings.resolve_prefs(_user('{"primary": "selfhost", "selfhost_base": "https://x.test"}'))
        assert prefs["primary"] == "selfhost"
        assert prefs["selfhost_base"] == "https://x.test"

    def test_invalid_host_and_expiry_dropped(self) -> None:
        """Test that invalid host and expiry dropped."""
        prefs = upload_settings.resolve_prefs(_user('{"primary": "nope", "expiry_minutes": 7}'))
        d = upload_settings.default_prefs()
        assert prefs["primary"] == d["primary"]
        assert prefs["expiry_minutes"] == d["expiry_minutes"]

    def test_backup_equal_to_primary_becomes_none(self) -> None:
        """Test that backup equal to primary becomes none."""
        prefs = upload_settings.resolve_prefs(_user('{"primary": "litterbox", "backup": "litterbox"}'))
        assert prefs["backup"] is None

    def test_corrupt_blob_falls_back(self) -> None:
        """Test that corrupt blob falls back."""
        assert upload_settings.resolve_prefs(_user("not json"))["primary"] == upload_settings.default_prefs()["primary"]


@pytest.fixture
def _no_url_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """Dispatch/cache tests stub the hosts themselves, so there's no real URL.

    to fetch — the served-file check is exercised in TestServedCheck.
    """
    monkeypatch.setattr(image_hosts, "_verify_served", _no_verify)
    monkeypatch.setattr(image_hosts, "_tmpfiles_direct_url", _same_page)


@pytest.mark.usefixtures("_no_url_check")
class TestDispatchOrder:
    """Tests for dispatch order."""

    def test_primary_then_backup(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that primary then backup."""
        calls: list[str] = []

        def litterbox(p: Path, e: int = 60) -> str:
            calls.append("litterbox")
            return "L"

        def tmpfiles(p: Path, e: int = 60) -> str:
            calls.append("tmpfiles")
            return "T"

        monkeypatch.setattr(image_hosts, "_upload_to_litterbox", litterbox)
        monkeypatch.setattr(image_hosts, "_upload_to_tmpfiles", tmpfiles)
        prefs = _prefs("tmpfiles", "litterbox")
        assert image_hosts.upload_file(Path("f"), prefs) == "T"
        assert calls == ["tmpfiles"]

    def test_falls_back_to_backup_on_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that falls back to backup on failure."""

        def boom(p: Path, e: int = 60) -> NoReturn:
            raise ValueError("down")

        monkeypatch.setattr(image_hosts, "_upload_to_tmpfiles", boom)
        monkeypatch.setattr(image_hosts, "_upload_to_litterbox", stub(lambda: "L"))
        prefs = _prefs("tmpfiles", "litterbox")
        assert image_hosts.upload_file(Path("f"), prefs) == "L"

    def test_all_fail_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that all fail raises."""

        def boom(p: Path, e: int = 60) -> NoReturn:
            raise ValueError("x")

        monkeypatch.setattr(image_hosts, "_upload_to_tmpfiles", boom)
        prefs = _prefs("tmpfiles", None)
        with pytest.raises(ValueError, match="All upload hosts failed"):
            image_hosts.upload_file(Path("f"), prefs)

    def test_litterbox_expiry_bucketed(self) -> None:
        """Test that litterbox expiry bucketed."""
        assert image_hosts.litterbox_time(70) == "1h"
        assert image_hosts.litterbox_time(4000) == "72h"


@pytest.mark.usefixtures("_no_url_check")
class TestUploadCache:
    """Tests for upload cache."""

    def test_reuses_url_without_reuploading(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that reuses url without reuploading."""
        image_hosts.clear_url_cache()
        f = tmp_path / "clip.mp4"
        f.write_bytes(b"video-bytes")
        calls: list[Path] = []

        def upload(p: Path, e: int = 60) -> str:
            calls.append(p)
            return "https://host/x"

        monkeypatch.setattr(image_hosts, "_upload_to_litterbox", upload)
        prefs = _prefs("litterbox", None)
        assert image_hosts.upload_file(f, prefs) == "https://host/x"
        assert image_hosts.upload_file(f, prefs) == "https://host/x"  # retry: served from cache
        assert len(calls) == 1  # uploaded only once

    def test_editing_the_file_forces_reupload(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that editing the file forces reupload."""
        image_hosts.clear_url_cache()
        f = tmp_path / "clip.mp4"
        f.write_bytes(b"v1")
        calls: list[Path] = []

        def upload(p: Path, e: int = 60) -> str:
            calls.append(p)
            return f"https://host/{len(calls)}"

        monkeypatch.setattr(image_hosts, "_upload_to_litterbox", upload)
        prefs = _prefs("litterbox", None)
        assert image_hosts.upload_file(f, prefs) == "https://host/1"
        f.write_bytes(b"different-bytes-and-size")  # content/size change invalidates the key
        assert image_hosts.upload_file(f, prefs) == "https://host/2"
        assert len(calls) == 2

    def test_expired_entry_is_not_reused(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that expired entry is not reused."""
        image_hosts.clear_url_cache()
        f = tmp_path / "clip.mp4"
        f.write_bytes(b"bytes")
        calls: list[Path] = []

        def upload(p: Path, e: int = 60) -> str:
            calls.append(p)
            return f"https://host/{len(calls)}"

        monkeypatch.setattr(image_hosts, "_upload_to_litterbox", upload)
        prefs = _prefs("litterbox", None)
        assert image_hosts.upload_file(f, prefs) == "https://host/1"
        # Force the one cached entry to look lapsed, then confirm a fresh upload.
        image_hosts.expire_cached_urls()
        assert image_hosts.upload_file(f, prefs) == "https://host/2"
        assert len(calls) == 2


class TestCacheLifetimeAndRecheck:
    """Retries reuse the upload but must never hand Pollo a dead link."""

    def test_tmpfiles_cached_for_its_fixed_hour_not_the_requested_span(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that tmpfiles is cached for 60 minutes even when 24h is requested."""
        image_hosts.clear_url_cache()
        monkeypatch.setattr(image_hosts, "_served_url", _no_upload_check)
        f = tmp_path / "clip.mp4"
        f.write_bytes(b"v")

        def upload(p: Path, e: int = 60) -> str:
            return "https://tmpfiles.org/abc/x.mp4"

        monkeypatch.setattr(image_hosts, "_upload_to_tmpfiles", upload)
        image_hosts.upload_file(f, _prefs("tmpfiles", None, 1440))
        (good_until,) = image_hosts.cached_url_expiries()
        assert good_until <= time.time() + 60 * 60

    def test_tmpfiles_retry_reuses_upload_with_a_fresh_download_link(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The dl/ link is signed for ~5 min: each hand-out derives a new one, without re-uploading."""
        image_hosts.clear_url_cache()
        monkeypatch.setattr(image_hosts, "_verify_served", _no_verify)
        f = tmp_path / "clip.mp4"
        f.write_bytes(b"v")
        uploads: list[Path] = []
        pages: list[str] = []

        def upload(p: Path, e: int = 60) -> str:
            uploads.append(p)
            return "https://tmpfiles.org/abc/x.mp4"

        def direct(page: str) -> str:
            pages.append(page)
            return f"https://tmpfiles.org/dl/{len(pages)}.sig/abc/x.mp4"

        monkeypatch.setattr(image_hosts, "_upload_to_tmpfiles", upload)
        monkeypatch.setattr(image_hosts, "_tmpfiles_direct_url", direct)
        prefs = _prefs("tmpfiles", None)
        assert image_hosts.upload_file(f, prefs) == "https://tmpfiles.org/dl/1.sig/abc/x.mp4"
        assert image_hosts.upload_file(f, prefs) == "https://tmpfiles.org/dl/2.sig/abc/x.mp4"
        assert len(uploads) == 1  # uploaded once
        assert pages == ["https://tmpfiles.org/abc/x.mp4"] * 2  # the stable page is what's cached

    def test_cached_upload_that_stopped_serving_is_reuploaded(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that a cached upload failing the served check triggers a fresh upload."""
        image_hosts.clear_url_cache()
        f = tmp_path / "clip.mp4"
        f.write_bytes(b"v")
        calls: list[Path] = []
        dead: set[str] = set()

        def upload(p: Path, e: int = 60) -> str:
            calls.append(p)
            return f"https://litter/{len(calls)}.mp4"

        def check(host: str, url: str, filepath: Path) -> None:
            if url in dead:
                raise HostedFileStatusError(404)

        monkeypatch.setattr(image_hosts, "_upload_to_litterbox", upload)
        monkeypatch.setattr(image_hosts, "_verify_served", check)
        prefs = _prefs("litterbox", None)
        assert image_hosts.upload_file(f, prefs) == "https://litter/1.mp4"
        assert image_hosts.upload_file(f, prefs) == "https://litter/1.mp4"  # still live: reused
        dead.add("https://litter/1.mp4")
        assert image_hosts.upload_file(f, prefs) == "https://litter/2.mp4"
        assert len(calls) == 2


class TestUguu:
    """uguu.se: anonymous, raw-file URLs, 128 MiB cap, fixed 3h retention."""

    def test_upload_returns_the_file_url(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that a successful upload returns uguu's direct file URL."""
        f = tmp_path / "clip.mov"
        f.write_bytes(b"v")
        sent: list[str] = []

        def post(url: str, **kw: object) -> _Reply:
            sent.append(url)
            return _Reply(200, '{"success": true, "files": [{"url": "https://h.uguu.se/AbCd.mov"}]}')

        monkeypatch.setattr(image_hosts.requests, "post", post)
        assert image_hosts.upload_to_uguu(f) == "https://h.uguu.se/AbCd.mov"
        assert sent == [image_hosts.UGUU_URL]

    def test_oversized_file_is_refused_before_uploading(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that a file over 128 MiB fails fast, without sending anything."""
        f = tmp_path / "big.mov"
        f.write_bytes(b"v")
        monkeypatch.setattr(image_hosts, "UGUU_MAX_BYTES", 0)

        def post(url: str, **kw: object) -> NoReturn:
            pytest.fail("should not upload")

        monkeypatch.setattr(image_hosts.requests, "post", post)
        with pytest.raises(ValueError, match="128 MiB"):
            image_hosts.upload_to_uguu(f)

    def test_error_reply_is_a_failure(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that an unsuccessful reply raises, so the backup host is tried."""
        f = tmp_path / "clip.mov"
        f.write_bytes(b"v")

        def post(url: str, **kw: object) -> _Reply:
            return _Reply(200, '{"success": false, "errorcode": 400, "description": "No input file(s)"}')

        monkeypatch.setattr(image_hosts.requests, "post", post)
        with pytest.raises(ValueError, match="No input file"):
            image_hosts.upload_to_uguu(f)

    def test_cached_for_its_fixed_three_hours(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that a uguu URL isn't reused past its 3h life, whatever span is requested."""
        image_hosts.clear_url_cache()
        monkeypatch.setattr(image_hosts, "_served_url", _no_upload_check)
        f = tmp_path / "clip.mov"
        f.write_bytes(b"v")

        def upload(p: Path) -> str:
            return "https://h.uguu.se/AbCd.mov"

        monkeypatch.setattr(image_hosts, "upload_to_uguu", upload)
        assert image_hosts.upload_file(f, _prefs("uguu", "tmpfiles", 4320)) == "https://h.uguu.se/AbCd.mov"
        (good_until,) = image_hosts.cached_url_expiries()
        assert good_until <= time.time() + 3 * 60 * 60


class TestFallbackNotice:
    """Falling back to the backup host is reported, with the primary's error."""

    def test_fallback_is_noted_with_reason(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that a backup-host upload leaves a note naming the primary's failure."""
        image_hosts.clear_url_cache()
        image_hosts.take_upload_notes()
        monkeypatch.setattr(image_hosts, "_served_url", _no_upload_check)
        f = tmp_path / "clip.mp4"
        f.write_bytes(b"v")

        def boom(p: Path, e: int = 60) -> str:
            raise LitterboxTimeoutError

        def upload(p: Path, e: int = 60) -> str:
            return "https://tmpfiles.org/abc/x.mp4"

        monkeypatch.setattr(image_hosts, "_upload_to_litterbox", boom)
        monkeypatch.setattr(image_hosts, "_upload_to_tmpfiles", upload)
        image_hosts.upload_file(f, _prefs("litterbox", "tmpfiles"))
        (note,) = image_hosts.take_upload_notes()
        assert "tmpfiles.org" in note
        assert "Litterbox upload timed out" in note
        assert image_hosts.take_upload_notes() == []  # taken once

    def test_primary_success_leaves_no_note(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that using the primary host leaves no note."""
        image_hosts.clear_url_cache()
        image_hosts.take_upload_notes()
        monkeypatch.setattr(image_hosts, "_served_url", _no_upload_check)
        f = tmp_path / "clip.mp4"
        f.write_bytes(b"v")

        def upload(p: Path, e: int = 60) -> str:
            return "https://litter/x.mp4"

        monkeypatch.setattr(image_hosts, "_upload_to_litterbox", upload)
        image_hosts.upload_file(f, _prefs("litterbox", "tmpfiles"))
        assert image_hosts.take_upload_notes() == []


class TestServedCheck:
    """A host can take the upload and still not serve the file to a plain.

    client; the provider would then be charged for fetching a web page.
    """

    @pytest.fixture(autouse=True)
    def _stub_tmpfiles_page(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The tmpfiles page lookup is its own request; these tests cover only the served check."""
        monkeypatch.setattr(image_hosts, "_tmpfiles_direct_url", _same_page)

    def test_html_answer_falls_through_to_the_backup(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that html answer falls through to the backup."""
        image_hosts.clear_url_cache()
        f = tmp_path / "clip.mp4"
        f.write_bytes(b"v")
        monkeypatch.setattr(image_hosts, "_upload_to_tmpfiles", stub(lambda: "https://tmp/x.mp4"))
        monkeypatch.setattr(image_hosts, "_upload_to_litterbox", stub(lambda: "https://litter/x.mp4"))

        def get(url: str, **kw: object) -> _Reply:
            return _served(content_type="text/html" if "tmp/" in url else "video/mp4")

        monkeypatch.setattr(image_hosts.requests, "get", get)
        prefs = _prefs("tmpfiles", "litterbox")
        assert image_hosts.upload_file(f, prefs) == "https://litter/x.mp4"

    def test_unreachable_url_is_not_handed_on(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that unreachable url is not handed on."""
        image_hosts.clear_url_cache()
        f = tmp_path / "clip.mp4"
        f.write_bytes(b"v")
        monkeypatch.setattr(image_hosts, "_upload_to_tmpfiles", stub(lambda: "https://tmp/x.mp4"))

        def boom(url: str, **kw: object) -> NoReturn:
            raise NoRouteError

        monkeypatch.setattr(image_hosts.requests, "get", boom)
        prefs = _prefs("tmpfiles", None)
        with pytest.raises(ValueError, match="All upload hosts failed"):
            image_hosts.upload_file(f, prefs)

    def test_a_served_file_passes(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that a served file passes."""
        image_hosts.clear_url_cache()
        f = tmp_path / "clip.mp4"
        f.write_bytes(b"v")
        monkeypatch.setattr(image_hosts, "_upload_to_tmpfiles", stub(lambda: "https://tmp/x.mp4"))
        monkeypatch.setattr(image_hosts.requests, "get", stub(lambda: _served(206, "application/octet-stream")))
        prefs = _prefs("tmpfiles", None)
        assert image_hosts.upload_file(f, prefs) == "https://tmp/x.mp4"

    def test_selfhost_is_not_checked(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that selfhost is not checked."""
        image_hosts.clear_url_cache()
        f = tmp_path / "clip.mp4"
        f.write_bytes(b"v")
        calls: list[str] = []

        def get(url: str, **kw: object) -> _Reply:
            calls.append(url)
            return _served()

        monkeypatch.setattr(image_hosts.requests, "get", get)
        # patch where image_hosts looks the name up, not where it is defined
        monkeypatch.setattr(image_hosts, "selfhost_url", stub(lambda: "https://my.box/t"))
        prefs = _prefs("selfhost", None, selfhost_base="https://my.box")
        assert image_hosts.upload_file(f, prefs) == "https://my.box/t"
        assert calls == []


class TestSelfHost:
    """Tests for self host."""

    def test_selfhost_url_requires_base(self, tmp_path: Path) -> None:
        """Test that selfhost url requires base."""
        f = tmp_path / "a.bin"
        f.write_bytes(b"x")
        with pytest.raises(ValueError, match="public base URL"):
            public_media.selfhost_url(f, "", ttl_seconds=60)

    def test_token_round_trip_and_serve(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that token round trip and serve."""
        monkeypatch.setattr(config, "ROOT_DIR", tmp_path)
        media = tmp_path / "chat" / "conv1"
        media.mkdir(parents=True)
        f = media / "clip.mp4"
        f.write_bytes(b"hello")
        url = public_media.selfhost_url(f, "https://my.box", ttl_seconds=120)
        token = url.rsplit("/", 1)[1]
        client = TestClient(_app())
        r = client.get(f"/api/public-media/{token}")
        assert r.status_code == 200
        assert r.content == b"hello"

    def test_serves_from_character_refs_root(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Character reference images (ROOT_DIR/characters) are a valid Pollo
        # image-ref source, so the self-host route must serve them too.
        """Test that serves from character refs root."""
        monkeypatch.setattr(config, "ROOT_DIR", tmp_path)
        chars = tmp_path / "characters" / "7"
        chars.mkdir(parents=True)
        f = chars / "face.png"
        f.write_bytes(b"png")
        url = public_media.selfhost_url(f, "https://my.box", ttl_seconds=120)
        token = url.rsplit("/", 1)[1]
        assert TestClient(_app()).get(f"/api/public-media/{token}").content == b"png"

    def test_expired_token_404(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that expired token 404."""
        monkeypatch.setattr(config, "ROOT_DIR", tmp_path)
        media = tmp_path / "chat"
        media.mkdir(parents=True)
        f = media / "clip.mp4"
        f.write_bytes(b"hi")
        token = public_media.sign_media_token(f, ttl_seconds=-1)  # already expired
        assert TestClient(_app()).get(f"/api/public-media/{token}").status_code == 404

    def test_tampered_token_404(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that tampered token 404."""
        monkeypatch.setattr(config, "ROOT_DIR", tmp_path)
        (tmp_path / "chat").mkdir(parents=True)
        f = tmp_path / "chat" / "clip.mp4"
        f.write_bytes(b"hi")
        token = public_media.sign_media_token(f, ttl_seconds=120)[:-2] + "zz"
        assert TestClient(_app()).get(f"/api/public-media/{token}").status_code == 404

    def test_out_of_bounds_path_404(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # A validly-signed token for a file outside the media roots must not serve.
        """Test that out of bounds path 404."""
        monkeypatch.setattr(config, "ROOT_DIR", tmp_path)
        (tmp_path / "chat").mkdir(parents=True)
        secret = tmp_path / "secret.env"
        secret.write_bytes(b"KEY=1")
        token = public_media.sign_media_token(secret, ttl_seconds=120)
        assert TestClient(_app()).get(f"/api/public-media/{token}").status_code == 404


class TestApi:
    """Tests for api."""

    def test_get_returns_defaults_and_meta(self) -> None:
        """Test that get returns defaults and meta."""
        r = TestClient(_app()).get("/api/settings/uploads")
        assert r.status_code == 200
        assert text(r, "prefs", "primary") in upload_settings.HOSTS
        assert "litterbox" in seq(r, "hosts")
        assert seq(r, "expiry_options") == list(upload_settings.EXPIRY_OPTIONS)


def _app() -> FastAPI:
    """The application under test."""
    return api_mod.app

"""Signed, expiring links for a provider to fetch a local file."""

import base64
import hashlib
import hmac
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from web.auth.session import USER_COOKIE, make_user_session, resolve_user_session, user_secret
from web.core import config
from web.media import public

pytest_plugins = ["tests.api_fixtures"]


@pytest.fixture
def media_file() -> Path:
    """A file in a chat's folder."""
    folder = config.ROOT_DIR / "chat" / "c1"
    folder.mkdir(parents=True)
    file = folder / "pic.png"
    file.write_bytes(b"png")
    return file


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _forge(relative: str, key: bytes, ttl: int = 60) -> str:
    payload = f"{_b64(relative.encode())}.{int(time.time()) + ttl}"
    return f"{payload}.{_b64(hmac.new(key, payload.encode(), hashlib.sha256).digest())}"


class TestToken:
    """What a link will and won't serve."""

    def test_serves_the_file(self, client: TestClient, media_file: Path) -> None:
        """A fresh link returns the file without a login."""
        token = public.sign_media_token(media_file, 60)
        r = client.get(f"/api/public-media/{token}")
        assert r.status_code == 200
        assert r.content == b"png"

    def test_the_link_does_not_show_where_the_data_folder_is(self, media_file: Path) -> None:
        """The provider that is handed the link learns the file's name in the data folder, not the server's layout."""
        token = public.sign_media_token(media_file, 60)
        path = base64.urlsafe_b64decode(token.split(".")[0] + "==").decode()
        assert path == "chat/c1/pic.png"
        assert str(config.ROOT_DIR) not in path

    def test_expired_links_stop_working(self, client: TestClient, media_file: Path) -> None:
        """A link is good for its lifetime."""
        token = public.sign_media_token(media_file, -1)
        assert client.get(f"/api/public-media/{token}").status_code == 404

    def test_a_changed_path_is_refused(self, client: TestClient, media_file: Path) -> None:
        """The path is covered by the signature."""
        payload, exp, sig = public.sign_media_token(media_file, 60).split(".")
        other = _b64(b"chat/c1/other.png")
        assert client.get(f"/api/public-media/{other}.{exp}.{sig}").status_code == 404
        assert payload

    def test_a_file_outside_the_media_folders_is_refused(self, client: TestClient, media_file: Path) -> None:
        """Even a correctly signed link can only reach the chat, character and library folders."""
        (config.ROOT_DIR / "secret.txt").write_text("x")
        token = _forge("secret.txt", public.signing_key("public-media"))
        assert client.get(f"/api/public-media/{token}").status_code == 404
        assert media_file.exists()


class TestKeysAreSeparate:
    """A signature made for one purpose is no good for another."""

    def test_a_login_key_signature_does_not_open_a_file(self, client: TestClient, media_file: Path) -> None:
        """Signed with the key that signs login cookies: refused."""
        token = _forge("chat/c1/pic.png", user_secret())
        assert client.get(f"/api/public-media/{token}").status_code == 404

    def test_a_media_link_is_not_a_login(self, media_file: Path) -> None:
        """Handing a media link to a login check gets nobody in."""
        assert resolve_user_session(public.sign_media_token(media_file, 60)) is None

    def test_a_login_cookie_is_not_a_media_link(self, client: TestClient, media_file: Path) -> None:
        """And the other way."""
        assert client.get(f"/api/public-media/{make_user_session('abc')}").status_code == 404
        assert USER_COOKIE

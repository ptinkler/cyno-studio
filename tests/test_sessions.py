"""Login cookies: signed, expiring, and revocable by raising the user's session version."""

import base64
import hashlib
import hmac
import time

import pytest
from fastapi.testclient import TestClient

import web.api as api_mod
import web.auth.users as auth_users
from web.auth.session import USER_COOKIE, SessionClaim, make_user_session, resolve_user_session, user_secret
from web.auth.users import current_user, require_user
from web.core.metadata import MetadataDB

pytest_plugins = ["tests.api_fixtures"]


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _signed(payload: str) -> str:
    return f"{payload}.{_b64(hmac.new(user_secret(), payload.encode(), hashlib.sha256).digest())}"


class TestCookie:
    """What a cookie says, and what makes it worthless."""

    def test_carries_the_user_and_version(self) -> None:
        """Both come back out of a valid cookie."""
        assert resolve_user_session(make_user_session("abc", 3)) == SessionClaim("abc", 3)

    def test_a_cookie_made_before_versions_counts_as_version_zero(self) -> None:
        """Existing logins (`<id>.<expiry>.<signature>`) keep working until a version is raised."""
        old = _signed(f"abc.{int(time.time()) + 60}")
        assert resolve_user_session(old) == SessionClaim("abc", 0)

    def test_the_version_cannot_be_edited(self) -> None:
        """It is covered by the signature: lowering it to dodge a revocation fails."""
        user, _version, exp, sig = make_user_session("abc", 2).split(".")
        assert resolve_user_session(f"{user}.0.{exp}.{sig}") is None

    def test_expired_and_malformed_cookies_are_refused(self) -> None:
        """Past its expiry, wrong shape, or nothing."""
        assert resolve_user_session(_signed(f"abc.1.{int(time.time()) - 1}")) is None
        assert resolve_user_session("abc") is None
        assert resolve_user_session("a.b.c.d.e") is None
        assert resolve_user_session(None) is None


class TestRevocation:
    """Raising the user's version signs every earlier cookie out."""

    def test_an_old_cookie_stops_working(self, db: MetadataDB, monkeypatch: pytest.MonkeyPatch) -> None:
        """The cookie of a version that has been replaced no longer finds the user."""
        monkeypatch.setattr(auth_users, "get_db", lambda: db)
        user = db.ensure_admin("a@x.com")
        old = make_user_session(user.id, user.session_version)
        assert current_user(old) is not None
        new_version = db.bump_session_version(user.id)
        assert current_user(old) is None
        assert current_user(make_user_session(user.id, new_version)) is not None

    def test_a_new_password_signs_the_other_devices_out(self, db: MetadataDB) -> None:
        """Setting a password for an account that already had one ends its sessions; the first one doesn't."""
        first = db.create_local_admin("a@x.com", "hash-1")
        assert first.session_version == 0
        again = db.create_local_admin("a@x.com", "hash-2")
        assert again.session_version == 1

    def test_unknown_user(self, db: MetadataDB) -> None:
        """Nothing to raise for an id that isn't a user."""
        assert db.bump_session_version("nobody") == 0


class TestSignOutOthers:
    """The endpoint behind "Sign out other devices"."""

    def test_raises_the_version_and_keeps_this_device_signed_in(self, client: TestClient, db: MetadataDB) -> None:
        """The reply sets a cookie at the new version; the old one is dead."""
        user = db.ensure_admin("a@x.com")
        api_mod.app.dependency_overrides[require_user] = lambda: user
        try:
            r = client.post("/api/auth/logout-others")
        finally:
            api_mod.app.dependency_overrides.clear()
        assert r.status_code == 200
        cookie = r.cookies[USER_COOKIE]
        assert resolve_user_session(cookie) == SessionClaim(user.id, 1)
        stored = db.get_user(user.id)
        assert stored is not None
        assert stored.session_version == 1

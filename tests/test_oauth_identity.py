"""An OAuth account is the provider plus the provider's user id; email only joins sign-ins it can vouch for."""

import asyncio
from typing import cast

import pytest
from fastapi.testclient import TestClient

from web.auth import oauth, oauth_routes
from web.auth.users import admit
from web.core.metadata import MetadataDB
from web.types import JsonValue

pytest_plugins = ["tests.api_fixtures"]


class TestAdmit:
    """Who may sign in, with or without an email."""

    def test_an_email_account_follows_the_email_lists(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Unchanged: ALLOWED_EMAILS and ADMIN_EMAILS."""
        monkeypatch.setenv("ADMIN_EMAILS", "boss@x.com")
        monkeypatch.setenv("ALLOWED_EMAILS", "friend@x.com")
        assert admit("friend@x.com", is_first_user=False) == (True, False)
        assert admit("boss@x.com", is_first_user=False) == (True, True)
        assert admit("stranger@x.com", is_first_user=False) == (False, False)

    def test_no_email_needs_the_id_listed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An X user gets in when `x:<id>` is in ALLOWED_OAUTH_IDS, and not otherwise."""
        monkeypatch.setenv("ADMIN_EMAILS", "boss@x.com")
        monkeypatch.setenv("ALLOWED_OAUTH_IDS", "x:111, google:abc")
        assert admit(None, is_first_user=False, identity="x:111") == (True, False)
        assert admit(None, is_first_user=False, identity="x:222") == (False, False)

    def test_ids_are_case_sensitive_and_exact(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """`x:111` doesn't admit `x:1111` or `X:111`."""
        monkeypatch.setenv("ALLOWED_OAUTH_IDS", "x:111")
        assert admit(None, is_first_user=False, identity="x:1111") == (False, False)
        assert admit(None, is_first_user=False, identity="X:111") == (False, False)

    def test_open_signup_admits_anyone(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """OPEN_SIGNUP applies with or without an email."""
        monkeypatch.setenv("OPEN_SIGNUP", "true")
        assert admit(None, is_first_user=False, identity="x:1") == (True, False)

    def test_nothing_to_go_on(self) -> None:
        """No email and no id: refused."""
        assert admit(None, is_first_user=True) == (False, False)

    def test_the_first_user_still_bootstraps_when_nothing_is_configured(self) -> None:
        """Fail-closed afterwards: only the very first sign-in, and only with no lists at all."""
        assert admit(None, is_first_user=True, identity="x:1") == (True, True)
        assert admit(None, is_first_user=False, identity="x:2") == (False, False)

    def test_configured_lists_stop_the_bootstrap(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """With ADMIN_EMAILS set, an email-less first user is not let in as admin."""
        monkeypatch.setenv("ADMIN_EMAILS", "boss@x.com")
        assert admit(None, is_first_user=True, identity="x:1") == (False, False)


class TestUpsert:
    """Finding the account."""

    def _x(self, sub: str, name: str = "Alice") -> dict[str, str | None]:
        return {"provider": "x", "sub": sub, "email": None, "name": name, "avatar": None}

    def test_an_x_user_has_no_email_and_is_found_by_id(self, db: MetadataDB) -> None:
        """First sign-in creates the account without an email; the second finds it."""
        first = db.upsert_oauth_user(self._x("1"))
        again = db.upsert_oauth_user(self._x("1", name="Alice B"))
        assert first.email is None
        assert again.id == first.id
        assert again.name == "Alice B"

    def test_a_handle_that_changes_hands_does_not_reach_the_old_account(self, db: MetadataDB) -> None:
        """Different X user id, same name: a new, separate account."""
        old = db.upsert_oauth_user(self._x("1", name="@alice"))
        new = db.upsert_oauth_user(self._x("2", name="@alice"))
        assert new.id != old.id

    def test_email_less_accounts_coexist(self, db: MetadataDB) -> None:
        """The unique email allows any number of nulls."""
        ids = {db.upsert_oauth_user(self._x(str(n))).id for n in range(3)}
        assert len(ids) == 3

    def test_a_verified_email_joins_a_second_sign_in_to_the_account(self, db: MetadataDB) -> None:
        """Google with the address of the local admin lands in that account."""
        admin = db.create_local_admin("a@x.com", "hash")
        google = db.upsert_oauth_user(
            {"provider": "google", "sub": "g1", "email": "a@x.com", "name": "A", "avatar": None}
        )
        assert google.id == admin.id
        assert google.password_hash == admin.password_hash

    def test_an_email_less_sign_in_never_matches_by_email(self, db: MetadataDB) -> None:
        """No email, no linking: an X user can't land in an email account."""
        admin = db.create_local_admin("a@x.com", "hash")
        x = db.upsert_oauth_user(self._x("9", name="a@x.com"))
        assert x.id != admin.id


class FakeClient:
    """Stands in for the X client."""

    async def get(self, url: str, *, token: dict[str, JsonValue]) -> "FakeResponse":
        """The users/me answer."""
        assert token == {}
        assert url.startswith("users/me")
        return FakeResponse()


class FakeResponse:
    """What X's users/me returns."""

    def json(self) -> dict[str, JsonValue]:
        """The document."""
        return {
            "data": {"id": "42", "username": "alice", "name": "", "profile_image_url": "https://pbs.twimg.com/a.png"}
        }


def test_x_profile_has_no_email_and_the_handle_is_a_label() -> None:
    """Nothing is invented: the account is the id, and with no display name the handle is shown."""
    profile = asyncio.run(oauth.normalize_profile("x", cast("oauth.OAuthClient", FakeClient()), {}))
    assert profile["sub"] == "42"
    assert profile["email"] is None
    assert profile["name"] == "@alice"


class TestCallback:
    """The redirect back from X."""

    @pytest.fixture(autouse=True)
    def _x_is_the_provider(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class Registry:
            def create_client(self, name: str) -> object:
                return Authorizer()

        class Authorizer:
            async def authorize_access_token(self, request: object) -> dict[str, JsonValue]:
                return {}

        async def profile(provider: str, client: object, token: dict[str, JsonValue]) -> dict[str, str | None]:
            return {"provider": "x", "sub": "42", "email": None, "name": "@alice", "avatar": None}

        monkeypatch.setattr(oauth_routes, "configured_providers", lambda: ["x"])
        monkeypatch.setattr(oauth_routes, "oauth", Registry())
        monkeypatch.setattr(oauth_routes, "normalize_profile", profile)
        monkeypatch.setenv("ADMIN_EMAILS", "boss@x.com")

    def test_an_unlisted_x_user_is_told_their_id(self, client: TestClient) -> None:
        """Refused, with the id to give the admin."""
        r = client.get("/api/auth/callback/x", follow_redirects=False)
        assert r.status_code == 302
        assert r.headers["location"] == "/?auth=denied&id=x%3A42"

    def test_a_listed_x_user_is_signed_in(
        self, client: TestClient, db: MetadataDB, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Let in by id: an account with no email and a login cookie."""
        monkeypatch.setenv("ALLOWED_OAUTH_IDS", "x:42")
        r = client.get("/api/auth/callback/x", follow_redirects=False)
        assert r.headers["location"] == "/"
        assert "user_session" in r.cookies
        assert db.count_users() == 1

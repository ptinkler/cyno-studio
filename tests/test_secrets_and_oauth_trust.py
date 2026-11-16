"""Startup refuses a guessable session secret; OAuth only trusts an email the provider vouches for."""

import asyncio
import logging
from typing import cast

import pytest

from web.auth import oauth, session
from web.auth.session import WeakSessionSecretError, check_secrets
from web.types import JsonValue

STRONG = "x" * 40


class TestCheckSecrets:
    """The session secret signs logins, so a guessable one is refused at startup."""

    @pytest.mark.parametrize("value", [None, "", "short", "change_me_long_random", "Change_Me" + "x" * 40])
    def test_refuses_missing_short_or_example(self, monkeypatch: pytest.MonkeyPatch, value: str | None) -> None:
        """Nothing, something short and the .env.example value are all refused."""
        if value is not None:
            monkeypatch.setenv("SESSION_SECRET", value)
        with pytest.raises(WeakSessionSecretError):
            check_secrets()

    def test_accepts_a_long_random_one(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A real secret passes."""
        monkeypatch.setenv("SESSION_SECRET", STRONG)
        check_secrets()

    def test_dev_login_is_exempt(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The throwaway dev setup needs no secrets."""
        monkeypatch.setenv("DEV_LOGIN", "true")
        check_secrets()

    def test_warns_about_example_values_it_cannot_refuse(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Changing KEYS_SECRET or PASSWORD_PEPPER would orphan saved data, so they only warn."""
        monkeypatch.setenv("SESSION_SECRET", STRONG)
        monkeypatch.setenv("KEYS_SECRET", "change_me_long_random")
        # Alembic's fileConfig (run by other tests) disables loggers that already exist; a fresh one isn't
        monkeypatch.setattr(session, "log", logging.getLogger("tests.secrets"))
        with caplog.at_level(logging.WARNING):
            check_secrets()
        assert "KEYS_SECRET" in caplog.text
        assert "PASSWORD_PEPPER" not in caplog.text


class FakeClient:
    """Stands in for the provider client: userinfo is whatever the test says."""

    def __init__(self, info: dict[str, JsonValue]) -> None:
        """Set the user-info document."""
        self.info = info

    async def userinfo(self, *, token: dict[str, JsonValue]) -> dict[str, JsonValue]:
        """The provider's user-info document."""
        assert token == {}
        return self.info


def _email(provider: str, info: dict[str, JsonValue]) -> str | None:
    profile = asyncio.run(oauth.normalize_profile(provider, cast("oauth.OAuthClient", FakeClient(info)), {}))
    return profile["email"]


class TestVerifiedEmail:
    """An unverified address could belong to anyone, and access is decided by email."""

    @pytest.mark.parametrize(
        ("verified", "expected"), [(True, "a@b.com"), ("true", "a@b.com"), (False, None), (None, None)]
    )
    def test_google_needs_email_verified(self, verified: JsonValue, expected: str | None) -> None:
        """Only a verified Google address counts."""
        assert _email("google", {"sub": "1", "email": "A@B.com", "email_verified": verified}) == expected

    def test_microsoft_any_tenant_gives_no_email(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """With the multi-tenant endpoint, any tenant's admin can claim any address."""
        info: dict[str, JsonValue] = {"sub": "1", "email": "admin@corp.com"}
        assert _email("microsoft", info) is None
        monkeypatch.setenv("MICROSOFT_OAUTH_TENANT", "common")
        assert _email("microsoft", info) is None

    def test_microsoft_own_tenant_is_trusted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A named tenant is ours, so its addresses (the email, else the sign-in name) are used."""
        monkeypatch.setenv("MICROSOFT_OAUTH_TENANT", "contoso.onmicrosoft.com")
        assert _email("microsoft", {"sub": "1", "email": "A@Contoso.com"}) == "a@contoso.com"
        assert _email("microsoft", {"sub": "1", "preferred_username": "b@contoso.com"}) == "b@contoso.com"

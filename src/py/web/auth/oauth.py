"""OAuth sign-in via Authlib — Google and Microsoft (OIDC) and X (OAuth2/PKCE).

Each provider is registered only when its client id/secret are configured, so
the app runs fine with none set. Add a provider by setting its env vars:

    GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET
    MICROSOFT_OAUTH_CLIENT_ID / MICROSOFT_OAUTH_CLIENT_SECRET / MICROSOFT_OAUTH_TENANT
    X_OAUTH_CLIENT_ID / X_OAUTH_CLIENT_SECRET

The redirect/callback URI registered with each provider must be
    https://<your-public-host>/api/auth/callback/<provider>
(https is mandatory except for http://localhost during development).

An account is its provider and the provider's user id. Where there is an email, access is decided by it
(ADMIN_EMAILS, ALLOWED_EMAILS) and it joins a second sign-in to the same person, so only an email the
provider vouches for is used: Google's `email_verified`, or a Microsoft address from one named tenant
(MICROSOFT_OAUTH_TENANT). Anyone can make a Microsoft account with any address in some other tenant, so
the multi-tenant endpoints ("common", "organizations", "consumers") yield no email. X yields none either:
its users are let in by id (ALLOWED_OAUTH_IDS, e.g. `x:12345`) or by OPEN_SIGNUP.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from typing import TYPE_CHECKING, Protocol, cast

from authlib.integrations.starlette_client import OAuth

if TYPE_CHECKING:
    from fastapi import Request
    from fastapi.responses import RedirectResponse

    from web.types import JsonValue

log = logging.getLogger(__name__)

# Authlib ships no type information, so the registry is typed by the Protocol above.
oauth = cast("OAuthRegistry", OAuth())

# Provider definitions. OIDC providers discover their endpoints from the
# metadata url; X is plain OAuth2 and needs its endpoints spelled out.
_GOOGLE_META = "https://accounts.google.com/.well-known/openid-configuration"
_MS_MULTI_TENANT = frozenset({"common", "organizations", "consumers"})  # endpoints that admit anyone's tenant


def _env(provider: str, field: str) -> str:
    return os.getenv(f"{provider.upper()}_OAUTH_{field}", "").strip()


def microsoft_tenant() -> str:
    """The Microsoft tenant users must belong to (MICROSOFT_OAUTH_TENANT), else the any-tenant "common"."""
    return _env("microsoft", "TENANT") or "common"


def _ms_meta() -> str:
    return f"https://login.microsoftonline.com/{microsoft_tenant()}/v2.0/.well-known/openid-configuration"


def register_providers() -> None:
    """Register providers with configured credentials.

    Call once during application startup.
    """
    if _env("google", "CLIENT_ID"):
        oauth.register(
            name="google",
            client_id=_env("google", "CLIENT_ID"),
            client_secret=_env("google", "CLIENT_SECRET"),
            server_metadata_url=_GOOGLE_META,
            client_kwargs={"scope": "openid email profile"},
        )
    if _env("microsoft", "CLIENT_ID"):
        oauth.register(
            name="microsoft",
            client_id=_env("microsoft", "CLIENT_ID"),
            client_secret=_env("microsoft", "CLIENT_SECRET"),
            server_metadata_url=_ms_meta(),
            client_kwargs={"scope": "openid email profile"},
        )
        if microsoft_tenant() in _MS_MULTI_TENANT:
            log.warning(
                "Microsoft sign-in is refused: MICROSOFT_OAUTH_TENANT is unset or multi-tenant, so its "
                "email can't be trusted. Set it to your tenant id or domain."
            )
    if _env("x", "CLIENT_ID"):
        oauth.register(
            name="x",
            client_id=_env("x", "CLIENT_ID"),
            client_secret=_env("x", "CLIENT_SECRET"),
            authorize_url="https://twitter.com/i/oauth2/authorize",
            # S106 false positive: this is X's public token-endpoint URL, not a credential, and
            # `access_token_url` is Authlib's own keyword so it can't be renamed. Approved by the maintainer.
            access_token_url="https://api.twitter.com/2/oauth2/token",  # noqa: S106
            api_base_url="https://api.twitter.com/2/",
            client_kwargs={
                "scope": "users.read tweet.read offline.access",
                "code_challenge_method": "S256",
                "token_endpoint_auth_method": "client_secret_basic",
            },
        )


# Providers whose sign-in always carries a verified email (access is decided by it); X has none
EMAIL_PROVIDERS = frozenset({"google", "microsoft"})


def configured_providers() -> list[str]:
    """Names of providers that are registered (have credentials)."""
    return [p for p in ("google", "microsoft", "x") if _env(p, "CLIENT_ID")]


class OAuthResponse(Protocol):
    """Response shape needed from an OAuth provider client."""

    def json(self) -> dict[str, JsonValue]:
        """Decode the provider response body."""
        raise NotImplementedError


class OAuthClient(Protocol):
    """Provider client operations used during sign-in (Authlib's dynamic interface)."""

    async def userinfo(self, *, token: dict[str, JsonValue]) -> dict[str, JsonValue]:
        """Fetch the provider's user-info document."""
        raise NotImplementedError

    async def get(self, url: str, *, token: dict[str, JsonValue]) -> OAuthResponse:
        """Perform an authenticated provider request."""
        raise NotImplementedError

    async def authorize_redirect(self, request: Request, redirect_uri: str) -> RedirectResponse:
        """Start the authorization-code flow."""
        raise NotImplementedError

    async def authorize_access_token(self, request: Request) -> dict[str, JsonValue]:
        """Exchange the callback's code for a token."""
        raise NotImplementedError


class OAuthRegistry(Protocol):
    """The part of Authlib's ``OAuth`` registry this app uses."""

    def register(self, name: str, **kwargs: JsonValue) -> object:
        """Register a provider by name."""
        raise NotImplementedError

    def create_client(self, name: str) -> OAuthClient:
        """The client for a registered provider."""
        raise NotImplementedError


def _text(value: JsonValue) -> str | None:
    """A JSON value as text when it is a string, else None."""
    return value if isinstance(value, str) else None


def _object(value: JsonValue) -> dict[str, JsonValue]:
    """A JSON value as an object when it is one, else empty."""
    return dict(value) if isinstance(value, Mapping) else {}


class UnknownProviderError(ValueError):
    """The sign-in provider is not one we support."""

    def __init__(self, provider: str) -> None:
        """Name the provider."""
        super().__init__(f"Unknown provider: {provider}")


def _verified_email(provider: str, info: Mapping[str, JsonValue]) -> str | None:
    """The account's email, only when the provider vouches that its owner controls it (else None)."""
    if provider == "google":
        email = _text(info.get("email"))
        verified = info.get("email_verified") in (True, "true")
        return email.lower() if email and verified else None
    if microsoft_tenant() in _MS_MULTI_TENANT:
        return None  # any tenant's admin can put any address on an account
    email = _text(info.get("email")) or _text(info.get("preferred_username"))  # an address within our own tenant
    return email.lower() if email else None


async def normalize_profile(provider: str, client: OAuthClient, token: dict[str, JsonValue]) -> dict[str, str | None]:
    """Normalize a provider's user-info response.

    The returned keys are ``provider``, ``sub``, ``email``, ``name``, and
    ``avatar``. Provider clients use Authlib's dynamic interface.

    Raises:
        ValueError: If ``provider`` is not supported.
    """
    if provider in ("google", "microsoft"):
        userinfo = token.get("userinfo")
        info = _object(userinfo) if isinstance(userinfo, Mapping) else await client.userinfo(token=token)
        return {
            "provider": provider,
            "sub": _text(info.get("sub")),
            "email": _verified_email(provider, info),
            "name": _text(info.get("name")),
            "avatar": _text(info.get("picture")),
        }
    if provider == "x":
        resp = await client.get("users/me?user.fields=profile_image_url,name,username", token=token)
        data = _object(_object(resp.json()).get("data"))
        username = _text(data.get("username"))
        # X gives no email and its handles can be taken over once released, so the account is the X user id
        # and the handle is only a label
        return {
            "provider": provider,
            "sub": _text(data.get("id")),
            "email": None,
            "name": _text(data.get("name")) or (f"@{username}" if username else None),
            "avatar": _text(data.get("profile_image_url")),
        }
    raise UnknownProviderError(provider)

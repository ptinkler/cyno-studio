"""Response models for the sign-in and account endpoints.

These are the contract the frontend's generated types come from (see docs/DEVELOPMENT.md, Typed
API): a route returns one of these instead of a loose dict, so the OpenAPI schema
says exactly which fields exist and which can be null.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from web.core.metadata import User


class SessionUser(BaseModel):
    """The signed-in user as the app shell needs them."""

    email: str | None  # none for a sign-in that has no email (X)
    name: str | None
    is_admin: bool


class AccountUser(SessionUser):
    """A user's full public profile, as shown on the account page."""

    id: str
    avatar_url: str | None
    provider: str


class AuthStatus(BaseModel):
    """Whether anyone is signed in, and who."""

    authenticated: bool
    user: SessionUser | None


class AuthMe(BaseModel):
    """The signed-in user's profile, if any."""

    user: AccountUser | None


class AuthProviders(AuthMe):
    """The sign-in options this instance offers, and the current user."""

    providers: list[str]
    open_signup: bool
    dev_login: bool


class LoginResult(SessionUser):
    """A successful sign-in: the new session's user."""

    ok: bool


class Ok(BaseModel):
    """A bare acknowledgement."""

    ok: bool


def session_user(user: User) -> SessionUser:
    """The app-shell view of a stored user."""
    return SessionUser(email=user.email, name=user.name, is_admin=user.is_admin)


def account_user(user: User) -> AccountUser:
    """The public profile of a stored user."""
    return AccountUser(
        id=user.id,
        email=user.email,
        name=user.name,
        avatar_url=user.avatar_url,
        provider=user.provider,
        is_admin=user.is_admin,
    )


def login_result(user: User) -> LoginResult:
    """The response to a successful sign-in as `user`."""
    return LoginResult(ok=True, email=user.email, name=user.name, is_admin=user.is_admin)

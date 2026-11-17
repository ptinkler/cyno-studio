"""User access policy for sign-in and current-user resolution.

The policy supports email allowlists, admin accounts, open signup and OAuth sessions.

Env:
  OPEN_SIGNUP=true           anyone who authenticates may create an account
  ALLOWED_EMAILS=a@x,b@y     only these (plus admins) may sign in
  ADMIN_EMAILS=you@x         admins; they also control the VPN

When none are set, the first user to sign in bootstraps as the sole admin and
no one else is admitted (fail-closed) until ALLOWED_EMAILS / OPEN_SIGNUP is set.
"""

from __future__ import annotations

from fastapi import Cookie, HTTPException

from web.auth.session import resolve_user_session
from web.core.env import bool_env, email_set, id_set
from web.core.metadata import User, get_db


def open_signup() -> bool:
    """Return whether anyone who authenticates may create an account."""
    return bool_env("OPEN_SIGNUP")


def allowed_emails() -> set[str]:
    """Return the normalized email allowlist."""
    return email_set("ALLOWED_EMAILS")


def admin_emails() -> set[str]:
    """Return the normalized set of administrator email addresses."""
    return email_set("ADMIN_EMAILS")


def allowed_ids() -> set[str]:
    """Return the provider ids let in without an email, as `provider:id` (e.g. `x:12345`)."""
    return id_set("ALLOWED_OAUTH_IDS")


def is_admin_email(email: str | None) -> bool:
    """Check whether an email belongs to an administrator."""
    return bool(email) and email.lower() in admin_emails()


def _admit_by_email(email: str, *, is_first_user: bool, admin: bool) -> bool:
    allow = allowed_emails()
    if allow:
        return email in allow or admin
    if admin_emails():  # admins only, no open list
        return admin
    return is_first_user  # first-ever user bootstraps as admin


def admit(email: str | None, *, is_first_user: bool, identity: str = "") -> tuple[bool, bool]:
    """Decide whether an authenticating person may sign in.

    `email` is the provider-verified address, if it gave one; `identity` is `provider:id`. Return an
    ``(allowed, is_admin)`` pair.
    """
    email = (email or "").lower()
    if not (email or identity):
        return False, False
    admin = (bool(email) and is_admin_email(email)) or (is_first_user and not admin_emails())
    if open_signup() or (identity and identity in allowed_ids()):
        return True, admin
    if not email:  # no email to match a list on: only the very first user (no lists set up yet) gets in
        return is_first_user and not (allowed_emails() or admin_emails()), admin
    return _admit_by_email(email, is_first_user=is_first_user, admin=admin), admin


def current_user(user_cookie: str | None) -> User | None:
    """The signed-in User for a user-session cookie (OAuth), or None."""
    claim = resolve_user_session(user_cookie)
    if not claim:
        return None
    user = get_db().get_user(claim.user_id)
    # A cookie from before the user signed out their other devices (or changed their password) is dead
    return user if user and user.session_version == claim.version else None


def resolve_current_user(user_cookie: str | None) -> User | None:
    """Resolve the current user from the signed session cookie.

    Local email-password login and OAuth both mint the same cookie.
    """
    return current_user(user_cookie)


def require_user(user_session: str | None = Cookie(None)) -> User:
    """Dependency: a signed-in user, else 401."""
    user = resolve_current_user(user_session)
    if not user:
        raise HTTPException(status_code=401, detail="Sign in required")
    return user


def require_admin(user_session: str | None = Cookie(None)) -> User:
    """Require the instance administrator for an owner-only action.

    Raise 401 when unsigned and 403 when the signed-in user is not an admin.
    """
    user = resolve_current_user(user_session)
    if not user:
        raise HTTPException(status_code=401, detail="Sign in required")
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")
    return user

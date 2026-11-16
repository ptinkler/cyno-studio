"""User session tokens for signed-in accounts.

Login is by user session only: a local admin signs in with email + password, an
allowed user signs in via OAuth, and either way the browser carries a signed
`user_session` cookie holding the user id. There is no API key — every
protected endpoint requires a resolvable session (see web/auth/users.py).
"""

import base64
import hashlib
import hmac
import logging
import os
import time

from fastapi import Request, Response

from web.core.env import bool_env, bool_env_or_none

log = logging.getLogger(__name__)

_TOKEN_PARTS = 3  # a signed token is <payload>.<expiry>.<signature>

# The session token and the cookie carrying it expire together.
SESSION_TTL = 60 * 60 * 24 * 30  # 30 days

USER_COOKIE = "user_session"


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


#
# The cookie holds a signed, expiring user id — not a raw credential — so a
# leaked cookie isn't a permanent password and sessions expire on their own.
# Signed with SESSION_SECRET when set, else a dev fallback.


def user_secret() -> bytes:
    """Return the signing key derived from the configured session secret."""
    explicit = os.getenv("SESSION_SECRET", "").strip()
    if explicit:
        return hashlib.sha256(
            b"pollo-user-v1\x00" + explicit.encode()
        ).digest()  # legacy salt: changing it signs every user out
    return hashlib.sha256(b"pollo-user-v1-dev").digest()


MIN_SECRET_CHARS = 32
PLACEHOLDER_PREFIX = "change_me"  # what .env.example ships


class WeakSessionSecretError(RuntimeError):
    """SESSION_SECRET is missing, short or still the example value, so session cookies could be forged."""

    def __init__(self) -> None:
        """Say what to set, and what else depends on it."""
        super().__init__(
            f"SESSION_SECRET must be a random string of at least {MIN_SECRET_CHARS} characters "
            "(openssl rand -hex 32). It signs login cookies; without a real one anyone can forge a session. "
            "Stored provider keys are encrypted with KEYS_SECRET, else this: set KEYS_SECRET too, "
            "since changing this one makes keys saved without it unreadable (they have to be entered again)."
        )


def check_secrets() -> None:
    """Refuse to start with a guessable session secret (DEV_LOGIN, the throwaway dev setup, is exempt).

    The other two secrets can't be refused: changing either one orphans data already saved with it.
    They are warned about instead.
    """
    if bool_env("DEV_LOGIN"):
        return
    secret = os.getenv("SESSION_SECRET", "").strip()
    if len(secret) < MIN_SECRET_CHARS or secret.lower().startswith(PLACEHOLDER_PREFIX):
        raise WeakSessionSecretError
    for name in ("KEYS_SECRET", "PASSWORD_PEPPER"):
        if os.getenv(name, "").strip().lower().startswith(PLACEHOLDER_PREFIX):
            log.warning("%s is still the example value from .env.example: anyone can read what it protects", name)


def make_user_session(user_id: str) -> str:
    """A signed cookie value for a signed-in user id."""
    payload = f"{user_id}.{int(time.time()) + SESSION_TTL}"
    sig = hmac.new(user_secret(), payload.encode(), hashlib.sha256).digest()
    return f"{payload}.{_b64(sig)}"


def cookie_secure(request: Request) -> bool:
    """Whether the session cookie should be marked Secure (HTTPS-only).

    Secure by default, so a TLS deployment (e.g. the NAS) needs no config. The
    one automatic exemption is plain-HTTP access to a loopback host, where
    local dev would otherwise break — browsers treat localhost as secure, so
    the cookie still works there. COOKIE_SECURE=true/false overrides either
    way: set it false only to serve auth over plain HTTP on a LAN.
    """
    override = bool_env_or_none("COOKIE_SECURE")
    if override is not None:
        return override
    forwarded = request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
    if request.url.scheme == "https" or forwarded == "https":
        return True
    host = (request.url.hostname or "").lower()
    return host not in {"localhost", "127.0.0.1", "::1"}


def set_user_cookie(response: Response, request: Request, user_id: str) -> None:
    """Set the signed-in user's session cookie on the response.

    Password login, OAuth, and development login all set the cookie here.
    """
    response.set_cookie(
        key=USER_COOKIE,
        value=make_user_session(user_id),
        httponly=True,
        samesite="lax",  # lax so the OAuth redirect back from the provider keeps it
        secure=cookie_secure(request),
        max_age=SESSION_TTL,
    )


def resolve_user_session(token: str | None) -> str | None:
    """Return the authenticated user ID, or None for an invalid session.

    Session IDs are UUID hex strings and therefore contain no periods.
    """
    if not token:
        return None
    parts = token.strip().split(".")
    if len(parts) != _TOKEN_PARTS:
        return None
    user_id, exp_s, sig_b64 = parts
    payload = f"{user_id}.{exp_s}"
    expected = hmac.new(user_secret(), payload.encode(), hashlib.sha256).digest()
    try:
        if not hmac.compare_digest(expected, _unb64(sig_b64)):
            return None
        if time.time() > int(exp_s):
            return None
    except (ValueError, TypeError):
        return None
    return user_id

"""Per-user provider API keys: encrypted at rest, never returned in the clear.

Each user brings their own Pollo / Venice / OpenRouter keys (entered in
Settings) instead of the shared .env — so each person pays their own way. The
keys are stored Fernet-encrypted (keyed off KEYS_SECRET, else the session
secret) and the API only ever exposes whether a key is set plus a short hint.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from typing import Annotated, cast

from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from web.auth.dev_login import store_keys_plaintext
from web.auth.session import user_secret
from web.auth.users import require_user
from web.core import key_caches as caches
from web.core.metadata import User, get_db
from web.jsonutil import loads

_HINT_CHARS = 4  # how many trailing characters of a saved key are shown as its hint

KEY_PROVIDERS = ("pollo", "venice", "openrouter")

router = APIRouter(prefix="/api/keys")


def fernet() -> Fernet:
    """The cipher that protects stored provider keys, keyed off KEYS_SECRET or the session secret."""
    secret = os.getenv("KEYS_SECRET", "").strip().encode() or user_secret()
    material = hashlib.sha256(b"pollo-keys-v1\x00" + secret).digest()
    return Fernet(base64.urlsafe_b64encode(material))


def _encrypt(keys: dict[str, str]) -> str:
    # In dev (DEV_LOGIN, fresh DB) store plaintext JSON — no secret to set,
    # nothing to lose. A Fernet token is never valid JSON, so reads tell the
    # two apart. See web/auth/dev_login.py.
    if store_keys_plaintext():
        return json.dumps(keys)
    return fernet().encrypt(json.dumps(keys).encode()).decode()


def _as_keys(data: object) -> dict[str, str] | None:
    """The {provider: key} entries of a decoded JSON object, or None if it isn't one."""
    if not isinstance(data, dict):
        return None
    return {str(k): v for k, v in cast("dict[object, object]", data).items() if isinstance(v, str)}


def _decrypt(blob: str | None) -> dict[str, str]:
    if not blob:
        return {}
    try:  # plaintext JSON (dev / no-encryption)
        keys = _as_keys(loads(blob))
    except (ValueError, TypeError):
        keys = None
    if keys is not None:
        return keys
    try:
        return _as_keys(loads(fernet().decrypt(blob.encode()).decode())) or {}
    except (InvalidToken, ValueError):
        return {}  # secret rotated or corrupt: treat as unset


def get_user_keys(user: User) -> dict[str, str]:
    """The user's decrypted {provider: key} (server-side use only)."""
    return _decrypt(getattr(user, "api_keys_json", None))


class KeyStatus(BaseModel):
    """Whether one provider's key is saved, with a short hint of it (never the key)."""

    set: bool
    hint: str


class KeysStatus(BaseModel):
    """The key status of every provider, by provider id."""

    keys: dict[str, KeyStatus]


def _masked(user: User | None) -> KeysStatus:
    keys = get_user_keys(user) if user else {}
    out: dict[str, KeyStatus] = {}
    for p in KEY_PROVIDERS:
        value = keys.get(p)
        hint = f"…{value[-_HINT_CHARS:]}" if value and len(value) >= _HINT_CHARS else ("set" if value else "")
        out[p] = KeyStatus(set=bool(value), hint=hint)
    return KeysStatus(keys=out)


class KeysUpdate(BaseModel):
    """Provider keys to set, clear or leave unchanged."""

    # {provider: "newkey"} to set, {provider: null/""} to clear; omit to keep
    keys: dict[str, str | None]


@router.get("")
async def get_keys(user: Annotated[User, Depends(require_user)]) -> KeysStatus:
    """Return whether each provider key is set and its masked hint."""
    return _masked(user)


@router.put("")
async def set_keys(data: KeysUpdate, user: Annotated[User, Depends(require_user)]) -> KeysStatus:
    """Update the signed-in user's provider keys."""
    current = get_user_keys(user)
    for provider, value in data.keys.items():
        if provider not in KEY_PROVIDERS:
            continue
        if value is None or not value.strip():
            current.pop(provider, None)  # clear
        else:
            current[provider] = value.strip()
    get_db().set_user_api_keys(user.id, _encrypt(current))
    caches.keys_changed()  # catalogues and balances are per user, built from their keys
    return _masked(get_db().get_user(user.id))

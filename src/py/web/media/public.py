"""Serve self-hosted source media through signed, expiring URLs.

Providers can fetch local uploads from this instance instead of a temp host.
unauthenticated URL so a provider that only takes a URL (Pollo) can fetch it
from *this* instance instead of a third-party temp host (catbox/tmpfiles).

The token signs the file's path (relative to the data folder, so the server's layout isn't shown to the
provider) with a key made for this use, so it can't be forged, widened or swapped for a login cookie; the
route additionally confines reads to the media roots. Links
expire after the configured TTL — the same short-lived, unguessable exposure
model as the public temp hosts, but on the instance's own domain.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from web.auth.session import signing_key
from web.core import config
from web.safepath import inside

_TOKEN_PARTS = 3  # a signed token is <payload>.<expiry>.<signature>

router = APIRouter(prefix="/api/public-media")


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


MEDIA_FOLDERS = ("chat", "characters", "library")  # what a self-hosted media link may serve


def _media_file(relative: str) -> Path | None:
    """The file a token names, if it is under the chat, character or library folders (else None)."""
    for folder in MEDIA_FOLDERS:
        try:
            return inside(config.ROOT_DIR / folder, Path(relative).relative_to(folder).as_posix())
        except (ValueError, HTTPException):
            continue
    return None


def sign_media_token(filepath: Path, ttl_seconds: int) -> str:
    """A signed, expiring token for a local media file (ValueError if it isn't under the data folder)."""
    relative = Path(filepath).resolve().relative_to(config.ROOT_DIR.resolve())
    b64path = _b64(relative.as_posix().encode())
    exp = int(time.time()) + int(ttl_seconds)
    payload = f"{b64path}.{exp}"
    sig = hmac.new(signing_key("public-media"), payload.encode(), hashlib.sha256).digest()
    return f"{payload}.{_b64(sig)}"


def _resolve_token(token: str) -> Path | None:
    """The valid, unexpired, in-bounds file a token points to, else None."""
    parts = token.split(".")
    if len(parts) != _TOKEN_PARTS:
        return None
    b64path, exp_s, sig_b64 = parts
    payload = f"{b64path}.{exp_s}"
    expected = hmac.new(signing_key("public-media"), payload.encode(), hashlib.sha256).digest()
    try:
        if not hmac.compare_digest(expected, _unb64(sig_b64)):
            return None
        if time.time() > int(exp_s):
            return None
        path = _media_file(_unb64(b64path).decode())
    except (ValueError, TypeError):
        return None
    return path if path and path.is_file() else None


class SelfhostBaseUrlError(ValueError):
    """Self-hosting was chosen but no reachable public base URL is configured."""

    def __init__(self) -> None:
        """Build the fixed message."""
        super().__init__(
            "Self-host upload needs a public base URL — set it in Settings → Media uploads "
            "(or PUBLIC_BASE_URL). It must be the https address this instance is reachable at."
        )


def selfhost_url(filepath: Path, base_url: str, ttl_seconds: int) -> str:
    """Build a signed URL for a provider to fetch a local file.

    Raise ``ValueError`` if no reachable base URL is configured.
    """
    base = (base_url or "").strip().rstrip("/")
    if not base.startswith(("http://", "https://")):
        raise SelfhostBaseUrlError
    return f"{base}/api/public-media/{sign_media_token(filepath, ttl_seconds)}"


@router.get("/{token}")
def serve_public_media(token: str) -> FileResponse:
    """Stream a signed media file without requiring login.

    Invalid, expired or out-of-bounds tokens return 404 without leaking file information.
    """
    path = _resolve_token(token)
    if path is None:
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(path)

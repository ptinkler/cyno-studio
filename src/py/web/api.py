"""Cyno Studio — API Backend (FastAPI).

Run:  make dev-api   (uvicorn web.api:app, from the repo root)

.env loading and logging setup live in web/__init__.py, which Python runs
before any web.* module, so everything here is a plain top-level import.
"""

import logging
import threading
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Annotated, cast

import uvicorn
from fastapi import Cookie, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

from web import characters, vpn
from web.auth import keyctx, user_keys
from web.auth.dev_login import router as dev_login_router
from web.auth.dev_login import seed_dev_user
from web.auth.oauth import configured_providers, register_providers
from web.auth.oauth_routes import router as oauth_router
from web.auth.passwords import hash_password, needs_rehash, verify_password
from web.auth.schemas import AuthStatus, LoginResult, Ok, login_result, session_user
from web.auth.session import USER_COOKIE, check_secrets, set_user_cookie, user_secret
from web.auth.user_keys import router as keys_router
from web.auth.users import admin_emails, resolve_current_user
from web.chat import router as chat_router
from web.chat import startup_resume_chat
from web.core.env import bool_env
from web.core.metadata import get_db, reset_tenant, set_tenant
from web.core.metadata.schema import ensure_schema
from web.core.openapi import event_stream_only
from web.media.public import router as public_media_router
from web.media.routes import router as media_router
from web.transfer.chatgpt import router as chatgpt_import_router
from web.transfer.export import router as chat_export_router
from web.types import JsonValue
from web.uploads.settings import router as upload_settings_router

log = logging.getLogger(__name__)

_MAX_TRACKED_LOGIN_KEYS = 2048  # above this many keys, idle ones are pruned so the map can't grow unbounded
ROOT_DIR = Path(__file__).resolve().parents[3]  # the repo root (src/py/web/api.py)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    """Lifespan context manager for startup/shutdown events."""
    check_secrets()  # a guessable session secret lets anyone forge a login
    # Startup: announce the auth posture so a misconfigured deploy is obvious
    admins = admin_emails()
    if admins:
        log.info("auth: email+password login for admin(s) %s; others via OAuth", ", ".join(sorted(admins)))
    else:
        log.warning("auth: no ADMIN_EMAILS set — no one can create a local admin until it is configured")
    # Register any OAuth providers that have credentials configured
    register_providers()
    providers = configured_providers()
    log.info("OAuth providers: %s", ", ".join(providers) if providers else "none configured")
    # Alembic owns the schema; bring it up to date before anything reads it.
    db = get_db()
    ensure_schema(db.engine, db.db_path, fresh=db.is_fresh)
    # Dev: seed the one-click dev account when enabled (no-op otherwise).
    seed_dev_user()
    startup_resume_chat()
    yield
    # Shutdown: nothing to do


# The interactive API docs (/docs, /redoc, /openapi.json) expose the whole API
# surface unauthenticated, so they're off by default — enable with ENABLE_API_DOCS
# (or in dev, where DEV_LOGIN is set).
_docs_on = bool_env("ENABLE_API_DOCS") or bool_env("DEV_LOGIN")
app = FastAPI(
    title="Cyno Studio API",
    lifespan=lifespan,
    docs_url="/docs" if _docs_on else None,
    redoc_url="/redoc" if _docs_on else None,
    openapi_url="/openapi.json" if _docs_on else None,
)

_build_openapi = app.openapi
_schema: dict[str, JsonValue] = {}


def _openapi() -> dict[str, JsonValue]:
    """The OpenAPI schema (built once), with event-stream routes described only as event streams."""
    if not _schema:
        _schema.update(event_stream_only(_build_openapi()))
    return _schema


app.openapi = _openapi

# CORS - allow frontend dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "https://localhost:5173",
        "https://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Session middleware holds Authlib's transient OAuth state across the redirect.
# SameSite=lax so the state cookie survives the return hop from the provider;
# Secure (https_only) by default, matching the login cookie — disable only for
# plain-HTTP LAN dev via COOKIE_SECURE=false.
app.add_middleware(
    SessionMiddleware,
    secret_key=user_secret().hex(),
    same_site="lax",
    https_only=bool_env("COOKIE_SECURE", default=True),
)


class UserContextMiddleware:
    """Bind the signed-in user's provider keys AND tenant for the whole request,.

    The streamed response body is included. A pure ASGI middleware (not
    BaseHTTPMiddleware) is required: its context survives into the response
    streaming, where chat turns run and would otherwise see no keys or tenant.
    """

    def __init__(self, app: ASGIApp) -> None:
        """Wrap the ASGI app this middleware sits in front of."""
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Bind user keys and tenant data while handling an API request."""
        path = cast("str", scope.get("path", ""))
        if scope["type"] != "http" or not path.startswith("/api"):
            return await self.app(scope, receive, send)

        raw_headers = cast("list[tuple[bytes, bytes]]", scope.get("headers", []))
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in raw_headers}
        jar = SimpleCookie()
        jar.load(headers.get("cookie", ""))

        def cookie(name: str) -> str | None:
            return jar[name].value if name in jar else None

        user = resolve_current_user(cookie("user_session"))
        ktoken = keyctx.set_keys(user_keys.get_user_keys(user) if user else {})
        # "" owns no rows, so an unauthenticated API call sees no tenant data
        # (with None the scope filter would be bypassed entirely).
        ttoken = set_tenant(user.id if user else "")
        try:
            await self.app(scope, receive, send)
        finally:
            keyctx.reset_keys(ktoken)
            reset_tenant(ttoken)


app.add_middleware(UserContextMiddleware)


class LoginRequest(BaseModel):
    """Credentials submitted to the local email-and-password login endpoint."""

    email: str
    password: str


# Login brute-force throttle: per-client-IP sliding window (in-memory).
LOGIN_MAX_ATTEMPTS = 10
LOGIN_WINDOW_SECONDS = 300
_login_attempts: dict[str, list[float]] = {}
_login_lock = threading.Lock()


def reset_login_attempts() -> None:
    """Forget every client's recent failed logins (tests, between runs)."""
    with _login_lock:
        _login_attempts.clear()


def _client_ip(request: Request) -> str:
    """The real client IP.

    Behind the reverse proxy, ``request.client`` is the proxy itself, so this prefers nginx's X-Real-IP
    header, then the first X-Forwarded-For hop, then the socket peer.
    """
    real = request.headers.get("x-real-ip", "").strip()
    if real:
        return real
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    if forwarded:
        return forwarded
    return request.client.host if request.client else "unknown"


def _record_attempt(key: str, now: float) -> bool:
    """Append an attempt under `key` (caller holds the lock); True if over the limit."""
    attempts = [t for t in _login_attempts.get(key, []) if now - t < LOGIN_WINDOW_SECONDS]
    attempts.append(now)
    _login_attempts[key] = attempts
    return len(attempts) > LOGIN_MAX_ATTEMPTS


def _login_rate_limited(request: Request, email: str) -> bool:
    """Record this login attempt and report whether the client IP OR the target.

    The email key also prevents spoofed forwarding headers from lifting the
    per-account cap.
    """
    now = time.time()
    with _login_lock:
        over_ip = _record_attempt(f"ip:{_client_ip(request)}", now)
        over_email = _record_attempt(f"email:{email}", now)
        # Opportunistically drop idle keys so the map can't grow unbounded.
        if len(_login_attempts) > _MAX_TRACKED_LOGIN_KEYS:
            for k in [k for k, ts in _login_attempts.items() if all(now - t >= LOGIN_WINDOW_SECONDS for t in ts)]:
                _login_attempts.pop(k, None)
        return over_ip or over_email


@app.post("/api/auth/login")
async def api_auth_login(data: LoginRequest, response: Response, request: Request) -> LoginResult:
    """Authenticate a local user and set the signed-in session cookie."""
    email = data.email.strip().lower()
    if _login_rate_limited(request, email):
        raise HTTPException(status_code=429, detail="Too many login attempts. Try again later.")
    db = get_db()
    user = db.get_user_by_email(email)
    if not user or not user.password_hash or not verify_password(user.password_hash, data.password):
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    if needs_rehash(user.password_hash):  # transparently upgrade to stronger params
        db.set_user_password(user.id, hash_password(data.password))
    set_user_cookie(response, request, user.id)
    return login_result(user)


@app.post("/api/auth/logout")
async def api_auth_logout(response: Response) -> Ok:
    """Clear the signed-in user cookie."""
    response.delete_cookie(key=USER_COOKIE, samesite="lax")
    return Ok(ok=True)


@app.get("/api/auth/status")
async def api_auth_status(user_session: Annotated[str | None, Cookie()] = None) -> AuthStatus:
    """Return whether a user is signed in and their public account details.

    Admin accounts are created via the CLI (web.provision_admin), never through the app.
    """
    user = resolve_current_user(user_session)
    return AuthStatus(authenticated=user is not None, user=session_user(user) if user else None)


# Must be registered before the SPA catch-all below.
app.include_router(oauth_router)
app.include_router(keys_router)
app.include_router(upload_settings_router)
app.include_router(public_media_router)
app.include_router(dev_login_router)
app.include_router(chat_router)
app.include_router(chatgpt_import_router)
app.include_router(chat_export_router)
app.include_router(characters.router)
app.include_router(media_router)
app.include_router(vpn.router)


STATIC_DIR = ROOT_DIR / "src" / "js" / "dist"  # the built frontend


def static_file(path: str, static_dir: Path = STATIC_DIR) -> Path:
    """Map a request path to a file in the SPA build, falling back to index.html.

    Resolved and confined to static_dir: encoded "../" (e.g. /..%2F.env)
    reaches us un-normalised and would otherwise escape the directory.
    """
    file = (static_dir / path).resolve()
    if file.is_relative_to(static_dir.resolve()) and file.is_file():
        return file
    return static_dir / "index.html"


if STATIC_DIR.is_dir():
    # Serve static assets (js, css, etc.)
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="static-assets")

    @app.get("/{path:path}", include_in_schema=False)  # the SPA, not part of the API
    def serve_frontend(path: str) -> FileResponse:
        """Catch-all: serve the Vue SPA index.html for any non-API route."""
        return FileResponse(static_file(path))


if __name__ == "__main__":
    log.info("starting Cyno Studio server on http://localhost:5000 (docs at /docs)")
    uvicorn.run(app, host="127.0.0.1", port=5000)

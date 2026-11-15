"""One-click dev login (DEV_LOGIN): signs in a local admin with no password,.

stores keys unencrypted, and is refused on an already-encrypted (prod) DB.
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import web.api as api_mod
from tests.jsonpath import flag, text
from web import dev_login, user_keys
from web.core.metadata import MetadataDB

# These exercise REAL session resolution (cookie -> user), so opt out of the
# autouse _tenant fixture that otherwise hardwires resolve_current_user.
pytestmark = pytest.mark.no_tenant


@pytest.fixture
def db(tmp_path: Path):
    """Provide the db fixture."""
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    return MetadataDB(db_path=tmp_path / "data" / "metadata.db")


@pytest.fixture
def client(db: MetadataDB, monkeypatch: pytest.MonkeyPatch):
    """Provide the client fixture."""
    monkeypatch.setattr(api_mod, "get_db", lambda: db)
    monkeypatch.setattr("web.users.get_db", lambda: db)
    monkeypatch.setattr("web.user_keys.get_db", lambda: db)
    monkeypatch.setattr("web.dev_login.get_db", lambda: db)
    # Dev serves over plain HTTP; without this the session cookie is marked
    # Secure for the non-localhost "testserver" host and the TestClient won't
    # resend it, so follow-up requests look unauthenticated. (Passes locally
    # only because a dev .env sets COOKIE_SECURE=false.)
    monkeypatch.setenv("COOKIE_SECURE", "false")
    return TestClient(api_mod.app, raise_server_exceptions=False)


def test_disabled_is_404(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that disabled is 404."""
    monkeypatch.delenv("DEV_LOGIN", raising=False)
    assert client.post("/api/auth/dev-login").status_code == 404


def test_signs_in_an_admin(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that signs in an admin."""
    monkeypatch.setenv("DEV_LOGIN", "true")
    r = client.post("/api/auth/dev-login")
    assert r.status_code == 200
    assert text(r, "email") == "dev@local"
    assert client.cookies.get("user_session")
    status = client.get("/api/auth/status")
    assert flag(status, "authenticated")
    assert flag(status, "user", "is_admin")


def test_keys_stored_plaintext_in_dev(client: TestClient, db: MetadataDB, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that keys stored plaintext in dev."""
    monkeypatch.setenv("DEV_LOGIN", "true")
    client.post("/api/auth/dev-login")
    assert client.put("/api/keys", json={"keys": {"pollo": "sk-dev-123"}}).status_code == 200
    # Stored blob is plaintext JSON, not a Fernet token — nothing to decrypt.
    (blob,) = db.list_api_key_blobs()
    assert json.loads(blob) == {"pollo": "sk-dev-123"}

    assert dev_login.db_has_encrypted_keys() is False


def test_refused_on_encrypted_db(client: TestClient, db: MetadataDB, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that refused on encrypted db."""
    monkeypatch.setenv("DEV_LOGIN", "true")

    # A pre-existing user with an ENCRYPTED key blob makes this look like prod.
    user = db.upsert_oauth_user({"provider": "local", "sub": "admin", "email": "a@b", "name": "A"}, is_admin=True)
    db.set_user_api_keys(user.id, user_keys.fernet().encrypt(json.dumps({"pollo": "secret"}).encode()).decode())
    assert dev_login.db_has_encrypted_keys() is True

    r = client.post("/api/auth/dev-login")
    assert r.status_code == 403
    assert "encrypted" in text(r, "detail").lower()

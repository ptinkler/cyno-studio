"""Email+password admin auth: hashing, registration gating, login."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import web.api as api_mod
from tests.jsonpath import obj
from web.auth import passwords
from web.auth.passwords import hash_password
from web.core.metadata import MetadataDB


@pytest.fixture
def db(tmp_path: Path):
    """Provide the db fixture."""
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    return MetadataDB(db_path=tmp_path / "data" / "metadata.db")


@pytest.fixture
def client(db: MetadataDB, monkeypatch: pytest.MonkeyPatch):
    """Provide the client fixture."""
    monkeypatch.setattr(api_mod, "get_db", lambda: db)
    monkeypatch.setenv("ADMIN_EMAILS", "admin@x.com")
    return TestClient(api_mod.app, raise_server_exceptions=False)


class TestHashing:
    """Tests for hashing."""

    def test_roundtrip_and_pepper(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that roundtrip and pepper."""
        monkeypatch.setenv("PASSWORD_PEPPER", "pepper-one")
        h = passwords.hash_password("correct horse battery")
        assert h != "correct horse battery"  # not plaintext
        assert passwords.verify_password(h, "correct horse battery")
        assert not passwords.verify_password(h, "wrong")
        assert not passwords.verify_password(None, "anything")
        # A different pepper must fail to verify the same password.
        monkeypatch.setenv("PASSWORD_PEPPER", "pepper-two")
        assert not passwords.verify_password(h, "correct horse battery")

    def test_unique_salt(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that unique salt."""
        monkeypatch.setenv("PASSWORD_PEPPER", "p")
        assert passwords.hash_password("samepassword") != passwords.hash_password("samepassword")


class TestKeys:
    """The signed-in user manages their own provider keys (no env)."""

    def test_get_keys(self, client: TestClient) -> None:
        """Test that get keys."""
        r = client.get("/api/keys")
        assert r.status_code == 200
        assert set(obj(r, "keys")) == {"pollo", "venice", "openrouter"}

    def test_put_keys(self, client: TestClient, db: MetadataDB, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that put keys."""
        monkeypatch.setenv("KEYS_SECRET", "test-secret")
        monkeypatch.setattr("web.auth.user_keys.get_db", lambda: db)
        r = client.put("/api/keys", json={"keys": {"pollo": "sk-test-key"}})
        assert r.status_code == 200


class TestLogin:
    """Admins are created via the CLI (web.provision_admin), not the app — there is no register endpoint.

    Login verifies against that CLI-set password.
    """

    def test_no_register_endpoint(self, client: TestClient) -> None:
        """Test that no register endpoint."""
        r = client.post("/api/auth/register", json={"email": "admin@x.com", "password": "longenough1"})
        assert r.status_code in (404, 405)  # no such route — admins are CLI-only

    def test_unknown_user(self, client: TestClient) -> None:
        """Test that unknown user."""
        r = client.post("/api/auth/login", json={"email": "ghost@x.com", "password": "whatever123"})
        assert r.status_code == 401

    def test_cli_created_admin_can_log_in(self, client: TestClient, db: MetadataDB) -> None:
        """Test that cli created admin can log in."""
        db.create_local_admin("admin@x.com", hash_password("longenough1"), name="Admin")
        assert client.post("/api/auth/login", json={"email": "admin@x.com", "password": "nope"}).status_code == 401
        ok = client.post("/api/auth/login", json={"email": "admin@x.com", "password": "longenough1"})
        assert ok.status_code == 200
        assert ok.json()["email"] == "admin@x.com"
        assert client.cookies.get("user_session")


def test_unknown_email_still_spends_the_time_of_a_password_check(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unknown email must not answer faster than a wrong password, or the difference lists the accounts."""
    spent: list[str] = []
    monkeypatch.setattr(api_mod, "spend_verification_time", spent.append)
    r = client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "pw"})
    assert r.status_code == 401
    assert spent == ["pw"]

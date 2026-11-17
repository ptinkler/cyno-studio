"""Tests for web.api: the endpoints and helpers that remain.

They remain after the legacy generation/projects/jobs subsystem was removed (auth, SPA serving, lifespan).
"""

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

import web.api as api_mod
from tests.jsonpath import must, number
from web.chat import routes_settings
from web.core.metadata import MetadataDB

if TYPE_CHECKING:
    from httpx import Response

pytest_plugins = ["tests.api_fixtures"]


class TestLifespan:
    """Tests for lifespan."""

    def test_lifespan_runs(self, client: TestClient, db: MetadataDB, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that lifespan runs."""
        monkeypatch.setenv("SESSION_SECRET", "x" * 40)

        async def run_lifespan() -> None:
            async with api_mod.lifespan(api_mod.app):
                pass

        asyncio.run(run_lifespan())


class TestMainGuards:
    """Tests for main guards."""

    def test_api_main_guard(self) -> None:
        """Test that api main guard."""
        assert hasattr(api_mod, "app")


class TestStaticFile:
    """Tests for static file."""

    @pytest.fixture
    def static(self, tmp_path: Path) -> Path:
        """Provide the static fixture."""
        d = tmp_path / "static"
        (d / "assets").mkdir(parents=True)
        (d / "index.html").write_text("index")
        (d / "favicon.ico").write_text("icon")
        (tmp_path / ".env").write_text("SECRET=1")
        return d

    def test_serves_existing_file(self, static: Path) -> None:
        """Test that serves existing file."""
        assert api_mod.static_file("favicon.ico", static) == (static / "favicon.ico").resolve()

    def test_unknown_path_falls_back_to_index(self, static: Path) -> None:
        """Test that unknown path falls back to index."""
        assert api_mod.static_file("project/foo/gallery", static) == static / "index.html"

    @pytest.mark.parametrize("path", ["../.env", "assets/../../.env", "/etc/passwd", "..", "../static2/x"])
    def test_traversal_falls_back_to_index(self, static: Path, path: str) -> None:
        """Test that traversal falls back to index."""
        assert api_mod.static_file(path, static) == static / "index.html"


class TestLoginThrottle:
    """Tests for login throttle."""

    def test_throttle_is_per_account_despite_ip_spoofing(self, client: TestClient) -> None:
        """Rotating the client-IP headers must not lift the per-email cap.

        A brute-force against one account trips the throttle even from fresh IPs.
        """
        api_mod.reset_login_attempts()
        last: Response | None = None
        for i in range(api_mod.LOGIN_MAX_ATTEMPTS + 2):
            last = client.post(
                "/api/auth/login",
                json={"email": "victim@example.com", "password": "wrong"},
                headers={"X-Real-IP": f"10.0.0.{i}"},  # a different IP each attempt
            )
        assert must(last).status_code == 429


class TestClientIp:
    """The forwarding headers are a proxy's word, so they count only from a proxy's address."""

    @staticmethod
    def _request(peer: str, headers: dict[str, str]) -> Request:
        scope: dict[str, object] = {
            "type": "http",
            "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
            "client": (peer, 1234),
        }
        return Request(scope)

    @pytest.mark.parametrize("peer", ["127.0.0.1", "10.1.2.3", "172.18.0.5", "192.168.1.9", "::1"])
    def test_a_proxys_headers_are_believed(self, peer: str) -> None:
        """From a loopback or private peer: X-Real-IP first, then the first X-Forwarded-For hop."""
        assert api_mod.client_ip(self._request(peer, {"X-Real-IP": "203.0.113.7"})) == "203.0.113.7"
        assert api_mod.client_ip(self._request(peer, {"X-Forwarded-For": "203.0.113.8, 10.0.0.1"})) == "203.0.113.8"
        assert api_mod.client_ip(self._request(peer, {})) == peer

    @pytest.mark.parametrize("peer", ["203.0.113.50", "8.8.8.8", "2606:4700::1111", "2001:db8::1", "testclient"])
    def test_anyone_elses_headers_are_their_own_claim(self, peer: str) -> None:
        """A connection from the open internet can't choose the address it is counted under."""
        spoofed = {"X-Real-IP": "1.2.3.4", "X-Forwarded-For": "5.6.7.8"}
        assert api_mod.client_ip(self._request(peer, spoofed)) == peer


def test_pollo_balance_accepts_fractional_credits(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Pollo reports fractional credits (e.g. 1.54); the balance route must not 500 on them."""

    def balance(api_key: str) -> dict[str, float]:
        return {"availableCredits": 1.5400000000008731, "totalCredits": 42026}

    monkeypatch.setattr(routes_settings, "get_credit_balance", balance)
    r = client.get("/api/chat/pollo-balance")
    assert r.status_code == 200
    assert number(r, "availableCredits") == pytest.approx(1.54)

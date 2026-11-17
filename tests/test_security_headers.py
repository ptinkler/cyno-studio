"""Every response carries the security headers; served files are sandboxed; nginx's copy of the policy matches."""

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from web.core.security_headers import FILE_CSP, PAGE_CSP, csp_for

pytest_plugins = ["tests.api_fixtures"]

NGINX_HEADERS = Path(__file__).parent.parent / "nginx" / "security-headers.inc"


def test_api_responses_carry_the_page_policy(client: TestClient) -> None:
    """A JSON reply still says nosniff and gets the policy (the SPA is served through the same app)."""
    r = client.get("/api/auth/status")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["referrer-policy"] == "same-origin"
    assert r.headers["content-security-policy"] == PAGE_CSP


@pytest.mark.parametrize("path", ["/api/chat/media/c/x.svg", "/api/media/thumb/lib:x.png", "/api/public-media/tok"])
def test_served_files_are_sandboxed(path: str) -> None:
    """A file opened on its own can't run script."""
    assert csp_for(path) == FILE_CSP


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_api_docs_are_left_alone(path: str) -> None:
    """The interactive docs load scripts from a CDN, so they get no policy."""
    assert csp_for(path) is None


def test_the_page_policy_blocks_remote_pictures_and_inline_script() -> None:
    """The point of it: no pictures from elsewhere (but the avatars), no inline script, no framing."""
    assert "script-src 'self'" in PAGE_CSP
    assert "frame-ancestors 'none'" in PAGE_CSP
    assert "img-src 'self' data: blob: https://lh3.googleusercontent.com" in PAGE_CSP
    assert "unsafe-eval" not in PAGE_CSP


class TestNginxHeaders:
    """The nginx config is its own defence for the pages it serves: judged on its own, not against the app's."""

    @pytest.fixture
    def policy(self) -> str:
        """The Content-Security-Policy nginx sends."""
        match = re.search(r'add_header Content-Security-Policy "([^"]+)" always;', NGINX_HEADERS.read_text())
        assert match
        return match.group(1)

    def test_scripts_only_from_here_and_nothing_embeds_it(self, policy: str) -> None:
        """No inline or remote script, no plugins, no framing."""
        directives = dict(d.strip().split(" ", 1) for d in policy.split(";") if " " in d.strip())
        assert directives["script-src"] == "'self'"
        assert directives["frame-ancestors"] == "'none'"
        assert directives["object-src"] == "'none'"
        assert "unsafe-eval" not in policy

    def test_remote_pictures_are_limited_to_the_avatar_hosts(self, policy: str) -> None:
        """Pictures come from here, data/blob URLs, or the two sign-in avatar hosts, so a reply can't ping elsewhere."""
        img = next(d.strip() for d in policy.split(";") if d.strip().startswith("img-src"))
        remote = [token for token in img.split() if token.startswith("http")]
        assert remote == ["https://lh3.googleusercontent.com", "https://pbs.twimg.com"]

    def test_every_page_location_includes_them(self) -> None:
        """add_header in a location replaces the server's, so each location the pages come from includes the file."""
        conf = (NGINX_HEADERS.parent / "nginx.conf").read_text()
        assert conf.count("include /etc/nginx/security-headers.inc;") == 2

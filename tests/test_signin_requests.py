"""A refused sign-in lands on the admin's pending list; approving it lets that identity in."""

import pytest
from fastapi.testclient import TestClient

from tests.test_oauth_identity import TestCallback as _CallbackBase
from web.auth.signin_requests import SigninRequestList
from web.core.metadata import MetadataDB

pytest_plugins = ["tests.api_fixtures"]


class TestPendingApproval(_CallbackBase):
    """Reuses the X-callback fixture: the provider answers `x:42` with no email."""

    def test_a_refused_sign_in_is_listed(self, client: TestClient) -> None:
        """The refusal is remembered with who it was."""
        client.get("/api/auth/callback/x", follow_redirects=False)
        rows = SigninRequestList.model_validate(client.get("/api/signin-requests").json()).requests
        assert [(r.identity, r.name, r.approved) for r in rows] == [("x:42", "@alice", False)]

    def test_approving_lets_the_next_attempt_in(self, client: TestClient, db: MetadataDB) -> None:
        """Approve from the list, retry, and the account exists."""
        client.get("/api/auth/callback/x", follow_redirects=False)
        assert client.post("/api/signin-requests/approve", params={"identity": "x:42"}).status_code == 200
        r = client.get("/api/auth/callback/x", follow_redirects=False)
        assert r.headers["location"] == "/"
        assert db.count_users() == 1

    def test_denying_removes_it_and_keeps_them_out(self, client: TestClient, db: MetadataDB) -> None:
        """A denied request is gone, and a retry is refused again."""
        client.get("/api/auth/callback/x", follow_redirects=False)
        assert client.delete("/api/signin-requests", params={"identity": "x:42"}).json() == {"requests": []}
        r = client.get("/api/auth/callback/x", follow_redirects=False)
        assert r.headers["location"].startswith("/?auth=denied")
        assert db.count_users() == 0

    @pytest.mark.parametrize("method", ["post", "delete"])
    def test_an_unknown_identity_is_a_404(self, client: TestClient, method: str) -> None:
        """Nothing to approve or deny."""
        path = "/api/signin-requests" + ("/approve" if method == "post" else "")
        assert client.request(method, path, params={"identity": "x:nope"}).status_code == 404

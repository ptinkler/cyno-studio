"""Tests for web.core.get_task — task status polling."""

from unittest.mock import patch

import httpx2

from web.core.get_task import get_credit_balance, get_task_status
from web.types import JsonValue


class FakeResponse(httpx2.Response):
    """A response with a fixed status and either a JSON body or raw text."""

    def __init__(self, status_code: int, body: JsonValue = None, text: str = "") -> None:
        """Build the reply: a JSON body when there is one, else the text."""
        if body is None:
            super().__init__(status_code, text=text)
        else:
            super().__init__(status_code, json=body)


class TestGetTaskStatus:
    """Tests for get task status."""

    def test_success_response(self) -> None:
        """Test that success response."""
        mock_resp = FakeResponse(
            200, {"data": {"generations": [{"status": "succeed", "failMsg": None, "url": "https://video.com/out.mp4"}]}}
        )
        with patch("web.core.get_task.httpx2.request", return_value=mock_resp):
            results = get_task_status("task123", "api-key-123")
        assert len(results) == 1
        assert results[0] == ("succeed", None, "https://video.com/out.mp4", None)

    def test_success_with_credit(self) -> None:
        """Test that success with credit."""
        mock_resp = FakeResponse(
            200,
            {
                "data": {
                    "credit": 21,
                    "generations": [
                        {"status": "succeed", "failMsg": None, "url": "https://video.com/out.mp4", "credit": "21"}
                    ],
                }
            },
        )
        with patch("web.core.get_task.httpx2.request", return_value=mock_resp):
            results = get_task_status("task123", "api-key-123")
        assert results[0][3] == 21

    def test_success_with_top_level_credit_only(self) -> None:
        """When per-generation credit is missing, top-level credit is used."""
        mock_resp = FakeResponse(
            200,
            {
                "data": {
                    "credit": 15,
                    "generations": [{"status": "succeed", "failMsg": None, "url": "https://video.com/out.mp4"}],
                }
            },
        )
        with patch("web.core.get_task.httpx2.request", return_value=mock_resp):
            results = get_task_status("task123", "api-key-123")
        assert results[0][3] == 15

    def test_result_key_with_video_url_field(self) -> None:
        """API response with 'result' key and 'videoUrl' field."""
        mock_resp = FakeResponse(
            200,
            {
                "data": {
                    "credit": 21,
                    "result": [
                        {
                            "status": "succeed",
                            "failMsg": None,
                            "videoUrl": "https://cdn.pollo.ai/video.mp4",
                            "credit": "21",
                        }
                    ],
                }
            },
        )
        with patch("web.core.get_task.httpx2.request", return_value=mock_resp):
            results = get_task_status("task123", "api-key-123")
        assert results[0] == ("succeed", None, "https://cdn.pollo.ai/video.mp4", 21)

    def test_error_response(self) -> None:
        """Test that error response."""
        mock_resp = FakeResponse(
            200, {"data": {"generations": [{"status": "error", "failMsg": "Something broke", "url": None}]}}
        )
        with patch("web.core.get_task.httpx2.request", return_value=mock_resp):
            results = get_task_status("task123", "api-key-123")
        assert results[0][0] == "error"
        assert results[0][1] == "Something broke"

    def test_processing_status(self) -> None:
        """Test that processing status."""
        mock_resp = FakeResponse(
            200, {"data": {"generations": [{"status": "processing", "failMsg": None, "url": None}]}}
        )
        with patch("web.core.get_task.httpx2.request", return_value=mock_resp):
            results = get_task_status("task123", "api-key-123")
        assert results[0] == ("processing", None, None, None)

    def test_no_generations(self) -> None:
        """Test that no generations."""
        mock_resp = FakeResponse(200, {"data": {"generations": []}})
        with patch("web.core.get_task.httpx2.request", return_value=mock_resp):
            results = get_task_status("task123", "api-key-123")
        assert results == [("error", "No generations found.", None, None)]

    def test_api_error_status_code(self) -> None:
        """Test that api error status code."""
        mock_resp = FakeResponse(400, {"data": {"issues": [{"message": "Bad request"}]}})
        with patch("web.core.get_task.httpx2.request", return_value=mock_resp):
            results = get_task_status("task123", "api-key-123")
        assert results[0][0] == "error"
        assert results[0][1] == "Bad request"

    def test_api_error_no_issues(self) -> None:
        """Test that api error no issues."""
        mock_resp = FakeResponse(400, {"data": {"issues": []}})
        with patch("web.core.get_task.httpx2.request", return_value=mock_resp):
            # No issues means the for-loop doesn't trigger, returns HTTP error fallback
            results = get_task_status("task123", "api-key-123")
        assert results == [("error", "HTTP 400", None, None)]

    def test_multiple_generations(self) -> None:
        """Test that multiple generations."""
        mock_resp = FakeResponse(
            200,
            {
                "data": {
                    "generations": [
                        {"status": "succeed", "failMsg": None, "url": "https://v1.mp4"},
                        {"status": "processing", "failMsg": None, "url": None},
                    ]
                }
            },
        )
        with patch("web.core.get_task.httpx2.request", return_value=mock_resp):
            results = get_task_status("task123", "api-key-123")
        assert len(results) == 2

    def test_cloudflare_block_returns_cloudflare_blocked_status(self) -> None:
        """Test that cloudflare block returns cloudflare blocked status."""
        mock_resp = FakeResponse(403, text="<html><title>Just a moment...</title>cloudflare</html>")
        with (
            patch("web.core.get_task.httpx2.request", return_value=mock_resp),
            patch("web.core.get_task.is_cloudflare_block", return_value=True),
        ):
            results = get_task_status("task123", "api-key-123")
        assert results[0][0] == "cloudflare_blocked"
        assert "Cloudflare" in (results[0][1] or "")

    def test_headers_include_api_key(self) -> None:
        """Test that headers include api key."""
        mock_resp = FakeResponse(200, {"data": {"generations": [{"status": "succeed", "failMsg": None, "url": "x"}]}})
        with patch("web.core.get_task.httpx2.request", return_value=mock_resp) as mock_req:
            get_task_status("task123", "my-key")
        mock_req.assert_called_once_with(
            "GET",
            "https://pollo.ai/api/platform/generation/task123/status",
            headers={"x-api-key": "my-key"},
            timeout=30,
        )


class TestGetCreditBalance:
    """Tests for get credit balance."""

    def test_success(self) -> None:
        """Test that success."""
        mock_resp = FakeResponse(200, {"availableCredits": 500, "totalCredits": 1000})
        with patch("web.core.get_task.httpx2.get", return_value=mock_resp):
            result = get_credit_balance("api-key-123")
        assert result == {"availableCredits": 500, "totalCredits": 1000}

    def test_failure(self) -> None:
        """Test that failure."""
        mock_resp = FakeResponse(401)
        with patch("web.core.get_task.httpx2.get", return_value=mock_resp):
            result = get_credit_balance("bad-key")
        assert result is None

    def test_network_error(self) -> None:
        """Test that network error."""
        with patch("web.core.get_task.httpx2.get", side_effect=httpx2.ConnectError("timeout")):
            result = get_credit_balance("api-key-123")
        assert result is None

"""web.request_log keeps each user's provider-call log to themselves."""

import pytest

from web import request_log
from web.core import metadata


def _prompts():
    prompts: list[str] = []
    for entry in request_log.recent():
        request = entry.get("request")
        if isinstance(request, dict) and isinstance((prompt := request.get("prompt")), str):
            prompts.append(prompt)
    return prompts


def test_log_is_per_tenant() -> None:
    """Two users' provider calls go to separate per-tenant logs.

    So the Request log never shows one user another user's prompts/content.
    """
    token = metadata.set_tenant("user-a")
    try:
        request_log.record("venice", "POST", "/image/generate", {"prompt": "a-secret"})
    finally:
        metadata.reset_tenant(token)

    token = metadata.set_tenant("user-b")
    try:
        request_log.record("venice", "POST", "/image/generate", {"prompt": "b-secret"})
        assert _prompts() == ["b-secret"]  # B sees only B's
    finally:
        metadata.reset_tenant(token)

    token = metadata.set_tenant("user-a")
    try:
        assert _prompts() == ["a-secret"]  # A sees only A's
    finally:
        metadata.reset_tenant(token)


def test_entry_of_returns_the_log_entry_of_a_call_that_raised() -> None:
    """Test that an error leaving logged() carries its entry, even a builtin exception type."""
    with pytest.raises(ValueError, match="boom") as raised, request_log.logged("p", "POST", "/x", {"a": 1}):
        raise ValueError("boom")
    entry = request_log.entry_of(raised.value)
    assert entry is not None
    assert entry["error"] == "boom"


def test_entry_of_is_none_for_an_error_that_was_never_logged() -> None:
    """Test that an exception raised outside logged() has no entry."""
    assert request_log.entry_of(ValueError("plain")) is None

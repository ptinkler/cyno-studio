"""web.core.request_log keeps each user's provider-call log to themselves."""

from typing import TYPE_CHECKING

import pytest

from web.core import metadata, request_log

if TYPE_CHECKING:
    from web.types import ChatChunk


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


def test_chat_reply_logs_what_arrived_even_when_the_stream_stops_early() -> None:
    """Test that a reply the app stopped reading still shows its text and tool calls so far."""
    outcome: request_log.LogOutcome = {"status": None, "flags": None, "response": None}
    chunks: list[ChatChunk] = [
        {"choices": [{"delta": {"content": "Hel"}}]},
        {
            "choices": [
                {"delta": {"tool_calls": [{"index": 0, "function": {"name": "generate_image", "arguments": '{"pro'}}]}}
            ]
        },
        {"choices": [{"delta": {"content": "lo"}}]},
    ]
    stream = request_log.chat_reply(iter(chunks), outcome)
    next(stream)
    next(stream)
    stream.close()  # the consumer walked away mid-stream
    assert outcome["response"] == {
        "content": "Hel",
        "tool_calls": {"0": {"name": "generate_image", "arguments": '{"pro'}},
        "finish_reason": None,
        "usage": None,
    }

"""Parse OpenAI-style server-sent chat completion streams.

Shared by the OpenRouter and Venice clients.
"""

import json
import time
from collections.abc import Callable, Iterable, Iterator
from typing import cast

from web.jsonutil import as_object, loads
from web.types import ChatChunk, JsonValue


def timeout_message(seconds: int) -> str:
    """The error text for a model that ran past its time limit."""
    return f"The model didn't finish within {seconds}s"


def _data_payload(line: str) -> str | None:
    """The payload of an SSE "data:" line (None for separators and ":" keep-alives)."""
    return line[5:].strip() if line.startswith("data:") else None


def _parse_chunk(payload: str) -> dict[str, JsonValue] | None:
    """A payload's JSON object, or None when it isn't readable JSON."""
    try:
        return as_object(loads(payload))
    except json.JSONDecodeError:
        return None


def _error_message(err: JsonValue) -> str:
    """The text of a chunk's error value (a bare string, or an object with a message)."""
    if isinstance(err, dict):
        message = err.get("message")
        return message if isinstance(message, str) else str(message)
    return str(err)


def _check_deadline(deadline: float | None, limit: int, error: Callable[[str, int | None], Exception]) -> None:
    """Raise `error` (a 504) once the whole-call time limit has passed."""
    if deadline and time.monotonic() > deadline:
        raise error(timeout_message(limit), 504)


def chat_chunks(
    lines: Iterable[str],
    error: Callable[[str, int | None], Exception],
    max_seconds: float | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> Iterator[ChatChunk]:
    """The parsed chunk dicts from a response's lines, until "[DONE]".

    Blank separators and ":" keep-alives are skipped but still checked
    against `max_seconds` (a cap on the whole call) and `should_stop`
    (polled on every line, so a cancel is noticed while no tokens flow).
    An error chunk raises `error(message, status)`.
    """
    deadline = time.monotonic() + max_seconds if max_seconds else None
    limit = int(max_seconds) if max_seconds else 0
    for line in lines:
        if should_stop and should_stop():
            return
        _check_deadline(deadline, limit, error)
        payload = _data_payload(line)
        if payload is None:
            continue
        if payload == "[DONE]":
            return
        chunk = _parse_chunk(payload)
        if chunk is None:
            continue
        err = chunk.get("error")
        if err:
            raise error(_error_message(err), None)
        yield cast("ChatChunk", chunk)

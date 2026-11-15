"""Parse OpenAI-style server-sent chat completion streams.

Shared by the OpenRouter and Venice clients.
"""

import json
import time
from collections.abc import Callable, Iterable, Iterator
from typing import cast

from web.types import ChatChunk, JsonValue


def timeout_message(seconds: int) -> str:
    """The error text for a model that ran past its time limit."""
    return f"The model didn't finish within {seconds}s"


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
        if deadline and time.monotonic() > deadline:
            raise error(timeout_message(limit), 504)
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if payload == "[DONE]":
            return
        try:
            chunk = cast("dict[str, JsonValue]", json.loads(payload))
        except json.JSONDecodeError:
            continue
        err = chunk.get("error")
        if err:
            if isinstance(err, dict):
                message = err.get("message")
                raise error(message if isinstance(message, str) else str(message), None)
            raise error(str(err), None)
        yield cast("ChatChunk", chunk)

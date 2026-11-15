"""Venice text models: streamed chat completions and their cost."""

import logging
import time
from collections.abc import Iterator
from http import HTTPStatus

import httpx

from web.core import request_log, sse
from web.jsonutil import as_number, as_object
from web.providers.openrouter import CHAT_TIMEOUT
from web.providers.specs import StreamOptions
from web.providers.venice import client, models
from web.providers.venice.catalogue import PREFIX, usd_or_none
from web.providers.venice.errors import StreamDroppedError, VeniceError
from web.types import ChatChunk, JsonValue

log = logging.getLogger(__name__)


def stream_chat(
    model_id: str, messages: list[dict[str, JsonValue]], options: StreamOptions | None = None
) -> Iterator[ChatChunk]:
    """Yield chat-completion chunks with usage cost in USD.

    Cost comes from Venice's reported value or token counts and model prices.
    Venice has no session concept, so ``session_id`` only labels the request in the debug log.
    """
    options = options or StreamOptions()
    log.debug("venice chat %s (session %s)", model_id, options.session_id)
    body: dict[str, JsonValue] = {
        "model": model_id[len(PREFIX) :],
        "messages": messages,
        "stream": True,
        "stream_options": {"include_usage": True},
        "venice_parameters": {"include_venice_system_prompt": False},
    }
    if options.tools:
        body["tools"] = options.tools
    start = time.monotonic()
    try:
        with (
            request_log.logged("venice", "POST", "/chat/completions", body) as outcome,
            client.http.stream(
                "POST",
                f"{client.VENICE_BASE}/chat/completions",
                headers=client.headers(),
                json=body,
                timeout=CHAT_TIMEOUT,
            ) as resp,
        ):
            outcome["status"] = resp.status_code
            if resp.status_code >= HTTPStatus.BAD_REQUEST:
                resp.read()
                outcome["response"] = request_log.response_of(resp)
            client.raise_for_response(resp)
            chunks = sse.chat_chunks(resp.iter_lines(), _stream_error, options.max_seconds, options.should_stop)
            for chunk in request_log.chat_reply(chunks, outcome):
                usage = chunk.get("usage")
                if usage:
                    chunk["usage"] = {**usage, "cost": _chat_cost(model_id, usage, as_object(chunk).get("cost"))}
                yield chunk
    except (httpx.RemoteProtocolError, httpx.ReadError, httpx.WriteError) as e:
        raise StreamDroppedError(round(time.monotonic() - start), e) from e


def _stream_error(message: str, status: int | None) -> VeniceError:
    """A stream failure: the time cap as it is, an error chunk labelled as Venice's."""
    return VeniceError(message if status else f"Venice: {message}", status)


def _chat_cost(model_id: str, usage: dict[str, JsonValue], top_level_cost: JsonValue = None) -> float | None:
    cost = usd_or_none(usage.get("cost")) if usage.get("cost") is not None else usd_or_none(top_level_cost)
    if cost is not None:
        return cost
    try:
        info = models.find(models.get_catalogue().text, "text", model_id)
    except VeniceError:
        return None
    if info.prompt_price is None or info.completion_price is None:
        return None
    return round(
        (as_number(usage.get("prompt_tokens")) or 0) * info.prompt_price
        + (as_number(usage.get("completion_tokens")) or 0) * info.completion_price,
        6,
    )

"""A mock Venice API (``/venice/api/v1``): catalogue, chat (with tool calls), images, videos and the balance.

The model picks the behaviour:

text   mock-chat (echoes), mock-artist (asks for an image through generate_image), mock-chat-drop (cuts the stream)
image  mock-image (+ its edit twin), mock-image-slow, mock-image-drop (connection cut, like the VPN's 60 s idle cut),
       mock-image-filtered (content filter), mock-image-rejected (HTTP 400 with Venice's message)
video  mock-text-to-video / mock-image-to-video (one entry), mock-reference-to-video, mock-broken-text-to-video
       (the job fails)
"""

import asyncio
import base64
import json
import uuid
from collections.abc import AsyncIterator, Mapping

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from tests.mock_providers import media
from tests.mock_providers.state import Recorded, state
from web.jsonutil import as_list, as_object, as_str
from web.types import JsonValue

router = APIRouter(prefix="/venice/api/v1")


class CutOnPurposeError(ConnectionAbortedError):
    """Raised mid-response so the server drops the connection, as a flaky network would."""

    def __init__(self) -> None:
        """Build the fixed message."""
        super().__init__("mock: connection cut on purpose")


def _text(value: JsonValue) -> str:
    return as_str(value) or ""


_VIDEO = {"durations": ["5s", "10s"], "resolutions": ["720p"], "aspect_ratios": ["16:9", "9:16"], "audio": False}

MODELS: dict[str, list[dict[str, JsonValue]]] = {
    "text": [
        {
            "id": "mock-chat",
            "model_spec": {
                "name": "Mock Chat",
                "pricing": {"input": {"usd": 0.1}, "output": {"usd": 0.2}},
                "capabilities": {"supportsVision": True},
            },
        },
        {
            "id": "mock-artist",
            "model_spec": {
                "name": "Mock Artist",
                "pricing": {"input": {"usd": 0.1}, "output": {"usd": 0.2}},
                "capabilities": {"supportsVision": True, "supportsFunctionCalling": True},
            },
        },
        {"id": "mock-chat-drop", "model_spec": {"name": "Mock Chat (drops)", "capabilities": {}}},
    ],
    "image": [
        {
            "id": f"mock-image{suffix}",
            "model_spec": {
                "name": f"Mock Image{label}",
                "pricing": {"generation": {"usd": 0.01}},
                "constraints": {"aspectRatios": ["1:1", "16:9"], "resolutions": ["1K"]},
            },
        }
        for suffix, label in (
            ("", ""),
            ("-slow", " (slow)"),
            ("-drop", " (drops)"),
            ("-filtered", " (filtered)"),
            ("-rejected", " (rejected)"),
        )
    ],
    "inpaint": [
        {
            "id": "mock-image-edit",
            "model_spec": {
                "name": "Mock Image Edit",
                "pricing": {"inpaint": {"usd": 0.02}},
                "constraints": {"maxInputImages": 3},
            },
        }
    ],
    "video": [
        {
            "id": "mock-text-to-video",
            "model_spec": {"name": "Mock Video", "constraints": {**_VIDEO, "model_type": "text-to-video"}},
        },
        {
            "id": "mock-image-to-video",
            "model_spec": {"name": "Mock Video I2V", "constraints": {**_VIDEO, "model_type": "image-to-video"}},
        },
        {
            "id": "mock-reference-to-video",
            "model_spec": {"name": "Mock Ref Video", "constraints": {**_VIDEO, "model_type": "image-to-video"}},
        },
        {
            "id": "mock-broken-text-to-video",
            "model_spec": {"name": "Mock Broken Video", "constraints": {**_VIDEO, "model_type": "text-to-video"}},
        },
    ],
}


async def _record(request: Request) -> dict[str, JsonValue]:
    """Note the request for the control API and return its JSON body ({} when it has none)."""
    raw = await request.body()
    body: JsonValue = json.loads(raw) if raw else None
    state.requests.append(Recorded("venice", request.method, request.url.path, body, dict(request.query_params)))
    return as_object(body)


def _balance_headers() -> dict[str, str]:
    return {"x-venice-balance-usd": str(state.settings.venice_usd)}


async def _cut_after(seconds: float) -> AsyncIterator[bytes]:
    """Send headers, wait, then drop the connection without a body: the client sees RemoteProtocolError."""
    await asyncio.sleep(seconds)
    raise CutOnPurposeError
    yield b""  # makes this a generator


def _dropped(seconds: float) -> StreamingResponse:
    return StreamingResponse(_cut_after(seconds), media_type="application/json")


@router.get("/models")
async def models(request: Request) -> JSONResponse:
    """The catalogue of one kind (text / image / inpaint / video)."""
    await _record(request)
    return JSONResponse({"data": MODELS.get(request.query_params.get("type", ""), [])}, headers=_balance_headers())


@router.get("/api_keys/rate_limits")
async def rate_limits(request: Request) -> JSONResponse:
    """The key's balances."""
    await _record(request)
    s = state.settings
    return JSONResponse(
        {"data": {"balances": {"USD": s.venice_usd, "BUNDLED_CREDITS": s.venice_credits, "DIEM": s.venice_diem}}}
    )


def _last_text(messages: list[JsonValue]) -> str:
    """The last user message's text (its text parts, when it has images too)."""
    for message in reversed(messages):
        m = as_object(message)
        if m.get("role") != "user":
            continue
        content = m.get("content")
        if isinstance(content, str):
            return content
        parts = [as_object(p) for p in as_list(content)]
        return " ".join(_text(p.get("text")) for p in parts if p.get("type") == "text")
    return ""


def _sse(chunk: Mapping[str, JsonValue]) -> bytes:
    return f"data: {json.dumps(chunk)}\n\n".encode()


def _reply_chunks(model: str, messages: list[JsonValue], tools: list[JsonValue]) -> list[dict[str, JsonValue]]:
    """The streamed chunks of a reply: text, or (mock-artist, before its tool has run) a generate_image call."""
    usage: dict[str, JsonValue] = {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.0001}
    asked_tool = any(as_object(m).get("role") == "tool" for m in messages)
    if model == "mock-artist" and tools and not asked_tool:
        call = {
            "index": 0,
            "id": f"call_{uuid.uuid4().hex[:8]}",
            "type": "function",
            "function": {"name": "generate_image", "arguments": json.dumps({"prompt": _last_text(messages)})},
        }
        return [
            {"choices": [{"delta": {"tool_calls": [call]}}]},
            {"choices": [{"delta": {}, "finish_reason": "tool_calls"}], "usage": usage},
        ]
    text = "Here it is." if asked_tool else f"You said: {_last_text(messages)}"
    words = [f"{w} " for w in text.split(" ")]
    return [
        *({"choices": [{"delta": {"content": w}}]} for w in words),
        {"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": usage},
    ]


async def _stream(chunks: list[dict[str, JsonValue]], *, drop: bool) -> AsyncIterator[bytes]:
    for i, chunk in enumerate(chunks):
        if drop and i == 1:
            raise CutOnPurposeError
        yield _sse(chunk)
        await asyncio.sleep(0.02)
    yield b"data: [DONE]\n\n"


@router.post("/chat/completions")
async def chat(request: Request) -> StreamingResponse:
    """A streamed chat reply."""
    body = await _record(request)
    model = _text(body.get("model"))
    chunks = _reply_chunks(model, as_list(body.get("messages")), as_list(body.get("tools")))
    return StreamingResponse(_stream(chunks, drop=model == "mock-chat-drop"), media_type="text/event-stream")


async def _image_response(model: str, color: str) -> Response:
    s = state.settings
    if model == "mock-image-drop":
        return _dropped(s.drop_after_seconds)
    if model == "mock-image-rejected":
        return JSONResponse({"error": "Mock: this prompt is rejected"}, status_code=400)
    if model == "mock-image-slow":
        await asyncio.sleep(s.slow_seconds)
    headers = {"x-venice-is-content-violation": "true"} if model == "mock-image-filtered" else {}
    return Response(media.png(color), media_type="image/png", headers={**headers, **_balance_headers()})


@router.post("/image/generate")
async def generate_image(request: Request) -> Response:
    """A new picture: JSON with base64 images, like Venice."""
    body = await _record(request)
    answer = await _image_response(_text(body.get("model")), "teal")
    if answer.media_type != "image/png" or answer.headers.get("x-venice-is-content-violation"):
        return answer  # a failure, or a filtered picture (Venice sends those as bytes with the flag)
    return JSONResponse({"images": [base64.b64encode(media.png("teal")).decode()]}, headers=_balance_headers())


@router.post("/image/multi-edit")
async def edit_image(request: Request) -> Response:
    """An edit of the reference images: the picture's bytes, like Venice."""
    body = await _record(request)
    return await _image_response(_text(body.get("model")).removesuffix("-edit"), "orange")


@router.post("/video/quote")
async def quote(request: Request) -> JSONResponse:
    """The price of a video."""
    await _record(request)
    return JSONResponse({"quote": 0.25})


@router.post("/video/queue")
async def queue(request: Request) -> JSONResponse:
    """Start a video job."""
    await _record(request)
    queue_id = uuid.uuid4().hex
    state.video_checks[queue_id] = 0
    return JSONResponse({"queue_id": queue_id})


@router.post("/video/retrieve")
async def retrieve(request: Request) -> Response:
    """A job's status, or the finished video's bytes."""
    body = await _record(request)
    queue_id = _text(body.get("queue_id"))
    if _text(body.get("model")).startswith("mock-broken"):
        return JSONResponse({"status": "FAILED", "error": "Mock: render failed"})
    checks = state.video_checks.get(queue_id, 0) + 1
    state.video_checks[queue_id] = checks
    if checks <= state.settings.video_polls:
        return JSONResponse({"status": "PROCESSING"})
    return Response(media.mp4(), media_type="video/mp4")

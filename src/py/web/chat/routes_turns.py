"""HTTP routes for running turns and managing generated media.

Turn, retry, and edit responses stream events from a worker; the engine lives
in `turn.py` and generation helpers live in `generation.py`.
"""

import json
import logging
import queue
import threading
import uuid
from collections.abc import Callable, Iterator

from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from web.chat.audio import audio_params
from web.chat.catalogue import fit_video_params, model_info
from web.chat.deps import router, start_lock
from web.chat.generation import (
    enhance_prompt,
)
from web.chat.helpers import (
    conversation_dir,
    message_out,
    remember_settings,
    require_conv,
    require_idle,
    require_text_provider,
    saved_media,
    shown_message,
)
from web.chat.models import EditMessage, EnhancePrompt, EstimateRequest, RetryMessage, SendMessage, TurnSettings
from web.chat.schemas import ShownMessage
from web.chat.turn import Turn
from web.chat.turn_base import Reword, TurnLink
from web.chat.workers import ctx_thread
from web.core.metadata import get_db
from web.core.metadata.models import ChatMessage
from web.media.kinds import kind_of
from web.providers import openrouter, pollo
from web.providers.specs import CostQuery
from web.types import JsonValue
from web.uploads.files import safe_filename

log = logging.getLogger(__name__)

# Live turns' cancel flags, keyed by the assistant message id (set by the
# cancel route, checked by the running Turn).
_cancel_events: dict[int, threading.Event] = {}


@router.post("/enhance-prompt")
def api_enhance_prompt(data: EnhancePrompt) -> dict[str, str | float]:
    """Rewrite a prompt with the chat model.

    Only ever called by the user's
    Enhance button — generations themselves always use the prompt as written.
    """
    try:
        prompt, cost = enhance_prompt(data.model, data.prompt, "video" if data.kind == "video" else "image")
    except (openrouter.OpenRouterError, ValueError) as e:
        raise HTTPException(502, str(e)) from e
    return {"prompt": prompt, "cost": cost}


@router.post("/estimate")
def api_estimate(data: EstimateRequest) -> dict[str, JsonValue]:
    """Estimate a Pollo generation's credit cost for the composer.

    Returns a null estimate for other providers or when Pollo cannot price it.
    """
    if not pollo.is_pollo(data.model):
        return {"estimate": None}
    duration, ratio, resolution = data.duration, data.aspect_ratio, data.resolution
    if data.kind == "video":
        duration, ratio, resolution = fit_video_params(data.model, duration, ratio, resolution)
    return {
        "estimate": pollo.estimate_cost(
            data.model,
            CostQuery(
                data.kind if data.kind in ("video", "audio") else "image",
                duration,
                ratio,
                resolution,
                generate_audio=data.generate_audio,
                n_images=data.n_images,
                prompt=data.prompt,
                audio=audio_params(data.audio_options),
            ),
        )
    }


@router.get("/audio/voices")
def api_audio_voices(page: int = 1, page_size: int = 50, language: str = "", gender: str = "") -> dict[str, JsonValue]:
    """Pollo's official TTS voices, for the speech models' voice picker."""
    if not pollo.is_configured():
        raise HTTPException(503, "No Pollo API key set — add one in Settings → Keys")
    try:
        return pollo.list_voices(page, min(page_size, 100), language=language, gender=gender)
    except openrouter.OpenRouterError as e:
        raise HTTPException(502, str(e)) from e


@router.post("/messages/{message_id}/cancel")
def api_cancel_message(message_id: int) -> dict[str, bool]:
    """Request cancellation of a running assistant message."""
    ev = _cancel_events.get(message_id)
    if ev:
        ev.set()
    return {"cancelled": bool(ev)}


def _prompt_optional(settings: TurnSettings) -> bool:
    """Tools take a source file and no prompt (e.g. upscale the chat's latest video)."""
    if settings.mode == "image":
        return bool((model_info("image", settings.image_model) or {}).get("no_prompt"))
    if settings.mode == "video":
        return bool((model_info("video", settings.video_model) or {}).get("no_prompt"))
    return False


@router.post("/conversations/{conv_id}/messages")
def api_send_message(conv_id: str, data: SendMessage) -> StreamingResponse:
    """Create a user message and stream its assistant turn."""
    require_text_provider(data.mode)
    conv = require_conv(conv_id)
    content = data.content.strip()
    if not content and not data.attachments and not _prompt_optional(data):
        raise HTTPException(400, "Message is empty")

    conv_dir = conversation_dir(conv_id)
    media: list[dict[str, JsonValue]] = []
    for name in data.attachments[:8]:
        if not (conv_dir / safe_filename(name)).is_file():
            raise HTTPException(400, f"Attachment not found: {name}")
        # audio here is a lip-sync track, driven onto a portrait
        media.append(saved_media(kind_of(name) or "image", "upload", name))

    db = get_db()
    lane = "gallery" if data.lane == "gallery" else None
    with start_lock:
        # One reply at a time in the chat (gallery exchanges run side by side):
        # a second send while one streams would be a double charge, and its
        # reply would be written against a half-finished history.
        require_idle(conv_id, lane)
        user_msg = db.add_chat_message(conv_id, "user", content, media=media, mode=data.mode, lane=lane)
        remember_settings(conv, data)
        return _start_turn(conv_id, data, user_msg, parent_id=user_msg.id, lane=lane)


@router.post("/conversations/{conv_id}/retry")
def api_retry(conv_id: str, data: RetryMessage) -> StreamingResponse:
    """Generate another version of an assistant reply, as a new branch beside it.

    The old reply and everything after it stay on their branch.
    """
    require_text_provider(data.mode)
    conv = require_conv(conv_id)
    msg = get_db().get_chat_message(data.message_id)
    if not msg or msg.conversation_id != conv_id or msg.role != "assistant":
        raise HTTPException(400, "Can only retry an assistant message in this conversation")
    with start_lock:
        require_idle(conv_id, msg.lane)
        # The retry runs in the mode selected now; the prompt's mode tag follows it
        if msg.parent_id:
            get_db().update_chat_message(msg.parent_id, mode=data.mode)
        remember_settings(conv, data)
        return _start_turn(conv_id, data, None, parent_id=msg.parent_id, lane=msg.lane)


@router.post("/conversations/{conv_id}/edit")
def api_edit(conv_id: str, data: EditMessage) -> StreamingResponse:
    """Resend a user message with new text, as a new branch beside it (same attachments), and stream a fresh reply.

    The original prompt and
    everything after it stay on their branch.
    """
    require_text_provider(data.mode)
    conv = require_conv(conv_id)
    db = get_db()
    msg = db.get_chat_message(data.message_id)
    if not msg or msg.conversation_id != conv_id or msg.role != "user":
        raise HTTPException(400, "Can only edit a user message in this conversation")
    content = data.content.strip()
    if not content and not msg.media:
        raise HTTPException(400, "Message is empty")
    media = [{**item, "id": uuid.uuid4().hex[:8]} for item in msg.media]
    with start_lock:
        require_idle(conv_id, msg.lane)
        user_msg = db.add_chat_message(
            conv_id, "user", content, media=media, parent_id=msg.parent_id, mode=data.mode, lane=msg.lane
        )
        remember_settings(conv, data)
        return _start_turn(conv_id, data, user_msg, parent_id=user_msg.id, lane=msg.lane)


def _sse(event: dict[str, JsonValue]) -> str:
    return f"data: {json.dumps(event)}\n\n"


def _start_turn(
    conv_id: str, settings: TurnSettings, user_msg: ChatMessage | None, parent_id: int | None, lane: str | None = None
) -> StreamingResponse:
    model = {"image": settings.image_model, "video": settings.video_model, "audio": settings.audio_model}.get(
        settings.mode, settings.text_model
    )
    assistant = get_db().add_chat_message(
        conv_id, "assistant", "", model=model, status="streaming", parent_id=parent_id, mode=settings.mode, lane=lane
    )
    start: dict[str, JsonValue] = {
        "type": "start",
        "user_message": message_out(user_msg) if user_msg else None,
        "assistant_message": message_out(assistant),
    }
    return _stream_turn(conv_id, settings, assistant.id, start)


def _stream_turn(
    conv_id: str,
    settings: TurnSettings,
    assistant_id: int,
    start: dict[str, JsonValue],
    reword: Reword | None = None,
) -> StreamingResponse:
    """Run a Turn against `assistant_id` and stream its events as SSE.

    Used
    both for a brand-new reply and for generating an existing one again.

    A `reword` has an `after` that runs once the Turn has finished and saved; if it returns a message
    that goes out as a final "done", so the UI ends on its state.
    """
    events: queue.Queue[dict[str, JsonValue] | None] = queue.Queue()
    cancel = threading.Event()
    _cancel_events[assistant_id] = cancel

    def worker() -> None:
        try:
            Turn(conv_id, settings, assistant_id, TurnLink(events.put, cancel), reword).run()
            if reword and reword.after and (msg := reword.after()):
                events.put({"type": "done", "message": message_out(msg)})
        finally:
            _cancel_events.pop(assistant_id, None)
            events.put(None)

    # Run in a copy of the current context so the turn's DB writes/reads are
    # scoped to the signed-in user (tenant) and use their keys — a plain thread
    # would not inherit those contextvars.
    ctx_thread(worker, name=f"chat-turn-{assistant_id}").start()

    def stream() -> Iterator[str]:
        yield _sse(start)
        while True:
            try:
                ev = events.get(timeout=15)
            except queue.Empty:
                yield ": keep-alive\n\n"
                continue
            if ev is None:
                return
            yield _sse(ev)

    return StreamingResponse(
        stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


class RewordMessage(TurnSettings):
    """Turn settings and assistant message ID for regenerating only its text."""

    message_id: int  # the assistant reply whose words to generate again
    # Edit text: how to change the words ("shorter", "make it rhyme"). Empty =
    # Redo text: write them again from the conversation alone.
    instruction: str = ""


def _text_versions_json(items: list[dict[str, JsonValue]], shown: int) -> str:
    return json.dumps({"items": items, "shown": shown})


def _require_rewordable(msg: ChatMessage | None, conv_id: str, instruction: str) -> ChatMessage:
    """The assistant message to reword, or the HTTP error saying why it can't be."""
    if not msg or msg.conversation_id != conv_id or msg.role != "assistant":
        raise HTTPException(400, "Can only reword an assistant message in this conversation")
    if msg.status == "streaming":
        raise HTTPException(409, "Wait for the reply to finish first")
    if any(i.get("status") == "pending" for i in msg.media):
        raise HTTPException(409, "Wait for this reply's media to finish first")
    if instruction and not (msg.content or "").strip():
        raise HTTPException(400, "This reply has no words to edit yet")
    return msg


def _reword_finisher(
    message_id: int, previous: str, items: list[dict[str, JsonValue]], text_model: str | None
) -> Callable[[], ChatMessage | None]:
    """A callback that files the new words as the latest version (or restores the old ones)."""

    def after() -> ChatMessage | None:
        """File the new words as the latest version — or, if none came, put the old ones back."""
        db = get_db()
        done = db.get_chat_message(message_id)
        if not done:
            return None
        if not (done.content or "").strip():
            return db.update_chat_message(message_id, content=previous)
        versions: list[dict[str, JsonValue]] = [*items, {"content": done.content, "model": text_model}]
        return db.update_chat_message(message_id, text_versions_json=_text_versions_json(versions, len(versions) - 1))

    return after


@router.post("/conversations/{conv_id}/reword")
def api_reword(conv_id: str, data: RewordMessage) -> StreamingResponse:
    """Write this reply's words again, keeping the pictures it already made.

    Unlike Retry, which starts a whole new turn on a new branch (new words AND
    new media), this re-runs only the chat model, with its tools withheld, and
    overwrites the text on the same message. The media items are left exactly
    as they are, so a reply whose picture is right but whose words aren't can
    be fixed without paying for the picture again.
    """
    require_text_provider("text")
    conv = require_conv(conv_id)
    db = get_db()
    instruction = data.instruction.strip()
    msg = _require_rewordable(db.get_chat_message(data.message_id), conv_id, instruction)
    previous = msg.content or ""
    # Only the words are generated again, whatever mode the composer is in.
    settings = data.model_copy(update={"mode": "text"})
    # The words being replaced were paid for too (and stay as a version you
    # can switch back to), so the reply's cost keeps everything spent on it.
    spent = msg.cost or 0.0
    items: list[dict[str, JsonValue]] = msg.text_versions[0]
    if not items:  # first rewrite: the words it has become version 1
        items = [{"content": previous, "model": msg.model}]
    message_id = msg.id
    after = _reword_finisher(message_id, previous, items, settings.text_model)

    with start_lock:
        require_idle(conv_id, msg.lane)
        if (db.get_chat_message(message_id) or msg).status == "streaming":
            raise HTTPException(409, "Wait for the reply to finish first")
        remember_settings(conv, data)
        db.update_chat_message(message_id, content="", status="streaming", error=None)
        start: dict[str, JsonValue] = {
            "type": "start",
            "user_message": None,
            "assistant_message": {**message_out(msg), "content": "", "status": "streaming"},
            "replaces": msg.id,
        }
        reword = Reword(spent, (previous, instruction) if instruction else None, after)
        return _stream_turn(conv_id, settings, message_id, start, reword)


class ShowTextVersion(BaseModel):
    """Which of a reply's wordings to show (0 = the first)."""

    index: int


@router.post("/messages/{message_id}/text-version")
def api_show_text_version(message_id: int, data: ShowTextVersion) -> ShownMessage:
    """Switch a reply to one of its earlier (or later) wordings.

    The chosen words become the reply's text — what's shown and what the chat
    model sees from then on. Its pictures are untouched; nothing is generated.
    """
    db = get_db()
    msg = db.get_chat_message(message_id)
    if not msg or msg.role != "assistant":
        raise HTTPException(404, "Message not found")
    if msg.status == "streaming":
        raise HTTPException(409, "Wait for the reply to finish first")
    items, _ = msg.text_versions
    if not 0 <= data.index < len(items):
        raise HTTPException(400, "No such version")
    content = items[data.index]["content"]
    updated = db.update_chat_message(
        message_id,
        content=content if isinstance(content, str) else "",
        text_versions_json=_text_versions_json(items, data.index),
    )
    if not updated:
        raise HTTPException(404, "Message not found")
    return shown_message(updated)

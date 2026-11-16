"""Actions on a chat's media cards: pin, favourite, regenerate, switch version, and active generations."""

import logging
import threading
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from fastapi import HTTPException
from pydantic import BaseModel

from web.chat import polling
from web.chat.audio import AudioJob, submit_audio_generation
from web.chat.catalogue import fit_video_params
from web.chat.constants import DEFAULT_IMAGE_LIMIT
from web.chat.deps import router, start_lock
from web.chat.errors import InvalidMediaItemError
from web.chat.generation import (
    HistoryShape,
    ImageAsk,
    conversation_instructions,
    exchange_fields,
    failure_fields,
    image_context,
    is_conversational,
    param_characters,
    run_image_generation,
    submit_video_generation,
    take_log,
)
from web.chat.helpers import (
    add_message_cost,
    branch_to,
    find_media,
    saved_media,
    shown_message,
)
from web.chat.schemas import ActiveGenerations, Generation, ShownMessage
from web.chat.workers import with_owner_keys
from web.core.metadata import get_db, iso
from web.core.metadata.models import ChatMessage
from web.jsonutil import as_int, as_list, as_object, as_str
from web.providers import openrouter
from web.types import JsonValue, VideoJob

log = logging.getLogger(__name__)


class PinMedia(BaseModel):
    """Requested pin state for an image."""

    pinned: bool


def _require_message(msg: ChatMessage | None) -> ChatMessage:
    """The message, or 404 when it has gone."""
    if msg is None:
        raise HTTPException(404, "Message not found")
    return msg


@router.post("/messages/{message_id}/media/{media_id}/pin")
def api_pin_media(message_id: int, media_id: str, data: PinMedia) -> ShownMessage:
    """Pin an image as a reference.

    It is sent with every image generated later on this branch of the chat, until unpinned.
    """
    db = get_db()
    msg = db.get_chat_message(message_id)
    item = find_media(msg, media_id)
    if not item or item["kind"] != "image" or not item.get("file") or item.get("status", "done") != "done":
        raise HTTPException(404, "Image not found")
    return shown_message(_require_message(db.update_chat_media_item(message_id, media_id, pinned=data.pinned)))


class FavouriteMedia(BaseModel):
    """Requested favourite state for a media item."""

    favourite: bool


@router.post("/messages/{message_id}/media/{media_id}/favourite")
def api_favourite_media(message_id: int, media_id: str, data: FavouriteMedia) -> ShownMessage:
    """Star/un-star a generation.

    Unlike pinning (which re-sends an image as a
    reference with every new generation), a favourite is just a bookmark: it
    surfaces the item in the cross-thread Favourites gallery. Works for images
    and videos.
    """
    db = get_db()
    msg = db.get_chat_message(message_id)
    item = find_media(msg, media_id)
    if not item or not item.get("file") or item.get("status", "done") != "done":
        raise HTTPException(404, "Generation not found")
    return shown_message(_require_message(db.update_chat_media_item(message_id, media_id, favourite=data.favourite)))


class RegenerateMedia(BaseModel):
    """Optional model, prompt, and replacement behavior for a media retry."""

    model: str | None = None  # None = same model as the failed attempt
    prompt: str | None = None  # None = the prompt it was made with
    # Edit: send the image itself back as the reference, so the model changes
    # this picture instead of making a new one from the prompt alone.
    edit: bool = False
    # Replace the item rather than adding a new one beside it: the picture it
    # had moves into `versions`, so nothing is lost and the card can flip back.
    replace: bool = False


# A card's pictures: the live one is the item's own fields; the others are in
# `versions`, and `version_shown` is where the live one sits among them all
# (missing = last). Whichever is showing is the real one — what the chat sends
# as context and references, pins, downloads — so the arrows swap it in.
VERSION_FIELDS = ("file", "prompt", "model", "cost", "credits", "params", "request", "response")


def _all_versions(item: Mapping[str, JsonValue]) -> tuple[list[dict[str, JsonValue]], int]:
    """Every picture the card has had, in order, and which is live (None-file live ones left out)."""
    raw = item.get("versions")
    versions = [v for v in (raw if isinstance(raw, list) else []) if isinstance(v, dict)]
    shown = item.get("version_shown")
    at = (
        shown
        if isinstance(shown, int) and not isinstance(shown, bool) and 0 <= shown <= len(versions)
        else len(versions)
    )
    live = [_as_version(item)] if item.get("file") else []
    return [*versions[:at], *live, *versions[at:]], at


def _spent(item: Mapping[str, JsonValue]) -> list[JsonValue]:
    """Failed-attempt charges kept from older records.

    Failures aren't billed, so nothing new is added and spend ignores these.
    """
    raw = item.get("spent")
    return list(raw) if isinstance(raw, list) else []


def _as_version(item: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    """What a card keeps about a picture it has replaced."""
    return {k: item[k] for k in VERSION_FIELDS if item.get(k) is not None}


@router.post("/messages/{message_id}/media/{media_id}/regenerate")
def api_regenerate_media(message_id: int, media_id: str, data: RegenerateMedia) -> ShownMessage:
    """Retry or re-roll a generated image or video.

    The retry runs in the background while the UI polls the message.
    """
    with start_lock:
        return _regenerate_media(message_id, media_id, data)


_RESULT_FIELDS = ("file", "cost", "credits", "error", "job_id", "request", "response")


# What a re-rolled copy of a finished item must not inherit from it
_NOT_REROLLED = (
    "file",
    "cost",
    "credits",
    "error",
    "job_id",
    "favourite",
    "pinned",
    "log",
    "versions",
    "version_shown",
    "spent",
)


def _regenerable_item(message_id: int, media_id: str) -> dict[str, JsonValue]:
    """The generated item a regenerate request targets, or the HTTP error saying why it can't be."""
    msg = get_db().get_chat_message(message_id)
    if not msg:
        raise HTTPException(404, "Message not found")
    if msg.status == "streaming":
        raise HTTPException(409, "Wait for the reply to finish first")
    item = find_media(msg, media_id)
    if not item or item.get("source") != "generated":
        raise HTTPException(404, "Media not found")
    if item.get("status") not in ("error", "done"):
        raise HTTPException(400, "Wait for the generation to finish first")
    return item


@dataclass(frozen=True)
class _Rerun:
    """What a regenerated item is run with."""

    model: str
    prompt: str
    params: dict[str, JsonValue]


def _regeneration_inputs(message_id: int, media_id: str, data: RegenerateMedia) -> tuple[dict[str, JsonValue], _Rerun]:
    """Validate a regenerate request; the item, and the model, prompt and params to run it with."""
    item = _regenerable_item(message_id, media_id)
    prompt = (data.prompt or "").strip() or as_str(item.get("prompt"))
    if not prompt:
        raise HTTPException(400, "This item has no stored prompt to retry")
    file = as_str(item.get("file"))
    if data.edit and not file:
        raise HTTPException(400, "There is no picture here to edit yet")
    model = data.model or as_str(item.get("model"))
    if not model:
        raise HTTPException(400, "This item has no stored model to retry")
    params = as_object(item.get("params"))
    if data.edit and file:
        # The picture being edited leads the reference list; the references it
        # was itself made from are dropped, so the model edits this one image.
        params["refs"] = [file, *(r for r in as_list(params.get("refs")) if str(r).startswith("char:"))]
    return item, _Rerun(model, prompt, params)


def _regenerate_media(message_id: int, media_id: str, data: RegenerateMedia) -> ShownMessage:
    db = get_db()
    item, rerun = _regeneration_inputs(message_id, media_id, data)
    model, prompt, params = rerun.model, rerun.prompt, rerun.params
    if data.replace:
        item, msg = _replace_item(message_id, media_id, item, rerun)
    elif item["status"] == "done":
        item, msg = _reroll_item(message_id, item, rerun)
        media_id = str(item["id"])
    else:
        item = {**item, "prompt": prompt, "params": params, "model": model}
        msg = db.update_chat_media_item(
            message_id,
            media_id,
            status="pending",
            error=None,
            moderated=False,
            model=model,
            job_id=None,
            prompt=prompt,
            params=params,
        )
    if msg is None:
        raise HTTPException(404, "Message not found")
    threading.Thread(
        target=_regenerate_worker,
        args=(msg.conversation_id, message_id, dict(item), model),
        daemon=True,
        name=f"chat-regen-{media_id}",
    ).start()
    return shown_message(msg)


def _replace_item(
    message_id: int, media_id: str, item: Mapping[str, JsonValue], rerun: _Rerun
) -> tuple[dict[str, JsonValue], ChatMessage | None]:
    """Keep what the card looked like before, then clear its result fields.

    The worker fills them in on the same item. A failed attempt has no
    picture to keep, so retrying one adds no version to flip back to.
    The new picture goes last, whichever one was showing.
    """
    versions, _ = _all_versions(item)
    spent = _spent(item)
    blank: dict[str, JsonValue] = dict.fromkeys(_RESULT_FIELDS)
    fresh: dict[str, JsonValue] = {
        **item,
        **blank,
        "status": "pending",
        "model": rerun.model,
        "prompt": rerun.prompt,
        "params": rerun.params,
        "versions": versions,
        "version_shown": len(versions),
        "spent": spent,
    }
    msg = get_db().update_chat_media_item(
        message_id,
        media_id,
        **{
            k: fresh[k]
            for k in (*_RESULT_FIELDS, "status", "model", "prompt", "params", "versions", "version_shown", "spent")
        },
        moderated=False,
    )
    return fresh, msg


def _reroll_item(
    message_id: int, item: Mapping[str, JsonValue], rerun: _Rerun
) -> tuple[dict[str, JsonValue], ChatMessage | None]:
    """Re-roll just this image/video: the original stays, a new one joins the reply."""
    kept = {k: v for k, v in item.items() if k not in _NOT_REROLLED}
    fresh: dict[str, JsonValue] = {
        **kept,
        "id": uuid.uuid4().hex[:8],
        "status": "pending",
        "model": rerun.model,
        "prompt": rerun.prompt,
        "params": rerun.params,
    }
    return fresh, get_db().append_chat_media_item(message_id, fresh)


class ShowMediaVersion(BaseModel):
    """Which of a card's pictures to make the live one (0 = the first)."""

    index: int


@router.post("/messages/{message_id}/media/{media_id}/version")
def api_show_media_version(message_id: int, media_id: str, data: ShowMediaVersion) -> ShownMessage:
    """Make one of a card's pictures the real one.

    It becomes the item's file, prompt, model and settings — what the chat
    sends from then on — and the one that was live becomes a version. Nothing
    is generated; what each cost stays counted.
    """
    with start_lock:
        db = get_db()
        msg = db.get_chat_message(message_id)
        if not msg:
            raise HTTPException(404, "Message not found")
        if msg.status == "streaming":
            raise HTTPException(409, "Wait for the reply to finish first")
        item = find_media(msg, media_id)
        if not item:
            raise HTTPException(404, "Media not found")
        if item.get("status") == "pending":
            raise HTTPException(409, "Wait for the generation to finish first")
        versions, _ = _all_versions(item)
        if not 0 <= data.index < len(versions):
            raise HTTPException(400, "No such version")
        chosen = versions.pop(data.index)
        fields: dict[str, JsonValue] = {k: chosen.get(k) for k in VERSION_FIELDS}
        updated = db.update_chat_media_item(
            message_id,
            media_id,
            **fields,
            status="done",
            error=None,
            moderated=False,
            versions=cast("JsonValue", versions),
            version_shown=data.index,
            spent=_spent(item),
        )
        if not updated:
            raise HTTPException(404, "Message not found")
        return shown_message(updated)


class ActiveQuery(BaseModel):
    """Message IDs whose generation state the client still tracks."""

    # Message ids the client is already tracking, so finished/failed ones get
    # their final status back even though they've dropped out of the pending set.
    known: list[int] = []


def _gen_descriptor(msg: ChatMessage, item: dict[str, JsonValue], title: str) -> Generation:
    return Generation.model_validate(
        {
            "media_id": item["id"],
            "message_id": msg.id,
            "conversation_id": msg.conversation_id,
            "conversation_title": title,
            "kind": item.get("kind"),
            "prompt": item.get("prompt"),
            "model": item.get("model") or msg.model,
            "status": item.get("status"),
            "file": item.get("file"),
            "error": item.get("error"),
            "moderated": bool(item.get("moderated")),
            "created_at": iso(msg.created_at),
        }
    )


@router.post("/generations/active")
def api_active_generations(data: ActiveQuery) -> ActiveGenerations:
    """List pending generations and the final states of tracked messages.

    Results cover all of the signed-in user's conversations. `known` IDs let
    the client resolve completions that have left the pending set.
    """
    db = get_db()
    msgs: dict[int, ChatMessage] = {m.id: m for m in db.get_chat_messages_with_pending_media()}
    for m in db.get_chat_messages_by_ids([i for i in data.known if i not in msgs]):
        msgs.setdefault(m.id, m)
    titles: dict[str, str] = {}
    items: list[Generation] = []
    seen: set[str] = set()
    for m in msgs.values():
        for item in m.media:
            if item.get("source") != "generated" or item.get("kind") not in ("image", "video", "audio"):
                continue
            item_id = as_str(item.get("id"))
            if item_id is None or item_id in seen:
                continue
            seen.add(item_id)
            cid = m.conversation_id
            if cid not in titles:
                conv = db.get_conversation(cid)
                titles[cid] = conv.title if conv else ""
            items.append(_gen_descriptor(m, item, titles[cid]))
    return ActiveGenerations(items=items)


@dataclass
class _Regen:
    """One media card being regenerated, and what to regenerate it with."""

    conv_id: str
    message_id: int
    media_id: str
    model: str
    prompt: str
    params: dict[str, JsonValue]


def _regen_image_context(r: _Regen) -> list[dict[str, JsonValue]] | None:
    """The conversation sent to a conversational image model, or None for a lone prompt."""
    if not is_conversational(r.model):
        return None
    msg = get_db().get_chat_message(r.message_id)
    history = branch_to(get_db().get_chat_messages(r.conv_id), r.message_id)[:-1]
    refs = r.params.get("refs")
    image_limit = as_int(r.params.get("image_limit"))
    shape = HistoryShape(
        as_int(r.params.get("history_limit")), image_limit if image_limit is not None else DEFAULT_IMAGE_LIMIT
    )
    ask = ImageAsk(
        msg.content if msg else "",
        None if r.params.get("direct") is True else r.prompt,
        [ref for ref in refs if isinstance(ref, str)] if isinstance(refs, list) else [],
        param_characters(r.params),
    )
    return image_context(r.conv_id, history, shape, ask, conversation_instructions(r.conv_id))


def _regen_image(r: _Regen) -> None:
    """Regenerate an image card; extra images the model returns become further cards."""
    db = get_db()
    context = _regen_image_context(r)
    r.params["context"] = context is not None
    names, cost, credit_cost, sent = run_image_generation(r.conv_id, r.model, r.prompt, r.params, context)
    sent, exchange = take_log(sent)
    db.update_chat_media_item(
        r.message_id,
        r.media_id,
        status="done",
        file=names[0],
        cost=cost,
        credits=credit_cost,
        params={**r.params, **sent},
        **exchange,
    )
    for extra in names[1:]:
        db.append_chat_media_item(
            r.message_id, saved_media("image", "generated", extra, prompt=r.prompt, model=r.model)
        )
    add_message_cost(r.message_id, cost)


def _record_job(r: _Regen, job: VideoJob | AudioJob) -> None:
    """Store a submitted job on its card and start polling it."""
    get_db().update_chat_media_item(
        r.message_id,
        r.media_id,
        job_id=job["id"],
        params={**r.params, **job.get("params", {})},
        **exchange_fields(job.get("log")),
    )
    polling.start_video_poller(r.conv_id, r.message_id, r.media_id, job["id"])


def _regen_video(r: _Regen) -> None:
    """Regenerate a video card; a different model may support different durations/ratios."""
    params = r.params
    params["duration"], params["aspect_ratio"], params["resolution"] = fit_video_params(
        r.model,
        as_int(params.get("duration")),
        as_str(params.get("aspect_ratio")),
        as_str(params.get("resolution")),
    )
    _record_job(r, submit_video_generation(r.conv_id, r.model, r.prompt, params))


@with_owner_keys
def _regenerate_worker(conv_id: str, message_id: int, item: Mapping[str, JsonValue], model: str) -> None:
    db = get_db()
    media_id = item.get("id")
    prompt = item.get("prompt")
    kind = item.get("kind")
    if not isinstance(media_id, str) or not isinstance(prompt, str) or not isinstance(kind, str):
        raise InvalidMediaItemError
    raw_params = item.get("params")
    params: dict[str, JsonValue] = dict(raw_params) if isinstance(raw_params, Mapping) else {}
    r = _Regen(conv_id, message_id, media_id, model, prompt, params)
    try:
        if kind == "image":
            _regen_image(r)
        elif kind == "audio":
            _record_job(r, submit_audio_generation(conv_id, model, prompt, params))
        else:
            _regen_video(r)
    except openrouter.OpenRouterError as e:
        db.update_chat_media_item(message_id, media_id, **failure_fields(e))
    except Exception as e:  # never leave the card stuck on "pending"
        log.exception("regeneration of media %s on message %s failed", media_id, message_id)
        db.update_chat_media_item(
            message_id, media_id, status="error", error=f"{type(e).__name__}: {e}", moderated=False
        )

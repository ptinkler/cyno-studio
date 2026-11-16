"""HTTP routes for chat settings, conversations, and media.

Turn and SSE routes are in `routes_turns.py`; media-card actions in `routes_media_items.py`.
"""

import shutil
import threading
import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import TypedDict

from fastapi import HTTPException

from web import characters
from web.chat.constants import (
    CONVERSATION_LIST_LIMIT,
    DEFAULT_TITLE,
    PARAM_FILES,
    SNIPPET_CHARS,
    THREAD_KINDS,
)
from web.chat.deps import router
from web.chat.helpers import (
    branch_to,
    chat_root,
    conversation_dir,
    require_conv,
    require_idle,
    shown_branch,
    shown_message,
    spend,
)
from web.chat.models import (
    ConversationCreate,
    ConversationUpdate,
    ForkConversation,
    SwitchBranch,
)
from web.chat.routes_settings import (
    require_hidden_defaults,
    require_instruction_groups,
    require_instructions,
    require_paused,
    require_space,
)
from web.chat.schemas import (
    Conversation,
    ConversationList,
    ConversationSummary,
    ConversationThumbs,
    ConversationView,
    DeletedConversation,
    DeleteInfo,
    ShownBranch,
    ShownMessage,
    Spend,
    SpendBreakdown,
    SpendGroup,
)
from web.core import config
from web.core.metadata import MetadataDB, get_db
from web.jsonutil import as_list, as_object, as_str
from web.types import JsonValue
from web.uploads.files import safe_filename


class _SpendGroup(TypedDict):
    model: str
    kind: str
    usd: float
    credits: int
    count: int


@router.get("/conversations")
def api_list_conversations(q: str = "") -> ConversationList:
    """Pinned chats, then the most recent (`more` = older ones left out).

    With `q`, chats whose title or messages contain it, each with a snippet
    of the matching message when the title didn't match.
    """
    db = get_db()
    q = q.strip()
    if q:
        return ConversationList(
            conversations=[
                ConversationSummary.model_validate({**c.to_dict(), "snippet": _snippet(text, q) if text else None})
                for c, text in db.search_conversations(q)
            ],
            more=False,
        )
    convs = db.list_conversations(limit=CONVERSATION_LIST_LIMIT + 1)
    return ConversationList(
        conversations=[ConversationSummary.model_validate(c.to_dict()) for c in convs[:CONVERSATION_LIST_LIMIT]],
        more=len(convs) > CONVERSATION_LIST_LIMIT,
    )


@router.get("/conversations/thumbs")
def api_conversation_thumbs(ids: str = "") -> ConversationThumbs:
    """Newest image file per conversation id (comma-separated), for gallery cover thumbnails.

    Declared before /conversations/{conv_id} so "thumbs"
    isn't read as an id.
    """
    conv_ids = [i for i in ids.split(",") if i]
    return ConversationThumbs(thumbs=get_db().conversation_thumbs(conv_ids))


def _snippet(text: str, q: str) -> str:
    """The part of `text` around the first match of `q`, on one line."""
    text = " ".join(text.split())
    i = text.lower().find(q.lower())
    if i == -1 or len(text) <= SNIPPET_CHARS:
        return text[:SNIPPET_CHARS]
    start = max(0, min(i - SNIPPET_CHARS // 3, len(text) - SNIPPET_CHARS))
    return (
        ("…" if start else "")
        + text[start : start + SNIPPET_CHARS].strip()
        + ("…" if start + SNIPPET_CHARS < len(text) else "")
    )


def _clean_kind(kind: str | None) -> str:
    """A thread's landing view: 'chat' or 'gallery' (default 'chat')."""
    return kind if kind in THREAD_KINDS else "chat"


@router.post("/conversations")
def api_create_conversation(data: ConversationCreate) -> Conversation:
    """Create a conversation with validated model and settings references."""
    db = get_db()
    space = require_space(data.space_id) if data.space_id is not None else None
    # Only what's attached to this chat itself: the global and space defaults
    # apply live on top (see inherited_ids), so they aren't copied in
    instruction_ids = require_instructions(data.instruction_ids)
    instruction_group_ids = require_instruction_groups(data.instruction_group_ids)
    characters.require(data.character_ids, db)
    character_ids = list(dict.fromkeys(data.character_ids))
    hidden_defaults = require_hidden_defaults(data.hidden_defaults)
    paused_instructions = require_paused(data.paused_instructions)

    conv = db.create_conversation(
        title=(data.title or DEFAULT_TITLE).strip()[:255] or DEFAULT_TITLE,
        kind=_clean_kind(data.kind),
        text_model=data.text_model,
        image_model=data.image_model,
        video_model=data.video_model,
        space_id=space.id if space else None,
        instruction_ids=instruction_ids,
        instruction_group_ids=instruction_group_ids,
        character_ids=character_ids,
        hidden_defaults=hidden_defaults,
        paused_instructions=paused_instructions,
    )
    return Conversation.model_validate(conv.to_dict())


def _message_id(message: dict[str, JsonValue]) -> int:
    """A shaped message's id."""
    value = message["id"]
    return value if isinstance(value, int) and not isinstance(value, bool) else -1


@router.get("/conversations/{conv_id}")
def api_get_conversation(conv_id: str) -> ConversationView:
    """Return a conversation and its currently shown messages."""
    conv = require_conv(conv_id)
    db = get_db()
    origin = None
    if conv.forked_from_id:
        parent = db.get_conversation(conv.forked_from_id)
        origin = {
            "id": conv.forked_from_id,
            "title": parent.title if parent else None,
            "message_id": conv.forked_from_message_id,
            "exists": parent is not None,
        }
    forks: dict[int, list[dict[str, JsonValue]]] = {}
    for f in db.list_conversation_forks(conv_id):
        if f.forked_from_message_id is None:
            continue
        forks.setdefault(f.forked_from_message_id, []).append({"id": f.id, "title": f.title})
    return ConversationView.model_validate(
        {
            "conversation": {**conv.to_dict(), "forked_from": origin, "spend": spend(conv)},
            "messages": [{**m, "forks": forks.get(_message_id(m), [])} for m in shown_branch(conv_id)],
        }
    )


@router.get("/spend/breakdown")
def api_spend_breakdown(days: int = 0) -> SpendBreakdown:
    """What the user's money went on: per model (and kind) over the last `days` days (0 = all time).

    Pollo's credits are converted to USD at its fixed rate
    so everything adds up in one currency; the credits stay alongside.
    """
    db = get_db()
    cutoff = datetime.now().astimezone().replace(tzinfo=None) - timedelta(days=days) if days > 0 else None
    groups: dict[tuple[str, str], _SpendGroup] = {}
    for r in db.spend_rows([c.id for c in db.list_conversations(limit=None)]):
        if cutoff and r["at"] and r["at"] < cutoff:
            continue
        g = groups.setdefault(
            (r["model"] or "unknown", r["kind"]),
            {
                "model": r["model"] or "unknown",
                "kind": r["kind"],
                "usd": 0.0,
                "credits": 0,
                "count": 0,
            },
        )
        g["usd"] += r["usd"] + r["credits"] * config.POLLO_USD_PER_CREDIT
        g["credits"] += r["credits"]
        g["count"] += 1
    rows = sorted(groups.values(), key=lambda g: -g["usd"])
    for g in rows:
        g["usd"] = round(g["usd"], 4)
    return SpendBreakdown(
        days=days,
        total_usd=round(sum(g["usd"] for g in rows), 4),
        rows=[SpendGroup(**g) for g in rows],
    )


@router.get("/conversations/{conv_id}/spend")
def api_conversation_spend(conv_id: str) -> Spend:
    """Return the accumulated spend for one conversation."""
    return Spend.model_validate(spend(require_conv(conv_id)))


@router.post("/conversations/{conv_id}/branch")
def api_switch_branch(conv_id: str, data: SwitchBranch) -> ConversationView:
    """Show the branch through `message_id`, down to its newest message."""
    require_conv(conv_id)
    require_idle(conv_id)
    db = get_db()
    messages = db.get_chat_messages(conv_id)
    if not any(m.id == data.message_id for m in messages):
        raise HTTPException(400, "Message not in this conversation")
    # Children are always newer than their parent, so the newest message
    # under this one is the end of its most recent branch
    below = {data.message_id}
    for m in messages:
        if m.parent_id in below:
            below.add(m.id)
    db.set_chat_leaf(conv_id, max(below))
    return api_get_conversation(conv_id)


@router.post("/conversations/{conv_id}/fork")
def api_fork_conversation(conv_id: str, data: ForkConversation) -> Conversation:
    """Create a conversation branched at a prompt or reply.

    Copy the preceding messages, selected settings, and chat-owned characters.
    Link or copy media files and retain the source conversation reference.
    """
    conv = require_conv(conv_id)
    require_idle(conv_id)
    db = get_db()
    messages = db.get_chat_messages(conv_id)
    at = next((m for m in messages if m.id == data.message_id), None)
    if not at:
        raise HTTPException(400, "Message not in this conversation")
    path = branch_to(messages, at.id)
    replies = [m for m in messages if m.parent_id == at.id] if at.role == "user" else []
    if replies:
        shown = {m.id for m in branch_to(messages, db.get_chat_leaf_id(conv_id))}
        path.append(next((m for m in replies if m.id in shown), replies[-1]))

    new = db.create_conversation(
        title=f"{conv.title} (branch)"[:255],
        text_model=conv.text_model,
        image_model=conv.image_model,
        video_model=conv.video_model,
        space_id=conv.space_id,
        instruction_ids=conv.instruction_ids,
        instruction_group_ids=conv.instruction_group_ids,
        hidden_defaults=conv.hidden_defaults,
        paused_instructions=conv.paused_instructions,
        settings=conv.settings,
        forked_from_id=conv_id,
        forked_from_message_id=at.id,
        inherited_cost=round(sum(m.cost or 0 for m in path), 6) or None,
        inherited_credits=sum(
            credit_cost
            for msg in path
            for item in msg.media
            if isinstance((credit_cost := item.get("credits")), int) and not isinstance(credit_cost, bool)
        )
        or None,
    )
    # This chat's own characters, attached or used by the copied media, get
    # copies owned by the new chat; saved characters are shared as they are
    used = set(conv.character_ids)
    for msg in path:
        for item in msg.media:
            params = item.get("params")
            if isinstance(params, dict):
                used.update(_media_character_ids(params))
    char_map = {
        c.id: characters.copy_to_conversation(c, new.id, db).id
        for c in characters.load(sorted(used), db)
        if c.conversation_id == conv_id
    }
    db.update_conversation(new.id, character_ids=[char_map.get(i, i) for i in conv.character_ids])

    fork = _Fork(chat_root() / conv_id, conversation_dir(new.id), char_map)
    db.add_chat_branch(
        new.id,
        [
            {
                "role": msg.role,
                "content": msg.content,
                "media": [fork.media_item(item) for item in msg.media],
                "model": msg.model,
                "status": msg.status,
                "mode": msg.mode,
                "error": msg.error,
                "cost": msg.cost,
            }
            for msg in path
        ],
    )
    forked = db.get_conversation(new.id)
    if not forked:
        raise HTTPException(500, "Could not load forked conversation")
    return Conversation.model_validate(forked.to_dict())


def _media_character_ids(params: dict[str, JsonValue]) -> set[int]:
    """Characters a media item was made with: by id, or through their images."""
    character_ids = params.get("characters")
    ids: set[int] = set()
    if isinstance(character_ids, Sequence) and not isinstance(character_ids, str):
        ids.update(item for item in character_ids if isinstance(item, int) and not isinstance(item, bool))
    for value in (params.get("refs"), *(params.get(key) for key in PARAM_FILES)):
        refs = value if isinstance(value, Sequence) and not isinstance(value, str) else [value]
        for ref in refs:
            if isinstance(ref, str) and ref.startswith(characters.REF_PREFIX):
                cid = ref[len(characters.REF_PREFIX) :].partition("/")[0]
                if cid.isdigit():
                    ids.add(int(cid))
    return ids


class _Fork:
    """Copies media items into a branched chat.

    Files are linked into its folder under the same names (Media shows each pair once), and references to copied
    characters point at the copies, so regenerating works there.
    """

    def __init__(self, src: Path, dst: Path, char_map: dict[int, int]) -> None:
        self.src, self.dst, self.char_map = src, dst, char_map

    def media_item(self, item: dict[str, JsonValue]) -> dict[str, JsonValue]:
        item = {**item, "id": uuid.uuid4().hex[:8]}
        if item.get("status") == "pending":
            # Its poller keeps updating the original chat only
            return {
                **item,
                "status": "error",
                "error": "Still rendering in the original chat when this one was branched",
            }
        file = as_str(item.get("file"))
        if file:
            self._link(file)
        params = as_object(item.get("params"))
        if params:
            item["params"] = params
            self._remap_params(params)
        return item

    def _remap_params(self, params: dict[str, JsonValue]) -> None:
        """Point a copied item's characters, references and param files at the new chat (in place)."""
        if char_ids := as_list(params.get("characters")):
            params["characters"] = [
                self.char_map.get(i, i) if isinstance(i, int) and not isinstance(i, bool) else i for i in char_ids
            ]
        if refs := as_list(params.get("refs")):
            params["refs"] = [self._ref(r) for r in refs if isinstance(r, str)]
        for key in PARAM_FILES:
            if value := as_str(params.get(key)):
                params[key] = self._ref(value)

    def _ref(self, ref: str) -> str:
        """A reference for the new chat: a copied character's image, or a chat file (linked over)."""
        if ref.startswith(characters.REF_PREFIX):
            cid, _, file = ref[len(characters.REF_PREFIX) :].partition("/")
            if cid.isdigit() and int(cid) in self.char_map:
                return characters.image_ref(self.char_map[int(cid)], file)
            return ref
        self._link(ref)
        return ref

    def _link(self, name: str) -> None:
        if (
            Path(name).name != name
            or name.startswith(".")
            or not (self.src / name).is_file()
            or (self.dst / name).exists()
        ):
            return
        try:
            (self.dst / name).hardlink_to(self.src / name)
        except OSError:
            shutil.copy2(self.src / name, self.dst / name)


def _validate_conv_references(data: ConversationUpdate, fields: dict[str, JsonValue]) -> None:
    """Check that the instructions, space and characters a chat update names exist."""
    if "instruction_ids" in fields:
        fields["instruction_ids"] = require_instructions(data.instruction_ids or [])
    if "instruction_group_ids" in fields:
        fields["instruction_group_ids"] = require_instruction_groups(data.instruction_group_ids or [])
    if data.space_id is not None:
        require_space(data.space_id)
    if "character_ids" in fields:
        characters.require(data.character_ids or [], get_db())


def _clean_conv_update(data: ConversationUpdate, fields: dict[str, JsonValue]) -> None:
    """Normalize and validate the mutable ConversationUpdate fields in place.

    This is everything except `pinned`, which the route handles separately.
    """
    _validate_conv_references(data, fields)
    if "title" in fields:
        fields["title"] = (data.title or "").strip()[:255] or DEFAULT_TITLE
    if "kind" in fields:
        fields["kind"] = _clean_kind(data.kind)
    if "hidden_defaults" in fields:
        fields["hidden_defaults"] = require_hidden_defaults(data.hidden_defaults)
    if "paused_instructions" in fields:
        fields["paused_instructions"] = require_paused(data.paused_instructions)


@router.patch("/conversations/{conv_id}")
def api_update_conversation(conv_id: str, data: ConversationUpdate) -> Conversation:
    """Update a conversation's mutable fields and return its saved record."""
    require_conv(conv_id)
    fields: dict[str, JsonValue] = data.model_dump(exclude_unset=True)
    _clean_conv_update(data, fields)
    if "pinned" in fields:
        # Not an edit: the chat keeps its place among the rest
        get_db().set_conversation_pinned(conv_id, pinned=bool(fields.pop("pinned")))
    if not fields:
        conversation = get_db().get_conversation(conv_id)
        if not conversation:
            raise HTTPException(404, "Conversation not found")
        return Conversation.model_validate(conversation.to_dict())
    conversation = get_db().update_conversation(conv_id, **fields)
    if not conversation:
        raise HTTPException(404, "Conversation not found")
    return Conversation.model_validate(conversation.to_dict())


@router.delete("/conversations/{conv_id}")
def api_delete_conversation(conv_id: str, *, delete_media: bool = True) -> DeletedConversation:
    """Delete a chat.

    Its images/videos/uploads go with it unless delete_media=false
    (the files then stay and show up under "Orphaned" in the Media library).
    """
    require_conv(conv_id)
    characters.delete_for_conversation(conv_id, get_db())
    get_db().delete_conversation(conv_id)
    # Its files go in the background: hundreds of images take a while on a NAS
    folder = chat_root() / conv_id
    if delete_media and folder.exists():
        folder.rename(folder.with_name(f".deleting-{conv_id}"))  # out of the way at once
        threading.Thread(target=_empty_trash, daemon=True).start()
    return DeletedConversation(deleted=conv_id)


def _empty_trash() -> None:
    """Remove deleted chats' folders (any left by a restart mid-delete too)."""
    for trash in chat_root().glob(".deleting-*"):
        shutil.rmtree(trash, ignore_errors=True)


@router.get("/messages/{message_id}")
def api_get_message(message_id: int) -> ShownMessage:
    """Return one message with its branch siblings."""
    msg = get_db().get_chat_message(message_id)
    if not msg:
        raise HTTPException(404, "Message not found")
    return shown_message(msg)


@router.get("/messages/{message_id}/delete-info")
def api_delete_exchange_info(message_id: int) -> DeleteInfo:
    """What deleting this prompt would also remove, for the confirmation.

    That is other versions of it and the messages that followed them.
    """
    msg = get_db().get_chat_message(message_id)
    info = msg and get_db().chat_exchange_delete_info(msg.conversation_id, message_id)
    if not info:
        raise HTTPException(404, "Prompt not found")
    return DeleteInfo.model_validate(info)


def _delete_detached_media(db: MetadataDB, conv_id: str, detached: list[dict[str, JsonValue]]) -> None:
    """Delete the files and library rows of media detached from a deleted prompt turn."""
    for item in detached:
        file = item.get("file")
        if isinstance(file, str):
            (conversation_dir(conv_id) / safe_filename(file)).unlink(missing_ok=True)
        media_id = item.get("id")
        if not isinstance(media_id, str):
            raise TypeError(media_id)
        db.delete_chat_library_item(media_id)


@router.delete("/messages/{message_id}")
def api_delete_exchange(message_id: int, *, delete_media: bool = False) -> ShownBranch:
    """Delete a prompt turn and return the updated conversation.

    Replies and alternate prompt versions are removed while later messages on
    the shown branch remain. Generated media moves to the library unless
    `delete_media` is true.
    """
    db = get_db()
    msg = db.get_chat_message(message_id)
    if not msg:
        raise HTTPException(404, "Message not found")
    if msg.role != "user":
        raise HTTPException(400, "Delete the prompt; its reply goes with it")
    require_idle(msg.conversation_id)
    detached = db.delete_chat_exchange(msg.conversation_id, message_id)
    if delete_media:
        _delete_detached_media(db, msg.conversation_id, detached)
    conversation = db.get_conversation(msg.conversation_id)
    if not conversation:
        raise HTTPException(404, "Conversation not found")
    return ShownBranch.model_validate(
        {"conversation": conversation.to_dict(), "messages": shown_branch(msg.conversation_id)}
    )

"""Importing a parsed export into chats: merging new turns, the ChatGPT space, and the run itself."""

import logging
import threading
import zipfile
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast

from web.chat import CHAT_PREVIEW_SIZE, ConversationCreate, api_create_conversation
from web.core.metadata import get_db
from web.core.metadata.imports import ImportStamp
from web.core.metadata.models import ChatConversation, ChatMessage
from web.media.thumbs import THUMB_SIZE, make_thumb
from web.transfer import export as chat_export
from web.transfer.chatgpt.common import (
    DEFAULT_TITLE,
    NOT_AN_EXPORT,
    SOURCE,
    SPACE_NAME,
    ImportStats,
)
from web.transfer.chatgpt.media import ChatMedia
from web.transfer.chatgpt.parse import Export, Turn, build_turns, timestamp
from web.types import JsonValue

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from web.core.metadata.imports import ImportedMessage, ImportedMessageUpdate


def _when(ts: float | None) -> datetime | None:
    return datetime.fromtimestamp(ts).astimezone().replace(tzinfo=None) if ts else None


class _Merge:
    """What one chat's import adds to it.

    New messages (`rows`, each after the one before on the exported branch) and changes to replies imported
    before (`updates`).
    """

    def __init__(self, export: Export, conv_id: str, known: dict[str, ChatMessage], stats: ImportStats) -> None:
        self.known = known
        self.media = ChatMedia(export, conv_id, [i for m in known.values() for i in m.media], stats)
        self.rows: list[ImportedMessage] = []
        self.updates: dict[int, ImportedMessageUpdate] = {}
        self.parent: dict[str, str | int | None] = {"parent_id": None}

    def _add(self, import_id: str, **row: JsonValue | datetime) -> None:
        self.rows.append(cast("ImportedMessage", {**self.parent, "import_id": import_id, **row}))
        self.parent = {"parent_import_id": import_id}

    def prompt(self, turn: Turn) -> None:
        if turn.prompt_id is None:
            return
        if turn.prompt_id in self.known:
            self.parent = {"parent_id": self.known[turn.prompt_id].id}
            return
        self._add(
            turn.prompt_id,
            role="user",
            content=turn.prompt,
            media=[self.media.item(f, "upload") for f in turn.uploads],
            created_at=_when(turn.time) or datetime.now().astimezone().replace(tzinfo=None),
        )

    def reply(self, turn: Turn) -> None:
        reply_id = f"reply:{turn.prompt_id or ''}"
        content = "\n\n".join(turn.reply)
        prev = self.known.get(reply_id)
        have: set[str] = (
            {import_file for item in prev.media if isinstance(import_file := item.get("import_file"), str)}
            if prev
            else set()
        )
        items = [
            i
            for g in turn.generated
            if g["id"] not in have and (i := self.media.item(g["id"], "generated", g.get("mime"), g.get("name")))
        ]
        if prev:
            # A reply still being written when the last export was made
            fields: ImportedMessageUpdate = {"content": content} if content and content != prev.content else {}
            if items:
                fields["media"] = prev.media + items
            if fields:
                self.updates[prev.id] = fields
            self.parent = {"parent_id": prev.id}
        elif content or items:
            self._add(
                reply_id,
                role="assistant",
                content=content,
                media=items,
                model=f"{SOURCE}/{turn.model}" if turn.model else None,
                created_at=_when(turn.reply_time or turn.time) or datetime.now().astimezone().replace(tzinfo=None),
            )


def _import_space_id() -> int:
    """The "ChatGPT" space, made the first time it's needed (or again, if renamed or deleted)."""
    db = get_db()
    space = next((s for s in db.list_spaces() if s.name.strip().lower() == SPACE_NAME.lower()), None)
    if space is None:
        space = db.save_space(name=SPACE_NAME)
    return space.id


def _new_imported_conversation(data: Mapping[str, JsonValue], stats: ImportStats) -> ChatConversation:
    """Create a chat for a new ChatGPT import."""
    db = get_db()
    # Made like a chat started in the space, so it gets the same defaults.
    space_id = stats.get("space_id")
    if space_id is None:
        space_id = stats["space_id"] = _import_space_id()
    import_id = data.get("id")
    if not isinstance(import_id, str):
        raise TypeError(import_id)
    title_value = data.get("title")
    title = (title_value if isinstance(title_value, str) else DEFAULT_TITLE).strip()[:255] or DEFAULT_TITLE
    made = api_create_conversation(ConversationCreate(title=title, space_id=space_id))
    create_time = data.get("create_time")
    timestamp = (
        float(create_time) if isinstance(create_time, int | float) and not isinstance(create_time, bool) else None
    )
    conv = db.update_conversation(
        made.id,
        import_source=SOURCE,
        import_id=import_id,
        created_at=_when(timestamp) or datetime.now().astimezone().replace(tzinfo=None),
    )
    if conv is None:
        raise LookupError(made.id)
    return conv


def _import_conversation(
    export: Export, data: dict[str, JsonValue], conv: ChatConversation | None, stats: ImportStats
) -> str:
    """Import one chat, or what's new in it: "new", "updated", "unchanged" or "empty"."""
    db = get_db()
    conv_id = data.get("id")
    if not isinstance(conv_id, str):
        raise TypeError(conv_id)
    turns = build_turns(data, export.library.get(conv_id, []))
    fresh = conv is None
    if fresh and not turns:
        return "empty"
    imported_conv = _new_imported_conversation(data, stats) if conv is None else conv
    known: dict[str, ChatMessage] = {} if fresh else db.get_chat_import_ids(imported_conv.id)
    leaf = None if fresh else db.get_chat_leaf_id(imported_conv.id)
    # Carried on here since: keep showing that, the new turns are a branch
    show = leaf is None or any(m.id == leaf for m in known.values())

    merge = _Merge(export, imported_conv.id, known, stats)
    for turn in turns:
        if turn.prompt_id:
            merge.prompt(turn)
        merge.reply(turn)
    changed = bool(merge.rows or merge.updates)
    changed_at = _when(timestamp(data.get("update_time")))
    if fresh:
        updated_at = changed_at
    else:
        updated_at = max(filter(None, [changed_at, conv.updated_at])) if changed else conv.updated_at
    stamp = ImportStamp(timestamp(data.get("update_time")), updated_at)
    db.add_imported_messages(imported_conv.id, merge.rows, merge.updates, stamp, show=show)
    if fresh:
        return "new"
    return "updated" if changed else "unchanged"


def _fresh_stats(progress: dict[str, JsonValue] | None) -> ImportStats:
    """Zero the import counters (in `progress` when given, so a poller sees them move)."""
    stats: ImportStats = cast("ImportStats", progress) if progress is not None else cast("ImportStats", {})
    stats.update(
        total=0,
        processed=0,
        new=0,
        updated=0,
        unchanged=0,
        deleted=0,
        empty=0,
        images=0,
        missing_images=0,
        failed=[],
    )
    stats.pop("space_id", None)  # the space new chats went in, once there are some
    return stats


def _conversation_outcome(
    export: Export,
    data: dict[str, JsonValue],
    imported: Mapping[str, ChatConversation],
    skips: set[str],
    stats: ImportStats,
) -> str | None:
    """Import one exported chat; "new" / "updated" / "unchanged" / "deleted" / "empty", None if it failed."""
    conv_id = data.get("id") or data.get("conversation_id")
    if not isinstance(conv_id, str):
        return "empty"
    data["id"] = conv_id
    conv = imported.get(conv_id)
    if conv_id in skips:
        return "deleted"
    if conv and conv.import_updated_at == timestamp(data.get("update_time")):
        return "unchanged"
    try:
        return _import_conversation(export, data, conv, stats)
    except Exception as e:  # one bad chat shouldn't stop the rest
        log.exception("importing one ChatGPT conversation failed")
        stats["failed"].append({"title": data.get("title"), "error": str(e)})
        return None


def run_import(path: Path, progress: dict[str, JsonValue] | None = None) -> ImportStats:
    """Import the export at `path`.

    Returns (and keeps `progress` up to
    date with) how many chats were new, updated, unchanged or skipped.
    """
    stats = _fresh_stats(progress)
    db = get_db()
    with zipfile.ZipFile(path) as zf:
        if chat_export.is_native_export(zf):
            return _run_native(zf, stats)
        if "conversations.json" not in zf.namelist():
            raise ValueError(NOT_AN_EXPORT)
        export = Export(zf)
        stats["total"] = len(export.conversations)
        imported = db.get_imported_conversations(SOURCE)
        skips = db.get_import_skips(SOURCE)
        for data in export.conversations:
            outcome = _conversation_outcome(export, data, imported, skips, stats)
            if outcome:
                stats[outcome] += 1
            stats["processed"] += 1
    if export.new_files:
        threading.Thread(target=_warm_thumbnails, args=(export.new_files,), daemon=True).start()
    return stats


def _run_native(zf: zipfile.ZipFile, stats: ImportStats) -> ImportStats:
    """This app's own export (from here or another server)."""
    written = chat_export.import_native(zf, cast("dict[str, JsonValue]", stats))
    if written:
        threading.Thread(target=_warm_thumbnails, args=(written,), daemon=True).start()
    return stats


def _warm_thumbnails(paths: list[Path]) -> None:
    """Make the new images' grid thumbnails and chat previews now, one at a time in the background.

    So opening the chats and the Media page later doesn't wait for hundreds of them to be made.
    """
    for path in paths:
        for size in (THUMB_SIZE, CHAT_PREVIEW_SIZE):
            make_thumb(path, size)

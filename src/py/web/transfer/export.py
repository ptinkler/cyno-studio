"""Exporting chats as a zip that this app's importer reads back.

For moving chats between servers (production → a test instance) or keeping a
copy. The zip goes into the same Import dialog as a ChatGPT export; the
importer tells them apart by what's inside:

    pollo-chats.json          {"format": "pollo-chats", "version": 1,
                               "exported_at", "conversations": [...]}: each
                              chat's settings, every message on every branch
                              (with its media items, versions and costs) and
                              its detached library media
    chats/<chat id>/<file>    the chat's media files, as stored

The character images a card was made from do travel, as plain files of the chat (see
character_refs.py).

What doesn't travel: attached characters and instructions (their ids belong to
the exporting server; the importing server's space/global defaults apply
instead) and forks' links to the chat they came from. A chat's space goes by
name, made if the importing server hasn't one by that name.

Importing again only adds what's new, like the ChatGPT import: chats remember
the id they had on the exporting server, messages theirs, unchanged chats are
skipped, and chats deleted here stay deleted.
"""

import json
import logging
import tempfile
import zipfile
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import TypeAdapter
from starlette.background import BackgroundTask

from web.auth.users import require_user
from web.chat import ConversationCreate, api_create_conversation, conversation_dir
from web.core.metadata import get_db, iso
from web.core.metadata.imports import ImportStamp
from web.core.metadata.models import ChatConversation
from web.transfer.character_refs import snapshot_card
from web.transfer.limits import EntryTooLargeError, copy_entry, is_media_file
from web.transfer.schemas import ExportableChat, ExportableChats
from web.types import JsonValue
from web.uploads.files import safe_filename

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from web.core.metadata.imports import NativeLibraryItem, NativeMessage

router = APIRouter(prefix="/api/chat/export", dependencies=[Depends(require_user)])

SOURCE = "pollo"  # import_source of chats brought in from another server's export
MANIFEST = "pollo-chats.json"
_MANIFEST = TypeAdapter(dict[str, JsonValue])
FORMAT = "pollo-chats"
VERSION = 1


# ― export ―


def _space_names() -> dict[int, str]:
    return {s.id: s.name for s in get_db().list_spaces()}


def _conversation_out(
    conv: ChatConversation, spaces: Mapping[int, str], taken: dict[str, Path]
) -> dict[str, JsonValue]:
    """One chat for the manifest. `taken` collects character images its cards used (see character_refs)."""
    db = get_db()
    return {
        "id": conv.id,
        "title": conv.title,
        "kind": conv.kind,
        "text_model": conv.text_model,
        "image_model": conv.image_model,
        "video_model": conv.video_model,
        "settings": conv.settings,
        "pinned": conv.pinned,
        "space": spaces.get(conv.space_id) if conv.space_id is not None else None,
        "current_leaf_id": conv.current_leaf_id,
        "inherited_cost": conv.inherited_cost,
        "inherited_credits": conv.inherited_credits,
        "created_at": iso(conv.created_at),
        "updated_at": iso(conv.updated_at),
        "messages": [
            {
                "id": m.id,
                "parent_id": m.parent_id,
                "role": m.role,
                "content": m.content,
                "media": [snapshot_card(item, taken) for item in m.media],
                "model": m.model,
                "mode": m.mode,
                "lane": m.lane,
                "status": m.status,
                "error": m.error,
                "cost": m.cost,
                "text_versions_json": m.text_versions_json,
                "created_at": iso(m.created_at),
            }
            for m in db.get_chat_messages(conv.id)
        ],
        "library": [
            {
                "media_id": lib.media_id,
                "item": snapshot_card(lib.item, taken),
                "created_at": iso(lib.created_at),
                "detached_at": iso(lib.detached_at),
            }
            for lib in db.list_chat_library()
            if lib.conversation_id == conv.id
        ],
    }


def _chat_files(conv_id: str) -> list[Path]:
    folder = conversation_dir(conv_id)
    return sorted(p for p in folder.iterdir() if p.is_file() and not p.name.startswith("."))


def write_export(conv_ids: list[str], out: Path) -> int:
    """Write the chats to a zip at `out`; returns how many were written (unknown ids are skipped)."""
    db = get_db()
    spaces = _space_names()
    chats: list[JsonValue] = []
    # Media is already compressed: stored as is, only the JSON is deflated
    with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED, allowZip64=True) as zf:
        for conv_id in dict.fromkeys(conv_ids):
            conv = db.get_conversation(conv_id)
            if not conv:
                continue
            taken: dict[str, Path] = {}
            chats.append(_conversation_out(conv, spaces, taken))
            files = _chat_files(conv.id)
            for path in files:
                zf.write(path, f"chats/{conv.id}/{path.name}")
            for name, path in taken.items():
                if name not in {f.name for f in files}:
                    zf.write(path, f"chats/{conv.id}/{name}")
        manifest = {
            "format": FORMAT,
            "version": VERSION,
            "exported_at": iso(datetime.now().astimezone().replace(tzinfo=None)),
            "conversations": chats,
        }
        zf.writestr(MANIFEST, json.dumps(manifest), compress_type=zipfile.ZIP_DEFLATED)
    return len(chats)


@router.get("/chats")
def api_export_list() -> ExportableChats:
    """Every chat, for picking which to export."""
    spaces = _space_names()
    return ExportableChats(
        chats=[
            ExportableChat(
                id=c.id,
                title=c.title,
                kind=c.kind,
                space=spaces.get(c.space_id) if c.space_id is not None else None,
                updated_at=iso(c.updated_at),
            )
            for c in get_db().list_conversations(limit=None)
        ]
    )


@router.get("")
def api_export(
    ids: Annotated[str, Query(description="Comma-separated chat ids; empty = every chat")] = "",
) -> FileResponse:
    """Download chats as a zip the Import dialog (here or on another server) reads back."""
    wanted = [i for i in ids.split(",") if i] or [c.id for c in get_db().list_conversations(limit=None)]
    with tempfile.NamedTemporaryFile(prefix="chat-export-", suffix=".zip", delete=False) as tmp:
        out = Path(tmp.name)
    try:
        count = write_export(wanted, out)
    except Exception:
        out.unlink(missing_ok=True)
        raise
    if not count:
        out.unlink(missing_ok=True)
        raise HTTPException(404, "No such chats")
    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M")
    filename = f"chats-{count}-{stamp}.zip"
    if count == 1:
        conv = get_db().get_conversation(wanted[0])
        title = safe_filename((conv.title if conv else "") or "chat").replace(" ", "_")[:60] or "chat"
        filename = f"{title}-{stamp}.zip"
    return FileResponse(
        out,
        media_type="application/zip",
        filename=filename,
        background=BackgroundTask(lambda: out.unlink(missing_ok=True)),
    )


# ― import ―


def is_native_export(zf: zipfile.ZipFile) -> bool:
    """Whether a zip is this app's own export (rather than ChatGPT's)."""
    return MANIFEST in zf.namelist()


def _when(value: JsonValue) -> datetime | None:
    """A stored timestamp back as naive server-local time, as the database keeps them."""
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return dt.astimezone().replace(tzinfo=None) if dt.tzinfo else dt


def _str(value: JsonValue) -> str | None:
    return value if isinstance(value, str) else None


def _num(value: JsonValue) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _obj(value: JsonValue) -> dict[str, JsonValue]:
    return value if isinstance(value, dict) else {}


def _space_id(name: str | None, cache: dict[str, int]) -> int | None:
    if not name:
        return None
    key = name.strip().lower()
    if key not in cache:
        db = get_db()
        space = next((s for s in db.list_spaces() if s.name.strip().lower() == key), None) or db.save_space(
            name=name.strip()
        )
        cache[key] = space.id
    return cache[key]


def _new_conversation(data: Mapping[str, JsonValue], spaces: dict[str, int]) -> ChatConversation:
    """Make the chat here, like one started in its space, carrying its own settings."""
    made = api_create_conversation(
        ConversationCreate(
            title=_str(data.get("title")),
            kind=_str(data.get("kind")),
            text_model=_str(data.get("text_model")),
            image_model=_str(data.get("image_model")),
            video_model=_str(data.get("video_model")),
            space_id=_space_id(_str(data.get("space")), spaces),
        )
    )
    settings = data.get("settings")
    conv = get_db().update_conversation(
        made.id,
        import_source=SOURCE,
        import_id=_str(data.get("id")),
        pinned=data.get("pinned") is True,
        settings_json=json.dumps(settings) if isinstance(settings, dict) and settings else None,
        inherited_cost=_num(data.get("inherited_cost")),
        inherited_credits=int(n) if (n := _num(data.get("inherited_credits"))) is not None else None,
        created_at=_when(data.get("created_at")) or datetime.now().astimezone().replace(tzinfo=None),
    )
    if conv is None:
        raise LookupError(made.id)
    return conv


def _messages(data: Mapping[str, JsonValue]) -> list["NativeMessage"]:
    rows: list[NativeMessage] = []
    raw = data.get("messages")
    for m in sorted((_obj(x) for x in (raw if isinstance(raw, list) else [])), key=lambda x: _num(x.get("id")) or 0):
        msg_id, role = m.get("id"), _str(m.get("role"))
        if not isinstance(msg_id, int) or role not in ("user", "assistant"):
            continue
        parent = m.get("parent_id")
        media = m.get("media")
        status = _str(m.get("status")) or "done"
        rows.append(
            {
                "import_id": str(msg_id),
                "parent_import_id": str(parent) if isinstance(parent, int) else None,
                "role": role,
                "content": _str(m.get("content")) or "",
                "media": [_obj(i) for i in media if isinstance(i, dict)] if isinstance(media, list) else [],
                "model": _str(m.get("model")),
                "mode": _str(m.get("mode")),
                "lane": _str(m.get("lane")),
                # A reply mid-stream when exported won't finish here
                "status": "error" if status == "streaming" else status,
                "error": "Still being written when exported" if status == "streaming" else _str(m.get("error")),
                "cost": _num(m.get("cost")),
                "text_versions_json": _str(m.get("text_versions_json")),
                "created_at": _when(m.get("created_at")) or datetime.now().astimezone().replace(tzinfo=None),
            }
        )
    return rows


def _settle_pending(rows: list["NativeMessage"]) -> None:
    """A generation still running when exported won't be polled here: mark it failed, not stuck."""
    for row in rows:
        for item in row["media"]:
            if item.get("status") == "pending":
                item.update(status="error", error="Still being made when exported", job_id=None)


def _library(data: Mapping[str, JsonValue]) -> list["NativeLibraryItem"]:
    out: list[NativeLibraryItem] = []
    raw = data.get("library")
    for lib in (_obj(x) for x in (raw if isinstance(raw, list) else [])):
        media_id, item = _str(lib.get("media_id")), _obj(lib.get("item"))
        if not media_id or not item:
            continue
        now = datetime.now().astimezone().replace(tzinfo=None)
        out.append(
            {
                "media_id": media_id,
                "item": item,
                "created_at": _when(lib.get("created_at")) or now,
                "detached_at": _when(lib.get("detached_at")) or now,
            }
        )
    return out


def _copy_files(zf: zipfile.ZipFile, src_id: str, conv_id: str, stats: dict[str, JsonValue]) -> list[Path]:
    """The chat's files into its folder here; ones already there are left alone."""
    folder = conversation_dir(conv_id)
    prefix = f"chats/{src_id}/"
    written: list[Path] = []
    for name in zf.namelist():
        if not name.startswith(prefix) or name.endswith("/"):
            continue
        file = safe_filename(name[len(prefix) :])
        target = folder / file
        if not is_media_file(file) or target.exists():
            continue  # a chat's folder holds pictures, videos and audio, so that is all that is unpacked
        try:
            copy_entry(zf, name, target)
        except (EntryTooLargeError, zipfile.BadZipFile):
            log.warning("import: skipped %s (too large or damaged)", name)
            continue
        written.append(target)
        stats["images"] = int(_num(stats.get("images")) or 0) + 1
    return written


class _Importer:
    """One export's import: what's here already, and the spaces made along the way."""

    def __init__(self, zf: zipfile.ZipFile, stats: dict[str, JsonValue]) -> None:
        db = get_db()
        self.zf, self.stats = zf, stats
        self.imported = db.get_imported_conversations(SOURCE)
        self.skips = db.get_import_skips(SOURCE)
        self.spaces: dict[str, int] = {}
        self.written: list[Path] = []

    def chat(self, data: Mapping[str, JsonValue]) -> str:
        """Import one chat: "new", "updated", "unchanged", "deleted" or "empty"."""
        src_id = _str(data.get("id"))
        updated = _when(data.get("updated_at"))
        stamp = updated.timestamp() if updated else None
        if not src_id:
            return "empty"
        if src_id in self.skips:
            return "deleted"
        conv = self.imported.get(src_id)
        if conv and conv.import_updated_at == stamp:
            return "unchanged"
        rows = _messages(data)
        if conv is None and not rows:
            return "empty"
        target = conv or _new_conversation(data, self.spaces)
        _settle_pending(rows)
        self.written += _copy_files(self.zf, src_id, target.id, self.stats)
        leaf = data.get("current_leaf_id")
        added, changed = get_db().add_native_import(
            target.id,
            rows,
            _library(data),
            str(leaf) if isinstance(leaf, int) else None,
            ImportStamp(stamp, updated),
        )
        if conv is None:
            return "new"
        return "updated" if added or changed else "unchanged"


class NotAChatExportError(ValueError):
    """The zip's manifest is not this app's chat-export format."""

    def __init__(self) -> None:
        """Name the manifest file that failed the check."""
        super().__init__(f"{MANIFEST} isn't a chat export")


class ExportTooNewError(ValueError):
    """The export was written by a newer version of the app than this server."""

    def __init__(self) -> None:
        """Build the fixed message."""
        super().__init__("This export is from a newer version of the app — update this server first")


def import_native(zf: zipfile.ZipFile, stats: dict[str, JsonValue]) -> list[Path]:
    """Import this app's own export into the stats the ChatGPT import reports; returns the files written."""
    manifest = _MANIFEST.validate_json(zf.read(MANIFEST))
    if manifest.get("format") != FORMAT:
        raise NotAChatExportError
    version = manifest.get("version")
    if not isinstance(version, int) or version > VERSION:
        raise ExportTooNewError
    raw = manifest.get("conversations")
    chats = [_obj(c) for c in (raw if isinstance(raw, list) else [])]
    stats["total"] = len(chats)
    importer = _Importer(zf, stats)
    for data in chats:
        try:
            outcome: str | None = importer.chat(data)
        except Exception as e:  # one bad chat shouldn't stop the rest
            log.exception("importing one chat from the export failed")
            outcome = None
            failed = stats.setdefault("failed", [])
            if isinstance(failed, list):
                failed.append({"title": data.get("title"), "error": str(e)})
        if outcome:
            stats[outcome] = int(_num(stats.get(outcome)) or 0) + 1
        stats["processed"] = int(_num(stats.get("processed")) or 0) + 1
    return importer.written

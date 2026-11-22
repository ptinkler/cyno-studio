"""The media index: every library upload, recorded chat media and orphaned file, built and cached per user."""

import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from web.core import config
from web.core.env import number_env
from web.core.metadata import ChatLibraryItem, ChatMessage, MetadataDB, current_tenant, get_db, iso
from web.jsonutil import as_list, as_number, as_object, as_objects, as_str
from web.media.durations import known_duration
from web.media.paths import LibraryEntry, MediaItem, chat_dir, library_dir, library_kind, media_thumb_url, mtime_iso

if TYPE_CHECKING:
    from web.types import JsonValue

# A new chat file isn't orphaned until it's this old (s): attachments wait in
# the composer, and generations are written before their message records them
ORPHAN_GRACE = 3600


PARAM_FILES = ("first_frame", "last_frame", "source_video")  # chat media params naming one file


def library_items() -> list[LibraryEntry]:
    """The images uploaded straight to the library."""
    d = library_dir()
    if not d.is_dir():
        return []
    return [
        LibraryEntry(
            id=f"lib:{p.name}",
            kind=library_kind(p),
            source="upload",
            origin="library",
            name=p.name,
            url=f"/api/media/library/{p.name}",
            thumb_url=media_thumb_url(f"lib:{p.name}"),
            created_at=mtime_iso(p),
            duration=known_duration(p, library_kind(p)),
        )
        for p in d.iterdir()
        if p.is_file() and library_kind(p)
    ]


def chat_records(
    msgs: list[ChatMessage], lib_items: list[ChatLibraryItem], titles: dict[str, str]
) -> list[LibraryEntry]:
    """The media each chat message and detached library entry records."""
    # Keyed by file name alone: a branched chat links its media in under the
    # same names (web/chat/routes.py api_fork_conversation), so each shows once —
    # in the oldest chat that still has it
    items: dict[str, LibraryEntry] = {}

    def add(conv_id: str, item: MediaItem, created_at: datetime, *, replace: bool = False) -> None:
        file = as_str(item.get("file"))
        if not file or item.get("status", "done") != "done" or (file in items and not replace):
            return
        if not (chat_dir(conv_id) / file).is_file():
            return
        kind = as_str(item.get("kind")) or library_kind(file)
        items[file] = LibraryEntry(
            id=f"chat:{conv_id}:{file}",
            kind=kind,
            duration=known_duration(chat_dir(conv_id) / file, kind),
            source="upload" if item.get("source") == "upload" else "generated",
            origin="chat",
            name=file,
            url=f"/api/chat/media/{conv_id}/{file}",
            thumb_url=media_thumb_url(f"chat:{conv_id}:{file}"),
            created_at=iso(created_at),
            conversation_id=conv_id,
            conversation_title=titles.get(conv_id),
            prompt=as_str(item.get("prompt")),
            model=as_str(item.get("model")),
            cost=as_number(item.get("cost")),
        )

    for msg in msgs:  # newest first, so older copies win
        for item in msg.media:
            add(msg.conversation_id, item, msg.created_at, replace=True)
    for lib in lib_items:  # media detached from its message by older edits/retries
        add(lib.conversation_id, lib.item, lib.created_at)
    return list(items.values())


def referenced_files(item: MediaItem) -> list[str]:
    """Return files referenced by a chat media item and its versions.

    Includes source references retained for retries and replaced images retained
    for version navigation.
    """
    files: list[JsonValue] = [item.get("file")]
    for source in (item, *as_objects(item.get("versions"))):
        params = as_object(source.get("params"))
        named = (as_object(i).get("file") for i in as_list(params.get("ref_items")))
        files += [source.get("file"), *as_list(params.get("refs")), *(params.get(k) for k in PARAM_FILES), *named]
    return [f for f in files if isinstance(f, str) and f]


def _used_files(msgs: list[ChatMessage], lib_items: list[ChatLibraryItem]) -> set[tuple[str, str]]:
    """Every (conversation id, file name) that a message or library entry records."""
    used: set[tuple[str, str]] = set()
    for msg in msgs:
        used.update((msg.conversation_id, f) for i in msg.media for f in referenced_files(i))
    for lib in lib_items:
        used.update((lib.conversation_id, f) for f in referenced_files(lib.item))
    return used


def _orphan_item(p: Path, conv_id: str, kind: str, titles: dict[str, str]) -> LibraryEntry:
    """The library row for one unrecorded file in a chat's folder."""
    media_id = f"chat:{conv_id}:{p.name}"
    return LibraryEntry(
        id=media_id,
        kind=kind,
        source="upload" if p.name.startswith("up_") else "generated",
        origin="orphan",
        name=p.name,
        url=f"/api/chat/media/{conv_id}/{p.name}",
        thumb_url=media_thumb_url(media_id),
        created_at=mtime_iso(p),
        duration=known_duration(p, kind),
        conversation_id=conv_id if conv_id in titles else None,
        conversation_title=titles.get(conv_id),
    )


def _orphans_in(folder: Path, used: set[tuple[str, str]], cutoff: float, titles: dict[str, str]) -> list[LibraryEntry]:
    """The old-enough, unrecorded media files in one chat folder."""
    items: list[LibraryEntry] = []
    for p in folder.iterdir():
        kind = library_kind(p) if p.is_file() and (folder.name, p.name) not in used else None
        if kind and p.stat().st_mtime <= cutoff:
            items.append(_orphan_item(p, folder.name, kind, titles))
    return items


def _chat_orphans(
    msgs: list[ChatMessage], lib_items: list[ChatLibraryItem], titles: dict[str, str]
) -> list[LibraryEntry]:
    """Files in chat folders that no message or library entry records."""
    root = config.ROOT_DIR / "chat"
    if not root.is_dir():
        return []
    used = _used_files(msgs, lib_items)
    cutoff = time.time() - ORPHAN_GRACE
    items: list[LibraryEntry] = []
    # Only the current user's conversation folders (titles is tenant-scoped), so
    # one user's orphan scan never lists another user's files.
    for conv_id in titles:
        d = root / conv_id
        if not d.is_dir() or d.name.startswith("."):  # .deleting-<id>: a deleted chat's files, going
            continue
        items.extend(_orphans_in(d, used, cutoff, titles))
    return items


def build_items(db: MetadataDB) -> list[LibraryEntry]:
    """Build the complete library, newest first.

    Fetches chat messages and detached library entries once for both the
    recorded-media and orphan passes.
    """
    msgs = db.get_chat_messages_with_media()  # newest first (id desc)
    lib_items = db.list_chat_library()
    titles = db.conversation_titles()
    items = [*library_items(), *chat_records(msgs, lib_items, titles), *_chat_orphans(msgs, lib_items, titles)]
    items.sort(key=lambda i: as_str(i.get("created_at")) or "", reverse=True)
    return items


# The built list, cached so paging through it doesn't rebuild it each request
# (scanning the user's chat folders and the chat DB is slow on network or slow storage). Keyed on
# (ROOT_DIR, tenant) so one user never sees another's list, and tests (each with
# their own ROOT_DIR) stay isolated. Writes invalidate it; a short TTL catches
# creations made elsewhere (env MEDIA_LIST_TTL, seconds; 0 turns the cache off, as the end-to-end tests want).
_LIST_TTL = number_env("MEDIA_LIST_TTL", 30.0)


@dataclass
class _ListCacheEntry:
    """A built media list and when (monotonic seconds) it was built."""

    at: float
    items: list[LibraryEntry]


_list_cache: dict[tuple[Path, str | None], _ListCacheEntry] = {}


def all_items() -> list[LibraryEntry]:
    """The complete media list for the current user, newest first, cached briefly."""
    key = (config.ROOT_DIR, current_tenant())
    now = time.monotonic()
    entry = _list_cache.get(key)
    if entry is None or now - entry.at >= _LIST_TTL:
        entry = _ListCacheEntry(at=now, items=build_items(get_db()))
        _list_cache[key] = entry
    return entry.items


def invalidate_list() -> None:
    """Drop the cached media list so the next request rebuilds it."""
    _list_cache.clear()


def origin_label(item: LibraryEntry) -> str:
    """Where an item is from, for search — mirrors mediaOrigin in the frontend."""
    origin = item.get("origin")
    if origin == "chat":
        return as_str(item.get("conversation_title")) or "Chat"
    if origin == "orphan":
        title = as_str(item.get("conversation_title"))
        return f"{title} (orphaned)" if title else "Orphaned"
    return "Library"


def item_matches(item: LibraryEntry, kind: str, source: str, origin: str, q: str) -> bool:
    """Whether an item passes the list's kind / source / origin filters and the search text."""
    if kind != "all" and item.get("kind") != kind:
        return False
    if source != "all" and item.get("source") != source:
        return False
    if origin != "all" and item.get("origin") != origin:
        return False
    if not q:
        return True
    texts = (as_str(item.get("prompt")), as_str(item.get("name")), origin_label(item))
    return any(s and q in s.lower() for s in texts)

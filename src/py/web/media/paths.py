"""Where media lives on disk, and what a media id points at."""

from datetime import datetime
from pathlib import Path
from typing import Literal, NotRequired, TypedDict

from fastapi import HTTPException

from web.core import config
from web.core.metadata import current_tenant, get_db
from web.media.kinds import VIDEO_SUFFIXES
from web.types import JsonValue
from web.uploads.files import (
    image_media_type,
    safe_filename,
)

# One media card of a chat message or detached library entry, as stored (see web/chat/__init__.py).
type MediaItem = dict[str, JsonValue]


class LibraryEntry(TypedDict):
    """One row of the media library list: a file from the library, a chat, or an orphan, with where it is."""

    id: str  # "lib:<file>" or "chat:<conversation id>:<file>"
    kind: str | None  # "image" | "video" (| "audio" for a chat card)
    source: Literal["upload", "generated"]
    origin: Literal["library", "chat", "orphan"]
    name: str
    url: str
    thumb_url: str
    created_at: str | None
    duration: float | None  # video length, once read
    # chat and orphan rows only
    conversation_id: NotRequired[str | None]
    conversation_title: NotRequired[str | None]
    # generated chat rows only
    prompt: NotRequired[str | None]
    model: NotRequired[str | None]
    cost: NotRequired[float | None]


def library_dir() -> Path:
    """Return the current user's media library directory."""
    # Read config at call time so tests can redirect ROOT_DIR. Per-user
    # (<data>/library/<user_id>/) so one user's uploads never show to another;
    # the shared legacy folder is the admin's, migrated by provision_admin.
    base = config.ROOT_DIR / "library"
    uid = current_tenant()
    return base / uid if uid else base


def thumb_dir() -> Path:
    """Return the directory used to cache media thumbnails."""
    return config.ROOT_DIR / "cache" / "media-thumbs"


def chat_dir(conv_id: str) -> Path:
    """A chat's media folder."""
    return config.ROOT_DIR / "chat" / conv_id


def library_kind(path: Path | str) -> str | None:
    """What the library indexes: pictures and videos (not audio)."""
    if Path(path).suffix.lower() in VIDEO_SUFFIXES:
        return "video"
    return "image" if image_media_type(path) else None


def mtime_iso(path: Path) -> str | None:
    """A file's modification time as an ISO string (None if it can't be read)."""
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat()
    except OSError:
        return None


def resolve(media_id: str) -> tuple[str, Path, dict[str, str]]:
    """Resolve an item ID to its origin, file path, and location parts.

    Raises HTTP 400 for malformed IDs and HTTP 404 when an item is unavailable.
    """
    origin, _, rest = media_id.partition(":")
    if origin == "lib":
        path, parts = library_dir() / safe_filename(rest), {}
    elif origin == "chat":
        conv_id, _, file = rest.partition(":")
        # Multi-tenant guard: chat files live under a global <data>/chat/<id>/,
        # so the id alone must not reach another user's files. Allow it only
        # when the chat is the current user's (get_conversation is tenant-
        # scoped) or no conversation row exists anywhere (a truly orphaned
        # folder — e.g. a deleted chat's leftovers, which anyone may clean up).
        # A row owned by a DIFFERENT user reads as not-mine here → 404.
        db = get_db()
        if not db.get_conversation(conv_id) and db.conversation_exists_any_tenant(conv_id):
            raise HTTPException(404, "Media not found")
        path, parts = (
            chat_dir(safe_filename(conv_id)) / safe_filename(file),
            {"conversation_id": conv_id, "file": file},
        )
    else:
        raise HTTPException(400, "Unknown media id")
    if not path.is_file():
        raise HTTPException(404, "Media not found")
    return origin, path, parts


def item_path(item: LibraryEntry) -> Path | None:
    """The file a media item's id points at (None when the id is malformed or the file is gone)."""
    try:
        return resolve(item["id"])[1]
    except HTTPException:
        return None


def media_thumb_url(media_id: str) -> str:
    """The URL of a media item's thumbnail."""
    return f"/api/media/thumb/{media_id}"

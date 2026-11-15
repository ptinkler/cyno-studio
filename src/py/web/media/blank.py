"""Blank (all-black) image detection, cached on disk, and the list of blocked generations."""

import contextlib
import json
import threading
from dataclasses import dataclass
from pathlib import Path

from pydantic import TypeAdapter

from web.core import config
from web.core.metadata import ChatLibraryItem, ChatMessage, MetadataDB
from web.jsonutil import as_str
from web.media.paths import MediaItem, chat_dir
from web.media.thumbs import thumb_path
from web.uploads.files import (
    is_blank_image,
)


# Which saved images are solid black, per file version, kept on disk: the
# Media page asks on every load, and decoding every chat image again after
# each restart takes minutes on a NAS
class _BlankChecks:
    """Which saved images are blank, by file version; loaded from disk on first use."""

    def __init__(self) -> None:
        self.checks: dict[str, bool] | None = None
        self.lock = threading.Lock()


_blank = _BlankChecks()


_BLANK_CHECKS = TypeAdapter(dict[str, bool])


def reset_blank_checks() -> None:
    """Forget the in-memory results so they are read from disk again (as after a restart)."""
    _blank.checks = None


def _blank_cache_path() -> Path:
    return config.ROOT_DIR / "cache" / "blank-images.json"


def _blank_checks() -> dict[str, bool]:
    checks = _blank.checks
    if checks is None:
        try:
            checks = _BLANK_CHECKS.validate_json(_blank_cache_path().read_text())
        except (OSError, ValueError):  # missing, unreadable or malformed: start over (ValidationError is a ValueError)
            checks = {}
        _blank.checks = checks
    return checks


def _save_blank_checks() -> None:
    path = _blank_cache_path()
    with contextlib.suppress(OSError):
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".part")
        tmp.write_text(json.dumps(_blank_checks()))
        tmp.replace(path)


def is_blank_file(path: Path) -> bool:
    """Check and cache whether a saved image is blank.

    Uses the thumbnail instead of the full image when one is available.
    """
    try:
        key = f"{path}:{path.stat().st_mtime}"
    except OSError:
        return False
    checks = _blank_checks()
    if key not in checks:
        thumb = thumb_path(path)
        data = thumb.read_bytes() if thumb.is_file() else path.read_bytes()
        with _blank.lock:
            checks[key] = is_blank_image(data)
    return checks[key]


def blocked_reason(conv_id: str, item: MediaItem) -> str | None:
    """Return why an item is a blocked generation, if applicable.

    Reasons are ``"moderated"`` for content-filter refusals and ``"black"``
    for black images saved before the app detected them.
    """
    if item.get("source") == "upload" or item.get("import_file"):  # imports weren't made by this app's providers
        return None
    if item.get("status") == "error":
        return "moderated" if item.get("moderated") else None
    file = as_str(item.get("file"))
    if item.get("kind") == "image" and item.get("status", "done") == "done" and file:
        path = chat_dir(conv_id) / file
        if path.is_file() and is_blank_file(path):
            return "black"
    return None


@dataclass(frozen=True)
class Blocked:
    """A blocked generation: where it is recorded, the media item itself, and why it is blocked."""

    owner: ChatMessage | ChatLibraryItem
    item: MediaItem
    reason: str


def blocked_generations(db: MetadataDB) -> list[Blocked]:
    """Each blocked generation, with the chat message or detached library entry that records it."""
    checked = len(_blank_checks())
    out: list[Blocked] = []
    for msg in db.get_chat_messages_with_media():
        out += [Blocked(msg, i, r) for i in msg.media if (r := blocked_reason(msg.conversation_id, i))]
    for lib in db.list_chat_library():
        if r := blocked_reason(lib.conversation_id, lib.item):
            out.append(Blocked(lib, lib.item, r))
    if len(_blank_checks()) != checked:
        _save_blank_checks()
    return out

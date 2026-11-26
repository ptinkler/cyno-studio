"""Merge identical files into one: every copy becomes another name for the same bytes on disk."""

import logging
import os
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from web.characters import char_dir
from web.core.metadata import get_db
from web.media.digest import file_digest
from web.media.places import media_dirs

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Merged:
    """What a merge did."""

    files: int  # copies that are now links to another file
    bytes: int  # disk space that freed


def _folders() -> list[Path]:
    """The library, the chats and the characters of the current user: the library first, so its file is the one kept."""
    return [*media_dirs(), *(char_dir(c.id) for c in get_db().list_characters())]


def _files(folder: Path) -> list[Path]:
    if not folder.is_dir() or folder.name.startswith("."):
        return []
    return [p for p in folder.iterdir() if p.is_file() and not p.name.startswith(".")]


def _link_over(keeper: Path, copy: Path) -> bool:
    """Make `copy` a hard link to `keeper` (atomically: the old file stays until the link is ready)."""
    tmp = copy.with_name(f".{copy.name}.merge")
    try:
        os.link(keeper, tmp)
        tmp.replace(copy)
    except OSError:  # another filesystem, no link support, a file in use: leave this one as it is
        tmp.unlink(missing_ok=True)
        return False
    return True


def _same_size_groups() -> list[list[Path]]:
    """Files grouped by size; only groups of several can hold copies."""
    by_size: dict[int, list[Path]] = defaultdict(list)
    for folder in _folders():
        for path in _files(folder):
            by_size[path.stat().st_size].append(path)
    return [g for g in by_size.values() if len(g) > 1]


def _merge_group(paths: list[Path]) -> int:
    """Link the copies among same-size files to the first of each; returns how many were linked."""
    first: dict[str, Path] = {}
    linked = 0
    for path in paths:
        digest = file_digest(path)
        keeper = first.setdefault(digest, path) if digest else path
        if keeper is not path and not os.path.samestat(keeper.stat(), path.stat()) and _link_over(keeper, path):
            linked += 1
    return linked


def merge_duplicates() -> Merged:
    """Turn every extra copy of a file (same bytes, in the library, a chat or a character) into a link to the first.

    Nothing changes for the app: each name still opens. Only the disk space is shared.
    """
    files = freed = 0
    for group in _same_size_groups():
        linked = _merge_group(group)
        files += linked
        freed += linked * group[0].stat().st_size
    if files:
        log.info("merged %d duplicate file(s), %d bytes", files, freed)
    return Merged(files, freed)

"""merge identical media files into one: library, chat and character copies become hard links.

Revision ID: 0036
Revises: 0035
Create Date: 2026-11-26

Using a library picture in a chat, or uploading it twice, used to leave a separate copy each time. New copies are
no longer made (they link to the existing file); this turns the ones already on disk into links, once, when the
database is migrated. Nothing else is left behind: no marker, no setting, no endpoint. A user's files are only
ever merged with that same user's files. It never fails the migration: what can't be linked stays as it is.
"""

import hashlib
import logging
import os
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path

import sqlalchemy as sa
from alembic import op

from web.core import config

revision: str = "0036"
down_revision: str | Sequence[str] | None = "0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

log = logging.getLogger(__name__)

# Whose files they are: a user id, or None for the legacy admin's
type Owner = str | None


def _files(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    return [p for p in folder.iterdir() if p.is_file() and not p.name.startswith(".")]


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _link_over(keeper: Path, copy: Path) -> bool:
    """Make `copy` a hard link to `keeper`; the old file stays until the link is ready."""
    tmp = copy.with_name(f".{copy.name}.merge")
    try:
        os.link(keeper, tmp)
        tmp.replace(copy)
    except OSError:  # another filesystem, no link support: this one stays a copy
        tmp.unlink(missing_ok=True)
        return False
    return True


def merge_identical(folders: dict[Owner, list[Path]]) -> tuple[int, int]:
    """Link identical files of each owner to the first one found; returns (files linked, bytes freed)."""
    linked = freed = 0
    for owned in folders.values():
        by_size: dict[int, list[Path]] = defaultdict(list)
        for folder in owned:
            for path in _files(folder):
                by_size[path.stat().st_size].append(path)
        for same_size in (g for g in by_size.values() if len(g) > 1):
            first: dict[str, Path] = {}
            for path in same_size:
                keeper = first.setdefault(_digest(path), path)
                if keeper is not path and not os.path.samestat(keeper.stat(), path.stat()) and _link_over(keeper, path):
                    linked += 1
                    freed += path.stat().st_size
    return linked, freed


def _folders(root: Path, bind: sa.engine.Connection) -> dict[Owner, list[Path]]:
    """Every media folder under `root`, by the user who owns it (library first: its file is the one kept)."""
    out: dict[Owner, list[Path]] = defaultdict(list)
    library = root / "library"
    if library.is_dir():
        out[None].append(library)  # the legacy admin's files sit directly in it
        out.update({sub.name: [sub] for sub in library.iterdir() if sub.is_dir()})
    for table, folder in (("chat_conversations", "chat"), ("characters", "characters")):
        rows = bind.execute(
            sa.select(sa.column("id", sa.String()), sa.column("user_id", sa.String())).select_from(sa.table(table))
        )
        for row_id, user_id in rows:
            out[user_id].append(root / folder / str(row_id))
    return out


def upgrade() -> None:
    """Merge the copies. Any failure is logged and the migration still succeeds."""
    try:
        linked, freed = merge_identical(_folders(config.ROOT_DIR, op.get_bind()))
        if linked:
            log.info("merged %d duplicate media file(s) into links, freeing %d bytes", linked, freed)
    except Exception:  # a failed tidy-up must never stop the server starting
        log.exception("merging duplicate media files failed; they stay as they are")


def downgrade() -> None:
    """Nothing to undo: a linked file is an ordinary file."""

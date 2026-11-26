"""Migration 0036: identical media files of one user become links to one file, once, and nothing is left behind."""

import importlib.util
import os
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

import web.core.config as config

MIGRATION = Path(__file__).parent.parent / "alembic" / "versions" / "0036_merge_identical_media.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migration_0036", MIGRATION)
    assert spec
    assert spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _put(root: Path, where: str, name: str, data: bytes) -> Path:
    path = root / where / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _same(a: Path, b: Path) -> bool:
    return os.path.samestat(a.stat(), b.stat())


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sa.Connection]:
    """A database with chats and characters of two users (u1, u2) and the legacy admin (no user)."""
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'm.db'}")
    with engine.begin() as c:
        c.execute(sa.text("CREATE TABLE chat_conversations (id VARCHAR(50) PRIMARY KEY, user_id VARCHAR(50))"))
        c.execute(sa.text("CREATE TABLE characters (id INTEGER PRIMARY KEY, user_id VARCHAR(50))"))
        c.execute(
            sa.text("INSERT INTO chat_conversations VALUES ('c1', 'u1'), ('c2', 'u1'), ('c3', 'u2'), ('c4', NULL)")
        )
        c.execute(sa.text("INSERT INTO characters VALUES (1, 'u1'), (2, 'u2')"))
        yield c


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The data folder the migration reads."""
    monkeypatch.setattr(config, "ROOT_DIR", tmp_path / "data")
    return tmp_path / "data"


def _upgrade(conn: sa.Connection, module: ModuleType | None = None) -> None:
    direction = "upgrade"
    with Operations.context(MigrationContext.configure(conn)):
        getattr(module or _load(), direction)()


def test_a_users_copies_in_library_chats_and_characters_become_one_file(conn: sa.Connection, root: Path) -> None:
    """The same picture, kept three ways for one user, ends up as one file on disk."""
    lib = _put(root, "library/u1", "up_a.png", b"picture-a")
    chat1 = _put(root, "chat/c1", "up_a.png", b"picture-a")
    chat2 = _put(root, "chat/c2", "up_a.png", b"picture-a")
    char = _put(root, "characters/1", "img_x.png", b"picture-a")
    _upgrade(conn)
    assert all(_same(lib, p) for p in (chat1, chat2, char))
    assert lib.read_bytes() == b"picture-a"


def test_different_pictures_and_different_users_stay_apart(conn: sa.Connection, root: Path) -> None:
    """Same size but different bytes are kept; one user's file is never linked to another user's."""
    mine = _put(root, "chat/c1", "a.png", b"aaaaaaaa")
    other_bytes = _put(root, "chat/c2", "b.png", b"bbbbbbbb")
    theirs = _put(root, "chat/c3", "a.png", b"aaaaaaaa")
    legacy = _put(root, "chat/c4", "a.png", b"aaaaaaaa")
    _upgrade(conn)
    assert not _same(mine, other_bytes)
    assert not _same(mine, theirs)
    assert not _same(mine, legacy)
    assert not _same(theirs, legacy)


def test_nothing_is_left_behind(conn: sa.Connection, root: Path) -> None:
    """Only the files themselves remain: no marker, no temporary link."""
    _put(root, "chat/c1", "a.png", b"same")
    _put(root, "chat/c2", "a.png", b"same")
    before = {p for p in root.rglob("*") if p.is_file()}
    _upgrade(conn)
    assert {p for p in root.rglob("*") if p.is_file()} == before
    assert not list(root.rglob(".*.merge"))


def test_a_failure_does_not_stop_the_migration(
    conn: sa.Connection, root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The tidy-up is optional: whatever goes wrong, the upgrade still finishes."""
    module = _load()

    def boom(_folders: object) -> tuple[int, int]:
        raise OSError

    monkeypatch.setattr(module, "merge_identical", boom)
    _upgrade(conn, module)

"""Concurrent database access: no update may be lost, and readers and backups never wait on a writer."""

import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import OperationalError

from web.core.metadata import MetadataDB
from web.core.metadata.models import ChatInstruction

THREADS = 12
READ_DEADLINE = 3.0  # seconds a read may take while a writer holds the write lock (it should be instant)


@pytest.fixture
def database(tmp_path: Path) -> Iterator[MetadataDB]:
    """A fresh database file, closed afterwards."""
    db = MetadataDB(db_path=tmp_path / "data" / "metadata.db")
    yield db
    db.engine.dispose()
    db.read_engine.dispose()


def _in_parallel(jobs: list[Callable[[], object]]) -> None:
    """Run the jobs on their own threads, released together, and re-raise the first failure."""
    start = threading.Barrier(len(jobs))

    def run(job: Callable[[], object]) -> None:
        start.wait()
        job()

    with ThreadPoolExecutor(len(jobs)) as pool:
        for future in [pool.submit(run, job) for job in jobs]:
            future.result()


def test_concurrent_increments_are_all_counted(database: MetadataDB) -> None:
    """Test that read-modify-write counters lose nothing when many threads bump them at once."""
    user = database.create_local_admin("a@example.com", "hash")
    before = database.get_user(user.id)
    assert before is not None
    rounds = 15

    def bump() -> None:
        for _ in range(rounds):
            database.bump_session_version(user.id)

    _in_parallel([bump] * THREADS)
    after = database.get_user(user.id)
    assert after is not None
    assert after.session_version == before.session_version + THREADS * rounds


def test_concurrent_list_rewrites_leave_no_dangling_ids(database: MetadataDB) -> None:
    """Test that deleting snippets in parallel removes every deleted id from the chats that listed them.

    Each delete rewrites a JSON list on every chat (read, remove one id, write back), so a lost update leaves a
    deleted id behind.
    """
    snippets = [database.save_instruction(name=f"s{i}", content="x").id for i in range(THREADS)]
    chats = [database.create_conversation(f"c{i}", instruction_ids=list(snippets)) for i in range(6)]

    _in_parallel([lambda sid=sid: database.delete_instruction(sid) for sid in snippets])

    for chat in chats:
        fresh = database.get_conversation(chat.id)
        assert fresh is not None
        assert fresh.instruction_ids == []


def test_concurrent_saves_of_different_fields_both_stick(database: MetadataDB) -> None:
    """Test that two threads updating different rows (and one row's different fields) all land."""
    items = [database.save_instruction(name=f"n{i}", content="old").id for i in range(THREADS)]

    def rename(item_id: int) -> None:
        database.save_instruction(item_id, name=f"renamed-{item_id}")

    _in_parallel([lambda item_id=item_id: rename(item_id) for item_id in items])
    names = {i.id: i.name for i in database.list_instructions()}
    assert names == {item_id: f"renamed-{item_id}" for item_id in items}


def test_a_read_does_not_wait_for_a_writer(database: MetadataDB) -> None:
    """Test that a lookup returns at once while another thread holds the write lock."""
    user = database.create_local_admin("a@example.com", "hash")
    holding = threading.Event()
    release = threading.Event()

    def hold_the_write_lock() -> None:
        with database.write_session() as session:
            session.execute(sa.update(ChatInstruction).values(content="x"))  # first statement takes the write lock
            holding.set()
            release.wait(timeout=10)

    writer = threading.Thread(target=hold_the_write_lock)
    writer.start()
    try:
        assert holding.wait(timeout=5)
        started = time.monotonic()
        assert database.get_user(user.id) is not None
        assert time.monotonic() - started < READ_DEADLINE
    finally:
        release.set()
        writer.join(timeout=10)


def test_a_backup_does_not_wait_for_a_writer(database: MetadataDB, tmp_path: Path) -> None:
    """Test that a backup completes while another thread holds the write lock, and is a readable copy."""
    database.save_instruction(name="kept", content="x")
    holding = threading.Event()
    release = threading.Event()

    def hold_the_write_lock() -> None:
        with database.write_session() as session:
            session.execute(sa.update(ChatInstruction).values(content="y"))
            holding.set()
            release.wait(timeout=10)

    writer = threading.Thread(target=hold_the_write_lock)
    writer.start()
    try:
        assert holding.wait(timeout=5)
        target = tmp_path / "copy.db"
        started = time.monotonic()
        database.backup_to(target)
        assert time.monotonic() - started < READ_DEADLINE
    finally:
        release.set()
        writer.join(timeout=10)
    copy = MetadataDB(db_path=target)
    try:
        assert [i.name for i in copy.list_instructions()] == ["kept"]
    finally:
        copy.engine.dispose()
        copy.read_engine.dispose()


def _write_through_a_read_session(database: MetadataDB) -> None:
    with database.read_session() as session:
        session.add(ChatInstruction(name="nope", content=""))
        session.commit()


def test_a_read_session_cannot_write(database: MetadataDB) -> None:
    """Test that a session opened for reading refuses writes (a misclassified call site fails at once)."""
    with pytest.raises(OperationalError, match="readonly"):
        _write_through_a_read_session(database)

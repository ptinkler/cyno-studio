"""Provide infrastructure shared by the metadata database mixins.

This module configures the two engines and the SQLite pragmas, provides the
write and read session context managers and shared list/get/save helpers, and
detaches ids from JSON-backed lists. Alembic owns the schema; see ``schema.py``.

Concurrency: the database runs in WAL mode, so readers never block the writer
and the writer never blocks readers. SQLite allows ONE writer at a time, and a
write session takes that write lock when its transaction begins
(``BEGIN IMMEDIATE``), so a read-modify-write inside it cannot interleave with
another writer: no update is lost. Read sessions use a separate engine whose
connections refuse writes, so a call site that writes through ``read_session``
fails at once instead of racing.
"""

import inspect
import logging
import sqlite3
from collections.abc import Generator, Mapping
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Protocol, TypeVar, cast, overload

import sqlalchemy as sa
from sqlalchemy import create_engine, event
from sqlalchemy.orm import InstrumentedAttribute, Session
from sqlalchemy.sql.elements import ColumnElement

from web.core.config import DB_PATH
from web.core.fsinfo import filesystem_type, is_network_filesystem
from web.core.metadata.models import Base
from web.types import JsonValue

log = logging.getLogger(__name__)

ModelT = TypeVar("ModelT", bound=Base)


class UnknownFieldError(AttributeError):
    """A row update named a field the model doesn't have."""

    def __init__(self, model: str, name: str) -> None:
        super().__init__(f"{model} has no field {name!r}")


def set_fields(item: object, fields: Mapping[str, JsonValue | datetime]) -> None:
    """Set values on a row by field name: a column, or a property with a setter.

    An unknown name raises instead of being silently dropped (or set as a stray attribute that is never saved), so
    a misspelt field in a caller fails at once.
    """
    cls = type(item)
    for name, value in fields.items():
        # Columns (instrumented attributes) and properties both have __set__; plain methods and unknown names don't.
        if not hasattr(cast("object", inspect.getattr_static(cls, name, None)), "__set__"):
            raise UnknownFieldError(cls.__name__, name)
        setattr(item, name, value)


class _Stamped(Protocol):
    """A row that records when it was last changed."""

    updated_at: datetime


OrderByT = TypeVar("OrderByT")


def _make_engine(db_path: Path, *, read_only: bool) -> sa.Engine:
    """An engine on the database file: the writer's (takes the write lock per transaction) or a read-only one.

    Python's sqlite3 module normally starts transactions itself, and only before a write, so a read followed by a
    write would not be inside one transaction. Turning that off and issuing BEGIN ourselves (SQLAlchemy's documented
    recipe for pysqlite) makes the transaction start where the session does.
    """
    engine = create_engine(
        f"sqlite:///{db_path}",
        echo=False,
        connect_args={"check_same_thread": False, "timeout": 30},  # wait up to 30 s for the write lock
    )

    @event.listens_for(engine, "connect")
    def _configure(dbapi_conn: sqlite3.Connection, _connection_record: sa.pool.ConnectionPoolEntry) -> None:
        dbapi_conn.isolation_level = None  # we emit BEGIN ourselves (see _begin)
        cursor = dbapi_conn.cursor()
        if read_only:
            cursor.execute("PRAGMA query_only=ON")  # any write fails with "attempt to write a readonly database"
        else:
            cursor.execute("PRAGMA journal_mode=WAL")  # persists in the file; needs a local disk, not a network share
            cursor.execute("PRAGMA synchronous=NORMAL")  # safe with WAL: a crash can lose the last commits, not corrupt
        cursor.close()

    @event.listens_for(engine, "begin")
    def _begin(conn: sa.Connection) -> None:
        # IMMEDIATE takes the single write lock now, before the first read, so read-modify-write cannot interleave.
        conn.exec_driver_sql("BEGIN" if read_only else "BEGIN IMMEDIATE")

    return engine


class DBBase:
    """Provide the engines and sessions used by domain mixins.

    Also handles fresh-database initialization and shared ORM helpers.
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if is_network_filesystem(self.db_path.parent):
            log.warning(
                "the database folder %s is on a network filesystem (%s): SQLite's WAL mode is NOT safe there and can "
                "corrupt the database. Put the database on a local disk (CYNO_DB_DIR).",
                self.db_path.parent,
                filesystem_type(self.db_path.parent),
            )
        self.engine = _make_engine(self.db_path, read_only=False)  # the writer: also creates and migrates the file
        self.read_engine = _make_engine(self.db_path, read_only=True)

        # Alembic owns the schema (see schema.ensure_schema, run at startup).
        # create_all only has to make the tables of a brand-new file.
        fresh = not sa.inspect(self.engine).has_table("chat_conversations")
        Base.metadata.create_all(self.engine)
        self.is_fresh = fresh

    def backup_to(self, target: Path) -> None:
        """Write a consistent copy of the database to `target` (which must not exist).

        VACUUM INTO reads one snapshot, so it neither blocks writers nor is disturbed by them.
        """
        raw = self.engine.raw_connection()
        try:
            cast("sqlite3.Connection", raw.driver_connection).execute("VACUUM INTO ?", (str(target),))
        finally:
            raw.close()

    @contextmanager
    def write_session(self) -> Generator[Session]:
        """Yield a Session whose transaction takes the database's write lock when it begins.

        Use it for anything that writes, and for read-modify-write: other writers wait (up to 30 s) until it ends, so
        nothing it read can change underneath it. Readers are not blocked.
        """
        with Session(self.engine) as session:
            yield session

    @contextmanager
    def read_session(self) -> Generator[Session]:
        """Yield a read-only Session that sees one consistent snapshot and never waits for a writer.

        Writing through it fails ("attempt to write a readonly database").
        """
        with Session(self.read_engine) as session:
            yield session

    # ── small helpers the domain mixins share. Each opens a session, does the
    #    one thing, and detaches what it returns so callers hold plain objects.

    def _list(
        self,
        model: type[ModelT],
        order_by: ColumnElement[OrderByT] | InstrumentedAttribute[OrderByT] | None = None,
    ) -> list[ModelT]:
        with self.read_session() as session:
            query = session.query(model)
            items = (query.order_by(order_by) if order_by is not None else query).all()
            for item in items:
                session.expunge(item)
            return items

    def _get(self, model: type[ModelT], pk: int | str) -> ModelT | None:
        with self.read_session() as session:
            item = session.get(model, pk)
            if item:
                session.expunge(item)
            return item

    @overload
    def _save(self, model: type[ModelT], pk: None, **fields: JsonValue) -> ModelT: ...

    @overload
    def _save(self, model: type[ModelT], pk: int | str, **fields: JsonValue) -> ModelT | None: ...

    def _save(self, model: type[ModelT], pk: int | str | None, **fields: JsonValue) -> ModelT | None:
        """Create (pk None) or update one row; None if the pk isn't there."""
        with self.write_session() as session:
            if pk is None:
                item = model(**fields)
                session.add(item)
            else:
                item = session.get(model, pk)
                if not item:
                    return None
                set_fields(item, fields)
                cast("_Stamped", item).updated_at = datetime.now().astimezone().replace(tzinfo=None)
            session.commit()
            session.refresh(item)
            session.expunge(item)
            return item

    @staticmethod
    def _detach_id(
        session: Session,
        model: type[ModelT],
        json_column: InstrumentedAttribute[OrderByT],
        list_attr: str,
        target_id: int,
    ) -> None:
        """Remove an id from a JSON-backed list on matching rows.

        The SQL ``LIKE`` narrows the rows; membership is checked exactly
        before the id is removed.
        """
        for row in session.query(model).filter(json_column.like(f"%{target_id}%")).all():
            ids = cast("list[int]", getattr(row, list_attr))
            if target_id in ids:
                setattr(row, list_attr, [i for i in ids if i != target_id])

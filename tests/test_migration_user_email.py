"""Migration 0032: users.email may be null, and the table keeps its rows, its unique email and its index."""

import importlib.util
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.exc import IntegrityError

MIGRATION = Path(__file__).parent.parent / "alembic" / "versions" / "0032_user_email_nullable.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migration_0032", MIGRATION)
    assert spec
    assert spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sa.Connection]:
    """A database holding the users table as it was before the migration, with one user."""
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'm.db'}")
    with engine.begin() as c:
        c.execute(
            sa.text(
                "CREATE TABLE users (id VARCHAR(50) PRIMARY KEY, email VARCHAR(320) NOT NULL, name VARCHAR(255),"
                " provider VARCHAR(32) NOT NULL, provider_sub VARCHAR(255) NOT NULL,"
                " is_admin BOOLEAN NOT NULL DEFAULT 0)"
            )
        )
        c.execute(sa.text("CREATE UNIQUE INDEX ix_users_email ON users (email)"))
        c.execute(
            sa.text("INSERT INTO users (id, email, provider, provider_sub) VALUES ('u1', 'a@x.com', 'google', 'g')")
        )
        yield c
    engine.dispose()


def _run(conn: sa.Connection, direction: str) -> None:
    module = _load()
    with Operations.context(MigrationContext.configure(conn)):
        getattr(module, direction)()


def _email_nullable(conn: sa.Connection) -> bool:
    return next(c for c in sa.inspect(conn).get_columns("users") if c["name"] == "email")["nullable"]


def test_upgrade_allows_no_email_and_keeps_everything_else(conn: sa.Connection) -> None:
    """Existing rows survive, the email stays unique, and any number of accounts can have none."""
    assert not _email_nullable(conn)
    _run(conn, "upgrade")
    assert _email_nullable(conn)
    assert conn.execute(sa.text("SELECT email FROM users WHERE id = 'u1'")).scalar_one() == "a@x.com"
    indexes = {i["name"]: i["unique"] for i in sa.inspect(conn).get_indexes("users")}
    assert indexes["ix_users_email"]
    conn.execute(sa.text("INSERT INTO users (id, provider, provider_sub) VALUES ('u2', 'x', '1')"))
    conn.execute(sa.text("INSERT INTO users (id, provider, provider_sub) VALUES ('u3', 'x', '2')"))
    with pytest.raises(IntegrityError):
        conn.execute(
            sa.text("INSERT INTO users (id, email, provider, provider_sub) VALUES ('u4', 'a@x.com', 'g', 'z')")
        )


def test_downgrade_gives_email_less_accounts_a_placeholder(conn: sa.Connection) -> None:
    """The old column required a value, so none is left null."""
    _run(conn, "upgrade")
    conn.execute(sa.text("INSERT INTO users (id, provider, provider_sub) VALUES ('u2', 'x', '1')"))
    _run(conn, "downgrade")
    assert not _email_nullable(conn)
    assert conn.execute(sa.text("SELECT email FROM users WHERE id = 'u2'")).scalar_one() == "u2@no-email.invalid"


def test_running_it_twice_changes_nothing(conn: sa.Connection) -> None:
    """Migrations here are idempotent (a database may already have been created from the model)."""
    _run(conn, "upgrade")
    _run(conn, "upgrade")
    assert _email_nullable(conn)

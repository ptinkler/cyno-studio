"""strip the v1 suffix from stored Pollo model ids.

Revision ID: 0027
Revises: 0026
Create Date: 2026-11-10

Pollo's legacy (pre-v1) endpoints are gone, so the engine's model keys no
longer need to say which API generation they belong to: "seedance20fastv1"
is now "seedance20fast". Those keys are stored as "pollo/<key>" wherever a
generation recorded which model made it, so rewrite them in place.

The ids are labels on past work — history, the composer's remembered picks —
so this is cosmetic, but leaving them stale would show "unknown model" on old
cards and lose a thread's model selection.

Note: a few renamed keys match ids that belonged to the removed legacy models
of the same name (legacy "seedance20fast" and v1 "seedance20fastv1" both end
up "seedance20fast"). Those are the same model on a different endpoint, so
history pointing at the surviving one is right.

Ids of models that were removed outright with the legacy endpoints (Pollo
Image 2.0, Qwen Image) are deliberately left as they are: they record what
actually made that image, so the card shows the bare key rather than a label.
"""

import json
from collections.abc import Sequence
from typing import cast

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

type _JsonValue = str | int | float | bool | list[_JsonValue] | dict[str, _JsonValue] | None

revision: str = "0027"
down_revision: str | Sequence[str] | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PREFIX = "pollo/"
SUFFIX = "v1"
# Plain string columns holding one model id
_COLUMNS = [
    ("chat_conversations", "text_model"),
    ("chat_conversations", "image_model"),
    ("chat_conversations", "video_model"),
    ("chat_messages", "model"),
    ("chat_settings", "title_model"),
]
# JSON columns: (table, column, whether the JSON is a list of media items)
_JSON_COLUMNS = [
    ("chat_messages", "media_json", True),  # [ {model: …}, … ]
    ("chat_library_items", "item_json", False),  # { model: … }
    ("chat_conversations", "settings_json", False),  # { audio_model: … }
]
_JSON_KEYS = ("model", "audio_model", "text_model", "image_model", "video_model")


def _renamed(value: _JsonValue, *, to_v1: bool) -> _JsonValue:
    """One model id, with the v1 suffix stripped (or put back on a downgrade).

    Anything that isn't a suffixed Pollo id is returned unchanged.
    """
    if not isinstance(value, str) or not value.startswith(PREFIX):
        return value
    key = value[len(PREFIX) :]
    if to_v1:
        return value if key.endswith(SUFFIX) else f"{PREFIX}{key}{SUFFIX}"
    return f"{PREFIX}{key[: -len(SUFFIX)]}" if key.endswith(SUFFIX) else value


def _walk(data: _JsonValue, *, to_v1: bool) -> bool:
    """Rewrite every model id in a decoded JSON value; True if anything changed."""
    if isinstance(data, list):
        return sum(_walk(item, to_v1=to_v1) for item in data) > 0  # sum, not any: every item must be visited
    if isinstance(data, dict):
        return sum(_walk_entry(data, key, to_v1=to_v1) for key in list(data)) > 0
    return False


def _walk_entry(data: dict[str, _JsonValue], key: str, *, to_v1: bool) -> bool:
    """Rewrite one key of a JSON object (a model id, or a nested value to descend into)."""
    value = data[key]
    if key in _JSON_KEYS:
        new = _renamed(value, to_v1=to_v1)
        if new == value:
            return False
        data[key] = new
        return True
    return isinstance(value, list | dict) and _walk(value, to_v1=to_v1)


def _table(table: str, column: str) -> sa.TableClause:
    """A lightweight handle on one text column of a table, plus SQLite's rowid."""
    return sa.table(table, sa.column("rowid", sa.Integer), sa.column(column, sa.Text()))


def _rewrite_columns(bind: Connection, tables: set[str], *, to_v1: bool) -> int:
    """Rewrite the plain model-id columns; returns how many rows changed."""
    changed_rows = 0
    for table, column in _COLUMNS:
        if table not in tables:
            continue
        target = _table(table, column)
        rows = cast(
            "list[tuple[int, str]]",
            bind.execute(sa.select(target.c.rowid, target.c[column]).where(target.c[column].like(f"{PREFIX}%")))
            .tuples()
            .all(),
        )
        for rowid, value in rows:
            new = _renamed(value, to_v1=to_v1)
            if new != value:
                bind.execute(sa.update(target).where(target.c.rowid == rowid).values({column: new}))
                changed_rows += 1
    return changed_rows


def _rewrite_json_columns(bind: Connection, tables: set[str], *, to_v1: bool) -> int:
    """Rewrite model ids nested inside the JSON columns; returns how many rows changed."""
    changed_rows = 0
    for table, column, _is_list in _JSON_COLUMNS:
        if table not in tables:
            continue
        target = _table(table, column)
        json_rows = cast(
            "list[tuple[int, str | None]]",
            bind.execute(sa.select(target.c.rowid, target.c[column]).where(target.c[column].like(f"%{PREFIX}%")))
            .tuples()
            .all(),
        )
        for rowid, raw in json_rows:
            try:
                data = cast("_JsonValue", json.loads(raw or ""))
            except (TypeError, ValueError):
                continue  # not readable JSON: leave it exactly as it is
            if _walk(data, to_v1=to_v1):
                bind.execute(sa.update(target).where(target.c.rowid == rowid).values({column: json.dumps(data)}))
                changed_rows += 1
    return changed_rows


def rewrite(bind: Connection, *, to_v1: bool = False) -> int:
    """Rewrite every stored Pollo model id; returns how many rows changed.

    Takes the bind so it can be tested without an Alembic context.
    """
    tables = set(sa.inspect(bind).get_table_names())
    return _rewrite_columns(bind, tables, to_v1=to_v1) + _rewrite_json_columns(bind, tables, to_v1=to_v1)


def upgrade() -> None:
    """Remove the v1 suffix from stored Pollo model IDs."""
    rewrite(op.get_bind(), to_v1=False)


def downgrade() -> None:
    """Restore the v1 suffix to stored Pollo model IDs."""
    rewrite(op.get_bind(), to_v1=True)

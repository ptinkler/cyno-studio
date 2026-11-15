"""Migration 0027: stripping the v1 suffix from stored Pollo model ids.

The ids live in plain columns and inside JSON, so the rewrite has to reach
every place a generation recorded which model made it — and leave every other
provider's ids (and unreadable JSON) untouched.
"""

import importlib.util
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Protocol, cast

import pytest
import sqlalchemy as sa
from pydantic import TypeAdapter

from tests.jsonpath import dig, must, text
from web.types import JsonValue

pytestmark = pytest.mark.no_tenant

_JSON = TypeAdapter[JsonValue](JsonValue)


class _Migration(Protocol):
    """The part of migration 0027 these tests call."""

    def rewrite(self, bind: sa.Connection, to_v1: bool = False) -> int:
        """Rewrite every stored Pollo model id; returns how many rows changed."""
        raise NotImplementedError


def _migration() -> _Migration:
    path = Path(__file__).parent.parent / "alembic" / "versions" / "0027_drop_pollo_v1_suffix.py"
    spec = must(importlib.util.spec_from_file_location("m0027", path))
    mod = importlib.util.module_from_spec(spec)
    must(spec.loader).exec_module(mod)
    return cast("_Migration", mod)


def _scalar(bind: sa.Connection, sql: str) -> str | None:
    """The first column of the first row of ``sql``."""
    return cast("str | None", bind.execute(sa.text(sql)).scalar())


def _row(bind: sa.Connection, sql: str) -> dict[str, JsonValue]:
    """The single row ``sql`` returns, by column name."""
    return cast("dict[str, JsonValue]", dict(bind.execute(sa.text(sql)).mappings().one()))


def _loads(raw: str | None) -> JsonValue:
    """Decode a JSON column."""
    return _JSON.validate_json(must(raw))


@pytest.fixture
def bind() -> Iterator[sa.Connection]:
    """Provide the bind fixture."""
    eng = sa.create_engine("sqlite://")
    with eng.begin() as c:
        c.execute(
            sa.text(
                "CREATE TABLE chat_conversations (id TEXT, text_model TEXT, image_model TEXT,"
                " video_model TEXT, settings_json TEXT)"
            )
        )
        c.execute(sa.text("CREATE TABLE chat_messages (id INTEGER PRIMARY KEY, model TEXT, media_json TEXT)"))
        c.execute(sa.text("CREATE TABLE chat_library_items (id TEXT, item_json TEXT)"))
        c.execute(sa.text("CREATE TABLE chat_settings (id INTEGER PRIMARY KEY, title_model TEXT)"))
        yield c


def test_rewrites_every_stored_id(bind: sa.Connection) -> None:
    """Test that rewrites every stored id."""
    mod = _migration()
    bind.execute(
        sa.text(
            "INSERT INTO chat_conversations VALUES ('c', 'anthropic/claude', 'pollo/seedreamv1',"
            " 'pollo/seedance20fastv1', :s)"
        ),
        {"s": json.dumps({"audio_model": "pollo/elevenv3v1", "image_options": {"resolution": "1K"}})},
    )
    bind.execute(
        sa.text("INSERT INTO chat_messages VALUES (1, 'pollo/pollo30v1', :m)"),
        {
            "m": json.dumps(
                [
                    {"id": "a", "kind": "image", "model": "pollo/seedreamprov1", "prompt": "a fox"},
                    {"id": "b", "kind": "video", "model": "venice/wan-2-5", "params": {"duration": 5}},
                ]
            )
        },
    )
    bind.execute(
        sa.text("INSERT INTO chat_library_items VALUES ('x', :i)"),
        {"i": json.dumps({"id": "x", "model": "pollo/klingv3imagev1"})},
    )
    bind.execute(sa.text("INSERT INTO chat_settings VALUES (1, 'pollo/pollo30v1')"))

    # one update per column touched: image_model, video_model, settings_json,
    # chat_messages.model, media_json, item_json, title_model
    assert mod.rewrite(bind) == 7

    conv = _row(bind, "SELECT * FROM chat_conversations")
    assert conv["image_model"] == "pollo/seedream"
    assert conv["video_model"] == "pollo/seedance20fast"
    assert conv["text_model"] == "anthropic/claude"  # another provider's id is left alone
    assert _loads(text(conv, "settings_json")) == {
        "audio_model": "pollo/elevenv3",
        "image_options": {"resolution": "1K"},
    }

    msg = _row(bind, "SELECT * FROM chat_messages")
    assert msg["model"] == "pollo/pollo30"
    media = _loads(text(msg, "media_json"))
    assert dig(media, 0, "model") == "pollo/seedreampro"
    assert dig(media, 1, "model") == "venice/wan-2-5"
    assert dig(media, 1, "params") == {"duration": 5}  # nothing else in the item is touched

    lib = _scalar(bind, "SELECT item_json FROM chat_library_items")
    assert dig(_loads(lib), "model") == "pollo/klingv3image"
    assert _scalar(bind, "SELECT title_model FROM chat_settings") == "pollo/pollo30"


def test_is_idempotent_and_reversible(bind: sa.Connection) -> None:
    """Test that is idempotent and reversible."""
    mod = _migration()
    bind.execute(sa.text("INSERT INTO chat_conversations VALUES ('c', NULL, 'pollo/seedreamv1', NULL, NULL)"))
    assert mod.rewrite(bind) == 1
    assert mod.rewrite(bind) == 0  # a second run has nothing left to do
    assert _scalar(bind, "SELECT image_model FROM chat_conversations") == "pollo/seedream"
    mod.rewrite(bind, to_v1=True)  # downgrade
    assert _scalar(bind, "SELECT image_model FROM chat_conversations") == "pollo/seedreamv1"


def test_leaves_unreadable_json_alone(bind: sa.Connection) -> None:
    """Test that leaves unreadable json alone."""
    mod = _migration()
    bind.execute(sa.text("INSERT INTO chat_messages VALUES (1, NULL, 'pollo/ not json {')"))
    assert mod.rewrite(bind) == 0
    assert _scalar(bind, "SELECT media_json FROM chat_messages") == "pollo/ not json {"


def test_skips_tables_that_do_not_exist_yet() -> None:
    """An older database may predate some of these tables."""
    mod = _migration()
    eng = sa.create_engine("sqlite://")
    with eng.begin() as c:
        c.execute(sa.text("CREATE TABLE chat_messages (id INTEGER PRIMARY KEY, model TEXT, media_json TEXT)"))
        c.execute(sa.text("INSERT INTO chat_messages VALUES (1, 'pollo/pollo30v1', NULL)"))
        assert mod.rewrite(c) == 1

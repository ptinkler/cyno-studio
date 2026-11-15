"""Fixtures and shared helpers for the chat-mode tests, loaded via.

`pytest_plugins`.

A fixture plugin rather than a cross-module import: pytest resolves fixtures by
name, so the test modules need no import of this file to use them (and no F401
or F811 to excuse one). The helpers below are imported normally, because they
are called rather than injected.
"""

import io
import json
import sys
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Required, TypedDict, cast

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from PIL import Image
from pydantic import TypeAdapter

import web.api as api_mod
from tests.stubs import stub
from web.chat import catalogue as chat_catalogue
from web.chat import generation as chat_generation
from web.chat import polling as chat_polling
from web.core.metadata import MetadataDB
from web.jsonutil import body_of
from web.types import ChatChunk, JsonValue

SETTINGS = {"text_model": "t/model", "image_model": "i/model", "video_model": "v/model"}


class ConversationOut(TypedDict, total=False):
    """A conversation as the API returns it (the keys the tests read)."""

    id: Required[str]
    title: str
    text_model: str | None
    image_model: str | None
    video_model: str | None
    space_id: int | None
    import_source: str | None
    character_ids: list[int]
    instruction_ids: list[int]
    paused_instructions: dict[str, list[int]]
    settings_json: str | None
    updated_at: str


def png_bytes(size: tuple[int, int] = (8, 8), color: str = "red") -> bytes:
    """A tiny PNG of one colour."""
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def text_chunks(*parts: str, cost: float = 0.001) -> Iterator[ChatChunk]:
    """A streamed text reply made of ``parts``."""
    for p in parts:
        yield {"choices": [{"delta": {"content": p}}]}
    yield {"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {"cost": cost}}


def tool_chunks(
    name: str, args: Mapping[str, JsonValue], call_id: str = "call_1", text: str = ""
) -> Iterator[ChatChunk]:
    """A streamed reply that calls the tool ``name`` with ``args`` (split across two chunks)."""
    raw = json.dumps(args)
    if text:
        yield {"choices": [{"delta": {"content": text}}]}
    yield {
        "choices": [
            {"delta": {"tool_calls": [{"index": 0, "id": call_id, "function": {"name": name, "arguments": raw[:5]}}]}}
        ]
    }
    yield {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": raw[5:]}}]}}]}
    yield {"choices": [{"delta": {}, "finish_reason": "tool_calls"}], "usage": {"cost": 0.003}}


_EVENT = TypeAdapter(dict[str, JsonValue])


def sse_events(resp: Response) -> list[dict[str, JsonValue]]:
    """The JSON events of a server-sent-events response."""
    return [_EVENT.validate_json(line[6:]) for line in resp.text.splitlines() if line.startswith("data: ")]


@pytest.fixture
def db(tmp_path: Path) -> MetadataDB:
    """A metadata database in the test's temporary directory."""
    return MetadataDB(db_path=tmp_path / "data" / "metadata.db")


@pytest.fixture
def chat(monkeypatch: pytest.MonkeyPatch, db: MetadataDB, provider_keys: dict[str, str | None]) -> None:
    """Point every chat module at the test database and stub out the network-bound helpers."""
    # Patch get_db wherever it was imported (chat is a package now: routes,
    # helpers and catalogue each resolve their own get_db).
    for name, mod in list(sys.modules.items()):
        if name.startswith("web.") and getattr(mod, "get_db", None) is not None:
            monkeypatch.setattr(mod, "get_db", lambda: db)
    provider_keys["openrouter"] = "sk-test"
    provider_keys["venice"] = None  # tests never reach the real Venice
    monkeypatch.setattr(chat_polling, "VIDEO_POLL_INTERVAL", 0)
    monkeypatch.setattr(chat_polling, "start_video_poller", stub(lambda: None))
    monkeypatch.setattr(chat_generation, "generate_title", stub(lambda: (None, 0.0)))  # tests opt in
    chat_catalogue.clear_models()


@pytest.fixture
def client(chat: None) -> TestClient:
    """A test client for the app."""
    return TestClient(api_mod.app, raise_server_exceptions=False)


@pytest.fixture
def conv(client: TestClient) -> ConversationOut:
    """A new, empty conversation."""
    return cast("ConversationOut", body_of(client.post("/api/chat/conversations", json={})))

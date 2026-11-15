"""Tests for web.chat — OpenRouter chat mode. OpenRouter is always mocked."""

import base64
import importlib.util
import io
import json
import socket
import threading
import time
import time as _t
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import ClassVar, Protocol, Self, cast

import httpx
import pytest
import requests
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from fastapi import HTTPException
from fastapi.testclient import TestClient
from PIL import Image

import web.characters as characters_mod
import web.chat as chat_pkg
import web.core.config as config
import web.media as media_mod
import web.providers.pollo_engine as registry
from tests import jsonpath as jp
from tests.chat_fixtures import SETTINGS, ConversationOut, png_bytes, sse_events, text_chunks, tool_chunks
from tests.errors import InsufficientCreditsError, SeedOverloadedError, UpstreamTimeoutError, server_disconnected
from tests.jsonpath import dig, integer, must, number, obj, rows, seq, text
from tests.stubs import stub
from web import request_log
from web.chat import catalogue
from web.chat import catalogue as chat_catalogue
from web.chat import constants as chat_constants
from web.chat import generation as chat_generation
from web.chat import helpers as chat_helpers
from web.chat import polling as chat_polling
from web.chat import tools as chat_tools
from web.core.get_task import TaskResult
from web.core.metadata import ChatMessage, MetadataDB, reset_tenant, set_tenant
from web.jsonutil import as_object
from web.providers import openrouter, pollo_estimate
from web.providers import pollo as pollo_provider
from web.providers.pollo_engine._shared import Payload
from web.providers.pollo_engine.registry import ModelSpec, PolloGenerator
from web.types import Catalogue, ChatChunk, JsonValue, ModelEntry, VideoJob

pytest_plugins = ["tests.chat_fixtures"]

# Fixtures (db, chat, client, conv) come from this plugin; pytest injects them
# by name, so they are not imported here.

ROOT_DIR = Path(__file__).parent.parent.resolve()


@dataclass
class StreamCall:
    """One call made to the faked ``openrouter.stream_chat``."""

    model: str
    messages: list[dict[str, JsonValue]]
    tools: list[dict[str, JsonValue]] | None


class FakeStream:
    """Stands in for ``openrouter.stream_chat``: serves the queued replies in turn and records each call."""

    def __init__(self, *replies: Iterable[ChatChunk]) -> None:
        """Queue the replies, one per call."""
        self._replies = iter(replies)
        self.calls: list[StreamCall] = []

    def __call__(
        self,
        model: str,
        messages: list[dict[str, JsonValue]],
        tools: list[dict[str, JsonValue]] | None = None,
        session_id: str | None = None,
        **_kw: object,
    ) -> Iterator[ChatChunk]:
        """Record the call and hand back the next reply."""
        self.calls.append(StreamCall(model, messages, tools))
        return iter(next(self._replies))


@dataclass
class ImageCall:
    """One call made to the faked ``openrouter.generate_image``."""

    model: str
    prompt: str
    aspect_ratio: str | None
    resolution: str | None
    input_images: list[str] | None


class FakeImages:
    """Stands in for ``openrouter.generate_image``: records each request and returns ``count`` PNGs."""

    def __init__(self, count: int = 1, cost: float | None = 0.04) -> None:
        """Set how many pictures each call returns and what they cost."""
        self.count = count
        self.cost = cost
        self.calls: list[ImageCall] = []

    def __call__(
        self,
        model: str,
        prompt: str,
        aspect_ratio: str | None = None,
        resolution: str | None = None,
        input_images: list[str] | None = None,
        session_id: str | None = None,
    ) -> tuple[list[tuple[bytes, str]], float | None]:
        """Record the request and return the pictures."""
        self.calls.append(ImageCall(model, prompt, aspect_ratio, resolution, input_images))
        return [(png_bytes(), "image/png")] * self.count, self.cost


class FakeVideoSubmit:
    """Stands in for ``openrouter.submit_video``: remembers the first frame it was given."""

    def __init__(self, job_id: str) -> None:
        """Set the id of the job every submission returns."""
        self.job_id = job_id
        self.first_frame: str | None = None

    def __call__(
        self,
        model: str,
        prompt: str,
        duration: int | None = None,
        aspect_ratio: str | None = None,
        resolution: str | None = None,
        first_frame: str | None = None,
        generate_audio: bool | None = None,
        session_id: str | None = None,
    ) -> VideoJob:
        """Record the first frame and return the job."""
        self.first_frame = first_frame
        return {"id": self.job_id}


def loads_object(raw: str) -> dict[str, JsonValue]:
    """Decode a JSON object from text (the arguments or result a tool call carries)."""
    return as_object(cast("object", json.loads(raw)))


class NopeError(openrouter.OpenRouterError):
    """An OpenRouter failure (HTTP 500) with the message ``nope``."""

    def __init__(self) -> None:
        """Build the fixed message."""
        super().__init__("nope", 500)


class PollerStarts:
    """Stands in for ``chat_polling.start_video_poller``: records the jobs it was asked to follow."""

    def __init__(self) -> None:
        """Start with no jobs."""
        self.jobs: list[tuple[str, int, str, str]] = []

    def __call__(self, conv_id: str, message_id: int, media_id: str, job_id: str) -> None:
        """Record the job."""
        self.jobs.append((conv_id, message_id, media_id, job_id))


class TestModelCatalogue:
    """The /models catalogue lists each provider independently — no provider.

    gates the endpoint, so media models show with only a Pollo key.
    """

    def test_media_models_load_without_a_chat_provider(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch, provider_keys: dict[str, str | None]
    ) -> None:
        # Only Pollo configured — no OpenRouter/Venice text provider.
        """Test that media models load without a chat provider."""
        provider_keys["openrouter"] = None
        provider_keys["venice"] = None
        provider_keys["pollo"] = "pollo-test"

        catalogue.clear_models()

        def fake_list(kind: str, refresh: bool = False) -> list[ModelEntry]:
            return [{"id": "pollo/seedream", "name": "Seedream"}] if kind == "image" else []

        monkeypatch.setattr(pollo_provider, "list_models", fake_list)

        r = client.get("/api/chat/models")
        assert r.status_code == 200
        assert jp.obj(r, "errors") == {}
        assert jp.seq(r, "text") == []  # no chat provider, but the endpoint still serves
        assert [m["id"] for m in jp.rows(r, "image")] == ["pollo/seedream"]


class TestConversations:
    """Tests for conversations."""

    def test_crud(self, client: TestClient) -> None:
        """Test that crud."""
        c = client.post("/api/chat/conversations", json={"text_model": "a/b"})
        cid = jp.text(c, "id")
        assert jp.text(c, "title") == "New chat"
        assert jp.text(c, "text_model") == "a/b"
        assert [x["id"] for x in jp.rows(client.get("/api/chat/conversations"), "conversations")] == [cid]
        r = client.patch(f"/api/chat/conversations/{cid}", json={"title": "  Renamed "})
        assert jp.text(r, "title") == "Renamed"
        assert client.delete(f"/api/chat/conversations/{cid}").status_code == 200
        assert client.get(f"/api/chat/conversations/{cid}").status_code == 404

    def test_kind_persists_through_create_patch_list_and_fetch(self, client: TestClient) -> None:
        # Create as a gallery thread → kind sticks on create, list and fetch.
        """Test that kind persists through create patch list and fetch."""
        g = client.post("/api/chat/conversations", json={"kind": "gallery"})
        gid = jp.text(g, "id")
        assert jp.text(g, "kind") == "gallery"
        # GET returns a { conversation, messages } envelope — kind is on the conversation.
        assert jp.text(client.get(f"/api/chat/conversations/{gid}"), "conversation", "kind") == "gallery"
        listing = jp.rows(client.get("/api/chat/conversations"), "conversations")
        listed = {jp.text(c, "id"): jp.text(c, "kind") for c in listing}
        assert listed[gid] == "gallery"
        # The "Opens on Chat/Gallery" toggle (PATCH kind) persists too.
        assert jp.text(client.patch(f"/api/chat/conversations/{gid}", json={"kind": "chat"}), "kind") == "chat"
        assert jp.text(client.get(f"/api/chat/conversations/{gid}"), "conversation", "kind") == "chat"
        # An unknown kind falls back to "chat" rather than being stored raw.
        c = client.post("/api/chat/conversations", json={"kind": "bogus"})
        assert jp.text(c, "kind") == "chat"

    def test_gallery_lane_stays_beside_the_chat_branch(self, client: TestClient, db: MetadataDB) -> None:
        """Test that gallery lane stays beside the chat branch."""
        cid = jp.text(client.post("/api/chat/conversations", json={}), "id")
        u = db.add_chat_message(cid, "user", "story")
        g = db.add_chat_message(cid, "user", "a cat", lane="gallery")
        ga = db.add_chat_message(cid, "assistant", parent_id=g.id, lane="gallery")
        nxt = db.add_chat_message(cid, "user", "go on")
        # The gallery exchange neither moves the chat's leaf nor becomes its parent
        assert nxt.parent_id == u.id
        assert g.parent_id is None
        assert ga.parent_id == g.id
        assert db.get_chat_leaf_id(cid) == nxt.id
        out = jp.rows(client.get(f"/api/chat/conversations/{cid}"), "messages")
        chat = [m["id"] for m in out if not m["lane"]]
        assert chat == [u.id, nxt.id]
        assert {jp.integer(m, "id") for m in out if m["lane"]} == {g.id, ga.id}
        # No version arrows from sharing "no parent" with the chat's first turn
        assert next(m for m in out if m["id"] == u.id)["siblings"] == [u.id]
        # Deleting the gallery exchange leaves the chat alone
        after = jp.rows(client.delete(f"/api/chat/messages/{g.id}"), "messages")
        assert [m["id"] for m in after] == [u.id, nxt.id]

    def test_conversation_thumbs_returns_newest_image(self, client: TestClient, db: MetadataDB) -> None:
        """Test that conversation thumbs returns newest image."""
        cid = jp.text(client.post("/api/chat/conversations", json={}), "id")

        def img(mid: str, f: str) -> list[dict[str, JsonValue]]:
            return [{"id": mid, "kind": "image", "status": "done", "file": f}]

        db.add_chat_message(cid, "assistant", media=img("m1", "old.png"))
        db.add_chat_message(cid, "assistant", media=img("m2", "new.png"))
        # Newest image wins; the route isn't shadowed by /conversations/{id}; unknown ids are absent.
        r = client.get(f"/api/chat/conversations/thumbs?ids={cid},nope")
        assert jp.decode(r) == {"thumbs": {cid: "new.png"}}

    def test_status_reports_key(self, client: TestClient, provider_keys: dict[str, str | None]) -> None:
        """Test that status reports key."""
        assert jp.decode(client.get("/api/chat/status")) == {"configured": True, "openrouter": True, "venice": False}
        provider_keys["openrouter"] = None
        assert jp.flag(client.get("/api/chat/status"), "configured") is False
        provider_keys["venice"] = "v-test"  # Venice alone can run the chat
        assert jp.decode(client.get("/api/chat/status")) == {"configured": True, "openrouter": False, "venice": True}

    def test_openrouter_balance(self, client: TestClient, chat: None, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that openrouter balance."""

        def fake_get(path: str, params: dict[str, str] | None = None) -> dict[str, JsonValue]:
            if path != "/credits":
                pytest.fail(path)
            return {"data": {"total_credits": 60, "total_usage": 52.78926312}}

        monkeypatch.setattr(openrouter, "_get", fake_get)
        assert jp.decode(client.get("/api/chat/credits")) == {
            "total_credits": 60.0,
            "total_usage": 52.78926312,
            "remaining": 7.2107,
        }

    def test_openrouter_balance_error_is_502(
        self, client: TestClient, chat: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that openrouter balance error is 502."""

        def boom(path: str, params: dict[str, str] | None = None) -> None:
            raise NopeError

        monkeypatch.setattr(openrouter, "_get", boom)
        assert client.get("/api/chat/credits").status_code == 502

    def test_send_without_key_is_503(
        self, client: TestClient, conv: ConversationOut, provider_keys: dict[str, str | None]
    ) -> None:
        """Test that send without key is 503."""
        provider_keys["openrouter"] = None
        r = client.post(f"/api/chat/conversations/{conv['id']}/messages", json={"content": "hi", **SETTINGS})
        assert r.status_code == 503


class TestMedia:
    """Tests for media."""

    def test_upload_and_serve(self, client: TestClient, conv: ConversationOut) -> None:
        """Test that upload and serve."""
        r = client.post(
            f"/api/chat/conversations/{conv['id']}/attachments", files={"file": ("a.png", png_bytes(), "image/png")}
        )
        name = jp.text(r, "file")
        assert name.startswith("up_")
        assert name.endswith(".png")
        assert client.get(f"/api/chat/media/{conv['id']}/{name}").content == png_bytes()

    def test_rejects_non_image(self, client: TestClient, conv: ConversationOut) -> None:
        """Test that rejects non image."""
        r = client.post(
            f"/api/chat/conversations/{conv['id']}/attachments", files={"file": ("a.png", b"not an image", "image/png")}
        )
        assert r.status_code == 400

    @pytest.mark.parametrize(("conv_id", "name"), [("abc", "../x.png"), ("..", "metadata.db"), ("abc", ".hidden")])
    def test_path_traversal_blocked(self, chat: None, conv_id: str, name: str) -> None:
        """Test that path traversal blocked."""
        with pytest.raises(HTTPException) as e:
            chat_pkg.routes.api_chat_media(conv_id, name)
        assert e.value.status_code == 400

    def test_an_image_already_in_the_chat_can_be_attached(
        self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Attaching by name: "make a video from this image" uses it as the first frame."""
        (chat_pkg.conversation_dir(conv["id"]) / "img_old.png").write_bytes(png_bytes())
        submit = FakeVideoSubmit("vid-1")
        monkeypatch.setattr(openrouter, "submit_video", submit)
        sse_events(
            client.post(
                f"/api/chat/conversations/{conv['id']}/messages",
                json={"content": "slow zoom", "attachments": ["img_old.png"], "mode": "video", **SETTINGS},
            )
        )
        assert jp.must(submit.first_frame).startswith("data:image/")

    def test_unknown_attachment_rejected(self, client: TestClient, conv: ConversationOut) -> None:
        """Test that unknown attachment rejected."""
        r = client.post(
            f"/api/chat/conversations/{conv['id']}/messages",
            json={"content": "x", "attachments": ["nope.png"], **SETTINGS},
        )
        assert r.status_code == 400


class TestTurns:
    """Tests for turns."""

    def test_text_mode_streams_and_persists(
        self, client: TestClient, conv: ConversationOut, chat: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that text mode streams and persists."""
        stream = FakeStream(text_chunks("Hel", "lo!"))
        monkeypatch.setattr(openrouter, "stream_chat", stream)

        r = client.post(
            f"/api/chat/conversations/{conv['id']}/messages", json={"content": "Say hello", "mode": "text", **SETTINGS}
        )
        ev = sse_events(r)
        assert ev[0]["type"] == "start"
        assert jp.text(ev[0], "user_message", "content") == "Say hello"
        assert "".join(jp.text(e, "text") for e in ev if e["type"] == "delta") == "Hello!"
        assert {"type": "title", "title": "Say hello"} in ev
        done = ev[-1]
        assert jp.text(done, "message", "content") == "Hello!"
        assert jp.text(done, "message", "status") == "done"
        assert jp.number(done, "message", "cost") == 0.001
        seen = stream.calls[0]
        assert seen.tools is None
        assert seen.messages[0]["role"] == "system"
        assert seen.messages[-1] == {"role": "user", "content": [{"type": "text", "text": "Say hello"}]}
        # model picks are remembered on the conversation
        assert jp.text(client.get(f"/api/chat/conversations/{conv['id']}"), "conversation", "text_model") == "t/model"

    def test_text_plus_image_is_one_llm_call(
        self, client: TestClient, conv: ConversationOut, chat: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that text plus image is one llm call."""
        stream = FakeStream(
            tool_chunks("generate_image", {"prompt": "a cat", "aspect_ratio": "16:9"}, text="Once upon a time, a cat.")
        )
        monkeypatch.setattr(openrouter, "stream_chat", stream)
        images = FakeImages()
        monkeypatch.setattr(openrouter, "generate_image", images)

        ev = sse_events(
            client.post(
                f"/api/chat/conversations/{conv['id']}/messages",
                json={"content": "a story about a cat, with a picture", "mode": "auto", **SETTINGS},
            )
        )
        assert [jp.text(t, "function", "name") for t in jp.rows(jp.must(stream.calls[0].tools))] == [
            "generate_image",
            "create_character",
            "generate_video",
            "create_instruction",
        ]
        assert len(stream.calls) == 1  # reply written + image made → complete
        assert images.calls[0].model == "i/model"
        assert images.calls[0].prompt == "a cat"
        # The ratio is the composer's, not the model's: on "auto" with an image
        # model that has no auto value, nothing is sent (its natural shape)
        assert images.calls[0].aspect_ratio is None
        media_events = [jp.obj(e, "item") for e in ev if e["type"] == "media"]
        assert [m["status"] for m in media_events] == ["pending", "done"]
        done = ev[-1]
        assert jp.text(done, "message", "content") == "Once upon a time, a cat."
        assert jp.text(done, "message", "media", 0, "file").startswith("img_")
        assert jp.number(done, "message", "cost") == pytest.approx(0.043)  # LLM round + image
        path = chat_helpers.chat_root() / conv["id"] / jp.text(done, "message", "media", 0, "file")
        assert path.read_bytes() == png_bytes()

    def test_image_models_own_auto_beats_the_chat_models_ratio_pick(
        self, client: TestClient, conv: ConversationOut, chat: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # With the composer ratio left unset and the image model offering its
        # own "auto", that wins over whatever ratio the chat model guessed.
        """Test that image models own auto beats the chat models ratio pick."""
        chat_catalogue.seed_models(
            {"text": [], "video": [], "image": [{"id": "i/model", "aspect_ratios": ["auto", "16:9", "1:1"]}]},
        )
        rounds = iter([tool_chunks("generate_image", {"prompt": "a cat", "aspect_ratio": "16:9"}, text="A cat.")])
        monkeypatch.setattr(openrouter, "stream_chat", stub(lambda: next(rounds)))
        images = FakeImages()
        monkeypatch.setattr(openrouter, "generate_image", images)
        sse_events(
            client.post(
                f"/api/chat/conversations/{conv['id']}/messages",
                json={"content": "draw a cat", "mode": "auto", **SETTINGS},
            )
        )
        assert images.calls[0].aspect_ratio == "auto"  # the image model's auto, not the chat model's 16:9

    def test_model_can_create_and_attach_an_instruction(
        self, client: TestClient, conv: ConversationOut, chat: None, monkeypatch: pytest.MonkeyPatch, db: MetadataDB
    ) -> None:
        """Test that model can create and attach an instruction."""
        rounds = iter(
            [
                tool_chunks(
                    "create_instruction",
                    {"name": "Pirate", "content": "You are a pirate. Always talk like one."},
                    text="Aye, saving that.",
                ),
                text_chunks("Arr, done!"),
            ]
        )
        monkeypatch.setattr(openrouter, "stream_chat", stub(lambda: next(rounds)))

        ev = sse_events(
            client.post(
                f"/api/chat/conversations/{conv['id']}/messages",
                json={"content": "always talk like a pirate from now on", "mode": "auto", **SETTINGS},
            )
        )

        saved = db.list_instructions()
        assert [i.name for i in saved] == ["Pirate"]
        assert saved[0].content == "You are a pirate. Always talk like one."
        # Attached to the chat, and the UI was told so the sidebar updates live
        assert jp.must(db.get_conversation(conv["id"])).instruction_ids == [saved[0].id]
        attach = next(e for e in ev if e["type"] == "instructions")
        assert attach["instruction_ids"] == [saved[0].id]
        assert jp.text(attach, "instruction", "name") == "Pirate"
        # The model still wrote its reply after saving
        assert jp.text(ev[-1], "message", "content") == "Aye, saving that.\n\nArr, done!"

    def test_create_instruction_rejects_a_name_already_in_this_chat(
        self, client: TestClient, conv: ConversationOut, chat: None, monkeypatch: pytest.MonkeyPatch, db: MetadataDB
    ) -> None:
        """A name already applied to this chat is refused; elsewhere in the library it's fine."""
        existing = db.save_instruction(name="Pirate", content="existing")
        db.update_conversation(conv["id"], instruction_ids=[existing.id])
        stream = FakeStream(
            tool_chunks("create_instruction", {"name": "pirate", "content": "You are a pirate."}),
            text_chunks("I couldn't save that."),
        )
        monkeypatch.setattr(openrouter, "stream_chat", stream)

        client.post(
            f"/api/chat/conversations/{conv['id']}/messages",
            json={"content": "save a pirate instruction", "mode": "auto", **SETTINGS},
        )

        # Only the original instruction exists; the model got an error result back
        assert len(db.list_instructions()) == 1
        result = loads_object(jp.text(stream.calls[1].messages[-1], "content"))
        assert not result["ok"]
        assert "already has an instruction" in jp.text(result, "error")

    def test_create_instruction_reuses_a_library_name(
        self, client: TestClient, conv: ConversationOut, chat: None, monkeypatch: pytest.MonkeyPatch, db: MetadataDB
    ) -> None:
        """A library instruction not on this chat doesn't block the name."""
        db.save_instruction(name="Pirate", content="existing")
        rounds = iter([tool_chunks("create_instruction", {"name": "Pirate", "content": "Arr."}), text_chunks("ok")])
        monkeypatch.setattr(openrouter, "stream_chat", stub(lambda: next(rounds)))
        client.post(f"/api/chat/conversations/{conv['id']}/messages", json={"content": "x", "mode": "auto", **SETTINGS})
        assert [i.name for i in db.list_instructions()] == ["Pirate", "Pirate"]

    def test_failed_tool_gets_follow_up_round(
        self, client: TestClient, conv: ConversationOut, chat: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that failed tool gets follow up round."""
        stream = FakeStream(
            tool_chunks("generate_image", {"prompt": "a cat"}, text="Drawing it."),
            text_chunks("Sorry, the image model is down."),
        )
        monkeypatch.setattr(openrouter, "stream_chat", stream)

        def boom(*a: object, **k: object) -> None:
            raise SeedOverloadedError

        monkeypatch.setattr(openrouter, "generate_image", boom)

        ev = sse_events(
            client.post(f"/api/chat/conversations/{conv['id']}/messages", json={"content": "draw a cat", **SETTINGS})
        )
        assert len(stream.calls) == 2
        tool_result = stream.calls[1].messages[-1]
        assert tool_result["role"] == "tool"
        assert not jp.flag(loads_object(jp.text(tool_result, "content")), "ok")
        done = jp.obj(ev[-1], "message")
        assert done["status"] == "done"
        assert done["content"] == "Drawing it.\n\nSorry, the image model is down."
        assert jp.text(done, "media", 0, "status") == "error"

    def test_chained_image_then_video_in_one_response(
        self, client: TestClient, conv: ConversationOut, chat: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that chained image then video in one response."""
        args_img = json.dumps({"prompt": "a fox"})
        args_vid = json.dumps({"prompt": "the fox runs", "source_image": "latest"})
        chunks: list[ChatChunk] = [
            {"choices": [{"delta": {"content": "A fox, then it runs."}}]},
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {"index": 0, "id": "c1", "function": {"name": "generate_image", "arguments": args_img}},
                                {"index": 1, "id": "c2", "function": {"name": "generate_video", "arguments": args_vid}},
                            ]
                        }
                    }
                ]
            },
        ]
        stream = FakeStream(chunks, text_chunks("Done."))
        monkeypatch.setattr(openrouter, "stream_chat", stream)
        monkeypatch.setattr(openrouter, "generate_image", stub(lambda: ([(png_bytes(), "image/png")], None)))
        submit = FakeVideoSubmit("gen-vid-1")
        monkeypatch.setattr(openrouter, "submit_video", submit)
        ev = sse_events(
            client.post(
                f"/api/chat/conversations/{conv['id']}/messages",
                json={"content": "draw a fox and animate it", **SETTINGS},
            )
        )
        assert len(stream.calls) == 1
        assert jp.must(submit.first_frame).startswith("data:image/png;base64,")
        assert [m["kind"] for m in jp.rows(ev[-1], "message", "media")] == ["image", "video"]

    def test_source_latest_uses_previous_image(
        self, client: TestClient, conv: ConversationOut, chat: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that source latest uses previous image."""
        up = jp.text(
            client.post(
                f"/api/chat/conversations/{conv['id']}/attachments", files={"file": ("a.png", png_bytes(), "image/png")}
            ),
            "file",
        )
        rounds = iter(
            [
                tool_chunks("generate_image", {"prompt": "make it blue", "source_image": "latest"}),
                text_chunks("Done."),
            ]
        )
        monkeypatch.setattr(openrouter, "stream_chat", stub(lambda: next(rounds)))
        images = FakeImages(cost=None)
        monkeypatch.setattr(openrouter, "generate_image", images)
        sse_events(
            client.post(
                f"/api/chat/conversations/{conv['id']}/messages",
                json={"content": "make it blue", "attachments": [up], **SETTINGS},
            )
        )
        assert jp.must(images.calls[0].input_images)[0].startswith("data:image/png;base64,")

    def test_image_mode_skips_text_model(
        self, client: TestClient, conv: ConversationOut, chat: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that image mode skips text model."""
        monkeypatch.setattr(openrouter, "stream_chat", stub(lambda: pytest.fail("no LLM in image mode")))
        images = FakeImages(count=2, cost=0.02)
        monkeypatch.setattr(openrouter, "generate_image", images)
        ev = sse_events(
            client.post(
                f"/api/chat/conversations/{conv['id']}/messages",
                json={
                    "content": "a dog",
                    "mode": "image",
                    "image_options": {"aspect_ratio": "1:1", "resolution": "2K"},
                    **SETTINGS,
                },
            )
        )
        assert images.calls[0].prompt == "a dog"
        assert images.calls[0].aspect_ratio == "1:1"
        assert images.calls[0].resolution == "2K"
        assert len(jp.seq(ev[-1], "message", "media")) == 2
        assert jp.text(ev[-1], "message", "model") == "i/model"

    def test_video_mode_submits_and_polls(
        self, client: TestClient, conv: ConversationOut, chat: None, monkeypatch: pytest.MonkeyPatch, db: MetadataDB
    ) -> None:
        """Test that video mode submits and polls."""
        started = PollerStarts()
        monkeypatch.setattr(chat_polling, "start_video_poller", started)
        monkeypatch.setattr(openrouter, "submit_video", stub(lambda: {"id": "gen-vid-1", "status": "pending"}))
        chat_catalogue.seed_models(
            {
                "text": [],
                "image": [],
                "video": [{"id": "v/model", "durations": [5, 10], "aspect_ratios": ["16:9"], "resolutions": ["720p"]}],
            },
        )
        ev = sse_events(
            client.post(
                f"/api/chat/conversations/{conv['id']}/messages",
                json={
                    "content": "waves",
                    "mode": "video",
                    "video_options": {"duration": 7, "aspect_ratio": "1:1"},
                    **SETTINGS,
                },
            )
        )
        item = jp.obj(ev[-1], "message", "media", 0)
        assert item["status"] == "pending"
        assert item["job_id"] == "gen-vid-1"
        assert jp.integer(item, "params", "duration") == 5
        assert jp.dig(item, "params", "aspect_ratio") is None
        conv_id, msg_id, media_id, job_id = started.jobs[0]

        # Now run the poller for real against mocked status/download
        statuses = iter([{"status": "in_progress"}, {"status": "completed", "usage": {"cost": 0.5}}])
        monkeypatch.setattr(openrouter, "get_video", stub(lambda: next(statuses)))

        def fake_download(job: str, dest: Path, index: int = 0) -> None:
            dest.write_bytes(b"mp4")

        monkeypatch.setattr(openrouter, "download_video", fake_download)
        chat_polling.poll_video(conv_id, msg_id, media_id, job_id)
        msg = client.get(f"/api/chat/messages/{msg_id}")
        assert jp.text(msg, "media", 0, "status") == "done"
        assert jp.text(msg, "media", 0, "file").endswith(".mp4")
        assert jp.number(msg, "cost") == 0.5

    def test_video_failure_marks_item(
        self, chat: None, db: MetadataDB, conv: ConversationOut, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that video failure marks item."""
        msg = db.add_chat_message(conv["id"], "assistant", media=[{"id": "m1", "kind": "video", "status": "pending"}])
        monkeypatch.setattr(openrouter, "get_video", stub(lambda: {"status": "failed", "error": "nsfw"}))
        chat_polling.poll_video(conv["id"], msg.id, "m1", "gen-vid-x")
        assert jp.must(db.get_chat_message(msg.id)).media[0] == {
            "id": "m1",
            "kind": "video",
            "status": "error",
            "error": "nsfw",
            "moderated": True,
        }

    def test_openrouter_error_marks_message(
        self, client: TestClient, conv: ConversationOut, chat: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that openrouter error marks message."""

        def boom(*a: object, **k: object) -> None:
            raise InsufficientCreditsError

        monkeypatch.setattr(openrouter, "stream_chat", boom)
        ev = sse_events(
            client.post(f"/api/chat/conversations/{conv['id']}/messages", json={"content": "hi", **SETTINGS})
        )
        assert {"type": "error", "message": "Insufficient credits"} in ev
        assert jp.text(ev[-1], "message", "status") == "error"

    def test_tools_withheld_for_models_without_tool_support(
        self, client: TestClient, conv: ConversationOut, chat: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that tools withheld for models without tool support."""
        chat_catalogue.seed_models(
            {
                "image": [],
                "video": [],
                "text": [{"id": "t/model", "supports_tools": False, "input_modalities": ["text"]}],
            },
        )
        stream = FakeStream(text_chunks("ok"))
        monkeypatch.setattr(openrouter, "stream_chat", stream)
        sse_events(
            client.post(
                f"/api/chat/conversations/{conv['id']}/messages", json={"content": "hi", "mode": "auto", **SETTINGS}
            )
        )
        assert stream.calls[0].tools is None

    def test_retry_replaces_assistant_message(
        self, client: TestClient, conv: ConversationOut, chat: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that retry replaces assistant message."""
        replies = iter([text_chunks("first"), text_chunks("second")])
        monkeypatch.setattr(openrouter, "stream_chat", stub(lambda: next(replies)))
        first = sse_events(
            client.post(f"/api/chat/conversations/{conv['id']}/messages", json={"content": "hi", **SETTINGS})
        )[-1]
        ev = sse_events(
            client.post(
                f"/api/chat/conversations/{conv['id']}/retry",
                json={"message_id": jp.integer(first, "message", "id"), **SETTINGS},
            )
        )
        assert ev[0]["user_message"] is None
        msgs = jp.rows(client.get(f"/api/chat/conversations/{conv['id']}"), "messages")
        assert [(m["role"], m["content"]) for m in msgs] == [("user", "hi"), ("assistant", "second")]

    def test_retry_uses_the_selected_mode(
        self, client: TestClient, conv: ConversationOut, chat: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A reply sent in Chat mode, retried with Auto selected, reruns in Auto.

        (tools offered) and the prompt's mode tag follows it.
        """
        stream = FakeStream(text_chunks("ok"), text_chunks("ok"))
        monkeypatch.setattr(openrouter, "stream_chat", stream)
        first = sse_events(
            client.post(
                f"/api/chat/conversations/{conv['id']}/messages", json={"content": "hi", **SETTINGS, "mode": "text"}
            )
        )[-1]
        sse_events(
            client.post(
                f"/api/chat/conversations/{conv['id']}/retry",
                json={"message_id": jp.integer(first, "message", "id"), **SETTINGS, "mode": "auto"},
            )
        )
        assert [bool(call.tools) for call in stream.calls] == [False, True]
        msgs = jp.rows(client.get(f"/api/chat/conversations/{conv['id']}"), "messages")
        assert [(m["role"], m["mode"]) for m in msgs] == [("user", "auto"), ("assistant", "auto")]

    def test_history_records_past_media_as_tool_calls(
        self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that history records past media as tool calls."""
        db.add_chat_message(conv["id"], "user", "draw a fox")
        db.add_chat_message(
            conv["id"],
            "assistant",
            "Here!",
            media=[
                {
                    "id": "a",
                    "kind": "image",
                    "source": "generated",
                    "status": "done",
                    "file": "x.png",
                    "prompt": "a fox",
                    "params": {"aspect_ratio": "16:9"},
                },
                {
                    "id": "b",
                    "kind": "image",
                    "source": "generated",
                    "status": "error",
                    "error": "flagged",
                    "prompt": "another fox",
                },
            ],
        )
        stream = FakeStream(text_chunks("ok"))
        monkeypatch.setattr(openrouter, "stream_chat", stream)
        sse_events(client.post(f"/api/chat/conversations/{conv['id']}/messages", json={"content": "nice", **SETTINGS}))
        m = stream.calls[0].messages
        assert m[2] == {
            "role": "assistant",
            "content": "Here!",
            "tool_calls": [
                {
                    "id": "call_a",
                    "type": "function",
                    "function": {
                        "name": "generate_image",
                        "arguments": json.dumps({"prompt": "a fox", "aspect_ratio": "16:9"}),
                    },
                },
                {
                    "id": "call_b",
                    "type": "function",
                    "function": {"name": "generate_image", "arguments": json.dumps({"prompt": "another fox"})},
                },
            ],
        }
        assert m[3] == {
            "role": "tool",
            "tool_call_id": "call_a",
            "content": json.dumps({"ok": True, "result": chat_tools.IMAGE_TOOL_RESULT}),
        }
        assert m[4] == {
            "role": "tool",
            "tool_call_id": "call_b",
            "content": json.dumps({"ok": False, "error": "flagged"}),
        }
        assert m[5]["role"] == "user"
        assert not any("[generated image" in json.dumps(x) for x in m[1:])

    def test_history_uses_notes_when_no_tools_are_offered(
        self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that history uses notes when no tools are offered."""
        db.add_chat_message(conv["id"], "user", "draw a fox")
        db.add_chat_message(
            conv["id"],
            "assistant",
            "Here!",
            media=[
                {
                    "id": "a",
                    "kind": "image",
                    "source": "generated",
                    "status": "done",
                    "file": "x.png",
                    "prompt": "a fox",
                }
            ],
        )
        stream = FakeStream(text_chunks("ok"))
        monkeypatch.setattr(openrouter, "stream_chat", stream)
        sse_events(
            client.post(
                f"/api/chat/conversations/{conv['id']}/messages", json={"content": "nice", "mode": "text", **SETTINGS}
            )
        )
        msgs = stream.calls[0].messages
        assert msgs[2] == {"role": "assistant", "content": "Here!\n\n[generated image: a fox]"}
        assert not any("tool_calls" in x for x in msgs)


class TestStartupResume:
    """Tests for startup resume."""

    def test_resumes_pending_videos_and_fails_orphans(
        self, chat: None, db: MetadataDB, conv: ConversationOut, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that resumes pending videos and fails orphans."""
        started = PollerStarts()
        monkeypatch.setattr(chat_polling, "start_video_poller", started)
        m1 = db.add_chat_message(
            conv["id"],
            "assistant",
            media=[
                {"id": "v", "kind": "video", "status": "pending", "job_id": "gen-vid-9"},
                {"id": "i", "kind": "image", "status": "pending"},
            ],
        )
        m2 = db.add_chat_message(conv["id"], "assistant", status="streaming")
        chat_pkg.startup_resume_chat()
        assert started.jobs == [(conv["id"], m1.id, "v", "gen-vid-9")]
        assert jp.must(db.get_chat_message(m1.id)).media[1]["status"] == "error"
        assert jp.must(db.get_chat_message(m2.id)).status == "error"


class _GalleryBackfill(Protocol):
    """The part of the 0024 migration module that the test calls."""

    def backfill(self, conn: sa.Connection) -> int:
        """Backfill pure-gallery conversations and return the converted count."""
        raise NotImplementedError


@pytest.mark.no_tenant
def test_gallery_lane_backfill_converts_only_pure_gallery_threads() -> None:
    """Test that gallery lane backfill converts only pure gallery threads."""
    spec = jp.must(importlib.util.spec_from_file_location("m0024", "alembic/versions/0024_backfill_gallery_lane.py"))
    module = importlib.util.module_from_spec(spec)
    jp.must(spec.loader).exec_module(module)
    mod = cast("_GalleryBackfill", module)
    eng = sa.create_engine("sqlite://")
    with eng.begin() as c:
        c.execute(sa.text("CREATE TABLE chat_conversations (id TEXT, kind TEXT, current_leaf_id INTEGER)"))
        c.execute(
            sa.text(
                "CREATE TABLE chat_messages (id INTEGER PRIMARY KEY, conversation_id TEXT, parent_id INTEGER,"
                " role TEXT, mode TEXT, lane TEXT)"
            )
        )
        c.execute(sa.text("INSERT INTO chat_conversations VALUES ('g','gallery',4),('m','gallery',7),('c','chat',9)"))
        rows = [
            (1, "g", None, "user", "image"), (2, "g", 1, "assistant", "image"),
            (3, "g", 2, "user", "image"), (4, "g", 3, "assistant", "image"),
            (5, "m", None, "user", "image"), (6, "m", 5, "assistant", "image"), (7, "m", 6, "user", "text"),
            (8, "c", None, "user", "image"), (9, "c", 8, "assistant", "image"),
        ]  # fmt: skip
        for r in rows:
            c.execute(
                sa.text("INSERT INTO chat_messages VALUES (:i,:c,:p,:r,:m,NULL)"), dict(zip("icprm", r, strict=True))
            )
        assert mod.backfill(c) == 1
        lanes = dict(
            cast(
                "list[tuple[str, str | None]]",
                c.execute(sa.text("SELECT conversation_id, MAX(lane) FROM chat_messages GROUP BY 1")).all(),
            )
        )
        assert lanes == {"g": "gallery", "m": None, "c": None}
        assert c.execute(sa.text("SELECT parent_id FROM chat_messages WHERE id = 3")).scalar() is None
        assert c.execute(sa.text("SELECT parent_id FROM chat_messages WHERE id = 4")).scalar() == 3
        assert c.execute(sa.text("SELECT current_leaf_id FROM chat_conversations WHERE id='g'")).scalar() is None


def test_alembic_migration_creates_chat_tables(tmp_path: Path) -> None:
    """0003 adds the chat tables to a pre-chat DB, and is a no-op when.

    create_all() already made them (the app creates tables on startup).
    """

    def cfg_for(path: Path) -> Config:
        cfg = Config(str(ROOT_DIR / "alembic.ini"))
        cfg.set_main_option("script_location", str(ROOT_DIR / "alembic"))
        cfg.set_main_option("sqlalchemy.url", f"sqlite:///{path}")
        return cfg

    # Pre-chat DB: full schema minus the chat tables, stamped at 0002
    old = tmp_path / "old.db"
    MetadataDB(db_path=old).engine.dispose()
    eng = sa.create_engine(f"sqlite:///{old}")
    with eng.begin() as c:
        c.execute(sa.text("DROP TABLE chat_library_items"))
        c.execute(sa.text("DROP TABLE chat_messages"))
        c.execute(sa.text("DROP TABLE chat_conversations"))
    command.stamp(cfg_for(old), "0002")
    command.upgrade(cfg_for(old), "head")
    assert {"chat_conversations", "chat_messages", "chat_library_items"} <= set(sa.inspect(eng).get_table_names())

    # DB where create_all already made them
    fresh = tmp_path / "fresh.db"
    MetadataDB(db_path=fresh).engine.dispose()
    command.stamp(cfg_for(fresh), "0002")
    command.upgrade(cfg_for(fresh), "head")


class TestOpenRouterErrors:
    """Tests for open router errors."""

    def _resp(self, status: int, body: dict[str, JsonValue]) -> httpx.Response:
        return httpx.Response(status, json=body)

    def test_names_upstream_provider(self) -> None:
        """Test that names upstream provider."""
        body: dict[str, JsonValue] = {
            "error": {
                "code": 400,
                "message": "API key not valid. Please pass a valid API key.",
                "metadata": {"provider_name": "Google AI Studio"},
            }
        }
        with pytest.raises(openrouter.OpenRouterError) as e:
            openrouter.raise_for_response(self._resp(400, body))
        assert str(e.value) == "[Google AI Studio] API key not valid. Please pass a valid API key."
        assert e.value.status == 400

    def test_appends_raw_upstream_message(self) -> None:
        """Test that appends raw upstream message."""
        body: dict[str, JsonValue] = {
            "error": {
                "message": "Provider returned error",
                "metadata": {"provider_name": "Fal", "raw": "content policy"},
            }
        }
        with pytest.raises(openrouter.OpenRouterError) as e:
            openrouter.raise_for_response(self._resp(502, body))
        assert str(e.value) == "[Fal] Provider returned error: content policy"

    def test_non_json_body(self) -> None:
        """Test that non json body."""
        with pytest.raises(openrouter.OpenRouterError) as e:
            openrouter.raise_for_response(httpx.Response(503, text="upstream down"))
        assert str(e.value) == "upstream down"


class TestEditAndLibrary:
    """Tests for edit and library."""

    def _send(
        self, client: TestClient, conv: ConversationOut, content: str, **extra: JsonValue
    ) -> list[dict[str, JsonValue]]:
        return sse_events(
            client.post(
                f"/api/chat/conversations/{conv['id']}/messages", json={"content": content, **SETTINGS, **extra}
            )
        )

    def _messages(self, client: TestClient, conv: ConversationOut) -> list[dict[str, JsonValue]]:
        return jp.rows(client.get(f"/api/chat/conversations/{conv['id']}"), "messages")

    def _switch(self, client: TestClient, conv: ConversationOut, message_id: int) -> httpx.Response:
        """Document the  switch test helper."""
        return client.post(f"/api/chat/conversations/{conv['id']}/branch", json={"message_id": message_id})

    def test_edit_starts_a_branch_and_keeps_the_old_one(
        self, client: TestClient, conv: ConversationOut, chat: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that edit starts a branch and keeps the old one."""
        stream = FakeStream(text_chunks("one"), text_chunks("two"), text_chunks("edited reply"))
        monkeypatch.setattr(openrouter, "stream_chat", stream)
        first = jp.obj(self._send(client, conv, "first")[0], "user_message")
        self._send(client, conv, "second")

        ev = sse_events(
            client.post(
                f"/api/chat/conversations/{conv['id']}/edit",
                json={"message_id": first["id"], "content": "first, but better", **SETTINGS},
            )
        )
        edited = jp.obj(ev[0], "user_message")
        assert edited["id"] != first["id"]
        assert edited["content"] == "first, but better"
        assert edited["siblings"] == [first["id"], edited["id"]]
        assert [(m["role"], m["content"]) for m in self._messages(client, conv)] == [
            ("user", "first, but better"),
            ("assistant", "edited reply"),
        ]
        # the model only saw the edited prompt, not the other branch
        assert [m["role"] for m in stream.calls[-1].messages] == ["system", "user"]

        old = jp.rows(self._switch(client, conv, jp.integer(first, "id")), "messages")
        assert [m["content"] for m in old] == ["first", "one", "second", "two"]
        assert old[0]["siblings"] == [first["id"], edited["id"]]
        assert [m["content"] for m in self._messages(client, conv)] == ["first", "one", "second", "two"]

    def test_messages_remember_their_mode(
        self, client: TestClient, conv: ConversationOut, chat: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The UI reruns an edit/retry in the message's own mode, so it must be recorded."""
        monkeypatch.setattr(openrouter, "generate_image", stub(lambda: ([(png_bytes(), "image/png")], None)))
        ev = self._send(client, conv, "a dog", mode="image")
        assert jp.dig(ev[0], "user_message", "mode") == "image"
        assert jp.dig(ev[-1], "message", "mode") == "image"
        edited = sse_events(
            client.post(
                f"/api/chat/conversations/{conv['id']}/edit",
                json={
                    "message_id": jp.integer(ev[0], "user_message", "id"),
                    "content": "a puppy",
                    "mode": "image",
                    **SETTINGS,
                },
            )
        )
        assert jp.dig(edited[0], "user_message", "mode") == "image"
        assert [m["mode"] for m in self._messages(client, conv)] == ["image", "image"]

    def test_switching_goes_to_the_newest_end_of_a_branch(
        self, client: TestClient, conv: ConversationOut, chat: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that switching goes to the newest end of a branch."""
        stream = FakeStream(text_chunks("a1"), text_chunks("a2"), text_chunks("b1"), text_chunks("a3"))
        monkeypatch.setattr(openrouter, "stream_chat", stream)
        first = jp.obj(self._send(client, conv, "q1")[0], "user_message")
        self._send(client, conv, "q2")
        sse_events(
            client.post(
                f"/api/chat/conversations/{conv['id']}/edit",
                json={"message_id": first["id"], "content": "other q1", **SETTINGS},
            )
        )
        self._switch(client, conv, jp.integer(first, "id"))
        # A new message continues the branch being shown
        self._send(client, conv, "q3")
        assert [m["content"] for m in self._messages(client, conv)] == ["q1", "a1", "q2", "a2", "q3", "a3"]
        sent = [
            jp.text(p, "text") for m in stream.calls[-1].messages if m["role"] == "user" for p in jp.seq(m, "content")
        ]
        assert sent == ["q1", "q2", "q3"]

    def test_switch_rejects_message_from_another_chat(
        self, client: TestClient, conv: ConversationOut, db: MetadataDB
    ) -> None:
        """Test that switch rejects message from another chat."""
        other = jp.text(client.post("/api/chat/conversations", json={}), "id")
        msg = db.add_chat_message(other, "user", "hi")
        assert self._switch(client, conv, msg.id).status_code == 400

    def test_switch_rejected_while_streaming(self, client: TestClient, conv: ConversationOut, db: MetadataDB) -> None:
        """Test that switch rejected while streaming."""
        user = db.add_chat_message(conv["id"], "user", "hi")
        db.add_chat_message(conv["id"], "assistant", status="streaming")
        assert self._switch(client, conv, user.id).status_code == 409

    def test_edit_keeps_attachments(
        self, client: TestClient, conv: ConversationOut, chat: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that edit keeps attachments."""
        monkeypatch.setattr(openrouter, "stream_chat", stub(lambda: text_chunks("ok")))
        up = jp.dig(
            client.post(
                f"/api/chat/conversations/{conv['id']}/attachments",
                files={"file": ("a.png", png_bytes(), "image/png")},
            ),
            "file",
        )
        first = jp.obj(self._send(client, conv, "what is this", attachments=[up])[0], "user_message")
        edited = sse_events(
            client.post(
                f"/api/chat/conversations/{conv['id']}/edit",
                json={"message_id": first["id"], "content": "describe it", **SETTINGS},
            )
        )[0]
        assert [i["file"] for i in jp.rows(edited, "user_message", "media")] == [up]

    def test_edit_keeps_generated_media_on_the_old_branch(
        self, client: TestClient, conv: ConversationOut, chat: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that edit keeps generated media on the old branch."""
        rounds = iter(
            [
                tool_chunks("generate_image", {"prompt": "a cat"}),
                text_chunks("Here."),
                text_chunks("No image this time."),
            ]
        )
        monkeypatch.setattr(openrouter, "stream_chat", stub(lambda: next(rounds)))
        monkeypatch.setattr(openrouter, "generate_image", stub(lambda: ([(png_bytes(), "image/png")], 0.04)))
        ev = self._send(client, conv, "draw a cat")
        user_id = jp.integer(ev[0], "user_message", "id")
        img = jp.obj(ev[-1], "message", "media", 0)

        sse_events(
            client.post(
                f"/api/chat/conversations/{conv['id']}/edit",
                json={"message_id": user_id, "content": "just say hi", **SETTINGS},
            )
        )
        assert all(not m["media"] for m in self._messages(client, conv))
        lib = jp.rows(client.get("/api/chat/library"), "items")
        assert [(i["id"], i["attached"]) for i in lib] == [(img["id"], True)]
        old = jp.rows(self._switch(client, conv, user_id), "messages")
        assert jp.dig(old[1], "media", 0, "id") == img["id"]

    def test_retry_adds_a_sibling_reply(
        self, client: TestClient, conv: ConversationOut, chat: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that retry adds a sibling reply."""
        monkeypatch.setattr(openrouter, "stream_chat", stub(lambda: pytest.fail("no LLM in image mode")))
        monkeypatch.setattr(openrouter, "generate_image", stub(lambda: ([(png_bytes(), "image/png")], None)))
        first = jp.obj(self._send(client, conv, "a dog", mode="image")[-1], "message")
        second = jp.obj(
            sse_events(
                client.post(
                    f"/api/chat/conversations/{conv['id']}/retry",
                    json={"message_id": first["id"], "mode": "image", **SETTINGS},
                )
            )[-1],
            "message",
        )
        assert second["siblings"] == [first["id"], second["id"]]
        lib = jp.rows(client.get("/api/chat/library"), "items")
        assert {(i["id"], i["attached"]) for i in lib} == {
            (jp.dig(first, "media", 0, "id"), True),
            (jp.dig(second, "media", 0, "id"), True),
        }
        shown = jp.rows(self._switch(client, conv, jp.integer(first, "id")), "messages")
        assert [m["id"] for m in shown][-1] == first["id"]

    def test_uploads_are_not_kept_in_library(
        self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that uploads are not kept in library."""
        monkeypatch.setattr(openrouter, "stream_chat", stub(lambda: text_chunks("ok")))
        up = jp.dig(
            client.post(
                f"/api/chat/conversations/{conv['id']}/attachments",
                files={"file": ("a.png", png_bytes(), "image/png")},
            ),
            "file",
        )
        first = jp.obj(self._send(client, conv, "hi")[0], "user_message")
        self._send(client, conv, "look", attachments=[up])
        sse_events(
            client.post(
                f"/api/chat/conversations/{conv['id']}/edit",
                json={"message_id": first["id"], "content": "hello", **SETTINGS},
            )
        )
        assert jp.seq(client.get("/api/chat/library"), "items") == []

    def test_edit_rejected_while_streaming(self, client: TestClient, conv: ConversationOut, db: MetadataDB) -> None:
        """Test that edit rejected while streaming."""
        user = db.add_chat_message(conv["id"], "user", "hi")
        db.add_chat_message(conv["id"], "assistant", status="streaming")
        r = client.post(
            f"/api/chat/conversations/{conv['id']}/edit", json={"message_id": user.id, "content": "x", **SETTINGS}
        )
        assert r.status_code == 409

    def test_edit_rejects_assistant_message(self, client: TestClient, conv: ConversationOut, db: MetadataDB) -> None:
        """Test that edit rejects assistant message."""
        a = db.add_chat_message(conv["id"], "assistant", "hi")
        r = client.post(
            f"/api/chat/conversations/{conv['id']}/edit", json={"message_id": a.id, "content": "x", **SETTINGS}
        )
        assert r.status_code == 400

    def test_pending_video_finishes_into_library(
        self, chat: None, db: MetadataDB, conv: ConversationOut, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that pending video finishes into library."""
        db.add_chat_message(conv["id"], "user", "waves")
        msg = db.add_chat_message(
            conv["id"],
            "assistant",
            media=[{"id": "v1", "kind": "video", "source": "generated", "status": "pending", "job_id": "gen-vid-1"}],
        )
        db.truncate_chat(conv["id"], after_id=msg.id - 1)
        assert db.get_chat_message(msg.id) is None
        monkeypatch.setattr(openrouter, "get_video", stub(lambda: {"status": "completed", "usage": {"cost": 0.3}}))

        def fake_download(_job_id: str, dest: Path, _index: int = 0) -> None:
            dest.write_bytes(b"mp4")

        monkeypatch.setattr(openrouter, "download_video", fake_download)
        chat_polling.poll_video(conv["id"], msg.id, "v1", "gen-vid-1")
        item = jp.must(db.get_chat_library_item("v1")).item
        assert item["status"] == "done"
        assert jp.text(item, "file").endswith(".mp4")
        assert item["cost"] == 0.3

    def test_startup_resumes_library_videos(
        self, chat: None, db: MetadataDB, conv: ConversationOut, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that startup resumes library videos."""
        started = PollerStarts()
        monkeypatch.setattr(chat_polling, "start_video_poller", started)
        msg = db.add_chat_message(
            conv["id"],
            "assistant",
            media=[{"id": "v2", "kind": "video", "source": "generated", "status": "pending", "job_id": "gen-vid-2"}],
        )
        db.truncate_chat(conv["id"], after_id=msg.id - 1)
        chat_pkg.startup_resume_chat()
        assert started.jobs == [(conv["id"], 0, "v2", "gen-vid-2")]

    def test_delete_library_item(self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB) -> None:
        """Test that delete library item."""
        f = chat_pkg.conversation_dir(conv["id"]) / "img_x.png"
        f.write_bytes(b"png")
        msg = db.add_chat_message(
            conv["id"],
            "assistant",
            media=[{"id": "i1", "kind": "image", "source": "generated", "status": "done", "file": "img_x.png"}],
        )
        assert client.delete("/api/chat/library/i1").status_code == 404  # still attached
        db.truncate_chat(conv["id"], after_id=msg.id - 1)
        assert client.delete("/api/chat/library/i1").status_code == 200
        assert not f.exists()
        assert jp.seq(client.get("/api/chat/library"), "items") == []

    def test_deleting_conversation_removes_its_library_items(
        self, client: TestClient, conv: ConversationOut, db: MetadataDB
    ) -> None:
        """Test that deleting conversation removes its library items."""
        msg = db.add_chat_message(
            conv["id"],
            "assistant",
            media=[{"id": "i2", "kind": "image", "source": "generated", "status": "done", "file": "x.png"}],
        )
        db.truncate_chat(conv["id"], after_id=msg.id - 1)
        client.delete(f"/api/chat/conversations/{conv['id']}")
        assert db.get_chat_library_item("i2") is None

    def test_deleting_conversation_can_keep_its_files(
        self, client: TestClient, conv: ConversationOut, chat: None
    ) -> None:
        """Test that deleting conversation can keep its files."""
        folder = chat_pkg.conversation_dir(conv["id"])
        (folder / "keep.png").write_bytes(b"x")
        client.delete(f"/api/chat/conversations/{conv['id']}?delete_media=false")
        assert (folder / "keep.png").exists()

    def test_deleting_conversation_deletes_files_by_default(
        self, client: TestClient, conv: ConversationOut, chat: None
    ) -> None:
        """Test that deleting conversation deletes files by default."""
        folder = chat_pkg.conversation_dir(conv["id"])
        (folder / "gone.png").write_bytes(b"x")
        client.delete(f"/api/chat/conversations/{conv['id']}")
        for _ in range(50):  # the folder is removed on a background thread
            if not folder.exists():
                break
            time.sleep(0.05)
        assert not folder.exists()

    def test_deleting_an_exchange_can_delete_its_media(
        self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB
    ) -> None:
        """Test that deleting an exchange can delete its media."""
        user = db.add_chat_message(conv["id"], "user", "draw")
        (chat_pkg.conversation_dir(conv["id"]) / "img_x.png").write_bytes(b"x")
        db.add_chat_message(
            conv["id"],
            "assistant",
            media=[{"id": "m1", "kind": "image", "source": "generated", "status": "done", "file": "img_x.png"}],
        )
        client.delete(f"/api/chat/messages/{user.id}?delete_media=true")
        assert not (chat_pkg.conversation_dir(conv["id"]) / "img_x.png").exists()
        assert db.get_chat_library_item("m1") is None


def test_resend_same_prompt_gets_fresh_reply(
    client: TestClient, conv: ConversationOut, chat: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Retry on a prompt = edit with unchanged text: a new branch with a fresh reply."""
    replies = iter([text_chunks("a"), text_chunks("b"), text_chunks("c")])
    monkeypatch.setattr(openrouter, "stream_chat", stub(lambda: next(replies)))
    first = jp.obj(
        sse_events(
            client.post(
                f"/api/chat/conversations/{conv['id']}/messages", json={"content": "tell me a joke", **SETTINGS}
            )
        )[0],
        "user_message",
    )
    sse_events(client.post(f"/api/chat/conversations/{conv['id']}/messages", json={"content": "another", **SETTINGS}))
    sse_events(
        client.post(
            f"/api/chat/conversations/{conv['id']}/edit",
            json={"message_id": first["id"], "content": "tell me a joke", **SETTINGS},
        )
    )
    msgs = jp.rows(client.get(f"/api/chat/conversations/{conv['id']}"), "messages")
    assert [(m["role"], m["content"]) for m in msgs] == [("user", "tell me a joke"), ("assistant", "c")]


class TestModerationAndRegenerate:
    """Tests for moderation and regenerate."""

    def _blocked(
        self, chat: None, status: int = 403, msg: str = "Your input was flagged by moderation"
    ) -> Callable[..., None]:
        def boom(*_a: object, **_k: object) -> None:
            raise openrouter.OpenRouterError(msg, status)

        return boom

    def test_moderation_block_ends_turn_without_retry(
        self, client: TestClient, conv: ConversationOut, chat: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that moderation block ends turn without retry."""
        rounds = iter([tool_chunks("generate_image", {"prompt": "risky", "aspect_ratio": "9:16"}, text="Here goes.")])
        calls: list[int] = []
        monkeypatch.setattr(openrouter, "stream_chat", stub(lambda: (calls.append(1), next(rounds))[1]))
        monkeypatch.setattr(openrouter, "generate_image", self._blocked(chat))
        ev = sse_events(
            client.post(f"/api/chat/conversations/{conv['id']}/messages", json={"content": "draw it", **SETTINGS})
        )
        assert len(calls) == 1  # no follow-up round, so no silent re-attempt
        done = jp.obj(ev[-1], "message")
        assert done["content"] == "Here goes."
        assert done["status"] == "done"
        item = jp.obj(done, "media", 0)
        assert item["status"] == "error"
        assert item["moderated"] is True
        # The model's 9:16 is ignored — ratio is the composer's, left on auto here
        assert item["params"] == {"aspect_ratio": None, "resolution": None, "refs": []}

    @pytest.mark.parametrize(
        ("status", "msg", "expected"),
        [
            (403, "Forbidden", True),
            (400, "[Seed] Request rejected: content policy violation", True),
            (400, "Provider returned error: prompt contains sensitive content", True),
            (502, "Upstream timed out", False),
            (400, "Invalid aspect_ratio", False),
        ],
    )
    def test_moderation_detection(self, chat: None, status: int, msg: str, expected: bool) -> None:
        """Test that moderation detection."""
        assert chat_generation.is_moderation_error(openrouter.OpenRouterError(msg, status)) is expected

    def _failed_image(self, db: MetadataDB, conv: ConversationOut, **extra: JsonValue) -> ChatMessage:
        db.add_chat_message(conv["id"], "user", "draw")
        return db.add_chat_message(
            conv["id"],
            "assistant",
            "Here goes.",
            model="t/model",
            media=[
                {
                    "id": "m1",
                    "kind": "image",
                    "source": "generated",
                    "status": "error",
                    "error": "flagged",
                    "moderated": True,
                    "prompt": "a lighthouse",
                    "model": "i/model",
                    "params": {"aspect_ratio": "16:9", "resolution": None, "refs": []},
                    **extra,
                }
            ],
        )

    def _run_worker_inline(self, chat: None, monkeypatch: pytest.MonkeyPatch) -> None:
        class Inline:
            def __init__(self, target: Callable[..., None], args: tuple[object, ...], **_kw: object) -> None:
                self.target, self.args = target, args

            def start(self) -> None:
                self.target(*self.args)

        monkeypatch.setattr(threading, "Thread", Inline)

    def test_retry_same_model(
        self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that retry same model."""
        msg = self._failed_image(db, conv)
        self._run_worker_inline(chat, monkeypatch)
        images = FakeImages(cost=0.02)
        monkeypatch.setattr(openrouter, "generate_image", images)
        r = client.post(f"/api/chat/messages/{msg.id}/media/m1/regenerate", json={})
        assert r.status_code == 200
        (call,) = images.calls
        assert call.model == "i/model"
        assert call.prompt == "a lighthouse"
        assert call.aspect_ratio == "16:9"
        item = jp.must(db.get_chat_message(msg.id)).media[0]
        assert item["status"] == "done"
        assert jp.text(item, "file").startswith("img_")
        assert item["moderated"] is False
        assert jp.must(db.get_chat_message(msg.id)).cost == 0.02

    def test_retry_with_different_model(
        self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that retry with different model."""
        msg = self._failed_image(db, conv)
        self._run_worker_inline(chat, monkeypatch)
        images = FakeImages(cost=None)
        monkeypatch.setattr(openrouter, "generate_image", images)
        client.post(f"/api/chat/messages/{msg.id}/media/m1/regenerate", json={"model": "other/model"})
        assert [c.model for c in images.calls] == ["other/model"]
        assert jp.must(db.get_chat_message(msg.id)).media[0]["model"] == "other/model"

    def test_retry_blocked_again_stays_failed(
        self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that retry blocked again stays failed."""
        msg = self._failed_image(db, conv)
        self._run_worker_inline(chat, monkeypatch)
        monkeypatch.setattr(openrouter, "generate_image", self._blocked(chat))
        client.post(f"/api/chat/messages/{msg.id}/media/m1/regenerate", json={})
        item = jp.must(db.get_chat_message(msg.id)).media[0]
        assert item["status"] == "error"
        assert item["moderated"] is True

    def test_retry_video_refits_params_for_new_model(
        self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that retry video refits params for new model."""
        db.add_chat_message(conv["id"], "user", "waves")
        msg = db.add_chat_message(
            conv["id"],
            "assistant",
            media=[
                {
                    "id": "v1",
                    "kind": "video",
                    "source": "generated",
                    "status": "error",
                    "error": "flagged",
                    "prompt": "waves",
                    "model": "v/old",
                    "params": {"duration": 7, "aspect_ratio": "16:9", "resolution": None, "first_frame": None},
                }
            ],
        )
        chat_catalogue.seed_models(
            {
                "text": [],
                "image": [],
                "video": [{"id": "v/new", "durations": [5, 10], "aspect_ratios": ["16:9"], "resolutions": []}],
            },
        )
        self._run_worker_inline(chat, monkeypatch)
        started = PollerStarts()
        monkeypatch.setattr(chat_polling, "start_video_poller", started)
        got: dict[str, JsonValue] = {}

        def fake_submit(model: str, _prompt: str, **kw: JsonValue) -> VideoJob:
            got.update(model=model, **kw)
            return {"id": "gen-vid-9"}

        monkeypatch.setattr(openrouter, "submit_video", fake_submit)
        client.post(f"/api/chat/messages/{msg.id}/media/v1/regenerate", json={"model": "v/new"})
        assert got["model"] == "v/new"
        assert got["duration"] == 5
        item = jp.must(db.get_chat_message(msg.id)).media[0]
        assert item["status"] == "pending"
        assert item["job_id"] == "gen-vid-9"
        assert started.jobs == [(conv["id"], msg.id, "v1", "gen-vid-9")]

    def test_finished_item_is_rerolled_as_a_new_item_beside_it(
        self, client: TestClient, conv: ConversationOut, db: MetadataDB, chat: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that finished item is rerolled as a new item beside it."""
        msg = self._failed_image(db, conv, status="done", file="x.png")
        self._run_worker_inline(chat, monkeypatch)
        monkeypatch.setattr(chat_pkg.routes_turns, "_regenerate_worker", stub(lambda: None))
        r = client.post(f"/api/chat/messages/{msg.id}/media/m1/regenerate", json={})
        assert r.status_code == 200
        old, new = jp.must(db.get_chat_message(msg.id)).media
        assert old["file"] == "x.png"
        assert old["status"] == "done"
        assert new["id"] != "m1"
        assert new["status"] == "pending"
        assert not new.get("file")
        assert client.post(f"/api/chat/messages/{msg.id}/media/nope/regenerate", json={}).status_code == 404


class TestContext:
    """Tests for context."""

    def _capture(self, chat: None, monkeypatch: pytest.MonkeyPatch) -> FakeStream:
        stream = FakeStream(text_chunks("ok"))
        monkeypatch.setattr(openrouter, "stream_chat", stream)
        return stream

    def _img(self, chat: None, conv: ConversationOut, name: str) -> dict[str, JsonValue]:
        (chat_pkg.conversation_dir(conv["id"]) / name).write_bytes(png_bytes())
        return {"id": name, "kind": "image", "source": "generated", "status": "done", "file": name, "prompt": name}

    def test_generated_image_is_sent_as_pixels_with_next_user_message(
        self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that generated image is sent as pixels with next user message."""
        db.add_chat_message(conv["id"], "user", "draw Linh")
        db.add_chat_message(conv["id"], "assistant", "Here she is.", media=[self._img(chat, conv, "g1.png")])
        stream = self._capture(chat, monkeypatch)
        sse_events(
            client.post(
                f"/api/chat/conversations/{conv['id']}/messages", json={"content": "what is she wearing?", **SETTINGS}
            )
        )
        msgs = stream.calls[-1].messages
        last = msgs[-1]
        assert last["role"] == "user"
        kinds = [jp.dig(p, "type") for p in jp.seq(last, "content")]
        assert kinds == ["text", "image_url", "text"]
        assert "images you generated" in jp.text(last, "content", 0, "text")
        assert jp.text(last, "content", 1, "image_url", "url").startswith("data:image/png;base64,")
        assert jp.text(last, "content", 2, "text") == "what is she wearing?"
        # the image appears in history as the tool call that made it
        assert jp.dig(msgs[-3], "tool_calls", 0, "function", "name") == "generate_image"
        assert msgs[-2]["role"] == "tool"

    def _pixels_sent(
        self,
        client: TestClient,
        conv: ConversationOut,
        chat: None,
        db: MetadataDB,
        monkeypatch: pytest.MonkeyPatch,
        **settings: JsonValue,
    ) -> int:
        for i in range(8):
            db.add_chat_message(conv["id"], "user", f"draw {i}")
            db.add_chat_message(conv["id"], "assistant", "ok", media=[self._img(chat, conv, f"g{i}.png")])
        stream = self._capture(chat, monkeypatch)
        sse_events(
            client.post(
                f"/api/chat/conversations/{conv['id']}/messages", json={"content": "next", **SETTINGS, **settings}
            )
        )
        return sum(
            1
            for m in stream.calls[-1].messages
            if isinstance(jp.dig(m, "content"), list)
            for p in jp.seq(m, "content")
            if jp.dig(p, "type") == "image_url"
        )

    def test_only_most_recent_images_as_pixels(
        self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that only most recent images as pixels."""
        assert self._pixels_sent(client, conv, chat, db, monkeypatch) == chat_constants.DEFAULT_IMAGE_LIMIT == 6

    @pytest.mark.parametrize(("limit", "expected"), [(2, 2), (0, 0), (None, 8)])
    def test_image_slider_sets_how_many(
        self,
        client: TestClient,
        conv: ConversationOut,
        chat: None,
        db: MetadataDB,
        monkeypatch: pytest.MonkeyPatch,
        limit: int | None,
        expected: int,
    ) -> None:
        """Test that image slider sets how many."""
        assert self._pixels_sent(client, conv, chat, db, monkeypatch, image_limit=limit) == expected

    def test_no_pixels_for_text_only_models(
        self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that no pixels for text only models."""
        chat_catalogue.seed_models(
            {
                "image": [],
                "video": [],
                "text": [{"id": "t/model", "supports_tools": True, "input_modalities": ["text"]}],
            },
        )
        db.add_chat_message(conv["id"], "user", "draw")
        db.add_chat_message(conv["id"], "assistant", "ok", media=[self._img(chat, conv, "g.png")])
        stream = self._capture(chat, monkeypatch)
        sse_events(client.post(f"/api/chat/conversations/{conv['id']}/messages", json={"content": "next", **SETTINGS}))
        assert stream.calls[-1].messages[-1] == {"role": "user", "content": [{"type": "text", "text": "next"}]}

    def test_history_limit_keeps_recent_messages_starting_on_user(
        self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that history limit keeps recent messages starting on user."""
        for i in range(5):
            db.add_chat_message(conv["id"], "user", f"q{i}")
            db.add_chat_message(conv["id"], "assistant", f"a{i}")
        stream = self._capture(chat, monkeypatch)
        # limit 4 of 11 history messages → [a3?, q4, a4, now] trimmed to start on a user message
        sse_events(
            client.post(
                f"/api/chat/conversations/{conv['id']}/messages",
                json={"content": "now", "history_limit": 4, **SETTINGS},
            )
        )
        body = stream.calls[-1].messages[1:]
        assert [m["role"] for m in body] == ["user", "assistant", "user"]
        assert jp.dig(body[0], "content", 0, "text") == "q4"

    def test_no_limit_sends_everything(
        self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that no limit sends everything."""
        for i in range(3):
            db.add_chat_message(conv["id"], "user", f"q{i}")
            db.add_chat_message(conv["id"], "assistant", f"a{i}")
        stream = self._capture(chat, monkeypatch)
        sse_events(client.post(f"/api/chat/conversations/{conv['id']}/messages", json={"content": "now", **SETTINGS}))
        msgs = stream.calls[-1].messages
        assert len(msgs) == 1 + 7
        assert "omitted" not in jp.text(msgs[0], "content")

    def test_invalid_limit_rejected(self, client: TestClient, conv: ConversationOut) -> None:
        """Test that invalid limit rejected."""
        r = client.post(
            f"/api/chat/conversations/{conv['id']}/messages", json={"content": "x", "history_limit": 0, **SETTINGS}
        )
        assert r.status_code == 422


class TestStallProtection:
    """A stalled upstream only sends keep-alives; we must not hang forever."""

    class _FakeStream:
        def __init__(self, lines: Iterator[str]) -> None:
            self.lines = lines
            self.status_code = 200

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_a: object) -> bool:
            return False

        def iter_lines(self) -> Iterator[str]:
            yield from self.lines

    def _keepalives(self) -> Iterator[str]:
        while True:
            _t.sleep(0.02)
            yield ": OPENROUTER PROCESSING"

    def test_deadline_breaks_a_keepalive_only_stream(self, chat: None, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that deadline breaks a keepalive only stream."""
        monkeypatch.setattr(openrouter.http_client, "stream", stub(lambda: self._FakeStream(self._keepalives())))
        with pytest.raises(openrouter.OpenRouterError) as e:
            list(openrouter.stream_chat("m", [], max_seconds=0.2))
        assert e.value.status == 504

    def test_stop_is_noticed_during_keepalives(self, chat: None, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that stop is noticed during keepalives."""
        monkeypatch.setattr(openrouter.http_client, "stream", stub(lambda: self._FakeStream(self._keepalives())))
        stop = threading.Event()
        threading.Timer(0.1, stop.set).start()
        t0 = _t.monotonic()
        assert list(openrouter.stream_chat("m", [], should_stop=stop.is_set)) == []
        assert _t.monotonic() - t0 < 2


class _StreamSpy:
    """A stand-in ``openrouter.stream_chat`` that records each call and plays the next scripted reply."""

    def __init__(self, next_reply: Callable[[], Iterator[ChatChunk]]) -> None:
        """Play ``next_reply()`` for every call."""
        self._next_reply = next_reply
        self.messages: list[list[dict[str, JsonValue]]] = []
        self.tools: list[list[dict[str, JsonValue]] | None] = []

    def __call__(
        self,
        model: str,
        messages: list[dict[str, JsonValue]],
        tools: list[dict[str, JsonValue]] | None = None,
        session_id: str | None = None,
        max_seconds: float | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> Iterator[ChatChunk]:
        """Record what was sent and stream the next reply."""
        self.messages.append(messages)
        self.tools.append(tools)
        return self._next_reply()


class _ImageApiSpy:
    """A stand-in ``openrouter.generate_image`` that records what it was asked for."""

    def __init__(self) -> None:
        """Start with nothing recorded."""
        self.prompt: str | None = None
        self.input_images: list[str] | None = None

    def __call__(
        self,
        model: str,
        prompt: str,
        aspect_ratio: str | None = None,
        resolution: str | None = None,
        input_images: list[str] | None = None,
        session_id: str | None = None,
    ) -> tuple[list[tuple[bytes, str]], float | None]:
        """Record the prompt and reference images, and return one picture."""
        self.prompt = prompt
        self.input_images = input_images
        return [(png_bytes(), "image/png")], None


class _ChatImageSpy:
    """A stand-in ``openrouter.generate_image_chat`` that records the conversation it was given."""

    def __init__(self, cost: float | None = None) -> None:
        """Return one picture costing ``cost``."""
        self._cost = cost
        self.model: str | None = None
        self.messages: list[dict[str, JsonValue]] = []
        self.aspect_ratio: str | None = None

    def __call__(
        self,
        model: str,
        messages: list[dict[str, JsonValue]],
        aspect_ratio: str | None = None,
        session_id: str | None = None,
    ) -> tuple[list[tuple[bytes, str]], float | None]:
        """Record what was sent and return one picture."""
        self.model = model
        self.messages = messages
        self.aspect_ratio = aspect_ratio
        return [(png_bytes(), "image/png")], self._cost


class TestConsistencyReferences:
    """Tests for consistency references."""

    def _prior_images(self, chat: None, db: MetadataDB, conv: ConversationOut, n: int) -> None:
        db.add_chat_message(conv["id"], "user", "story with a photo")
        for i in range(n):
            f = f"g{i}.png"
            (chat_pkg.conversation_dir(conv["id"]) / f).write_bytes(png_bytes(color=f"rgb({i * 40},0,0)"))
            db.add_chat_message(
                conv["id"],
                "assistant",
                f"scene {i}",
                media=[
                    {
                        "id": f"g{i}",
                        "kind": "image",
                        "source": "generated",
                        "status": "done",
                        "file": f,
                        "prompt": f"p{i}",
                    }
                ],
            )

    def _run(
        self,
        client: TestClient,
        conv: ConversationOut,
        chat: None,
        monkeypatch: pytest.MonkeyPatch,
        tool_args: dict[str, JsonValue],
    ) -> tuple[_ImageApiSpy, dict[str, JsonValue]]:
        replies = iter([tool_chunks("generate_image", tool_args, text="Next scene."), text_chunks("Done.")])
        monkeypatch.setattr(openrouter, "stream_chat", stub(lambda: next(replies)))
        got = _ImageApiSpy()
        monkeypatch.setattr(openrouter, "generate_image", got)
        ev = sse_events(
            client.post(
                f"/api/chat/conversations/{conv['id']}/messages", json={"content": "continue the story", **SETTINGS}
            )
        )
        return got, jp.obj(ev[-1], "message", "media", 0)

    def test_no_references_unless_the_model_asks(
        self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that no references unless the model asks."""
        self._prior_images(chat, db, conv, 1)
        got, item = self._run(client, conv, chat, monkeypatch, {"prompt": "the same woman, now turned around"})
        assert got.input_images is None
        assert jp.dig(item, "params", "refs") == []

    def test_model_opts_in_and_prompt_is_passed_verbatim(
        self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that model opts in and prompt is passed verbatim."""
        self._prior_images(chat, db, conv, 1)
        replies = iter(
            [
                tool_chunks(
                    "generate_image", {"prompt": "exactly what the model wrote", "keep_consistent": True}, text="Next."
                ),
                text_chunks("Done."),
            ]
        )
        monkeypatch.setattr(openrouter, "stream_chat", stub(lambda: next(replies)))
        got = _ImageApiSpy()
        monkeypatch.setattr(openrouter, "generate_image", got)
        sse_events(
            client.post(f"/api/chat/conversations/{conv['id']}/messages", json={"content": "continue", **SETTINGS})
        )
        assert got.prompt == "exactly what the model wrote"
        assert len(jp.must(got.input_images)) == 1

    def test_uses_only_the_most_recent_two(
        self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that uses only the most recent two."""
        self._prior_images(chat, db, conv, 3)
        _got, item = self._run(client, conv, chat, monkeypatch, {"prompt": "scene 4", "keep_consistent": True})
        assert jp.dig(item, "params", "refs") == ["g2.png", "g1.png"]

    def test_first_image_in_chat_has_no_refs(
        self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that first image in chat has no refs."""
        got, _item = self._run(client, conv, chat, monkeypatch, {"prompt": "Linh", "keep_consistent": True})
        assert got.input_images is None

    def test_skipped_for_image_models_without_reference_support(
        self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that skipped for image models without reference support."""
        chat_catalogue.seed_models(
            {"text": [], "video": [], "image": [{"id": "i/model", "input_modalities": ["text"]}]}
        )
        self._prior_images(chat, db, conv, 1)
        got, _item = self._run(client, conv, chat, monkeypatch, {"prompt": "next", "keep_consistent": True})
        assert got.input_images is None

    def test_edit_source_comes_first(
        self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that edit source comes first."""
        self._prior_images(chat, db, conv, 2)
        _got, item = self._run(
            client,
            conv,
            chat,
            monkeypatch,
            {"prompt": "make it night", "source_image": "latest", "keep_consistent": True},
        )
        assert jp.dig(item, "params", "refs") == ["g1.png", "g0.png"]

    def test_edit_alone_sends_just_the_source(
        self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that edit alone sends just the source."""
        self._prior_images(chat, db, conv, 2)
        _got, item = self._run(client, conv, chat, monkeypatch, {"prompt": "make it night", "source_image": "latest"})
        assert jp.dig(item, "params", "refs") == ["g1.png"]

    def _pin(
        self, client: TestClient, db: MetadataDB, conv: ConversationOut, media_id: str, pinned: bool = True
    ) -> JsonValue:
        msg = next(m for m in db.get_chat_messages(conv["id"]) if any(i["id"] == media_id for i in m.media))
        r = client.post(f"/api/chat/messages/{msg.id}/media/{media_id}/pin", json={"pinned": pinned})
        assert r.status_code == 200
        return jp.dig(r)

    def test_pinned_images_are_sent_without_the_model_asking(
        self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that pinned images are sent without the model asking."""
        self._prior_images(chat, db, conv, 3)
        out = self._pin(client, db, conv, "g0")
        assert jp.dig(out, "media", 0, "pinned") is True
        got, item = self._run(client, conv, chat, monkeypatch, {"prompt": "next scene"})
        assert jp.dig(item, "params", "refs") == ["g0.png"]
        assert len(jp.must(got.input_images)) == 1

    def test_order_is_edit_source_then_pins_then_recent_picks(
        self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Also the priority when a model takes fewer images (Venice edit models keep the first N)."""
        self._prior_images(chat, db, conv, 3)
        self._pin(client, db, conv, "g0")
        _got, item = self._run(
            client,
            conv,
            chat,
            monkeypatch,
            {"prompt": "make it night", "source_image": "latest", "keep_consistent": True},
        )
        assert jp.dig(item, "params", "refs") == ["g2.png", "g0.png", "g1.png"]
        assert jp.dig(item, "params", "ref_args") == {"source_image": "latest", "keep_consistent": True}

    def test_unpinned_images_stop_being_sent(
        self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that unpinned images stop being sent."""
        self._prior_images(chat, db, conv, 2)
        self._pin(client, db, conv, "g0")
        self._pin(client, db, conv, "g0", pinned=False)
        _got, item = self._run(client, conv, chat, monkeypatch, {"prompt": "next"})
        assert jp.dig(item, "params", "refs") == []

    def test_pinned_upload_is_a_reference_in_image_mode(
        self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that pinned upload is a reference in image mode."""
        (chat_pkg.conversation_dir(conv["id"]) / "u.png").write_bytes(png_bytes())
        db.add_chat_message(
            conv["id"],
            "user",
            "this is Linh",
            media=[{"id": "u1", "kind": "image", "source": "upload", "status": "done", "file": "u.png"}],
        )
        db.add_chat_message(conv["id"], "assistant", "Nice photo.")
        self._pin(client, db, conv, "u1")
        monkeypatch.setattr(openrouter, "generate_image", _ImageApiSpy())
        ev = sse_events(
            client.post(
                f"/api/chat/conversations/{conv['id']}/messages",
                json={"content": "Linh at the beach", **SETTINGS, "mode": "image"},
            )
        )
        assert jp.dig(ev[-1], "message", "media", 0, "params", "refs") == ["u.png"]

    def test_pins_ignored_for_image_models_without_reference_support(
        self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that pins ignored for image models without reference support."""
        chat_catalogue.seed_models(
            {"text": [], "video": [], "image": [{"id": "i/model", "input_modalities": ["text"]}]}
        )
        self._prior_images(chat, db, conv, 1)
        self._pin(client, db, conv, "g0")
        got, _item = self._run(client, conv, chat, monkeypatch, {"prompt": "next"})
        assert got.input_images is None

    def test_only_finished_images_can_be_pinned(
        self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB
    ) -> None:
        """Test that only finished images can be pinned."""
        db.add_chat_message(conv["id"], "user", "go")
        msg = db.add_chat_message(
            conv["id"],
            "assistant",
            "",
            media=[
                {"id": "v", "kind": "video", "source": "generated", "status": "done", "file": "v.mp4", "prompt": "p"},
                {"id": "e", "kind": "image", "source": "generated", "status": "error", "prompt": "p"},
            ],
        )
        for mid in ("v", "e", "nope"):
            assert client.post(f"/api/chat/messages/{msg.id}/media/{mid}/pin", json={"pinned": True}).status_code == 404

    def test_history_replays_reference_choices(
        self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that history replays reference choices."""
        db.add_chat_message(conv["id"], "user", "draw Linh again")
        db.add_chat_message(
            conv["id"],
            "assistant",
            "Here!",
            media=[
                {
                    "id": "a",
                    "kind": "image",
                    "source": "generated",
                    "status": "done",
                    "file": "x.png",
                    "prompt": "Linh",
                    "params": {"refs": ["p.png", "q.png"], "ref_args": {"keep_consistent": True}},
                }
            ],
        )
        seen = _StreamSpy(lambda: text_chunks("ok"))
        monkeypatch.setattr(openrouter, "stream_chat", seen)
        sse_events(client.post(f"/api/chat/conversations/{conv['id']}/messages", json={"content": "nice", **SETTINGS}))
        msgs = seen.messages[0]
        assert json.loads(jp.text(msgs, 2, "tool_calls", 0, "function", "arguments")) == {
            "prompt": "Linh",
            "keep_consistent": True,
        }
        assert json.loads(jp.text(msgs, 3, "content")) == {
            "ok": True,
            "result": chat_tools.IMAGE_TOOL_RESULT,
            "reference_images": 2,
        }


class TestModelDecides:
    """The app never adds instructions or extra calls to steer the model."""

    def test_no_extra_call_when_model_skips_the_tool(
        self, client: TestClient, conv: ConversationOut, chat: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that no extra call when model skips the tool."""
        calls = _StreamSpy(lambda: text_chunks("A story, and here's the photo."))
        monkeypatch.setattr(openrouter, "stream_chat", calls)
        ev = sse_events(
            client.post(
                f"/api/chat/conversations/{conv['id']}/messages",
                json={"content": "write a story and create an image of the scene", **SETTINGS},
            )
        )
        assert len(calls.messages) == 1
        assert jp.dig(ev[-1], "message", "content") == "A story, and here's the photo."
        assert jp.dig(ev[-1], "message", "media") == []

    def test_system_prompt_is_static(
        self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that system prompt is static."""
        for i in range(4):
            db.add_chat_message(conv["id"], "user", f"q{i}")
            db.add_chat_message(conv["id"], "assistant", f"a{i}")
        chat_catalogue.seed_models(
            {
                "image": [],
                "video": [],
                "text": [{"id": "t/model", "supports_tools": False, "input_modalities": ["text"]}],
            },
        )
        seen = _StreamSpy(lambda: text_chunks("ok"))
        monkeypatch.setattr(openrouter, "stream_chat", seen)
        sse_events(
            client.post(
                f"/api/chat/conversations/{conv['id']}/messages", json={"content": "hi", "history_limit": 3, **SETTINGS}
            )
        )

        today = datetime.now().astimezone().strftime("%A %d %B %Y")
        assert jp.dig(seen.messages[0], 0, "content") == chat_tools.SYSTEM_PROMPT.format(today=today)


class TestConversationalImageModels:
    """Gemini-style image models get the conversation, not a lone prompt."""

    CATALOGUE: ClassVar[Catalogue] = {
        "text": [],
        "video": [],
        "image": [{"id": "i/model", "input_modalities": ["text", "image"], "conversational": True}],
    }

    def _setup(self, chat: None, db: MetadataDB, conv: ConversationOut, with_prior_image: bool = True) -> None:
        chat_catalogue.seed_models(self.CATALOGUE)
        db.add_chat_message(conv["id"], "user", "write a story about Linh, with a photo")
        media: list[dict[str, JsonValue]] = []
        if with_prior_image:
            (chat_pkg.conversation_dir(conv["id"]) / "g0.png").write_bytes(png_bytes())
            media = [
                {
                    "id": "g0",
                    "kind": "image",
                    "source": "generated",
                    "status": "done",
                    "file": "g0.png",
                    "prompt": "Linh in the gym",
                }
            ]
        db.add_chat_message(conv["id"], "assistant", "Linh lifted.", media=media)

    def _fake_chat_image(self, chat: None, monkeypatch: pytest.MonkeyPatch) -> _ChatImageSpy:
        got = _ChatImageSpy(cost=0.04)
        monkeypatch.setattr(openrouter, "generate_image_chat", got)
        monkeypatch.setattr(openrouter, "generate_image", stub(lambda: pytest.fail("Images API not used")))
        return got

    def test_auto_mode_sends_conversation_reply_and_prompt(
        self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that auto mode sends conversation reply and prompt."""
        self._setup(chat, db, conv)
        replies = iter(
            [
                tool_chunks(
                    "generate_image", {"prompt": "Linh turns around", "aspect_ratio": "3:4"}, text="She turned around."
                ),
                text_chunks("Done."),
            ]
        )
        monkeypatch.setattr(openrouter, "stream_chat", stub(lambda: next(replies)))
        got = self._fake_chat_image(chat, monkeypatch)
        ev = sse_events(
            client.post(
                f"/api/chat/conversations/{conv['id']}/messages",
                json={"content": "can I see your muscles? (continue, with an image)", **SETTINGS},
            )
        )
        msgs = got.messages
        # The model's 3:4 pick is ignored; the composer (on auto) governs the ratio
        assert got.model == "i/model"
        assert got.aspect_ratio is None
        assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant", "user"]
        assert jp.text(msgs, 0, "content", 0, "text") == "write a story about Linh, with a photo"
        # the earlier generated image is in the context as pixels
        assert any(jp.dig(p, "type") == "image_url" for p in jp.seq(msgs, 2, "content"))
        assert msgs[3] == {"role": "assistant", "content": "She turned around."}  # this reply so far
        assert msgs[4] == {"role": "user", "content": [{"type": "text", "text": "Linh turns around"}]}  # verbatim
        assert all(m["role"] != "system" for m in msgs)
        item = jp.obj(ev[-1], "message", "media", 0)
        assert item["status"] == "done"
        assert jp.dig(item, "params", "context") is True

    def test_image_mode_sends_conversation_ending_with_users_message(
        self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that image mode sends conversation ending with users message."""
        self._setup(chat, db, conv)
        got = self._fake_chat_image(chat, monkeypatch)
        sse_events(
            client.post(
                f"/api/chat/conversations/{conv['id']}/messages",
                json={"content": "Linh and Marcus high-five", "mode": "image", **SETTINGS},
            )
        )
        last = got.messages[-1]
        assert last["role"] == "user"
        assert jp.dig(last, "content", -1) == {"type": "text", "text": "Linh and Marcus high-five"}
        assert len(got.messages) == 3

    def test_memory_slider_applies_to_image_context(
        self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that memory slider applies to image context."""
        self._setup(chat, db, conv, with_prior_image=False)
        for i in range(3):
            db.add_chat_message(conv["id"], "user", f"q{i}")
            db.add_chat_message(conv["id"], "assistant", f"a{i}")
        got = self._fake_chat_image(chat, monkeypatch)
        sse_events(
            client.post(
                f"/api/chat/conversations/{conv['id']}/messages",
                json={"content": "draw it", "mode": "image", "history_limit": 3, **SETTINGS},
            )
        )
        assert [m["role"] for m in got.messages] == ["user", "assistant", "user"]

    def test_non_conversational_models_still_use_images_api(
        self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that non conversational models still use images api."""
        chat_catalogue.seed_models(
            {
                "text": [],
                "video": [],
                "image": [{"id": "i/model", "input_modalities": ["text", "image"], "conversational": False}],
            },
        )
        monkeypatch.setattr(openrouter, "generate_image_chat", stub(lambda: pytest.fail("chat path not used")))
        monkeypatch.setattr(openrouter, "generate_image", stub(lambda: ([(png_bytes(), "image/png")], None)))
        ev = sse_events(
            client.post(
                f"/api/chat/conversations/{conv['id']}/messages", json={"content": "a dog", "mode": "image", **SETTINGS}
            )
        )
        assert "context" not in jp.obj(ev[-1], "message", "media", 0, "params")

    def test_retry_of_failed_image_rebuilds_context(
        self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that retry of failed image rebuilds context."""
        chat_catalogue.seed_models(self.CATALOGUE)
        db.add_chat_message(conv["id"], "user", "story please, with a photo")
        msg = db.add_chat_message(
            conv["id"],
            "assistant",
            "Linh lifted.",
            media=[
                {
                    "id": "m1",
                    "kind": "image",
                    "source": "generated",
                    "status": "error",
                    "error": "timeout",
                    "prompt": "Linh lifting",
                    "model": "i/model",
                    "params": {"aspect_ratio": None, "resolution": None, "refs": [], "context": True, "direct": False},
                }
            ],
        )

        class Inline:
            """A thread that runs its target on ``start`` instead of in the background."""

            def __init__(self, target: Callable[..., object], args: tuple[object, ...], **kw: object) -> None:
                self.target, self.args = target, args

            def start(self) -> None:
                self.target(*self.args)

        monkeypatch.setattr(threading, "Thread", Inline)
        got = self._fake_chat_image(chat, monkeypatch)
        client.post(f"/api/chat/messages/{msg.id}/media/m1/regenerate", json={})
        assert [m["role"] for m in got.messages] == ["user", "assistant", "user"]
        assert got.messages[1] == {"role": "assistant", "content": "Linh lifted."}
        assert jp.text(got.messages, 2, "content", 0, "text") == "Linh lifting"
        assert jp.must(db.get_chat_message(msg.id)).media[0]["status"] == "done"


class TestOpenRouterChatImages:
    """Tests for open router chat images."""

    def _resp(self, body: JsonValue) -> httpx.Response:
        return httpx.Response(200, json=body)

    def test_parses_data_url_images_and_sends_modalities(self, chat: None, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that parses data url images and sends modalities."""
        sent: dict[str, JsonValue] = {}
        b64 = base64.b64encode(png_bytes()).decode()

        def fake_post(url: str, **kw: JsonValue) -> httpx.Response:
            sent.update(jp.obj(kw, "json"))
            return self._resp(
                {
                    "choices": [
                        {
                            "message": {
                                "content": "Here",
                                "images": [{"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}],
                            }
                        }
                    ],
                    "usage": {"cost": 0.039},
                }
            )

        monkeypatch.setattr(openrouter.http_client, "post", fake_post)
        images, cost = openrouter.generate_image_chat("g/img", [{"role": "user", "content": "hi"}], aspect_ratio="16:9")
        assert sent["modalities"] == ["image", "text"]
        assert sent["image_config"] == {"aspect_ratio": "16:9"}
        assert images == [(png_bytes(), "image/png")]
        assert cost == 0.039

    def test_no_image_reports_models_text(self, chat: None, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that no image reports models text."""
        monkeypatch.setattr(
            openrouter.http_client,
            "post",
            stub(lambda: self._resp({"choices": [{"message": {"content": "I can't draw that."}}]})),
        )
        with pytest.raises(openrouter.OpenRouterError) as e:
            openrouter.generate_image_chat("g/img", [])
        assert "I can't draw that." in str(e.value)

    def test_catalogue_marks_and_adds_conversational_models(self, chat: None, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that catalogue marks and adds conversational models."""

        def fake_get(path: str, params: dict[str, str] | None = None) -> dict[str, JsonValue]:
            if path == "/images/models":
                return {"data": [{"id": "google/gem-img", "name": "Gem"}, {"id": "seed/dream", "name": "Seed"}]}
            return {
                "data": [
                    {"id": "google/gem-img", "architecture": {"output_modalities": ["image", "text"]}},
                    {
                        "id": "openai/gpt-img",
                        "name": "GPT Image",
                        "architecture": {"output_modalities": ["image", "text"], "input_modalities": ["text", "image"]},
                    },
                    {"id": "seed/dream", "architecture": {"output_modalities": ["image"]}},
                ]
            }

        monkeypatch.setattr(openrouter, "_get", fake_get)
        models = {jp.text(m, "id"): m for m in openrouter.list_image_models()}
        assert jp.dig(models, "google/gem-img", "conversational") is True
        assert jp.dig(models, "seed/dream", "conversational") is False
        assert jp.dig(models, "openai/gpt-img", "conversational") is True
        assert jp.dig(models, "openai/gpt-img", "name") == "GPT Image"


class TestFollowUpRounds:
    """Tests for follow up rounds."""

    def _run(
        self,
        client: TestClient,
        conv: ConversationOut,
        chat: None,
        monkeypatch: pytest.MonkeyPatch,
        rounds: list[Iterator[ChatChunk]],
    ) -> tuple[list[list[dict[str, JsonValue]] | None], dict[str, JsonValue]]:
        upcoming = iter(rounds)
        spy = _StreamSpy(lambda: next(upcoming))
        monkeypatch.setattr(openrouter, "stream_chat", spy)
        monkeypatch.setattr(openrouter, "generate_image", stub(lambda: ([(png_bytes(), "image/png")], None)))
        ev = sse_events(
            client.post(
                f"/api/chat/conversations/{conv['id']}/messages", json={"content": "story and a picture", **SETTINGS}
            )
        )
        return spy.tools, jp.obj(ev[-1], "message")

    def test_tool_first_gets_one_text_only_follow_up(
        self, client: TestClient, conv: ConversationOut, chat: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that tool first gets one text only follow up."""
        calls, done = self._run(
            client,
            conv,
            chat,
            monkeypatch,
            [
                tool_chunks("generate_image", {"prompt": "scene"}),  # no text yet
                text_chunks("Here is the story."),
            ],
        )
        assert len(calls) == 2
        assert calls[0]
        assert calls[1] is None
        assert done["content"] == "Here is the story."
        assert len(jp.seq(done, "media")) == 1

    def test_no_second_image_even_if_the_model_tries(
        self, client: TestClient, conv: ConversationOut, chat: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # With tools withheld, a model can't call generate_image again
        """Test that no second image even if the model tries."""
        _calls, done = self._run(
            client,
            conv,
            chat,
            monkeypatch,
            [
                tool_chunks("generate_image", {"prompt": "scene"}),
                text_chunks("Story."),
            ],
        )
        assert len(jp.seq(done, "media")) == 1

    def test_non_moderation_failure_keeps_tools_for_a_retry(
        self, client: TestClient, conv: ConversationOut, chat: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that non moderation failure keeps tools for a retry."""
        attempts: list[str] = []

        def image(model: str, prompt: str, **kw: object) -> tuple[list[tuple[bytes, str]], float | None]:
            attempts.append(prompt)
            if len(attempts) == 1:
                raise UpstreamTimeoutError
            return [(png_bytes(), "image/png")], None

        rounds = iter(
            [
                tool_chunks("generate_image", {"prompt": "first"}, text="Story."),
                tool_chunks("generate_image", {"prompt": "second"}, text="Trying again."),
            ]
        )
        spy = _StreamSpy(lambda: next(rounds))
        monkeypatch.setattr(openrouter, "stream_chat", spy)
        monkeypatch.setattr(openrouter, "generate_image", image)
        ev = sse_events(
            client.post(
                f"/api/chat/conversations/{conv['id']}/messages", json={"content": "story and a picture", **SETTINGS}
            )
        )
        assert len(spy.tools) == 2
        assert spy.tools[1]
        assert attempts == ["first", "second"]
        assert [jp.dig(m, "status") for m in jp.rows(ev[-1], "message", "media")] == ["error", "done"]


def test_attribution_is_generic_and_hidden(chat: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """The app is named but not linkable: generic localhost URL, hidden from public rankings."""
    monkeypatch.setenv("OPENROUTER_REFERER", "https://example.com/should-be-ignored")
    assert openrouter.request_headers() == {
        "Authorization": "Bearer sk-test",
        "HTTP-Referer": "http://localhost",
        "X-OpenRouter-Title": "Pollo Chat",
        "X-OpenRouter-App-Visibility": "hidden",
    }


def _new_snippet(client: TestClient, name: str, content: str) -> int:
    """Create an instruction snippet and return its id."""
    return jp.integer(client.post("/api/chat/instructions", json={"name": name, "content": content}), "id")


def _new_group(client: TestClient, name: str, snippet_ids: list[int]) -> int:
    """Create an instruction group and return its id."""
    body = {"name": name, "snippet_ids": snippet_ids}
    return jp.integer(client.post("/api/chat/instruction-groups", json=body), "id")


class TestCustomInstructions:
    """Tests for custom instructions."""

    def test_snippet_crud(self, client: TestClient) -> None:
        """Test that snippet crud."""
        a = _new_snippet(client, "Terse", "Be brief.")
        b = _new_snippet(client, "Story", "Write vividly.")
        listed = client.get("/api/chat/instructions")
        assert {jp.text(i, "name") for i in jp.rows(listed, "instructions")} == {"Terse", "Story"}
        r = client.put(f"/api/chat/instructions/{a}", json={"name": "Terse", "content": "Very brief."})
        assert jp.dig(r, "content") == "Very brief."
        assert client.delete(f"/api/chat/instructions/{b}").status_code == 200
        listed = client.get("/api/chat/instructions")
        assert [jp.text(i, "name") for i in jp.rows(listed, "instructions")] == ["Terse"]
        assert client.post("/api/chat/instructions", json={"name": "", "content": "x"}).status_code == 422

    def test_group_crud(self, client: TestClient) -> None:
        """Test that group crud."""
        a = _new_snippet(client, "Tone", "Be warm.")
        b = _new_snippet(client, "Format", "Use markdown.")
        g = _new_group(client, "Starter", [a, b])
        data = client.get("/api/chat/instructions")
        assert [jp.text(x, "name") for x in jp.rows(data, "groups")] == ["Starter"]
        assert jp.dig(data, "groups", 0, "snippet_ids") == [a, b]
        assert (
            client.post("/api/chat/instruction-groups", json={"name": "Bad", "snippet_ids": [9999]}).status_code == 400
        )
        assert client.delete(f"/api/chat/instruction-groups/{g}").status_code == 200
        assert jp.dig(client.get("/api/chat/instructions"), "groups") == []

    def test_deleting_a_snippet_removes_it_from_groups_and_chats(
        self, client: TestClient, conv: ConversationOut
    ) -> None:
        """Test that deleting a snippet removes it from groups and chats."""
        a = _new_snippet(client, "A", "x")
        b = _new_snippet(client, "B", "y")
        g = _new_group(client, "G", [a, b])
        client.patch(
            f"/api/chat/conversations/{conv['id']}",
            json={"instruction_ids": [a], "instruction_group_ids": [g]},
        )
        client.delete(f"/api/chat/instructions/{a}")
        assert jp.dig(client.get("/api/chat/instructions"), "groups", 0, "snippet_ids") == [b]
        gone = client.get(f"/api/chat/conversations/{conv['id']}")
        assert jp.dig(gone, "conversation", "instruction_ids") == []
        assert jp.dig(gone, "conversation", "instruction_group_ids") == [g]

    def test_global_defaults_apply_live_to_every_chat(self, client: TestClient, chat: None) -> None:
        """Test that global defaults apply live to every chat."""
        d = _new_snippet(client, "D", "x")
        e = _new_snippet(client, "E", "y")
        g = _new_group(client, "G", [d])
        client.put(
            "/api/chat/settings",
            json={"default_instruction_ids": [d, e], "default_instruction_group_ids": [g]},
        )
        made = client.post("/api/chat/conversations", json={})
        # Nothing is copied in: the defaults apply on top of the chat's own (none here)
        assert jp.dig(made, "instruction_ids") == []
        assert jp.dig(made, "instruction_group_ids") == []
        made_id = jp.text(made, "id")
        assert chat_generation.conversation_instructions(made_id) == "x\n\ny"  # D once, though in G too
        # Changing the defaults changes the chat
        client.put("/api/chat/settings", json={"default_instruction_ids": [e]})
        assert chat_generation.conversation_instructions(made_id) == "y"
        assert client.post("/api/chat/conversations", json={"instruction_ids": [999]}).status_code == 400

    def test_global_settings_crud_and_validation(self, client: TestClient) -> None:
        """Test that global settings crud and validation."""
        s = _new_snippet(client, "S", "x")
        assert jp.dig(client.get("/api/chat/settings")) == {
            "default_character_ids": [],
            "default_instruction_ids": [],
            "default_instruction_group_ids": [],
            "title_model": None,
        }
        updated = client.put("/api/chat/settings", json={"default_instruction_ids": [s]})
        assert jp.dig(updated, "default_instruction_ids") == [s]
        assert client.put("/api/chat/settings", json={"default_instruction_ids": [999]}).status_code == 400
        # Deleting the snippet clears it from the global bucket
        client.delete(f"/api/chat/instructions/{s}")
        assert jp.dig(client.get("/api/chat/settings"), "default_instruction_ids") == []

    def test_attach_and_detach_on_existing_chat(self, client: TestClient, conv: ConversationOut) -> None:
        """Test that attach and detach on existing chat."""
        i = _new_snippet(client, "I", "x")
        attached = client.patch(f"/api/chat/conversations/{conv['id']}", json={"instruction_ids": [i]})
        assert jp.dig(attached, "instruction_ids") == [i]
        detached = client.patch(f"/api/chat/conversations/{conv['id']}", json={"instruction_ids": []})
        assert jp.dig(detached, "instruction_ids") == []

    def test_deleting_an_instruction_detaches_it(self, client: TestClient, conv: ConversationOut) -> None:
        """Test that deleting an instruction detaches it."""
        i = _new_snippet(client, "I", "x")
        client.patch(f"/api/chat/conversations/{conv['id']}", json={"instruction_ids": [i]})
        client.delete(f"/api/chat/instructions/{i}")
        assert jp.dig(client.get(f"/api/chat/conversations/{conv['id']}"), "conversation", "instruction_ids") == []

    def test_flattened_snippets_and_groups_sent_deduped_as_one_system_message(
        self, client: TestClient, conv: ConversationOut, chat: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that flattened snippets and groups sent deduped as one system message."""
        tone = _new_snippet(client, "Tone", "Be warm.")
        fmt = _new_snippet(client, "Fmt", "Use markdown.")
        lang = _new_snippet(client, "Lang", "In French.")
        g = _new_group(client, "G", [tone, fmt])
        # tone is attached both via the group and individually: sent once
        client.patch(
            f"/api/chat/conversations/{conv['id']}",
            json={"instruction_group_ids": [g], "instruction_ids": [tone, lang]},
        )
        seen = _StreamSpy(lambda: text_chunks("ok"))
        monkeypatch.setattr(openrouter, "stream_chat", seen)
        sse_events(client.post(f"/api/chat/conversations/{conv['id']}/messages", json={"content": "hi", **SETTINGS}))
        msgs = seen.messages[0]
        assert msgs[1] == {"role": "system", "content": "Be warm.\n\nUse markdown.\n\nIn French."}
        assert msgs[2]["role"] == "user"

    def test_not_sent_when_none_attached(
        self, client: TestClient, conv: ConversationOut, chat: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that not sent when none attached."""
        seen = _StreamSpy(lambda: text_chunks("ok"))
        monkeypatch.setattr(openrouter, "stream_chat", seen)
        sse_events(client.post(f"/api/chat/conversations/{conv['id']}/messages", json={"content": "hi", **SETTINGS}))
        assert [m["role"] for m in seen.messages[0]] == ["system", "user"]

    def test_conversational_image_models_get_them_too(
        self, client: TestClient, conv: ConversationOut, chat: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that conversational image models get them too."""
        chat_catalogue.seed_models(
            {
                "text": [],
                "video": [],
                "image": [{"id": "i/model", "input_modalities": ["text", "image"], "conversational": True}],
            },
        )
        i = _new_snippet(client, "I", "Watercolour style only.")
        client.patch(f"/api/chat/conversations/{conv['id']}", json={"instruction_ids": [i]})
        got = _ChatImageSpy()
        monkeypatch.setattr(openrouter, "generate_image_chat", got)
        sse_events(
            client.post(
                f"/api/chat/conversations/{conv['id']}/messages", json={"content": "a fox", "mode": "image", **SETTINGS}
            )
        )
        assert got.messages[0] == {"role": "system", "content": "Watercolour style only."}


class TestChatSpaces:
    """Tests for chat spaces."""

    def test_crud(self, client: TestClient) -> None:
        """Test that crud."""
        s = _new_snippet(client, "Tone", "Be warm.")
        g = _new_group(client, "G", [s])
        sp = client.post(
            "/api/chat/spaces",
            json={"name": "Novel", "default_instruction_ids": [s], "default_instruction_group_ids": [g]},
        )
        assert jp.dig(sp, "name") == "Novel"
        assert jp.dig(sp, "default_instruction_ids") == [s]
        assert [jp.text(x, "name") for x in jp.rows(client.get("/api/chat/spaces"), "spaces")] == ["Novel"]
        space_id = jp.integer(sp, "id")
        upd = client.put(f"/api/chat/spaces/{space_id}", json={"name": "Renamed"})
        assert jp.dig(upd, "name") == "Renamed"
        assert jp.dig(upd, "default_instruction_ids") == []
        assert client.delete(f"/api/chat/spaces/{space_id}").status_code == 200
        assert jp.dig(client.get("/api/chat/spaces"), "spaces") == []
        assert (
            client.post("/api/chat/spaces", json={"name": "Bad", "default_instruction_ids": [999]}).status_code == 400
        )

    def test_chat_in_space_stacks_global_and_space_defaults_deduped(self, client: TestClient, chat: None) -> None:
        """Test that chat in space stacks global and space defaults deduped."""
        shared = _new_snippet(client, "Shared", "both.")
        spaceonly = _new_snippet(client, "SpaceOnly", "Be warm.")
        glob = _new_snippet(client, "Glob", "x")
        # Global defaults: glob + shared. Space defaults: shared + spaceonly.
        client.put("/api/chat/settings", json={"default_instruction_ids": [glob, shared]})
        sp = jp.integer(
            client.post("/api/chat/spaces", json={"name": "Novel", "default_instruction_ids": [shared, spaceonly]}),
            "id",
        )
        made = client.post("/api/chat/conversations", json={"space_id": sp})
        assert jp.dig(made, "space_id") == sp
        assert jp.dig(made, "instruction_ids") == []
        made_id = jp.text(made, "id")
        # Global first, then the space's own, each snippet once (shared de-duped)
        assert chat_generation.conversation_instructions(made_id) == "x\n\nboth.\n\nBe warm."
        # Out of the space, only the global defaults apply
        client.patch(f"/api/chat/conversations/{made_id}", json={"space_id": None})
        assert chat_generation.conversation_instructions(made_id) == "x\n\nboth."

    def test_chat_without_space_uses_only_global_defaults(self, client: TestClient, chat: None, db: MetadataDB) -> None:
        """Test that chat without space uses only global defaults."""
        glob = _new_snippet(client, "Glob", "x")
        client.put("/api/chat/settings", json={"default_instruction_ids": [glob]})
        made = client.post("/api/chat/conversations", json={})
        assert jp.dig(made, "space_id") is None
        assert chat_helpers.inherited_ids(db.get_conversation(jp.text(made, "id")))["instruction"] == [glob]

    def test_space_character_defaults_apply_to_its_chats(self, client: TestClient, chat: None, db: MetadataDB) -> None:
        """Test that space character defaults apply to its chats."""
        c1 = db.create_character("Alice")
        c2 = db.create_character("Bob")
        space = client.post("/api/chat/spaces", json={"name": "Novel", "default_character_ids": [c1.id]})
        made = client.post(
            "/api/chat/conversations", json={"space_id": jp.integer(space, "id"), "character_ids": [c2.id]}
        )
        assert jp.dig(made, "character_ids") == [c2.id]  # its own
        assert chat_helpers.effective_ids(db.get_conversation(jp.text(made, "id")), "character") == [c1.id, c2.id]

    def test_deleting_a_character_clears_it_from_global_and_space_defaults(
        self, client: TestClient, db: MetadataDB
    ) -> None:
        """Test that deleting a character clears it from global and space defaults."""
        c1 = db.create_character("Alice")
        client.put("/api/chat/settings", json={"default_character_ids": [c1.id]})
        sp = client.post("/api/chat/spaces", json={"name": "Novel", "default_character_ids": [c1.id]})
        assert jp.dig(sp, "default_character_ids") == [c1.id]
        db.delete_character(c1.id)  # symmetric with snippet/group deletion
        assert jp.dig(client.get("/api/chat/settings"), "default_character_ids") == []
        assert jp.dig(client.get("/api/chat/spaces"), "spaces", 0, "default_character_ids") == []

    def test_move_chat_between_spaces_and_unfiled(self, client: TestClient, conv: ConversationOut) -> None:
        """Test that move chat between spaces and unfiled."""
        sp = jp.integer(client.post("/api/chat/spaces", json={"name": "Novel"}), "id")
        moved = client.patch(f"/api/chat/conversations/{conv['id']}", json={"space_id": sp})
        assert jp.dig(moved, "space_id") == sp
        back = client.patch(f"/api/chat/conversations/{conv['id']}", json={"space_id": None})
        assert jp.dig(back, "space_id") is None
        assert client.patch(f"/api/chat/conversations/{conv['id']}", json={"space_id": 999}).status_code == 400

    def test_deleting_space_unfiles_its_chats(self, client: TestClient) -> None:
        """Test that deleting space unfiles its chats."""
        sp = jp.integer(client.post("/api/chat/spaces", json={"name": "Novel"}), "id")
        made = jp.text(client.post("/api/chat/conversations", json={"space_id": sp}), "id")
        client.delete(f"/api/chat/spaces/{sp}")
        assert jp.dig(client.get(f"/api/chat/conversations/{made}"), "conversation", "space_id") is None

    def test_deleting_a_snippet_clears_it_from_space_defaults(self, client: TestClient) -> None:
        """Test that deleting a snippet clears it from space defaults."""
        s = _new_snippet(client, "Tone", "x")
        client.post("/api/chat/spaces", json={"name": "Novel", "default_instruction_ids": [s]})
        client.delete(f"/api/chat/instructions/{s}")
        assert jp.dig(client.get("/api/chat/spaces"), "spaces", 0, "default_instruction_ids") == []


def _no_statuses() -> Iterator[list[TaskResult]]:
    """An empty queue of Pollo task statuses."""
    return iter([])


@dataclass
class PolloCalls:
    """What the faked Pollo client was asked to do, and the task statuses it will report next."""

    generators: list[tuple[str, dict[str, JsonValue]]] = field(default_factory=list)
    uploads: list[str] = field(default_factory=list)
    statuses: Iterator[list[TaskResult]] = field(default_factory=_no_statuses)

    def report(self, *rounds: list[TaskResult]) -> None:
        """Queue the statuses that successive polls of a Pollo task will see."""
        self.statuses = iter(rounds)


class _FakeResponse:
    """A canned HTTP response, usable as a ``requests`` response and as a context manager."""

    def __init__(
        self,
        body: JsonValue,
        content: bytes = b"",
        content_type: str = "image/png",
        status_code: int = 200,
    ) -> None:
        self._body = body
        self.content = content
        self.status_code = status_code
        self.text = ""
        self.headers = {"Content-Type": content_type}

    def json(self) -> JsonValue:
        """The canned body."""
        return self._body

    def raise_for_status(self) -> None:
        """Never raises: every canned response is a success."""

    def iter_content(self, chunk_size: int | None = None) -> Iterator[bytes]:
        """The whole content as one chunk."""
        _ = chunk_size
        yield self.content

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


class _FakeGenerator:
    """A Pollo image/video generator that records its call and answers "accepted"."""

    api_key = "pollo-test"

    def __init__(self, calls: PolloCalls, key: str, **kwargs: JsonValue) -> None:
        calls.generators.append((key, kwargs))
        self._kwargs = kwargs
        self.payload_attrs: dict[str, JsonValue] = {}

    def get_payload(self) -> dict[str, dict[str, JsonValue]]:
        """The request body: just what the fake saw."""
        return {"input": self.payload_attrs}

    def send_request(self) -> _FakeResponse:
        """Pretend to submit the task."""
        self.payload_attrs = {
            name: self._kwargs.get(arg)
            for name, arg in (
                ("aspectRatio", "aspect_ratio"),
                ("resolution", "resolution"),
                ("duration", "length"),
                ("generateAudio", "generate_audio"),
            )
            if self._kwargs.get(arg) is not None
        }
        return _FakeResponse({"code": "SUCCESS", "data": {"taskId": "task-1", "status": "waiting"}})


class _FakeAudioGenerator:
    """A Pollo audio generator that records its call and answers with a task id."""

    api_key = "pollo-test"

    def __init__(self, calls: PolloCalls, key: str, attrs: dict[str, JsonValue], **kwargs: JsonValue) -> None:
        calls.generators.append((key, kwargs))
        self.payload_attrs = attrs

    def get_payload(self) -> dict[str, dict[str, JsonValue]]:
        """An empty request body."""
        return {"input": {}}

    def send_request(self) -> _FakeResponse:
        """Pretend to submit the task."""
        return _FakeResponse({"data": {"taskId": "task-1"}})


class _RefusingGenerator:
    """A Pollo generator whose submit always gets ``reply`` back."""

    api_key = "k"

    def __init__(self, reply: _FakeResponse) -> None:
        self._reply = reply
        self.payload_attrs: dict[str, JsonValue] = {}

    def get_payload(self) -> dict[str, dict[str, JsonValue]]:
        """An empty request body."""
        return {"input": {}}

    def send_request(self) -> _FakeResponse:
        """The canned reply."""
        return self._reply


class _InlineThread:
    """A stand-in for ``threading.Thread`` that runs its target as soon as it is started."""

    def __init__(self, target: Callable[..., None], args: Sequence[object] = (), **_kwargs: object) -> None:
        self._target = target
        self._args = args

    def start(self) -> None:
        """Run the target now, on the calling thread."""
        self._target(*self._args)


def _by_id(models: list[ModelEntry]) -> dict[str, ModelEntry]:
    """Index catalogue entries by their ``id``."""
    return {jp.text(m, "id"): m for m in models}


class TestPolloImageModels:
    """Pollo image models in chat. Pollo is fully mocked — nothing here can.

    reach the real API (which would bill credits).
    """

    POLLO: ClassVar = {**SETTINGS, "image_model": "pollo/seedream"}

    @pytest.fixture
    def pollo(self, chat: None, monkeypatch: pytest.MonkeyPatch, provider_keys: dict[str, str | None]) -> PolloCalls:
        """Provide the pollo fixture."""
        provider_keys["pollo"] = "pollo-test"
        monkeypatch.setattr(pollo_provider, "POLL_INTERVAL", 0)
        calls = PolloCalls()

        def make_generator(key: str, **kwargs: JsonValue) -> _FakeGenerator:
            return _FakeGenerator(calls, key, **kwargs)

        def next_statuses(*_args: object, **_kwargs: object) -> list[TaskResult]:
            return next(calls.statuses)

        def download(url: str, timeout: float | None = None, stream: bool = False) -> _FakeResponse:
            _ = (timeout, stream)
            return _FakeResponse(None, b"mp4-bytes" if url.endswith(".mp4") else png_bytes(), "image/jpeg")

        def upload(path: Path, *_args: object, **_kwargs: object) -> str:
            calls.uploads.append(path.name)
            return f"https://tmp.example/{path.name}"

        monkeypatch.setattr(pollo_provider, "get_image_generator", make_generator)
        monkeypatch.setattr(pollo_provider, "get_video_generator", make_generator)
        monkeypatch.setattr(pollo_provider, "get_task_status", next_statuses)
        monkeypatch.setattr(pollo_provider.requests, "get", download)
        monkeypatch.setattr(pollo_provider.image_hosts, "upload_file", upload)
        return calls

    def _draw(
        self,
        client: TestClient,
        conv: ConversationOut,
        chat: None,
        monkeypatch: pytest.MonkeyPatch,
        args: Mapping[str, JsonValue],
        statuses: Sequence[list[TaskResult]],
        pollo: PolloCalls,
    ) -> dict[str, JsonValue]:
        pollo.report(*statuses)
        rounds = iter([tool_chunks("generate_image", args, text="Here you go."), text_chunks("unused")])
        monkeypatch.setattr(openrouter, "stream_chat", stub(lambda: next(rounds)))
        monkeypatch.setattr(openrouter, "generate_image", stub(lambda: pytest.fail("should run on Pollo")))
        return jp.obj(
            sse_events(
                client.post(
                    f"/api/chat/conversations/{conv['id']}/messages",
                    json={"content": "draw", "mode": "auto", **self.POLLO},
                )
            )[-1],
            "message",
        )

    def test_listed_in_the_image_catalogue_when_key_is_set(
        self, chat: None, monkeypatch: pytest.MonkeyPatch, pollo: PolloCalls, provider_keys: dict[str, str | None]
    ) -> None:
        """Test that listed in the image catalogue when key is set."""
        for fn in ("list_text_models", "list_image_models", "list_video_models"):
            monkeypatch.setattr(openrouter, fn, list)
        models = _by_id(chat_catalogue.get_models(refresh=True).get("image", []))
        assert jp.dig(models["pollo/seedream"], "name") == "Pollo: Seedream 5.0 Lite"
        assert jp.dig(models["pollo/seedreampro"], "name") == "Pollo: Seedream 5.0 Pro"
        assert "21:9" in jp.seq(models["pollo/seedream"], "aspect_ratios")
        provider_keys["pollo"] = None
        assert not any(
            jp.text(m, "id").startswith("pollo/") for m in chat_catalogue.get_models(refresh=True).get("image", [])
        )

    def test_tool_call_runs_on_pollo(
        self,
        client: TestClient,
        conv: ConversationOut,
        chat: None,
        monkeypatch: pytest.MonkeyPatch,
        pollo: PolloCalls,
    ) -> None:
        """Test that tool call runs on pollo."""
        msg = self._draw(
            client,
            conv,
            chat,
            monkeypatch,
            {"prompt": "a red fox", "aspect_ratio": "16:9"},
            [[("processing", None, None, None)], [("succeed", None, "https://cdn/x.jpg", 6)]],
            pollo,
        )
        item = jp.rows(msg, "media")[0]
        assert item["status"] == "done"
        assert jp.text(item, "file").endswith(".jpg")
        assert item["credits"] == 6
        assert not item.get("cost")
        assert jp.number(msg, "cost") == pytest.approx(0.003)  # OpenRouter text only — credits aren't dollars
        key, kwargs = pollo.generators[0]
        assert key == "seedream"
        # The model's 16:9 is ignored; composer on auto → no ratio sent (model default)
        assert (kwargs["prompt"], kwargs["aspect_ratio"], kwargs["images"]) == ("a red fox", None, None)

    def test_unsupported_ratio_falls_back_to_model_default(
        self,
        client: TestClient,
        conv: ConversationOut,
        chat: None,
        monkeypatch: pytest.MonkeyPatch,
        pollo: PolloCalls,
    ) -> None:
        """Test that unsupported ratio falls back to model default."""
        self._draw(
            client,
            conv,
            chat,
            monkeypatch,
            {"prompt": "x", "aspect_ratio": "5:4"},
            [[("succeed", None, "https://cdn/x.png", 3)]],
            pollo,
        )
        assert pollo.generators[0][1]["aspect_ratio"] is None

    def test_reference_images_are_uploaded_for_pollo(
        self,
        client: TestClient,
        conv: ConversationOut,
        chat: None,
        db: MetadataDB,
        monkeypatch: pytest.MonkeyPatch,
        pollo: PolloCalls,
    ) -> None:
        """Test that reference images are uploaded for pollo."""
        (chat_pkg.conversation_dir(conv["id"]) / "img_prev.png").write_bytes(png_bytes())
        db.add_chat_message(conv["id"], "user", "a cat")
        db.add_chat_message(
            conv["id"],
            "assistant",
            media=[{"id": "p1", "kind": "image", "source": "generated", "status": "done", "file": "img_prev.png"}],
        )
        self._draw(
            client,
            conv,
            chat,
            monkeypatch,
            {"prompt": "same cat, in a hat", "source_image": "latest"},
            [[("succeed", None, "https://cdn/x.png", 3)]],
            pollo,
        )
        assert pollo.uploads == ["img_prev.png"]
        assert pollo.generators[0][1]["images"] == ["https://tmp.example/img_prev.png"]

    def test_failure_marks_the_item_and_can_be_retried(
        self,
        client: TestClient,
        conv: ConversationOut,
        chat: None,
        db: MetadataDB,
        monkeypatch: pytest.MonkeyPatch,
        pollo: PolloCalls,
    ) -> None:
        """Test that failure marks the item and can be retried."""
        msg = self._draw(
            client,
            conv,
            chat,
            monkeypatch,
            {"prompt": "x"},
            [[("failed", "Content flagged by moderation", None, None)]],
            pollo,
        )
        item = jp.rows(msg, "media")[0]
        assert item["status"] == "error"
        assert item["moderated"] is True
        assert "Pollo" in jp.text(item, "error")

        pollo.report([("succeed", None, "https://cdn/y.png", 3)])
        monkeypatch.setattr(threading, "Thread", _InlineThread)
        client.post(f"/api/chat/messages/{jp.integer(msg, 'id')}/media/{jp.text(item, 'id')}/regenerate", json={})
        fixed = jp.must(db.get_chat_message(jp.integer(msg, "id"))).media[0]
        assert fixed["status"] == "done"
        assert fixed["credits"] == 3

    def test_polling_survives_transient_errors(
        self, chat: None, monkeypatch: pytest.MonkeyPatch, pollo: PolloCalls
    ) -> None:
        """Test that polling survives transient errors."""
        pollo.report(
            [("cloudflare_blocked", "blocked", None, None)],
            [("error", "HTTP 502", None, None)],
            [("succeed", None, "https://cdn/x.png", 2)],
        )
        images, credit_cost, _sent = pollo_provider.generate_image("pollo/nanobanana2", "x")
        assert len(images) == 1
        assert credit_cost == 2

    # ── video ──
    VIDEO: ClassVar = {**SETTINGS, "video_model": "pollo/seedance20fast"}

    def test_video_models_listed_without_deprecated_ones(
        self, chat: None, monkeypatch: pytest.MonkeyPatch, pollo: PolloCalls
    ) -> None:
        """Test that video models listed without deprecated ones."""
        for fn in ("list_text_models", "list_image_models", "list_video_models"):
            monkeypatch.setattr(openrouter, fn, list)
        models = _by_id(chat_catalogue.get_models(refresh=True).get("video", []))
        fast = models["pollo/seedance20fast"]
        assert fast["name"] == "Pollo: Seedance 2.0 Fast"
        assert fast["durations"] == list(range(4, 16))
        assert fast["resolutions"] == ["480p", "720p"]
        assert fast["frame_images"] == ["first_frame"]
        assert fast["generate_audio"] is True
        assert "pollo/wan27" not in models  # marked deprecated on the Generate page

    def test_video_mode_submits_to_pollo_with_first_frame(
        self,
        client: TestClient,
        conv: ConversationOut,
        chat: None,
        monkeypatch: pytest.MonkeyPatch,
        pollo: PolloCalls,
    ) -> None:
        """Test that video mode submits to pollo with first frame."""
        monkeypatch.setattr(openrouter, "submit_video", stub(lambda: pytest.fail("should run on Pollo")))
        chat_catalogue.seed_models(
            {"video": [{"id": "pollo/seedance20fast", "durations": list(range(4, 16))}]}, stale=True
        )
        up = jp.text(
            client.post(
                f"/api/chat/conversations/{conv['id']}/attachments",
                files={"file": ("a.png", png_bytes(), "image/png")},
            ),
            "file",
        )
        msg = jp.obj(
            sse_events(
                client.post(
                    f"/api/chat/conversations/{conv['id']}/messages",
                    json={
                        "content": "make it move",
                        "attachments": [up],
                        "mode": "video",
                        **self.VIDEO,
                        "video_options": {"duration": 20, "aspect_ratio": "9:16", "generate_audio": False},
                    },
                )
            )[-1],
            "message",
        )
        item = jp.rows(msg, "media")[0]
        assert item["status"] == "pending"
        assert item["job_id"] == "pollo:task-1"
        key, kwargs = pollo.generators[0]
        assert key == "seedance20fast"
        assert pollo.uploads == [up]
        assert kwargs["image_url"] == f"https://tmp.example/{up}"
        assert (kwargs["prompt"], kwargs["length"], kwargs["generate_audio"]) == ("make it move", 15, False)
        assert kwargs["aspect_ratio"] == "9:16"  # picked in the composer, so it wins over the image's shape

    def test_auto_length_is_remembered_on_the_media_item(
        self,
        client: TestClient,
        conv: ConversationOut,
        chat: None,
        monkeypatch: pytest.MonkeyPatch,
        pollo: PolloCalls,
    ) -> None:
        """The composer resolves Auto to a number before sending, so the item.

        records that it *was* Auto — otherwise reusing its settings would pin
        whatever Auto worked out to.
        """
        monkeypatch.setattr(openrouter, "submit_video", stub(lambda: pytest.fail("should run on Pollo")))
        chat_catalogue.seed_models(
            {"video": [{"id": "pollo/seedance20fast", "durations": list(range(4, 16))}]}, stale=True
        )
        up = jp.text(
            client.post(
                f"/api/chat/conversations/{conv['id']}/attachments",
                files={"file": ("a.png", png_bytes(), "image/png")},
            ),
            "file",
        )

        def send(video_options: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
            return jp.rows(
                sse_events(
                    client.post(
                        f"/api/chat/conversations/{conv['id']}/messages",
                        json={
                            "content": "make it move",
                            "attachments": [up],
                            "mode": "video",
                            **self.VIDEO,
                            "video_options": video_options,
                        },
                    )
                )[-1],
                "message",
                "media",
            )[0]

        auto = send({"duration": 10, "duration_auto": True})
        assert jp.dig(auto, "params", "duration") == 10
        assert jp.dig(auto, "params", "duration_auto") is True
        picked = send({"duration": 10})
        assert jp.dig(picked, "params", "duration") == 10
        assert jp.dig(picked, "params", "duration_auto") is False
        # Either way Pollo is sent the resolved length, not the flag
        assert all("duration_auto" not in kwargs for _, kwargs in pollo.generators)

    # ── audio ──
    AUDIO: ClassVar = {**SETTINGS, "audio_model": "pollo/elevenv3"}

    def test_audio_models_listed_with_their_type(
        self, chat: None, monkeypatch: pytest.MonkeyPatch, pollo: PolloCalls
    ) -> None:
        """Test that audio models listed with their type."""
        for fn in ("list_text_models", "list_image_models", "list_video_models"):
            monkeypatch.setattr(openrouter, fn, list)
        models = _by_id(chat_catalogue.get_models(refresh=True).get("audio", []))
        assert models["pollo/elevenv3"]["tags"] == ["tts"]
        assert models["pollo/elevenv3"]["options"] == ["voice"]
        assert models["pollo/sunov55"]["tags"] == ["music"]

    def test_audio_mode_submits_speech_with_the_picked_voice(
        self,
        client: TestClient,
        conv: ConversationOut,
        chat: None,
        monkeypatch: pytest.MonkeyPatch,
        pollo: PolloCalls,
    ) -> None:
        """Test that audio mode submits speech with the picked voice."""
        self._fake_audio_generator(monkeypatch, chat, pollo, {"prompt": "hello", "voiceId": "v1"})
        msg = jp.obj(
            sse_events(
                client.post(
                    f"/api/chat/conversations/{conv['id']}/messages",
                    json={"content": "hello", "mode": "audio", **self.AUDIO, "audio_options": {"voice": "v1"}},
                )
            )[-1],
            "message",
        )
        item = jp.rows(msg, "media")[0]
        assert item["kind"] == "audio"
        assert item["status"] == "pending"
        assert item["job_id"] == "pollo:task-1"
        key, kwargs = pollo.generators[0]
        assert key == "elevenv3"
        assert kwargs["prompt"] == "hello"
        assert kwargs["voice"] == "v1"
        # the picks are remembered with the conversation's composer settings
        settings = client.get(f"/api/chat/conversations/{conv['id']}")
        assert jp.dig(settings, "conversation", "settings", "audio_model") == "pollo/elevenv3"
        assert jp.dig(settings, "conversation", "settings", "audio_options", "voice") == "v1"

    def _fake_audio_generator(
        self, monkeypatch: pytest.MonkeyPatch, chat: None, pollo: PolloCalls, attrs: dict[str, JsonValue]
    ) -> None:
        def make_generator(key: str, **kwargs: JsonValue) -> _FakeAudioGenerator:
            return _FakeAudioGenerator(pollo, key, attrs, **kwargs)

        monkeypatch.setattr(pollo_provider, "get_audio_generator", make_generator)
        monkeypatch.setattr(chat_polling, "start_video_poller", stub(lambda: None))

    def test_auto_mode_chat_model_can_call_generate_audio(
        self,
        client: TestClient,
        conv: ConversationOut,
        chat: None,
        monkeypatch: pytest.MonkeyPatch,
        pollo: PolloCalls,
    ) -> None:
        """Test that auto mode chat model can call generate audio."""
        self._fake_audio_generator(monkeypatch, chat, pollo, {"prompt": "x"})
        rounds = iter([tool_chunks("generate_audio", {"prompt": "Hello there"}, text="On it."), text_chunks("x")])
        monkeypatch.setattr(openrouter, "stream_chat", stub(lambda: next(rounds)))
        msg = jp.obj(
            sse_events(
                client.post(
                    f"/api/chat/conversations/{conv['id']}/messages",
                    json={"content": "say hello", "mode": "auto", **self.AUDIO, "audio_options": {"voice": "v1"}},
                )
            )[-1],
            "message",
        )
        assert jp.dig(msg, "media", 0, "kind") == "audio"
        assert jp.dig(msg, "media", 0, "job_id") == "pollo:task-1"
        assert pollo.generators[0][1]["prompt"] == "Hello there"

    def test_audio_estimate_prices_by_the_text(
        self, client: TestClient, chat: None, monkeypatch: pytest.MonkeyPatch, pollo: PolloCalls
    ) -> None:
        """Test that audio estimate prices by the text."""
        kinds: list[str] = []
        arg_lists: list[tuple[JsonValue, ...]] = []

        def fake(model: str, kind: str, *args: JsonValue) -> dict[str, JsonValue]:
            _ = model
            kinds.append(kind)
            arg_lists.append(args)
            return {"credits": 3}

        monkeypatch.setattr(pollo_provider, "estimate_cost", fake)
        r = client.post(
            "/api/chat/estimate",
            json={"model": "pollo/elevenv3", "kind": "audio", "prompt": "hi", "audio_options": {"voice": "v1"}},
        )
        assert jp.decode(r) == {"estimate": {"credits": 3}}
        assert kinds[-1] == "audio"
        assert arg_lists[-1][-2:] == ("hi", {"voice": "v1"})

    def test_a_tool_needs_no_prompt_but_an_image(
        self,
        client: TestClient,
        conv: ConversationOut,
        chat: None,
        monkeypatch: pytest.MonkeyPatch,
        pollo: PolloCalls,
    ) -> None:
        """Test that a tool needs no prompt but an image."""
        chat_catalogue.seed_models(
            {
                "image": [
                    {"id": "pollo/imageupscale", "name": "Pollo: Image Upscale", "tool": "upscale", "no_prompt": True}
                ]
            },
            stale=True,
        )
        body = {"content": "", "mode": "image", **SETTINGS, "image_model": "pollo/imageupscale"}
        r = client.post(f"/api/chat/conversations/{conv['id']}/messages", json=body)
        assert r.status_code == 200  # an empty message is fine for a tool…
        assert "needs an image" in jp.text(sse_events(r)[-1], "message", "error")  # …but it must have an image

    def test_poller_keeps_the_result_extension(
        self,
        chat: None,
        db: MetadataDB,
        conv: ConversationOut,
        monkeypatch: pytest.MonkeyPatch,
        pollo: PolloCalls,
    ) -> None:
        """Test that poller keeps the result extension."""
        msg = db.add_chat_message(
            conv["id"],
            "assistant",
            media=[{"id": "pt1", "kind": "video", "source": "generated", "status": "pending", "job_id": "pollo:t-6"}],
        )
        pollo.report(
            [("succeed", None, "https://cdn/cut.webm?sig=1", 2)], [("succeed", None, "https://cdn/cut.webm?sig=1", 2)]
        )
        chat_polling.poll_video(conv["id"], msg.id, "pt1", "pollo:t-6")
        assert jp.text(jp.must(db.get_chat_message(msg.id)).media[0], "file").endswith(".webm")

    def test_audio_mode_needs_a_prompt_and_a_model(
        self,
        client: TestClient,
        conv: ConversationOut,
        chat: None,
        monkeypatch: pytest.MonkeyPatch,
        pollo: PolloCalls,
    ) -> None:
        """Test that audio mode needs a prompt and a model."""
        msgs = sse_events(
            client.post(
                f"/api/chat/conversations/{conv['id']}/messages",
                json={"content": "hi", "mode": "audio", **SETTINGS},
            )
        )
        assert "No audio model" in jp.text(msgs[-1], "message", "error")

    def _video_from_image(
        self,
        client: TestClient,
        conv: ConversationOut,
        chat: None,
        size: tuple[int, int],
        model: str,
        **extra: JsonValue,
    ) -> None:
        up = jp.text(
            client.post(
                f"/api/chat/conversations/{conv['id']}/attachments",
                files={"file": ("a.png", png_bytes(size), "image/png")},
            ),
            "file",
        )
        sse_events(
            client.post(
                f"/api/chat/conversations/{conv['id']}/messages",
                json={
                    "content": "animate",
                    "attachments": [up],
                    "mode": "video",
                    **SETTINGS,
                    "video_model": model,
                    **extra,
                },
            )
        )

    def test_first_frame_sets_the_ratio_when_none_is_picked(
        self,
        client: TestClient,
        conv: ConversationOut,
        chat: None,
        monkeypatch: pytest.MonkeyPatch,
        pollo: PolloCalls,
    ) -> None:
        """Test that first frame sets the ratio when none is picked."""
        self._video_from_image(client, conv, chat, (60, 80), "pollo/seedance20fast")  # 3:4 photo
        assert pollo.generators[0][1]["aspect_ratio"] == "3:4"

    def test_follow_image_ratio_preferred_when_the_model_has_one(
        self,
        client: TestClient,
        conv: ConversationOut,
        chat: None,
        monkeypatch: pytest.MonkeyPatch,
        pollo: PolloCalls,
    ) -> None:
        """Test that follow image ratio preferred when the model has one."""
        self._video_from_image(client, conv, chat, (60, 80), "pollo/seedance25")
        assert pollo.generators[0][1]["aspect_ratio"] == "adaptive"

    def test_animating_ignores_the_chat_models_ratio_guess(
        self,
        client: TestClient,
        conv: ConversationOut,
        chat: None,
        db: MetadataDB,
        monkeypatch: pytest.MonkeyPatch,
        pollo: PolloCalls,
    ) -> None:
        """Test that animating ignores the chat models ratio guess."""
        (chat_pkg.conversation_dir(conv["id"]) / "img_prev.png").write_bytes(png_bytes((60, 80)))
        db.add_chat_message(conv["id"], "user", "a cat")
        db.add_chat_message(
            conv["id"],
            "assistant",
            media=[{"id": "p1", "kind": "image", "source": "generated", "status": "done", "file": "img_prev.png"}],
        )
        rounds = iter(
            [
                tool_chunks(
                    "generate_video",
                    {"prompt": "it walks", "aspect_ratio": "9:16", "source_image": "latest"},
                    text="Rolling.",
                ),
                text_chunks("x"),
            ]
        )
        monkeypatch.setattr(openrouter, "stream_chat", stub(lambda: next(rounds)))
        sse_events(
            client.post(
                f"/api/chat/conversations/{conv['id']}/messages",
                json={"content": "animate it", "mode": "auto", **self.VIDEO},
            )
        )
        assert pollo.generators[0][1]["aspect_ratio"] == "3:4"

    def test_poller_finishes_a_pollo_video(
        self,
        chat: None,
        db: MetadataDB,
        conv: ConversationOut,
        monkeypatch: pytest.MonkeyPatch,
        pollo: PolloCalls,
    ) -> None:
        """Test that poller finishes a pollo video."""
        monkeypatch.setattr(openrouter, "get_video", stub(lambda: pytest.fail("should ask Pollo")))
        msg = db.add_chat_message(
            conv["id"],
            "assistant",
            media=[
                {"id": "pv1", "kind": "video", "source": "generated", "status": "pending", "job_id": "pollo:task-9"}
            ],
        )
        pollo.report(
            [("processing", None, None, None)],
            [("cloudflare_blocked", "blocked", None, None)],
            [("succeed", None, "https://cdn/v.mp4", 40)],
            [("succeed", None, "https://cdn/v.mp4", 40)],
        )  # re-read for the download
        chat_polling.poll_video(conv["id"], msg.id, "pv1", "pollo:task-9")
        item = jp.must(db.get_chat_message(msg.id)).media[0]
        assert item["status"] == "done"
        assert item["credits"] == 40
        assert not item.get("cost")
        assert (chat_helpers.chat_root() / conv["id"] / jp.text(item, "file")).read_bytes() == b"mp4-bytes"

    def test_poller_saves_a_pollo_audio_job_as_mp3(
        self,
        chat: None,
        db: MetadataDB,
        conv: ConversationOut,
        monkeypatch: pytest.MonkeyPatch,
        pollo: PolloCalls,
    ) -> None:
        """Test that poller saves a pollo audio job as mp3."""
        msg = db.add_chat_message(
            conv["id"],
            "assistant",
            media=[{"id": "pa1", "kind": "audio", "source": "generated", "status": "pending", "job_id": "pollo:t-5"}],
        )
        pollo.report([("succeed", None, "https://cdn/a.mp3", 3)], [("succeed", None, "https://cdn/a.mp3", 3)])
        chat_polling.poll_video(conv["id"], msg.id, "pa1", "pollo:t-5")
        item = jp.must(db.get_chat_message(msg.id)).media[0]
        assert item["status"] == "done"
        assert jp.text(item, "file").endswith(".mp3")
        assert item["credits"] == 3

    def test_failed_pollo_video_marks_the_item(
        self,
        chat: None,
        db: MetadataDB,
        conv: ConversationOut,
        monkeypatch: pytest.MonkeyPatch,
        pollo: PolloCalls,
    ) -> None:
        """Test that failed pollo video marks the item."""
        msg = db.add_chat_message(
            conv["id"],
            "assistant",
            media=[
                {"id": "pv2", "kind": "video", "source": "generated", "status": "pending", "job_id": "pollo:task-8"}
            ],
        )
        pollo.report([("failed", "Your prompt violates our content policy", None, None)])
        chat_polling.poll_video(conv["id"], msg.id, "pv2", "pollo:task-8")
        item = jp.must(db.get_chat_message(msg.id)).media[0]
        assert item["status"] == "error"
        assert item["moderated"] is True
        assert jp.text(item, "error").startswith("Pollo:")

    def test_a_failure_records_no_credits_and_shows_the_verdict(
        self, chat: None, db: MetadataDB, conv: ConversationOut, pollo: PolloCalls
    ) -> None:
        """A failed job isn't billed, even though Pollo reports its price.

        with the verdict — so no credits land on the item or in spend — and the
        stored response is the verdict, not the "accepted" reply from submitting.
        """
        msg = db.add_chat_message(
            conv["id"],
            "assistant",
            media=[
                {
                    "id": "pv3",
                    "kind": "video",
                    "source": "generated",
                    "status": "pending",
                    "job_id": "pollo:task-11",
                    "response": {"code": "SUCCESS", "data": {"status": "waiting"}},
                }
            ],
        )
        pollo.report([("failed", "InvalidParameter Invalid video_url.", None, 61)])
        chat_polling.poll_video(conv["id"], msg.id, "pv3", "pollo:task-11")
        item = jp.must(db.get_chat_message(msg.id)).media[0]
        assert item["status"] == "error"
        assert item.get("credits") is None
        assert jp.dig(item, "response", "generations", 0, "failMsg") == "InvalidParameter Invalid video_url."
        assert db.spend_rows([conv["id"]]) == []

    def test_kling_and_qwen_models_offered_in_chat(
        self, chat: None, monkeypatch: pytest.MonkeyPatch, pollo: PolloCalls
    ) -> None:
        """Test that kling and qwen models offered in chat."""
        for fn in ("list_text_models", "list_image_models", "list_video_models"):
            monkeypatch.setattr(openrouter, fn, list)
        data = chat_catalogue.get_models(refresh=True)
        images = _by_id(data.get("image", []))
        videos = _by_id(data.get("video", []))
        assert images["pollo/qwenimage3pro"]["input_modalities"] == ["text", "image"]
        assert images["pollo/qwenimageflash"]["input_modalities"] == ["text"]  # no reference images
        assert videos["pollo/klingv3"]["resolutions"] == ["std", "pro", "4K"]
        assert videos["pollo/klingv3"]["durations"] == list(range(3, 16))

    def test_image_only_kling_without_an_image_fails_on_the_card(
        self,
        client: TestClient,
        conv: ConversationOut,
        chat: None,
        db: MetadataDB,
        monkeypatch: pytest.MonkeyPatch,
        pollo: PolloCalls,
    ) -> None:
        """Test that image only kling without an image fails on the card."""
        monkeypatch.setattr(pollo_provider, "get_video_generator", registry.video_generator)  # the real one
        msg = jp.obj(
            sse_events(
                client.post(
                    f"/api/chat/conversations/{conv['id']}/messages",
                    json={"content": "a fox running", "mode": "video", **SETTINGS, "video_model": "pollo/klingv21"},
                )
            )[-1],
            "message",
        )
        item = jp.rows(msg, "media")[0]
        assert item["status"] == "error"
        assert "needs a source image" in jp.text(item, "error")

    def test_auto_mode_uses_composer_video_settings_and_records_what_was_sent(
        self,
        client: TestClient,
        conv: ConversationOut,
        chat: None,
        monkeypatch: pytest.MonkeyPatch,
        pollo: PolloCalls,
    ) -> None:
        """Test that auto mode uses composer video settings and records what was sent."""
        chat_catalogue.seed_models(
            {
                "video": [
                    {"id": "pollo/seedance20fast", "durations": list(range(4, 16)), "resolutions": ["480p", "720p"]}
                ]
            },
            stale=True,
        )
        rounds = iter(
            [tool_chunks("generate_video", {"prompt": "waves", "duration": 6}, text="Rolling."), text_chunks("x")]
        )
        monkeypatch.setattr(openrouter, "stream_chat", stub(lambda: next(rounds)))
        msg = jp.obj(
            sse_events(
                client.post(
                    f"/api/chat/conversations/{conv['id']}/messages",
                    json={
                        "content": "make a video of waves",
                        "mode": "auto",
                        **self.VIDEO,
                        "video_options": {"resolution": "720p", "aspect_ratio": "16:9"},
                    },
                )
            )[-1],
            "message",
        )
        kwargs = pollo.generators[0][1]
        # composer picks apply in Auto; the chat model's duration fills the gap
        assert (kwargs["resolution"], kwargs["aspect_ratio"], kwargs["length"]) == ("720p", "16:9", 6)
        params = jp.obj(msg, "media", 0, "params")
        assert (params["resolution"], params["aspect_ratio"], params["duration"]) == ("720p", "16:9", 6)

    def test_model_pollo_doesnt_serve_explains_itself(
        self,
        client: TestClient,
        conv: ConversationOut,
        chat: None,
        monkeypatch: pytest.MonkeyPatch,
        pollo: PolloCalls,
    ) -> None:
        """Test that model pollo doesnt serve explains itself."""
        not_served = _FakeResponse(
            {"message": "Not found", "code": "NOT_FOUND", "errorCode": "REJECTED"}, status_code=404
        )
        monkeypatch.setattr(pollo_provider, "get_image_generator", stub(lambda: _RefusingGenerator(not_served)))
        monkeypatch.setattr(openrouter, "stream_chat", stub(lambda: pytest.fail("no LLM in image mode")))
        msg = jp.obj(
            sse_events(
                client.post(
                    f"/api/chat/conversations/{conv['id']}/messages",
                    json={"content": "a fox", "mode": "image", **SETTINGS, "image_model": "pollo/qwenimage3pro"},
                )
            )[-1],
            "message",
        )
        assert "isn't available to your API key" in jp.text(msg, "media", 0, "error")

    def test_pollo_not_enabled_is_not_called_moderation(
        self,
        client: TestClient,
        conv: ConversationOut,
        chat: None,
        monkeypatch: pytest.MonkeyPatch,
        pollo: PolloCalls,
    ) -> None:
        """Pollo answers 403 for "not enabled for API access" — that's not a content block."""
        refused = _FakeResponse(
            {"message": "This model is not enabled for API access.", "code": "FORBIDDEN"}, status_code=403
        )
        monkeypatch.setattr(pollo_provider, "get_image_generator", stub(lambda: _RefusingGenerator(refused)))
        monkeypatch.setattr(openrouter, "stream_chat", stub(lambda: pytest.fail("no LLM in image mode")))
        msg = jp.obj(
            sse_events(
                client.post(
                    f"/api/chat/conversations/{conv['id']}/messages",
                    json={"content": "a gym", "mode": "image", **SETTINGS, "image_model": "pollo/seedreampro"},
                )
            )[-1],
            "message",
        )
        item = jp.rows(msg, "media")[0]
        assert item["error"] == "Pollo: This model is not enabled for API access."
        assert item["moderated"] is False

    def test_pollo_content_rejection_is_still_moderation(self, chat: None) -> None:
        """Test that pollo content rejection is still moderation."""
        is_mod = chat_generation.is_moderation_error
        assert is_mod(pollo_provider.PolloError("Pollo: prompt flagged as sensitive content", 400))
        assert is_mod(openrouter.OpenRouterError("Forbidden", 403))  # OpenRouter's 403 still counts

    def test_models_not_enabled_for_the_key_are_flagged_hidden(
        self, chat: None, monkeypatch: pytest.MonkeyPatch, pollo: PolloCalls
    ) -> None:
        """Test that models not enabled for the key are flagged hidden."""
        for fn in ("list_text_models", "list_image_models", "list_video_models"):
            monkeypatch.setattr(openrouter, fn, list)
        images = _by_id(chat_catalogue.get_models(refresh=True).get("image", []))
        hidden = {k for k, m in images.items() if m["hidden"]}
        assert hidden == {"pollo/qwenimageflash"}
        # `hidden` carries the reason, shown in the picker behind "Show hidden"
        assert "unavailable" in jp.text(images["pollo/qwenimageflash"], "hidden")
        assert images["pollo/qwenimage3"]["hidden"] is None  # works since its address was fixed
        assert images["pollo/klingv3image"]["hidden"] is None  # confirmed working


class TestOpenRouterConnection:
    """Tests for open router connection."""

    def test_connections_use_tcp_keepalive(self, chat: None) -> None:
        """Test that connections use tcp keepalive."""
        opts = openrouter.keepalive_socket_options()
        assert (socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1) in opts
        if hasattr(socket, "TCP_KEEPIDLE"):
            assert (socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 5) in opts

    def test_dropped_connection_fails_the_card_with_an_explanation(
        self, client: TestClient, conv: ConversationOut, chat: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """httpx.RemoteProtocolError used to escape as a raw error and leave the image pending."""

        def drop(*_args: object, **_kwargs: object) -> None:
            raise server_disconnected()

        monkeypatch.setattr(openrouter.http_client, "stream", drop)
        monkeypatch.setattr(openrouter, "stream_chat", stub(lambda: pytest.fail("no LLM in image mode")))
        msg = jp.obj(
            sse_events(
                client.post(
                    f"/api/chat/conversations/{conv['id']}/messages",
                    json={"content": "a fox", "mode": "image", **SETTINGS},
                )
            )[-1],
            "message",
        )
        item = jp.rows(msg, "media")[0]
        assert item["status"] == "error"
        assert item["moderated"] is False
        assert "connection to OpenRouter dropped after" in jp.text(item, "error")
        assert "RemoteProtocolError" in jp.text(item, "error")


class TestOpenRouterImageStream:
    """/images is streamed so the connection isn't silent while the image renders."""

    class _Stream:
        def __init__(
            self,
            lines: list[str],
            content_type: str = "text/event-stream",
            status: int = 200,
            body: JsonValue = None,
        ) -> None:
            self.lines = lines
            self.status_code = status
            self._body = body
            self.headers = {"content-type": content_type}

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_exc: object) -> bool:
            return False

        def iter_lines(self) -> Iterator[str]:
            yield from self.lines

        def read(self) -> bytes:
            return b""

        def json(self) -> JsonValue:
            return self._body

    def _b64(self, color: str = "red") -> str:
        return base64.b64encode(png_bytes(color=color)).decode()

    def test_keeps_only_completed_images_and_cost(self, chat: None, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that keeps only completed images and cost."""
        sent: dict[str, JsonValue] = {}
        lines = [
            ": OPENROUTER PROCESSING",
            "",
            "event: image_generation.partial_image",
            "data: " + json.dumps({"type": "image_generation.partial_image", "b64_json": self._b64("blue")}),
            "",
            ": OPENROUTER PROCESSING",
            "",
            "event: image_generation.completed",
            "data: "
            + json.dumps({"type": "image_generation.completed", "b64_json": self._b64(), "usage": {"cost": 0.03}}),
            "",
            "data: [DONE]",
        ]

        def fake_stream(method: str, url: str, **kwargs: JsonValue) -> TestOpenRouterImageStream._Stream:
            _ = (method, url)
            sent.update(jp.obj(kwargs, "json"))
            return self._Stream(lines)

        monkeypatch.setattr(openrouter.http_client, "stream", fake_stream)
        images, cost = openrouter.generate_image("x/img", "a fox")
        assert sent["stream"] is True
        assert images == [(png_bytes(), "image/png")]
        assert cost == 0.03

    def test_logs_the_request_and_the_card_keeps_it(
        self, client: TestClient, conv: ConversationOut, chat: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that logs the request and the card keeps it."""
        lines = ["event: error", "data: " + json.dumps({"error": {"message": "flagged by moderation"}}), ""]
        monkeypatch.setattr(openrouter.http_client, "stream", stub(lambda: self._Stream(lines)))
        ev = sse_events(
            client.post(
                f"/api/chat/conversations/{conv['id']}/messages",
                json={"content": "a fox", **SETTINGS, "mode": "image"},
            )
        )
        item = jp.obj(ev[-1], "message", "media", 0)
        [entry] = [e for e in request_log.recent() if e["path"] == "/images"]
        assert entry["provider"] == "openrouter"
        assert entry["model"] == "i/model"
        assert entry["status"] == 200
        error = entry["error"]
        assert isinstance(error, str)
        assert "flagged" in error
        assert item["request"] == entry["request"]
        assert jp.dig(item, "request", "prompt") == "a fox"

    def test_reference_images_are_cut_short_in_the_log(self, chat: None, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that reference images are cut short in the log."""
        lines = ["event: image_generation.completed", "data: " + json.dumps({"b64_json": self._b64()}), ""]
        monkeypatch.setattr(openrouter.http_client, "stream", stub(lambda: self._Stream(lines)))
        request_log.forget_last()
        openrouter.generate_image("x/img", "a fox", input_images=["data:image/png;base64," + "A" * 4096])
        last = request_log.take_last()
        assert last is not None
        assert last["response"] == {"images": ["image/png"], "cost": None}
        assert isinstance(last.get("request"), dict)
        refs = jp.dig(last, "request", "input_references")
        assert refs == [{"type": "image_url", "image_url": {"url": "data:image/png;base64,… (3 KB)"}}]

    def test_event_name_alone_identifies_the_final_image(self, chat: None, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that event name alone identifies the final image."""
        lines = ["event: image_generation.completed", "data: " + json.dumps({"b64_json": self._b64()}), ""]
        monkeypatch.setattr(openrouter.http_client, "stream", stub(lambda: self._Stream(lines)))
        images, _ = openrouter.generate_image("x/img", "a fox")
        assert len(images) == 1

    def test_error_event_raises(self, chat: None, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that error event raises."""
        lines = ["event: error", "data: " + json.dumps({"error": {"message": "flagged by moderation"}}), ""]
        monkeypatch.setattr(openrouter.http_client, "stream", stub(lambda: self._Stream(lines)))
        with pytest.raises(openrouter.OpenRouterError, match="flagged"):
            openrouter.generate_image("x/img", "a fox")

    def test_plain_json_answer_still_works(self, chat: None, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that plain json answer still works."""
        body = {"data": [{"b64_json": self._b64(), "media_type": "image/png"}], "usage": {"cost": 0.01}}
        monkeypatch.setattr(
            openrouter.http_client,
            "stream",
            stub(lambda: self._Stream([], content_type="application/json", body=body)),
        )
        images, cost = openrouter.generate_image("x/img", "a fox")
        assert len(images) == 1
        assert cost == 0.01

    def test_stream_without_an_image_raises(self, chat: None, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that stream without an image raises."""
        monkeypatch.setattr(openrouter.http_client, "stream", stub(lambda: self._Stream(["data: [DONE]"])))
        with pytest.raises(openrouter.OpenRouterError, match="no images"):
            openrouter.generate_image("x/img", "a fox")


class TestDeleteExchange:
    """Tests for delete exchange."""

    def _chat(
        self, db: MetadataDB, conv: ConversationOut
    ) -> tuple[ChatMessage, ChatMessage, ChatMessage, ChatMessage, ChatMessage, ChatMessage]:
        u1 = db.add_chat_message(conv["id"], "user", "draw a fox")
        a1 = db.add_chat_message(
            conv["id"],
            "assistant",
            "Here!",
            media=[
                {
                    "id": "f1",
                    "kind": "image",
                    "source": "generated",
                    "status": "done",
                    "file": "fox.png",
                    "prompt": "fox",
                }
            ],
        )
        u2 = db.add_chat_message(conv["id"], "user", "now a cat", parent_id=a1.id)
        a2 = db.add_chat_message(
            conv["id"],
            "assistant",
            "Meow",
            parent_id=u2.id,
            media=[
                {
                    "id": "c1",
                    "kind": "image",
                    "source": "generated",
                    "status": "done",
                    "file": "cat.png",
                    "prompt": "cat",
                }
            ],
        )
        u3 = db.add_chat_message(conv["id"], "user", "thanks", parent_id=a2.id)
        a3 = db.add_chat_message(conv["id"], "assistant", "Welcome", parent_id=u3.id)
        return u1, a1, u2, a2, u3, a3

    def test_removes_prompt_and_reply_and_rejoins_the_chat(
        self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that removes prompt and reply and rejoins the chat."""
        _u1, _a1, u2, _a2, _u3, _a3 = self._chat(db, conv)
        r = client.delete(f"/api/chat/messages/{u2.id}")
        assert r.status_code == 200
        assert [jp.dig(m, "content") for m in jp.rows(r, "messages")] == ["draw a fox", "Here!", "thanks", "Welcome"]
        # The models no longer see it
        seen: list[list[dict[str, JsonValue]]] = []

        def fake_stream_chat(
            model: str,
            messages: list[dict[str, JsonValue]],
            tools: list[dict[str, JsonValue]] | None = None,
            session_id: str | None = None,
            **_kwargs: object,
        ) -> Iterator[ChatChunk]:
            _ = (model, tools, session_id)
            seen.append(messages)
            return text_chunks("ok")

        monkeypatch.setattr(openrouter, "stream_chat", fake_stream_chat)
        sse_events(client.post(f"/api/chat/conversations/{conv['id']}/messages", json={"content": "more", **SETTINGS}))
        assert "now a cat" not in json.dumps(seen[-1])
        assert "Meow" not in json.dumps(seen[-1])
        # Its image is kept, in the library
        lib = jp.rows(client.get("/api/chat/library"), "items")
        cat = next(i for i in lib if i["id"] == "c1")
        assert cat["attached"] is False
        assert cat["file"] == "cat.png"

    def test_whole_turn_goes_and_only_the_shown_continuation_stays(
        self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB
    ) -> None:
        """Test that whole turn goes and only the shown continuation stays."""
        u1, a1, u2, _a2, u3, a3 = self._chat(db, conv)
        # Another reply version, an edited prompt version, each with follow-ups
        retry = db.add_chat_message(
            conv["id"],
            "assistant",
            "Purr",
            parent_id=u2.id,
            media=[
                {"id": "r1", "kind": "image", "source": "generated", "status": "done", "file": "r.png", "prompt": "r"}
            ],
        )
        db.add_chat_message(conv["id"], "user", "on the retry branch", parent_id=retry.id)
        edit = db.add_chat_message(conv["id"], "user", "now a dog", parent_id=a1.id)
        edit_reply = db.add_chat_message(conv["id"], "assistant", "Woof", parent_id=edit.id)
        db.add_chat_message(conv["id"], "user", "on the edit branch", parent_id=edit_reply.id)
        db.set_chat_leaf(conv["id"], a3.id)  # looking at the original version

        info = client.get(f"/api/chat/messages/{u2.id}/delete-info")
        # Both generated images go with the turn, so the confirmation can name them
        assert jp.decode(info) == {"other_versions": 1, "other_messages": 2, "media": {"image": 2}}

        msgs = jp.rows(client.delete(f"/api/chat/messages/{u2.id}"), "messages")
        assert [m["content"] for m in msgs] == ["draw a fox", "Here!", "thanks", "Welcome"]
        ids = {m.id for m in db.get_chat_messages(conv["id"])}
        assert ids == {u1.id, a1.id, u3.id, a3.id}
        assert jp.must(db.get_chat_message(u3.id)).parent_id == a1.id
        assert jp.dig(client.get(f"/api/chat/messages/{u3.id}"), "siblings") == [u3.id]  # no stray versions
        lib = {jp.text(i, "id") for i in jp.rows(client.get("/api/chat/library"), "items") if not i["attached"]}
        assert {"c1", "r1"} <= lib

    def test_shown_branch_decides_what_stays(self, client: TestClient, conv: ConversationOut, db: MetadataDB) -> None:
        """Test that shown branch decides what stays."""
        _u1, a1, _u2, _a2, _u3, _a3 = self._chat(db, conv)
        edit = db.add_chat_message(conv["id"], "user", "now a dog", parent_id=a1.id)
        edit_reply = db.add_chat_message(conv["id"], "assistant", "Woof", parent_id=edit.id)
        edit_next = db.add_chat_message(conv["id"], "user", "walkies", parent_id=edit_reply.id)
        db.set_chat_leaf(conv["id"], edit_next.id)  # looking at the edited version
        msgs = jp.rows(client.delete(f"/api/chat/messages/{edit.id}"), "messages")
        assert [m["content"] for m in msgs] == ["draw a fox", "Here!", "walkies"]

    def test_info_is_quiet_without_other_versions(
        self, client: TestClient, conv: ConversationOut, db: MetadataDB
    ) -> None:
        """Test that info is quiet without other versions."""
        _u1, _a1, u2, *_ = self._chat(db, conv)
        assert jp.decode(client.get(f"/api/chat/messages/{u2.id}/delete-info")) == {
            "other_versions": 0,
            "other_messages": 0,
            "media": {"image": 1},
        }

    def test_info_counts_no_media_when_the_generation_failed(
        self, client: TestClient, conv: ConversationOut, db: MetadataDB
    ) -> None:
        """Test that info counts no media when the generation failed."""
        u = db.add_chat_message(conv["id"], "user", "make a video")
        db.add_chat_message(
            conv["id"],
            "assistant",
            "",
            parent_id=u.id,
            media=[{"id": "f1", "kind": "video", "source": "generated", "status": "error", "error": "nope"}],
        )
        info = client.get(f"/api/chat/messages/{u.id}/delete-info")
        assert jp.dig(info, "media") == {}  # nothing was made, so there's nothing to offer to delete

    def test_info_ignores_uploads(self, client: TestClient, conv: ConversationOut, db: MetadataDB) -> None:
        """Test that info ignores uploads."""
        u = db.add_chat_message(
            conv["id"],
            "user",
            "here you go",
            media=[{"id": "up1", "kind": "image", "source": "upload", "status": "done", "file": "up_a.png"}],
        )
        db.add_chat_message(conv["id"], "assistant", "Nice", parent_id=u.id)
        assert jp.dig(client.get(f"/api/chat/messages/{u.id}/delete-info"), "media") == {}

    def test_deleting_the_last_exchange_shows_the_one_before(
        self, client: TestClient, conv: ConversationOut, db: MetadataDB
    ) -> None:
        """Test that deleting the last exchange shows the one before."""
        _u1, _a1, _u2, _a2, u3, _a3 = self._chat(db, conv)
        msgs = jp.rows(client.delete(f"/api/chat/messages/{u3.id}"), "messages")
        assert [m["content"] for m in msgs][-1] == "Meow"

    def test_only_prompts_and_not_while_replying(
        self, client: TestClient, conv: ConversationOut, db: MetadataDB
    ) -> None:
        """Test that only prompts and not while replying."""
        u1, a1, *_ = self._chat(db, conv)
        assert client.delete(f"/api/chat/messages/{a1.id}").status_code == 400
        db.add_chat_message(conv["id"], "assistant", "", status="streaming")
        assert client.delete(f"/api/chat/messages/{u1.id}").status_code == 409
        assert client.delete("/api/chat/messages/999999").status_code == 404


class TestFork:
    """Tests for fork."""

    def _chat(
        self, chat: None, db: MetadataDB, conv: ConversationOut
    ) -> tuple[ChatMessage, ChatMessage, ChatMessage, ChatMessage]:
        d = chat_pkg.conversation_dir(conv["id"])
        (d / "fox.png").write_bytes(png_bytes())
        (d / "cat.png").write_bytes(png_bytes(color="blue"))
        u1 = db.add_chat_message(conv["id"], "user", "draw a fox", mode="auto")
        a1 = db.add_chat_message(
            conv["id"],
            "assistant",
            "Here!",
            model="t/model",
            media=[
                {
                    "id": "f1",
                    "kind": "image",
                    "source": "generated",
                    "status": "done",
                    "file": "fox.png",
                    "pinned": True,
                }
            ],
        )
        db.update_chat_message(a1.id, cost=0.02)
        u2 = db.add_chat_message(conv["id"], "user", "now a cat", parent_id=a1.id)
        a2 = db.add_chat_message(
            conv["id"],
            "assistant",
            "Meow",
            parent_id=u2.id,
            media=[{"id": "c1", "kind": "image", "source": "generated", "status": "done", "file": "cat.png"}],
        )
        return u1, a1, u2, a2

    def _fork(self, client: TestClient, conv: ConversationOut, message_id: int) -> httpx.Response:
        return client.post(f"/api/chat/conversations/{conv['id']}/fork", json={"message_id": message_id})

    def test_new_chat_ends_at_the_prompt_and_its_reply(
        self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB
    ) -> None:
        """Test that new chat ends at the prompt and its reply."""
        u1, _a1, _u2, _a2 = self._chat(chat, db, conv)
        client.patch(f"/api/chat/conversations/{conv['id']}", json={"title": "Animals", **SETTINGS})
        r = self._fork(client, conv, u1.id)
        assert r.status_code == 200
        new = obj(r)
        new_id = text(new, "id")
        assert new_id != conv["id"]
        assert new["title"] == "Animals (branch)"
        assert (new["text_model"], new["image_model"]) == ("t/model", "i/model")

        msgs = rows(client.get(f"/api/chat/conversations/{new_id}"), "messages")
        assert [(m["role"], m["content"]) for m in msgs] == [("user", "draw a fox"), ("assistant", "Here!")]
        assert msgs[0]["mode"] == "auto"
        assert msgs[1]["cost"] == 0.02
        assert msgs[1]["model"] == "t/model"
        assert msgs[1]["parent_id"] == msgs[0]["id"]
        assert msgs[0]["parent_id"] is None
        img = obj(msgs[1], "media", 0)
        assert img["file"] == "fox.png"
        assert img["pinned"]
        assert img["id"] != "f1"
        assert client.get(f"/api/chat/media/{new_id}/fox.png").status_code == 200
        # The original is untouched
        orig = rows(client.get(f"/api/chat/conversations/{conv['id']}"), "messages")
        assert [m["content"] for m in orig] == ["draw a fox", "Here!", "now a cat", "Meow"]

    def test_new_chat_survives_deleting_the_original(
        self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB
    ) -> None:
        """Test that new chat survives deleting the original."""
        u1, *_ = self._chat(chat, db, conv)
        new_id = text(self._fork(client, conv, u1.id), "id")
        client.delete(f"/api/chat/conversations/{conv['id']}")
        assert client.get(f"/api/chat/media/{new_id}/fox.png").status_code == 200

    def test_takes_the_shown_reply(self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB) -> None:
        """Test that takes the shown reply."""
        _u1, _a1, u2, a2 = self._chat(chat, db, conv)
        retry = db.add_chat_message(conv["id"], "assistant", "Purr", parent_id=u2.id)
        db.set_chat_leaf(conv["id"], a2.id)
        new_id = text(self._fork(client, conv, u2.id), "id")
        msgs = rows(client.get(f"/api/chat/conversations/{new_id}"), "messages")
        assert [m["content"] for m in msgs] == ["draw a fox", "Here!", "now a cat", "Meow"]
        assert all(m["siblings"] == [m["id"]] for m in msgs)  # no other versions come along
        db.set_chat_leaf(conv["id"], retry.id)
        new_id = text(self._fork(client, conv, u2.id), "id")
        assert text(client.get(f"/api/chat/conversations/{new_id}"), "messages", -1, "content") == "Purr"

    def test_media_shows_once(self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB) -> None:
        """Test that media shows once."""
        u1, *_ = self._chat(chat, db, conv)
        self._fork(client, conv, u1.id)
        items = [i for i in rows(client.get("/api/media"), "items") if i["origin"] == "chat"]
        assert sorted(text(i, "name") for i in items) == ["cat.png", "fox.png"]
        assert all(i["conversation_id"] == conv["id"] for i in items)

    def test_pending_video_is_not_copied_as_pending(
        self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB
    ) -> None:
        """Test that pending video is not copied as pending."""
        u = db.add_chat_message(conv["id"], "user", "a clip")
        db.add_chat_message(
            conv["id"],
            "assistant",
            "",
            media=[
                {"id": "v1", "kind": "video", "source": "generated", "status": "pending", "file": None, "job_id": "j"}
            ],
        )
        new_id = text(self._fork(client, conv, u.id), "id")
        item = obj(client.get(f"/api/chat/conversations/{new_id}"), "messages", 1, "media", 0)
        assert item["status"] == "error"

    def test_only_messages_in_this_chat_and_not_while_replying(
        self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB
    ) -> None:
        """Test that only messages in this chat and not while replying."""
        u1, _a1, *_ = self._chat(chat, db, conv)
        other = ConversationOut(id=text(client.post("/api/chat/conversations", json={}), "id"))
        assert self._fork(client, other, u1.id).status_code == 400
        db.add_chat_message(conv["id"], "assistant", "", status="streaming")
        assert self._fork(client, conv, u1.id).status_code == 409

    def test_chat_made_characters_are_copied_and_saved_ones_shared(
        self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB
    ) -> None:
        """Test that chat made characters are copied and saved ones shared."""
        saved = db.create_character("Rex", "a dog")
        own = db.create_character("Bob", "a fox", conversation_id=conv["id"])
        d = characters_mod.char_dir(own.id)
        d.mkdir(parents=True)
        (d / "img_bob.png").write_bytes(png_bytes())
        own = must(db.update_character(own.id, images=["img_bob.png"]))
        unused = db.create_character("Ann", "", conversation_id=conv["id"])
        client.patch(f"/api/chat/conversations/{conv['id']}", json={"character_ids": [saved.id, own.id]})
        (chat_pkg.conversation_dir(conv["id"]) / "bob.png").write_bytes(png_bytes())
        (chat_pkg.conversation_dir(conv["id"]) / "up_src.png").write_bytes(png_bytes())
        u = db.add_chat_message(conv["id"], "user", "draw Bob")
        db.add_chat_message(
            conv["id"],
            "assistant",
            "",
            media=[
                {
                    "id": "b1",
                    "kind": "image",
                    "source": "generated",
                    "status": "done",
                    "file": "bob.png",
                    "params": {"characters": [own.id], "refs": ["up_src.png", f"char:{own.id}/img_bob.png"]},
                }
            ],
        )

        new = obj(self._fork(client, conv, u.id))
        new_id = text(new, "id")
        copy_id = integer(new, "character_ids", 1)
        assert new["character_ids"] == [saved.id, copy_id]
        assert copy_id != own.id
        copy = must(db.get_character(copy_id))
        assert (copy.name, copy.conversation_id, copy.images) == ("Bob", new_id, ["img_bob.png"])
        assert (characters_mod.char_dir(copy_id) / "img_bob.png").is_file()
        assert not any(c.name == "Ann" and c.conversation_id == new_id for c in db.list_characters())

        params = dig(client.get(f"/api/chat/conversations/{new_id}"), "messages", 1, "media", 0, "params")
        assert params == {"characters": [copy_id], "refs": ["up_src.png", f"char:{copy_id}/img_bob.png"]}
        assert (chat_pkg.conversation_dir(new_id) / "up_src.png").is_file()

        # Deleting the original takes its own characters, not the branch's
        client.delete(f"/api/chat/conversations/{conv['id']}")
        assert db.get_character(own.id) is None
        assert db.get_character(unused.id) is None
        assert dig(client.get(f"/api/chat/conversations/{new_id}"), "conversation", "character_ids") == [
            saved.id,
            copy_id,
        ]
        assert (characters_mod.char_dir(copy_id) / "img_bob.png").is_file()

    def test_branching_from_a_reply_ends_with_that_reply(
        self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB
    ) -> None:
        """Test that branching from a reply ends with that reply."""
        _u1, a1, _u2, _a2 = self._chat(chat, db, conv)
        new_id = text(self._fork(client, conv, a1.id), "id")
        msgs = rows(client.get(f"/api/chat/conversations/{new_id}"), "messages")
        assert [m["content"] for m in msgs] == ["draw a fox", "Here!"]

    def test_branch_remembers_its_origin_and_the_original_lists_it(
        self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB
    ) -> None:
        """Test that branch remembers its origin and the original lists it."""
        _u1, _a1, u2, _a2 = self._chat(chat, db, conv)
        client.patch(f"/api/chat/conversations/{conv['id']}", json={"title": "Animals"})
        new_id = text(self._fork(client, conv, u2.id), "id")
        got = obj(client.get(f"/api/chat/conversations/{new_id}"), "conversation")
        assert got["forked_from"] == {"id": conv["id"], "title": "Animals", "message_id": u2.id, "exists": True}
        orig = rows(client.get(f"/api/chat/conversations/{conv['id']}"), "messages")
        assert {integer(m, "id"): m["forks"] for m in orig}[u2.id] == [{"id": new_id, "title": "Animals (branch)"}]
        assert all(not m["forks"] for m in orig if m["id"] != u2.id)
        client.delete(f"/api/chat/conversations/{conv['id']}")
        got = obj(client.get(f"/api/chat/conversations/{new_id}"), "conversation")
        assert dig(got, "forked_from", "exists") is False
        assert dig(got, "forked_from", "title") is None

    def test_branch_spend_says_what_came_with_it(
        self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB
    ) -> None:
        """Test that branch spend says what came with it."""
        u1, a1, *_ = self._chat(chat, db, conv)
        db.update_chat_message(a1.id, media=[{**must(db.get_chat_message(a1.id)).media[0], "credits": 30}])
        new_id = text(self._fork(client, conv, u1.id), "id")
        u = db.add_chat_message(new_id, "user", "more")
        a = db.add_chat_message(new_id, "assistant", "ok", parent_id=u.id)
        db.update_chat_message(a.id, cost=0.01)
        spend = obj(client.get(f"/api/chat/conversations/{new_id}/spend"))
        assert spend == {"usd": 0.03, "credits": 30, "inherited_usd": 0.02, "inherited_credits": 30}


class TestConversationList:
    """Tests for conversation list."""

    def test_pinned_first_and_pinning_keeps_the_order_of_the_rest(self, client: TestClient, db: MetadataDB) -> None:
        """Test that pinned first and pinning keeps the order of the rest."""
        a_id = text(client.post("/api/chat/conversations", json={"title": "A"}), "id")
        client.post("/api/chat/conversations", json={"title": "B"})
        client.post("/api/chat/conversations", json={"title": "C"})
        r = client.patch(f"/api/chat/conversations/{a_id}", json={"pinned": True})
        assert dig(r, "pinned") is True

        def titles() -> list[str]:
            return [text(x, "title") for x in rows(client.get("/api/chat/conversations"), "conversations")]

        assert titles() == ["A", "C", "B"]
        client.patch(f"/api/chat/conversations/{a_id}", json={"pinned": False})
        assert titles() == ["C", "B", "A"]

    def test_says_when_older_chats_are_left_out(
        self, client: TestClient, chat: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that says when older chats are left out."""
        monkeypatch.setattr(chat_pkg.routes, "CONVERSATION_LIST_LIMIT", 2)
        for t in "ABC":
            client.post("/api/chat/conversations", json={"title": t})
        data = client.get("/api/chat/conversations")
        assert len(seq(data, "conversations")) == 2
        assert dig(data, "more") is True

    def test_search_finds_titles_and_messages_on_any_branch(self, client: TestClient, db: MetadataDB) -> None:
        """Test that search finds titles and messages on any branch."""
        client.post("/api/chat/conversations", json={"title": "Fox story"})
        other_id = text(client.post("/api/chat/conversations", json={"title": "Misc"}), "id")
        client.post("/api/chat/conversations", json={"title": "Nothing here"})
        db.add_chat_message(
            other_id, "user", "a long intro " * 20 + "then a FOX appears in the snow " + "and more " * 20
        )
        db.add_chat_message(other_id, "user", "edited away", parent_id=None)  # another branch shown
        res = rows(client.get("/api/chat/conversations", params={"q": "fox"}), "conversations")
        assert {text(c, "title") for c in res} == {"Fox story", "Misc"}
        by = {text(c, "title"): c for c in res}
        assert by["Fox story"]["snippet"] is None
        snip = text(by["Misc"], "snippet")
        assert "FOX appears" in snip
        assert snip.startswith("…")
        assert snip.endswith("…")
        assert len(snip) <= 122

    def test_search_treats_wildcards_literally(self, client: TestClient) -> None:
        """Test that search treats wildcards literally."""
        client.post("/api/chat/conversations", json={"title": "100% done"})
        client.post("/api/chat/conversations", json={"title": "1000 done"})
        res = rows(client.get("/api/chat/conversations", params={"q": "0%"}), "conversations")
        assert [c["title"] for c in res] == ["100% done"]


class TestRememberedSettings:
    """Tests for remembered settings."""

    def test_turn_settings_are_kept_on_the_chat_and_copied_to_branches(
        self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that turn settings are kept on the chat and copied to branches."""
        monkeypatch.setattr(openrouter, "stream_chat", stub(lambda: text_chunks("ok")))
        ev = sse_events(
            client.post(
                f"/api/chat/conversations/{conv['id']}/messages",
                json={
                    "content": "hi",
                    **SETTINGS,
                    "mode": "text",
                    "history_limit": 10,
                    "image_limit": 2,
                    "image_options": {"aspect_ratio": "16:9"},
                },
            )
        )
        got = obj(client.get(f"/api/chat/conversations/{conv['id']}"), "conversation", "settings")
        assert got["mode"] == "text"
        assert got["history_limit"] == 10
        assert got["image_limit"] == 2
        assert dig(got, "image_options", "aspect_ratio") == "16:9"
        new = obj(
            client.post(
                f"/api/chat/conversations/{conv['id']}/fork", json={"message_id": integer(ev[0], "user_message", "id")}
            )
        )
        assert new["settings"] == got


class TestTitles:
    """Tests for titles."""

    def _send(
        self, client: TestClient, conv: ConversationOut, content: str = "tell me about foxes in winter"
    ) -> list[dict[str, JsonValue]]:
        return sse_events(
            client.post(
                f"/api/chat/conversations/{conv['id']}/messages", json={"content": content, **SETTINGS, "mode": "text"}
            )
        )

    def test_model_title_and_its_cost(
        self, client: TestClient, conv: ConversationOut, chat: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that model title and its cost."""
        monkeypatch.setattr(openrouter, "stream_chat", stub(lambda: text_chunks("ok", cost=0.001)))
        seen: dict[str, str] = {}

        def fake_title(model: str, prompt: str) -> tuple[str | None, float]:
            seen.update(model=model, prompt=prompt)
            return "Winter Foxes", 0.0005

        monkeypatch.setattr(chat_generation, "generate_title", fake_title)
        ev = self._send(client, conv)
        assert {"type": "title", "title": "Winter Foxes"} in ev
        assert seen == {"model": "t/model", "prompt": "tell me about foxes in winter"}
        assert number(ev[-1], "message", "cost") == 0.0015
        assert text(client.get(f"/api/chat/conversations/{conv['id']}"), "conversation", "title") == "Winter Foxes"
        # Only the first turn
        self._send(client, conv, "more")
        assert seen["prompt"] == "tell me about foxes in winter"

    def test_falls_back_to_the_prompt(
        self, client: TestClient, conv: ConversationOut, chat: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that falls back to the prompt."""
        monkeypatch.setattr(openrouter, "stream_chat", stub(lambda: text_chunks("ok")))

        def boom(model: str, prompt: str) -> tuple[str | None, float]:
            raise openrouter.OpenRouterError("nope")

        monkeypatch.setattr(chat_generation, "generate_title", boom)
        ev = self._send(client, conv)
        assert {"type": "title", "title": "tell me about foxes in winter"} in ev

    def test_title_model_override(
        self, client: TestClient, conv: ConversationOut, chat: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that title model override."""
        monkeypatch.setenv("CHAT_TITLE_MODEL", "cheap/model")
        monkeypatch.setattr(openrouter, "stream_chat", stub(lambda: text_chunks("ok")))
        seen: dict[str, str] = {}

        def fake_title(model: str, prompt: str) -> tuple[str | None, float]:
            seen.update(model=model)
            return "T", 0.0

        monkeypatch.setattr(chat_generation, "generate_title", fake_title)
        self._send(client, conv)
        assert seen["model"] == "cheap/model"

    def test_generate_title_cleans_the_reply(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that generate title cleans the reply."""
        monkeypatch.setattr(
            openrouter,
            "stream_chat",
            stub(lambda: text_chunks('<think>hmm</think>**Title:** "Winter Foxes."\nextra', cost=0.0002)),
        )
        assert chat_generation.generate_title("t/model", "foxes") == ("Winter Foxes", 0.0002)

    def test_clean_title_rejects_rambling(self, chat: None) -> None:
        """Test that clean title rejects rambling."""
        assert chat_generation.clean_title("x" * 100) is None
        assert chat_generation.clean_title("   ") is None


class TestPolloRequestLog:
    """Tests for pollo request log."""

    def test_submit_is_logged_with_its_payload(self, chat: None) -> None:
        """Test that submit is logged with its payload."""

        class Resp(requests.Response):
            def __init__(self) -> None:
                super().__init__()
                self.status_code = 200

            def json(self, **_kwargs: object) -> JsonValue:
                return {"data": {"taskId": "t-9"}}

        class Gen(PolloGenerator):
            def __init__(self) -> None:
                super().__init__(
                    ModelSpec(
                        model_id="seedance-2-0",
                        kind="video",
                        family="video",
                        model_url="https://pollo.ai/api/platform/generation/bytedance/seedance-2-0",
                    )
                )

            def get_payload(self) -> Payload:
                return {"input": {"prompt": "waves", "image": "https://host/x.png"}}

            def send_request(self) -> requests.Response:
                return Resp()

        assert pollo_provider.submit_task(Gen()) == "t-9"
        entry = request_log.recent()[0]
        assert entry["provider"] == "pollo"
        assert entry["model"] == "seedance-2-0"
        assert entry["status"] == 200
        assert entry["path"] == "/api/platform/generation/bytedance/seedance-2-0"
        assert entry["request"] == {"input": {"prompt": "waves", "image": "https://host/x.png"}}


class TestHiddenDefaults:
    """A chat can switch off any of its defaults for itself only."""

    def test_hiding_a_default_in_one_chat_leaves_the_others(self, client: TestClient, chat: None) -> None:
        """Test that hiding a default in one chat leaves the others."""
        a_id = integer(client.post("/api/chat/instructions", json={"name": "A", "content": "aa"}), "id")
        b_id = integer(client.post("/api/chat/instructions", json={"name": "B", "content": "bb"}), "id")
        client.put("/api/chat/settings", json={"default_instruction_ids": [a_id, b_id]})
        one_id = text(client.post("/api/chat/conversations", json={}), "id")
        two_id = text(client.post("/api/chat/conversations", json={}), "id")
        hidden = client.patch(f"/api/chat/conversations/{one_id}", json={"hidden_defaults": {"instruction": [a_id]}})
        assert dig(hidden, "hidden_defaults", "instruction") == [a_id]
        assert chat_generation.conversation_instructions(one_id) == "bb"
        assert chat_generation.conversation_instructions(two_id) == "aa\n\nbb"
        # Shown again
        client.patch(f"/api/chat/conversations/{one_id}", json={"hidden_defaults": {}})
        assert chat_generation.conversation_instructions(one_id) == "aa\n\nbb"

    def test_a_new_chat_can_start_with_some_hidden(self, client: TestClient, chat: None, db: MetadataDB) -> None:
        """Test that a new chat can start with some hidden."""
        c1 = db.create_character("Alice")
        client.put("/api/chat/settings", json={"default_character_ids": [c1.id]})
        conv_id = text(client.post("/api/chat/conversations", json={"hidden_defaults": {"character": [c1.id]}}), "id")
        assert chat_helpers.effective_ids(db.get_conversation(conv_id), "character") == []

    def test_a_branch_keeps_what_was_hidden(
        self, client: TestClient, chat: None, db: MetadataDB, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that a branch keeps what was hidden."""
        a_id = integer(client.post("/api/chat/instructions", json={"name": "A", "content": "aa"}), "id")
        client.put("/api/chat/settings", json={"default_instruction_ids": [a_id]})
        conv_id = text(client.post("/api/chat/conversations", json={"hidden_defaults": {"instruction": [a_id]}}), "id")
        msg = db.add_chat_message(conv_id, "user", "hi")
        fork = client.post(f"/api/chat/conversations/{conv_id}/fork", json={"message_id": msg.id})
        assert dig(fork, "hidden_defaults", "instruction") == [a_id]

    def test_unknown_kinds_are_refused(self, client: TestClient) -> None:
        """Test that unknown kinds are refused."""
        conv_id = text(client.post("/api/chat/conversations", json={}), "id")
        resp = client.patch(f"/api/chat/conversations/{conv_id}", json={"hidden_defaults": {"nope": [1]}})
        assert resp.status_code == 400


class TestPausedInstructions:
    """A chat can pause attached snippets/groups: kept attached, not sent."""

    def test_paused_snippets_and_groups_stay_attached_but_are_not_sent(
        self, client: TestClient, conv: ConversationOut, chat: None
    ) -> None:
        """Test that paused snippets and groups stay attached but are not sent."""
        tone = integer(client.post("/api/chat/instructions", json={"name": "Tone", "content": "Be warm."}), "id")
        fmt = integer(client.post("/api/chat/instructions", json={"name": "Fmt", "content": "Use markdown."}), "id")
        lang = integer(client.post("/api/chat/instructions", json={"name": "Lang", "content": "In French."}), "id")
        g = integer(client.post("/api/chat/instruction-groups", json={"name": "G", "snippet_ids": [tone, fmt]}), "id")
        client.patch(
            f"/api/chat/conversations/{conv['id']}",
            json={"instruction_group_ids": [g], "instruction_ids": [tone, lang]},
        )
        assert chat_generation.conversation_instructions(conv["id"]) == "Be warm.\n\nUse markdown.\n\nIn French."
        # Pause the group: its Fmt drops, but Tone stays (attached individually too)
        r = client.patch(
            f"/api/chat/conversations/{conv['id']}", json={"paused_instructions": {"instruction_group": [g]}}
        )
        assert dig(r, "paused_instructions", "instruction_group") == [g]
        assert dig(r, "instruction_group_ids") == [g]  # still attached, just paused
        assert chat_generation.conversation_instructions(conv["id"]) == "Be warm.\n\nIn French."
        # Also pause the Tone snippet → only Lang is left
        client.patch(
            f"/api/chat/conversations/{conv['id']}",
            json={"paused_instructions": {"instruction_group": [g], "instruction": [tone]}},
        )
        assert chat_generation.conversation_instructions(conv["id"]) == "In French."
        # Resume everything
        client.patch(f"/api/chat/conversations/{conv['id']}", json={"paused_instructions": {}})
        assert chat_generation.conversation_instructions(conv["id"]) == "Be warm.\n\nUse markdown.\n\nIn French."

    def test_an_inherited_default_can_be_paused(self, client: TestClient, chat: None) -> None:
        """Test that an inherited default can be paused."""
        a = integer(client.post("/api/chat/instructions", json={"name": "A", "content": "aa"}), "id")
        b = integer(client.post("/api/chat/instructions", json={"name": "B", "content": "bb"}), "id")
        client.put("/api/chat/settings", json={"default_instruction_ids": [a, b]})
        one = text(client.post("/api/chat/conversations", json={}), "id")
        two = text(client.post("/api/chat/conversations", json={}), "id")
        client.patch(f"/api/chat/conversations/{one}", json={"paused_instructions": {"instruction": [a]}})
        assert chat_generation.conversation_instructions(one) == "bb"  # paused here
        assert chat_generation.conversation_instructions(two) == "aa\n\nbb"  # unaffected elsewhere

    def test_a_new_chat_can_start_with_some_paused(self, client: TestClient, chat: None) -> None:
        """Test that a new chat can start with some paused."""
        a = integer(client.post("/api/chat/instructions", json={"name": "A", "content": "aa"}), "id")
        client.put("/api/chat/settings", json={"default_instruction_ids": [a]})
        created = client.post("/api/chat/conversations", json={"paused_instructions": {"instruction": [a]}})
        assert dig(created, "paused_instructions", "instruction") == [a]
        assert chat_generation.conversation_instructions(text(created, "id")) is None

    def test_a_branch_keeps_what_was_paused(self, client: TestClient, db: MetadataDB) -> None:
        """Test that a branch keeps what was paused."""
        a = integer(client.post("/api/chat/instructions", json={"name": "A", "content": "aa"}), "id")
        conv_id = text(client.post("/api/chat/conversations", json={"instruction_ids": [a]}), "id")
        client.patch(f"/api/chat/conversations/{conv_id}", json={"paused_instructions": {"instruction": [a]}})
        msg = db.add_chat_message(conv_id, "user", "hi")
        fork = client.post(f"/api/chat/conversations/{conv_id}/fork", json={"message_id": msg.id})
        assert dig(fork, "paused_instructions", "instruction") == [a]

    def test_unknown_kinds_are_refused(self, client: TestClient, conv: ConversationOut) -> None:
        """Test that unknown kinds are refused."""
        resp = client.patch(f"/api/chat/conversations/{conv['id']}", json={"paused_instructions": {"character": [1]}})
        assert resp.status_code == 400


class TestLargeChats:
    """Big chats (imports run to hundreds of messages and images) stay quick."""

    def test_images_have_a_small_preview(self, client: TestClient, conv: ConversationOut, tmp_path: Path) -> None:
        """Test that images have a small preview."""
        folder = tmp_path / "chat" / conv["id"]
        folder.mkdir(parents=True)
        Image.new("RGB", (1536, 2048), "red").save(folder / "img_big.png")
        resp = client.get(f"/api/chat/media/{conv['id']}/img_big.png/preview")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/jpeg"
        assert min(Image.open(io.BytesIO(resp.content)).size) == 768
        assert client.get(f"/api/chat/media/{conv['id']}/nope.png/preview").status_code == 404

    def test_deleting_a_chat_removes_its_messages_and_files(
        self, client: TestClient, conv: ConversationOut, db: MetadataDB, tmp_path: Path
    ) -> None:
        """Test that deleting a chat removes its messages and files."""
        for i in range(30):
            db.add_chat_message(conv["id"], "user" if i % 2 == 0 else "assistant", f"m{i}")
        folder = tmp_path / "chat" / conv["id"]
        folder.mkdir(parents=True)
        (folder / "img_a.png").write_bytes(png_bytes())
        assert client.delete(f"/api/chat/conversations/{conv['id']}").status_code == 200
        assert db.get_chat_messages(conv["id"]) == []
        assert not folder.exists()  # moved aside at once, then removed in the background
        for _ in range(50):
            if not list((tmp_path / "chat").glob(".deleting-*")):
                break
            time.sleep(0.02)
        assert not list((tmp_path / "chat").glob(".deleting-*"))

    def test_missing_thumbnails_are_made_in_the_background(self, chat: None, tmp_path: Path) -> None:
        """Test that missing thumbnails are made in the background."""
        folder = tmp_path / "chat" / "c1"
        folder.mkdir(parents=True)
        Image.new("RGB", (1200, 1600), "blue").save(folder / "img_a.png")
        chat_polling.warm_missing_thumbnails()
        for size in (media_mod.THUMB_SIZE, chat_pkg.CHAT_PREVIEW_SIZE):
            assert media_mod.thumb_path(folder / "img_a.png", size).is_file()


class TestActiveGenerations:
    """The /generations/active endpoint behind the always-visible queue."""

    def gen(self, mid: str, kind: str = "image", status: str = "pending", **f: JsonValue) -> dict[str, JsonValue]:
        """Document the gen test helper."""
        return {"id": mid, "kind": kind, "source": "generated", "status": status, "prompt": "p", **f}

    def test_pending_across_threads_plus_known_completions(self, client: TestClient, db: MetadataDB) -> None:
        """Test that pending across threads plus known completions."""
        a = text(client.post("/api/chat/conversations", json={"title": "A"}), "id")
        b = text(client.post("/api/chat/conversations", json={"title": "B"}), "id")
        # One pending in each thread, and a finished one that is NOT pending.
        db.add_chat_message(a, "assistant", media=[self.gen("p1")], status="done")
        db.add_chat_message(b, "assistant", media=[self.gen("p2", kind="video")], status="done")
        done_msg = db.add_chat_message(a, "assistant", media=[self.gen("d1", status="done", file="x.png")])

        # No `known`: only the two pending ones come back, from both threads.
        r = rows(client.post("/api/chat/generations/active", json={}), "items")
        by = {text(i, "media_id"): i for i in r}
        assert set(by) == {"p1", "p2"}
        assert by["p1"]["conversation_title"] == "A"
        assert by["p2"]["kind"] == "video"

        # Tracking the finished message resolves it to its done state.
        r = rows(client.post("/api/chat/generations/active", json={"known": [done_msg.id]}), "items")
        by = {text(i, "media_id"): i for i in r}
        assert set(by) == {"p1", "p2", "d1"}
        assert by["d1"]["status"] == "done"
        assert by["d1"]["file"] == "x.png"

    def test_reports_failure_and_ignores_non_generated(self, client: TestClient, db: MetadataDB) -> None:
        """Test that reports failure and ignores non generated."""
        c = text(client.post("/api/chat/conversations", json={}), "id")
        m = db.add_chat_message(
            c,
            "assistant",
            media=[
                self.gen("e1", status="error", error="boom", moderated=True),
                {"id": "u1", "kind": "image", "source": "upload", "status": "done", "file": "up.png"},
            ],
            status="done",
        )
        r = rows(client.post("/api/chat/generations/active", json={"known": [m.id]}), "items")
        by = {text(i, "media_id"): i for i in r}
        assert set(by) == {"e1"}  # the uploaded image isn't a generation
        assert by["e1"]["status"] == "error"
        assert by["e1"]["error"] == "boom"
        assert by["e1"]["moderated"] is True

    def test_scoped_to_the_signed_in_user(self, client: TestClient, db: MetadataDB) -> None:
        """Test that scoped to the signed in user."""
        c = text(client.post("/api/chat/conversations", json={}), "id")
        tok = set_tenant("someone-else")
        try:
            other = db.create_conversation(title="theirs")
            db.add_chat_message(other.id, "assistant", media=[self.gen("x1")], status="done")
        finally:
            reset_tenant(tok)
        db.add_chat_message(c, "assistant", media=[self.gen("mine")], status="done")
        items = rows(client.post("/api/chat/generations/active", json={}), "items")
        assert {text(i, "media_id") for i in items} == {"mine"}  # never the other user's


class TestEnhancePrompt:
    """Tests for enhance prompt."""

    def test_rewrites_only_on_request(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that rewrites only on request."""

        def fake_stream(model: str, messages: list[dict[str, JsonValue]], **kw: object) -> Iterator[ChatChunk]:
            assert "a cat" in text(messages[0], "content")
            yield {"choices": [{"delta": {"content": "A fluffy cat, golden hour"}}], "usage": {"cost": 0.001}}

        monkeypatch.setattr(openrouter, "stream_chat", fake_stream)
        r = client.post("/api/chat/enhance-prompt", json={"prompt": "a cat", "model": "x/y", "kind": "image"})
        assert r.status_code == 200
        assert dig(r) == {"prompt": "A fluffy cat, golden hour", "cost": 0.001}

    def test_empty_reply_is_an_error(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that empty reply is an error."""
        nothing: list[ChatChunk] = []
        monkeypatch.setattr(openrouter, "stream_chat", stub(lambda: iter(nothing)))
        r = client.post("/api/chat/enhance-prompt", json={"prompt": "a cat", "model": "x/y"})
        assert r.status_code == 502


class TestEstimate:
    """Tests for estimate."""

    def test_pollo_estimate_asks_pollo_and_others_get_none(
        self, client: TestClient, provider_keys: dict[str, str | None], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that pollo estimate asks pollo and others get none."""
        provider_keys["pollo"] = "pk-test"
        seen: dict[str, JsonValue] = {}

        def fake_ask(url: str, payload: Payload, api_key: str | None) -> tuple[dict[str, JsonValue] | None, bool]:
            seen.update(url=url, payload=payload["input"], key=api_key)
            return {"credits": 8, "full_credits": 10}, True

        monkeypatch.setattr(pollo_estimate, "_ask", fake_ask)
        pollo_estimate.clear_cache()
        body = {"model": "pollo/seedance20fast", "kind": "video", "duration": 5, "resolution": "480p"}
        got = dig(client.post("/api/chat/estimate", json=body))
        assert got == {"estimate": {"credits": 8, "full_credits": 10}}
        assert text(seen, "url").endswith("/estimate")
        assert seen["key"] == "pk-test"
        # a Ref model (legacy ref2video) has no estimate endpoint; other providers aren't priced here
        ref = dig(client.post("/api/chat/estimate", json={**body, "model": "pollo/nonexistentref"}))
        assert ref == {"estimate": None}
        assert dig(client.post("/api/chat/estimate", json={**body, "model": "venice/x"})) == {"estimate": None}


class TestSpendBreakdown:
    """Tests for spend breakdown."""

    def test_groups_by_model_and_converts_credits_to_usd(
        self, client: TestClient, conv: ConversationOut, db: MetadataDB
    ) -> None:
        """Test that groups by model and converts credits to usd."""
        db.add_chat_message(
            conv["id"],
            "assistant",
            "",
            media=[
                {"id": "a", "kind": "video", "status": "done", "model": "pollo/seedance25", "credits": 10},
                {"id": "b", "kind": "video", "status": "done", "model": "pollo/seedance25", "credits": 5},
            ],
        )
        body = client.get("/api/chat/spend/breakdown")
        row = next(r for r in rows(body, "rows") if r["model"] == "pollo/seedance25")
        assert row["credits"] == 15
        assert row["count"] == 2
        assert row["usd"] == 0.9
        assert number(body, "total_usd") >= 0.9
        assert client.get("/api/chat/spend/breakdown?days=7").status_code == 200


class TestTitleModel:
    """Tests for title model."""

    def test_setting_round_trips(self, client: TestClient) -> None:
        """Test that setting round trips."""
        assert dig(client.get("/api/chat/settings"), "title_model") is None
        r = client.put("/api/chat/settings/title-model", json={"title_model": "x/cheap"})
        assert dig(r, "title_model") == "x/cheap"
        # saving the default lists doesn't touch it
        assert dig(client.put("/api/chat/settings", json={}), "title_model") == "x/cheap"
        assert dig(client.put("/api/chat/settings/title-model", json={"title_model": ""}), "title_model") is None


class TestEditAndRewordInPlace:
    """Editing a picture on its card, and writing a reply's words again,.

    without re-running the turn that made them.
    """

    def _reply_with_image(self, db: MetadataDB, conv: ConversationOut, **extra: JsonValue) -> ChatMessage:
        db.add_chat_message(conv["id"], "user", "draw a fox")
        return db.add_chat_message(
            conv["id"],
            "assistant",
            "Here is your fox.",
            model="t/model",
            media=[
                {
                    "id": "m1",
                    "kind": "image",
                    "source": "generated",
                    "status": "done",
                    "file": "img_old.png",
                    "prompt": "a fox",
                    "model": "i/model",
                    "cost": 0.02,
                    "params": {"aspect_ratio": "16:9", "resolution": None, "refs": ["img_ref.png"]},
                    **extra,
                }
            ],
        )

    def _media(self, db: MetadataDB, message_id: int) -> list[dict[str, JsonValue]]:
        return must(db.get_chat_message(message_id)).media

    def _reply(self, db: MetadataDB, conv: ConversationOut, **extra: JsonValue) -> ChatMessage:
        msg = self._reply_with_image(db, conv, **extra)
        db.update_chat_message(msg.id, cost=0.01)  # the words it already cost
        # the files must really be there: generation drops references it can't find

        d = config.ROOT_DIR / "chat" / conv["id"]
        d.mkdir(parents=True, exist_ok=True)
        for name in ("img_old.png", "img_ref.png"):
            (d / name).write_bytes(png_bytes())
        return msg

    def _inline(self, chat: None, monkeypatch: pytest.MonkeyPatch) -> None:
        class Inline:
            def __init__(self, target: Callable[..., object], args: tuple[object, ...], **kw: object) -> None:
                self.target, self.args = target, args

            def start(self) -> None:
                self.target(*self.args)

        monkeypatch.setattr(threading, "Thread", Inline)

    def _capture(self, monkeypatch: pytest.MonkeyPatch, got: dict[str, JsonValue]) -> None:
        def fake_image(model: str, prompt: str, **kw: JsonValue) -> tuple[list[tuple[bytes, str]], float | None]:
            got.update(model=model, prompt=prompt, **kw)
            return [(png_bytes(), "image/png")], 0.03

        monkeypatch.setattr(openrouter, "generate_image", fake_image)

    def test_edit_sends_the_picture_back_and_replaces_it(
        self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that edit sends the picture back and replaces it."""
        msg = self._reply(db, conv)
        self._inline(chat, monkeypatch)
        got: dict[str, JsonValue] = {}
        self._capture(monkeypatch, got)
        r = client.post(
            f"/api/chat/messages/{msg.id}/media/m1/regenerate",
            json={"prompt": "give it a hat", "edit": True, "replace": True},
        )
        assert r.status_code == 200
        assert got["prompt"] == "give it a hat"
        media = self._media(db, msg.id)
        # the picture itself leads the references; the one it was made from is dropped
        assert dig(media[0], "params", "refs") == ["img_old.png"]
        assert len(seq(got, "input_images")) == 1
        assert len(media) == 1  # replaced, not added beside
        assert media[0]["id"] == "m1"
        assert media[0]["status"] == "done"
        assert media[0]["file"] != "img_old.png"
        assert media[0]["prompt"] == "give it a hat"

    def test_the_replaced_picture_is_kept_as_a_version(
        self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that the replaced picture is kept as a version."""
        msg = self._reply(db, conv)
        self._inline(chat, monkeypatch)
        self._capture(monkeypatch, {})
        client.post(
            f"/api/chat/messages/{msg.id}/media/m1/regenerate",
            json={"prompt": "give it a hat", "edit": True, "replace": True},
        )
        item = self._media(db, msg.id)[0]
        assert [text(v, "file") for v in rows(item, "versions")] == ["img_old.png"]
        assert dig(item, "versions", 0, "prompt") == "a fox"

    def test_an_earlier_version_is_not_treated_as_an_orphan(
        self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Its file must stay referenced, or the media sweep would offer to delete it."""
        msg = self._reply(db, conv)
        self._inline(chat, monkeypatch)
        self._capture(monkeypatch, {})
        client.post(
            f"/api/chat/messages/{msg.id}/media/m1/regenerate",
            json={"prompt": "give it a hat", "edit": True, "replace": True},
        )
        item = self._media(db, msg.id)[0]
        assert "img_old.png" in media_mod.referenced_files(item)

    def test_redo_re_rolls_the_prompt_without_the_picture(
        self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that redo re rolls the prompt without the picture."""
        msg = self._reply(db, conv)
        self._inline(chat, monkeypatch)
        got: dict[str, JsonValue] = {}
        self._capture(monkeypatch, got)
        client.post(
            f"/api/chat/messages/{msg.id}/media/m1/regenerate",
            json={"prompt": "a fox, wider shot", "replace": True},
        )
        assert got["prompt"] == "a fox, wider shot"
        # not an edit: the picture isn't sent back, the original reference stands
        assert dig(self._media(db, msg.id)[0], "params", "refs") == ["img_ref.png"]

    def test_the_picture_showing_is_the_real_one(
        self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Going back to an earlier picture makes it the item's file, prompt and settings."""
        msg = self._reply(db, conv)
        self._inline(chat, monkeypatch)
        self._capture(monkeypatch, {})
        client.post(
            f"/api/chat/messages/{msg.id}/media/m1/regenerate", json={"prompt": "a fox, wider", "replace": True}
        )
        new_file = text(self._media(db, msg.id)[0], "file")
        out = client.post(f"/api/chat/messages/{msg.id}/media/m1/version", json={"index": 0})
        item = obj(out, "media", 0)
        assert (item["file"], item["prompt"], item["version_shown"]) == ("img_old.png", "a fox", 0)
        assert [text(v, "file") for v in rows(item, "versions")] == [new_file]
        # and forward again
        item = obj(client.post(f"/api/chat/messages/{msg.id}/media/m1/version", json={"index": 1}), "media", 0)
        assert (item["file"], item["version_shown"]) == (new_file, 1)
        assert [text(v, "file") for v in rows(item, "versions")] == ["img_old.png"]

    def test_a_redo_from_an_earlier_picture_goes_last(
        self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With version 1 of 2 showing, a redo becomes version 3, keeping both."""
        msg = self._reply(db, conv)
        self._inline(chat, monkeypatch)
        self._capture(monkeypatch, {})
        client.post(f"/api/chat/messages/{msg.id}/media/m1/regenerate", json={"prompt": "b", "replace": True})
        second = text(self._media(db, msg.id)[0], "file")
        client.post(f"/api/chat/messages/{msg.id}/media/m1/version", json={"index": 0})
        client.post(f"/api/chat/messages/{msg.id}/media/m1/regenerate", json={"prompt": "c", "replace": True})
        item = self._media(db, msg.id)[0]
        assert [text(v, "file") for v in rows(item, "versions")] == ["img_old.png", second]
        assert item["version_shown"] == 2
        assert item["prompt"] == "c"

    def test_switching_keeps_every_charge(
        self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB
    ) -> None:
        """Swapping which picture is live doesn't change what the chat spent."""
        msg = self._reply(db, conv, credits=5, versions=[{"file": "img_a.png", "credits": 3}])
        before = db.get_chat_spend(conv["id"])
        client.post(f"/api/chat/messages/{msg.id}/media/m1/version", json={"index": 0})
        assert db.get_chat_spend(conv["id"]) == before

    def test_a_failed_attempt_never_counts(
        self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB
    ) -> None:
        """Failures aren't billed: an older record's failed-attempt credits stay out of spend."""
        msg = self._reply(
            db, conv, file=None, status="error", error="nope", credits=4, versions=[{"file": "img_a.png", "credits": 3}]
        )
        out = client.post(f"/api/chat/messages/{msg.id}/media/m1/version", json={"index": 0})
        assert dig(out, "media", 0, "file") == "img_a.png"
        assert dig(out, "media", 0, "status") == "done"
        assert db.get_chat_spend(conv["id"])[1] == 3

    def test_no_switching_while_it_is_being_made(
        self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB
    ) -> None:
        """Test that a pending card can't be switched."""
        msg = self._reply(db, conv, status="pending", versions=[{"file": "img_a.png"}])
        r = client.post(f"/api/chat/messages/{msg.id}/media/m1/version", json={"index": 0})
        assert r.status_code == 409

    def test_editing_without_a_picture_is_refused(
        self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB
    ) -> None:
        """Test that editing without a picture is refused."""
        msg = self._reply(db, conv, file=None, status="error", error="nope")
        r = client.post(
            f"/api/chat/messages/{msg.id}/media/m1/regenerate", json={"prompt": "x", "edit": True, "replace": True}
        )
        assert r.status_code == 400

    def test_gallery_re_roll_still_adds_a_second_picture(
        self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Without `replace` the old behaviour stands, for the gallery."""
        msg = self._reply(db, conv)
        self._inline(chat, monkeypatch)
        self._capture(monkeypatch, {})
        client.post(f"/api/chat/messages/{msg.id}/media/m1/regenerate", json={})
        media = self._media(db, msg.id)
        assert len(media) == 2
        assert media[0]["file"] == "img_old.png"

    def test_reword_replaces_the_words_and_keeps_the_picture(
        self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that reword replaces the words and keeps the picture."""
        msg = self._reply(db, conv)
        monkeypatch.setattr(openrouter, "stream_chat", stub(lambda: text_chunks("A fox, as requested.")))
        monkeypatch.setattr(
            openrouter, "generate_image", stub(lambda: pytest.fail("rewording must not remake the picture"))
        )
        sse_events(client.post(f"/api/chat/conversations/{conv['id']}/reword", json={"message_id": msg.id, **SETTINGS}))
        after = must(db.get_chat_message(msg.id))
        assert after.content == "A fox, as requested."
        assert len(after.media) == 1
        assert after.media[0]["file"] == "img_old.png"

    def test_reword_keeps_everything_the_reply_cost(
        self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The old words were paid for (and stay as a version), so their cost stays in the total."""
        msg = self._reply(db, conv)
        db.update_chat_message(msg.id, cost=0.03)  # 0.01 of words + the picture's 0.02
        monkeypatch.setattr(openrouter, "stream_chat", stub(lambda: text_chunks("Reworded.")))
        sse_events(client.post(f"/api/chat/conversations/{conv['id']}/reword", json={"message_id": msg.id, **SETTINGS}))
        assert must(db.get_chat_message(msg.id)).cost == 0.031

    def test_reword_keeps_the_old_words_as_a_version(
        self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Redo text files both wordings, and the arrows switch between them."""
        msg = self._reply(db, conv)
        monkeypatch.setattr(openrouter, "stream_chat", stub(lambda: text_chunks("A new telling.")))
        sse_events(client.post(f"/api/chat/conversations/{conv['id']}/reword", json={"message_id": msg.id, **SETTINGS}))
        after = must(db.get_chat_message(msg.id))
        assert after.to_dict()["text_versions"] == 2
        assert after.to_dict()["text_shown"] == 1
        back = obj(client.post(f"/api/chat/messages/{msg.id}/text-version", json={"index": 0}))
        assert back["content"] == "Here is your fox."
        assert back["text_shown"] == 0
        # the picture is untouched by switching words
        assert dig(back, "media", 0, "file") == "img_old.png"
        assert must(db.get_chat_message(msg.id)).content == "Here is your fox."

    def test_a_failed_reword_adds_no_version(
        self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Nothing came back: the old words return and no empty version is filed."""
        msg = self._reply(db, conv)
        monkeypatch.setattr(openrouter, "stream_chat", stub(lambda: text_chunks("")))
        sse_events(client.post(f"/api/chat/conversations/{conv['id']}/reword", json={"message_id": msg.id, **SETTINGS}))
        assert must(db.get_chat_message(msg.id)).to_dict()["text_versions"] == 0

    def test_edit_text_sends_the_old_words_and_the_instruction(
        self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Edit text: the model sees its reply and how to change it."""
        msg = self._reply(db, conv)
        sent: dict[str, list[dict[str, JsonValue]]] = {}

        def fake(model: str, messages: list[dict[str, JsonValue]], *a: object, **k: object) -> Iterator[ChatChunk]:
            sent["messages"] = messages
            return text_chunks("A shorter fox.")

        monkeypatch.setattr(openrouter, "stream_chat", fake)
        body = {"message_id": msg.id, "instruction": "make it shorter", **SETTINGS}
        sse_events(client.post(f"/api/chat/conversations/{conv['id']}/reword", json=body))
        assert sent["messages"][-2] == {"role": "assistant", "content": "Here is your fox."}
        assert "make it shorter" in text(sent["messages"][-1], "content")
        assert must(db.get_chat_message(msg.id)).content == "A shorter fox."

    def test_switching_words_is_refused_mid_reply(
        self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB
    ) -> None:
        """Test that the wording can't be switched while the reply streams."""
        msg = self._reply(db, conv)
        db.update_chat_message(
            msg.id, status="streaming", text_versions_json='{"items": [{"content": "a"}, {"content": "b"}], "shown": 1}'
        )
        r = client.post(f"/api/chat/messages/{msg.id}/text-version", json={"index": 0})
        assert r.status_code == 409

    def test_replaced_pictures_still_count_towards_spend(self, conv: ConversationOut, db: MetadataDB) -> None:
        """A redone picture's credits move into `versions`; they were still billed."""
        db.add_chat_message(conv["id"], "user", "draw")
        db.add_chat_message(
            conv["id"],
            "assistant",
            "",
            media=[
                {
                    "id": "m1",
                    "kind": "image",
                    "source": "generated",
                    "status": "done",
                    "file": "b.png",
                    "credits": 5,
                    "versions": [{"file": "a.png", "credits": 3}],
                }
            ],
        )
        assert db.get_chat_spend(conv["id"])[1] == 8

    def test_a_pollo_charge_is_credits_or_dollars_not_both(self, conv: ConversationOut, db: MetadataDB) -> None:
        """Pollo's costUsd is its credits converted: an item carrying both is charged once, in credits."""
        db.add_chat_message(conv["id"], "user", "draw")
        db.add_chat_message(
            conv["id"],
            "assistant",
            "",
            media=[
                {
                    "id": "m1",
                    "kind": "image",
                    "source": "generated",
                    "status": "done",
                    "file": "b.png",
                    "credits": 5,
                    "cost": 0.3,
                    "versions": [{"file": "a.png", "credits": 3, "cost": 0.18}],
                }
            ],
        )
        [row] = db.spend_rows([conv["id"]])
        assert (row["usd"], row["credits"]) == (0.0, 8)

    def test_reword_puts_the_old_words_back_if_nothing_comes_out(
        self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that reword puts the old words back if nothing comes out."""
        msg = self._reply(db, conv)
        monkeypatch.setattr(openrouter, "stream_chat", stub(lambda: text_chunks("")))
        sse_events(client.post(f"/api/chat/conversations/{conv['id']}/reword", json={"message_id": msg.id, **SETTINGS}))
        assert must(db.get_chat_message(msg.id)).content == "Here is your fox."

    def test_reword_refuses_a_user_message(
        self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB
    ) -> None:
        """Test that reword refuses a user message."""
        db.add_chat_message(conv["id"], "user", "hello")
        user = db.get_chat_messages(conv["id"])[-1]
        r = client.post(f"/api/chat/conversations/{conv['id']}/reword", json={"message_id": user.id, **SETTINGS})
        assert r.status_code == 400


class TestRetryAFailedPicture:
    """A failed generation can be run again with a changed prompt, and leaves.

    no empty version behind.
    """

    def _failed(self, db: MetadataDB, conv: ConversationOut) -> ChatMessage:
        db.add_chat_message(conv["id"], "user", "draw a fox")
        return db.add_chat_message(
            conv["id"],
            "assistant",
            "Sorry.",
            model="t/model",
            media=[
                {
                    "id": "m1",
                    "kind": "image",
                    "source": "generated",
                    "status": "error",
                    "error": "flagged",
                    "prompt": "a fox",
                    "model": "i/model",
                    "params": {"aspect_ratio": "16:9", "resolution": None, "refs": []},
                }
            ],
        )

    def _inline(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class Inline:
            def __init__(self, target: Callable[..., object], args: tuple[object, ...], **kw: object) -> None:
                """Document the   init   test helper."""
                self.target, self.args = target, args

            def start(self) -> None:
                self.target(*self.args)

        monkeypatch.setattr(threading, "Thread", Inline)

    def test_a_changed_prompt_is_used(
        self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that a changed prompt is used."""
        msg = self._failed(db, conv)
        self._inline(monkeypatch)
        got: dict[str, str] = {}

        def fake_image(model: str, prompt: str, **kw: object) -> tuple[list[tuple[bytes, str]], float | None]:
            got.update(prompt=prompt)
            return [(png_bytes(), "image/png")], 0.01

        monkeypatch.setattr(openrouter, "generate_image", fake_image)
        r = client.post(
            f"/api/chat/messages/{msg.id}/media/m1/regenerate",
            json={"prompt": "a fox, softer lighting", "replace": True},
        )
        assert r.status_code == 200
        assert got["prompt"] == "a fox, softer lighting"
        item = must(db.get_chat_message(msg.id)).media[0]
        assert item["status"] == "done"
        assert item["prompt"] == "a fox, softer lighting"

    def test_it_leaves_no_empty_version(
        self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """There was no picture, so there is nothing to flip back to."""
        msg = self._failed(db, conv)
        self._inline(monkeypatch)
        monkeypatch.setattr(openrouter, "generate_image", stub(lambda: ([(png_bytes(), "image/png")], 0.01)))
        client.post(f"/api/chat/messages/{msg.id}/media/m1/regenerate", json={"prompt": "try again", "replace": True})
        assert must(db.get_chat_message(msg.id)).media[0].get("versions") in (None, [])

    def test_editing_a_failed_picture_is_still_refused(
        self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB
    ) -> None:
        """`edit` needs a picture to send back; a failure has none."""
        msg = self._failed(db, conv)
        r = client.post(
            f"/api/chat/messages/{msg.id}/media/m1/regenerate",
            json={"prompt": "x", "edit": True, "replace": True},
        )
        assert r.status_code == 400


def test_a_webm_attachment_is_recorded_as_a_video(
    client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB
) -> None:
    """Attachment kind comes from web.media_types now. Only ".mp4" counted.

    before, so a .webm or .mov clip was recorded as an image.
    """
    d = config.ROOT_DIR / "chat" / conv["id"]
    d.mkdir(parents=True, exist_ok=True)
    for name in ("upv_clip.webm", "upa_voice.ogg", "up_pic.png"):
        (d / name).write_bytes(b"fake")
    sse_events(
        client.post(
            f"/api/chat/conversations/{conv['id']}/messages",
            json={
                "content": "look",
                "attachments": ["upv_clip.webm", "upa_voice.ogg", "up_pic.png"],
                "mode": "text",
                **SETTINGS,
            },
        )
    )
    user = next(m for m in db.get_chat_messages(conv["id"]) if m.role == "user")
    assert [i["kind"] for i in user.media] == ["video", "audio", "image"]


class TestNoDoubleCharges:
    """Guards against paying twice for one request."""

    def test_a_second_send_while_a_reply_streams_is_refused(
        self, client: TestClient, conv: ConversationOut, db: MetadataDB
    ) -> None:
        """A double-clicked Send (or a second tab) can't start a second paid turn."""
        db.add_chat_message(conv["id"], "user", "hi")
        db.add_chat_message(conv["id"], "assistant", "", status="streaming")
        r = client.post(
            f"/api/chat/conversations/{conv['id']}/messages", json={"content": "again", "mode": "auto", **SETTINGS}
        )
        assert r.status_code == 409

    def test_gallery_sends_still_run_side_by_side(
        self, client: TestClient, conv: ConversationOut, db: MetadataDB, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Gallery exchanges never wait on the chat."""
        db.add_chat_message(conv["id"], "user", "hi")
        db.add_chat_message(conv["id"], "assistant", "", status="streaming")
        monkeypatch.setattr(openrouter, "stream_chat", stub(lambda: text_chunks("ok")))
        r = client.post(
            f"/api/chat/conversations/{conv['id']}/messages",
            json={"content": "x", "mode": "text", "lane": "gallery", **SETTINGS},
        )
        assert r.status_code == 200

    def test_a_repeated_identical_tool_call_is_not_made_twice(
        self, client: TestClient, conv: ConversationOut, chat: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A model repeating the same generate_image call word for word is only billed once."""
        args: dict[str, JsonValue] = {"prompt": "a cat"}
        rounds = iter([tool_chunks("generate_image", args), tool_chunks("generate_image", args), text_chunks("Done.")])
        monkeypatch.setattr(openrouter, "stream_chat", stub(lambda: next(rounds)))
        made: list[str] = []

        def fake_image(model: str, prompt: str, **kw: object) -> tuple[list[tuple[bytes, str]], float | None]:
            made.append(prompt)
            return [(png_bytes(), "image/png")], 0.04

        monkeypatch.setattr(openrouter, "generate_image", fake_image)
        ev = sse_events(
            client.post(
                f"/api/chat/conversations/{conv['id']}/messages",
                json={"content": "draw a cat", "mode": "auto", **SETTINGS},
            )
        )
        assert made == ["a cat"]
        assert len(seq(ev[-1], "message", "media")) == 1

"""Tests for web.characters — characters shared by chat and generations."""

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import TypedDict, cast

import pytest
from fastapi.testclient import TestClient
from httpx2 import Response

import web.characters as characters_mod
import web.chat as chat_pkg
from tests.chat_fixtures import SETTINGS, ConversationOut, png_bytes, sse_events, text_chunks, tool_chunks
from tests.jsonpath import dig, flag, integer, must, obj, seq, text
from tests.stubs import stub
from web.chat import catalogue as chat_catalogue
from web.chat import constants as chat_constants
from web.chat import generation as chat_generation
from web.chat import turn_base as chat_turn_base
from web.core.metadata import MetadataDB
from web.jsonutil import as_object
from web.providers import ImageRequest, StreamOptions, VideoRequest, openrouter
from web.types import ChatChunk, JsonValue, VideoJob
from web.uploads.files import file_to_data_url

pytest_plugins = ["tests.chat_fixtures"]

type Messages = list[dict[str, JsonValue]]
type Tools = list[dict[str, JsonValue]] | None
type Events = list[dict[str, JsonValue]]


class CharacterOut(TypedDict):
    """A character as the API returns it (the keys the tests read)."""

    id: int
    name: str
    images: list[str]
    adhoc: bool


@dataclass
class ImageCapture:
    """What the stubbed image generator was last asked for."""

    sent_prompt: str | None = None
    input_images: list[str] | None = None

    @property
    def prompt(self) -> str:
        """The prompt it received (fails the test if it was never called)."""
        return must(self.sent_prompt)


@dataclass
class ChatCapture:
    """What the stubbed chat stream was last asked for."""

    messages: Messages = field(default_factory=list)
    tools: Tools = None


def _make(
    client: TestClient,
    name: str = "Linh",
    description: str = "Short black hair, red scarf",
    images: int = 1,
    **extra: JsonValue,
) -> CharacterOut:
    """Create a character through the API and add ``images`` reference images to it."""
    reply: Response = client.post("/api/characters", json={"name": name, "description": description, **extra})
    for i in range(images):
        reply = client.post(
            f"/api/characters/{integer(reply, 'id')}/images",
            files={"file": (f"{i}.png", png_bytes(color=f"rgb({i * 50},0,0)"), "image/png")},
        )
    return CharacterOut(
        id=integer(reply, "id"),
        name=text(reply, "name"),
        images=[text(image) for image in seq(reply, "images")],
        adhoc=flag(reply, "adhoc"),
    )


def _capture_images(monkeypatch: pytest.MonkeyPatch) -> ImageCapture:
    """Replace image generation with a stub that records the prompt and reference images."""
    got = ImageCapture()

    def generate_image(req: ImageRequest) -> tuple[list[tuple[bytes, str]], float | None]:
        got.sent_prompt = req.prompt
        got.input_images = [file_to_data_url(p) for p in req.ref_paths] or None
        return [(png_bytes(), "image/png")], None

    monkeypatch.setattr(openrouter, "generate_image", generate_image)
    return got


def _capture_chat(monkeypatch: pytest.MonkeyPatch) -> ChatCapture:
    """Replace the chat stream with a stub that records messages and tools and answers "Hi"."""
    seen = ChatCapture()

    def stream_chat(model: str, messages: Messages, options: StreamOptions | None = None) -> Iterator[ChatChunk]:
        seen.messages = messages
        seen.tools = options.tools if options else None
        return text_chunks("Hi")

    monkeypatch.setattr(openrouter, "stream_chat", stream_chat)
    return seen


def _system_texts(seen: ChatCapture) -> list[str]:
    """The text of every system message the chat model was sent."""
    return [str(dig(m, "content")) for m in seen.messages if dig(m, "role") == "system"]


def _item(ev: Events) -> dict[str, JsonValue]:
    """The first media item of the last event's message."""
    return obj(ev[-1], "message", "media", 0)


def _params(ev: Events) -> dict[str, JsonValue]:
    """The generation params of the first media item of the last event's message."""
    return obj(_item(ev), "params")


def _find_tool(tools: Tools, name: str) -> dict[str, JsonValue]:
    """The tool definition called ``name``."""
    return next(t for t in must(tools) if dig(t, "function", "name") == name)


def _post(client: TestClient, conv: ConversationOut, content: str, **extra: JsonValue) -> Response:
    """Send a chat message in the conversation."""
    return client.post(f"/api/chat/conversations/{conv['id']}/messages", json={"content": content, **SETTINGS, **extra})


class TestManagement:
    """Tests for management."""

    def test_crud(self, client: TestClient) -> None:
        """Test that crud."""
        c = _make(client, images=2)
        assert c["name"] == "Linh"
        assert len(c["images"]) == 2
        assert c["adhoc"] is False
        img = client.get(f"/api/characters/{c['id']}/images/{c['images'][0]}")
        assert img.status_code == 200
        assert img.headers["content-type"] == "image/png"

        r = client.patch(f"/api/characters/{c['id']}", json={"name": " Linh Tran ", "images": [c["images"][1]]})
        assert text(r, "name") == "Linh Tran"
        assert dig(r, "images") == [c["images"][1]]
        # The dropped image's file is gone
        assert client.get(f"/api/characters/{c['id']}/images/{c['images'][0]}").status_code == 404

        assert client.delete(f"/api/characters/{c['id']}").status_code == 200
        assert client.get(f"/api/characters/{c['id']}").status_code == 404

    def test_unknown_image_in_reorder_is_rejected(self, client: TestClient) -> None:
        """Test that unknown image in reorder is rejected."""
        c = _make(client)
        assert client.patch(f"/api/characters/{c['id']}", json={"images": ["nope.png"]}).status_code == 400

    def test_image_limit(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that image limit."""
        monkeypatch.setattr(characters_mod, "MAX_IMAGES", 1)
        c = _make(client)
        r = client.post(f"/api/characters/{c['id']}/images", files={"file": ("a.png", png_bytes(), "image/png")})
        assert r.status_code == 400

    def test_copy_image_from_chat(self, client: TestClient, conv: ConversationOut, chat: None) -> None:
        """Test that copy image from chat."""
        (chat_pkg.conversation_dir(conv["id"]) / "g.png").write_bytes(png_bytes())
        c = _make(client, images=0)
        r = client.post(
            f"/api/characters/{c['id']}/images/from-chat", json={"conversation_id": conv["id"], "file": "g.png"}
        )
        assert len(seq(r, "images")) == 1
        bad = client.post(
            f"/api/characters/{c['id']}/images/from-chat", json={"conversation_id": conv["id"], "file": "../x.png"}
        )
        assert bad.status_code == 400

    def test_adhoc_characters_belong_to_their_chat(
        self, client: TestClient, conv: ConversationOut, db: MetadataDB
    ) -> None:
        """Test that adhoc characters belong to their chat."""
        other_id = text(client.post("/api/chat/conversations", json={}), "id")
        saved = _make(client, name="Saved", images=0)
        adhoc = _make(client, name="Adhoc", images=0, conversation_id=conv["id"])
        assert adhoc["adhoc"] is True
        # Created in a chat = attached to it
        assert must(db.get_conversation(conv["id"])).character_ids == [adhoc["id"]]

        def names(q: str) -> list[str]:
            return [text(c, "name") for c in seq(client.get(f"/api/characters{q}"), "characters")]

        assert names(f"?conversation_id={conv['id']}") == ["Adhoc", "Saved"]
        assert names(f"?conversation_id={other_id}") == ["Saved"]
        assert names("?include_adhoc=true") == ["Adhoc", "Saved"]
        assert saved["adhoc"] is False

    def test_promote(self, client: TestClient, conv: ConversationOut) -> None:
        """Test that promote."""
        adhoc = _make(client, images=0, conversation_id=conv["id"])
        r = client.post(f"/api/characters/{adhoc['id']}/promote")
        assert flag(r, "adhoc") is False
        assert dig(r, "conversation_id") is None
        # Promoted characters survive their chat
        client.delete(f"/api/chat/conversations/{conv['id']}")
        assert client.get(f"/api/characters/{adhoc['id']}").status_code == 200

    def test_deleting_a_chat_deletes_its_adhoc_characters(self, client: TestClient, conv: ConversationOut) -> None:
        """Test that deleting a chat deletes its adhoc characters."""
        adhoc = _make(client, conversation_id=conv["id"])
        client.delete(f"/api/chat/conversations/{conv['id']}")
        assert client.get(f"/api/characters/{adhoc['id']}").status_code == 404

    def test_attach_to_chat(self, client: TestClient, conv: ConversationOut) -> None:
        """Test that attach to chat."""
        c = _make(client, images=0)
        r = client.patch(f"/api/chat/conversations/{conv['id']}", json={"character_ids": [c["id"]]})
        assert dig(r, "character_ids") == [c["id"]]
        assert client.patch(f"/api/chat/conversations/{conv['id']}", json={"character_ids": [999]}).status_code == 400
        # Deleting a character detaches it
        client.delete(f"/api/characters/{c['id']}")
        assert dig(client.get(f"/api/chat/conversations/{conv['id']}"), "conversation", "character_ids") == []


class TestInChat:
    """Tests for in chat."""

    def _attach(self, client: TestClient, conv: ConversationOut, *chars: CharacterOut) -> None:
        client.patch(f"/api/chat/conversations/{conv['id']}", json={"character_ids": [c["id"] for c in chars]})

    def test_chat_model_is_told_and_tool_lists_names(
        self, client: TestClient, conv: ConversationOut, chat: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that chat model is told and tool lists names."""
        linh = _make(client)
        self._attach(client, conv, linh)
        seen = _capture_chat(monkeypatch)
        sse_events(_post(client, conv, "hi"))
        system = " ".join(_system_texts(seen))
        assert "Linh: Short black hair, red scarf" in system
        image_tool = _find_tool(seen.tools, "generate_image")
        assert dig(image_tool, "function", "parameters", "properties", "characters", "items", "enum") == ["Linh"]

    def test_named_character_sends_description_and_images(
        self, client: TestClient, conv: ConversationOut, chat: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that named character sends description and images."""
        linh, bao = _make(client, images=2), _make(client, name="Bao", description="Tall", images=1)
        self._attach(client, conv, linh, bao)
        replies = iter(
            [
                tool_chunks("generate_image", {"prompt": "Linh at the beach", "characters": ["linh"]}, text="Here."),
                text_chunks("Done."),
            ]
        )
        monkeypatch.setattr(openrouter, "stream_chat", stub(lambda: next(replies)))
        got = _capture_images(monkeypatch)
        ev = sse_events(_post(client, conv, "go"))
        item = _item(ev)
        assert item["prompt"] == "Linh at the beach"  # stored as the model wrote it
        assert "Linh: Short black hair" in got.prompt
        assert "Bao" not in got.prompt
        assert dig(item, "params", "refs") == [f"char:{linh['id']}/{f}" for f in linh["images"]]
        assert dig(item, "params", "characters") == [linh["id"]]
        assert len(must(got.input_images)) == 2

    def _overlapping_names(self, client: TestClient, conv: ConversationOut) -> tuple[CharacterOut, CharacterOut]:
        chloe = _make(client, name="Chloe", description="Slim")
        muscle = _make(client, name="Chloe Muscle", description="Bodybuilder")
        self._attach(client, conv, muscle)
        return chloe, muscle

    def _attached_ids(self, client: TestClient, conv: ConversationOut) -> list[JsonValue]:
        return seq(client.get(f"/api/chat/conversations/{conv['id']}"), "conversation", "character_ids")

    def test_short_name_means_the_attached_character_in_auto_mode(
        self, client: TestClient, conv: ConversationOut, chat: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that short name means the attached character in auto mode."""
        _chloe, muscle = self._overlapping_names(client, conv)
        # The model calls her by the short name, in the argument and its prompt
        replies = iter(
            [
                tool_chunks("generate_image", {"prompt": "Chloe flexing", "characters": ["Chloe"]}, text="Here."),
                text_chunks("Done."),
            ]
        )
        monkeypatch.setattr(openrouter, "stream_chat", stub(lambda: next(replies)))
        got = _capture_images(monkeypatch)
        ev = sse_events(_post(client, conv, "create an image of chloe"))
        assert _params(ev)["characters"] == [muscle["id"]]
        assert "Bodybuilder" in got.prompt
        assert "Slim" not in got.prompt
        assert self._attached_ids(client, conv) == [muscle["id"]]

    def test_short_name_is_ignored_when_ambiguous(
        self, client: TestClient, conv: ConversationOut, chat: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that short name is ignored when ambiguous."""
        a, b = _make(client, name="Chloe Muscle"), _make(client, name="Chloe Slim")
        self._attach(client, conv, a, b)
        replies = iter(
            [tool_chunks("generate_image", {"prompt": "Chloe waving", "characters": ["Chloe"]}), text_chunks("Done.")]
        )
        monkeypatch.setattr(openrouter, "stream_chat", stub(lambda: next(replies)))
        _capture_images(monkeypatch)
        ev = sse_events(_post(client, conv, "go"))
        assert "characters" not in _params(ev)

    def test_full_name_in_prompt_does_not_also_match_the_shorter_one(
        self, client: TestClient, conv: ConversationOut, chat: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that full name in prompt does not also match the shorter one."""
        chloe, muscle = _make(client, name="Chloe"), _make(client, name="Chloe Muscle")
        self._attach(client, conv, chloe, muscle)
        replies = iter([tool_chunks("generate_image", {"prompt": "Chloe Muscle at the gym"}), text_chunks("Done.")])
        monkeypatch.setattr(openrouter, "stream_chat", stub(lambda: next(replies)))
        _capture_images(monkeypatch)
        ev = sse_events(_post(client, conv, "go"))
        assert _params(ev)["characters"] == [muscle["id"]]

    def test_image_mode_uses_every_attached_character(
        self, client: TestClient, conv: ConversationOut, chat: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that image mode uses every attached character."""
        linh, bao = _make(client), _make(client, name="Bao", images=1)
        self._attach(client, conv, linh, bao)
        got = _capture_images(monkeypatch)
        ev = sse_events(_post(client, conv, "both at the park", mode="image"))
        assert _params(ev)["refs"] == [
            f"char:{linh['id']}/{linh['images'][0]}",
            f"char:{bao['id']}/{bao['images'][0]}",
        ]
        assert "Linh:" in got.prompt
        assert "- Bao" in got.prompt

    def test_main_character_images_come_before_pins_and_recent_picks(
        self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The priority when a model takes fewer images than that (see TestReferenceCaps)."""
        linh = _make(client)
        self._attach(client, conv, linh)
        (chat_pkg.conversation_dir(conv["id"]) / "g.png").write_bytes(png_bytes())
        db.add_chat_message(conv["id"], "user", "x")
        msg = db.add_chat_message(
            conv["id"],
            "assistant",
            "",
            media=[
                {"id": "g", "kind": "image", "source": "generated", "status": "done", "file": "g.png", "prompt": "p"}
            ],
        )
        client.post(f"/api/chat/messages/{msg.id}/media/g/pin", json={"pinned": True})
        replies = iter([tool_chunks("generate_image", {"prompt": "Linh", "characters": ["Linh"]}), text_chunks("ok")])
        monkeypatch.setattr(openrouter, "stream_chat", stub(lambda: next(replies)))
        _capture_images(monkeypatch)
        ev = sse_events(_post(client, conv, "go"))
        assert _params(ev)["refs"] == [f"char:{linh['id']}/{linh['images'][0]}", "g.png"]

    def test_character_refs_are_shared_round_robin(self, chat: None, client: TestClient) -> None:
        """Test that character refs are shared round robin."""
        a, b = _make(client, name="A", images=3), _make(client, name="B", images=3)

        refs = characters_mod.reference_refs(characters_mod.load([a["id"], b["id"]]), 3)
        assert refs == [
            f"char:{a['id']}/{a['images'][0]}",
            f"char:{b['id']}/{b['images'][0]}",
            f"char:{a['id']}/{a['images'][1]}",
        ]

    def test_video_mode_does_not_use_characters(
        self, client: TestClient, conv: ConversationOut, chat: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that video mode does not use characters."""
        linh = _make(client)
        self._attach(client, conv, linh)
        sent: list[str] = []

        def submit_video(req: VideoRequest) -> VideoJob:
            sent.append(req.prompt)
            return {"id": "job1"}

        monkeypatch.setattr(openrouter, "submit_video", submit_video)
        sse_events(_post(client, conv, "Linh dancing", mode="video"))
        assert sent[-1] == "Linh dancing"

    def test_image_model_without_references_does_not_use_characters(
        self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that image model without references does not use characters."""
        chat_catalogue.seed_models(
            {"text": [], "video": [], "image": [{"id": "i/model", "input_modalities": ["text"]}]}
        )
        linh = _make(client)
        self._attach(client, conv, linh)
        got = _capture_images(monkeypatch)
        sse_events(_post(client, conv, "Linh on a bike", mode="image"))
        assert got.prompt == "Linh on a bike"
        # Still attached, for when a model that can use it is picked again
        assert must(db.get_conversation(conv["id"])).character_ids == [linh["id"]]

    def test_chat_model_without_tools_is_not_told_in_auto(
        self, client: TestClient, conv: ConversationOut, chat: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that chat model without tools is not told in auto."""
        chat_catalogue.seed_models(
            {
                "image": [],
                "video": [],
                "text": [{"id": "t/model", "supports_tools": False, "input_modalities": ["text"]}],
            },
        )
        self._attach(client, conv, _make(client))
        seen = _capture_chat(monkeypatch)
        sse_events(_post(client, conv, "hi"))
        assert not any("Linh" in system for system in _system_texts(seen))

    def test_chat_mode_tells_the_chat_model(
        self, client: TestClient, conv: ConversationOut, chat: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that chat mode tells the chat model."""
        self._attach(client, conv, _make(client))
        seen = _capture_chat(monkeypatch)
        sse_events(_post(client, conv, "hi", mode="text"))
        assert any("Linh: Short black hair" in system for system in _system_texts(seen))


class TestUseByName:
    """Only characters the user attached are used — a name coming up never attaches one."""

    def test_model_is_not_told_about_unattached_characters(
        self, client: TestClient, conv: ConversationOut, chat: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that model is not told about unattached characters."""
        _make(client, name="Linh")
        seen = _capture_chat(monkeypatch)
        sse_events(_post(client, conv, "hi"))
        assert "Linh" not in json.dumps(seen.messages)
        assert "Linh" not in json.dumps(seen.tools)

    def test_naming_an_unattached_character_neither_uses_nor_attaches_it(
        self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that naming an unattached character neither uses nor attaches it."""
        _make(client)
        replies = iter(
            [
                tool_chunks("generate_image", {"prompt": "Linh at the beach", "characters": ["Linh"]}),
                text_chunks("Here she is."),
            ]
        )
        monkeypatch.setattr(openrouter, "stream_chat", stub(lambda: next(replies)))
        got = _capture_images(monkeypatch)
        ev = sse_events(_post(client, conv, "use Linh, at the beach"))
        assert "Short black hair" not in got.prompt
        assert not got.input_images
        assert not any(dig(e, "type") == "characters" for e in ev)
        assert must(db.get_conversation(conv["id"])).character_ids == []

    def test_image_mode_ignores_unattached_names(
        self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that image mode ignores unattached names."""
        _make(client)
        _capture_images(monkeypatch)
        ev = sse_events(_post(client, conv, "linh on a bike", mode="image"))
        assert "characters" not in _params(ev)
        assert must(db.get_conversation(conv["id"])).character_ids == []

    def test_name_in_the_prompt_counts_when_the_model_forgets_the_argument(
        self, client: TestClient, conv: ConversationOut, chat: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that name in the prompt counts when the model forgets the argument."""
        linh = _make(client)
        client.patch(f"/api/chat/conversations/{conv['id']}", json={"character_ids": [linh["id"]]})
        replies = iter([tool_chunks("generate_image", {"prompt": "Linh reading in a café"}), text_chunks("Done.")])
        monkeypatch.setattr(openrouter, "stream_chat", stub(lambda: next(replies)))
        _capture_images(monkeypatch)
        ev = sse_events(_post(client, conv, "go"))
        assert _params(ev)["characters"] == [linh["id"]]

    def test_create_character_from_the_latest_image_then_draw_them(
        self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that create character from the latest image then draw them."""
        (chat_pkg.conversation_dir(conv["id"]) / "g.png").write_bytes(png_bytes())
        db.add_chat_message(conv["id"], "user", "draw a girl")
        db.add_chat_message(
            conv["id"],
            "assistant",
            "Here.",
            media=[
                {
                    "id": "g",
                    "kind": "image",
                    "source": "generated",
                    "status": "done",
                    "file": "g.png",
                    "prompt": "a girl",
                }
            ],
        )
        tools_seen: list[Tools] = []
        replies = iter(
            [
                tool_chunks("create_character", {"name": "Mai", "description": "Freckles, yellow raincoat"}),
                tool_chunks("generate_image", {"prompt": "Mai in the rain", "characters": ["Mai"]}, call_id="c2"),
                text_chunks("Here's Mai again."),
            ]
        )

        def stream(model: str, messages: Messages, options: StreamOptions | None = None) -> Iterator[ChatChunk]:
            tools_seen.append(options.tools if options else None)
            return next(replies)

        monkeypatch.setattr(openrouter, "stream_chat", stream)
        got = _capture_images(monkeypatch)
        ev = sse_events(_post(client, conv, "make her a character called Mai and draw her in the rain"))
        mai = next(c for c in db.list_characters() if c.name == "Mai")
        assert mai.conversation_id == conv["id"]
        assert len(mai.images) == 1
        # The second round's tool offers Mai by name
        enum = _find_tool(tools_seen[1], "generate_image")
        assert "Mai" in seq(enum, "function", "parameters", "properties", "characters", "items", "enum")
        assert "Freckles" in got.prompt
        assert _params(ev)["refs"] == [f"char:{mai.id}/{mai.images[0]}"]

    def _chat_image(self, chat: None, conv: ConversationOut, db: MetadataDB) -> None:
        (chat_pkg.conversation_dir(conv["id"]) / "g.png").write_bytes(png_bytes())
        db.add_chat_message(conv["id"], "user", "draw a girl")
        db.add_chat_message(
            conv["id"],
            "assistant",
            "Here.",
            media=[{"id": "g", "kind": "image", "source": "generated", "status": "done", "file": "g.png"}],
        )

    def _run(
        self, client: TestClient, conv: ConversationOut, monkeypatch: pytest.MonkeyPatch, *calls: Iterator[ChatChunk]
    ) -> list[dict[str, JsonValue]]:
        replies = iter([*calls, text_chunks("Done.")])
        results: list[dict[str, JsonValue]] = []

        def stream(model: str, messages: Messages, options: StreamOptions | None = None) -> Iterator[ChatChunk]:
            results.extend(
                as_object(cast("object", json.loads(text(m, "content")))) for m in messages if dig(m, "role") == "tool"
            )
            return next(replies)

        monkeypatch.setattr(openrouter, "stream_chat", stream)
        sse_events(_post(client, conv, "go"))
        return results

    def test_create_character_needs_an_image(
        self, client: TestClient, conv: ConversationOut, chat: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that create character needs an image."""
        results = self._run(client, conv, monkeypatch, tool_chunks("create_character", {"name": "Mai"}))
        assert "no image" in text(results[0], "error")

    def test_a_library_name_doesnt_stop_a_chat_making_its_own(
        self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Names needn't be unique: a library Linh not in this chat is someone else."""
        library = _make(client, name="Linh")
        self._chat_image(chat, conv, db)
        results = self._run(client, conv, monkeypatch, tool_chunks("create_character", {"name": "Linh"}))
        assert results[0]["ok"]
        linhs = [c for c in db.list_characters() if c.name == "Linh"]
        assert len(linhs) == 2
        own = next(c for c in linhs if c.id != library["id"])
        assert own.conversation_id == conv["id"]

    def test_a_name_already_in_this_chat_is_used_not_made_again(
        self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that the model is told to use the chat's Linh rather than making another."""
        linh = _make(client, name="Linh")
        client.patch(f"/api/chat/conversations/{conv['id']}", json={"character_ids": [linh["id"]]})
        self._chat_image(chat, conv, db)
        results = self._run(client, conv, monkeypatch, tool_chunks("create_character", {"name": "linh"}))
        assert "already one of this chat's characters" in text(results[0], "error")
        assert len([c for c in db.list_characters() if c.name == "Linh"]) == 1

    def test_a_shared_name_means_the_chats_own(self, db: MetadataDB) -> None:
        """A library Linh attached beside the chat's own Linh: "Linh" means the chat's."""
        lib = db.create_character("Linh")
        own = db.create_character("Linh", conversation_id="c1")
        assert characters_mod.named([lib, own], ["linh"]) == [own]
        assert characters_mod.mentioned([lib, own], "Linh waves") == [own]


def _pin_media(n: int) -> list[dict[str, JsonValue]]:
    """``n`` pinned generated-image media items, p0 to p{n-1}."""
    return [
        {
            "id": f"p{i}",
            "kind": "image",
            "source": "generated",
            "status": "done",
            "file": f"p{i}.png",
            "prompt": "x",
            "pinned": True,
        }
        for i in range(n)
    ]


class TestReferenceCaps:
    """Chat images are capped by the image slider (default 6); character images never are."""

    def test_every_character_image_is_sent_beyond_the_chat_cap(
        self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that every character image is sent beyond the chat cap."""
        linh, bao = _make(client, images=5), _make(client, name="Bao", images=4)
        client.patch(f"/api/chat/conversations/{conv['id']}", json={"character_ids": [linh["id"], bao["id"]]})
        # 8 pinned chat images: only the slider's number of them go
        db.add_chat_message(conv["id"], "user", "pics")
        for i in range(8):
            (chat_pkg.conversation_dir(conv["id"]) / f"p{i}.png").write_bytes(png_bytes())
        db.add_chat_message(conv["id"], "assistant", "ok", media=_pin_media(8))
        got = _capture_images(monkeypatch)
        ev = sse_events(_post(client, conv, "both", mode="image"))
        refs = [text(r) for r in seq(_params(ev), "refs")]
        char_refs = [r for r in refs if r.startswith("char:")]
        assert len(char_refs) == 9  # all 5 + 4
        assert char_refs[:2] == [f"char:{linh['id']}/{linh['images'][0]}", f"char:{bao['id']}/{bao['images'][0]}"]
        assert len(refs) - len(char_refs) == chat_constants.DEFAULT_IMAGE_LIMIT
        assert len(must(got.input_images)) == 9 + chat_constants.DEFAULT_IMAGE_LIMIT

    def test_slider_raises_the_chat_image_cap(
        self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that slider raises the chat image cap."""
        db.add_chat_message(conv["id"], "user", "pics")
        for i in range(8):
            (chat_pkg.conversation_dir(conv["id"]) / f"p{i}.png").write_bytes(png_bytes())
        db.add_chat_message(conv["id"], "assistant", "ok", media=_pin_media(8))
        monkeypatch.setattr(openrouter, "generate_image", stub(lambda: ([(png_bytes(), "image/png")], None)))
        ev = sse_events(_post(client, conv, "go", mode="image", image_limit=None))
        assert len(seq(_params(ev), "refs")) == 8

    def _pins(self, chat: None, db: MetadataDB, conv: ConversationOut, n: int) -> None:
        db.add_chat_message(conv["id"], "user", "pics")
        for i in range(n):
            (chat_pkg.conversation_dir(conv["id"]) / f"p{i}.png").write_bytes(png_bytes())
        db.add_chat_message(conv["id"], "assistant", "ok", media=_pin_media(n))

    def _send_image(
        self,
        client: TestClient,
        conv: ConversationOut,
        chat: None,
        monkeypatch: pytest.MonkeyPatch,
        max_refs: int,
        **settings: JsonValue,
    ) -> dict[str, JsonValue]:
        real = chat_catalogue.model_info

        def fake_info(kind: str, mid: str | None) -> chat_catalogue.ModelInfo | None:
            if kind == "image":
                return {"input_modalities": ["text", "image"], "max_refs": max_refs}
            return real(kind, mid)

        # model_info is read in both the turn (ref caps) and generation (modality) modules
        monkeypatch.setattr(chat_turn_base, "model_info", fake_info)
        monkeypatch.setattr(chat_generation, "model_info", fake_info)
        monkeypatch.setattr(openrouter, "generate_image", stub(lambda: ([(png_bytes(), "image/png")], None)))
        return _params(sse_events(_post(client, conv, "go", mode="image", **settings)))

    def test_a_model_maximum_keeps_room_for_chat_images(
        self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Each character's main image first, then pins, then the characters' other images."""
        a, b = _make(client, name="A", images=3), _make(client, name="B", images=3)
        client.patch(f"/api/chat/conversations/{conv['id']}", json={"character_ids": [a["id"], b["id"]]})
        self._pins(chat, db, conv, 2)
        params = self._send_image(client, conv, chat, monkeypatch, max_refs=6)

        def ref(c: CharacterOut, i: int) -> str:
            return f"char:{c['id']}/{c['images'][i]}"

        assert params["refs"] == [ref(a, 0), ref(b, 0), "p0.png", "p1.png", ref(a, 1), ref(b, 1)]
        assert params["refs_dropped"] == [ref(a, 2), ref(b, 2)]

    def test_composer_picks_switch_references_on_and_off(
        self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that composer picks switch references on and off."""
        a = _make(client, name="A", images=3)
        client.patch(f"/api/chat/conversations/{conv['id']}", json={"character_ids": [a["id"]]})
        self._pins(chat, db, conv, 2)

        def ref(i: int) -> str:
            return f"char:{a['id']}/{a['images'][i]}"

        choices: dict[str, JsonValue] = {"on": [ref(2), "not-a-candidate.png"], "off": [ref(0), "p1.png"]}
        params = self._send_image(client, conv, chat, monkeypatch, max_refs=2, ref_choices=choices)
        # The forced one goes first, then the (new) main image; switched-off ones never go
        assert params["refs"] == [ref(2), ref(1)]
        assert params["refs_dropped"] == ["p0.png"]
        settings = dig(client.get(f"/api/chat/conversations/{conv['id']}"), "conversation", "settings", "ref_choices")
        assert settings == choices  # remembered with the chat

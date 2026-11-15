"""Chat images through OpenRouter: conversational models, references and the image stream."""

import base64
import json
import socket
import threading
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import ClassVar, Self

import httpx
import pytest
from fastapi.testclient import TestClient

import web.chat as chat_pkg
from tests import jsonpath as jp
from tests.chat_fixtures import SETTINGS, ConversationOut, png_bytes, sse_events, text_chunks, tool_chunks
from tests.chat_support import ChatImageSpy, ImageApiSpy, StreamSpy
from tests.errors import server_disconnected
from tests.stubs import stub
from web.chat import catalogue as chat_catalogue
from web.chat import tools as chat_tools
from web.core import request_log
from web.core.metadata import MetadataDB
from web.providers import ImageRequest, openrouter
from web.types import Catalogue, JsonValue

pytest_plugins = ["tests.chat_fixtures"]


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
    ) -> tuple[ImageApiSpy, dict[str, JsonValue]]:
        replies = iter([tool_chunks("generate_image", tool_args, text="Next scene."), text_chunks("Done.")])
        monkeypatch.setattr(openrouter, "stream_chat", stub(lambda: next(replies)))
        got = ImageApiSpy()
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
        got = ImageApiSpy()
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
        monkeypatch.setattr(openrouter, "generate_image", ImageApiSpy())
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
        seen = StreamSpy(lambda: text_chunks("ok"))
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

    def _fake_chat_image(self, chat: None, monkeypatch: pytest.MonkeyPatch) -> ChatImageSpy:
        got = ChatImageSpy(cost=0.04)
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
        images, cost = openrouter.generate_image(ImageRequest("x/img", "a fox"))
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

    def test_reference_images_are_cut_short_in_the_log(
        self, chat: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Test that reference images are cut short in the log."""
        lines = ["event: image_generation.completed", "data: " + json.dumps({"b64_json": self._b64()}), ""]
        monkeypatch.setattr(openrouter.http_client, "stream", stub(lambda: self._Stream(lines)))
        request_log.forget_last()
        ref = tmp_path / "ref.png"
        ref.write_bytes(b"A" * 3100)  # sent inline as a data URL, logged as its size
        openrouter.generate_image(ImageRequest("x/img", "a fox", ref_paths=[ref]))
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
        images, _ = openrouter.generate_image(ImageRequest("x/img", "a fox"))
        assert len(images) == 1

    def test_error_event_raises(self, chat: None, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that error event raises."""
        lines = ["event: error", "data: " + json.dumps({"error": {"message": "flagged by moderation"}}), ""]
        monkeypatch.setattr(openrouter.http_client, "stream", stub(lambda: self._Stream(lines)))
        with pytest.raises(openrouter.OpenRouterError, match="flagged"):
            openrouter.generate_image(ImageRequest("x/img", "a fox"))

    def test_plain_json_answer_still_works(self, chat: None, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that plain json answer still works."""
        body = {"data": [{"b64_json": self._b64(), "media_type": "image/png"}], "usage": {"cost": 0.01}}
        monkeypatch.setattr(
            openrouter.http_client,
            "stream",
            stub(lambda: self._Stream([], content_type="application/json", body=body)),
        )
        images, cost = openrouter.generate_image(ImageRequest("x/img", "a fox"))
        assert len(images) == 1
        assert cost == 0.01

    def test_stream_without_an_image_raises(self, chat: None, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that stream without an image raises."""
        monkeypatch.setattr(openrouter.http_client, "stream", stub(lambda: self._Stream(["data: [DONE]"])))
        with pytest.raises(openrouter.OpenRouterError, match="no images"):
            openrouter.generate_image(ImageRequest("x/img", "a fox"))

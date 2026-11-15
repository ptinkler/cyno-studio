"""Chat turns: streaming, tool rounds, context, stalls, estimates and charges."""

import json
import threading
import time as _t
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Self

import pytest
from fastapi.testclient import TestClient

import web.chat as chat_pkg
from tests import jsonpath as jp
from tests.chat_fixtures import SETTINGS, ConversationOut, png_bytes, sse_events, text_chunks, tool_chunks
from tests.chat_support import FakeImages, FakeStream, FakeVideoSubmit, PollerStarts, StreamSpy, loads_object
from tests.errors import InsufficientCreditsError, SeedOverloadedError, UpstreamTimeoutError
from tests.jsonpath import dig, rows, seq, text
from tests.stubs import stub
from web.chat import catalogue as chat_catalogue
from web.chat import constants as chat_constants
from web.chat import helpers as chat_helpers
from web.chat import polling as chat_polling
from web.chat import tools as chat_tools
from web.core.metadata import MetadataDB, reset_tenant, set_tenant
from web.providers import ImageRequest, StreamOptions, openrouter
from web.providers.pollo import estimate as pollo_estimate
from web.providers.pollo.engine._shared import Payload
from web.types import ChatChunk, JsonValue

pytest_plugins = ["tests.chat_fixtures"]


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

        That means tools are offered, and the prompt's mode tag follows it.
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
            list(openrouter.stream_chat("m", [], StreamOptions(max_seconds=0.2)))
        assert e.value.status == 504

    def test_stop_is_noticed_during_keepalives(self, chat: None, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that stop is noticed during keepalives."""
        monkeypatch.setattr(openrouter.http_client, "stream", stub(lambda: self._FakeStream(self._keepalives())))
        stop = threading.Event()
        threading.Timer(0.1, stop.set).start()
        t0 = _t.monotonic()
        assert list(openrouter.stream_chat("m", [], StreamOptions(should_stop=stop.is_set))) == []
        assert _t.monotonic() - t0 < 2


class TestModelDecides:
    """The app never adds instructions or extra calls to steer the model."""

    def test_no_extra_call_when_model_skips_the_tool(
        self, client: TestClient, conv: ConversationOut, chat: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that no extra call when model skips the tool."""
        calls = StreamSpy(lambda: text_chunks("A story, and here's the photo."))
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
        seen = StreamSpy(lambda: text_chunks("ok"))
        monkeypatch.setattr(openrouter, "stream_chat", seen)
        sse_events(
            client.post(
                f"/api/chat/conversations/{conv['id']}/messages", json={"content": "hi", "history_limit": 3, **SETTINGS}
            )
        )

        today = datetime.now().astimezone().strftime("%A %d %B %Y")
        assert jp.dig(seen.messages[0], 0, "content") == chat_tools.SYSTEM_PROMPT.format(today=today)


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
        spy = StreamSpy(lambda: next(upcoming))
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

        def image(req: ImageRequest) -> tuple[list[tuple[bytes, str]], float | None]:
            attempts.append(req.prompt)
            if len(attempts) == 1:
                raise UpstreamTimeoutError
            return [(png_bytes(), "image/png")], None

        rounds = iter(
            [
                tool_chunks("generate_image", {"prompt": "first"}, text="Story."),
                tool_chunks("generate_image", {"prompt": "second"}, text="Trying again."),
            ]
        )
        spy = StreamSpy(lambda: next(rounds))
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

        def fake_stream(
            model: str, messages: list[dict[str, JsonValue]], options: StreamOptions | None = None
        ) -> Iterator[ChatChunk]:
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

        def fake_image(req: ImageRequest) -> tuple[list[tuple[bytes, str]], float | None]:
            made.append(req.prompt)
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

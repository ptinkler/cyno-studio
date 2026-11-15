"""Chat media: edits, the library, moderation, regenerate, forks and deleting prompts."""

import json
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import web.characters as characters_mod
import web.chat as chat_pkg
import web.core.config as config
import web.media as media_mod
from tests import jsonpath as jp
from tests.chat_fixtures import SETTINGS, ConversationOut, png_bytes, sse_events, text_chunks, tool_chunks
from tests.chat_support import FakeImages, FakeStream, FakeVideoSubmit, PollerStarts
from tests.jsonpath import dig, integer, must, obj, rows, seq, text
from tests.stubs import stub
from web.chat import catalogue as chat_catalogue
from web.chat import generation as chat_generation
from web.chat import polling as chat_polling
from web.core.metadata import ChatMessage, MetadataDB
from web.providers import openrouter
from web.types import ChatChunk, JsonValue, VideoJob

pytest_plugins = ["tests.chat_fixtures"]


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
            chat_pkg.routes_media.api_chat_media(conv_id, name)
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
        monkeypatch.setattr(chat_pkg.routes_media_items, "_regenerate_worker", stub(lambda: None))
        r = client.post(f"/api/chat/messages/{msg.id}/media/m1/regenerate", json={})
        assert r.status_code == 200
        old, new = jp.must(db.get_chat_message(msg.id)).media
        assert old["file"] == "x.png"
        assert old["status"] == "done"
        assert new["id"] != "m1"
        assert new["status"] == "pending"
        assert not new.get("file")
        assert client.post(f"/api/chat/messages/{msg.id}/media/nope/regenerate", json={}).status_code == 404


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

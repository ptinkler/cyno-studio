"""Chat generation through Pollo: image models, their payloads and the request log."""

import threading
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import ClassVar

import pytest
import requests
from fastapi.testclient import TestClient

import web.chat as chat_pkg
import web.providers.pollo.engine as registry
from tests import jsonpath as jp
from tests.chat_fixtures import SETTINGS, ConversationOut, png_bytes, sse_events, text_chunks, tool_chunks
from tests.chat_support import (
    FakeAudioGenerator,
    FakeGenerator,
    FakeResponse,
    InlineThread,
    PolloCalls,
    RefusingGenerator,
    by_id,
)
from tests.stubs import stub
from web.chat import catalogue as chat_catalogue
from web.chat import generation as chat_generation
from web.chat import helpers as chat_helpers
from web.chat import polling as chat_polling
from web.core import request_log
from web.core.get_task import TaskResult
from web.core.metadata import MetadataDB
from web.providers import openrouter
from web.providers import pollo as pollo_provider
from web.providers.pollo import submit as pollo_submit
from web.providers.pollo import tasks as pollo_tasks
from web.providers.pollo import uploads as pollo_uploads
from web.providers.pollo.engine._shared import Payload
from web.providers.pollo.engine.registry import ModelSpec, PolloGenerator
from web.providers.specs import CostQuery
from web.types import JsonValue

pytest_plugins = ["tests.chat_fixtures"]


class TestPolloImageModels:
    """Pollo image models in chat.

    Pollo is fully mocked — nothing here can reach the real API (which would bill credits).
    """

    POLLO: ClassVar = {**SETTINGS, "image_model": "pollo/seedream"}

    @pytest.fixture
    def pollo(self, chat: None, monkeypatch: pytest.MonkeyPatch, provider_keys: dict[str, str | None]) -> PolloCalls:
        """Provide the pollo fixture."""
        provider_keys["pollo"] = "pollo-test"
        monkeypatch.setattr(pollo_tasks, "POLL_INTERVAL", 0)
        calls = PolloCalls()

        def make_generator(key: str, **kwargs: JsonValue) -> FakeGenerator:
            return FakeGenerator(calls, key, **kwargs)

        def next_statuses(*_args: object, **_kwargs: object) -> list[TaskResult]:
            return next(calls.statuses)

        def download(url: str, timeout: float | None = None, stream: bool = False) -> FakeResponse:
            _ = (timeout, stream)
            return FakeResponse(None, b"mp4-bytes" if url.endswith(".mp4") else png_bytes(), "image/jpeg")

        def upload(path: Path, *_args: object, **_kwargs: object) -> str:
            calls.uploads.append(path.name)
            return f"https://tmp.example/{path.name}"

        monkeypatch.setattr(pollo_submit, "get_image_generator", make_generator)
        monkeypatch.setattr(pollo_submit, "get_video_generator", make_generator)
        monkeypatch.setattr(pollo_tasks, "get_task_status", next_statuses)
        monkeypatch.setattr(pollo_tasks.requests, "get", download)
        monkeypatch.setattr(pollo_uploads.image_hosts, "upload_file", upload)
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
        models = by_id(chat_catalogue.get_models(refresh=True).get("image", []))
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
        monkeypatch.setattr(threading, "Thread", InlineThread)
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
        models = by_id(chat_catalogue.get_models(refresh=True).get("video", []))
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
        """The media item records that its length *was* Auto.

        The composer resolves Auto to a number before sending; otherwise reusing the item's settings would pin whatever
        Auto worked out to.
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
        models = by_id(chat_catalogue.get_models(refresh=True).get("audio", []))
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
        def make_generator(key: str, **kwargs: JsonValue) -> FakeAudioGenerator:
            return FakeAudioGenerator(pollo, key, attrs, **kwargs)

        monkeypatch.setattr(pollo_submit, "get_audio_generator", make_generator)
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
        options: list[dict[str, JsonValue]] = []

        def fake(model: str, query: CostQuery) -> dict[str, JsonValue]:
            _ = model
            kinds.append(query.kind)
            options.append({"prompt": query.prompt, "audio": dict(query.audio or {})})
            return {"credits": 3}

        monkeypatch.setattr(pollo_provider, "estimate_cost", fake)
        r = client.post(
            "/api/chat/estimate",
            json={"model": "pollo/elevenv3", "kind": "audio", "prompt": "hi", "audio_options": {"voice": "v1"}},
        )
        assert jp.decode(r) == {"estimate": {"credits": 3}}
        assert kinds[-1] == "audio"
        assert options[-1]["prompt"] == "hi"
        assert options[-1]["audio"] == {"voice": "v1"}

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

        The card ends in error with the verdict, so no credits land on the item or in spend, and the stored response is
        the verdict, not the "accepted" reply from submitting.
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
        images = by_id(data.get("image", []))
        videos = by_id(data.get("video", []))
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
        monkeypatch.setattr(pollo_submit, "get_video_generator", registry.video_generator)  # the real one
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
        not_served = FakeResponse(
            {"message": "Not found", "code": "NOT_FOUND", "errorCode": "REJECTED"}, status_code=404
        )
        monkeypatch.setattr(pollo_submit, "get_image_generator", stub(lambda: RefusingGenerator(not_served)))
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
        refused = FakeResponse(
            {"message": "This model is not enabled for API access.", "code": "FORBIDDEN"}, status_code=403
        )
        monkeypatch.setattr(pollo_submit, "get_image_generator", stub(lambda: RefusingGenerator(refused)))
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
        images = by_id(chat_catalogue.get_models(refresh=True).get("image", []))
        hidden = {k for k, m in images.items() if m["hidden"]}
        assert hidden == {"pollo/qwenimageflash"}
        # `hidden` carries the reason, shown in the picker behind "Show hidden"
        assert "unavailable" in jp.text(images["pollo/qwenimageflash"], "hidden")
        assert images["pollo/qwenimage3"]["hidden"] is None  # works since its address was fixed
        assert images["pollo/klingv3image"]["hidden"] is None  # confirmed working


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

        assert pollo_tasks.submit_task(Gen()) == "t-9"
        entry = request_log.recent()[0]
        assert entry["provider"] == "pollo"
        assert entry["model"] == "seedance-2-0"
        assert entry["status"] == 200
        assert entry["path"] == "/api/platform/generation/bytedance/seedance-2-0"
        assert entry["request"] == {"input": {"prompt": "waves", "image": "https://host/x.png"}}

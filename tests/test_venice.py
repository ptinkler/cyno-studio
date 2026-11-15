"""Tests for web.providers.venice — Venice text, image and video models in chat (no network)."""

import base64
import contextlib
import io
import json
from collections.abc import Callable, Generator, Sequence
from pathlib import Path
from typing import NamedTuple

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

import web.chat as chat_pkg
import web.providers.venice as v
from tests.chat_fixtures import SETTINGS, ConversationOut, png_bytes, sse_events
from tests.jsonpath import dig, must, number, obj, rows, seq, text
from tests.stubs import stub
from web.chat import catalogue as chat_catalogue
from web.core import request_log
from web.core.metadata import MetadataDB
from web.jsonutil import as_object
from web.providers import StreamOptions, VideoRequest, openrouter
from web.providers.venice import client as venice_client
from web.providers.venice import jobs as venice_jobs
from web.providers.venice_errors import VeniceError
from web.types import JsonValue, ModelEntry

pytest_plugins = ["tests.chat_fixtures"]

MODELS: dict[str, list[dict[str, JsonValue]]] = {
    "text": [
        {
            "id": "llama-big",
            "context_length": 128000,
            "created": 1,
            "model_spec": {
                "name": "Llama Big",
                "availableContextTokens": 128000,
                "pricing": {"input": {"usd": 1.0}, "output": {"usd": 4.0}},
                "capabilities": {"supportsVision": True, "supportsFunctionCalling": True},
            },
        },
        {
            "id": "venice-uncensored",
            "model_spec": {"name": "Venice Uncensored", "uncensored": True, "capabilities": {}},
        },
    ],
    "image": [
        {
            "id": "seedream-v5-pro",
            "model_spec": {
                "name": "Seedream 5 Pro",
                "pricing": {"generation": {"usd": 0.05}},
                "constraints": {"aspectRatios": ["1:1", "16:9"], "resolutions": ["1K", "2K"]},
            },
        },
        {"id": "grok-imagine-image-quality", "model_spec": {"name": "Grok Quality", "constraints": {}}},
        {"id": "lustify-v8", "model_spec": {"name": "Lustify", "uncensored": True, "constraints": {}}},
        {"id": "gone", "model_spec": {"name": "Gone", "offline": True}},
    ],
    "inpaint": [
        {
            "id": "seedream-v5-pro-edit",
            "model_spec": {
                "name": "Seedream Edit",
                "pricing": {"inpaint": {"usd": 0.06}},
                "constraints": {"maxInputImages": 2},
            },
        },
        {"id": "grok-imagine-quality-edit", "model_spec": {"name": "Grok Q Edit", "constraints": {}}},
        {"id": "firered-image-edit", "model_spec": {"name": "FireRed", "constraints": {}}},
        {"id": "qwen-edit-uncensored", "model_spec": {"name": "Qwen Edit", "uncensored": True, "constraints": {}}},
    ],
    "video": [
        {
            "id": "wan-3-0-text-to-video",
            "model_spec": {
                "name": "Wan 3.0",
                "constraints": {
                    "model_type": "text-to-video",
                    "durations": ["2s", "5s", "10s"],
                    "resolutions": ["720p", "1080p"],
                    "aspect_ratios": ["16:9", "9:16"],
                    "audio": True,
                    "audio_configurable": True,
                },
            },
        },
        {
            "id": "wan-3-0-image-to-video",
            "model_spec": {
                "name": "Wan 3.0 I2V",
                "constraints": {
                    "model_type": "image-to-video",
                    "durations": ["5s", "10s"],
                    "resolutions": ["720p"],
                    "aspect_ratios": [],
                    "audio": True,
                    "audio_configurable": True,
                },
            },
        },
        {
            "id": "wan-3-0-reference-to-video",
            "model_spec": {"name": "Wan Ref", "constraints": {"model_type": "image-to-video", "durations": ["5s"]}},
        },
        {
            "id": "flux-3-first-last-frame-to-video",
            "model_spec": {
                "name": "Flux 3 FLF",
                "constraints": {"model_type": "image-to-video", "durations": ["5s", "10s"], "resolutions": ["720p"]},
            },
        },
        {
            "id": "wan-2-7-video-to-video",
            "model_spec": {
                "name": "Wan 2.7 V2V",
                "uncensored": True,
                "constraints": {"model_type": "video", "durations": ["Auto"], "resolutions": ["720p"]},
            },
        },
        {
            "id": "topaz-video-upscale",
            "model_spec": {
                "name": "Topaz",
                "constraints": {"model_type": "video", "durations": ["Auto"], "resolutions": ["2x", "4x"]},
            },
        },
        {
            "id": "ovi-image-to-video",
            "model_spec": {
                "name": "Ovi",
                "uncensored": True,
                "constraints": {
                    "model_type": "image-to-video",
                    "durations": ["5s"],
                    "audio": True,
                    "audio_configurable": False,
                },
            },
        },
    ],
}

QUOTES: dict[str, float] = {
    "wan-3-0-text-to-video": 0.65,
    "ovi-image-to-video": 0.4,
    "wan-3-0-reference-to-video": 0.3,
    "flux-3-first-last-frame-to-video": 0.9,
}


class Call(NamedTuple):
    """One request the code under test sent to the fake Venice."""

    method: str
    path: str
    body: JsonValue
    params: dict[str, str] | None


type Route = httpx.Response | Callable[[JsonValue], httpx.Response]


class FakeVenice:
    """Stands in for venice._client; records requests, answers from `routes`."""

    def __init__(self) -> None:
        """Start with no recorded calls and no canned routes."""
        self.calls: list[Call] = []
        self.routes: dict[str, Route] = {}

    def _answer(self, method: str, url: str, body: JsonValue, params: dict[str, str] | None) -> httpx.Response:
        path = url.split("/api/v1", 1)[1]
        self.calls.append(Call(method, path, body, params))
        if path == "/models":
            return httpx.Response(
                200, json={"data": MODELS[must(params)["type"]]}, headers={"x-venice-balance-usd": "12.5"}
            )
        handler = self.routes.get(path)
        if handler is None:
            pytest.fail(f"unexpected Venice call {method} {path}")
        return handler if isinstance(handler, httpx.Response) else handler(body)

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        timeout: httpx.Timeout | None = None,
        json: JsonValue = None,
        params: dict[str, str] | None = None,
    ) -> httpx.Response:
        """Answer a plain request from the canned routes."""
        del headers, timeout
        return self._answer(method, url, json, params)

    def stream(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        timeout: httpx.Timeout | None = None,
        json: JsonValue = None,
        params: dict[str, str] | None = None,
    ) -> contextlib.AbstractContextManager[httpx.Response]:
        """Answer a streaming request from the canned routes."""
        del headers, timeout
        resp = self._answer(method, url, json, params)

        @contextlib.contextmanager
        def ctx() -> Generator[httpx.Response]:
            yield resp

        return ctx()

    def calls_to(self, path: str) -> list[Call]:
        """The requests sent to ``path``, oldest first."""
        return [c for c in self.calls if c.path == path]

    def body(self, path: str) -> dict[str, JsonValue]:
        """The JSON body of the first request sent to ``path``."""
        return obj(self.calls_to(path)[0].body)


def _quote(body: JsonValue) -> httpx.Response:
    return httpx.Response(200, json={"quote": QUOTES.get(text(body, "model"))})


@pytest.fixture
def venice(
    chat: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, provider_keys: dict[str, str | None]
) -> FakeVenice:
    """Point the venice module at a fake client and return the fake."""
    provider_keys["venice"] = "v-test"
    fake = FakeVenice()
    # Catalogue builds price each video model; tests that queue videos set their own quote
    fake.routes["/video/quote"] = _quote
    monkeypatch.setattr(venice_client, "http", fake)
    monkeypatch.setattr(venice_jobs, "_VIDEO_DIR", tmp_path / "venice-videos")
    v.clear_caches()
    return fake


def _ids(models: Sequence[ModelEntry]) -> list[str]:
    """The ids of catalogue entries without the ``venice/`` prefix."""
    return [text(m, "id")[7:] for m in models]


def _dark_png() -> bytes:
    """A PNG of one dark, not quite black, colour."""
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (20, 20, 30)).save(buf, "PNG")
    return buf.getvalue()


def _attach(client: TestClient, conv: ConversationOut, name: str, color: str = "red") -> JsonValue:
    """Upload a one-colour PNG as a chat attachment and return its stored file name."""
    reply = client.post(
        f"/api/chat/conversations/{conv['id']}/attachments", files={"file": (name, png_bytes(color=color), "image/png")}
    )
    return dig(reply, "file")


def _send(client: TestClient, conv: ConversationOut, content: str, **extra: JsonValue) -> list[dict[str, JsonValue]]:
    """Post a chat message and return the streamed events."""
    return sse_events(
        client.post(f"/api/chat/conversations/{conv['id']}/messages", json={"content": content, **SETTINGS, **extra})
    )


class TestCatalogue:
    """Tests for catalogue."""

    def test_lists_text_models_with_prices_and_tools(self, venice: FakeVenice) -> None:
        """Test that lists text models with prices and tools."""
        unc, m = v.list_models("text")  # uncensored first
        assert m["id"] == "venice/llama-big"
        assert m["name"] == "Venice: Llama Big"
        assert m["uncensored"] is None
        assert unc["uncensored"] is True
        assert m["supports_tools"] is True
        assert m["input_modalities"] == ["text", "image"]
        assert m["prompt_price"] == pytest.approx(1e-6)
        assert m["completion_price"] == pytest.approx(4e-6)

    def test_image_models_pair_with_their_edit_twins(self, venice: FakeVenice) -> None:
        """Test that image models pair with their edit twins."""
        by_id = {text(m, "id"): m for m in v.list_models("image")}
        assert by_id["venice/seedream-v5-pro"]["input_modalities"] == ["text", "image"]
        assert by_id["venice/grok-imagine-image-quality"]["input_modalities"] == ["text", "image"]  # "-image" dropped
        assert by_id["venice/lustify-v8"]["input_modalities"] == ["text"]
        assert by_id["venice/lustify-v8"]["uncensored"] is True
        assert by_id["venice/seedream-v5-pro"]["uncensored"] is None
        assert by_id["venice/qwen-edit-uncensored"]["uncensored"] is True
        assert "edit only" in text(by_id["venice/firered-image-edit"], "name")
        assert "venice/seedream-v5-pro-edit" not in by_id
        assert "venice/gone" not in by_id
        assert not any(k.startswith("_") for m in by_id.values() for k in m)  # internals stay server-side

    def test_video_models_pair_text_and_image_variants(self, venice: FakeVenice) -> None:
        """Test that video models pair text and image variants."""
        by_id = {text(m, "id"): m for m in v.list_models("video")}
        assert set(by_id) == {
            "venice/wan-3-0-text-to-video",
            "venice/ovi-image-to-video",
            "venice/wan-3-0-reference-to-video",
            "venice/flux-3-first-last-frame-to-video",
            "venice/wan-2-7-video-to-video",
            "venice/topaz-video-upscale",
        }
        assert [
            by_id[f"venice/{i}"]["family"]
            for i in ("flux-3-first-last-frame-to-video", "wan-2-7-video-to-video", "topaz-video-upscale")
        ] == ["frames", "video", "upscale"]
        assert by_id["venice/flux-3-first-last-frame-to-video"]["frame_images"] == ["first_frame", "last_frame"]
        assert by_id["venice/wan-2-7-video-to-video"]["video_input"] is True
        ids = [text(m, "id") for m in v.list_models("video")]
        assert all(by_id[i]["uncensored"] for i in ids[:2])
        assert not any(by_id[i]["uncensored"] for i in ids[2:])
        assert by_id["venice/wan-3-0-reference-to-video"]["family"] == "reference"
        assert by_id["venice/wan-3-0-reference-to-video"]["reference_images"] is True
        assert "refs→video" in text(by_id["venice/wan-3-0-reference-to-video"], "name")
        wan = by_id["venice/wan-3-0-text-to-video"]
        assert wan["frame_images"] == ["first_frame"]
        assert wan["durations"] == [2, 5, 10]
        assert wan["generate_audio"] is True
        assert "image→video only" in text(by_id["venice/ovi-image-to-video"], "name")
        assert by_id["venice/ovi-image-to-video"]["uncensored"] is True
        assert wan["uncensored"] is None

    def test_chat_catalogue_includes_venice_alongside_openrouter(
        self, client: TestClient, chat: None, venice: FakeVenice, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that chat catalogue includes venice alongside openrouter."""
        monkeypatch.setattr(openrouter, "list_text_models", stub(lambda: [{"id": "or/text", "name": "OR"}]))
        monkeypatch.setattr(openrouter, "list_image_models", stub(list[ModelEntry]))
        monkeypatch.setattr(openrouter, "list_video_models", stub(list[ModelEntry]))
        data = client.get("/api/chat/models")
        assert [text(m, "id") for m in seq(data, "text")] == ["venice/venice-uncensored", "venice/llama-big", "or/text"]
        assert any(dig(m, "id") == "venice/seedream-v5-pro" for m in seq(data, "image"))

    def test_not_listed_without_a_key(self, venice: FakeVenice, provider_keys: dict[str, str | None]) -> None:
        """Test that not listed without a key."""
        provider_keys["venice"] = None
        assert v.list_models("image") == []
        assert venice.calls == []


class TestPriceOrder:
    """Tests for price order."""

    def test_privacy_level(self, venice: FakeVenice, monkeypatch: pytest.MonkeyPatch) -> None:
        """A pair is only as private as its less private half."""
        monkeypatch.setitem(
            MODELS,
            "image",
            [
                {"id": "own", "model_spec": {"name": "O", "privacy": "private"}},
                {"id": "mixed", "model_spec": {"name": "M", "privacy": "private"}},
            ],
        )
        monkeypatch.setitem(
            MODELS,
            "inpaint",
            [
                {"id": "mixed-edit", "model_spec": {"name": "ME", "privacy": "anonymized"}},
            ],
        )
        got = {text(m, "id")[7:]: m["privacy"] for m in v.list_models("image")}
        assert got["own"] == "private"
        assert got["mixed"] == "anonymized"

    def test_uncensored_first_then_cheapest(self, venice: FakeVenice, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that uncensored first then cheapest."""
        monkeypatch.setitem(
            MODELS,
            "image",
            [
                {
                    "id": "pricey-unc",
                    "model_spec": {"name": "B", "uncensored": True, "pricing": {"generation": {"usd": 0.09}}},
                },
                {
                    "id": "cheap-unc",
                    "model_spec": {"name": "C", "uncensored": True, "pricing": {"generation": {"usd": 0.01}}},
                },
                {
                    "id": "tiered",
                    "model_spec": {
                        "name": "T",
                        "pricing": {"resolutions": {"1K": {"usd": 0.07}, "2K": {"usd": 0.1}}},
                        "constraints": {"resolutions": ["1K", "2K"], "defaultResolution": "1K"},
                    },
                },
                {"id": "cheapest-safe", "model_spec": {"name": "S", "pricing": {"generation": {"usd": 0.005}}}},
                {"id": "unpriced", "model_spec": {"name": "U"}},
            ],
        )
        mine = {"pricey-unc", "cheap-unc", "tiered", "cheapest-safe", "unpriced"}
        models = [m for m in v.list_models("image") if text(m, "id")[7:] in mine]  # edit-only fixtures left out
        assert _ids(models) == ["cheap-unc", "pricey-unc", "cheapest-safe", "tiered", "unpriced"]
        assert models[3]["price"] == {"usd": 0.07, "basis": "1K"}

    def test_tiered_image_is_billed_at_the_resolution_used(
        self, venice: FakeVenice, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that tiered image is billed at the resolution used."""
        monkeypatch.setitem(
            MODELS,
            "image",
            [
                {
                    "id": "tiered",
                    "model_spec": {
                        "name": "T",
                        "pricing": {"resolutions": {"1K": {"usd": 0.07}, "2K": {"usd": 0.1}}},
                        "constraints": {"resolutions": ["1K", "2K"], "defaultResolution": "1K"},
                    },
                }
            ],
        )
        venice.routes["/image/generate"] = httpx.Response(
            200, json={"images": [base64.b64encode(png_bytes()).decode()]}
        )
        assert v.generate_image("venice/tiered", "x", resolution="2K")[1] == 0.1
        assert v.generate_image("venice/tiered", "x")[1] == 0.07

    def test_videos_priced_at_5s_lowest_resolution_and_sorted(self, venice: FakeVenice) -> None:
        """Test that videos priced at 5s lowest resolution and sorted."""
        by_id = {text(m, "id")[7:]: m for m in v.list_models("video")}
        assert by_id["wan-3-0-text-to-video"]["price"] == {"usd": 0.65, "basis": "5s · 720p"}
        wan_quote = next(
            c.body for c in venice.calls_to("/video/quote") if dig(c.body, "model") == "wan-3-0-text-to-video"
        )
        assert wan_quote == {"model": "wan-3-0-text-to-video", "duration": "5s", "resolution": "720p"}
        assert by_id["wan-2-7-video-to-video"]["price"] is None  # depends on the source video
        ids = _ids(v.list_models("video"))
        assert ids.index("ovi-image-to-video") < ids.index("wan-2-7-video-to-video")  # both uncensored: priced first
        assert ids.index("wan-3-0-reference-to-video") < ids.index("wan-3-0-text-to-video")  # 0.30 < 0.65

    def test_quotes_are_cached_across_catalogue_refreshes(self, venice: FakeVenice) -> None:
        """Test that quotes are cached across catalogue refreshes."""
        v.list_models("video")
        n = len(venice.calls_to("/video/quote"))
        v.list_models("video", refresh=True)
        assert len(venice.calls_to("/video/quote")) == n


class TestImages:
    """Tests for images."""

    def test_text_to_image_sends_safe_mode_off(self, venice: FakeVenice) -> None:
        """Test that text to image sends safe mode off."""
        venice.routes["/image/generate"] = httpx.Response(
            200, json={"images": [base64.b64encode(png_bytes()).decode()]}
        )
        images, cost, sent = v.generate_image("venice/seedream-v5-pro", "a fox", aspect_ratio="16:9", resolution="4K")
        body = venice.body("/image/generate")
        assert body["model"] == "seedream-v5-pro"
        assert body["safe_mode"] is False
        assert body["hide_watermark"] is True
        assert body["aspect_ratio"] == "16:9"
        assert "resolution" not in body
        assert images == [(png_bytes(), "image/png")]
        assert cost == 0.05
        assert sent == {"aspect_ratio": "16:9", "resolution": None}

    def test_references_go_to_the_edit_twin_capped_at_its_limit(self, venice: FakeVenice, tmp_path: Path) -> None:
        """Test that references go to the edit twin capped at its limit."""
        refs: list[Path] = []
        for i in range(3):
            p = tmp_path / f"r{i}.png"
            p.write_bytes(png_bytes())
            refs.append(p)
        venice.routes["/image/multi-edit"] = httpx.Response(200, content=b"IMG", headers={"content-type": "image/webp"})
        images, cost, sent = v.generate_image("venice/seedream-v5-pro", "same fox, at night", ref_paths=refs)
        body = venice.body("/image/multi-edit")
        assert body["modelId"] == "seedream-v5-pro-edit"
        assert body["safe_mode"] is False
        assert len(seq(body, "images")) == 2
        assert text(body, "images", 0).startswith("data:image/png;base64,")
        assert images == [(b"IMG", "image/webp")]
        assert cost == 0.06
        assert sent.get("refs_used") == 2

    def test_edit_only_model_needs_a_reference(self, venice: FakeVenice) -> None:
        """Test that edit only model needs a reference."""
        with pytest.raises(VeniceError, match="only edits images"):
            v.generate_image("venice/firered-image-edit", "a fox")

    def test_errors_carry_venices_message(self, venice: FakeVenice) -> None:
        """Test that errors carry venices message."""
        venice.routes["/image/generate"] = httpx.Response(400, json={"error": "Prompt too long"})
        with pytest.raises(VeniceError, match="Venice: Prompt too long"):
            v.generate_image("venice/lustify-v8", "x" * 10)

    def test_chat_image_mode_runs_on_venice(
        self,
        client: TestClient,
        conv: ConversationOut,
        chat: None,
        venice: FakeVenice,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test that chat image mode runs on venice."""
        venice.routes["/image/generate"] = httpx.Response(
            200, json={"images": [base64.b64encode(png_bytes()).decode()]}
        )
        monkeypatch.setattr(openrouter, "generate_image", stub(lambda: pytest.fail("not OpenRouter")))
        ev = _send(client, conv, "a fox", mode="image", image_model="venice/seedream-v5-pro")
        item = obj(ev[-1], "message", "media", 0)
        assert item["status"] == "done"
        assert item["cost"] == 0.05

    def test_content_violation_flag_is_a_moderation_block(self, venice: FakeVenice) -> None:
        """Test that content violation flag is a moderation block."""
        venice.routes["/image/generate"] = httpx.Response(
            200,
            json={"images": [base64.b64encode(png_bytes()).decode()]},
            headers={"x-venice-is-content-violation": "true"},
        )
        with pytest.raises(VeniceError, match="content filter") as e:
            v.generate_image("venice/seedream-v5-pro", "a fox")
        assert e.value.status == 403

    def test_black_image_fails_as_moderated(
        self, client: TestClient, conv: ConversationOut, chat: None, venice: FakeVenice
    ) -> None:
        """Provider filters send a solid black image instead of an error."""
        black = base64.b64encode(png_bytes(color="black")).decode()
        venice.routes["/image/generate"] = httpx.Response(200, json={"images": [black]})
        ev = _send(client, conv, "a fox", mode="image", image_model="venice/seedream-v5-pro")
        item = obj(ev[-1], "message", "media", 0)
        assert item["status"] == "error"
        assert item["moderated"] is True
        assert "black image" in text(item, "error")

    def test_dark_but_not_black_image_is_kept(
        self, client: TestClient, conv: ConversationOut, chat: None, venice: FakeVenice
    ) -> None:
        """Test that dark but not black image is kept."""
        night = base64.b64encode(_dark_png()).decode()
        venice.routes["/image/generate"] = httpx.Response(200, json={"images": [night]})
        ev = _send(client, conv, "a fox at night", mode="image", image_model="venice/seedream-v5-pro")
        assert dig(ev[-1], "message", "media", 0, "status") == "done"

    def test_requests_are_logged_with_images_cut_short(self, venice: FakeVenice, tmp_path: Path) -> None:
        """Test that requests are logged with images cut short."""
        ref = tmp_path / "r.png"
        ref.write_bytes(png_bytes())
        venice.routes["/image/multi-edit"] = httpx.Response(
            422, json={"error": "Your prompt violates the content policy of Venice.ai or the model provider"}
        )
        with pytest.raises(VeniceError) as e:
            v.generate_image("venice/seedream-v5-pro", "a fox", ref_paths=[ref])
        [entry] = request_log.recent()
        assert entry["provider"] == "venice"
        assert entry["path"] == "/image/multi-edit"
        assert entry["model"] == "seedream-v5-pro-edit"
        assert entry["status"] == 422
        assert "content policy" in text(entry, "error")
        request = obj(entry, "request")
        assert request["prompt"] == "a fox"
        assert request["safe_mode"] is False
        assert request["images"] == ["data:image/png;base64,… (0 KB)"]
        response = obj(entry, "response")
        assert response == {"error": "Your prompt violates the content policy of Venice.ai or the model provider"}
        assert request_log.entry_of(e.value) == entry

    def test_failed_card_keeps_the_request_and_the_log_is_readable(
        self, client: TestClient, conv: ConversationOut, chat: None, venice: FakeVenice
    ) -> None:
        """Test that failed card keeps the request and the log is readable."""
        venice.routes["/image/generate"] = httpx.Response(
            422, json={"error": "Your prompt violates the content policy"}
        )
        ev = _send(client, conv, "a fox", mode="image", image_model="venice/seedream-v5-pro")
        item = obj(ev[-1], "message", "media", 0)
        assert item["status"] == "error"
        assert dig(item, "request", "model") == "seedream-v5-pro"
        assert item["response"] == {"error": "Your prompt violates the content policy"}
        log = rows(client.get("/api/chat/request-log"), "entries")
        assert log[0]["request"] == item["request"]
        assert log[0]["response"] == item["response"]
        assert log[0]["status"] == 422

    def test_done_card_keeps_the_request_outside_params(
        self, client: TestClient, conv: ConversationOut, chat: None, venice: FakeVenice
    ) -> None:
        """Test that done card keeps the request outside params."""
        big = base64.b64encode(png_bytes() + b"\0" * 4096).decode()
        venice.routes["/image/generate"] = httpx.Response(200, json={"id": "gen-1", "images": [big]})
        ev = _send(client, conv, "a fox", mode="image", image_model="venice/seedream-v5-pro")
        item = obj(ev[-1], "message", "media", 0)
        assert dig(item, "request", "prompt") == "a fox"
        assert "request" not in obj(item, "params")
        assert dig(item, "response", "id") == "gen-1"
        assert text(item, "response", "images", 0).endswith("KB of base64)")


class TestVideo:
    """Tests for video."""

    def _frame(self, tmp_path: Path) -> Path:
        p = tmp_path / "frame.png"
        p.write_bytes(png_bytes())
        return p

    def test_text_to_video_snaps_duration_and_quotes(self, venice: FakeVenice) -> None:
        """Test that text to video snaps duration and quotes."""
        venice.routes["/video/quote"] = httpx.Response(200, json={"quote": 0.42})
        venice.routes["/video/queue"] = httpx.Response(200, json={"model": "wan-3-0-text-to-video", "queue_id": "q1"})
        job = v.submit_video(
            VideoRequest(
                "venice/wan-3-0-text-to-video",
                "waves",
                duration=7,
                aspect_ratio="16:9",
                resolution="1080p",
                generate_audio=False,
            )
        )
        body = venice.body("/video/queue")
        assert body == {
            "model": "wan-3-0-text-to-video",
            "prompt": "waves",
            "duration": "5s",
            "aspect_ratio": "16:9",
            "resolution": "1080p",
            "audio": False,
        }
        assert job["id"] == "venice:wan-3-0-text-to-video:q1"
        assert job.get("params") == {
            "duration": 5,
            "aspect_ratio": "16:9",
            "resolution": "1080p",
            "generate_audio": False,
        }

    def test_first_frame_switches_to_the_image_to_video_twin(self, venice: FakeVenice, tmp_path: Path) -> None:
        """Test that first frame switches to the image to video twin."""
        venice.routes["/video/quote"] = httpx.Response(500, json={"error": "quote down"})  # optional
        venice.routes["/video/queue"] = httpx.Response(200, json={"queue_id": "q2"})
        job = v.submit_video(
            VideoRequest(
                "venice/wan-3-0-text-to-video",
                "she waves",
                duration=10,
                aspect_ratio="16:9",
                resolution="1080p",
                first_frame=self._frame(tmp_path),
            )
        )
        body = venice.body("/video/queue")
        assert body["model"] == "wan-3-0-image-to-video"
        assert text(body, "image_url").startswith("data:image/png")
        assert "aspect_ratio" not in body
        assert "resolution" not in body
        assert body["duration"] == "10s"
        assert job["id"] == "venice:wan-3-0-image-to-video:q2"

    def test_image_only_model_needs_a_frame(self, venice: FakeVenice) -> None:
        """Test that image only model needs a frame."""
        with pytest.raises(VeniceError, match="needs an image"):
            v.submit_video(VideoRequest("venice/ovi-image-to-video", "waves"))

    def test_poll_then_download(self, venice: FakeVenice, tmp_path: Path) -> None:
        """Test that poll then download."""
        venice.routes["/video/quote"] = httpx.Response(200, json={"quote": 0.3})
        venice.routes["/video/queue"] = httpx.Response(200, json={"queue_id": "q3"})
        job = v.submit_video(VideoRequest("venice/wan-3-0-text-to-video", "waves", duration=5))
        venice.routes["/video/retrieve"] = httpx.Response(
            200, json={"status": "PROCESSING", "average_execution_time": 1}
        )
        assert v.get_video(job["id"]) == {"status": "in_progress"}
        assert venice.calls_to("/video/retrieve")[0].body == {"model": "wan-3-0-text-to-video", "queue_id": "q3"}
        venice.routes["/video/retrieve"] = httpx.Response(
            200, content=b"MP4DATA", headers={"content-type": "video/mp4"}
        )
        assert v.get_video(job["id"]) == {"status": "completed", "usage": {"cost": 0.3}}
        dest = tmp_path / "out" / "vid.mp4"
        v.download_video(job["id"], dest)
        assert dest.read_bytes() == b"MP4DATA"

    def test_failed_job_and_transient_errors(self, venice: FakeVenice) -> None:
        """Test that failed job and transient errors."""
        venice.routes["/video/retrieve"] = httpx.Response(400, json={"error": "Content policy violation"})
        assert v.get_video("venice:m:q") == {"status": "failed", "error": "Venice: Content policy violation"}
        venice.routes["/video/retrieve"] = httpx.Response(503, text="busy")
        with pytest.raises(VeniceError):
            v.get_video("venice:m:q")  # the poller retries these


def _sse(*chunks: JsonValue) -> httpx.Response:
    """A streamed chat completion made of ``chunks``."""
    lines = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
    return httpx.Response(200, content=lines.encode(), headers={"content-type": "text/event-stream"})


class TestText:
    """Tests for text."""

    def test_streams_without_venices_system_prompt_and_prices_usage(self, venice: FakeVenice) -> None:
        """Test that streams without venices system prompt and prices usage."""
        venice.routes["/chat/completions"] = _sse(
            {"choices": [{"delta": {"content": "Hi"}}]},
            {"choices": [], "usage": {"prompt_tokens": 1000, "completion_tokens": 500}},
        )
        chunks = [
            as_object(c)
            for c in v.stream_chat(
                "venice/llama-big",
                [{"role": "user", "content": "hello"}],
                StreamOptions(tools=[{"type": "function", "function": {"name": "f"}}]),
            )
        ]
        body = venice.body("/chat/completions")
        assert body["model"] == "llama-big"
        assert body["venice_parameters"] == {"include_venice_system_prompt": False}
        assert body["stream_options"] == {"include_usage": True}
        assert dig(body, "tools", 0, "function", "name") == "f"
        assert dig(chunks[0], "choices", 0, "delta", "content") == "Hi"
        assert number(chunks[1], "usage", "cost") == pytest.approx(1000 * 1e-6 + 500 * 4e-6)

    def test_chat_reply_is_logged_with_its_text_and_tool_calls(self, venice: FakeVenice) -> None:
        """Test that chat reply is logged with its text and tool calls."""
        call = {"index": 0, "function": {"name": "generate_image", "arguments": '{"prompt": "a fox"}'}}
        venice.routes["/chat/completions"] = _sse(
            {"choices": [{"delta": {"content": "Here "}}]},
            {"choices": [{"delta": {"content": "you go", "tool_calls": [call]}, "finish_reason": "tool_calls"}]},
        )
        list(v.stream_chat("venice/llama-big", [{"role": "user", "content": "draw a fox"}]))
        entry = request_log.recent()[0]
        assert entry["path"] == "/chat/completions"
        assert entry["status"] == 200
        response = obj(entry, "response")
        assert response["content"] == "Here you go"
        assert response["tool_calls"] == [{"name": "generate_image", "arguments": '{"prompt": "a fox"}'}]
        assert response["finish_reason"] == "tool_calls"

    def test_reported_cost_object_wins(self, venice: FakeVenice) -> None:
        """Test that reported cost object wins."""
        venice.routes["/chat/completions"] = _sse(
            {"choices": [], "usage": {"prompt_tokens": 1, "completion_tokens": 1, "cost": {"usd": 0.0123, "diem": 0}}}
        )
        [chunk] = v.stream_chat("venice/llama-big", [])
        assert number(as_object(chunk), "usage", "cost") == 0.0123

    def test_chat_turn_uses_venice_for_a_venice_text_model(
        self,
        client: TestClient,
        conv: ConversationOut,
        chat: None,
        venice: FakeVenice,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test that chat turn uses venice for a venice text model."""
        venice.routes["/chat/completions"] = _sse({"choices": [{"delta": {"content": "From Venice"}}]})
        monkeypatch.setattr(openrouter, "stream_chat", stub(lambda: pytest.fail("not OpenRouter")))
        ev = _send(client, conv, "hi", text_model="venice/llama-big")
        assert dig(ev[-1], "message", "content") == "From Venice"

    def test_no_images_for_a_model_without_vision_before_the_model_list_loads(
        self, client: TestClient, conv: ConversationOut, chat: None, venice: FakeVenice
    ) -> None:
        """After a restart (or a failed model list) the app still knows the model can't see images.

        It knows this from Venice's own catalogue.
        """
        venice.routes["/chat/completions"] = _sse({"choices": [{"delta": {"content": "ok"}}]})
        assert chat_catalogue.cached_models() is None
        up = _attach(client, conv, "a.png")
        ev = _send(client, conv, "like this", mode="auto", text_model="venice/venice-uncensored", attachments=[up])
        assert dig(ev[-1], "message", "status") != "error"
        sent = json.dumps(obj(venice.calls_to("/chat/completions")[0].body)["messages"])
        assert "image_url" not in sent
        assert "[user attached an image]" in sent


def test_balance_reads_usd_from_the_rate_limits_body(client: TestClient, venice: FakeVenice) -> None:
    """Test that balance reads usd from the rate limits body."""
    # Inference keys can't read /billing/balance; the USD figure is in the
    # rate-limits body under balances.USD (not a response header).
    venice.routes["/api_keys/rate_limits"] = httpx.Response(
        200, json={"data": {"balances": {"USD": 4.49725029, "DIEM": 0, "BUNDLED_CREDITS": 0}}}
    )
    assert obj(client.get("/api/chat/venice-balance")) == {"usd": 4.49725029, "credits": 0.0}


def test_balance_includes_the_plans_bundled_credits(client: TestClient, venice: FakeVenice) -> None:
    """Test that balance includes the plans bundled credits."""
    venice.routes["/api_keys/rate_limits"] = httpx.Response(
        200, json={"data": {"balances": {"USD": 0.76, "DIEM": 0, "BUNDLED_CREDITS": 4.7635423}}}
    )
    assert obj(client.get("/api/chat/venice-balance")) == {"usd": 0.76, "credits": 4.7635423}


def test_balance_falls_back_to_the_response_header_when_rate_limits_unreadable(
    client: TestClient, venice: FakeVenice
) -> None:
    """Test that balance falls back to the response header when rate limits unreadable."""
    # If the endpoint errors, fall back to the balance a prior response's header
    # reported (_note_balance runs on the error response too).
    venice.routes["/api_keys/rate_limits"] = httpx.Response(
        403, json={"error": "nope"}, headers={"x-venice-balance-usd": "3.5"}
    )
    assert obj(client.get("/api/chat/venice-balance")) == {"usd": 3.5, "credits": None}


class TestVideoFamiliesInChat:
    """Reference, first+last-frame and video-input models get the right inputs from the chat."""

    def _load_catalogue(self, client: TestClient, chat: None, monkeypatch: pytest.MonkeyPatch) -> None:
        for fn in ("list_text_models", "list_image_models", "list_video_models"):
            monkeypatch.setattr(openrouter, fn, stub(list[ModelEntry]))
        client.get("/api/chat/models")

    def _queue(self, fake: FakeVenice, queue_id: str = "q") -> None:
        fake.routes["/video/quote"] = httpx.Response(200, json={"quote": 0.1})
        fake.routes["/video/queue"] = httpx.Response(200, json={"queue_id": queue_id})

    def _image(self, chat: None, conv: ConversationOut, name: str) -> None:
        (chat_pkg.conversation_dir(conv["id"]) / name).write_bytes(png_bytes())

    def test_reference_model_gets_attached_pinned_and_character_images(
        self,
        client: TestClient,
        conv: ConversationOut,
        chat: None,
        db: MetadataDB,
        venice: FakeVenice,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test that reference model gets attached pinned and character images."""
        self._load_catalogue(client, chat, monkeypatch)
        self._queue(venice)
        for f in ("pin.png", "a.png", "b.png"):
            self._image(chat, conv, f)
        db.add_chat_message(conv["id"], "user", "x")
        msg = db.add_chat_message(
            conv["id"],
            "assistant",
            "",
            media=[
                {"id": "p", "kind": "image", "source": "generated", "status": "done", "file": "pin.png", "prompt": "p"}
            ],
        )
        client.post(f"/api/chat/messages/{msg.id}/media/p/pin", json={"pinned": True})
        ups = [_attach(client, conv, "a.png", "red"), _attach(client, conv, "b.png", "blue")]
        ev = _send(
            client,
            conv,
            "they dance",
            attachments=ups,
            mode="video",
            video_model="venice/wan-3-0-reference-to-video",
        )
        body = venice.body("/video/queue")
        assert body["model"] == "wan-3-0-reference-to-video"
        assert len(seq(body, "reference_image_urls")) == 3
        item = obj(ev[-1], "message", "media", 0)
        assert dig(item, "params", "refs") == [*ups, "pin.png"]
        assert dig(item, "params", "refs_used") == 3

    def test_first_and_last_frame_from_two_attachments(
        self,
        client: TestClient,
        conv: ConversationOut,
        chat: None,
        venice: FakeVenice,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test that first and last frame from two attachments."""
        self._load_catalogue(client, chat, monkeypatch)
        self._queue(venice)
        ups = [_attach(client, conv, "s.png", "blue"), _attach(client, conv, "e.png", "blue")]
        ev = _send(
            client,
            conv,
            "morph",
            attachments=ups,
            mode="video",
            video_model="venice/flux-3-first-last-frame-to-video",
        )
        body = venice.body("/video/queue")
        assert text(body, "image_url").startswith("data:image")
        assert text(body, "end_image_url").startswith("data:image")
        assert dig(ev[-1], "message", "media", 0, "params", "last_frame") == ups[1]

    def test_video_to_video_uses_the_latest_chat_video(
        self,
        client: TestClient,
        conv: ConversationOut,
        chat: None,
        db: MetadataDB,
        venice: FakeVenice,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test that video to video uses the latest chat video."""
        self._load_catalogue(client, chat, monkeypatch)
        self._queue(venice)
        (chat_pkg.conversation_dir(conv["id"]) / "vid_old.mp4").write_bytes(b"MP4")
        db.add_chat_message(conv["id"], "user", "x")
        db.add_chat_message(
            conv["id"],
            "assistant",
            "",
            media=[
                {
                    "id": "v1",
                    "kind": "video",
                    "source": "generated",
                    "status": "done",
                    "file": "vid_old.mp4",
                    "prompt": "p",
                }
            ],
        )
        ev = _send(client, conv, "make it anime", mode="video", video_model="venice/wan-2-7-video-to-video")
        body = venice.body("/video/queue")
        assert text(body, "video_url").startswith("data:")
        assert body["duration"] == "Auto"
        assert dig(ev[-1], "message", "media", 0, "params", "source_video") == "vid_old.mp4"

    def test_upscale_maps_the_resolution_pick_to_a_factor(self, venice: FakeVenice, tmp_path: Path) -> None:
        """Test that upscale maps the resolution pick to a factor."""
        self._queue(venice)
        src = tmp_path / "in.mp4"
        src.write_bytes(b"MP4")
        job = v.submit_video(VideoRequest("venice/topaz-video-upscale", "", resolution="4x", source_video=src))
        body = venice.body("/video/queue")
        assert body["upscale_factor"] == 4
        assert "resolution" not in body
        assert dig(job.get("params"), "resolution") == "4x"

    def test_missing_inputs_explain_what_is_needed(self, venice: FakeVenice, tmp_path: Path) -> None:
        """Test that missing inputs explain what is needed."""
        with pytest.raises(VeniceError, match="reference images"):
            v.submit_video(VideoRequest("venice/wan-3-0-reference-to-video", "x"))
        with pytest.raises(VeniceError, match="first and a last frame"):
            v.submit_video(VideoRequest("venice/flux-3-first-last-frame-to-video", "x"))
        with pytest.raises(VeniceError, match="works on a video"):
            v.submit_video(VideoRequest("venice/wan-2-7-video-to-video", "x"))

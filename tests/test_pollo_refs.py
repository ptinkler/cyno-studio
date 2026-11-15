"""Reference-to-video (refs branch).

Covers the named refs list a ref_mode model gets, how attachments map to [@name] handles with per-type caps,
and the submit path that uploads each ref and routes to Pollo's reference-to-video branch.
"""

import json
import types
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

import web.providers.pollo as pollo
from tests.jsonpath import rows, text
from web.chat.catalogue import RefMode
from web.chat.turn import Turn
from web.core.metadata.models import ChatMessage
from web.jsonutil import as_object
from web.providers import VideoRequest
from web.providers.pollo_engine import PolloGenerator

if TYPE_CHECKING:
    from web.providers.pollo_engine._shared import Payload

pytestmark = pytest.mark.no_tenant


def _user(*media: tuple[str, str]) -> ChatMessage:
    """A user message whose media is (kind, file) pairs, in order."""
    return ChatMessage(role="user", media_json=json.dumps([{"kind": k, "file": f} for k, f in media]))


class TestRefItems:
    """Turn.build_ref_items only touches self._last_user(), so a stub drives it."""

    def _items(self, ref_mode: RefMode, user: ChatMessage) -> list[dict[str, str]]:
        stub = cast("Turn", types.SimpleNamespace(_last_user=lambda: user))
        return Turn.build_ref_items(stub, ref_mode)

    def test_names_by_type_and_order(self) -> None:
        """Test that names by type and order."""
        rm: RefMode = {"types": ["image", "video", "audio"], "max": 15}
        items = self._items(rm, _user(("video", "v1.mp4"), ("image", "a.png"), ("image", "b.png")))
        assert items == [
            {"file": "v1.mp4", "name": "video1", "type": "video"},
            {"file": "a.png", "name": "image1", "type": "image"},
            {"file": "b.png", "name": "image2", "type": "image"},
        ]

    def test_per_type_cap_drops_overflow(self) -> None:
        # Kling 3.0 Omni: at most 1 video, 4 images.
        """Test that per type cap drops overflow."""
        rm: RefMode = {"types": ["image", "video"], "max": 7, "limits": {"image": 4, "video": 1}}
        items = self._items(rm, _user(("video", "v1.mp4"), ("video", "v2.mp4"), ("image", "a.png")))
        names = [i["name"] for i in items]
        assert "video1" in names
        assert "video2" not in names
        assert "image1" in names

    def test_disallowed_type_excluded(self) -> None:
        # Flash takes no audio refs.
        """Test that disallowed type excluded."""
        rm: RefMode = {"types": ["image", "video"], "max": 15}
        items = self._items(rm, _user(("audio", "a.mp3"), ("image", "i.png")))
        assert [i["type"] for i in items] == ["image"]

    def test_total_max_caps_list(self) -> None:
        """Test that total max caps list."""
        rm: RefMode = {"types": ["image"], "max": 2}
        items = self._items(rm, _user(("image", "a.png"), ("image", "b.png"), ("image", "c.png")))
        assert len(items) == 2


class TestSubmitRefBranch:
    """Tests for submit ref branch."""

    def test_ref_items_route_to_refs_branch(
        self, monkeypatch: pytest.MonkeyPatch, provider_keys: dict[str, str | None]
    ) -> None:
        """Test that ref items route to refs branch."""
        provider_keys["pollo"] = "K"

        def fake_upload(path: Path, what: str = "image") -> str:
            return f"https://h/{'vid' if what == 'video' else 'img'}/{path.name}"

        monkeypatch.setattr(pollo, "_upload", fake_upload)
        captured: dict[str, Payload] = {}

        def fake_submit(gen: PolloGenerator) -> str:
            captured["p"] = gen.get_payload()
            return "task1"

        monkeypatch.setattr(pollo, "submit_task", fake_submit)
        job = pollo.submit_video(
            VideoRequest(
                "pollo/klingv4",
                "replace [@video1] with [@image1]",
                duration=5,
                ref_items=[
                    {"path": Path("/x/v.mp4"), "name": "video1", "type": "video"},
                    {"path": Path("/x/i.png"), "name": "image1", "type": "image"},
                ],
            )
        )
        assert job["id"] == "pollo:task1"
        refs = rows(captured["p"]["input"], "refs")
        assert [text(r, "name") for r in refs] == ["video1", "image1"]
        assert text(refs[0], "url").startswith("https://h/vid/")
        assert text(refs[1], "url").startswith("https://h/img/")
        assert "image" not in captured["p"]["input"]  # refs branch, not image-to-video

    def test_empty_ref_items_use_normal_branch(
        self, monkeypatch: pytest.MonkeyPatch, provider_keys: dict[str, str | None]
    ) -> None:
        # No refs -> falls through to the plain image/text path (first_frame).
        """Test that empty ref items use normal branch."""
        provider_keys["pollo"] = "K"

        def fake_submit(gen: PolloGenerator) -> str:
            assert gen.get_payload()
            return "task2"

        monkeypatch.setattr(pollo, "submit_task", fake_submit)
        job = pollo.submit_video(VideoRequest("pollo/klingv4", "a fox runs", duration=5, ref_items=[]))
        assert job["id"] == "pollo:task2"


def test_list_video_models_surfaces_ref_mode(provider_keys: dict[str, str | None]) -> None:
    """Test that list video models surfaces ref mode."""
    provider_keys["pollo"] = "K"
    by_id = {m["id"]: m for m in pollo.list_video_models()}
    assert as_object(by_id["pollo/klingv4"]["ref_mode"])["limits"] == {"image": 10, "video": 5, "audio": 3}
    assert as_object(by_id["pollo/klingv4flash"]["ref_mode"])["types"] == ["image", "video"]
    # A non-refs model carries ref_mode: None.
    assert by_id["pollo/klingv3turbo"]["ref_mode"] is None

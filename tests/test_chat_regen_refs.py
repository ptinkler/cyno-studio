"""Redo / Edit on a card with pictures of the caller's choosing as references."""

from collections.abc import Mapping

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import web.chat as chat_pkg
from tests import jsonpath as jp
from tests.chat_fixtures import ConversationOut, png_bytes
from tests.stubs import stub
from web.chat import regen_refs
from web.chat.helpers import conversation_dir
from web.core.metadata import ChatMessage, MetadataDB
from web.types import JsonValue

pytest_plugins = ["tests.chat_fixtures"]


def _models(monkeypatch: pytest.MonkeyPatch, info: Mapping[str, JsonValue]) -> None:

    def fake(_kind: str, _model: str | None) -> Mapping[str, JsonValue]:
        return info

    monkeypatch.setattr(regen_refs, "model_info", fake)


class TestVideoParams:
    """Each video family takes its pictures in its own inputs."""

    def test_frame_model_takes_first_and_last(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """First+last-frame models get the first two pictures as frames, not as refs."""
        _models(monkeypatch, {"frame_images": ["first_frame", "last_frame"]})
        old = {"first_frame": "old.png", "refs": ["x.png"], "ref_items": [{"file": "v.mp4", "type": "video"}]}
        out = regen_refs.video_params("m", "a fox", old, ["a.png", "b.png", "c.png"])
        assert out["first_frame"] == "a.png"
        assert out["last_frame"] == "b.png"
        assert "refs" not in out
        assert "ref_items" not in out

    def test_single_frame_model_drops_last(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A model with no last frame never gets one, and no pictures means no first frame."""
        _models(monkeypatch, {"frame_images": ["first_frame"]})
        out = regen_refs.video_params("m", "p", {"first_frame": "old.png", "last_frame": "z.png"}, [])
        assert out["first_frame"] is None
        assert "last_frame" not in out

    def test_reference_image_model_keeps_character_refs(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Reference-image models get the pictures as `refs`, capped at max_refs, characters kept."""
        _models(monkeypatch, {"reference_images": True, "max_refs": 2, "frame_images": []})
        out = regen_refs.video_params("m", "p", {"refs": ["char:3/a.png", "old.png"]}, ["a.png", "b.png", "c.png"])
        assert out["refs"] == ["a.png", "b.png", "char:3/a.png"]
        assert out["first_frame"] == "a.png"

    def test_ref_mode_with_mention_uses_named_items(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A prompt that mentions [@image1] goes through the named-references branch; clips stay."""
        _models(monkeypatch, {"ref_mode": {"limits": {"image": 2}}})
        old = {"ref_items": [{"file": "v.mp4", "name": "video1", "type": "video"}], "first_frame": "f.png"}
        out = regen_refs.video_params("m", "use [@image1]", old, ["a.png", "b.png", "c.png"])
        assert out["ref_items"] == [
            {"file": "a.png", "name": "image1", "type": "image"},
            {"file": "b.png", "name": "image2", "type": "image"},
            {"file": "v.mp4", "name": "video1", "type": "video"},
        ]
        assert out["first_frame"] is None

    def test_ref_mode_without_mention_is_plain_image_to_video(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Like a fresh send: no mention and no clip means a lone image is just the first frame."""
        _models(monkeypatch, {"ref_mode": {"limits": {"image": 9}}, "frame_images": ["first_frame"]})
        out = regen_refs.video_params("m", "a fox", {}, ["a.png"])
        assert out["first_frame"] == "a.png"
        assert "ref_items" not in out


class TestRegenerateWithRefs:
    """The endpoint checks the files and stores them on the card."""

    @pytest.fixture
    def msg(self, db: MetadataDB, conv: ConversationOut, monkeypatch: pytest.MonkeyPatch) -> ChatMessage:
        """A finished image card made from one reference, with the worker stubbed out."""
        monkeypatch.setattr(chat_pkg.routes_media_items, "_regenerate_worker", stub(lambda: None))
        folder = conversation_dir(conv["id"])
        for name in ("img_a.png", "up_ref1.png", "up_ref2.png", "clip.mp4"):
            (folder / name).write_bytes(png_bytes())
        db.add_chat_message(conv["id"], "user", "draw")
        return db.add_chat_message(
            conv["id"],
            "assistant",
            "",
            media=[
                {
                    "id": "m1",
                    "kind": "image",
                    "source": "generated",
                    "status": "done",
                    "file": "img_a.png",
                    "prompt": "a fox",
                    "model": "i/model",
                    "params": {"refs": ["up_ref1.png", "char:3/c.png"]},
                }
            ],
        )

    def _post(self, client: TestClient, msg: ChatMessage, **body: JsonValue) -> int:
        return client.post(
            f"/api/chat/messages/{msg.id}/media/m1/regenerate", json={"replace": True, **body}
        ).status_code

    def _refs(self, db: MetadataDB, msg: ChatMessage) -> JsonValue:
        return jp.obj(jp.must(db.get_chat_message(msg.id)).media[0], "params")["refs"]

    def test_redo_replaces_the_references_and_keeps_characters(
        self, client: TestClient, db: MetadataDB, msg: ChatMessage
    ) -> None:
        """The list is the whole set: the old reference is gone, the character's image stays."""
        assert self._post(client, msg, refs=["up_ref2.png"]) == 200
        assert self._refs(db, msg) == ["up_ref2.png", "char:3/c.png"]

    def test_no_refs_leaves_them_as_they_were(self, client: TestClient, db: MetadataDB, msg: ChatMessage) -> None:
        """Omitting `refs` is today's behaviour."""
        assert self._post(client, msg) == 200
        assert self._refs(db, msg) == ["up_ref1.png", "char:3/c.png"]

    def test_edit_leads_with_the_picture_then_the_added_ones(
        self, client: TestClient, db: MetadataDB, msg: ChatMessage
    ) -> None:
        """An edit sends the picture itself first, then what was added."""
        assert self._post(client, msg, edit=True, refs=["up_ref2.png"]) == 200
        assert self._refs(db, msg) == ["img_a.png", "up_ref2.png", "char:3/c.png"]

    @pytest.mark.parametrize("name", ["../secret.png", "nope.png", "clip.mp4", "sub/x.png"])
    def test_rejects_files_that_are_not_pictures_in_this_chat(
        self, client: TestClient, db: MetadataDB, msg: ChatMessage, name: str
    ) -> None:
        """Traversal, missing files and non-images are refused, and the card is untouched."""
        assert self._post(client, msg, refs=[name]) == 400
        assert self._refs(db, msg) == ["up_ref1.png", "char:3/c.png"]

    def test_too_many(self, client: TestClient, msg: ChatMessage) -> None:
        """More than the cap is refused."""
        with pytest.raises(HTTPException):
            regen_refs.checked_refs(msg.conversation_id, [f"p{i}.png" for i in range(regen_refs.MAX_REFS + 1)])

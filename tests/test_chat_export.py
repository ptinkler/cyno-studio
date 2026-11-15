"""Tests for web.chat_export — exporting chats as a zip the Import dialog reads back."""

import io
import json
import zipfile
from collections.abc import Sequence
from pathlib import Path
from typing import cast

import pytest
from fastapi.testclient import TestClient

import web.chatgpt_import as imp_mod
from tests.chat_fixtures import ConversationOut, png_bytes
from tests.jsonpath import dig, number, obj, rows, seq, text
from tests.stubs import stub
from web.chat import conversation_dir
from web.core.metadata import MetadataDB
from web.types import JsonValue

pytest_plugins = ["tests.chat_fixtures"]


@pytest.fixture
def imp(chat: None, db: MetadataDB, monkeypatch: pytest.MonkeyPatch) -> None:
    """The importer (``imp_mod``), on the test database."""
    monkeypatch.setattr(imp_mod, "get_db", stub(lambda: db))
    imp_mod.reset_jobs()


def _new_chat(client: TestClient, title: str, text_model: str | None = None) -> ConversationOut:
    """Create a chat through the API."""
    body: dict[str, JsonValue] = {"title": title}
    if text_model:
        body["text_model"] = text_model
    return cast("ConversationOut", obj(client.post("/api/chat/conversations", json=body)))


def _chat_with_branches(client: TestClient, db: MetadataDB) -> ConversationOut:
    """A chat: a prompt with two replies (a retry), the second shown, with a picture and a rewritten text."""
    conv = _new_chat(client, "Foxes", text_model="t/model")
    (conversation_dir(conv["id"]) / "img_fox.png").write_bytes(png_bytes())
    user = db.add_chat_message(conv["id"], "user", "draw a fox")
    first = db.add_chat_message(conv["id"], "assistant", "First go.", parent_id=user.id)
    db.update_chat_message(first.id, cost=0.01)
    second = db.add_chat_message(
        conv["id"],
        "assistant",
        "Second go.",
        parent_id=user.id,
        media=[
            {
                "id": "m1",
                "kind": "image",
                "source": "generated",
                "status": "done",
                "file": "img_fox.png",
                "credits": 5,
                "versions": [{"file": "img_old.png", "credits": 3}],
            }
        ],
    )
    db.update_chat_message(
        second.id,
        cost=0.03,
        text_versions_json=json.dumps({"items": [{"content": "Old"}, {"content": "Second go."}], "shown": 1}),
    )
    client.post(f"/api/chat/conversations/{conv['id']}/branch", json={"message_id": second.id})
    return conv


def _export(client: TestClient, ids: Sequence[str], tmp_path: Path, name: str = "export.zip") -> Path:
    r = client.get(f"/api/chat/export?ids={','.join(ids)}")
    assert r.status_code == 200
    path = tmp_path / name
    path.write_bytes(r.content)
    return path


def _manifest(zf: zipfile.ZipFile) -> JsonValue:
    """The decoded ``pollo-chats.json`` of an export."""
    return cast("JsonValue", json.loads(zf.read("pollo-chats.json")))


def _copies(client: TestClient, title: str) -> list[dict[str, JsonValue]]:
    convs = rows(client.get("/api/chat/conversations"), "conversations")
    return [c for c in convs if c["title"] == title]


class TestExport:
    """What goes in the zip."""

    def test_holds_every_branch_and_the_files(
        self, client: TestClient, db: MetadataDB, chat: None, tmp_path: Path
    ) -> None:
        """Both versions of the reply and the picture go in."""
        conv = _chat_with_branches(client, db)
        with zipfile.ZipFile(_export(client, [conv["id"]], tmp_path)) as zf:
            manifest = obj(_manifest(zf))
            assert f"chats/{conv['id']}/img_fox.png" in zf.namelist()
        assert manifest["format"] == "pollo-chats"
        [exported] = rows(manifest, "conversations")
        assert exported["title"] == "Foxes"
        assert [m["content"] for m in rows(exported, "messages")] == ["draw a fox", "First go.", "Second go."]

    def test_a_batch_and_unknown_ids(self, client: TestClient, db: MetadataDB, chat: None, tmp_path: Path) -> None:
        """Several chats go in one zip; ids that aren't chats are skipped."""
        a = _new_chat(client, "A")
        b = _new_chat(client, "B")
        with zipfile.ZipFile(_export(client, [a["id"], b["id"], "nope"], tmp_path)) as zf:
            titles = [c["title"] for c in rows(_manifest(zf), "conversations")]
        assert titles == ["A", "B"]

    def test_nothing_to_export(self, client: TestClient, chat: None) -> None:
        """Only unknown ids: a 404, not an empty zip."""
        assert client.get("/api/chat/export?ids=nope").status_code == 404

    def test_lists_the_chats_to_pick_from(self, client: TestClient, chat: None) -> None:
        """The picker's list."""
        _new_chat(client, "Listed")
        chats = rows(client.get("/api/chat/export/chats"), "chats")
        assert [c["title"] for c in chats] == ["Listed"]


class TestImport:
    """Reading the zip back with the importer (as on another server)."""

    def test_round_trip(self, imp: None, client: TestClient, db: MetadataDB, tmp_path: Path) -> None:
        """Branches, the shown branch, media, text versions, costs and files all come back."""
        conv = _chat_with_branches(client, db)
        path = _export(client, [conv["id"]], tmp_path)
        client.delete(f"/api/chat/conversations/{conv['id']}")  # as if on a fresh server
        stats = imp_mod.run_import(path)
        assert stats["new"] == 1
        assert not stats["failed"]
        [copy] = _copies(client, "Foxes")
        assert copy["text_model"] == "t/model"
        copy_id = text(copy, "id")
        shown = rows(client.get(f"/api/chat/conversations/{copy_id}"), "messages")
        assert [m["content"] for m in shown] == ["draw a fox", "Second go."]
        reply = shown[-1]
        assert len(seq(reply, "siblings")) == 2  # the other version came too
        assert dig(reply, "media", 0, "file") == "img_fox.png"
        assert reply["text_versions"] == 2
        assert number(reply, "cost") == 0.03
        assert (conversation_dir(copy_id) / "img_fox.png").read_bytes() == png_bytes()
        assert db.get_chat_spend(copy_id) == (0.04, 8)

    def test_importing_again_changes_nothing(
        self, imp: None, client: TestClient, db: MetadataDB, tmp_path: Path
    ) -> None:
        """The same export twice: one chat, the second time unchanged."""
        conv = _chat_with_branches(client, db)
        path = _export(client, [conv["id"]], tmp_path)
        imp_mod.run_import(path)
        stats = imp_mod.run_import(path)
        assert stats["unchanged"] == 1
        assert len(_copies(client, "Foxes")) == 2  # the original and one copy

    def test_a_newer_export_adds_the_new_messages(
        self, imp: None, client: TestClient, db: MetadataDB, tmp_path: Path
    ) -> None:
        """Carried on where it was exported from: only the new turn comes in."""
        conv = _chat_with_branches(client, db)
        imp_mod.run_import(_export(client, [conv["id"]], tmp_path, "one.zip"))
        leaf = db.get_chat_leaf_id(conv["id"])
        user = db.add_chat_message(conv["id"], "user", "and a hat", parent_id=leaf)
        db.add_chat_message(conv["id"], "assistant", "Hat on.", parent_id=user.id)
        stats = imp_mod.run_import(_export(client, [conv["id"]], tmp_path, "two.zip"))
        assert stats["updated"] == 1
        copy = next(c for c in _copies(client, "Foxes") if c["id"] != conv["id"])
        shown = rows(client.get(f"/api/chat/conversations/{text(copy, 'id')}"), "messages")
        assert [m["content"] for m in shown] == ["draw a fox", "Second go.", "and a hat", "Hat on."]

    def test_a_deleted_import_stays_deleted(
        self, imp: None, client: TestClient, db: MetadataDB, tmp_path: Path
    ) -> None:
        """Deleting the imported copy keeps a later import from bringing it back."""
        conv = _chat_with_branches(client, db)
        path = _export(client, [conv["id"]], tmp_path)
        imp_mod.run_import(path)
        copy = next(c for c in _copies(client, "Foxes") if c["id"] != conv["id"])
        client.delete(f"/api/chat/conversations/{text(copy, 'id')}")
        assert imp_mod.run_import(path)["deleted"] == 1

    def test_a_generation_still_running_is_not_left_pending(
        self, imp: None, client: TestClient, db: MetadataDB, tmp_path: Path
    ) -> None:
        """Nothing would ever poll it on the new server."""
        conv = _new_chat(client, "Busy")
        user = db.add_chat_message(conv["id"], "user", "a video")
        db.add_chat_message(
            conv["id"],
            "assistant",
            "",
            parent_id=user.id,
            media=[{"id": "v1", "kind": "video", "source": "generated", "status": "pending", "job_id": "j"}],
        )
        path = _export(client, [conv["id"]], tmp_path)
        client.delete(f"/api/chat/conversations/{conv['id']}")
        imp_mod.run_import(path)
        [copy] = _copies(client, "Busy")
        reply = client.get(f"/api/chat/conversations/{text(copy, 'id')}")
        assert dig(reply, "messages", -1, "media", 0, "status") == "error"

    def test_upload_accepts_a_chat_export(self, imp: None, client: TestClient, db: MetadataDB, tmp_path: Path) -> None:
        """The Import dialog's upload takes this zip as well as ChatGPT's."""
        conv = _chat_with_branches(client, db)
        raw = _export(client, [conv["id"]], tmp_path).read_bytes()
        up = client.post("/api/chat/import/chatgpt/uploads", json={"name": "chats.zip", "size": len(raw)})
        r = client.post(
            f"/api/chat/import/chatgpt/uploads/{text(up, 'id')}",
            data={"offset": "0"},
            files={"chunk": ("chunk", io.BytesIO(raw), "application/octet-stream")},
        )
        assert r.status_code == 200
        assert text(r, "file") == "chats.zip"

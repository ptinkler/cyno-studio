"""Tests for web.chatgpt_import — importing chats from a ChatGPT data export."""

import json
import time
import zipfile
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from httpx import Response

import web.chatgpt_import as imp_mod
from tests.chat_fixtures import SETTINGS, png_bytes, text_chunks
from tests.jsonpath import dig, integer, must, obj, rows, seq, text
from tests.stubs import stub
from web.chat import generation as chat_generation
from web.core.metadata import MetadataDB
from web.providers import openrouter
from web.types import JsonValue

pytest_plugins = ["tests.chat_fixtures"]

T0 = 1_790_000_000.0  # the first prompt's time


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).isoformat()


def _msg(
    mid: str, role: str, parts: list[JsonValue], t: float, content_type: str = "text", **meta: JsonValue
) -> dict[str, JsonValue]:
    return {
        "id": mid,
        "author": {"role": role},
        "content": {"content_type": content_type, "parts": parts},
        "create_time": t,
        "recipient": "all",
        "metadata": meta,
    }


def _pointer(file_id: str) -> dict[str, JsonValue]:
    return {"content_type": "image_asset_pointer", "asset_pointer": f"sediment://{file_id}"}


def conversation(
    cid: str, title: str, messages: Sequence[Mapping[str, JsonValue]], update_time: float
) -> dict[str, JsonValue]:
    """A chat whose messages follow one another (the exported branch)."""
    children: dict[str, list[JsonValue]] = {"root": []}
    mapping: dict[str, JsonValue] = {
        "root": {"id": "root", "message": None, "parent": None, "children": children["root"]}
    }
    parent = "root"
    for m in messages:
        mid = text(m, "id")
        children[mid] = []
        mapping[mid] = {"id": mid, "message": m, "parent": parent, "children": children[mid]}
        children[parent].append(mid)
        parent = mid
    return {
        "id": cid,
        "conversation_id": cid,
        "title": title,
        "create_time": T0 - 5,
        "update_time": update_time,
        "current_node": parent,
        "mapping": mapping,
    }


def _story_messages() -> list[dict[str, JsonValue]]:
    return [
        _msg("u1", "user", [_pointer("file_up1"), "draw her in the rain"], T0, "multimodal_text"),
        _msg("r1", "assistant", [""], T0 + 1, content_type="reasoning_recap"),
        _msg("a1", "assistant", [""], T0 + 20, model_slug="gpt-4o"),
        _msg("u2", "user", ["now a story about it"], T0 + 100),
        _msg(
            "a2",
            "assistant",
            [':::writing{variant="document" id="1" title="Rainy Day"}\nIt rained.\n:::'],
            T0 + 105,
            model_slug="gpt-4o",
        ),
        _msg("a2b", "assistant", ["Want another?"], T0 + 106, model_slug="gpt-4o"),
    ]


def _library(*files: tuple[str, str, str, float]) -> list[JsonValue]:
    return [
        {
            "file_id": fid,
            "file_name": name,
            "mime_type": "image/png",
            "origination_thread_id": thread,
            "created_at": _iso(t),
        }
        for fid, name, thread, t in files
    ]


STORY_LIBRARY = _library(
    ("file_up1", "image.png", "c1", T0 - 2),  # the upload
    ("file_gen1", "Rainy Street.png", "c1", T0 + 15),  # made for the first prompt
    ("file_gone", "Never Finished.png", "c1", T0 + 16),  # not in the zip
)


def _export(
    path: Path,
    conversations: Sequence[JsonValue],
    library: Sequence[JsonValue],
    files: Sequence[str] = ("file_up1", "file_gen1"),
) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("conversations.json", json.dumps(conversations))
        zf.writestr("library_files.json", json.dumps(library))
        for fid in files:
            zf.writestr(f"{fid}.dat", png_bytes())
    return path


@pytest.fixture
def imp(chat: None, db: MetadataDB, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the importer at the test database (use ``imp_mod`` for the module itself)."""
    monkeypatch.setattr(imp_mod, "get_db", stub(lambda: db))
    imp_mod.reset_jobs()  # per-tenant import progress, reset between tests


@pytest.fixture
def story_zip(tmp_path: Path) -> Path:
    """Provide the story zip fixture."""
    return _export(tmp_path / "export1.zip", [conversation("c1", "Rain", _story_messages(), T0 + 200)], STORY_LIBRARY)


def _shown(client: TestClient, conv_id: str) -> list[dict[str, JsonValue]]:
    return rows(client.get(f"/api/chat/conversations/{conv_id}"), "messages")


def _space(client: TestClient) -> dict[str, JsonValue] | None:
    return next((sp for sp in rows(client.get("/api/chat/spaces"), "spaces") if sp["name"] == "ChatGPT"), None)


def _imported(client: TestClient) -> list[dict[str, JsonValue]]:
    """The chats in the ChatGPT space."""
    space = _space(client)
    convs = rows(client.get("/api/chat/conversations"), "conversations")
    return [c for c in convs if space and c["space_id"] == space["id"]]


class TestFirstImport:
    """Tests for first import."""

    def test_turns_become_a_prompt_and_one_reply(self, imp: None, client: TestClient, story_zip: Path) -> None:
        """Test that turns become a prompt and one reply."""
        stats = imp_mod.run_import(story_zip)
        assert stats["new"] == 1
        assert stats["images"] == 2
        assert stats["missing_images"] == 1
        [conv] = _imported(client)
        assert conv["title"] == "Rain"
        assert conv["import_source"] == "chatgpt"
        msgs = _shown(client, text(conv, "id"))
        assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"]
        assert msgs[0]["content"] == "draw her in the rain"
        # Document markup becomes its title in bold; a turn's replies are joined
        assert msgs[3]["content"] == "**Rainy Day**\n\nIt rained.\n\nWant another?"
        assert msgs[3]["model"] == "chatgpt/gpt-4o"

    def test_uploads_on_their_prompt_and_generated_images_on_its_reply(
        self, imp: None, client: TestClient, story_zip: Path, tmp_path: Path
    ) -> None:
        """Test that uploads on their prompt and generated images on its reply."""
        imp_mod.run_import(story_zip)
        conv_id = text(_imported(client)[0], "id")
        msgs = _shown(client, conv_id)
        [up] = rows(msgs[0], "media")
        assert up["source"] == "upload"
        assert up["status"] == "done"
        assert text(up, "file").endswith(".png")
        [gen] = rows(msgs[1], "media")  # the unfinished one is left out
        assert gen["source"] == "generated"
        assert gen["prompt"] == "Rainy Street"
        assert gen["model"] == "chatgpt"
        assert (tmp_path / "chat" / conv_id / text(gen, "file")).is_file()
        assert client.get(f"/api/chat/media/{conv_id}/{text(gen, 'file')}").status_code == 200
        assert msgs[3]["media"] == []

    def test_a_missing_upload_is_noted(self, imp: None, client: TestClient, tmp_path: Path) -> None:
        """Test that a missing upload is noted."""
        path = _export(
            tmp_path / "e.zip", [conversation("c1", "Rain", _story_messages(), T0 + 200)], STORY_LIBRARY, files=()
        )
        imp_mod.run_import(path)
        [up] = rows(_shown(client, text(_imported(client)[0], "id"))[0], "media")
        assert up["status"] == "error"
        assert up["error"] == imp_mod.MISSING

    def test_keeps_chatgpt_dates(self, imp: None, client: TestClient, story_zip: Path) -> None:
        """Test that keeps chatgpt dates."""
        imp_mod.run_import(story_zip)
        conv = _imported(client)[0]
        assert text(conv, "updated_at").startswith(datetime.fromtimestamp(T0 + 200).astimezone().isoformat()[:19])
        assert text(_shown(client, text(conv, "id"))[2], "created_at").startswith(
            datetime.fromtimestamp(T0 + 100).astimezone().isoformat()[:19]
        )

    def test_older_exports_with_image_tool_messages(self, imp: None, client: TestClient, tmp_path: Path) -> None:
        """Test that older exports with image tool messages."""
        messages = [
            _msg("u1", "user", ["draw a cat"], T0),
            _msg("t1", "tool", [_pointer("file_gen1")], T0 + 10, "multimodal_text"),
            _msg("a1", "assistant", ["Here it is"], T0 + 11),
        ]
        imp_mod.run_import(_export(tmp_path / "e.zip", [conversation("c1", "Cat", messages, T0 + 20)], []))
        msgs = _shown(client, text(_imported(client)[0], "id"))
        assert msgs[1]["content"] == "Here it is"
        assert dig(msgs[1], "media", 0, "source") == "generated"

    def test_not_an_export(self, imp: None, tmp_path: Path) -> None:
        """Test that not an export."""
        path = tmp_path / "other.zip"
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("readme.txt", "hi")
        with pytest.raises(ValueError, match=r"conversations\.json"):
            imp_mod.run_import(path)


class TestImportingAgain:
    """Tests for importing again."""

    def test_unchanged_chats_are_skipped(self, imp: None, client: TestClient, story_zip: Path) -> None:
        """Test that unchanged chats are skipped."""
        imp_mod.run_import(story_zip)
        stats = imp_mod.run_import(story_zip)
        assert stats["unchanged"] == 1
        assert stats["new"] == 0
        assert stats["images"] == 0
        assert len(_imported(client)) == 1

    def test_new_turns_are_added(self, imp: None, client: TestClient, story_zip: Path, tmp_path: Path) -> None:
        """Test that new turns are added."""
        imp_mod.run_import(story_zip)
        messages = [
            *_story_messages(),
            _msg("u3", "user", ["one more picture"], T0 + 300),
            _msg("a3", "assistant", [""], T0 + 320),
        ]
        library = [*STORY_LIBRARY, *_library(("file_gen2", "Sunset.png", "c1", T0 + 310))]
        later = _export(
            tmp_path / "export2.zip",
            [
                conversation("c1", "Rain", messages, T0 + 400),
                conversation("c2", "Other", [_msg("x1", "user", ["hi"], T0)], T0 + 10),
            ],
            library,
            files=("file_up1", "file_gen1", "file_gen2"),
        )
        stats = imp_mod.run_import(later)
        assert stats["updated"] == 1
        assert stats["new"] == 1
        assert stats["images"] == 1
        conv = next(c for c in _imported(client) if c["title"] == "Rain")
        msgs = _shown(client, text(conv, "id"))
        assert [m["content"] for m in msgs[4:]] == ["one more picture", ""]
        assert dig(msgs[5], "media", 0, "prompt") == "Sunset"
        assert len(seq(msgs[1], "media")) == 1  # nothing added twice

    def test_a_chat_carried_on_here_gets_chatgpt_turns_as_a_branch(
        self,
        imp: None,
        client: TestClient,
        chat: None,
        story_zip: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test that a chat carried on here gets chatgpt turns as a branch."""
        imp_mod.run_import(story_zip)
        conv_id = text(_imported(client)[0], "id")
        monkeypatch.setattr(openrouter, "stream_chat", stub(lambda: text_chunks("Sure.")))
        client.post(
            f"/api/chat/conversations/{conv_id}/messages", json={"content": "continue", "mode": "text", **SETTINGS}
        )
        mine = _shown(client, conv_id)
        assert mine[-1]["content"] == "Sure."

        messages = [*_story_messages(), _msg("u3", "user", ["from chatgpt"], T0 + 300)]
        imp_mod.run_import(
            _export(tmp_path / "e2.zip", [conversation("c1", "Rain", messages, T0 + 400)], STORY_LIBRARY)
        )
        shown = _shown(client, conv_id)
        assert [m["id"] for m in shown] == [m["id"] for m in mine]  # still showing what was carried on here
        assert seq(shown[-2], "siblings") == [dig(mine[-2], "id"), dig(shown[-2], "siblings", 1)]
        client.post(f"/api/chat/conversations/{conv_id}/branch", json={"message_id": dig(shown[-2], "siblings", 1)})
        assert _shown(client, conv_id)[-1]["content"] == "from chatgpt"

    def test_deleted_chats_stay_deleted(self, imp: None, client: TestClient, story_zip: Path) -> None:
        """Test that deleted chats stay deleted."""
        imp_mod.run_import(story_zip)
        client.delete(f"/api/chat/conversations/{text(_imported(client)[0], 'id')}")
        stats = imp_mod.run_import(story_zip)
        assert stats["deleted"] == 1
        assert _imported(client) == []


class TestSpace:
    """Tests for space."""

    def test_imported_chats_go_in_a_chatgpt_space(self, imp: None, client: TestClient, story_zip: Path) -> None:
        """Test that imported chats go in a chatgpt space."""
        stats = imp_mod.run_import(story_zip)
        space = must(_space(client))
        assert stats.get("space_id") == space["id"]
        assert [c["title"] for c in _imported(client)] == ["Rain"]
        imp_mod.run_import(story_zip)
        assert [sp["name"] for sp in rows(client.get("/api/chat/spaces"), "spaces")] == ["ChatGPT"]  # just the one

    def test_no_space_until_there_is_something_to_import(self, imp: None, client: TestClient, story_zip: Path) -> None:
        """Test that no space until there is something to import."""
        imp_mod.run_import(story_zip)
        client.delete(f"/api/chat/spaces/{integer(must(_space(client)), 'id')}")
        imp_mod.run_import(story_zip)  # nothing new
        assert _space(client) is None

    def test_imported_chats_use_the_defaults(self, imp: None, client: TestClient, chat: None, story_zip: Path) -> None:
        """Test that imported chats use the defaults."""
        snippet = obj(client.post("/api/chat/instructions", json={"name": "Style", "content": "Be brief."}))
        client.put("/api/chat/settings", json={"default_instruction_ids": [snippet["id"]]})
        imp_mod.run_import(story_zip)
        assert chat_generation.conversation_instructions(text(_imported(client)[0], "id")) == "Be brief."

    def test_a_chat_moved_out_keeps_getting_imports_where_it_is(
        self, imp: None, client: TestClient, story_zip: Path, tmp_path: Path
    ) -> None:
        """Test that a chat moved out keeps getting imports where it is."""
        imp_mod.run_import(story_zip)
        conv_id = text(_imported(client)[0], "id")
        client.patch(f"/api/chat/conversations/{conv_id}", json={"space_id": None})
        messages = [*_story_messages(), _msg("u3", "user", ["more"], T0 + 300)]
        imp_mod.run_import(
            _export(tmp_path / "e2.zip", [conversation("c1", "Rain", messages, T0 + 400)], STORY_LIBRARY)
        )
        assert _shown(client, conv_id)[-1]["content"] == "more"
        assert _imported(client) == []
        moved = obj(client.get(f"/api/chat/conversations/{conv_id}"), "conversation")
        assert moved["space_id"] is None

    def test_search_finds_imported_chats(self, imp: None, client: TestClient, story_zip: Path) -> None:
        """Test that search finds imported chats."""
        imp_mod.run_import(story_zip)
        found = rows(client.get("/api/chat/conversations?q=rained"), "conversations")
        assert [c["title"] for c in found] == ["Rain"]


class TestRoutes:
    """Tests for routes."""

    def test_lists_exports_and_runs_an_import(
        self, imp: None, client: TestClient, story_zip: Path, tmp_path: Path
    ) -> None:
        """Test that lists exports and runs an import."""
        (tmp_path / "imports" / "test-user").mkdir(parents=True)
        story_zip.rename(tmp_path / "imports" / "test-user" / "export1.zip")
        data = client.get("/api/chat/import/chatgpt")
        assert [f["name"] for f in rows(data, "files")] == ["export1.zip"]
        assert dig(data, "job", "state") == "idle"
        assert client.post("/api/chat/import/chatgpt", json={"file": "export1.zip"}).status_code == 200
        job = obj(client.get("/api/chat/import/chatgpt"), "job")
        for _ in range(100):
            job = obj(client.get("/api/chat/import/chatgpt"), "job")
            if job["state"] != "running":
                break
            time.sleep(0.05)
        assert job["state"] == "done"
        assert job["new"] == 1
        assert len(_imported(client)) == 1

    def test_only_exports_in_the_imports_folder(self, imp: None, client: TestClient) -> None:
        """Test that only exports in the imports folder."""
        assert client.post("/api/chat/import/chatgpt", json={"file": "nope.zip"}).status_code == 404
        assert client.post("/api/chat/import/chatgpt", json={"file": "../x.zip"}).status_code == 400

    def test_another_users_export_is_not_importable(
        self, imp: None, client: TestClient, story_zip: Path, tmp_path: Path
    ) -> None:
        """The imports folder is per-tenant, so a user can't list or import an.

        export another user uploaded (even knowing its filename).
        """
        (tmp_path / "imports" / "other-user").mkdir(parents=True)
        story_zip.rename(tmp_path / "imports" / "other-user" / "export1.zip")
        assert seq(client.get("/api/chat/import/chatgpt"), "files") == []  # not listed
        assert client.post("/api/chat/import/chatgpt", json={"file": "export1.zip"}).status_code == 404


class TestUpload:
    """Tests for upload."""

    @pytest.fixture
    def small_chunks(self, imp: None, monkeypatch: pytest.MonkeyPatch) -> None:
        """Make uploads go in small chunks."""
        monkeypatch.setattr(imp_mod, "UPLOAD_CHUNK", 1000)

    def _start(self, client: TestClient, raw: bytes, name: str = "export1.zip") -> str:
        """Start an upload; return its id."""
        return text(client.post("/api/chat/import/chatgpt/uploads", json={"name": name, "size": len(raw)}), "id")

    def _send(self, client: TestClient, upload_id: str, offset: int, raw: bytes) -> Response:
        return client.post(
            f"/api/chat/import/chatgpt/uploads/{upload_id}",
            data={"offset": str(offset)},
            files={"chunk": ("blob", raw, "application/octet-stream")},
        )

    def _upload(self, client: TestClient, raw: bytes, name: str = "export1.zip") -> Response:
        up = self._start(client, raw, name)
        sent = [self._send(client, up, offset, raw[offset : offset + 1000]) for offset in range(0, len(raw), 1000)]
        return sent[-1]

    def test_chunks_become_an_export_in_the_imports_folder(
        self, small_chunks: None, client: TestClient, story_zip: Path, tmp_path: Path
    ) -> None:
        """Test that chunks become an export in the imports folder."""
        raw = story_zip.read_bytes()
        assert len(raw) > 2000  # several chunks
        resp = self._upload(client, raw)
        assert dig(resp) == {"received": len(raw), "file": "export1.zip"}
        assert (tmp_path / "imports" / "test-user" / "export1.zip").read_bytes() == raw
        files = rows(client.get("/api/chat/import/chatgpt"), "files")
        assert [f["name"] for f in files] == ["export1.zip"]  # the upload's own files aren't listed
        assert sorted(p.name for p in (tmp_path / "imports" / "test-user").iterdir()) == ["export1.zip"]

    def test_a_resent_chunk_replaces_itself(
        self, small_chunks: None, client: TestClient, story_zip: Path, tmp_path: Path
    ) -> None:
        """Test that a resent chunk replaces itself."""
        raw = story_zip.read_bytes()
        up = self._start(client, raw)
        assert dig(self._send(client, up, 0, raw[:1000])) == {"received": 1000}
        assert dig(self._send(client, up, 0, raw[:1000])) == {"received": 1000}
        assert self._send(client, up, 2000, raw[2000:3000]).status_code == 409  # one was skipped
        sent = [self._send(client, up, offset, raw[offset : offset + 1000]) for offset in range(1000, len(raw), 1000)]
        assert text(sent[-1], "file") == "export1.zip"
        assert (tmp_path / "imports" / "test-user" / "export1.zip").read_bytes() == raw

    def test_the_same_name_twice_is_kept_apart(self, small_chunks: None, client: TestClient, story_zip: Path) -> None:
        """Test that the same name twice is kept apart."""
        raw = story_zip.read_bytes()
        self._upload(client, raw)
        assert text(self._upload(client, raw), "file") == "export1 (2).zip"

    def test_only_chatgpt_exports(self, small_chunks: None, client: TestClient, tmp_path: Path) -> None:
        """Test that only chatgpt exports."""
        assert client.post("/api/chat/import/chatgpt/uploads", json={"name": "x.txt", "size": 5}).status_code == 400
        assert self._upload(client, b"not a zip").status_code == 400
        other = tmp_path / "other.zip"
        with zipfile.ZipFile(other, "w") as zf:
            zf.writestr("readme.txt", "hi")
        assert "conversations.json" in text(self._upload(client, other.read_bytes()), "detail")
        assert list((tmp_path / "imports" / "test-user").iterdir()) == []

    def test_chunks_past_the_end_or_too_big(self, small_chunks: None, client: TestClient) -> None:
        """Test that chunks past the end or too big."""
        up = self._start(client, b"x" * 1500)
        assert self._send(client, up, 1000, b"x" * 600).status_code == 400
        assert self._send(client, up, 0, b"x" * 1001).status_code == 400

    def test_cancel_and_unknown_uploads(self, small_chunks: None, client: TestClient, tmp_path: Path) -> None:
        """Test that cancel and unknown uploads."""
        up = self._start(client, b"x" * 1500)
        client.delete(f"/api/chat/import/chatgpt/uploads/{up}")
        assert list((tmp_path / "imports" / "test-user").iterdir()) == []
        assert self._send(client, up, 0, b"x").status_code == 404
        assert self._send(client, "not-an-id", 0, b"x").status_code == 404

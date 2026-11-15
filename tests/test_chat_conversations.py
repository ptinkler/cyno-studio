"""Chat conversations: the catalogue, settings, spaces, instructions, titles, usage and the schema."""

import importlib.util
import io
import time
from pathlib import Path
from typing import cast

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from PIL import Image

import web.chat as chat_pkg
import web.media as media_mod
from tests import jsonpath as jp
from tests.chat_fixtures import SETTINGS, ConversationOut, png_bytes, sse_events, text_chunks
from tests.chat_support import ROOT_DIR, ChatImageSpy, GalleryBackfill, NopeError, StreamSpy, new_group, new_snippet
from tests.jsonpath import dig, integer, number, obj, rows, seq, text
from tests.stubs import stub
from web.chat import catalogue
from web.chat import catalogue as chat_catalogue
from web.chat import generation as chat_generation
from web.chat import helpers as chat_helpers
from web.chat import polling as chat_polling
from web.core.metadata import MetadataDB
from web.providers import openrouter
from web.providers import pollo as pollo_provider
from web.types import JsonValue, ModelEntry

pytest_plugins = ["tests.chat_fixtures"]


class TestModelCatalogue:
    """The /models catalogue lists each provider independently.

    No provider gates the endpoint, so media models show with only a Pollo key.
    """

    def test_media_models_load_without_a_chat_provider(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch, provider_keys: dict[str, str | None]
    ) -> None:
        # Only Pollo configured — no OpenRouter/Venice text provider.
        """Test that media models load without a chat provider."""
        provider_keys["openrouter"] = None
        provider_keys["venice"] = None
        provider_keys["pollo"] = "pollo-test"

        catalogue.clear_models()

        def fake_list(kind: str, refresh: bool = False) -> list[ModelEntry]:
            return [{"id": "pollo/seedream", "name": "Seedream"}] if kind == "image" else []

        monkeypatch.setattr(pollo_provider, "list_models", fake_list)

        r = client.get("/api/chat/models")
        assert r.status_code == 200
        assert jp.obj(r, "errors") == {}
        assert jp.seq(r, "text") == []  # no chat provider, but the endpoint still serves
        assert [m["id"] for m in jp.rows(r, "image")] == ["pollo/seedream"]


class TestConversations:
    """Tests for conversations."""

    def test_crud(self, client: TestClient) -> None:
        """Test that crud."""
        c = client.post("/api/chat/conversations", json={"text_model": "a/b"})
        cid = jp.text(c, "id")
        assert jp.text(c, "title") == "New chat"
        assert jp.text(c, "text_model") == "a/b"
        assert [x["id"] for x in jp.rows(client.get("/api/chat/conversations"), "conversations")] == [cid]
        r = client.patch(f"/api/chat/conversations/{cid}", json={"title": "  Renamed "})
        assert jp.text(r, "title") == "Renamed"
        assert client.delete(f"/api/chat/conversations/{cid}").status_code == 200
        assert client.get(f"/api/chat/conversations/{cid}").status_code == 404

    def test_kind_persists_through_create_patch_list_and_fetch(self, client: TestClient) -> None:
        # Create as a gallery thread → kind sticks on create, list and fetch.
        """Test that kind persists through create patch list and fetch."""
        g = client.post("/api/chat/conversations", json={"kind": "gallery"})
        gid = jp.text(g, "id")
        assert jp.text(g, "kind") == "gallery"
        # GET returns a { conversation, messages } envelope — kind is on the conversation.
        assert jp.text(client.get(f"/api/chat/conversations/{gid}"), "conversation", "kind") == "gallery"
        listing = jp.rows(client.get("/api/chat/conversations"), "conversations")
        listed = {jp.text(c, "id"): jp.text(c, "kind") for c in listing}
        assert listed[gid] == "gallery"
        # The "Opens on Chat/Gallery" toggle (PATCH kind) persists too.
        assert jp.text(client.patch(f"/api/chat/conversations/{gid}", json={"kind": "chat"}), "kind") == "chat"
        assert jp.text(client.get(f"/api/chat/conversations/{gid}"), "conversation", "kind") == "chat"
        # An unknown kind falls back to "chat" rather than being stored raw.
        c = client.post("/api/chat/conversations", json={"kind": "bogus"})
        assert jp.text(c, "kind") == "chat"

    def test_gallery_lane_stays_beside_the_chat_branch(self, client: TestClient, db: MetadataDB) -> None:
        """Test that gallery lane stays beside the chat branch."""
        cid = jp.text(client.post("/api/chat/conversations", json={}), "id")
        u = db.add_chat_message(cid, "user", "story")
        g = db.add_chat_message(cid, "user", "a cat", lane="gallery")
        ga = db.add_chat_message(cid, "assistant", parent_id=g.id, lane="gallery")
        nxt = db.add_chat_message(cid, "user", "go on")
        # The gallery exchange neither moves the chat's leaf nor becomes its parent
        assert nxt.parent_id == u.id
        assert g.parent_id is None
        assert ga.parent_id == g.id
        assert db.get_chat_leaf_id(cid) == nxt.id
        out = jp.rows(client.get(f"/api/chat/conversations/{cid}"), "messages")
        chat = [m["id"] for m in out if not m["lane"]]
        assert chat == [u.id, nxt.id]
        assert {jp.integer(m, "id") for m in out if m["lane"]} == {g.id, ga.id}
        # No version arrows from sharing "no parent" with the chat's first turn
        assert next(m for m in out if m["id"] == u.id)["siblings"] == [u.id]
        # Deleting the gallery exchange leaves the chat alone
        after = jp.rows(client.delete(f"/api/chat/messages/{g.id}"), "messages")
        assert [m["id"] for m in after] == [u.id, nxt.id]

    def test_conversation_thumbs_returns_newest_image(self, client: TestClient, db: MetadataDB) -> None:
        """Test that conversation thumbs returns newest image."""
        cid = jp.text(client.post("/api/chat/conversations", json={}), "id")

        def img(mid: str, f: str) -> list[dict[str, JsonValue]]:
            return [{"id": mid, "kind": "image", "status": "done", "file": f}]

        db.add_chat_message(cid, "assistant", media=img("m1", "old.png"))
        db.add_chat_message(cid, "assistant", media=img("m2", "new.png"))
        # Newest image wins; the route isn't shadowed by /conversations/{id}; unknown ids are absent.
        r = client.get(f"/api/chat/conversations/thumbs?ids={cid},nope")
        assert jp.decode(r) == {"thumbs": {cid: "new.png"}}

    def test_status_reports_key(self, client: TestClient, provider_keys: dict[str, str | None]) -> None:
        """Test that status reports key."""
        assert jp.decode(client.get("/api/chat/status")) == {"configured": True, "openrouter": True, "venice": False}
        provider_keys["openrouter"] = None
        assert jp.flag(client.get("/api/chat/status"), "configured") is False
        provider_keys["venice"] = "v-test"  # Venice alone can run the chat
        assert jp.decode(client.get("/api/chat/status")) == {"configured": True, "openrouter": False, "venice": True}

    def test_openrouter_balance(self, client: TestClient, chat: None, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that openrouter balance."""

        def fake_get(path: str, params: dict[str, str] | None = None) -> dict[str, JsonValue]:
            if path != "/credits":
                pytest.fail(path)
            return {"data": {"total_credits": 60, "total_usage": 52.78926312}}

        monkeypatch.setattr(openrouter, "_get", fake_get)
        assert jp.decode(client.get("/api/chat/credits")) == {
            "total_credits": 60.0,
            "total_usage": 52.78926312,
            "remaining": 7.2107,
        }

    def test_openrouter_balance_error_is_502(
        self, client: TestClient, chat: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that openrouter balance error is 502."""

        def boom(path: str, params: dict[str, str] | None = None) -> None:
            raise NopeError

        monkeypatch.setattr(openrouter, "_get", boom)
        assert client.get("/api/chat/credits").status_code == 502

    def test_send_without_key_is_503(
        self, client: TestClient, conv: ConversationOut, provider_keys: dict[str, str | None]
    ) -> None:
        """Test that send without key is 503."""
        provider_keys["openrouter"] = None
        r = client.post(f"/api/chat/conversations/{conv['id']}/messages", json={"content": "hi", **SETTINGS})
        assert r.status_code == 503


@pytest.mark.no_tenant
def test_gallery_lane_backfill_converts_only_pure_gallery_threads() -> None:
    """Test that gallery lane backfill converts only pure gallery threads."""
    spec = jp.must(importlib.util.spec_from_file_location("m0024", "alembic/versions/0024_backfill_gallery_lane.py"))
    module = importlib.util.module_from_spec(spec)
    jp.must(spec.loader).exec_module(module)
    mod = cast("GalleryBackfill", module)
    eng = sa.create_engine("sqlite://")
    with eng.begin() as c:
        c.execute(sa.text("CREATE TABLE chat_conversations (id TEXT, kind TEXT, current_leaf_id INTEGER)"))
        c.execute(
            sa.text(
                "CREATE TABLE chat_messages (id INTEGER PRIMARY KEY, conversation_id TEXT, parent_id INTEGER,"
                " role TEXT, mode TEXT, lane TEXT)"
            )
        )
        c.execute(sa.text("INSERT INTO chat_conversations VALUES ('g','gallery',4),('m','gallery',7),('c','chat',9)"))
        # One (id, conversation, parent, role, mode) row per line pair, kept compact: the formatter would split
        # each tuple over five lines and bury the table's shape.
        rows = [
            (1, "g", None, "user", "image"), (2, "g", 1, "assistant", "image"),
            (3, "g", 2, "user", "image"), (4, "g", 3, "assistant", "image"),
            (5, "m", None, "user", "image"), (6, "m", 5, "assistant", "image"), (7, "m", 6, "user", "text"),
            (8, "c", None, "user", "image"), (9, "c", 8, "assistant", "image"),
        ]  # fmt: skip
        for r in rows:
            c.execute(
                sa.text("INSERT INTO chat_messages VALUES (:i,:c,:p,:r,:m,NULL)"), dict(zip("icprm", r, strict=True))
            )
        assert mod.backfill(c) == 1
        lanes = dict(
            cast(
                "list[tuple[str, str | None]]",
                c.execute(sa.text("SELECT conversation_id, MAX(lane) FROM chat_messages GROUP BY 1")).all(),
            )
        )
        assert lanes == {"g": "gallery", "m": None, "c": None}
        assert c.execute(sa.text("SELECT parent_id FROM chat_messages WHERE id = 3")).scalar() is None
        assert c.execute(sa.text("SELECT parent_id FROM chat_messages WHERE id = 4")).scalar() == 3
        assert c.execute(sa.text("SELECT current_leaf_id FROM chat_conversations WHERE id='g'")).scalar() is None


def test_alembic_migration_creates_chat_tables(tmp_path: Path) -> None:
    """Migration 0003 adds the chat tables to a pre-chat DB.

    It is a no-op when create_all() already made them (the app creates tables on startup).
    """

    def cfg_for(path: Path) -> Config:
        cfg = Config(str(ROOT_DIR / "alembic.ini"))
        cfg.set_main_option("script_location", str(ROOT_DIR / "alembic"))
        cfg.set_main_option("sqlalchemy.url", f"sqlite:///{path}")
        return cfg

    # Pre-chat DB: full schema minus the chat tables, stamped at 0002
    old = tmp_path / "old.db"
    MetadataDB(db_path=old).engine.dispose()
    eng = sa.create_engine(f"sqlite:///{old}")
    with eng.begin() as c:
        c.execute(sa.text("DROP TABLE chat_library_items"))
        c.execute(sa.text("DROP TABLE chat_messages"))
        c.execute(sa.text("DROP TABLE chat_conversations"))
    command.stamp(cfg_for(old), "0002")
    command.upgrade(cfg_for(old), "head")
    assert {"chat_conversations", "chat_messages", "chat_library_items"} <= set(sa.inspect(eng).get_table_names())

    # DB where create_all already made them
    fresh = tmp_path / "fresh.db"
    MetadataDB(db_path=fresh).engine.dispose()
    command.stamp(cfg_for(fresh), "0002")
    command.upgrade(cfg_for(fresh), "head")


class TestCustomInstructions:
    """Tests for custom instructions."""

    def test_snippet_crud(self, client: TestClient) -> None:
        """Test that snippet crud."""
        a = new_snippet(client, "Terse", "Be brief.")
        b = new_snippet(client, "Story", "Write vividly.")
        listed = client.get("/api/chat/instructions")
        assert {jp.text(i, "name") for i in jp.rows(listed, "instructions")} == {"Terse", "Story"}
        r = client.put(f"/api/chat/instructions/{a}", json={"name": "Terse", "content": "Very brief."})
        assert jp.dig(r, "content") == "Very brief."
        assert client.delete(f"/api/chat/instructions/{b}").status_code == 200
        listed = client.get("/api/chat/instructions")
        assert [jp.text(i, "name") for i in jp.rows(listed, "instructions")] == ["Terse"]
        assert client.post("/api/chat/instructions", json={"name": "", "content": "x"}).status_code == 422

    def test_group_crud(self, client: TestClient) -> None:
        """Test that group crud."""
        a = new_snippet(client, "Tone", "Be warm.")
        b = new_snippet(client, "Format", "Use markdown.")
        g = new_group(client, "Starter", [a, b])
        data = client.get("/api/chat/instructions")
        assert [jp.text(x, "name") for x in jp.rows(data, "groups")] == ["Starter"]
        assert jp.dig(data, "groups", 0, "snippet_ids") == [a, b]
        assert (
            client.post("/api/chat/instruction-groups", json={"name": "Bad", "snippet_ids": [9999]}).status_code == 400
        )
        assert client.delete(f"/api/chat/instruction-groups/{g}").status_code == 200
        assert jp.dig(client.get("/api/chat/instructions"), "groups") == []

    def test_deleting_a_snippet_removes_it_from_groups_and_chats(
        self, client: TestClient, conv: ConversationOut
    ) -> None:
        """Test that deleting a snippet removes it from groups and chats."""
        a = new_snippet(client, "A", "x")
        b = new_snippet(client, "B", "y")
        g = new_group(client, "G", [a, b])
        client.patch(
            f"/api/chat/conversations/{conv['id']}",
            json={"instruction_ids": [a], "instruction_group_ids": [g]},
        )
        client.delete(f"/api/chat/instructions/{a}")
        assert jp.dig(client.get("/api/chat/instructions"), "groups", 0, "snippet_ids") == [b]
        gone = client.get(f"/api/chat/conversations/{conv['id']}")
        assert jp.dig(gone, "conversation", "instruction_ids") == []
        assert jp.dig(gone, "conversation", "instruction_group_ids") == [g]

    def test_global_defaults_apply_live_to_every_chat(self, client: TestClient, chat: None) -> None:
        """Test that global defaults apply live to every chat."""
        d = new_snippet(client, "D", "x")
        e = new_snippet(client, "E", "y")
        g = new_group(client, "G", [d])
        client.put(
            "/api/chat/settings",
            json={"default_instruction_ids": [d, e], "default_instruction_group_ids": [g]},
        )
        made = client.post("/api/chat/conversations", json={})
        # Nothing is copied in: the defaults apply on top of the chat's own (none here)
        assert jp.dig(made, "instruction_ids") == []
        assert jp.dig(made, "instruction_group_ids") == []
        made_id = jp.text(made, "id")
        assert chat_generation.conversation_instructions(made_id) == "x\n\ny"  # D once, though in G too
        # Changing the defaults changes the chat
        client.put("/api/chat/settings", json={"default_instruction_ids": [e]})
        assert chat_generation.conversation_instructions(made_id) == "y"
        assert client.post("/api/chat/conversations", json={"instruction_ids": [999]}).status_code == 400

    def test_global_settings_crud_and_validation(self, client: TestClient) -> None:
        """Test that global settings crud and validation."""
        s = new_snippet(client, "S", "x")
        assert jp.dig(client.get("/api/chat/settings")) == {
            "default_character_ids": [],
            "default_instruction_ids": [],
            "default_instruction_group_ids": [],
            "title_model": None,
        }
        updated = client.put("/api/chat/settings", json={"default_instruction_ids": [s]})
        assert jp.dig(updated, "default_instruction_ids") == [s]
        assert client.put("/api/chat/settings", json={"default_instruction_ids": [999]}).status_code == 400
        # Deleting the snippet clears it from the global bucket
        client.delete(f"/api/chat/instructions/{s}")
        assert jp.dig(client.get("/api/chat/settings"), "default_instruction_ids") == []

    def test_attach_and_detach_on_existing_chat(self, client: TestClient, conv: ConversationOut) -> None:
        """Test that attach and detach on existing chat."""
        i = new_snippet(client, "I", "x")
        attached = client.patch(f"/api/chat/conversations/{conv['id']}", json={"instruction_ids": [i]})
        assert jp.dig(attached, "instruction_ids") == [i]
        detached = client.patch(f"/api/chat/conversations/{conv['id']}", json={"instruction_ids": []})
        assert jp.dig(detached, "instruction_ids") == []

    def test_deleting_an_instruction_detaches_it(self, client: TestClient, conv: ConversationOut) -> None:
        """Test that deleting an instruction detaches it."""
        i = new_snippet(client, "I", "x")
        client.patch(f"/api/chat/conversations/{conv['id']}", json={"instruction_ids": [i]})
        client.delete(f"/api/chat/instructions/{i}")
        assert jp.dig(client.get(f"/api/chat/conversations/{conv['id']}"), "conversation", "instruction_ids") == []

    def test_flattened_snippets_and_groups_sent_deduped_as_one_system_message(
        self, client: TestClient, conv: ConversationOut, chat: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that flattened snippets and groups sent deduped as one system message."""
        tone = new_snippet(client, "Tone", "Be warm.")
        fmt = new_snippet(client, "Fmt", "Use markdown.")
        lang = new_snippet(client, "Lang", "In French.")
        g = new_group(client, "G", [tone, fmt])
        # tone is attached both via the group and individually: sent once
        client.patch(
            f"/api/chat/conversations/{conv['id']}",
            json={"instruction_group_ids": [g], "instruction_ids": [tone, lang]},
        )
        seen = StreamSpy(lambda: text_chunks("ok"))
        monkeypatch.setattr(openrouter, "stream_chat", seen)
        sse_events(client.post(f"/api/chat/conversations/{conv['id']}/messages", json={"content": "hi", **SETTINGS}))
        msgs = seen.messages[0]
        assert msgs[1] == {"role": "system", "content": "Be warm.\n\nUse markdown.\n\nIn French."}
        assert msgs[2]["role"] == "user"

    def test_not_sent_when_none_attached(
        self, client: TestClient, conv: ConversationOut, chat: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that not sent when none attached."""
        seen = StreamSpy(lambda: text_chunks("ok"))
        monkeypatch.setattr(openrouter, "stream_chat", seen)
        sse_events(client.post(f"/api/chat/conversations/{conv['id']}/messages", json={"content": "hi", **SETTINGS}))
        assert [m["role"] for m in seen.messages[0]] == ["system", "user"]

    def test_conversational_image_models_get_them_too(
        self, client: TestClient, conv: ConversationOut, chat: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that conversational image models get them too."""
        chat_catalogue.seed_models(
            {
                "text": [],
                "video": [],
                "image": [{"id": "i/model", "input_modalities": ["text", "image"], "conversational": True}],
            },
        )
        i = new_snippet(client, "I", "Watercolour style only.")
        client.patch(f"/api/chat/conversations/{conv['id']}", json={"instruction_ids": [i]})
        got = ChatImageSpy()
        monkeypatch.setattr(openrouter, "generate_image_chat", got)
        sse_events(
            client.post(
                f"/api/chat/conversations/{conv['id']}/messages", json={"content": "a fox", "mode": "image", **SETTINGS}
            )
        )
        assert got.messages[0] == {"role": "system", "content": "Watercolour style only."}


class TestChatSpaces:
    """Tests for chat spaces."""

    def test_crud(self, client: TestClient) -> None:
        """Test that crud."""
        s = new_snippet(client, "Tone", "Be warm.")
        g = new_group(client, "G", [s])
        sp = client.post(
            "/api/chat/spaces",
            json={"name": "Novel", "default_instruction_ids": [s], "default_instruction_group_ids": [g]},
        )
        assert jp.dig(sp, "name") == "Novel"
        assert jp.dig(sp, "default_instruction_ids") == [s]
        assert [jp.text(x, "name") for x in jp.rows(client.get("/api/chat/spaces"), "spaces")] == ["Novel"]
        space_id = jp.integer(sp, "id")
        upd = client.put(f"/api/chat/spaces/{space_id}", json={"name": "Renamed"})
        assert jp.dig(upd, "name") == "Renamed"
        assert jp.dig(upd, "default_instruction_ids") == []
        assert client.delete(f"/api/chat/spaces/{space_id}").status_code == 200
        assert jp.dig(client.get("/api/chat/spaces"), "spaces") == []
        assert (
            client.post("/api/chat/spaces", json={"name": "Bad", "default_instruction_ids": [999]}).status_code == 400
        )

    def test_chat_in_space_stacks_global_and_space_defaults_deduped(self, client: TestClient, chat: None) -> None:
        """Test that chat in space stacks global and space defaults deduped."""
        shared = new_snippet(client, "Shared", "both.")
        spaceonly = new_snippet(client, "SpaceOnly", "Be warm.")
        glob = new_snippet(client, "Glob", "x")
        # Global defaults: glob + shared. Space defaults: shared + spaceonly.
        client.put("/api/chat/settings", json={"default_instruction_ids": [glob, shared]})
        sp = jp.integer(
            client.post("/api/chat/spaces", json={"name": "Novel", "default_instruction_ids": [shared, spaceonly]}),
            "id",
        )
        made = client.post("/api/chat/conversations", json={"space_id": sp})
        assert jp.dig(made, "space_id") == sp
        assert jp.dig(made, "instruction_ids") == []
        made_id = jp.text(made, "id")
        # Global first, then the space's own, each snippet once (shared de-duped)
        assert chat_generation.conversation_instructions(made_id) == "x\n\nboth.\n\nBe warm."
        # Out of the space, only the global defaults apply
        client.patch(f"/api/chat/conversations/{made_id}", json={"space_id": None})
        assert chat_generation.conversation_instructions(made_id) == "x\n\nboth."

    def test_chat_without_space_uses_only_global_defaults(self, client: TestClient, chat: None, db: MetadataDB) -> None:
        """Test that chat without space uses only global defaults."""
        glob = new_snippet(client, "Glob", "x")
        client.put("/api/chat/settings", json={"default_instruction_ids": [glob]})
        made = client.post("/api/chat/conversations", json={})
        assert jp.dig(made, "space_id") is None
        assert chat_helpers.inherited_ids(db.get_conversation(jp.text(made, "id")))["instruction"] == [glob]

    def test_space_character_defaults_apply_to_its_chats(self, client: TestClient, chat: None, db: MetadataDB) -> None:
        """Test that space character defaults apply to its chats."""
        c1 = db.create_character("Alice")
        c2 = db.create_character("Bob")
        space = client.post("/api/chat/spaces", json={"name": "Novel", "default_character_ids": [c1.id]})
        made = client.post(
            "/api/chat/conversations", json={"space_id": jp.integer(space, "id"), "character_ids": [c2.id]}
        )
        assert jp.dig(made, "character_ids") == [c2.id]  # its own
        assert chat_helpers.effective_ids(db.get_conversation(jp.text(made, "id")), "character") == [c1.id, c2.id]

    def test_deleting_a_character_clears_it_from_global_and_space_defaults(
        self, client: TestClient, db: MetadataDB
    ) -> None:
        """Test that deleting a character clears it from global and space defaults."""
        c1 = db.create_character("Alice")
        client.put("/api/chat/settings", json={"default_character_ids": [c1.id]})
        sp = client.post("/api/chat/spaces", json={"name": "Novel", "default_character_ids": [c1.id]})
        assert jp.dig(sp, "default_character_ids") == [c1.id]
        db.delete_character(c1.id)  # symmetric with snippet/group deletion
        assert jp.dig(client.get("/api/chat/settings"), "default_character_ids") == []
        assert jp.dig(client.get("/api/chat/spaces"), "spaces", 0, "default_character_ids") == []

    def test_move_chat_between_spaces_and_unfiled(self, client: TestClient, conv: ConversationOut) -> None:
        """Test that move chat between spaces and unfiled."""
        sp = jp.integer(client.post("/api/chat/spaces", json={"name": "Novel"}), "id")
        moved = client.patch(f"/api/chat/conversations/{conv['id']}", json={"space_id": sp})
        assert jp.dig(moved, "space_id") == sp
        back = client.patch(f"/api/chat/conversations/{conv['id']}", json={"space_id": None})
        assert jp.dig(back, "space_id") is None
        assert client.patch(f"/api/chat/conversations/{conv['id']}", json={"space_id": 999}).status_code == 400

    def test_deleting_space_unfiles_its_chats(self, client: TestClient) -> None:
        """Test that deleting space unfiles its chats."""
        sp = jp.integer(client.post("/api/chat/spaces", json={"name": "Novel"}), "id")
        made = jp.text(client.post("/api/chat/conversations", json={"space_id": sp}), "id")
        client.delete(f"/api/chat/spaces/{sp}")
        assert jp.dig(client.get(f"/api/chat/conversations/{made}"), "conversation", "space_id") is None

    def test_deleting_a_snippet_clears_it_from_space_defaults(self, client: TestClient) -> None:
        """Test that deleting a snippet clears it from space defaults."""
        s = new_snippet(client, "Tone", "x")
        client.post("/api/chat/spaces", json={"name": "Novel", "default_instruction_ids": [s]})
        client.delete(f"/api/chat/instructions/{s}")
        assert jp.dig(client.get("/api/chat/spaces"), "spaces", 0, "default_instruction_ids") == []


class TestConversationList:
    """Tests for conversation list."""

    def test_pinned_first_and_pinning_keeps_the_order_of_the_rest(self, client: TestClient, db: MetadataDB) -> None:
        """Test that pinned first and pinning keeps the order of the rest."""
        a_id = text(client.post("/api/chat/conversations", json={"title": "A"}), "id")
        client.post("/api/chat/conversations", json={"title": "B"})
        client.post("/api/chat/conversations", json={"title": "C"})
        r = client.patch(f"/api/chat/conversations/{a_id}", json={"pinned": True})
        assert dig(r, "pinned") is True

        def titles() -> list[str]:
            return [text(x, "title") for x in rows(client.get("/api/chat/conversations"), "conversations")]

        assert titles() == ["A", "C", "B"]
        client.patch(f"/api/chat/conversations/{a_id}", json={"pinned": False})
        assert titles() == ["C", "B", "A"]

    def test_says_when_older_chats_are_left_out(
        self, client: TestClient, chat: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that says when older chats are left out."""
        monkeypatch.setattr(chat_pkg.routes, "CONVERSATION_LIST_LIMIT", 2)
        for t in "ABC":
            client.post("/api/chat/conversations", json={"title": t})
        data = client.get("/api/chat/conversations")
        assert len(seq(data, "conversations")) == 2
        assert dig(data, "more") is True

    def test_search_finds_titles_and_messages_on_any_branch(self, client: TestClient, db: MetadataDB) -> None:
        """Test that search finds titles and messages on any branch."""
        client.post("/api/chat/conversations", json={"title": "Fox story"})
        other_id = text(client.post("/api/chat/conversations", json={"title": "Misc"}), "id")
        client.post("/api/chat/conversations", json={"title": "Nothing here"})
        db.add_chat_message(
            other_id, "user", "a long intro " * 20 + "then a FOX appears in the snow " + "and more " * 20
        )
        db.add_chat_message(other_id, "user", "edited away", parent_id=None)  # another branch shown
        res = rows(client.get("/api/chat/conversations", params={"q": "fox"}), "conversations")
        assert {text(c, "title") for c in res} == {"Fox story", "Misc"}
        by = {text(c, "title"): c for c in res}
        assert by["Fox story"]["snippet"] is None
        snip = text(by["Misc"], "snippet")
        assert "FOX appears" in snip
        assert snip.startswith("…")
        assert snip.endswith("…")
        assert len(snip) <= 122

    def test_search_treats_wildcards_literally(self, client: TestClient) -> None:
        """Test that search treats wildcards literally."""
        client.post("/api/chat/conversations", json={"title": "100% done"})
        client.post("/api/chat/conversations", json={"title": "1000 done"})
        res = rows(client.get("/api/chat/conversations", params={"q": "0%"}), "conversations")
        assert [c["title"] for c in res] == ["100% done"]


class TestRememberedSettings:
    """Tests for remembered settings."""

    def test_turn_settings_are_kept_on_the_chat_and_copied_to_branches(
        self, client: TestClient, conv: ConversationOut, chat: None, db: MetadataDB, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that turn settings are kept on the chat and copied to branches."""
        monkeypatch.setattr(openrouter, "stream_chat", stub(lambda: text_chunks("ok")))
        ev = sse_events(
            client.post(
                f"/api/chat/conversations/{conv['id']}/messages",
                json={
                    "content": "hi",
                    **SETTINGS,
                    "mode": "text",
                    "history_limit": 10,
                    "image_limit": 2,
                    "image_options": {"aspect_ratio": "16:9"},
                },
            )
        )
        got = obj(client.get(f"/api/chat/conversations/{conv['id']}"), "conversation", "settings")
        assert got["mode"] == "text"
        assert got["history_limit"] == 10
        assert got["image_limit"] == 2
        assert dig(got, "image_options", "aspect_ratio") == "16:9"
        new = obj(
            client.post(
                f"/api/chat/conversations/{conv['id']}/fork", json={"message_id": integer(ev[0], "user_message", "id")}
            )
        )
        assert new["settings"] == got


class TestTitles:
    """Tests for titles."""

    def _send(
        self, client: TestClient, conv: ConversationOut, content: str = "tell me about foxes in winter"
    ) -> list[dict[str, JsonValue]]:
        return sse_events(
            client.post(
                f"/api/chat/conversations/{conv['id']}/messages", json={"content": content, **SETTINGS, "mode": "text"}
            )
        )

    def test_model_title_and_its_cost(
        self, client: TestClient, conv: ConversationOut, chat: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that model title and its cost."""
        monkeypatch.setattr(openrouter, "stream_chat", stub(lambda: text_chunks("ok", cost=0.001)))
        seen: dict[str, str] = {}

        def fake_title(model: str, prompt: str) -> tuple[str | None, float]:
            seen.update(model=model, prompt=prompt)
            return "Winter Foxes", 0.0005

        monkeypatch.setattr(chat_generation, "generate_title", fake_title)
        ev = self._send(client, conv)
        assert {"type": "title", "title": "Winter Foxes"} in ev
        assert seen == {"model": "t/model", "prompt": "tell me about foxes in winter"}
        assert number(ev[-1], "message", "cost") == 0.0015
        assert text(client.get(f"/api/chat/conversations/{conv['id']}"), "conversation", "title") == "Winter Foxes"
        # Only the first turn
        self._send(client, conv, "more")
        assert seen["prompt"] == "tell me about foxes in winter"

    def test_falls_back_to_the_prompt(
        self, client: TestClient, conv: ConversationOut, chat: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that falls back to the prompt."""
        monkeypatch.setattr(openrouter, "stream_chat", stub(lambda: text_chunks("ok")))

        def boom(model: str, prompt: str) -> tuple[str | None, float]:
            raise openrouter.OpenRouterError("nope")

        monkeypatch.setattr(chat_generation, "generate_title", boom)
        ev = self._send(client, conv)
        assert {"type": "title", "title": "tell me about foxes in winter"} in ev

    def test_title_model_override(
        self, client: TestClient, conv: ConversationOut, chat: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that title model override."""
        monkeypatch.setenv("CHAT_TITLE_MODEL", "cheap/model")
        monkeypatch.setattr(openrouter, "stream_chat", stub(lambda: text_chunks("ok")))
        seen: dict[str, str] = {}

        def fake_title(model: str, prompt: str) -> tuple[str | None, float]:
            seen.update(model=model)
            return "T", 0.0

        monkeypatch.setattr(chat_generation, "generate_title", fake_title)
        self._send(client, conv)
        assert seen["model"] == "cheap/model"

    def test_generate_title_cleans_the_reply(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that generate title cleans the reply."""
        monkeypatch.setattr(
            openrouter,
            "stream_chat",
            stub(lambda: text_chunks('<think>hmm</think>**Title:** "Winter Foxes."\nextra', cost=0.0002)),
        )
        assert chat_generation.generate_title("t/model", "foxes") == ("Winter Foxes", 0.0002)

    def test_clean_title_rejects_rambling(self, chat: None) -> None:
        """Test that clean title rejects rambling."""
        assert chat_generation.clean_title("x" * 100) is None
        assert chat_generation.clean_title("   ") is None


class TestHiddenDefaults:
    """A chat can switch off any of its defaults for itself only."""

    def test_hiding_a_default_in_one_chat_leaves_the_others(self, client: TestClient, chat: None) -> None:
        """Test that hiding a default in one chat leaves the others."""
        a_id = integer(client.post("/api/chat/instructions", json={"name": "A", "content": "aa"}), "id")
        b_id = integer(client.post("/api/chat/instructions", json={"name": "B", "content": "bb"}), "id")
        client.put("/api/chat/settings", json={"default_instruction_ids": [a_id, b_id]})
        one_id = text(client.post("/api/chat/conversations", json={}), "id")
        two_id = text(client.post("/api/chat/conversations", json={}), "id")
        hidden = client.patch(f"/api/chat/conversations/{one_id}", json={"hidden_defaults": {"instruction": [a_id]}})
        assert dig(hidden, "hidden_defaults", "instruction") == [a_id]
        assert chat_generation.conversation_instructions(one_id) == "bb"
        assert chat_generation.conversation_instructions(two_id) == "aa\n\nbb"
        # Shown again
        client.patch(f"/api/chat/conversations/{one_id}", json={"hidden_defaults": {}})
        assert chat_generation.conversation_instructions(one_id) == "aa\n\nbb"

    def test_a_new_chat_can_start_with_some_hidden(self, client: TestClient, chat: None, db: MetadataDB) -> None:
        """Test that a new chat can start with some hidden."""
        c1 = db.create_character("Alice")
        client.put("/api/chat/settings", json={"default_character_ids": [c1.id]})
        conv_id = text(client.post("/api/chat/conversations", json={"hidden_defaults": {"character": [c1.id]}}), "id")
        assert chat_helpers.effective_ids(db.get_conversation(conv_id), "character") == []

    def test_a_branch_keeps_what_was_hidden(
        self, client: TestClient, chat: None, db: MetadataDB, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that a branch keeps what was hidden."""
        a_id = integer(client.post("/api/chat/instructions", json={"name": "A", "content": "aa"}), "id")
        client.put("/api/chat/settings", json={"default_instruction_ids": [a_id]})
        conv_id = text(client.post("/api/chat/conversations", json={"hidden_defaults": {"instruction": [a_id]}}), "id")
        msg = db.add_chat_message(conv_id, "user", "hi")
        fork = client.post(f"/api/chat/conversations/{conv_id}/fork", json={"message_id": msg.id})
        assert dig(fork, "hidden_defaults", "instruction") == [a_id]

    def test_unknown_kinds_are_refused(self, client: TestClient) -> None:
        """Test that unknown kinds are refused."""
        conv_id = text(client.post("/api/chat/conversations", json={}), "id")
        resp = client.patch(f"/api/chat/conversations/{conv_id}", json={"hidden_defaults": {"nope": [1]}})
        assert resp.status_code == 400


class TestPausedInstructions:
    """A chat can pause attached snippets/groups: kept attached, not sent."""

    def test_paused_snippets_and_groups_stay_attached_but_are_not_sent(
        self, client: TestClient, conv: ConversationOut, chat: None
    ) -> None:
        """Test that paused snippets and groups stay attached but are not sent."""
        tone = integer(client.post("/api/chat/instructions", json={"name": "Tone", "content": "Be warm."}), "id")
        fmt = integer(client.post("/api/chat/instructions", json={"name": "Fmt", "content": "Use markdown."}), "id")
        lang = integer(client.post("/api/chat/instructions", json={"name": "Lang", "content": "In French."}), "id")
        g = integer(client.post("/api/chat/instruction-groups", json={"name": "G", "snippet_ids": [tone, fmt]}), "id")
        client.patch(
            f"/api/chat/conversations/{conv['id']}",
            json={"instruction_group_ids": [g], "instruction_ids": [tone, lang]},
        )
        assert chat_generation.conversation_instructions(conv["id"]) == "Be warm.\n\nUse markdown.\n\nIn French."
        # Pause the group: its Fmt drops, but Tone stays (attached individually too)
        r = client.patch(
            f"/api/chat/conversations/{conv['id']}", json={"paused_instructions": {"instruction_group": [g]}}
        )
        assert dig(r, "paused_instructions", "instruction_group") == [g]
        assert dig(r, "instruction_group_ids") == [g]  # still attached, just paused
        assert chat_generation.conversation_instructions(conv["id"]) == "Be warm.\n\nIn French."
        # Also pause the Tone snippet → only Lang is left
        client.patch(
            f"/api/chat/conversations/{conv['id']}",
            json={"paused_instructions": {"instruction_group": [g], "instruction": [tone]}},
        )
        assert chat_generation.conversation_instructions(conv["id"]) == "In French."
        # Resume everything
        client.patch(f"/api/chat/conversations/{conv['id']}", json={"paused_instructions": {}})
        assert chat_generation.conversation_instructions(conv["id"]) == "Be warm.\n\nUse markdown.\n\nIn French."

    def test_an_inherited_default_can_be_paused(self, client: TestClient, chat: None) -> None:
        """Test that an inherited default can be paused."""
        a = integer(client.post("/api/chat/instructions", json={"name": "A", "content": "aa"}), "id")
        b = integer(client.post("/api/chat/instructions", json={"name": "B", "content": "bb"}), "id")
        client.put("/api/chat/settings", json={"default_instruction_ids": [a, b]})
        one = text(client.post("/api/chat/conversations", json={}), "id")
        two = text(client.post("/api/chat/conversations", json={}), "id")
        client.patch(f"/api/chat/conversations/{one}", json={"paused_instructions": {"instruction": [a]}})
        assert chat_generation.conversation_instructions(one) == "bb"  # paused here
        assert chat_generation.conversation_instructions(two) == "aa\n\nbb"  # unaffected elsewhere

    def test_a_new_chat_can_start_with_some_paused(self, client: TestClient, chat: None) -> None:
        """Test that a new chat can start with some paused."""
        a = integer(client.post("/api/chat/instructions", json={"name": "A", "content": "aa"}), "id")
        client.put("/api/chat/settings", json={"default_instruction_ids": [a]})
        created = client.post("/api/chat/conversations", json={"paused_instructions": {"instruction": [a]}})
        assert dig(created, "paused_instructions", "instruction") == [a]
        assert chat_generation.conversation_instructions(text(created, "id")) is None

    def test_a_branch_keeps_what_was_paused(self, client: TestClient, db: MetadataDB) -> None:
        """Test that a branch keeps what was paused."""
        a = integer(client.post("/api/chat/instructions", json={"name": "A", "content": "aa"}), "id")
        conv_id = text(client.post("/api/chat/conversations", json={"instruction_ids": [a]}), "id")
        client.patch(f"/api/chat/conversations/{conv_id}", json={"paused_instructions": {"instruction": [a]}})
        msg = db.add_chat_message(conv_id, "user", "hi")
        fork = client.post(f"/api/chat/conversations/{conv_id}/fork", json={"message_id": msg.id})
        assert dig(fork, "paused_instructions", "instruction") == [a]

    def test_unknown_kinds_are_refused(self, client: TestClient, conv: ConversationOut) -> None:
        """Test that unknown kinds are refused."""
        resp = client.patch(f"/api/chat/conversations/{conv['id']}", json={"paused_instructions": {"character": [1]}})
        assert resp.status_code == 400


class TestLargeChats:
    """Big chats (imports run to hundreds of messages and images) stay quick."""

    def test_images_have_a_small_preview(self, client: TestClient, conv: ConversationOut, tmp_path: Path) -> None:
        """Test that images have a small preview."""
        folder = tmp_path / "chat" / conv["id"]
        folder.mkdir(parents=True)
        Image.new("RGB", (1536, 2048), "red").save(folder / "img_big.png")
        resp = client.get(f"/api/chat/media/{conv['id']}/img_big.png/preview")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/jpeg"
        assert min(Image.open(io.BytesIO(resp.content)).size) == 768
        assert client.get(f"/api/chat/media/{conv['id']}/nope.png/preview").status_code == 404

    def test_deleting_a_chat_removes_its_messages_and_files(
        self, client: TestClient, conv: ConversationOut, db: MetadataDB, tmp_path: Path
    ) -> None:
        """Test that deleting a chat removes its messages and files."""
        for i in range(30):
            db.add_chat_message(conv["id"], "user" if i % 2 == 0 else "assistant", f"m{i}")
        folder = tmp_path / "chat" / conv["id"]
        folder.mkdir(parents=True)
        (folder / "img_a.png").write_bytes(png_bytes())
        assert client.delete(f"/api/chat/conversations/{conv['id']}").status_code == 200
        assert db.get_chat_messages(conv["id"]) == []
        assert not folder.exists()  # moved aside at once, then removed in the background
        for _ in range(50):
            if not list((tmp_path / "chat").glob(".deleting-*")):
                break
            time.sleep(0.02)
        assert not list((tmp_path / "chat").glob(".deleting-*"))

    def test_missing_thumbnails_are_made_in_the_background(self, chat: None, tmp_path: Path) -> None:
        """Test that missing thumbnails are made in the background."""
        folder = tmp_path / "chat" / "c1"
        folder.mkdir(parents=True)
        Image.new("RGB", (1200, 1600), "blue").save(folder / "img_a.png")
        chat_polling.warm_missing_thumbnails()
        for size in (media_mod.THUMB_SIZE, chat_pkg.CHAT_PREVIEW_SIZE):
            assert media_mod.thumb_path(folder / "img_a.png", size).is_file()


class TestSpendBreakdown:
    """Tests for spend breakdown."""

    def test_groups_by_model_and_converts_credits_to_usd(
        self, client: TestClient, conv: ConversationOut, db: MetadataDB
    ) -> None:
        """Test that groups by model and converts credits to usd."""
        db.add_chat_message(
            conv["id"],
            "assistant",
            "",
            media=[
                {"id": "a", "kind": "video", "status": "done", "model": "pollo/seedance25", "credits": 10},
                {"id": "b", "kind": "video", "status": "done", "model": "pollo/seedance25", "credits": 5},
            ],
        )
        body = client.get("/api/chat/spend/breakdown")
        row = next(r for r in rows(body, "rows") if r["model"] == "pollo/seedance25")
        assert row["credits"] == 15
        assert row["count"] == 2
        assert row["usd"] == 0.9
        assert number(body, "total_usd") >= 0.9
        assert client.get("/api/chat/spend/breakdown?days=7").status_code == 200


class TestTitleModel:
    """Tests for title model."""

    def test_setting_round_trips(self, client: TestClient) -> None:
        """Test that setting round trips."""
        assert dig(client.get("/api/chat/settings"), "title_model") is None
        r = client.put("/api/chat/settings/title-model", json={"title_model": "x/cheap"})
        assert dig(r, "title_model") == "x/cheap"
        # saving the default lists doesn't touch it
        assert dig(client.put("/api/chat/settings", json={}), "title_model") == "x/cheap"
        assert dig(client.put("/api/chat/settings/title-model", json={"title_model": ""}), "title_model") is None

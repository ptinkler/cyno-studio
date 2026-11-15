"""Tests for web.media.library — the library of every upload and creation."""

import io
import os
import shutil
import threading
import time
import types
import zipfile
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import NoReturn

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

import web.core.config as config
import web.media.blank as blank_mod
import web.media.cache as media_cache
import web.media.durations as durations_mod
import web.media.index as index_mod
import web.media.paths as paths_mod
import web.media.thumbs as thumbs_mod
import web.media.video as video_mod
from tests.jsonpath import integer, obj, rows, seq, text
from tests.stubs import stub
from web.core import metadata
from web.core.metadata import ChatConversation, MetadataDB
from web.types import JsonValue

pytest_plugins = ["tests.api_fixtures"]


def _png(color: str | tuple[int, int, int] = "red") -> bytes:
    """A tiny PNG of one colour."""
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), color).save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture
def conv(db: MetadataDB, tmp_path: Path) -> ChatConversation:
    """Provide the conv fixture."""
    c = db.create_conversation(title="Fox chat")
    d = config.ROOT_DIR / "chat" / c.id
    d.mkdir(parents=True)
    (d / "up_1.png").write_bytes(_png())
    (d / "img_1.png").write_bytes(_png("green"))
    db.add_chat_message(
        c.id,
        "user",
        "here",
        media=[{"id": "u", "kind": "image", "source": "upload", "status": "done", "file": "up_1.png"}],
    )
    db.add_chat_message(
        c.id,
        "assistant",
        "drawn",
        media=[
            {
                "id": "g",
                "kind": "image",
                "source": "generated",
                "status": "done",
                "file": "img_1.png",
                "prompt": "fox in snow",
                "model": "a/b",
            },
            {"id": "p", "kind": "video", "source": "generated", "status": "pending", "file": None, "prompt": "x"},
        ],
    )
    return c


def _items(client: TestClient) -> dict[str, dict[str, JsonValue]]:
    """The library listing, keyed by media id."""
    return {text(i, "id"): i for i in rows(client.get("/api/media"), "items")}


def _upload(client: TestClient, name: str = "a.png", data: bytes | None = None) -> dict[str, JsonValue]:
    """Upload a PNG to the library and return the new item."""
    return obj(client.post("/api/media/upload", files={"file": (name, _png() if data is None else data, "image/png")}))


def _capture(*, readable: bool, releases: list[int]) -> types.SimpleNamespace:
    """A stand-in ``cv2.VideoCapture`` that opens, then reads one small frame (or fails), noting each release."""
    frame = np.zeros((2, 2, 3), dtype=np.uint8) if readable else None

    def release() -> None:
        releases.append(1)

    return types.SimpleNamespace(isOpened=stub(lambda: True), read=stub(lambda: (readable, frame)), release=release)


class _CaptureError(cv2.error):
    """What OpenCV raises when it cannot read a video."""

    def __init__(self) -> None:
        """Build the fixed message."""
        super().__init__("cv2 error")


def _failing_capture(*_args: object) -> NoReturn:
    """Stand in for ``cv2.VideoCapture`` where OpenCV itself fails."""
    raise _CaptureError


class TestListing:
    """Tests for listing."""

    def test_lists_everything_with_sources(self, client: TestClient, conv: ChatConversation) -> None:
        """Test that lists everything with sources."""
        _upload(client)
        items = _items(client)
        assert all(i["thumb_url"] for i in items.values())
        assert any(i["origin"] == "library" and i["source"] == "upload" for i in items.values())
        assert items[f"chat:{conv.id}:up_1.png"]["source"] == "upload"
        chat_gen = items[f"chat:{conv.id}:img_1.png"]
        assert chat_gen["source"] == "generated"
        assert chat_gen["conversation_title"] == "Fox chat"
        assert not any(i.startswith(f"chat:{conv.id}:") and "None" in i for i in items)  # pending skipped

    def test_upload_serve_delete(self, client: TestClient) -> None:
        """Test that upload serve delete."""
        item = _upload(client)
        assert item["origin"] == "library"
        assert item["source"] == "upload"
        assert client.get(text(item, "url")).content == _png()
        item_id = text(item, "id")
        assert item_id in _items(client)
        assert client.delete(f"/api/media/{item_id}").status_code == 200
        assert item_id not in _items(client)

    def test_bulk_download_and_delete(self, client: TestClient) -> None:
        """Test that bulk download and delete."""
        ids = [text(_upload(client, f"{n}.png", _png(n)), "id") for n in ("red", "blue")]
        r = client.post("/api/media/bulk-download", json={"ids": [*ids, "lib:missing.png"]})
        assert r.headers["content-type"] == "application/zip"
        assert len(zipfile.ZipFile(io.BytesIO(r.content)).namelist()) == 2  # the missing one is skipped
        r = client.post("/api/media/bulk-delete", json={"ids": [*ids, "lib:missing.png"]})
        assert sorted(str(i) for i in seq(r, "deleted")) == sorted(ids)
        assert seq(r, "failed") == ["lib:missing.png"]
        assert not set(ids) & set(_items(client))

    def test_rejects_non_images(self, client: TestClient) -> None:
        """Test that rejects non images."""
        assert client.post("/api/media/upload", files={"file": ("a.txt", b"x", "text/plain")}).status_code == 400

    @pytest.mark.parametrize("media_id", ["lib:../x.png", "proj:nope:a.png", "chat:abc:..", "zzz:1"])
    def test_bad_ids(self, client: TestClient, media_id: str) -> None:
        """Test that bad ids."""
        assert client.delete(f"/api/media/{media_id}").status_code in (400, 404)

    def test_another_users_chat_media_is_not_reachable(self, client: TestClient, db: MetadataDB) -> None:
        """Chat files live under a global folder keyed only by the (random) conversation id.

        Knowing another user's id must not let you view, delete, or copy their files — only the owning user,
        or anyone for a truly orphaned folder with no conversation row (see test_delete).
        """
        token = metadata.set_tenant("other-user")  # a conversation someone else owns
        try:
            other = db.create_conversation(title="Not yours")
        finally:
            metadata.reset_tenant(token)
        d = config.ROOT_DIR / "chat" / other.id
        d.mkdir(parents=True)
        secret = d / "img_secret.png"
        secret.write_bytes(_png("blue"))
        mid = f"chat:{other.id}:img_secret.png"

        assert client.get(f"/api/media/thumb/{mid}").status_code == 404  # can't view
        assert client.delete(f"/api/media/{mid}").status_code == 404  # can't delete
        assert secret.is_file()  # left untouched
        mine = db.create_conversation(title="Mine")
        copy = client.post("/api/media/import", json={"media_id": mid, "target": "chat", "conversation_id": mine.id})
        assert copy.status_code == 404  # can't copy it out either

    def test_paginates_with_total(self, client: TestClient) -> None:
        """Test that paginates with total."""
        for n in range(5):
            _upload(client, f"a{n}.png", _png((n, 0, 0)))
        full = client.get("/api/media")
        assert integer(full, "total") == 5
        full_ids = [text(i, "id") for i in rows(full, "items")]
        assert len(full_ids) == 5
        page = client.get("/api/media?offset=0&limit=2")
        assert integer(page, "total") == 5
        assert [text(i, "id") for i in rows(page, "items")] == full_ids[:2]
        rest = client.get("/api/media?offset=2&limit=2")
        assert [text(i, "id") for i in rows(rest, "items")] == full_ids[2:4]

    def test_filters_server_side(self, client: TestClient, conv: ChatConversation) -> None:
        """Test that filters server side."""
        images = client.get("/api/media?kind=image")
        assert rows(images, "items")
        assert all(i["kind"] == "image" for i in rows(images, "items"))
        assert integer(images, "total") == len(rows(images, "items"))
        chats = client.get("/api/media?origin=chat")
        assert rows(chats, "items")
        assert all(i["origin"] == "chat" for i in rows(chats, "items"))
        found = client.get("/api/media?q=fox")  # matches prompts / names / where-from
        assert rows(found, "items")
        assert integer(found, "total") == len(rows(found, "items"))


class TestOrphans:
    """Tests for orphans."""

    @pytest.fixture
    def orphans(self, db: MetadataDB, conv: ChatConversation) -> Path:
        """A conversation plus the files that are orphaned in its folder.

        The orphans are an attachment nothing sent, a reference a reply was made from, and the folder of a deleted chat,
        all old enough.
        """
        root = config.ROOT_DIR / "chat"
        (root / conv.id / "up_lost.png").write_bytes(_png())
        (root / conv.id / "up_ref.png").write_bytes(_png())
        db.add_chat_message(
            conv.id,
            "assistant",
            "",
            media=[
                {
                    "id": "r",
                    "kind": "image",
                    "source": "generated",
                    "status": "pending",
                    "params": {"refs": ["up_ref.png"]},
                }
            ],
        )
        (root / "gone").mkdir()
        (root / "gone" / "img_old.png").write_bytes(_png())
        for p in root.rglob("*.png"):
            os.utime(p, (0, 0))
        (root / conv.id / "up_new.png").write_bytes(_png())  # too new — may still be in the composer
        return root

    def test_lists_unrecorded_chat_files(self, client: TestClient, conv: ChatConversation, orphans: Path) -> None:
        """Test that lists unrecorded chat files."""
        items = _items(client)
        orphaned = {k for k, i in items.items() if i["origin"] == "orphan"}
        # Multi-tenant: only orphans in the user's own conversation folders. A
        # folder with no owning conversation ("gone") can't be attributed to a
        # user, so it is shown to no one.
        assert orphaned == {f"chat:{conv.id}:up_lost.png"}
        assert items[f"chat:{conv.id}:up_lost.png"]["conversation_title"] == "Fox chat"
        assert "chat:gone:img_old.png" not in items
        assert items[f"chat:{conv.id}:img_1.png"]["origin"] == "chat"

    def test_delete(self, client: TestClient, orphans: Path) -> None:
        """Test that delete."""
        assert client.delete("/api/media/chat:gone:img_old.png").status_code == 200
        assert not (orphans / "gone" / "img_old.png").exists()


class TestImport:
    """Tests for import."""

    def test_into_a_chat(self, client: TestClient, conv: ChatConversation) -> None:
        """Test that into a chat."""
        lib = _upload(client)
        r = client.post(
            "/api/media/import",
            json={"media_id": lib["id"], "target": "chat", "conversation_id": conv.id},
        )
        file = text(r, "file")
        assert file.startswith("up_")
        assert (config.ROOT_DIR / "chat" / conv.id / file).is_file()

    def test_into_a_character(self, client: TestClient, conv: ChatConversation) -> None:
        """Test that into a character."""
        char = client.post("/api/characters", json={"name": "Fox"})
        r = client.post(
            "/api/media/import",
            json={"media_id": f"chat:{conv.id}:img_1.png", "target": "character", "character_id": integer(char, "id")},
        )
        assert len(seq(r, "images")) == 1

    def test_videos_attach_to_chat_but_not_characters(self, client: TestClient, conv: ChatConversation) -> None:
        """Test that videos attach to chat but not characters."""
        (config.ROOT_DIR / "chat" / conv.id / "vid.mp4").write_bytes(b"fake mp4")
        mid = f"chat:{conv.id}:vid.mp4"
        # A video can be attached to a chat (as a reference-to-video ref)…
        chat = client.post("/api/media/import", json={"media_id": mid, "target": "chat", "conversation_id": conv.id})
        assert chat.status_code == 200
        # …but not added to a character (images only).
        char = client.post("/api/media/import", json={"media_id": mid, "target": "character", "character_id": 1})
        assert char.status_code == 400


class TestDelete:
    """Tests for delete."""

    def test_chat_item_leaves_its_message(self, client: TestClient, db: MetadataDB, conv: ChatConversation) -> None:
        """Test that chat item leaves its message."""
        assert client.delete(f"/api/media/chat:{conv.id}:img_1.png").status_code == 200
        reply = db.get_chat_messages(conv.id)[-1]
        assert [i["id"] for i in reply.media] == ["p"]
        assert not (config.ROOT_DIR / "chat" / conv.id / "img_1.png").exists()

    def test_copies_survive(self, client: TestClient, conv: ChatConversation) -> None:
        """Test that copies survive."""
        char_id = integer(client.post("/api/characters", json={"name": "Fox"}), "id")
        client.post(
            "/api/media/import",
            json={"media_id": f"chat:{conv.id}:img_1.png", "target": "character", "character_id": char_id},
        )
        client.delete(f"/api/media/chat:{conv.id}:img_1.png")
        c = client.get(f"/api/characters/{char_id}")
        assert client.get(f"/api/characters/{integer(c, 'id')}/images/{text(c, 'images', 0)}").status_code == 200


class TestBlocked:
    """Tests for blocked."""

    @pytest.fixture
    def blocked(self, db: MetadataDB, conv: ChatConversation) -> Path:
        """A conversation plus the blocked generations.

        They are a moderated failure and a black image in a reply, an ordinary failure (kept), and a moderated failure
        detached to the library.
        """
        d = config.ROOT_DIR / "chat" / conv.id
        (d / "img_black.png").write_bytes(_png("black"))
        db.add_chat_message(conv.id, "user", "again")
        db.add_chat_message(
            conv.id,
            "assistant",
            "",
            media=[
                {
                    "id": "m",
                    "kind": "image",
                    "source": "generated",
                    "status": "error",
                    "moderated": True,
                    "error": "flagged",
                },
                {"id": "b", "kind": "image", "source": "generated", "status": "done", "file": "img_black.png"},
                {
                    "id": "t",
                    "kind": "image",
                    "source": "generated",
                    "status": "error",
                    "moderated": False,
                    "error": "timeout",
                },
            ],
        )
        old = db.add_chat_message(conv.id, "user", "older")
        db.add_chat_message(
            conv.id,
            "assistant",
            "",
            parent_id=old.id,
            media=[
                {
                    "id": "lm",
                    "kind": "video",
                    "source": "generated",
                    "status": "error",
                    "moderated": True,
                    "error": "nsfw",
                    "job_id": "venice:m:q",
                }
            ],
        )
        db.delete_chat_exchange(conv.id, old.id)
        return d

    @pytest.fixture(autouse=True)
    def _fresh_blank_checks(self) -> Iterator[None]:
        blank_mod.reset_blank_checks()
        yield
        blank_mod.reset_blank_checks()

    def test_counts(self, client: TestClient, blocked: Path) -> None:
        """Test that counts."""
        assert obj(client.get("/api/media/blocked")) == {"moderated": 2, "black": 1}

    def test_black_images_are_checked_once_even_across_restarts(
        self, client: TestClient, blocked: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that black images are checked once even across restarts."""
        assert integer(client.get("/api/media/blocked"), "black") == 1
        blank_mod.reset_blank_checks()  # as after a restart

        def no_decoding(data: bytes) -> NoReturn:
            pytest.fail("decoded again")

        monkeypatch.setattr(blank_mod, "is_blank_image", no_decoding)
        assert integer(client.get("/api/media/blocked"), "black") == 1

    def test_imported_images_are_not_checked(
        self, client: TestClient, db: MetadataDB, conv: ChatConversation, blocked: Path
    ) -> None:
        """Test that imported images are not checked."""
        (blocked / "img_imported.png").write_bytes(_png("black"))
        db.add_chat_message(
            conv.id,
            "assistant",
            "",
            media=[
                {
                    "id": "i",
                    "kind": "image",
                    "source": "generated",
                    "status": "done",
                    "file": "img_imported.png",
                    "import_file": "file_x",
                }
            ],
        )
        assert integer(client.get("/api/media/blocked"), "black") == 1  # only the app's own

    def test_clear_removes_them_and_keeps_the_rest(
        self, client: TestClient, db: MetadataDB, conv: ChatConversation, blocked: Path
    ) -> None:
        """Test that clear removes them and keeps the rest."""
        assert obj(client.post("/api/media/blocked/clear")) == {"cleared": 3}
        media = {text(i, "id") for m in db.get_chat_messages(conv.id) for i in m.media}
        assert {"m", "b", "lm"}.isdisjoint(media)
        assert {"t", "g", "u", "p"} <= media
        assert not (blocked / "img_black.png").exists()
        assert (blocked / "img_1.png").exists()
        assert db.list_chat_library() == []
        assert obj(client.get("/api/media/blocked")) == {"moderated": 0, "black": 0}


class TestThumbnails:
    """Tests for thumbnails."""

    def _big_png(self, size: tuple[int, int] = (1600, 900)) -> bytes:
        """A large PNG, so its thumbnail is a real downscale."""
        buf = io.BytesIO()
        Image.new("RGB", size, "purple").save(buf, "PNG")
        return buf.getvalue()

    def test_image_thumb_is_small_and_cached(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that image thumb is small and cached."""
        thumb_url = text(_upload(client, data=self._big_png()), "thumb_url")
        r = client.get(thumb_url)
        assert r.status_code == 200
        assert r.headers["content-type"] == "image/jpeg"
        thumb = Image.open(io.BytesIO(r.content))
        assert min(thumb.size) == 320
        assert thumb.size[0] > thumb.size[1]
        # Second request comes from the cache — no re-encoding

        monkeypatch.setattr(thumbs_mod.Image, "open", stub(lambda: pytest.fail("re-encoded")))
        assert client.get(thumb_url).content == r.content

    def test_video_thumb_uses_the_first_frame(
        self, client: TestClient, conv: ChatConversation, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that video thumb uses the first frame."""
        (config.ROOT_DIR / "chat" / conv.id / "vid.mp4").write_bytes(b"fake mp4")
        buf = io.BytesIO()
        Image.new("RGB", (640, 360), "orange").save(buf, "JPEG")
        monkeypatch.setattr(thumbs_mod, "first_frame_jpeg", stub(buf.getvalue))
        r = client.get(f"/api/media/thumb/chat:{conv.id}:vid.mp4")
        assert r.status_code == 200
        assert Image.open(io.BytesIO(r.content)).size == (569, 320)

    def test_unreadable_file_has_no_thumb(
        self, client: TestClient, conv: ChatConversation, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that unreadable file has no thumb."""
        (config.ROOT_DIR / "chat" / conv.id / "vid.mp4").write_bytes(b"fake mp4")
        monkeypatch.setattr(thumbs_mod, "first_frame_jpeg", stub(lambda: None))
        assert client.get(f"/api/media/thumb/chat:{conv.id}:vid.mp4").status_code == 404


class TestFirstFrameJpeg:
    """first_frame_jpeg: the video frame the library's thumbnails are made from."""

    def test_unopenable_file(self, tmp_path: Path) -> None:
        """Test that unopenable file."""
        fp = tmp_path / "notavideo.mp4"
        fp.write_bytes(b"definitely not a video")
        assert video_mod.first_frame_jpeg(fp) is None

    def test_read_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that read fails."""
        fp = tmp_path / "readfail.mp4"
        fp.write_bytes(b"\x00" * 100)
        releases: list[int] = []
        cap = _capture(readable=False, releases=releases)
        monkeypatch.setattr(video_mod.cv2, "VideoCapture", stub(lambda: cap))
        assert video_mod.first_frame_jpeg(fp) is None
        assert releases == [1]

    def test_success(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that success."""
        fp = tmp_path / "success.mp4"
        fp.write_bytes(b"\x00" * 100)
        cap = _capture(readable=True, releases=[])
        monkeypatch.setattr(video_mod.cv2, "VideoCapture", stub(lambda: cap))
        assert video_mod.first_frame_jpeg(fp) is not None

    def test_exception(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that exception."""
        fp = tmp_path / "exc.mp4"
        fp.write_bytes(b"\x00" * 100)
        monkeypatch.setattr(video_mod.cv2, "VideoCapture", _failing_capture)
        assert video_mod.first_frame_jpeg(fp) is None

    def test_delete_drops_the_cached_thumb(self, client: TestClient) -> None:
        """Test that delete drops the cached thumb."""
        item = _upload(client)
        client.get(text(item, "thumb_url"))
        assert list(paths_mod.thumb_dir().iterdir())
        client.delete(f"/api/media/{text(item, 'id')}")
        assert not list(paths_mod.thumb_dir().iterdir())

    def test_at_most_two_made_at_once(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that at most two made at once."""
        thumb_urls = [text(_upload(client, f"{n}.png", _png((n, 0, 0))), "thumb_url") for n in range(8)]
        real, lock, state = thumbs_mod.make_thumb, threading.Lock(), {"now": 0, "peak": 0}

        def slow_thumb(path: Path, size: int = thumbs_mod.THUMB_SIZE) -> Path | None:
            with lock:
                state["now"] += 1
                state["peak"] = max(state["peak"], state["now"])
            time.sleep(0.05)
            try:
                return real(path, size)
            finally:
                with lock:
                    state["now"] -= 1

        monkeypatch.setattr(thumbs_mod, "make_thumb", slow_thumb)

        def status_of(url: str) -> int:
            return client.get(url).status_code

        with ThreadPoolExecutor(8) as pool:
            codes = list(pool.map(status_of, thumb_urls))
        assert codes == [200] * 8
        assert state["peak"] <= thumbs_mod.THUMB_WORKERS


class TestUploadDedupe:
    """Tests for upload dedupe."""

    def test_same_image_is_stored_once_and_unsent_one_can_be_discarded(
        self, client: TestClient, conv: ChatConversation, db: MetadataDB
    ) -> None:
        """Test that same image is stored once and unsent one can be discarded."""
        c = db.create_conversation(title="Dup")
        url = f"/api/chat/conversations/{c.id}/attachments"
        a = text(client.post(url, files={"file": ("a.png", _png(), "image/png")}), "file")
        b = text(client.post(url, files={"file": ("b.png", _png(), "image/png")}), "file")
        assert a == b  # identical bytes → one file
        assert obj(client.delete(f"{url}/{a}")) == {"deleted": True}
        assert obj(client.delete(f"{url}/{a}")) == {"deleted": False}  # already gone


def _seed_clips(db: MetadataDB, conv: ChatConversation) -> None:
    """Add three video clips to ``conv`` and start the media module with a clean duration state."""
    d = config.ROOT_DIR / "chat" / conv.id
    for n in range(3):
        (d / f"clip_{n}.mp4").write_bytes(b"not really a video")
    db.add_chat_message(
        conv.id,
        "assistant",
        "clips",
        media=[
            {
                "id": f"v{n}",
                "kind": "video",
                "source": "generated",
                "status": "done",
                "file": f"clip_{n}.mp4",
                "prompt": "x",
            }
            for n in range(3)
        ],
    )
    index_mod.invalidate_list()
    durations_mod.reset_durations(loaded=True)


def _clip_path(db: MetadataDB, name: str) -> Path:
    """Where the first conversation keeps the clip called ``name``."""
    return config.ROOT_DIR / "chat" / next(iter(db.list_conversations())).id / name


def _durations_by_name(client: TestClient) -> dict[str, JsonValue]:
    """The library's video lengths, keyed by file name."""
    return {text(i, "name"): i["duration"] for i in rows(client.get("/api/media"), "items") if "duration" in i}


class TestVideoDurations:
    """Reading a length opens the file with OpenCV, which is slow on a NAS.

    So building the list never does it: a request fills in the page it returns, and what's been read is kept in the
    database (MediaDuration).
    """

    @pytest.fixture
    def clips(self, db: MetadataDB, conv: ChatConversation) -> None:
        """Three clips in the library, with nothing read from them yet."""
        _seed_clips(db, conv)

    @pytest.mark.usefixtures("clips")
    def test_list_build_never_opens_a_video(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that list build never opens a video."""
        monkeypatch.setattr(
            durations_mod, "video_seconds", stub(lambda: pytest.fail("the list build read a video header"))
        )
        # The clips are in the library and get built into the list, but this
        # page holds no video, so nothing opens one
        r = client.get("/api/media?kind=image")
        assert r.status_code == 200
        assert integer(r, "total")
        assert not any(i["kind"] == "video" for i in rows(r, "items"))

    @pytest.mark.usefixtures("clips")
    def test_a_page_fills_in_its_own_lengths_and_remembers_them(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that a page fills in its own lengths and remembers them."""
        reads: list[str] = []

        def video_seconds(path: str, mtime: int) -> float:
            reads.append(path)
            return 12.5

        monkeypatch.setattr(durations_mod, "video_seconds", video_seconds)
        items = rows(client.get("/api/media"), "items")
        clip = next(i for i in items if i["name"] == "clip_0.mp4")
        assert clip["duration"] == 12.5
        assert len(reads) == 3
        # Read once: the next request (and the next process) uses what's stored
        reads.clear()
        index_mod.invalidate_list()
        durations_mod.reset_durations(loaded=False)  # as a fresh process would start: nothing in memory
        assert _durations_by_name(client)["clip_0.mp4"] == 12.5
        assert reads == []

    @pytest.mark.usefixtures("clips")
    def test_a_re_encoded_file_is_read_again(
        self, client: TestClient, db: MetadataDB, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that a re encoded file is read again."""
        monkeypatch.setattr(durations_mod, "video_seconds", stub(lambda: 4.0))
        client.get("/api/media")
        _clip_path(db, "clip_0.mp4").write_bytes(b"longer now")
        monkeypatch.setattr(durations_mod, "video_seconds", stub(lambda: 9.0))
        index_mod.invalidate_list()
        durations = _durations_by_name(client)
        assert durations["clip_0.mp4"] == 9.0
        assert durations["clip_1.mp4"] == 4.0

    @pytest.mark.usefixtures("clips")
    def test_fill_is_capped_so_one_request_cannot_stall(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that fill is capped so one request cannot stall."""
        monkeypatch.setattr(durations_mod, "DURATION_FILL_BUDGET", 2)
        reads: list[str] = []

        def video_seconds(path: str, mtime: int) -> float:
            reads.append(path)
            return 3.0

        monkeypatch.setattr(durations_mod, "video_seconds", video_seconds)
        client.get("/api/media")
        assert len(reads) == 2


class TestMediaCache:
    """The cache lives under <data>/cache with the thumbnails.

    So deleting that folder wipes it, and it can't grow past one row per file that exists.
    """

    @pytest.fixture(autouse=True)
    def _cached(self, client: TestClient, db: MetadataDB, conv: ChatConversation) -> None:
        """Three clips in the library, their lengths already read into the cache."""
        _seed_clips(db, conv)
        client.get("/api/media")  # fills in the clips' lengths

    def test_it_sits_in_the_cache_folder_and_a_wipe_is_harmless(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that it sits in the cache folder and a wipe is harmless."""
        assert media_cache.db_path().parent == config.ROOT_DIR / "cache"
        assert media_cache.durations()
        shutil.rmtree(config.ROOT_DIR / "cache")  # what a user wiping the cache does
        assert media_cache.durations() == {}
        media_cache.reset_sweep()
        assert client.get("/api/media").status_code == 200  # reads them again, no complaint

    def test_a_re_encoded_file_replaces_its_row(
        self, client: TestClient, db: MetadataDB, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that a re encoded file replaces its row."""
        before = len(media_cache.durations())
        path = _clip_path(db, "clip_0.mp4")
        path.write_bytes(b"re-encoded")
        monkeypatch.setattr(durations_mod, "video_seconds", stub(lambda: 7.0))
        index_mod.invalidate_list()
        client.get("/api/media")
        assert len(media_cache.durations()) == before  # replaced, not added
        assert media_cache.durations()[str(path)][1] == 7.0

    def test_deleting_media_drops_its_row(self, client: TestClient, db: MetadataDB) -> None:
        """Test that deleting media drops its row."""
        conv_id = next(iter(db.list_conversations())).id
        path = str(config.ROOT_DIR / "chat" / conv_id / "clip_0.mp4")
        assert path in media_cache.durations()
        assert client.delete(f"/api/media/chat:{conv_id}:clip_0.mp4").status_code == 200
        assert path not in media_cache.durations()

    def test_a_sweep_drops_rows_whose_file_has_gone(self, db: MetadataDB) -> None:
        """Test that a sweep drops rows whose file has gone."""
        _clip_path(db, "clip_1.mp4").unlink()
        assert media_cache.sweep() == 1
        assert all("clip_1.mp4" not in p for p in media_cache.durations())

    def test_an_unusable_cache_file_just_means_no_cache(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Test that an unusable cache file just means no cache."""
        blocker = tmp_path / "blocker"  # a file where the cache folder should be
        blocker.write_text("x")
        monkeypatch.setattr(media_cache, "db_path", stub(lambda: blocker / "media-cache.sqlite"))
        assert media_cache.durations() == {}  # degraded, not raised
        media_cache.remember([("/a.mp4", 1, 2.0)])
        media_cache.forget("/a.mp4")
        assert media_cache.sweep() == 0

"""An imported zip can't unpack to more than is allowed, and only media files are unpacked."""

import io
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from web.transfer.limits import MAX_IMPORT_BYTES, EntryTooLargeError, copy_entry, is_media_file, read_entry

pytest_plugins = ["tests.chat_fixtures"]


def _zip(files: dict[str, bytes]) -> zipfile.ZipFile:
    raw = io.BytesIO()
    with zipfile.ZipFile(raw, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return zipfile.ZipFile(io.BytesIO(raw.getvalue()))


class TestEntryLimits:
    """Entries are counted as they are read, not by what the header claims."""

    def test_reads_within_the_limit(self) -> None:
        """A small entry reads back whole."""
        assert read_entry(_zip({"a.txt": b"hello"}), "a.txt", limit=5) == b"hello"

    def test_refuses_an_entry_that_unpacks_larger(self) -> None:
        """A bomb: tiny compressed, huge unpacked."""
        zf = _zip({"bomb.bin": b"\0" * 10_000})
        with pytest.raises(EntryTooLargeError):
            read_entry(zf, "bomb.bin", limit=1000)

    def test_copy_leaves_nothing_behind_when_refused(self, tmp_path: Path) -> None:
        """The partly written file is removed."""
        zf = _zip({"bomb.bin": b"\0" * 10_000})
        with pytest.raises(EntryTooLargeError):
            copy_entry(zf, "bomb.bin", tmp_path / "bomb.png", limit=1000)
        assert not (tmp_path / "bomb.png").exists()

    @pytest.mark.parametrize(
        ("name", "media"),
        [("a.png", True), ("b.MP4", True), ("c.mp3", True), ("x.html", False), ("y.svg", False), ("z", False)],
    )
    def test_only_media_is_unpacked(self, name: str, media: bool) -> None:
        """Pictures, videos and audio; not pages or scripts."""
        assert is_media_file(name) is media


def test_declared_upload_size_is_capped(client: TestClient) -> None:
    """Nobody can announce an upload big enough to fill the disk."""
    ok = client.post("/api/chat/import/chatgpt/uploads", json={"name": "x.zip", "size": MAX_IMPORT_BYTES})
    big = client.post("/api/chat/import/chatgpt/uploads", json={"name": "x.zip", "size": MAX_IMPORT_BYTES + 1})
    assert ok.status_code == 200
    assert big.status_code == 422

"""Bounds on what an imported zip may unpack to.

A zip's header says how big each entry is, but the claim isn't enforced when it is read, so a small
upload can expand to fill the disk. Entries are counted as they are read instead.
"""

import zipfile
from pathlib import Path
from typing import IO

from web.media.kinds import AUDIO_SUFFIXES, VIDEO_SUFFIXES
from web.uploads.files import IMAGE_UPLOAD_TYPES

MAX_IMPORT_BYTES = 10 * 1024**3  # a whole export zip (ChatGPT's are several GB with images)
MAX_ENTRY_BYTES = 1024**3  # one file inside it
CHUNK = 1 << 20

# Pictures, videos and audio, by extension. Not `.svg` (a picture that can carry script) or anything else.
IMPORTED_SUFFIXES = frozenset({*IMAGE_UPLOAD_TYPES.values(), ".jpeg", *VIDEO_SUFFIXES, *AUDIO_SUFFIXES})


class EntryTooLargeError(ValueError):
    """One file in the zip unpacks to more than is allowed."""

    def __init__(self, name: str) -> None:
        """Name the entry."""
        super().__init__(f"{name} is larger than {MAX_ENTRY_BYTES // 1024**2} MB when unpacked")


def is_media_file(name: str) -> bool:
    """Whether a file name is a picture, video or audio clip (nothing else is unpacked into a chat)."""
    return Path(name).suffix.lower() in IMPORTED_SUFFIXES


def read_entry(zf: zipfile.ZipFile, name: str, limit: int = MAX_ENTRY_BYTES) -> bytes:
    """An entry's bytes, refusing one that unpacks to more than `limit`."""
    with zf.open(name) as src:
        data = src.read(limit + 1)
    if len(data) > limit:
        raise EntryTooLargeError(name)
    return data


def _write_capped(src: IO[bytes], dst: IO[bytes], name: str, limit: int) -> None:
    written = 0
    while chunk := src.read(CHUNK):
        written += len(chunk)
        if written > limit:
            raise EntryTooLargeError(name)
        dst.write(chunk)


def copy_entry(zf: zipfile.ZipFile, name: str, target: Path, limit: int = MAX_ENTRY_BYTES) -> None:
    """Write an entry to `target`, refusing (and leaving nothing behind for) one that unpacks to more than `limit`."""
    try:
        with zf.open(name) as src, target.open("wb") as dst:
            _write_capped(src, dst, name, limit)
    except (EntryTooLargeError, zipfile.BadZipFile):
        target.unlink(missing_ok=True)
        raise

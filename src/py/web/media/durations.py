"""Video lengths: read lazily, remembered in memory and in the media cache."""

import threading
from pathlib import Path

from web.media import cache as media_cache
from web.media.paths import LibraryEntry, item_path
from web.media.video import video_seconds

# Reading a length means opening the file with OpenCV, which on network or slow
# storage costs ~a tenth of a second each — enough to make building the whole list take the
# best part of a minute. So lengths are remembered in the media cache (see
# web/media/cache.py), the list build only ever uses what's already known, and
# a request reads a handful of the rest for the page it returns (the length is
# a caption on a tile, so arriving a request later costs nothing).
DURATION_FILL_BUDGET = 48


class _Durations:
    """Known video lengths by path: (mtime_ns, seconds), read from the media cache once per process."""

    def __init__(self) -> None:
        self._known: dict[str, tuple[int, float | None]] | None = None
        self._lock = threading.Lock()

    def reset(self, *, loaded: bool) -> None:
        """Drop the in-memory lengths: empty but loaded, or unloaded (as a fresh process starts)."""
        with self._lock:
            self._known = {} if loaded else None

    def get(self) -> dict[str, tuple[int, float | None]]:
        """The known lengths; the first call loads them and starts the stale-row sweep."""
        with self._lock:
            if self._known is None:
                self._known = media_cache.durations()
                media_cache.sweep_in_background()
            return self._known

    def update(self, read: list[tuple[str, int, float | None]]) -> None:
        """Add freshly read lengths (nothing to do while the cache is still unloaded)."""
        with self._lock:
            if self._known is not None:
                self._known.update({path: (mtime_ns, seconds) for path, mtime_ns, seconds in read})


_durations = _Durations()


def reset_durations(*, loaded: bool) -> None:
    """Drop the in-memory lengths: empty but loaded, or unloaded (as a fresh process starts)."""
    _durations.reset(loaded=loaded)


def durations_map() -> dict[str, tuple[int, float | None]]:
    """Return known lengths mapped to path, mtime, and seconds."""
    return _durations.get()


def duration_known(path: Path) -> bool:
    """Return whether this exact file version has already been checked.

    This includes files whose duration could not be determined, preventing
    repeated attempts on every request.
    """
    try:
        mtime_ns = path.stat().st_mtime_ns
    except OSError:
        return False
    known = durations_map().get(str(path))
    return bool(known and known[0] == mtime_ns)


def known_duration(path: Path, kind: str | None) -> float | None:
    """The length if it's already been read; never opens the file."""
    if kind != "video":
        return None
    try:
        mtime_ns = path.stat().st_mtime_ns
    except OSError:
        return None
    known = durations_map().get(str(path))
    return known[1] if known and known[0] == mtime_ns else None


def _read_duration(path: Path) -> tuple[int, float | None] | None:
    """Open the file and read its length (the slow part); None if it's gone."""
    try:
        mtime_ns = path.stat().st_mtime_ns
        return mtime_ns, video_seconds(str(path), mtime_ns)
    except OSError:
        return None


def _unread_video_path(item: LibraryEntry) -> Path | None:
    """The file of a video item whose length isn't known yet, else None."""
    if item.get("kind") != "video" or item.get("duration") is not None:
        return None
    path = item_path(item)
    return None if path is None or duration_known(path) else path


def _remember_durations(read: list[tuple[str, int, float | None]]) -> None:
    """Keep freshly read lengths in memory and on disk."""
    if not read:
        return
    _durations.update(read)
    media_cache.remember(read)


def fill_durations(items: list[LibraryEntry]) -> None:
    """Fill missing video durations in items, subject to a read budget.

    The budget keeps a page of previously unseen videos from making one
    request slow.
    """
    budget = DURATION_FILL_BUDGET
    read: list[tuple[str, int, float | None]] = []
    for item in items:
        if budget <= 0:
            break
        path = _unread_video_path(item)
        if path is None:
            continue
        budget -= 1
        got = _read_duration(path)
        if got is None:
            continue
        item["duration"] = got[1]
        read.append((str(path), *got))
    _remember_durations(read)

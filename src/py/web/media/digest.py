"""A file's content digest, to tell identical pictures apart from different ones."""

import hashlib
from pathlib import Path

# (path, size, mtime) -> digest, so an unchanged file is read once
_cache: dict[tuple[str, int, int], str] = {}
_CACHE_MAX = 20000


def file_digest(path: Path) -> str | None:
    """The SHA-256 of a file's bytes (None when it can't be read)."""
    try:
        st = path.stat()
        key = (str(path), st.st_size, st.st_mtime_ns)
        if key not in _cache:
            if len(_cache) >= _CACHE_MAX:
                _cache.clear()
            _cache[key] = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None
    return _cache[key]

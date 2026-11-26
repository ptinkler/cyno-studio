"""Every folder that holds the current user's media."""

from collections.abc import Iterator
from pathlib import Path

from web.core.metadata import get_db
from web.media.paths import chat_dir, library_dir


def media_dirs() -> Iterator[Path]:
    """The library folder, then each of the user's chat folders (read lazily: a caller may stop at the first hit)."""
    yield library_dir()
    for conv_id in get_db().conversation_titles():
        yield chat_dir(conv_id)

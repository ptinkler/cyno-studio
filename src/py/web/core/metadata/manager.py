"""Compose the metadata database from domain mixins.

This module also provides the process-wide database singleton accessor.
"""

import threading

from web.core.metadata.characters import CharacterMixin
from web.core.metadata.conversations import ConversationMixin
from web.core.metadata.imports import ImportMixin
from web.core.metadata.instructions import InstructionMixin
from web.core.metadata.library import LibraryMixin
from web.core.metadata.messages import MessageMixin
from web.core.metadata.signins import SigninMixin
from web.core.metadata.users import UserMixin


class MetadataDB(
    UserMixin,
    SigninMixin,
    ConversationMixin,
    InstructionMixin,
    CharacterMixin,
    MessageMixin,
    ImportMixin,
    LibraryMixin,
):
    """Manage metadata through a SQLAlchemy engine.

    The engine, schema catch-up, and locked session live on ``DBBase``; domain
    methods come from the mixins.
    """


class _Shared:
    """The process-wide database instance, built on first use."""

    instance: MetadataDB | None = None


_shared = _Shared()
_db_init_lock = threading.Lock()


def swap_db_instance(new: MetadataDB | None) -> MetadataDB | None:
    """Replace the global database instance (None builds a fresh one on next use); returns the old one."""
    with _db_init_lock:
        old, _shared.instance = _shared.instance, new
    return old


def get_db() -> MetadataDB:
    """Get the global metadata database instance."""
    db = _shared.instance
    if db is None:
        with _db_init_lock:
            db = _shared.instance
            if db is None:
                db = _shared.instance = MetadataDB()
    return db

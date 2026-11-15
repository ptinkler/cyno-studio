"""The state every layer of a chat turn shares: the conversation, settings, message row and cost."""

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from web import characters
from web.chat.catalogue import model_info
from web.chat.generation import (
    conversation_instructions,
)
from web.chat.helpers import branch_to, effective_ids
from web.chat.models import TurnSettings
from web.core.metadata import get_db
from web.core.metadata.models import ChatMessage
from web.types import JsonValue

if TYPE_CHECKING:
    from web.core.metadata.models import Character

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class TurnLink:
    """How a running turn talks to whoever started it: events out (`emit`), cancellation in (`cancel`)."""

    emit: Callable[[dict[str, JsonValue]], None]
    cancel: threading.Event


@dataclass(frozen=True)
class Reword:
    """A reply whose words are being written again, rather than a new reply.

    `spent` is what the reply already cost (its pictures, and the words being replaced), so the total stays
    right. `rewrite` is (the reply's current words, how to change them): the chat model sees its reply and
    the instruction, and writes it again; None = write them afresh from the conversation alone. `after` is for
    the stream that runs the turn, not the turn: it runs once the turn has saved, and a message it returns goes
    out as a final "done".
    """

    spent: float = 0.0
    rewrite: tuple[str, str] | None = None
    after: Callable[[], ChatMessage | None] | None = None


class TurnBase:
    """The state every layer of a chat turn shares: the conversation, settings, message row and cost."""

    def __init__(
        self,
        conv_id: str,
        settings: TurnSettings,
        message_id: int,
        link: TurnLink,
        reword: Reword | None = None,
    ) -> None:
        """Set up the turn: which conversation, which settings, which message row.

        `reword` is given when only the reply's words are being generated again.
        """
        self.conv_id = conv_id
        self.s = settings
        self.message_id = message_id
        self.emit = link.emit
        self.cancel = link.cancel
        self.db = get_db()
        # Only this reply's own branch — other versions of earlier turns aren't context
        self.history = branch_to(self.db.get_chat_messages(conv_id), message_id)[:-1]
        self.instructions = conversation_instructions(conv_id)
        conv = self.db.get_conversation(conv_id)
        self.characters: list[Character] = []  # attached (to the chat, or by its defaults); the only ones a turn uses
        if self._characters_usable():  # attached ones stay attached, just unused, otherwise
            self.characters = characters.load(effective_ids(conv, "character"), self.db)
        self.content: str = ""
        # What this reply has already cost (its pictures, when only the words
        # are being generated again), so the total stays right.
        self.cost: float = reword.spent if reword else 0.0
        self.media: list[dict[str, JsonValue]] = []
        self.rewrite = reword.rewrite if reword else None
        # Generation calls already run this turn: a model that repeats the
        # exact same call (same tool, same arguments) isn't charged twice
        self._calls_made: set[str] = set()

    def _append(self, text: str) -> None:
        self.content += text
        self.emit({"type": "delta", "text": text})

    def _add_media(self, item: dict[str, JsonValue]) -> None:
        self.media.append(item)
        self.db.append_chat_media_item(self.message_id, item)
        self.emit({"type": "media", "message_id": self.message_id, "item": dict(item)})

    def _update_media(self, item: dict[str, JsonValue], **fields: JsonValue) -> None:
        item.update(fields)
        media_id = item.get("id")
        if isinstance(media_id, str):
            self.db.update_chat_media_item(self.message_id, media_id, **fields)
        self.emit({"type": "media", "message_id": self.message_id, "item": dict(item)})

    def _characters_usable(self) -> bool:
        """Return whether this turn's selected models can use characters.

        In Auto mode, the chat model must support tools and the image model
        must accept references. Video mode requires a reference-capable model.
        """
        if self.s.mode == "text":
            return True
        if self.s.mode == "video":
            # Only video models that take reference images (Venice's refs→video)
            info = model_info("video", self.s.video_model) or {}
            return bool(info.get("reference_images") or info.get("family") == "motion")
        if not self.s.image_model or not self._accepts_refs():
            return False
        if self.s.mode == "auto":
            info = model_info("text", self.s.text_model)
            return info is None or bool(info.get("supports_tools"))
        return True

    def _accepts_refs(self) -> bool:
        info = model_info("image", self.s.image_model)
        return not info or "image" in (info.get("input_modalities") or [])

    def _max_refs(self) -> int | None:
        """How many reference images the image model takes (None = unknown)."""
        return (model_info("image", self.s.image_model) or {}).get("max_refs")

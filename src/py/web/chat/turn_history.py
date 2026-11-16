"""What a turn looks up in the chat so far: latest media, pins, instructions, references, characters."""

import logging
from collections.abc import Mapping
from datetime import datetime

from web import characters
from web.characters import CharacterInfo
from web.chat.catalogue import RefMode
from web.chat.constants import (
    CONSISTENCY_REFS,
)
from web.chat.generation import (
    HistoryShape,
    RefLimits,
    characters_note,
    conversation,
    dedupe,
    plan_refs,
)
from web.chat.helpers import effective_ids
from web.chat.schemas import CharactersEvent
from web.chat.tools import (
    SYSTEM_PROMPT,
)
from web.chat.turn_base import TurnBase
from web.core.metadata.models import Character, ChatInstruction, ChatMessage
from web.types import JsonValue

log = logging.getLogger(__name__)


class HistoryTurn(TurnBase):
    """What a turn looks up in the chat so far: latest media, pins, instructions, references, characters."""

    def _last_user(self) -> ChatMessage | None:
        return next((m for m in reversed(self.history) if m.role == "user"), None)

    def _latest_image(self) -> str | None:
        images = self._latest_images(1)
        return images[0] if images else None

    def _latest_images(self, n: int) -> list[str]:
        """The n most recent finished images (this turn first, then history)."""

        def done_images(media: list[dict[str, JsonValue]]) -> list[str]:
            return [
                file
                for item in reversed(media)
                if item["kind"] == "image"
                and item.get("status") == "done"
                and isinstance((file := item.get("file")), str)
            ]

        found = done_images(self.media)
        for msg in reversed(self.history):
            found.extend(done_images(msg.media))
        return found[:n]

    def _pinned_images(self) -> list[str]:
        """Images the user pinned on this branch, oldest first."""
        return [
            file
            for msg in self.history
            for item in msg.media
            if item.get("pinned")
            and item["kind"] == "image"
            and item.get("status", "done") == "done"
            and isinstance((file := item.get("file")), str)
        ]

    def _latest_video(self) -> str | None:
        """The most recent finished video (this turn first, then history)."""
        return self._latest_media_file("video")

    def _latest_audio(self) -> str | None:
        """The most recent audio attachment (this turn first, then history).

        It is the uploaded track a lip-sync model drives a portrait with.
        """
        return self._latest_media_file("audio")

    def _latest_media_file(self, kind: str) -> str | None:
        for item in [*reversed(self.media), *(i for m in reversed(self.history) for i in reversed(m.media))]:
            if item["kind"] == kind and item.get("status") == "done" and isinstance((file := item.get("file")), str):
                return file
        return None

    def _build_llm_messages(self, *, vision: bool, as_tool_calls: bool = False) -> list[dict[str, JsonValue]]:
        messages: list[dict[str, JsonValue]] = [
            {
                "role": "system",
                "content": SYSTEM_PROMPT.format(today=datetime.now().astimezone().strftime("%A %d %B %Y")),
            }
        ]
        if self.instructions:
            # The user's own custom instructions, verbatim
            messages.append({"role": "system", "content": self.instructions})
        note = characters_note(self.characters)
        if note:
            messages.append({"role": "system", "content": note})
        shape = HistoryShape(self.s.history_limit, self.s.image_limit)
        messages += conversation(self.conv_id, self.history, shape, vision=vision, as_tool_calls=as_tool_calls)
        if self.rewrite:
            previous, instruction = self.rewrite
            rewrite_turn: list[dict[str, JsonValue]] = [
                {"role": "assistant", "content": previous},
                {
                    "role": "user",
                    "content": (
                        "Rewrite your reply above with this change: "
                        f"{instruction}\n\nReply with the complete rewritten reply only — no preamble, "
                        "no comments on what changed."
                    ),
                },
            ]
            messages += rewrite_turn
        return messages

    def _chat_instructions(self) -> list[ChatInstruction]:
        """The instruction snippets applied to this chat: its own, its defaults', and those in its groups."""
        conv = self.db.get_conversation(self.conv_id)
        ids = set(effective_ids(conv, "instruction"))
        group_ids = set(effective_ids(conv, "instruction_group"))
        for group in self.db.list_instruction_groups():
            if group.id in group_ids:
                ids.update(group.snippet_ids)
        return [i for i in self.db.list_instructions() if i.id in ids]

    def _image_refs(
        self, args: Mapping[str, JsonValue], source: str | None, chars: list[Character]
    ) -> tuple[list[str], list[str]]:
        """Choose reference images for image generation and report any omitted.

        Priority is the edit source, selected characters, pinned images, then
        recent images requested with `keep_consistent`. Pins are user-selected.
        """
        if not self._accepts_refs():
            return [], []  # this image model can't take references
        lead = [source] if source else []
        pinned = self._pinned_images()
        recent = []
        if args.get("keep_consistent") is True:
            recent = [f for f in self._latest_images(CONSISTENCY_REFS) if f not in pinned and f not in lead]
        chat_refs = dedupe(lead + pinned + recent[: max(CONSISTENCY_REFS - len(lead), 0)])
        limits = RefLimits(self.s.image_limit, after=len(lead), max_refs=self._max_refs(), choices=self.s.ref_choices)
        return plan_refs(chat_refs, chars, limits)

    def _pick_characters(self, names: list[str], prompt: str) -> list[Character]:
        """Select attached characters named in the tool call or prompt.

        Unattached characters are never included.
        """
        named = characters.named(self.characters, names)  # "Chloe" can mean attached "Chloe Muscle"
        # "Chloe" in the prompt of a picture of "Chloe Muscle" is her, not an attached "Chloe"
        mentioned = characters.mentioned(self.characters, prompt, prefer=named)
        return list({c.id: c for c in named + mentioned}.values())

    def _attach(self, chars: list[Character]) -> None:
        """Attach characters to the chat (they stay for later turns) and tell the UI."""
        new = [c for c in chars if c.id not in {a.id for a in self.characters}]
        if not new:
            return
        self.characters += new
        conv = self.db.get_conversation(self.conv_id)
        own = conv.character_ids if conv else []
        own = [*own, *(c.id for c in new if c.id not in own)]  # the chat's own; its defaults' stay inherited
        self.db.update_conversation(self.conv_id, character_ids=own)
        self.emit(
            CharactersEvent(
                type="characters",
                character_ids=own,
                characters=[CharacterInfo.of(c) for c in self.characters],
            )
        )

    def build_ref_items(self, ref_mode: RefMode) -> list[dict[str, str]]:
        """Build the named reference list for a reference-to-video model.

        Supported attachments receive [@name] handles, subject to per-type and
        total limits. Order matches the composer so each handle stays stable.
        """
        user = self._last_user()
        types = set(ref_mode.get("types") or ("image", "video", "audio"))
        limits = ref_mode.get("limits") or {}
        total_max = ref_mode.get("max")
        counts: dict[str, int] = {}
        items: list[dict[str, str]] = []
        for m in user.media if user else []:
            kind = m.get("kind")
            file = m.get("file")
            if not isinstance(kind, str) or not isinstance(file, str) or kind not in types:
                continue
            counts[kind] = counts.get(kind, 0) + 1
            if limits.get(kind) and counts[kind] > limits[kind]:
                continue  # over this type's cap — leave it out (its [@name] won't resolve)
            items.append({"file": file, "name": f"{kind}{counts[kind]}", "type": kind})
            if total_max and len(items) >= total_max:
                break
        return items

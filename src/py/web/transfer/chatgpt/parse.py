"""Reading a ChatGPT export: the zip, its conversation trees, and the prompt-and-reply turns in them."""

import re
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, NotRequired, TypedDict

from web.jsonutil import as_object, as_objects, loads
from web.types import JsonValue

if TYPE_CHECKING:
    from pathlib import Path


# Search citations ChatGPT leaves in replies: citeturn0search1
_CITATION = re.compile("[^]*|[-]")
_FILE_ID = re.compile(r"^(file[-_][A-Za-z0-9]+)")
# Its document blocks: :::writing{variant="document" title="…"} … :::
_WRITING_START = re.compile(r"^:::writing(?:\{([^}\n]*)\})?[ \t]*\n?", re.MULTILINE)
_WRITING_END = re.compile(r"^:::[ \t]*(?:\n|$)", re.MULTILINE)
_TITLE_ATTR = re.compile(r'title="([^"]*)"')


class _GeneratedFile(TypedDict):
    id: str
    name: NotRequired[str | None]
    mime: NotRequired[str | None]


@dataclass
class Turn:
    """A prompt and the replies to it (no prompt: replies before the first one)."""

    prompt_id: str | None
    prompt: str = ""
    time: float = 0.0
    uploads: list[str] = field(default_factory=list)  # file ids
    reply: list[str] = field(default_factory=list)
    reply_time: float | None = None
    model: str | None = None
    generated: list[_GeneratedFile] = field(default_factory=list)


def _json_array(value: JsonValue) -> list[JsonValue]:
    return value if isinstance(value, list) else []


def timestamp(value: JsonValue) -> float | None:
    """A ChatGPT epoch-seconds value as a float (None if it isn't a number)."""
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    return None


class Export:
    """An opened export zip: its chats, its file library and the files themselves."""

    def __init__(self, zf: zipfile.ZipFile) -> None:
        self.zf = zf
        self.new_files: list[Path] = []  # images written by this import (their thumbnails are made after)
        self.files: dict[str, str] = {}  # file id → zip entry
        for name in zf.namelist():
            m = _FILE_ID.match(name.rsplit("/", 1)[-1])
            if m and not name.endswith("/"):
                self.files.setdefault(m.group(1), name)
        self.conversations = as_objects(loads(zf.read("conversations.json")))
        self.library: dict[str, list[Mapping[str, JsonValue]]] = {}  # chat id → its files
        if "library_files.json" in zf.namelist():
            for f in as_objects(loads(zf.read("library_files.json"))):
                thread_id = f.get("origination_thread_id")
                if isinstance(thread_id, str) and f.get("file_id"):
                    self.library.setdefault(thread_id, []).append(f)

    def read(self, file_id: str) -> bytes | None:
        """The bytes of an exported file (None if the zip doesn't have it)."""
        name = self.files.get(file_id)
        return self.zf.read(name) if name else None


def _chain(data: Mapping[str, JsonValue]) -> list[Mapping[str, JsonValue]]:
    """The messages on the exported branch, first first."""
    mapping = as_object(data.get("mapping"))
    current_node = data.get("current_node")
    node_id: str | None = current_node if isinstance(current_node, str) else None
    if node_id not in mapping:  # no shown branch recorded: the newest leaf
        leaves = [
            key
            for key, value in mapping.items()
            if not _json_array(as_object(value).get("children")) and as_object(value).get("message")
        ]
        node_id = max(
            leaves,
            key=lambda key: timestamp(as_object(as_object(mapping[key]).get("message")).get("create_time")) or 0,
            default=None,
        )
    out: list[Mapping[str, JsonValue]] = []
    seen: set[str] = set()
    while node_id is not None and node_id in mapping and node_id not in seen:
        seen.add(node_id)
        node = as_object(mapping[node_id])
        message = node.get("message")
        if message:
            out.append(as_object(message))
        parent = node.get("parent")
        node_id = parent if isinstance(parent, str) else None
    return out[::-1]


def _parts(msg: Mapping[str, JsonValue]) -> tuple[str, list[str]]:
    """A message's text and the files it shows."""
    texts: list[str] = []
    files: list[str] = []
    for raw_part in _json_array(as_object(msg.get("content")).get("parts")):
        if isinstance(raw_part, str):
            texts.append(raw_part)
            continue
        part = as_object(raw_part)
        if part.get("content_type") == "image_asset_pointer":
            pointer = part.get("asset_pointer")
            file_id = pointer.split("://")[-1] if isinstance(pointer, str) else ""
            if file_id:
                files.append(file_id)
    return _plain("\n".join(texts)), files


def _plain(text: str) -> str:
    """ChatGPT's markup out of a reply: citations, and document blocks with their title in bold."""

    def start(m: re.Match[str]) -> str:
        title = _TITLE_ATTR.search(m.group(1) or "")
        return f"**{title.group(1)}**\n\n" if title and title.group(1) else ""

    text = _WRITING_END.sub("", _WRITING_START.sub(start, _CITATION.sub("", text)))
    return text.strip()


def _shown(msg: Mapping[str, JsonValue]) -> bool:
    """A message the ChatGPT page shows, as opposed to tool calls, reasoning and hidden context."""
    meta = as_object(msg.get("metadata"))
    if meta.get("is_visually_hidden_from_conversation") or meta.get("is_user_system_message"):
        return False
    if msg.get("recipient") not in (None, "all"):
        return False
    return as_object(msg.get("content")).get("content_type") in ("text", "multimodal_text")


def _current(turns: list[Turn], time: float) -> Turn:
    """The turn a reply belongs to, starting one when it comes before any prompt."""
    if not turns:
        turns.append(Turn(None, time=time))
    return turns[-1]


def _add_to_turns(turns: list[Turn], msg: Mapping[str, JsonValue], time: float) -> None:
    """Fold one exported message into the turns: a prompt starts one, a reply joins the latest."""
    role = as_object(msg.get("author")).get("role")
    text, files = _parts(msg)
    if role == "tool" and files:
        # Older exports kept the image tool's results: those are generated images
        _current(turns, time).generated.extend({"id": file_id} for file_id in files)
    elif not _shown(msg):
        return
    elif role == "user" and (text or files):
        msg_id = msg.get("id")
        if isinstance(msg_id, str):
            turns.append(Turn(msg_id, text, time, files))
    elif role == "assistant":
        turn = _current(turns, time)
        turn.reply += [text] if text else []
        turn.reply_time = turn.reply_time or timestamp(msg.get("create_time"))
        model = as_object(msg.get("metadata")).get("model_slug")
        turn.model = model if isinstance(model, str) else turn.model


def build_turns(data: Mapping[str, JsonValue], library: list[Mapping[str, JsonValue]]) -> list[Turn]:
    """The turns of one chat: prompts with their replies, and the generated files placed on them."""
    turns: list[Turn] = []
    time = timestamp(data.get("create_time")) or 0.0
    for msg in _chain(data):
        time = timestamp(msg.get("create_time")) or time
        _add_to_turns(turns, msg, time)
    if turns:
        _place_generated(turns, library)
    return turns


def _place_generated(turns: list[Turn], library: list[Mapping[str, JsonValue]]) -> None:
    """Place generated images, which the export doesn't link to a message.

    Each goes on the reply to the latest prompt sent before it was made.
    """
    shown = {f for t in turns for f in t.uploads} | {g["id"] for t in turns for g in t.generated}
    for f in sorted(library, key=lambda file: str(file.get("created_at") or "")):
        file_id = f.get("file_id")
        if not isinstance(file_id, str) or file_id in shown:
            continue
        created_at = f.get("created_at")
        if not isinstance(created_at, str):
            continue
        try:
            made = datetime.fromisoformat(created_at).timestamp()
        except ValueError:
            continue
        turn = next((t for t in reversed(turns) if t.time <= made), turns[0])
        name, mime = f.get("file_name"), f.get("mime_type")
        turn.generated.append(
            {
                "id": file_id,
                "name": name if isinstance(name, str) else None,
                "mime": mime if isinstance(mime, str) else None,
            }
        )

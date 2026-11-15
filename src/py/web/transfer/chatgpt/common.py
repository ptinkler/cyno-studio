"""What the ChatGPT import modules share: its names, messages and the progress counters."""

from typing import NotRequired, TypedDict

from web.types import JsonValue


class ImportStats(TypedDict):
    """Counters of one import run, shown as its progress."""

    total: int
    processed: int
    new: int
    updated: int
    unchanged: int
    deleted: int
    empty: int
    images: int
    missing_images: int
    failed: list[dict[str, JsonValue]]
    space_id: NotRequired[int]


SOURCE = "chatgpt"
SPACE_NAME = "ChatGPT"  # the space new imports go in
DEFAULT_TITLE = "Imported chat"
NOT_AN_EXPORT = "Not a chat export: it has neither a ChatGPT conversations.json nor a pollo-chats.json"
MISSING = "Not included in the ChatGPT export"

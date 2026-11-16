"""Response models for the chat settings API: status, defaults, instructions and spaces.

The frontend's generated types come from these (see TODO.md, TypeScript migration). Timestamps are
ISO 8601 strings, as `core.metadata.models.iso` writes them.
"""

from typing import Literal

from pydantic import BaseModel

from web.types import JsonValue


class ChatStatus(BaseModel):
    """Which chat providers have a key."""

    configured: bool
    openrouter: bool
    venice: bool


class Defaults(BaseModel):
    """Character and instruction ids attached to every new chat (globally, or in a space)."""

    default_character_ids: list[int]
    default_instruction_ids: list[int]
    default_instruction_group_ids: list[int]


class ChatSettings(Defaults):
    """The user's global chat defaults."""

    title_model: str | None


class Space(Defaults):
    """A chat space and its own defaults."""

    id: int
    name: str
    created_at: str | None
    updated_at: str | None


class SpaceList(BaseModel):
    """All the user's spaces."""

    spaces: list[Space]


class Instruction(BaseModel):
    """A reusable instruction snippet."""

    id: int
    name: str
    content: str
    created_at: str | None
    updated_at: str | None


class InstructionGroup(BaseModel):
    """A named bundle of instruction snippets."""

    id: int
    name: str
    snippet_ids: list[int]
    created_at: str | None
    updated_at: str | None


class InstructionList(BaseModel):
    """Every instruction snippet and group."""

    instructions: list[Instruction]
    groups: list[InstructionGroup]


class Deleted(BaseModel):
    """The id of what a delete removed."""

    deleted: int


# --- Conversations and messages ---------------------------------------------------------------------

type JsonObject = dict[str, JsonValue]


class MediaVersion(BaseModel):
    """What a card keeps about a picture it has replaced (Edit / Redo)."""

    file: str | None = None
    prompt: str | None = None
    model: str | None = None
    cost: float | None = None
    credits: int | None = None
    params: JsonObject | None = None
    request: JsonObject | None = None
    response: JsonObject | None = None


class MediaCard(BaseModel):
    """An image, video or audio card on a message: uploaded, or generated (pending, done or failed).

    `params` is the model-specific generation settings, and `request` / `response` are the provider
    exchange for the "Request" view; all three are open JSON by nature.
    """

    id: str
    kind: Literal["image", "video", "audio"]
    source: str  # "upload" | "generated"
    status: Literal["pending", "done", "error"]
    file: str | None = (
        None  # under <data>/chat/<conversation_id>/; null (or absent in older items) until the render lands
    )
    prompt: str | None = None
    model: str | None = None
    params: JsonObject | None = None
    job_id: str | None = None
    error: str | None = None
    moderated: bool | None = None
    cost: float | None = None  # dollars
    credits: int | None = None  # Pollo bills in credits instead
    request: JsonObject | None = None
    response: JsonObject | None = None
    pinned: bool | None = None  # sent as a reference with every new image on the branch
    favourite: bool | None = None
    versions: list[MediaVersion] | None = None  # pictures this card replaced
    version_shown: int | None = None  # where the live one sits among them (missing = last)


class Message(BaseModel):
    """One message of a conversation: a prompt or a reply, with its media."""

    id: int
    conversation_id: str
    parent_id: int | None
    role: Literal["user", "assistant"]
    content: str
    media: list[MediaCard]
    model: str | None
    mode: str | None  # the composer mode the turn ran in; null on older messages
    lane: str | None  # null = the chat's branch; "gallery" = a standalone gallery exchange
    status: str  # "streaming" | "done" | "error"
    error: str | None
    cost: float | None
    text_versions: int  # how many earlier wordings the reply has
    text_shown: int  # which of them is shown
    created_at: str | None


class ShownMessage(Message):
    """A message on the shown branch, with the ids of its sibling versions (the < 1/2 > arrows)."""

    siblings: list[int]


class ForkRef(BaseModel):
    """A chat branched from a message."""

    id: str
    title: str


class ConversationMessage(ShownMessage):
    """A shown message and the chats that were branched from it."""

    forks: list[ForkRef]


class HiddenDefaults(BaseModel):
    """Defaults switched off in one chat only, by kind."""

    character: list[int]
    instruction: list[int]
    instruction_group: list[int]


class PausedInstructions(BaseModel):
    """Instructions still attached to a chat but temporarily not sent."""

    instruction: list[int]
    instruction_group: list[int]


class Conversation(BaseModel):
    """A chat and its settings."""

    id: str
    title: str
    text_model: str | None
    image_model: str | None
    video_model: str | None
    instruction_ids: list[int]
    instruction_group_ids: list[int]
    space_id: int | None
    current_leaf_id: int | None
    character_ids: list[int]
    forked_from_id: str | None
    forked_from_message_id: int | None
    pinned: bool
    kind: Literal["chat", "gallery"]
    settings: JsonObject | None  # the composer settings last used here
    hidden_defaults: HiddenDefaults
    paused_instructions: PausedInstructions
    import_source: str | None
    created_at: str | None
    updated_at: str | None


class Spend(BaseModel):
    """What a chat has cost, and how much of that came with the messages copied in by a branch."""

    usd: float
    credits: int
    inherited_usd: float
    inherited_credits: int


class ForkOrigin(BaseModel):
    """The chat this one was branched from (which may since have been deleted)."""

    id: str
    title: str | None
    message_id: int | None
    exists: bool


class OpenConversation(Conversation):
    """A conversation as the chat view opens it."""

    forked_from: ForkOrigin | None
    spend: Spend


class ConversationView(BaseModel):
    """A conversation with its shown messages."""

    conversation: OpenConversation
    messages: list[ConversationMessage]


class ConversationSummary(Conversation):
    """A row of the chat list; `snippet` is the matching text when the list was searched."""

    snippet: str | None = None


class ConversationList(BaseModel):
    """Pinned chats, then the most recent."""

    conversations: list[ConversationSummary]
    more: bool


class ConversationThumbs(BaseModel):
    """The newest image file of each chat that has one, by chat id."""

    thumbs: dict[str, str]


class DeletedConversation(BaseModel):
    """The chat a delete removed."""

    deleted: str


class DeleteInfo(BaseModel):
    """What deleting a prompt would also remove, for the confirmation."""

    other_versions: int
    other_messages: int
    media: dict[str, int]  # generated files that would go, by kind


class SpendGroup(BaseModel):
    """What one model (and kind) cost."""

    model: str
    kind: str
    usd: float
    credits: int
    count: int


class SpendBreakdown(BaseModel):
    """Where the user's money went over the last `days` days (0 = all time), in USD."""

    days: int
    total_usd: float
    rows: list[SpendGroup]


class ShownBranch(BaseModel):
    """A conversation's record and its shown messages, after a delete."""

    conversation: Conversation
    messages: list[ShownMessage]

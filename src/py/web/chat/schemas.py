"""Response models for the chat settings API: status, defaults, instructions and spaces.

The frontend's generated types come from these (see TODO.md, TypeScript migration). Timestamps are
ISO 8601 strings, as `core.metadata.models.iso` writes them.
"""

import logging
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, TypeAdapter, ValidationError
from pydantic.alias_generators import to_camel

from web.characters import CharacterInfo
from web.chat.models import ComposerSettings
from web.core.request_log import RequestLogEntry
from web.types import CreditEstimate, JsonValue

log = logging.getLogger(__name__)


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
    model_favourites: dict[str, list[str]]


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


def _composer_settings(raw: object) -> ComposerSettings | None:
    """A chat's stored composer settings, or None when they are absent or no longer fit the model.

    They are saved JSON that outlives versions (and may come from another server's export), so a
    stale shape must not stop the chat opening: it just forgets the remembered settings.
    """
    if raw is None or isinstance(raw, ComposerSettings):
        return raw
    try:
        return ComposerSettings.model_validate(raw)
    except ValidationError:
        log.warning("ignoring stored composer settings that no longer fit: %r", raw)
        return None


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
    settings: Annotated[ComposerSettings | None, BeforeValidator(_composer_settings)]  # last used in this chat
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


# --- Attachments, the library, active generations and the request log ----------------------------------


class AttachedFile(BaseModel):
    """The name an uploaded attachment was stored under in the chat."""

    file: str


class Discarded(BaseModel):
    """Whether an unsent attachment's file was removed (it stays if a message still uses it)."""

    deleted: bool


class LibraryCard(MediaCard):
    """A generated card in the chat library, with where it lives."""

    conversation_id: str
    conversation_title: str | None
    message_id: int | None  # null when an older edit or retry detached it from its message
    attached: bool  # still in its chat, on some branch
    created_at: str | None


class LibraryList(BaseModel):
    """Every generated image and video across chats, newest first."""

    items: list[LibraryCard]


class DeletedLibraryItem(BaseModel):
    """The id of the library item a delete removed."""

    deleted: str


class RequestLog(BaseModel):
    """The latest provider requests, newest first."""

    entries: list[RequestLogEntry]


class Generation(BaseModel):
    """A generation the queue dock tracks: where it is, what it is and how it is going."""

    media_id: str
    message_id: int
    conversation_id: str
    conversation_title: str
    kind: Literal["image", "video", "audio"]
    prompt: str | None
    model: str | None
    status: Literal["pending", "done", "error"]
    file: str | None
    error: str | None
    moderated: bool
    created_at: str | None


class ActiveGenerations(BaseModel):
    """The pending generations, and the final state of the ones the client was tracking."""

    items: list[Generation]


# --- Prompt tools, estimates and voices ---------------------------------------------------------


class Enhanced(BaseModel):
    """A prompt rewritten by the chat model, and what that cost."""

    prompt: str
    cost: float


class Estimate(BaseModel):
    """Pollo's credit estimate for a generation; null for other providers or when it can't be priced."""

    estimate: CreditEstimate | None


class Voice(BaseModel):
    """One of Pollo's official text-to-speech voices (field names are Pollo's, passed straight through)."""

    # Pollo's attributes may arrive as numbers; the camelCase names are on the wire, both ways
    model_config = ConfigDict(coerce_numbers_to_str=True, alias_generator=to_camel, populate_by_name=True)

    voice_id: str | None
    voice_name: str | None
    sample_audio: str | None
    language: str | None
    gender: str | None
    age: str | None
    voice_style: str | None
    accent: str | None
    engine_code: str | None


class VoiceList(BaseModel):
    """A page of voices and how many there are in all."""

    voices: list[Voice]
    total: int


class Cancelled(BaseModel):
    """Whether a running reply was found and told to stop."""

    cancelled: bool


# --- The server-sent events of a turn --------------------------------------------------------------
# A turn streams `data: {json}` lines. OpenAPI can't describe a stream, so these models are the contract:
# the routes list them as the event-stream schema, the engine emits them, and the frontend's types come
# from them. Every event names itself in `type`, so they form a discriminated union.


class StartEvent(BaseModel):
    """The turn began: the prompt that was saved (if any) and the reply being written."""

    type: Literal["start"]
    user_message: ShownMessage | None
    assistant_message: ShownMessage
    replaces: int | None = None  # a reword: the reply whose words are being written again


class DeltaEvent(BaseModel):
    """More of the reply's text."""

    type: Literal["delta"]
    text: str


class MediaEvent(BaseModel):
    """A card was added to the reply, or its state changed."""

    type: Literal["media"]
    message_id: int
    item: MediaCard


class CharactersEvent(BaseModel):
    """The chat model made characters: the chat's own character ids now, and those characters."""

    type: Literal["characters"]
    character_ids: list[int]
    characters: list[CharacterInfo]


class InstructionsEvent(BaseModel):
    """The chat model saved an instruction and attached it to the chat."""

    type: Literal["instructions"]
    instruction_ids: list[int]
    instruction: Instruction


class TitleEvent(BaseModel):
    """The chat got its title."""

    type: Literal["title"]
    title: str


class ErrorEvent(BaseModel):
    """The turn failed; a `done` follows."""

    type: Literal["error"]
    message: str


class DoneEvent(BaseModel):
    """The turn ended; `message` is the saved reply (null if it has gone)."""

    type: Literal["done"]
    message: ShownMessage | None


_Event = (
    StartEvent | DeltaEvent | MediaEvent | CharactersEvent | InstructionsEvent | TitleEvent | ErrorEvent | DoneEvent
)
TurnEvent = Annotated[_Event, Field(discriminator="type")]

_EVENT_ADAPTER: TypeAdapter[_Event] = TypeAdapter(TurnEvent)


def _event_schema() -> dict[str, object]:
    """The `TurnEvent` union as an OpenAPI schema of `$ref`s into the components."""
    schema: dict[str, object] = dict(_EVENT_ADAPTER.json_schema(ref_template="#/components/schemas/{model}"))
    # the models themselves are registered through `model` below, so don't repeat their `$defs`
    schema.pop("$defs", None)
    return schema


# The `responses=` of a streaming turn route: it lists the event models in the OpenAPI schema. `model` is
# what registers them; the `application/json` entry that comes with it is removed again by
# `web.core.openapi` once the schema is built, because the body is an event stream.
TURN_STREAM: dict[int | str, dict[str, object]] = {
    200: {
        "description": "Server-sent events: one `TurnEvent` as JSON per `data:` line.",
        "model": TurnEvent,
        "content": {"text/event-stream": {"schema": _event_schema()}},
    }
}

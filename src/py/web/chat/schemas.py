"""Response models for the chat settings API: status, defaults, instructions and spaces.

The frontend's generated types come from these (see TODO.md, TypeScript migration). Timestamps are
ISO 8601 strings, as `core.metadata.models.iso` writes them.
"""

from pydantic import BaseModel


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

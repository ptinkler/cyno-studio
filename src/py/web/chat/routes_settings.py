"""Chat status, defaults, custom instructions and spaces: the settings side of the chat API."""

from collections.abc import Callable

from fastapi import HTTPException

from web import characters
from web.auth import keyctx
from web.chat.catalogue import get_models
from web.chat.constants import (
    KINDS,
    PAUSE_KINDS,
)
from web.chat.deps import router
from web.chat.helpers import (
    require_text_provider,
)
from web.chat.model_schemas import ModelCatalogue, parse_catalogue
from web.chat.models import (
    DefaultsIn,
    InstructionGroupIn,
    InstructionIn,
    ModelFavouritesIn,
    PresetsIn,
    SpaceIn,
    TitleModelIn,
)
from web.chat.schemas import (
    ChatSettings,
    ChatStatus,
    Deleted,
    Instruction,
    InstructionGroup,
    InstructionList,
    Space,
    SpaceList,
)
from web.core.get_task import get_credit_balance
from web.core.metadata import get_db
from web.core.metadata.models import ChatSpace
from web.providers import openrouter, venice
from web.types import JsonValue, OpenRouterCredits, PolloBalance, VeniceBalances


@router.get("/status")
def api_chat_status() -> ChatStatus:
    """Report which chat providers are configured."""
    return ChatStatus(
        configured=openrouter.is_configured() or venice.is_configured(),
        openrouter=openrouter.is_configured(),
        venice=venice.is_configured(),
    )


@router.get("/credits")
def api_chat_credits() -> OpenRouterCredits:
    """OpenRouter balance for the chat header (Pollo's is /pollo-balance)."""
    require_text_provider()
    try:
        return openrouter.get_credits()
    except openrouter.OpenRouterError as e:
        raise HTTPException(502, f"Couldn't fetch the OpenRouter balance: {e}") from e


@router.get("/pollo-balance")
def api_pollo_balance() -> PolloBalance:
    """Pollo credit balance for the chat header."""
    api_key = keyctx.provider_key("pollo")
    if not api_key:
        raise HTTPException(503, "No Pollo API key set — add one in Settings → Keys")
    balance = get_credit_balance(api_key)
    if balance is None:
        raise HTTPException(502, "Couldn't fetch the Pollo balance")
    return balance


@router.get("/venice-balance")
def api_venice_balance() -> VeniceBalances:
    """Venice balance for the chat header: USD, and the plan's bundled credits."""
    if not venice.is_configured():
        raise HTTPException(503, "No Venice API key set — add one in Settings → Keys")
    return venice.get_balances()


@router.get("/models")
def api_chat_models(*, refresh: bool = False) -> ModelCatalogue:
    """Return the model catalogue for the configured providers."""
    # No provider gate: the catalogue lists each provider independently
    # (get_models swallows a provider's failure and an unconfigured provider
    # returns []), so media models show with only a Pollo key, and new
    # providers slot in without touching this endpoint. Chat generation still
    # requires a text provider — that gate lives on the turn routes.
    return parse_catalogue(get_models(refresh=refresh))


def require_hidden_defaults(value: dict[str, list[int]] | None) -> dict[str, list[int]]:
    """The kinds of defaults to hide, without repeats, or 400 for an unknown kind."""
    unknown = set(value or {}) - set(KINDS)
    if unknown:
        raise HTTPException(400, f"Unknown kind of default: {', '.join(sorted(unknown))}")
    return {k: list(dict.fromkeys(ids)) for k, ids in (value or {}).items()}


def require_paused(value: dict[str, list[int]] | None) -> dict[str, list[int]]:
    """The paused instructions per kind, without repeats, or 400 for a kind that can't be paused."""
    unknown = set(value or {}) - set(PAUSE_KINDS)
    if unknown:
        raise HTTPException(400, f"Can't pause kind: {', '.join(sorted(unknown))}")
    return {k: list(dict.fromkeys(ids)) for k, ids in (value or {}).items()}


def _require_ids(ids: list[int], get: Callable[[int], object | None], label: str) -> list[int]:
    """`ids` without repeats, or 400 naming the first that `get` can't find."""
    for i in ids:
        if not get(i):
            raise HTTPException(400, f"{label} {i} not found")
    return list(dict.fromkeys(ids))


def require_instructions(ids: list[int]) -> list[int]:
    """The instruction ids, without repeats, or 400 naming the first that doesn't exist."""
    return _require_ids(ids, get_db().get_instruction, "Instruction")


def require_instruction_groups(ids: list[int]) -> list[int]:
    """The instruction group ids, without repeats, or 400 naming the first that doesn't exist."""
    return _require_ids(ids, get_db().get_instruction_group, "Instruction group")


def require_space(space_id: int) -> ChatSpace:
    """The space, or 400 when it doesn't exist."""
    space = get_db().get_space(space_id)
    if not space:
        raise HTTPException(400, "Space not found")
    return space


def _require_characters(ids: list[int]) -> list[int]:
    characters.require(ids, get_db())
    return list(dict.fromkeys(ids))


def _defaults_fields(data: DefaultsIn) -> dict[str, list[int]]:
    """Validated default id-lists for a settings bucket (global or a space)."""
    return {
        "default_character_ids": _require_characters(data.default_character_ids),
        "default_instruction_ids": require_instructions(data.default_instruction_ids),
        "default_instruction_group_ids": require_instruction_groups(data.default_instruction_group_ids),
    }


@router.get("/settings")
def api_get_settings() -> ChatSettings:
    """Return the current user's global chat defaults."""
    return ChatSettings.model_validate(get_db().get_settings().to_dict())


@router.put("/settings")
def api_update_settings(data: DefaultsIn) -> ChatSettings:
    """Save validated global chat defaults."""
    return ChatSettings.model_validate(get_db().save_settings(**_defaults_fields(data)).to_dict())


@router.put("/settings/title-model")
def api_set_title_model(data: TitleModelIn) -> ChatSettings:
    """The text model that names new chats (empty = the chat's own model)."""
    saved = get_db().save_settings(title_model=(data.title_model or "").strip() or None)
    return ChatSettings.model_validate(saved.to_dict())


@router.put("/settings/model-favourites")
def api_set_model_favourites(data: ModelFavouritesIn) -> ChatSettings:
    """Save the user's starred models (per picker kind), so they follow them to any browser."""
    favourites = {kind: [i.strip() for i in ids if i.strip()] for kind, ids in data.model_favourites.items()}
    return ChatSettings.model_validate(get_db().save_settings(model_favourites=favourites).to_dict())


@router.put("/settings/presets")
def api_set_presets(data: PresetsIn) -> ChatSettings:
    """Save the user's composer presets, so they follow them to any browser."""
    return ChatSettings.model_validate(get_db().save_settings(presets=list[JsonValue](data.presets)).to_dict())


@router.get("/instructions")
def api_list_instructions() -> InstructionList:
    """List instruction snippets and groups."""
    return InstructionList(
        instructions=[Instruction.model_validate(i.to_dict()) for i in get_db().list_instructions()],
        groups=[InstructionGroup.model_validate(g.to_dict()) for g in get_db().list_instruction_groups()],
    )


@router.post("/instructions")
def api_create_instruction(data: InstructionIn) -> Instruction:
    """Create an instruction snippet."""
    item = get_db().save_instruction(name=data.name.strip(), content=data.content)
    if not item:
        raise HTTPException(500, "Could not create instruction")
    return Instruction.model_validate(item.to_dict())


@router.put("/instructions/{instruction_id}")
def api_update_instruction(instruction_id: int, data: InstructionIn) -> Instruction:
    """Update an instruction snippet by ID."""
    item = get_db().save_instruction(instruction_id, name=data.name.strip(), content=data.content)
    if not item:
        raise HTTPException(404, "Instruction not found")
    return Instruction.model_validate(item.to_dict())


@router.delete("/instructions/{instruction_id}")
def api_delete_instruction(instruction_id: int) -> Deleted:
    """Delete an instruction snippet by ID."""
    if not get_db().delete_instruction(instruction_id):
        raise HTTPException(404, "Instruction not found")
    return Deleted(deleted=instruction_id)


@router.post("/instruction-groups")
def api_create_instruction_group(data: InstructionGroupIn) -> InstructionGroup:
    """Create a group from validated instruction snippet IDs."""
    group = get_db().save_instruction_group(name=data.name.strip(), snippet_ids=require_instructions(data.snippet_ids))
    if not group:
        raise HTTPException(500, "Could not create instruction group")
    return InstructionGroup.model_validate(group.to_dict())


@router.put("/instruction-groups/{group_id}")
def api_update_instruction_group(group_id: int, data: InstructionGroupIn) -> InstructionGroup:
    """Update an instruction group by ID."""
    item = get_db().save_instruction_group(
        group_id, name=data.name.strip(), snippet_ids=require_instructions(data.snippet_ids)
    )
    if not item:
        raise HTTPException(404, "Instruction group not found")
    return InstructionGroup.model_validate(item.to_dict())


@router.delete("/instruction-groups/{group_id}")
def api_delete_instruction_group(group_id: int) -> Deleted:
    """Delete an instruction group by ID."""
    if not get_db().delete_instruction_group(group_id):
        raise HTTPException(404, "Instruction group not found")
    return Deleted(deleted=group_id)


@router.get("/spaces")
def api_list_spaces() -> SpaceList:
    """List the user's chat spaces."""
    return SpaceList(spaces=[Space.model_validate(s.to_dict()) for s in get_db().list_spaces()])


@router.post("/spaces")
def api_create_space(data: SpaceIn) -> Space:
    """Create a chat space with validated defaults."""
    space = get_db().save_space(None, name=data.name.strip(), **_defaults_fields(data))
    if not space:
        raise HTTPException(500, "Could not create space")
    return Space.model_validate(space.to_dict())


@router.put("/spaces/{space_id}")
def api_update_space(space_id: int, data: SpaceIn) -> Space:
    """Update a chat space and its defaults."""
    item = get_db().save_space(space_id, name=data.name.strip(), **_defaults_fields(data))
    if not item:
        raise HTTPException(404, "Space not found")
    return Space.model_validate(item.to_dict())


@router.delete("/spaces/{space_id}")
def api_delete_space(space_id: int) -> Deleted:
    """Delete a chat space by ID."""
    if not get_db().delete_space(space_id):
        raise HTTPException(404, "Space not found")
    return Deleted(deleted=space_id)

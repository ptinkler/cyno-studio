"""The shapes of a Pollo video model's config row, its resolved inputs, and a body builder."""

from __future__ import annotations

from typing import TYPE_CHECKING, NotRequired, Protocol, TypedDict

if TYPE_CHECKING:
    from web.providers.pollo_engine._shared import Payload
    from web.types import JsonValue


class VideoRow(TypedDict, total=False):
    """One video model's table row: overrides of the defaults, plus its endpoint."""

    PROVIDER: str
    MODEL: str
    V1_URL: str
    endpoint: str
    builder: str
    VALID_LENGTHS: tuple[int, ...]
    VALID_RESOLUTIONS: tuple[str, ...]
    VALID_RATIOS: tuple[str, ...]
    DEFAULT_RESOLUTION: str
    DEFAULT_LENGTH: int
    DEFAULT_RATIO: str
    FORCE_RESOLUTION: str
    DEFAULT_MODE: str
    MODE_DEFAULT: str
    MODES: tuple[str, ...]
    MODE_PRO_RESOLUTIONS: tuple[str, ...]
    HAS_GENERATE_AUDIO: bool
    HAS_WEB_SEARCH: bool
    HAS_SEED: bool
    HAS_IMAGE_TAIL: bool
    HAS_REFS: bool
    HAS_MODE: bool
    HAS_NEGATIVE_PROMPT_AUDIO: bool
    HAS_ASPECT_RATIO_ON_IMAGE: bool
    REF_TYPES: tuple[str, ...]
    MAX_REFS: int
    REF_HAS_SEED: bool
    REF_VALID_LENGTHS: tuple[int, ...]
    REF_VALID_RESOLUTIONS: tuple[str, ...]
    NEEDS_PROMPT: bool
    RESOLUTION_IS_MODE: bool
    MODE_ON_TEXT: bool
    TEXT_TO_VIDEO: bool
    IMAGE_TAIL_NEEDS_PRO: bool
    NO_AUDIO_WITH_IMAGE_TAIL: bool


class VideoCfg(TypedDict):
    """A video model's settings once the defaults are layered under its row."""

    VALID_LENGTHS: tuple[int, ...]
    VALID_RESOLUTIONS: tuple[str, ...]
    VALID_RATIOS: tuple[str, ...]
    DEFAULT_RESOLUTION: str
    DEFAULT_LENGTH: int
    HAS_GENERATE_AUDIO: bool
    HAS_WEB_SEARCH: bool
    HAS_SEED: bool
    HAS_IMAGE_TAIL: bool
    HAS_REFS: bool
    HAS_MODE: bool
    HAS_NEGATIVE_PROMPT_AUDIO: bool
    HAS_ASPECT_RATIO_ON_IMAGE: bool
    REF_TYPES: tuple[str, ...]
    MAX_REFS: int
    REF_HAS_SEED: bool
    REF_VALID_LENGTHS: tuple[int, ...]
    REF_VALID_RESOLUTIONS: tuple[str, ...]
    builder: str
    endpoint: str
    RESOLUTION_IS_MODE: bool
    MODE_ON_TEXT: bool
    TEXT_TO_VIDEO: bool
    IMAGE_TAIL_NEEDS_PRO: bool
    NO_AUDIO_WITH_IMAGE_TAIL: bool
    PROVIDER: NotRequired[str]
    MODEL: NotRequired[str]
    V1_URL: NotRequired[str]
    FORCE_RESOLUTION: NotRequired[str]
    DEFAULT_RATIO: NotRequired[str]
    DEFAULT_MODE: NotRequired[str]
    MODE_DEFAULT: NotRequired[str]
    MODES: NotRequired[tuple[str, ...]]
    MODE_PRO_RESOLUTIONS: NotRequired[tuple[str, ...]]
    NEEDS_PROMPT: NotRequired[bool]


class Inputs(TypedDict):
    """A request's inputs resolved against a model's configuration."""

    refs: list[dict[str, JsonValue]] | None
    is_text_only: bool
    resolution: str
    length: int
    aspect_ratio: str
    image_tail: JsonValue
    seed: JsonValue
    generate_audio: JsonValue
    web_search: JsonValue
    mode: str | None
    negative_prompt: JsonValue
    audio_url: JsonValue


class Builder(Protocol):
    """A family's body builder."""

    def __call__(self, c: VideoCfg, prompt: str, image_url: str | None, s: Inputs, /, **kw: JsonValue) -> Payload:
        """Build the request body for one video job."""
        raise NotImplementedError

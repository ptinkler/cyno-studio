"""Typed shapes for the Venice provider: its raw model records and the catalogue built from them.

Venice's JSON is untyped, so each record is narrowed once, here, into a small
dataclass. The rest of the provider then works with real fields instead of
digging through nested dicts.
"""

from dataclasses import dataclass, field
from typing import NamedTuple, NotRequired, TypedDict

from web.jsonutil import as_int, as_list, as_object, as_str
from web.types import JsonValue, ModelEntry


class ImageSettings(TypedDict):
    """The image settings a request actually sent."""

    aspect_ratio: str | None
    resolution: str | None
    refs_used: NotRequired[int]


def strs(value: JsonValue) -> list[str] | None:
    """The strings in a JSON list (None when the value is missing)."""
    if value is None:
        return None
    return [item for item in as_list(value) if isinstance(item, str)]


@dataclass(frozen=True, slots=True)
class Model:
    """One record from Venice's ``/models``, reduced to what the catalogue needs."""

    id: str
    name: str
    created: JsonValue
    context_length: JsonValue
    uncensored: bool
    privacy: str | None
    capabilities: dict[str, JsonValue]
    pricing: dict[str, JsonValue]
    constraints: dict[str, JsonValue]


def parse_model(raw: dict[str, JsonValue]) -> Model | None:
    """Narrow one ``/models`` record; None when it has no id or is offline."""
    model_id = as_str(raw.get("id"))
    spec = as_object(raw.get("model_spec"))
    if model_id is None or spec.get("offline"):
        return None
    return Model(
        id=model_id,
        name=as_str(spec.get("name")) or model_id,
        created=raw.get("created"),
        context_length=spec.get("availableContextTokens") or raw.get("context_length"),
        uncensored=bool(spec.get("uncensored")),
        privacy=as_str(spec.get("privacy")),
        capabilities=as_object(spec.get("capabilities")),
        pricing=as_object(spec.get("pricing")),
        constraints=as_object(spec.get("constraints")),
    )


@dataclass(frozen=True, slots=True)
class VideoConstraints:
    """What one video model accepts."""

    durations: list[str]
    resolutions: list[str]
    aspect_ratios: list[str]
    audio_configurable: bool
    audio: bool


def video_constraints(raw: dict[str, JsonValue]) -> VideoConstraints:
    """Narrow a video model's ``constraints`` object."""
    return VideoConstraints(
        durations=[str(d) for d in as_list(raw.get("durations")) if isinstance(d, (str, int, float))],
        resolutions=strs(raw.get("resolutions")) or [],
        aspect_ratios=strs(raw.get("aspect_ratios")) or [],
        audio_configurable=bool(raw.get("audio_configurable")),
        audio=bool(raw.get("audio")),
    )


def max_input_images(constraints: dict[str, JsonValue]) -> int:
    """How many reference images an edit model takes (one when Venice doesn't say)."""
    return as_int(constraints.get("maxInputImages")) or 1


class PriceSpec(NamedTuple):
    """Where an image model's price lives: its pricing key, its pricing object, its default resolution."""

    key: str
    pricing: dict[str, JsonValue]
    default_resolution: str | None


class ImageTarget(NamedTuple):
    """One Venice image model to call (generate or edit) and how it is priced."""

    model: str
    price: PriceSpec


class VideoTarget(NamedTuple):
    """One Venice video model to call and what it accepts."""

    model: str
    constraints: VideoConstraints


@dataclass(slots=True)
class Entry:
    """A catalogue entry: the public shape the picker sees, plus its id."""

    id: str
    public: ModelEntry


@dataclass(slots=True)
class TextEntry(Entry):
    """A text model; prices are USD per token."""

    prompt_price: float | None
    completion_price: float | None


@dataclass(slots=True)
class ImageEntry(Entry):
    """An image model: its text-to-image side, its edit twin (either may be missing), and its reference limit."""

    generate: ImageTarget | None
    edit: ImageTarget | None
    max_refs: int
    aspect_ratios: list[str]
    resolutions: list[str]


@dataclass(slots=True)
class VideoEntry(Entry):
    """A video model family member: its text-to-video and image-to-video models (either may be missing)."""

    family: str
    video_input: bool
    text: VideoTarget | None
    image: VideoTarget | None


@dataclass(slots=True)
class Catalogue:
    """Every Venice model by kind, cheapest first."""

    text: list[TextEntry] = field(default_factory=list[TextEntry])
    image: list[ImageEntry] = field(default_factory=list[ImageEntry])
    video: list[VideoEntry] = field(default_factory=list[VideoEntry])

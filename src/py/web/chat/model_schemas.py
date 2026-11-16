"""The model catalogue as the API serves it: one shape per kind of model.

Providers build their rows as loose dicts from third-party data (OpenRouter's and Venice's listings, Pollo's
tables), so the rows are parsed here, once, at the edge: a row that does not fit is dropped with a warning
instead of failing the whole catalogue. What passes is typed, and the frontend's types come from these.

A field with a default is one some providers leave out; a field without one is on every row of that kind.
"""

import logging
from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ValidationError

from web.providers.pollo.models import RefMode
from web.types import Catalogue, ModelEntry

log = logging.getLogger(__name__)


class ModelPrice(BaseModel):
    """A price badge: dollars, and what they buy ("1080p", "per 1M output tokens")."""

    usd: float
    basis: str


class ModelBase(BaseModel):
    """What every model has."""

    id: str  # prefixed with its provider ("pollo/", "venice/"); OpenRouter's are bare
    name: str
    tags: list[str]  # capability tags the picker filters on (see providers/model_tags.py)
    created: float | None = None
    hidden: str | None = None  # why it is left out of the pickers unless "Show hidden" is on
    uncensored: bool | None = None  # the provider says it has no content filtering
    privacy: Literal["private", "anonymized"] | None = None  # Venice's levels
    price: ModelPrice | None = None  # Venice's per-image / per-video quote


class TextModel(ModelBase):
    """A chat model."""

    input_modalities: list[str]
    supports_tools: bool
    context_length: int | None = None
    prompt_price: float | None = None  # dollars per token
    completion_price: float | None = None


class ImageModel(ModelBase):
    """An image model: a dedicated image API, or a chat model that can also make pictures."""

    input_modalities: list[str]
    conversational: bool  # sees the whole conversation, like the Gemini app
    aspect_ratios: list[str] | None = None
    resolutions: list[str] | None = None
    max_refs: int | None = None  # reference images it takes (null = unknown)
    tool: str | None = None  # a source image in, a result out
    no_prompt: bool | None = None  # the source file is the whole input


class VideoModel(ModelBase):
    """A video model."""

    frame_images: list[str]  # which frames it takes: "first_frame", "last_frame"
    durations: list[int] | None = None
    resolutions: list[str] | None = None
    aspect_ratios: list[str] | None = None
    generate_audio: bool | None = None
    no_prompt: bool | None = None
    audio_input: bool | None = None  # takes an audio track (lip sync)
    video_input: bool | None = None  # works on a source video
    reference_images: bool | None = None
    type: str | None = None  # Pollo's family
    family: str | None = None  # Venice's family
    family_hint: str | None = None
    modes: list[str] | None = None
    ref_mode: RefMode | None = None  # the reference-to-video branch: allowed types and limits


class AudioModel(ModelBase):
    """A speech or music model."""

    options: list[str]  # which inputs the UI offers
    audio_input: bool | None = None  # takes a reference clip (voice cloning)
    type: str | None = None


class ModelCatalogue(BaseModel):
    """Every provider's models by kind, and the providers that failed to list."""

    errors: dict[str, str]
    text: list[TextModel]
    image: list[ImageModel]
    video: list[VideoModel]
    audio: list[AudioModel]


def _parsed[M: ModelBase](model: type[M], row: ModelEntry) -> M | None:
    """The row as `model`, or None (with a warning) when it does not fit."""
    try:
        return model.model_validate(row)
    except ValidationError as e:
        log.warning("dropping a %s catalogue row %r: %s", model.__name__, row.get("id"), e.errors(include_url=False))
        return None


def _all_parsed[M: ModelBase](model: type[M], rows: Sequence[ModelEntry]) -> list[M]:
    return [parsed for row in rows if (parsed := _parsed(model, row)) is not None]


def parse_catalogue(data: Catalogue) -> ModelCatalogue:
    """The catalogue with each row parsed into its kind's model."""
    return ModelCatalogue(
        errors=data.get("errors", {}),
        text=_all_parsed(TextModel, data.get("text", [])),
        image=_all_parsed(ImageModel, data.get("image", [])),
        video=_all_parsed(VideoModel, data.get("video", [])),
        audio=_all_parsed(AudioModel, data.get("audio", [])),
    )

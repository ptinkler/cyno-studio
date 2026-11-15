"""What callers ask the providers for: one request object per kind of call, shared by every provider.

Each provider takes the same object and uses the fields it understands, ignoring the rest — an input a provider
has no use for (a last frame, a conversation) simply isn't sent.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from web.types import JsonValue


@dataclass(frozen=True)
class StreamOptions:
    """The optional parts of a streamed chat call.

    `max_seconds` caps the whole call and `should_stop` is polled while it streams, so a cancel is noticed
    even when no tokens are flowing.
    """

    tools: list[dict[str, JsonValue]] | None = None
    session_id: str | None = None
    max_seconds: float | None = None
    should_stop: Callable[[], bool] | None = None


@dataclass(frozen=True)
class ImageRequest:
    """An image to generate.

    `ref_paths` are reference images. `context` is the conversation, for OpenRouter's conversational image
    models; `session_id` also only means something to OpenRouter.
    """

    model: str
    prompt: str
    aspect_ratio: str | None = None
    resolution: str | None = None
    ref_paths: list[Path] = field(default_factory=list)
    context: list[dict[str, JsonValue]] | None = None
    session_id: str | None = None


@dataclass(frozen=True)
class VideoRequest:
    """A video to generate.

    Every provider takes the first six fields. The rest describe sources only some models accept: frames, a
    source video or audio track, an enhancement `mode`, references (`refs` as files, `ref_items` as named
    items for Pollo's reference-to-video).
    """

    model: str
    prompt: str
    duration: int | None = None
    aspect_ratio: str | None = None
    resolution: str | None = None
    generate_audio: bool | None = None
    first_frame: Path | None = None
    last_frame: Path | None = None
    source_video: Path | None = None
    source_audio: Path | None = None
    mode: str | None = None
    refs: list[Path] = field(default_factory=list)
    ref_items: list[dict[str, object]] = field(default_factory=list)
    session_id: str | None = None


@dataclass(frozen=True)
class CostQuery:
    """What a cost estimate is asked of: the kind of generation (image, video or audio) and its settings.

    `n_images` is how many reference images go with it; `audio` is a speech or music model's own options.
    """

    kind: str
    duration: int | None = None
    aspect_ratio: str | None = None
    resolution: str | None = None
    generate_audio: bool | None = None
    n_images: int = 0
    prompt: str = ""
    audio: Mapping[str, JsonValue] | None = None

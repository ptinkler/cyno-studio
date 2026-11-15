"""Model providers.

Every provider lives here as its own module — OpenRouter and Venice (text /
image / video via their chat APIs) and Pollo (image / video generation). The
goal is a single, uniform surface so callers dispatch over providers instead of
special-casing one by name. `provider_for()` is the first step of that: it maps
a model id to the module that owns it (OpenRouter is the fallback).
"""

from collections.abc import Iterator
from typing import Protocol, cast

from web.providers import openrouter, pollo, pollo_models, venice
from web.providers.specs import ImageRequest, StreamOptions, VideoRequest
from web.types import ChatChunk, JsonValue, ModelEntry, VideoJob


# Dispatch order for the model catalogue (Pollo first, OpenRouter last). Each
# exposes the uniform surface: NAME, is_configured(), list_models(kind, refresh).
class Provider(Protocol):
    """The uniform surface every provider module offers."""

    NAME: str

    def is_configured(self) -> bool: ...

    def list_models(self, kind: str, *, refresh: bool = False) -> list[ModelEntry]: ...


PROVIDERS: tuple[Provider, ...] = (pollo, venice, openrouter)


class _TextProvider(Protocol):
    def stream_chat(
        self, model: str, messages: list[dict[str, JsonValue]], options: StreamOptions | None = None
    ) -> Iterator[ChatChunk]: ...


class _VideoProvider(Protocol):
    def submit_video(self, req: VideoRequest) -> VideoJob: ...


def stream_chat(
    model: str, messages: list[dict[str, JsonValue]], options: StreamOptions | None = None
) -> Iterator[ChatChunk]:
    """Stream chat chunks from the provider that owns `model`."""
    return cast("_TextProvider", provider_for(model)).stream_chat(model, messages, options)


def provider_for(model_id: str | None) -> Provider:
    """The provider module that owns `model_id` (OpenRouter is the default)."""
    if pollo.is_pollo(model_id):
        return pollo
    if venice.is_venice(model_id):
        return venice
    return openrouter


def provider_for_job(job_id: str | None) -> Provider:
    """The provider module that owns an async job id.

    Pollo and Venice ids are prefixed with ``pollo:`` and ``venice:``; all
    other ids belong to OpenRouter. Background pollers use this to route jobs.
    """
    if pollo.is_pollo_job(job_id):
        return pollo
    if venice.is_venice_job(job_id):
        return venice
    return openrouter


def generate_image(
    req: ImageRequest,
) -> tuple[list[tuple[bytes, str]], float | None, int | None, dict[str, JsonValue]]:
    """Generate images on whichever provider owns `req.model`, and wait for them.

    Returns ([(bytes, media type)], cost in USD, Pollo credits, the settings
    actually sent). Providers bill differently — Pollo in credits, the rest in
    dollars — so both come back and only the relevant one is set.

    An input a provider has no use for is ignored: `context` (the conversation,
    for OpenRouter's conversational image models) and `session_id` only mean
    something to OpenRouter.
    """
    owner = provider_for(req.model)
    if owner is pollo:
        images, credit_cost, sent = pollo.generate_image(
            req.model, req.prompt, aspect_ratio=req.aspect_ratio, resolution=req.resolution, ref_paths=req.ref_paths
        )
        return images, None, credit_cost, sent
    if owner is venice:
        images, cost, sent = venice.generate_image(
            req.model, req.prompt, aspect_ratio=req.aspect_ratio, resolution=req.resolution, ref_paths=req.ref_paths
        )
        return images, cost, None, cast("dict[str, JsonValue]", sent)
    if req.context is not None:
        images, cost = openrouter.generate_image_chat(
            req.model, req.context, aspect_ratio=req.aspect_ratio, session_id=req.session_id
        )
        return images, cost, None, {}
    images, cost = openrouter.generate_image(req)
    return images, cost, None, {}


def submit_video(req: VideoRequest) -> VideoJob:
    """Start a video job on whichever provider owns `req.model`.

    Returns the job (``{"id", "params"}``), which the chat poller follows by id.

    Every provider takes the first six fields of the request; the rest describe sources only
    some models accept (a last frame, a source video or audio track, an
    enhancement mode, named references) and a provider ignores what it can't
    use.
    """
    return cast("_VideoProvider", provider_for(req.model)).submit_video(req)


# Re-exported: importing the package registers these submodules' routes/providers.
__all__ = ["ImageRequest", "StreamOptions", "VideoRequest", "openrouter", "pollo", "pollo_models", "venice"]

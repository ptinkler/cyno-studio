"""The chat model catalogue, cached per user.

It holds every provider's models, and the per-model lookups used to validate and auto-fit media params.
"""

import logging
import threading
import time
from typing import TypedDict, cast

from web.chat.constants import MODELS_CACHE_TTL
from web.core.key_caches import on_keys_changed
from web.core.metadata import current_tenant
from web.providers import PROVIDERS, venice
from web.providers.model_tags import tags_for
from web.providers.openrouter import OpenRouterError
from web.types import Catalogue, ModelEntry


class _CacheEntry(TypedDict):
    at: float
    data: Catalogue


log = logging.getLogger(__name__)

# Each provider lists the models the REQUESTING user's key can see (an
# unconfigured provider returns [], and "enabled for this key" differs per
# account), so a catalogue belongs to one user: the cache holds an entry per
# tenant, never one for the process. "" is the unauthenticated bucket.
_models_cache: dict[str, _CacheEntry] = {}
_models_lock = threading.Lock()
_MAX_CACHED_TENANTS = 32
_NEVER = 9e18  # an "at" that can't expire (seed_models)


class RefMode(TypedDict, total=False):
    """Describe the media types and limits accepted as video references."""

    types: list[str]
    limits: dict[str, int]
    max: int


class ModelInfo(TypedDict, total=False):
    """Represent the capabilities relevant to chat generation."""

    aspect_ratios: list[str] | None
    audio_input: bool
    conversational: bool
    durations: list[int] | None
    family: str
    frame_images: list[str]
    input_modalities: list[str]
    max_refs: int
    name: str
    no_prompt: bool
    reference_images: bool
    ref_mode: RefMode | None
    resolutions: list[str] | None
    supports_tools: bool
    tool: str | None


def _prune(now: float) -> None:
    """Caller holds the lock.

    Drop lapsed entries, then the oldest, so one
    process can't accumulate an entry per user who ever signed in.
    """
    for key in [k for k, e in _models_cache.items() if now - e["at"] > MODELS_CACHE_TTL]:
        del _models_cache[key]
    while len(_models_cache) > _MAX_CACHED_TENANTS:
        del _models_cache[min(_models_cache, key=lambda k: _models_cache[k]["at"])]


def cached_models() -> Catalogue | None:
    """The current tenant's cached catalogue, or None when nothing is cached."""
    entry = _models_cache.get(current_tenant() or "")
    return entry["data"] if entry else None


def seed_models(data: Catalogue, *, stale: bool = False) -> None:
    """Put a ready-made catalogue in the current tenant's cache (tests).

    `stale` lets get_models() refetch while the per-model lookups still see it.
    """
    with _models_lock:
        _models_cache[current_tenant() or ""] = {"at": 0.0 if stale else _NEVER, "data": data}


@on_keys_changed
def clear_models() -> None:
    """Forget every cached catalogue.

    Called when a user's provider keys change, since their keys decide what the catalogue contains.
    """
    with _models_lock:
        _models_cache.clear()


def get_models(*, refresh: bool = False) -> Catalogue:
    """Return each provider's model catalogue, refreshing the tenant cache if requested."""
    tenant = current_tenant() or ""
    with _models_lock:
        entry = _models_cache.get(tenant)
        if not refresh and entry and time.time() - entry["at"] < MODELS_CACHE_TTL:
            return entry["data"]
        errors: dict[str, str] = {}
        by_kind: dict[str, list[ModelEntry]] = {}
        # Uniform dispatch: each provider lists its own models per kind (in
        # PROVIDERS order), so no provider is special-cased here.
        for kind in ("text", "image", "video", "audio"):
            models: list[ModelEntry] = []
            for prov in PROVIDERS:
                try:
                    models += prov.list_models(kind, refresh=refresh)
                except Exception as e:  # each provider fails on its own; the rest still list
                    log.warning("listing %s %s models failed", prov.NAME, kind, exc_info=True)
                    errors[f"{prov.NAME}_{kind}"] = str(e)
            # Capability tags, derived uniformly so every provider is consistent;
            # the picker filters on these. Set once here rather than in each
            # provider's list_models (see web/providers/model_tags.py).
            for m in models:
                m["tags"] = tags_for(kind, m)
            by_kind[kind] = models
        data = Catalogue(
            errors=errors,
            text=by_kind["text"],
            image=by_kind["image"],
            video=by_kind["video"],
            audio=by_kind["audio"],
        )
        # Only cache a complete result, so a transient failure isn't sticky
        if not errors:
            now = time.time()
            _models_cache[tenant] = {"at": now, "data": data}
            _prune(now)
        return data


def model_info(kind: str, model_id: str | None) -> ModelInfo | None:
    """Look up cached catalogue info without fetching every provider's list.

    That cache is empty after a restart or when any list failed to load;
    Venice models then come from Venice's own catalogue, so a model without
    vision isn't sent images (Venice rejects those requests).
    """
    if not model_id:
        return None
    data = cached_models()
    models = cast("list[ModelEntry]", cast("dict[str, object]", data).get(kind, [])) if data else []
    info = next((m for m in models if m["id"] == model_id), None)
    if info is None and venice.is_venice(model_id) and venice.is_configured():
        try:
            return cast("ModelInfo", venice.model_info(kind, model_id))
        except OpenRouterError:  # unknown model or unreachable Venice is unknown
            return None
    return cast("ModelInfo", info) if info is not None else None


# Values a model exposes that mean "you decide" — mapped to from an unset ratio
# so the "Ratio: auto" placeholder really is automatic, not the provider's
# missing-field default (Seedream, for one, treats a missing ratio as 16:9).
_AUTO_RATIOS = ("auto", "adaptive")


def auto_ratio(kind: str, model_id: str | None) -> str | None:
    """The model's own 'auto' aspect-ratio value, if it offers one."""
    ratios = (model_info(kind, model_id) or {}).get("aspect_ratios") or []
    return next((v for v in _AUTO_RATIOS if v in ratios), None)


def fit_video_params(
    model_id: str, duration: int | None, aspect_ratio: str | None, resolution: str | None
) -> tuple[int | None, str | None, str | None]:
    """Snap requested params onto what the video model supports, when known.

    So a model-chosen "7 seconds" doesn't fail on a model that only takes 5 or 10.
    """
    info = model_info("video", model_id)
    if not info:
        return duration, aspect_ratio, resolution
    durations = info.get("durations") or []
    if duration and durations:
        requested_duration = duration
        if requested_duration not in durations:
            duration = min(durations, key=lambda d: abs(d - requested_duration))
    aspect_ratios = info.get("aspect_ratios") or []
    if aspect_ratio and aspect_ratios and aspect_ratio not in aspect_ratios:
        aspect_ratio = None
    resolutions = info.get("resolutions") or []
    if resolution and resolutions and resolution not in resolutions:
        resolution = None
    return duration, aspect_ratio, resolution

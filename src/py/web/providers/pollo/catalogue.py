"""Which Pollo models exist: the chat catalogues, voices, and model-key lookup."""

from collections.abc import Mapping

import requests

from web.auth import keyctx
from web.core.config import POLLO_API_TIMEOUT, POLLO_PLATFORM_BASE
from web.jsonutil import as_object, as_objects, body_of
from web.providers.pollo.engine import AUDIO_GENERATORS, IMAGE_GENERATORS, VIDEO_GENERATORS
from web.providers.pollo.engine.registry import ModelSpec
from web.providers.pollo.errors import ApiKeyMissingError, UnknownModelError, VoiceListError
from web.providers.pollo.models import MODEL_INFO, ModelInfo
from web.types import JsonValue, ModelEntry

PREFIX = "pollo/"
JOB_PREFIX = "pollo:"


def is_configured() -> bool:
    """Return whether a Pollo API key is configured."""
    return bool(keyctx.provider_key("pollo"))


def list_models(kind: str, *, refresh: bool = False) -> list[ModelEntry]:
    """List Pollo models for the uniform provider interface.

    Pollo has no text models; image, video and audio lists
    are already key-gated (empty without a Pollo key). Nothing is cached, so `refresh` has no effect.
    """
    _ = refresh
    if kind == "image":
        return list_image_models()
    if kind == "video":
        return list_video_models()
    if kind == "audio":
        return list_audio_models()
    return []


def is_pollo(model_id: str | None) -> bool:
    """Return whether ``model_id`` belongs to Pollo."""
    return bool(model_id and model_id.startswith(PREFIX))


def is_pollo_job(job_id: str | None) -> bool:
    """Return whether ``job_id`` belongs to Pollo."""
    return bool(job_id and job_id.startswith(JOB_PREFIX))


def _catalogue(generators: Mapping[str, ModelSpec]) -> list[tuple[str, ModelSpec, ModelInfo]]:
    """(key, spec, MODEL_INFO entry) for each model not marked deprecated."""
    if not is_configured():
        return []
    info = MODEL_INFO
    return [(key, spec, info[key]) for key, spec in generators.items() if not info.get(key, {}).get("deprecated")]


def list_image_models() -> list[ModelEntry]:
    """Pollo's image models, shaped like openrouter.list_image_models()."""
    return [
        {
            "id": PREFIX + key,
            "name": f"Pollo: {meta.get('label') or key}",
            "input_modalities": ["text", "image"] if spec.ACCEPTS_IMAGES else ["text"],
            "max_refs": spec.MAX_IMAGES or None,  # reference images it takes (None = unknown)
            "aspect_ratios": list(spec.VALID_RATIOS) or None,
            "resolutions": list(spec.VALID_RESOLUTIONS) or None,
            "tool": meta.get("tool") or None,  # a source image in, a result out (no prompt)
            "no_prompt": bool(meta.get("tool")),
            "created": None,
            "conversational": False,
            # Not enabled for this key — listed only behind "Show hidden"
            "hidden": meta.get("hidden") or None,
        }
        for key, spec, meta in _catalogue(IMAGE_GENERATORS)
    ]


def list_video_models() -> list[ModelEntry]:
    """Pollo's video models, shaped like openrouter.list_video_models()."""
    out: list[ModelEntry] = []
    for key, spec, meta in _catalogue(VIDEO_GENERATORS):
        # Motion models work on a source video + one reference image, so it has no
        # duration/resolution/aspect ratio (the source video sets those). Extend
        # continues a source video too, but the user picks the added duration
        # and resolution — it takes no image and no aspect ratio.
        typ = meta.get("type")
        recast = typ in IMAGE_AND_VIDEO  # a reference image + a source video
        no_image = typ in VIDEO_ONLY  # source-video families that take no first frame
        lipsync = typ == "lipsync"  # drive a portrait with an audio track
        # only the plain generators carry their own duration / aspect ratio;
        # the source-video / audio families derive the length from their input.
        # Extend alone lets the user pick the added duration.
        derived = recast or lipsync or no_image
        own_duration = not derived or typ == "extend"
        own_ratio = not derived
        out.append(
            {
                "id": PREFIX + key,
                "name": f"Pollo: {meta.get('label') or key}",
                "type": typ,
                "durations": (list(spec.VALID_LENGTHS) or None) if own_duration else None,
                "no_prompt": typ in NO_PROMPT,  # the source file is the whole input
                "resolutions": None if recast else (list(spec.VALID_RESOLUTIONS) or None),
                "aspect_ratios": (list(spec.VALID_RATIOS) or None) if own_ratio else None,
                # recast/lipsync: the reference image rides on first_frame; extend/edit take none
                "frame_images": [] if no_image else ["first_frame"],
                "audio_input": lipsync,  # takes an uploaded audio track (lip sync)
                # reference-to-video branch (image/video/audio refs, [@name]
                # mentions): the allowed types, total cap and per-type limits.
                "ref_mode": _plain(ref_mode) if (ref_mode := meta.get("ref_mode")) else None,
                "video_input": bool(meta.get("video_input")),
                "modes": meta.get("modes") or None,
                "generate_audio": "generate_audio" in meta.get("options", []),
                "created": None,
                "hidden": meta.get("hidden") or None,
            }
        )
    return out


def _plain(value: Mapping[str, object]) -> dict[str, JsonValue]:
    """A JSON-literal table entry (a ``TypedDict``) as a plain JSON object."""
    return as_object(value)


def list_audio_models() -> list[ModelEntry]:
    """Pollo's speech and music models. `options` says which inputs the UI offers."""
    return [
        {
            "id": PREFIX + key,
            "name": f"Pollo: {meta.get('label') or key}",
            "type": meta.get("type"),
            "options": meta.get("options") or [],
            "audio_input": bool(meta.get("audio_input")),  # takes a reference clip (voice cloning)
            "created": None,
            "hidden": meta.get("hidden") or None,
        }
        for key, _spec, meta in _catalogue(AUDIO_GENERATORS)
    ]


def list_voices(page: int = 1, page_size: int = 50, **filters: str) -> dict[str, JsonValue]:
    """Pollo's official TTS voices ({"voices": [...], "total"}). A free GET."""
    params = {"page": page, "pageSize": page_size, **{k: v for k, v in filters.items() if v}}
    try:
        resp = requests.get(
            f"{POLLO_PLATFORM_BASE}/config/voice/items",
            params=params,
            headers={"x-api-key": keyctx.provider_key("pollo") or ""},
            timeout=POLLO_API_TIMEOUT,
        )
        resp.raise_for_status()
        body = as_object(body_of(resp))
    except (requests.RequestException, ValueError) as e:
        raise VoiceListError(e) from e
    keep = ("voiceId", "voiceName", "sampleAudio", "language", "gender", "age", "voiceStyle", "accent", "engineCode")
    voices: list[JsonValue] = [{k: v.get(k) for k in keep} for v in as_objects(body.get("data"))]
    return {"voices": voices, "total": body.get("total", len(voices))}


def generator_key(model_id: str, generators: Mapping[str, ModelSpec]) -> str:
    """The model key of a ``pollo/<key>`` id; raises unless Pollo is configured and the key is in ``generators``."""
    if not is_configured():
        raise ApiKeyMissingError
    key = model_id[len(PREFIX) :]
    if key not in generators:
        raise UnknownModelError(key)
    return key


# families that animate a reference image with a source video (image + video)
IMAGE_AND_VIDEO = ("motion", "faceswap")
# families that work on a source video alone (no image)
VIDEO_ONLY = ("extend", "video_edit", "upscale", "bgremove", "subtitle_remove")
# families that run with no prompt text
NO_PROMPT = ("upscale", "bgremove", "subtitle_remove", "faceswap", "motion")
# families whose enhancement mode the user can pick
TAKES_MODE = ("motion", "upscale", "subtitle_remove")

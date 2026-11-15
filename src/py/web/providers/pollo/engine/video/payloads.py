"""Video API bodies: the generic family plus Kling, extend, edit, upscale, lipsync and motion."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

from web.providers.pollo.engine._shared import Payload, as_str, parse_aspect_ratio, valid_length
from web.providers.pollo.engine.errors import (
    EditPromptRequiredError,
    FaceImageRequiredError,
    LipsyncAudioRequiredError,
    LipsyncImageRequiredError,
    LipsyncPromptRequiredError,
    ReferenceImageRequiredError,
    SourceVideoRequiredError,
    TextToVideoUnsupportedError,
    UnknownBuilderError,
    VideoAction,
)
from web.providers.pollo.engine.video.models import cfg

if TYPE_CHECKING:
    from web.providers.pollo.engine.video.types import Builder, Inputs, VideoCfg
    from web.types import JsonValue


def _normalize_refs(refs: JsonValue) -> list[dict[str, JsonValue]] | None:
    if not isinstance(refs, Sequence) or isinstance(refs, str):
        return None
    out: list[dict[str, JsonValue]] = []
    for ref in refs:
        if not isinstance(ref, Mapping):
            continue
        url = str(ref.get("url") or ref.get("image") or ref.get("video") or ref.get("audio") or "").strip()
        if not url:
            continue
        item: dict[str, JsonValue] = {"url": url}
        if ref.get("type"):
            item["type"] = ref["type"]
        # The handle the prompt mentions as [@name] (Kling 4.0 / Omni, MiniMax
        # H3…). Pollo defaults it to ref1, ref2… by position when omitted.
        if ref.get("name"):
            item["name"] = ref["name"]
        out.append(item)
    return out or None


def _resolve_resolution(c: VideoCfg, **kw: JsonValue) -> str:
    if forced := c.get("FORCE_RESOLUTION"):
        return forced
    return as_str(kw.get("resolution")) or c["DEFAULT_RESOLUTION"]


def _resolve_length(c: VideoCfg, **kw: JsonValue) -> int:
    length_str = str(kw.get("length") or c["DEFAULT_LENGTH"])
    if kw.get("refs") and c["REF_VALID_LENGTHS"]:
        length = int(length_str) if length_str.isdigit() else c["DEFAULT_LENGTH"]
        return min(c["REF_VALID_LENGTHS"], key=lambda v: abs(v - length))
    return valid_length(length_str, c["VALID_LENGTHS"], c["DEFAULT_LENGTH"])


def _resolve_aspect_ratio(c: VideoCfg, **kw: JsonValue) -> str:
    # the explicit kwarg, then a model default ("adaptive" on a few), else the
    # base "portrait" → 9:16.
    return as_str(kw.get("aspect_ratio")) or c.get("DEFAULT_RATIO") or parse_aspect_ratio("portrait")


def _resolve_mode(c: VideoCfg, resolution: str, mode: str | None) -> str | None:
    if not c["HAS_MODE"]:
        return None
    if pro_resolutions := c.get("MODE_PRO_RESOLUTIONS"):
        return "pro" if resolution.upper() in {r.upper() for r in pro_resolutions} else "basic"
    return mode or c.get("MODE_DEFAULT")


def _pick_mode(c: VideoCfg, **kw: JsonValue) -> str | None:
    """The requested mode when the model offers it, else the model's first mode."""
    modes = c.get("MODES", ())
    requested = as_str(kw.get("mode"))
    if requested in modes:
        return requested
    return modes[0] if modes else None


def _process_inputs(c: VideoCfg, image_url: str | None, **kw: JsonValue) -> Inputs:
    """Resolve request inputs against a model's configuration.

    Use the caller's value or the model default; unsupported fields stay None.
    """
    refs = _normalize_refs(kw.get("refs")) if c["HAS_REFS"] else None
    resolution = _resolve_resolution(c, **kw)
    generate_audio = kw.get("generate_audio")
    web_search = kw.get("web_search")
    return {
        "refs": refs,
        "is_text_only": image_url is None,
        "resolution": resolution,
        "length": _resolve_length(c, **kw),
        "aspect_ratio": _resolve_aspect_ratio(c, **kw),
        "image_tail": kw.get("image_tail") if c["HAS_IMAGE_TAIL"] else None,
        "seed": kw.get("seed") if c["HAS_SEED"] else None,
        "generate_audio": (True if generate_audio is None else generate_audio) if c["HAS_GENERATE_AUDIO"] else None,
        "web_search": (False if web_search is None else web_search) if c["HAS_WEB_SEARCH"] else None,
        "mode": _resolve_mode(c, resolution, as_str(kw.get("mode"))),
        "negative_prompt": kw.get("negative_prompt") if c["HAS_NEGATIVE_PROMPT_AUDIO"] else None,
        "audio_url": kw.get("audio_url") if c["HAS_NEGATIVE_PROMPT_AUDIO"] else None,
    }


def _generic_payload(c: VideoCfg, prompt: str, image_url: str | None, s: Inputs, **_: JsonValue) -> Payload:
    refs, is_text_only = s["refs"], s["is_text_only"]
    attrs: dict[str, JsonValue] = {"prompt": prompt}
    if refs:
        attrs["refs"] = refs
    elif not is_text_only:
        attrs["image"] = image_url
    attrs["duration"] = s["length"]
    if s["resolution"]:  # some models (Sora 2) have no resolution field
        attrs["resolution"] = s["resolution"]
    # Only send aspectRatio when the model actually offers one (a few, e.g.
    # Hailuo 2.3, take none and derive it from the image).
    if (refs or is_text_only or c["HAS_ASPECT_RATIO_ON_IMAGE"]) and c["VALID_RATIOS"]:
        attrs["aspectRatio"] = s["aspect_ratio"]

    has_refs = bool(refs)
    image_branch = not has_refs and not is_text_only
    candidates: dict[str, tuple[JsonValue, bool]] = {
        "imageTail": ((s["image_tail"] or None) if c["HAS_IMAGE_TAIL"] else None, image_branch),
        "generateAudio": (s["generate_audio"], True),
        "webSearch": (s["web_search"], not has_refs),
        "seed": (s["seed"], c["REF_HAS_SEED"] or not has_refs),
        "mode": (s["mode"] or None, True),
        "negativePrompt": (s["negative_prompt"] or None, True),
        "audio": (s["audio_url"] or None, not has_refs),
    }
    attrs.update({k: v for k, (v, allowed) in candidates.items() if v is not None and allowed})
    return {"input": attrs}


def _kling_resolution(attrs: dict[str, JsonValue], c: VideoCfg, tier: JsonValue, s: Inputs) -> None:
    """Send Kling's resolution tier as `resolution` or, for mode-tier models, as `mode`."""
    if tier not in c["VALID_RESOLUTIONS"]:
        return
    if not c["RESOLUTION_IS_MODE"]:
        attrs["resolution"] = tier
    elif c["MODE_ON_TEXT"] or not s["is_text_only"]:
        attrs["mode"] = tier


def _kling_tail_rules(attrs: dict[str, JsonValue], c: VideoCfg) -> None:
    """A last frame can force pro mode and rule out generated audio."""
    if "imageTail" not in attrs:
        return
    if c["IMAGE_TAIL_NEEDS_PRO"]:
        attrs["mode"] = "pro"
    if c["NO_AUDIO_WITH_IMAGE_TAIL"]:
        attrs.pop("generateAudio", None)


def _kling_payload(c: VideoCfg, prompt: str, image_url: str | None, s: Inputs, **_: JsonValue) -> Payload:
    if s["is_text_only"] and not c["TEXT_TO_VIDEO"]:
        raise TextToVideoUnsupportedError(c.get("MODEL", ""))
    payload = _generic_payload(c, prompt, image_url, s)
    attrs = payload["input"]
    _kling_resolution(attrs, c, attrs.pop("resolution", None), s)
    _kling_tail_rules(attrs, c)
    return payload


def _extend_payload(_c: VideoCfg, prompt: str, _image_url: str | None, s: Inputs, **kw: JsonValue) -> Payload:
    video_url = kw.get("video_url")
    if not video_url:
        raise SourceVideoRequiredError(VideoAction.EXTEND)
    attrs: dict[str, JsonValue] = {"video": video_url}
    if prompt:
        attrs["prompt"] = prompt
    attrs["duration"] = s["length"]
    attrs["resolution"] = s["resolution"]
    if s["generate_audio"] is not None:
        attrs["generateAudio"] = s["generate_audio"]
    if s["seed"] is not None:
        attrs["seed"] = s["seed"]
    return {"input": attrs}


def _edit_payload(c: VideoCfg, prompt: str, _image_url: str | None, s: Inputs, **kw: JsonValue) -> Payload:
    video_url = kw.get("video_url")
    if not video_url:
        raise SourceVideoRequiredError(VideoAction.EDIT)
    if not prompt:
        raise EditPromptRequiredError
    attrs: dict[str, JsonValue] = {"video": video_url, "prompt": prompt}
    if c["VALID_RESOLUTIONS"] and s["resolution"]:
        attrs["resolution"] = s["resolution"]
    return {"input": attrs}


def _upscale_payload(c: VideoCfg, _prompt: str, _image_url: str | None, s: Inputs, **kw: JsonValue) -> Payload:
    """Build a video-upscale body containing the source, scale, and mode.

    Unknown scale or mode values fall back to the model defaults.
    """
    video_url = kw.get("video_url")
    if not video_url:
        raise SourceVideoRequiredError(VideoAction.UPSCALE)
    scales = {v.lower(): v for v in c["VALID_RESOLUTIONS"]}
    scale = scales.get(s["resolution"].lower(), c["DEFAULT_RESOLUTION"])
    return {"input": {"video": video_url, "scale": scale, "mode": _pick_mode(c, **kw)}}


def _bgremove_payload(c: VideoCfg, _prompt: str, _image_url: str | None, s: Inputs, **kw: JsonValue) -> Payload:
    """Video background removal: {video, outputFormat} (webm / mov, both transparent)."""
    if not kw.get("video_url"):
        raise SourceVideoRequiredError(VideoAction.BGREMOVE)
    fmt = s["resolution"] if s["resolution"] in c["VALID_RESOLUTIONS"] else c["DEFAULT_RESOLUTION"]
    return {"input": {"video": kw["video_url"], "outputFormat": fmt}}


def _subtitle_payload(c: VideoCfg, _prompt: str, _image_url: str | None, s: Inputs, **kw: JsonValue) -> Payload:
    """Subtitle removal: {video, language, tier}; unknown values fall back to the defaults."""
    if not kw.get("video_url"):
        raise SourceVideoRequiredError(VideoAction.SUBTITLE)
    lang = s["resolution"] if s["resolution"] in c["VALID_RESOLUTIONS"] else c["DEFAULT_RESOLUTION"]
    return {"input": {"video": kw["video_url"], "language": lang, "tier": _pick_mode(c, **kw)}}


def _faceswap_payload(_c: VideoCfg, _prompt: str, image_url: str | None, _s: Inputs, **kw: JsonValue) -> Payload:
    """Face swap: the source video plus a face image."""
    if not kw.get("video_url"):
        raise SourceVideoRequiredError(VideoAction.FACESWAP)
    if not image_url:
        raise FaceImageRequiredError
    return {"input": {"video": kw["video_url"], "faceImage": image_url}}


def _lipsync_payload(c: VideoCfg, prompt: str, image_url: str | None, s: Inputs, **kw: JsonValue) -> Payload:
    """Build a lip-sync body from a reference image and audio track.

    Include a prompt when supplied or required, and resolution when supported.
    """
    audio_url = kw.get("audio_url")
    if not image_url:
        raise LipsyncImageRequiredError
    if not audio_url:
        raise LipsyncAudioRequiredError
    if c.get("NEEDS_PROMPT") and not prompt:
        raise LipsyncPromptRequiredError
    attrs: dict[str, JsonValue] = {"image": image_url, "audio": audio_url}
    if prompt:
        attrs["prompt"] = prompt
    if c["VALID_RESOLUTIONS"] and s["resolution"]:
        attrs["resolution"] = s["resolution"]
    return {"input": attrs}


def _motion_payload(c: VideoCfg, _prompt: str, image_url: str | None, s: Inputs, **kw: JsonValue) -> Payload:
    """Build a motion-transfer body from a reference image and source video.

    ``mode`` is sent only when the model supports it.
    """
    video_url = kw.get("video_url")
    if not video_url:
        raise SourceVideoRequiredError(VideoAction.MOTION)
    if not image_url:
        raise ReferenceImageRequiredError
    attrs: dict[str, JsonValue] = {"image": image_url, "video": video_url}
    if c["HAS_MODE"]:
        attrs["mode"] = s["mode"] or c.get("DEFAULT_MODE")
    return {"input": attrs}


_BUILDERS: dict[str, Builder] = {
    "generic": _generic_payload,
    "kling": _kling_payload,
    "extend": _extend_payload,
    "edit": _edit_payload,
    "upscale": _upscale_payload,
    "bgremove": _bgremove_payload,
    "subtitle": _subtitle_payload,
    "faceswap": _faceswap_payload,
    "lipsync": _lipsync_payload,
    "motion": _motion_payload,
}


def video_payload(model_id: str, *, prompt: str, image_url: str | None, **kw: JsonValue) -> Payload:
    """Build the video API body for any model, dispatching on its family."""
    c = cfg(model_id)
    build = _BUILDERS.get(c["builder"])
    if build is None:
        raise UnknownBuilderError(c["builder"], model_id)
    return build(c, prompt, image_url, _process_inputs(c, image_url, **kw), **kw)

"""Venice's model catalogue entries: shaping the API's model list into text, image and video rows."""

import contextlib
import re
from collections.abc import Mapping

from web.jsonutil import as_number, as_object, as_str
from web.providers.venice.types import (
    Entry,
    ImageEntry,
    ImageTarget,
    Model,
    PriceSpec,
    TextEntry,
    VideoEntry,
    VideoTarget,
    max_input_images,
    strs,
    video_constraints,
)
from web.types import JsonValue, ModelEntry

PREFIX = "venice/"


# Video model families, by what they need from the chat (see video_family)
VIDEO_FAMILIES = {
    "standard": "text → video, or animate an image",
    "reference": "reference images (characters, pins, attached images) → video",
    "frames": "first frame + last frame → video",
    "angles": "image → video with a camera move around the subject",
    "video": "the chat's latest video → a new video",
    "motion": "the chat's latest video's motion + an image → video",
    "upscale": "upscale the chat's latest video",
}


FAMILY_LABELS = {
    "reference": "refs→video",
    "frames": "first+last frame",
    "angles": "multi-angle",
    "video": "video→video",
    "motion": "motion control",
    "upscale": "upscale",
}


def float_or_none(value: JsonValue) -> float | None:
    """The value as a float when it is a number or numeric text, else None."""
    if isinstance(value, (int, float, str)):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def usd_or_none(price: JsonValue) -> float | None:
    """A price as USD: a plain number, numeric text, or an object with a ``usd`` field."""
    if isinstance(price, Mapping):
        price = price.get("usd")
    return float_or_none(price)


def second_options(values: list[str]) -> list[int]:
    """The whole-second lengths in a list of duration strings like '5s' (others are skipped)."""
    out: list[int] = []
    for v in values:
        with contextlib.suppress(ValueError):  # "auto", "1 gen" — not a length chat can ask for
            out.append(int(v.lower().rstrip("s")))
    return sorted(set(out))


def uncensored_flag(*models: Model | None) -> bool | None:
    """Venice's own "uncensored" flag on a model (on any of a pair)."""
    return any(m.uncensored for m in models if m) or None


def privacy_level(*models: Model | None) -> str | None:
    """Return the least-private level across a model pair.

    Venice reports ``private`` for its own servers and ``anonymized`` for
    third-party providers that receive requests without user identity.
    """
    levels = {m.privacy for m in models if m} - {None}
    return "anonymized" if "anonymized" in levels else ("private" if levels else None)


def edit_model_for(image_id: str, edit_ids: set[str]) -> str | None:
    """Find an image model's edit twin among the available inpaint models.

    The match may drop ``-image`` before adding ``-edit``.
    """
    for candidate in (f"{image_id}-edit", image_id.replace("-image", "", 1) + "-edit"):
        if candidate in edit_ids:
            return candidate
    return None


def text_entry(m: Model) -> TextEntry:
    """One catalogue row for a Venice text model."""
    caps = m.capabilities
    prompt_usd, completion_usd = usd_or_none(m.pricing.get("input")), usd_or_none(m.pricing.get("output"))
    # Venice prices per million tokens; the picker expects per token
    prompt_price = prompt_usd / 1e6 if prompt_usd is not None else None
    completion_price = completion_usd / 1e6 if completion_usd is not None else None
    public: ModelEntry = {
        "id": PREFIX + m.id,
        "name": f"Venice: {m.name}",
        "context_length": m.context_length,
        "input_modalities": ["text", "image"] if caps.get("supportsVision") else ["text"],
        "supports_tools": bool(caps.get("supportsFunctionCalling")),
        "uncensored": uncensored_flag(m),
        "privacy": privacy_level(m),
        "prompt_price": prompt_price,
        "completion_price": completion_price,
        "created": m.created,
        "price": price_tag(completion_price * 1e6, "per 1M output tokens") if completion_price is not None else None,
    }
    return TextEntry(PREFIX + m.id, public, prompt_price, completion_price)


def image_entry(m: Model, edit: Model | None) -> ImageEntry:
    """A text-to-image model, with its edit twin when it has one."""
    c = m.constraints
    default_res = as_str(c.get("defaultResolution"))
    generate = ImageTarget(m.id, PriceSpec("generation", m.pricing, default_res))
    edit_target = (
        ImageTarget(edit.id, PriceSpec("inpaint", edit.pricing, as_str(edit.constraints.get("defaultResolution"))))
        if edit
        else None
    )
    max_refs = max_input_images(edit.constraints) if edit else 1
    aspect_ratios, resolutions = strs(c.get("aspectRatios")), strs(c.get("resolutions"))
    public: ModelEntry = {
        "id": PREFIX + m.id,
        "name": f"Venice: {m.name}",
        "input_modalities": ["text", "image"] if edit else ["text"],
        "uncensored": uncensored_flag(m, edit),
        "privacy": privacy_level(m, edit),
        "aspect_ratios": aspect_ratios,
        "resolutions": resolutions,
        "created": m.created,
        "conversational": False,
        # Reference images its edit twin takes (one when Venice doesn't say)
        "max_refs": max_refs if edit else None,
        "price": price_tag(image_price(m.pricing, "generation", None, default_res), default_res),
    }
    return ImageEntry(PREFIX + m.id, public, generate, edit_target, max_refs, aspect_ratios or [], resolutions or [])


def edit_only_entry(m: Model) -> ImageEntry:
    """An edit model with no text-to-image twin: it only works on a reference image."""
    c = m.constraints
    default_res = as_str(c.get("defaultResolution"))
    max_refs = max_input_images(c)
    aspect_ratios, resolutions = strs(c.get("aspectRatios")), strs(c.get("resolutions"))
    public: ModelEntry = {
        "id": PREFIX + m.id,
        "name": f"Venice: {m.name} (edit only)",
        "input_modalities": ["text", "image"],
        "uncensored": uncensored_flag(m),
        "privacy": privacy_level(m),
        "aspect_ratios": aspect_ratios,
        "resolutions": resolutions,
        "created": m.created,
        "conversational": False,
        "max_refs": max_refs,
        "price": price_tag(image_price(m.pricing, "inpaint", None, default_res), default_res),
    }
    edit_target = ImageTarget(m.id, PriceSpec("inpaint", m.pricing, default_res))
    return ImageEntry(PREFIX + m.id, public, None, edit_target, max_refs, aspect_ratios or [], resolutions or [])


def by_price[E: Entry](models: list[E]) -> list[E]:
    """Uncensored first (as the user asked), then cheapest first; unpriced last."""

    def key(m: E) -> tuple[bool, bool, int | float, str]:
        usd = as_number(as_object(m.public.get("price")).get("usd"))
        return (not m.public.get("uncensored"), usd is None, usd or 0, (as_str(m.public.get("name")) or "").lower())

    return sorted(models, key=key)


def price_tag(usd: float | None, basis: str | None = None) -> dict[str, JsonValue] | None:
    """The price badge for a model row (None when it has no known price)."""
    return {"usd": round(usd, 4), "basis": basis or ""} if usd is not None else None


def image_price(
    pricing: dict[str, JsonValue], key: str, resolution: str | None, default_res: str | None
) -> float | None:
    """One image's USD price: the resolution's tier if priced that way, else the flat price."""
    tiers = as_object(pricing.get("resolutions"))
    for res in (resolution, None, default_res):
        if res is None:
            flat = usd_or_none(pricing.get(key))
            if flat is not None:
                return flat
        elif res in tiers:
            tier = usd_or_none(tiers[res])
            if tier is not None:
                return tier
    prices = [p for p in (usd_or_none(v) for v in tiers.values()) if p is not None]
    return min(prices) if prices else None


def res_rank(res: str) -> int:
    """Rough vertical pixels, to find a model's lowest resolution ("480p", "768P", "2K", "4k")."""
    s = res.lower()
    if m := re.match(r"(\d+)p", s):
        return int(m.group(1))
    return {"1k": 1080, "2k": 1440, "4k": 2160}.get(s, 10_000)


# A model id containing any of these words belongs to that family (checked in order)
_VIDEO_FAMILY_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("reference", ("reference-to-video",)),
    ("frames", ("first-last-frame", "transition")),
    ("angles", ("multi-angle",)),
    ("upscale", ("upscale",)),
    ("motion", ("motion-control",)),
)


def video_family(m: Model) -> str:
    """Which family a Venice video model belongs to, by its id and type."""
    for family, markers in _VIDEO_FAMILY_MARKERS:
        if any(marker in m.id for marker in markers):
            return family
    return "video" if as_str(m.constraints.get("model_type")) == "video" else "standard"


def video_entry(family: str, first: Model, main: Model | None, i2v: Model | None) -> VideoEntry:
    """Build one catalogue entry from a video model family.

    ``first`` is the model that names the entry. For ``standard``, ``main`` is
    the text-to-video model (or None if only an image-to-video model exists),
    and ``i2v`` is its twin.
    """
    c = video_constraints(first.constraints)
    name = f"Venice: {first.name}"
    if family == "standard" and not main:
        name += " (image→video only)"
    elif family != "standard":
        name += f" ({FAMILY_LABELS[family]})"
    frames = {
        "standard": ["first_frame"] if i2v else [],
        "frames": ["first_frame", "last_frame"],
        "angles": ["first_frame"],
        "motion": ["first_frame"],
    }.get(family, [])
    video_input = family in ("video", "motion", "upscale")
    public: ModelEntry = {
        "id": PREFIX + first.id,
        "name": name,
        "family": family,
        "family_hint": VIDEO_FAMILIES[family],
        "durations": second_options(c.durations) or None,
        "resolutions": c.resolutions or None,
        "aspect_ratios": c.aspect_ratios or None,
        "frame_images": frames,
        "reference_images": family == "reference",
        "video_input": video_input,
        "uncensored": uncensored_flag(main, i2v),
        "privacy": privacy_level(main, i2v),
        "generate_audio": c.audio_configurable,
        "created": first.created,
    }
    if family == "standard":
        text = VideoTarget(main.id, video_constraints(main.constraints)) if main else None
        image = VideoTarget(i2v.id, video_constraints(i2v.constraints)) if i2v else None
    else:
        text, image = None, VideoTarget(first.id, c)
    return VideoEntry(PREFIX + first.id, public, family, video_input, text, image)

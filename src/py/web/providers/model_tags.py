"""Capability tags for every model, derived from the shaped catalogue dicts.

This keeps tags consistent across all three providers.

One source of truth for the tag slugs and their human labels (`TAGS`), plus
`tags_for(kind, model)` — called once per model by `web/chat/catalogue.py` as it
assembles the catalogue. Tags are what the model picker filters on; they're read
off fields the providers already emit (Pollo's `type`, Venice's `family`,
everyone's `frame_images`/`reference_images`/`generate_audio`/`input_modalities`),
so nothing new has to be stored per model.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from web.types import JsonValue, ModelEntry

# slug -> human label shown on the filter chips, grouped by the kind it applies
# to. Order here is the order the chips appear in.
TAGS: dict[str, str] = {
    # video
    "img2vid": "Image→Video",
    "text2vid": "Text→Video",
    "ref2vid": "References→Video",
    "video_refs": "Video refs (recast)",
    "first_last": "First+Last frame",
    "video_edit": "Video edit",
    "video_extend": "Video extend",
    "motion": "Motion / recast",
    "lipsync": "Lip sync",
    "upscale": "Upscale",
    "bg_remove": "Background remove",
    "subtitle_remove": "Subtitle remove",
    "face_swap": "Face swap",
    "audio": "Makes audio",
    # audio
    "tts": "Text→Speech",
    "music": "Music",
    # image
    "text2img": "Text→Image",
    "image_edit": "Image edit",
    "tools": "Image tools",
    # text
    "vision": "Vision",
    "functions": "Tools / functions",
}


def _text(value: JsonValue) -> str:
    """A catalogue value as text ("" when it isn't a string)."""
    return value if isinstance(value, str) else ""


def _strings(value: JsonValue) -> list[str]:
    """The strings in a catalogue list value (anything else is empty)."""
    if isinstance(value, Sequence) and not isinstance(value, str):
        return [item for item in value if isinstance(item, str)]
    return []


def tags_for(kind: str, m: ModelEntry) -> list[str]:
    """The capability tags for one shaped catalogue model of `kind`."""
    build = _BUILDERS.get(kind)
    return list(dict.fromkeys(build(m))) if build else []


_AUDIO_TYPE_TAGS = {"speech": ("tts",), "music": ("music",)}

# Pollo's `type` and Venice's `family` → capability tags (table-driven so the
# function stays simple). "standard" / img-animation is handled in the helper.
_POLLO_TYPE_TAGS = {
    "extend": ("video_extend",),
    "video_edit": ("video_edit",),
    "upscale": ("upscale",),
    "bgremove": ("bg_remove",),
    "subtitle_remove": ("subtitle_remove",),
    "faceswap": ("face_swap",),
    "motion": ("motion",),
    "lipsync": ("lipsync",),
    "ref": ("ref2vid",),
    "img2vid": ("img2vid", "text2vid"),
}
_VENICE_FAMILY_TAGS = {
    "video": ("video_edit",),
    "motion": ("motion",),
    "upscale": ("upscale",),
    "reference": ("ref2vid",),
    "frames": ("img2vid", "first_last"),
    "angles": ("img2vid",),
}
# Families/types where a "first_frame" is a role other than "animate this image"
_EDIT_TYPES = {
    "motion",
    "ref",
    "extend",
    "video_edit",
    "upscale",
    "bgremove",
    "subtitle_remove",
    "faceswap",
    "lipsync",
}
_VENICE_EDIT_FAMS = {"video", "motion", "upscale", "reference"}


def _video_tags(m: ModelEntry) -> list[str]:
    """Tags for a video model (may repeat; `tags_for` dedupes, keeping first-seen order)."""
    typ = _text(m.get("type"))  # Pollo
    fam = _text(m.get("family"))  # Venice
    frames = _strings(m.get("frame_images"))
    ref_mode = m.get("ref_mode")
    refs: Mapping[str, JsonValue] = (
        ref_mode if isinstance(ref_mode, Mapping) else {}
    )  # the model's reference-to-video branch
    tags = [*_POLLO_TYPE_TAGS.get(typ, ()), *_VENICE_FAMILY_TAGS.get(fam, ())]
    # (condition, tag) in the order the tags are reported
    conditional = (
        (fam == "standard", "text2vid"),
        (bool(m.get("reference_images")), "ref2vid"),
        (bool(refs), "ref2vid"),
        # takes a source video as a reference: replace/restyle part of a clip
        ("video" in _strings(refs.get("types")), "video_refs"),
        ("last_frame" in frames, "first_last"),
        (bool(m.get("generate_audio")), "audio"),
    )
    tags.extend(tag for present, tag in conditional if present)
    return [*tags, *_video_img_tags(m, typ, fam, frames)]


def _video_img_tags(m: ModelEntry, typ: str, fam: str, frames: list[str]) -> list[str]:
    """Image-to-video and text-to-video tags supported by the model.

    ``first_frame`` means image-to-video only for plain generators, not edit
    families where the image plays a different role.
    """
    special = typ in _EDIT_TYPES or fam in _VENICE_EDIT_FAMS
    tags: list[str] = []
    if "first_frame" in frames and not special:
        tags.append("img2vid")
    if not typ and not fam:  # OpenRouter video carries neither field
        if "image" in _strings(m.get("input_modalities")) or "first_frame" in frames:
            tags.append("img2vid")
        tags.append("text2vid")
    return tags


def _image_tags(m: ModelEntry) -> list[str]:
    """Tags for an image model."""
    # Image tools (face-swap, background remover, …) are their own thing and
    # don't generate from a bare prompt — a later stage sets `tool`.
    if m.get("tool"):
        return ["tools"]
    tags = ["text2img"]
    mods = _strings(m.get("input_modalities"))
    if "image" in mods or m.get("conversational") or m.get("max_refs"):
        tags.append("image_edit")
    return tags


def _audio_tags(m: ModelEntry) -> list[str]:
    """Tags for an audio (speech / music) model."""
    return list(_AUDIO_TYPE_TAGS.get(_text(m.get("type")), ()))


def _text_tags(m: ModelEntry) -> list[str]:
    """Tags for a text model."""
    tags: list[str] = []
    if "image" in _strings(m.get("input_modalities")):
        tags.append("vision")
    if m.get("supports_tools"):
        tags.append("functions")
    return tags


_BUILDERS: dict[str, Callable[[ModelEntry], list[str]]] = {
    "video": _video_tags,
    "image": _image_tags,
    "audio": _audio_tags,
    "text": _text_tags,
}

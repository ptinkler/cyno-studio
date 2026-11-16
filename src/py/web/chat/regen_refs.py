"""Reference pictures for a regenerated card.

The caller names chat files; this checks them and puts them where the model being run takes them:
an image model's `refs`, or, for a video model, its first/last frame, `refs` or named `ref_items`
(whichever its family uses, as a fresh send would).
"""

from collections.abc import Mapping, Sequence

from fastapi import HTTPException

from web.chat.catalogue import model_info
from web.chat.helpers import conversation_dir
from web.jsonutil import as_list
from web.media.kinds import kind_of
from web.types import JsonValue
from web.uploads.files import safe_filename

MAX_REFS = 8


def checked_refs(conv_id: str, names: Sequence[str]) -> list[str]:
    """The named files, each an image in this chat (400 otherwise), without repeats."""
    files = list(dict.fromkeys(safe_filename(name) for name in names))
    if len(files) > MAX_REFS:
        raise HTTPException(400, f"Up to {MAX_REFS} references")
    for name in files:
        if kind_of(name) != "image" or not (conversation_dir(conv_id) / name).is_file():
            raise HTTPException(400, f"Reference not found: {name}")
    return files


def _character_refs(params: Mapping[str, JsonValue]) -> list[JsonValue]:
    """The refs that are characters' images (kept as they were: the picker only handles chat files)."""
    return [r for r in as_list(params.get("refs")) if isinstance(r, str) and r.startswith("char:")]


def image_params(params: Mapping[str, JsonValue], files: Sequence[str]) -> dict[str, JsonValue]:
    """An image card's params with `files` as its references (characters stay)."""
    return {**params, "refs": [*files, *_character_refs(params)]}


def video_params(
    model: str, prompt: str, params: Mapping[str, JsonValue], files: Sequence[str]
) -> dict[str, JsonValue]:
    """A video card's params with `files` as its pictures, in the inputs `model` takes them in."""
    info = model_info("video", model) or {}
    out = dict(params)
    ref_mode = info.get("ref_mode")
    kept = [i for i in as_list(params.get("ref_items")) if isinstance(i, Mapping) and i.get("type") != "image"]
    # Like a fresh send: the named-references branch only when the prompt mentions one or a video/audio rides along
    if ref_mode and (kept or "[@" in prompt):
        cap = (ref_mode.get("limits") or {}).get("image")
        named = files[:cap] if cap else files
        out["ref_items"] = [
            *({"file": f, "name": f"image{n}", "type": "image"} for n, f in enumerate(named, 1)),
            *kept,
        ]
        out["first_frame"] = None
        out.pop("last_frame", None)
        out.pop("refs", None)
        return out
    out.pop("ref_items", None)
    out["first_frame"] = files[0] if files else None
    if info.get("reference_images") or info.get("family") == "motion":
        cap = info.get("max_refs")
        out["refs"] = [*(files[:cap] if cap else files), *_character_refs(params)]
    else:
        out.pop("refs", None)
    if "last_frame" in (info.get("frame_images") or []):
        out["last_frame"] = files[1] if len(files) > 1 else None
    else:
        out.pop("last_frame", None)
    return out


def regeneration_params(
    kind: str | None, model: str, prompt: str, params: Mapping[str, JsonValue], files: Sequence[str]
) -> dict[str, JsonValue]:
    """The card's params with `files` as its pictures, for whatever kind of card it is."""
    if kind == "video":
        return video_params(model, prompt, params, files)
    return image_params(params, files)

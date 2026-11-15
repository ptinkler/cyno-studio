"""Image API bodies."""

from __future__ import annotations

from typing import TYPE_CHECKING, NotRequired, TypedDict, cast

from web.core.config import POLLO_GENERATION_BASE
from web.providers.pollo_engine._shared import Payload, as_str, as_str_list, parse_aspect_ratio
from web.providers.pollo_engine.errors import SourceImageRequiredError

if TYPE_CHECKING:
    from web.types import JsonValue


class ImageRow(TypedDict, total=False):
    """One image model's table row: its endpoint plus overrides of the defaults."""

    PROVIDER: str
    MODEL: str
    V1_URL: str
    TOOL: str
    VALID_RATIOS: tuple[str, ...]
    VALID_RESOLUTIONS: tuple[str, ...]
    DEFAULT_RATIO_KEYWORD: str
    HAS_SEED: bool
    ACCEPTS_IMAGES: bool
    MAX_IMAGES: int
    ASPECT_RATIO_WITH_IMAGES: bool


class ImageCfg(TypedDict):
    """An image model's settings once the defaults are layered under its row."""

    VALID_RATIOS: tuple[str, ...]
    VALID_RESOLUTIONS: tuple[str, ...]
    DEFAULT_RATIO_KEYWORD: str
    HAS_SEED: bool
    ACCEPTS_IMAGES: bool
    MAX_IMAGES: int
    ASPECT_RATIO_WITH_IMAGES: bool
    PROVIDER: NotRequired[str]
    MODEL: NotRequired[str]
    V1_URL: NotRequired[str]
    TOOL: NotRequired[str]


_V1_IMAGE_DEFAULTS: ImageRow = {
    "VALID_RATIOS": (),
    "VALID_RESOLUTIONS": (),
    "DEFAULT_RATIO_KEYWORD": "square",
    "HAS_SEED": False,
    "ACCEPTS_IMAGES": True,
    "MAX_IMAGES": 0,
    "ASPECT_RATIO_WITH_IMAGES": True,
}

IMAGE_MODELS: dict[str, ImageRow] = {
    "pollojourney": {
        "PROVIDER": "pollo-ai",
        "MODEL": "pollojourney-v8-2-image",
        "VALID_RATIOS": ("1:1", "16:9", "3:2", "2:3", "3:4", "4:3", "9:16"),
        "VALID_RESOLUTIONS": ("1K", "2K"),
        "HAS_SEED": True,
    },
    "seedream": {
        "PROVIDER": "bytedance",
        "MODEL": "seedream-5-0-lite",
        "VALID_RATIOS": ("1:1", "16:9", "3:2", "2:3", "3:4", "4:3", "9:16", "21:9"),
        "VALID_RESOLUTIONS": ("2K", "3K", "4K"),
        "MAX_IMAGES": 14,
    },
    "nanobanana2": {
        "PROVIDER": "google",
        "MODEL": "nano-banana-2",
        "VALID_RATIOS": (
            "1:1",
            "9:16",
            "16:9",
            "4:3",
            "3:4",
            "3:2",
            "2:3",
            "5:4",
            "4:5",
            "21:9",
            "1:4",
            "4:1",
            "8:1",
            "1:8",
        ),
        "VALID_RESOLUTIONS": ("0.5K", "1K", "2K", "4K"),
    },
    "klingv3image": {
        "PROVIDER": "kling-ai",
        "MODEL": "kling-v3-image",
        "VALID_RATIOS": ("1:1", "3:2", "2:3", "3:4", "4:3", "16:9", "9:16", "21:9"),
        "VALID_RESOLUTIONS": ("1K", "2K"),
        "MAX_IMAGES": 1,
    },
    "klingv3omniimage": {
        "PROVIDER": "kling-ai",
        "MODEL": "kling-v3-omni",
        "VALID_RATIOS": ("16:9", "9:16", "1:1", "4:3", "3:4", "3:2", "2:3", "21:9", "auto"),
        "VALID_RESOLUTIONS": ("1K", "2K", "4K"),
        "MAX_IMAGES": 10,
    },
    "seedreampro": {
        "PROVIDER": "bytedance",
        "MODEL": "seedream-5-0-pro",
        "VALID_RATIOS": ("1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3"),
        "VALID_RESOLUTIONS": ("1K", "2K"),
        "MAX_IMAGES": 10,
    },
    "seedreamflash": {
        "PROVIDER": "bytedance",
        "MODEL": "seedream-5-0-flash",
        "VALID_RATIOS": ("1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "21:9"),
        "VALID_RESOLUTIONS": ("1K", "1.5K", "2K"),
        "MAX_IMAGES": 10,
    },
    "qwenimage3": {
        "PROVIDER": "alibaba",
        "MODEL": "qwen-image-3",
        "VALID_RATIOS": ("1:1", "3:4", "4:3", "16:9", "9:16"),
        "VALID_RESOLUTIONS": ("1K", "2K"),
        "MAX_IMAGES": 3,
    },
    "qwenimage3pro": {
        "PROVIDER": "alibaba",
        "MODEL": "qwen-image-3-pro",
        "VALID_RATIOS": ("1:1", "3:4", "4:3", "16:9", "9:16"),
        "VALID_RESOLUTIONS": ("1K", "2K"),
        "MAX_IMAGES": 3,
    },
    "qwenimageflash": {
        "PROVIDER": "alibaba",
        "MODEL": "pre-qwen-image-flash",
        "VALID_RATIOS": ("1:1", "3:4", "4:3", "16:9", "9:16"),
        "ACCEPTS_IMAGES": False,
    },
    # --- Newer frontier models (added 2026-11) ---
    "nanobananapro": {
        "PROVIDER": "google",
        "MODEL": "nano-banana-pro",
        "VALID_RATIOS": ("1:1", "9:16", "16:9", "4:3", "3:4", "3:2", "2:3", "5:4", "4:5", "21:9"),
        "VALID_RESOLUTIONS": ("1K", "2K", "4K"),
        "MAX_IMAGES": 14,
    },
    "nanobanana21": {
        "PROVIDER": "google",
        "MODEL": "nano-banana-2-1",
        "VALID_RATIOS": (
            "1:1",
            "9:16",
            "16:9",
            "4:3",
            "3:4",
            "3:2",
            "2:3",
            "5:4",
            "4:5",
            "21:9",
            "1:4",
            "4:1",
            "8:1",
            "1:8",
        ),
        "VALID_RESOLUTIONS": ("1K", "2K", "4K"),
    },
    "fluxkontextpro": {
        "PROVIDER": "flux",
        "MODEL": "flux-kontext-pro",
        "VALID_RATIOS": ("1:1", "16:9", "3:2", "2:3", "3:4", "4:3", "9:16"),
        "MAX_IMAGES": 1,
    },
    "fluxkontextmax": {
        "PROVIDER": "flux",
        "MODEL": "flux-kontext-max",
        "VALID_RATIOS": ("1:1", "16:9", "3:2", "2:3", "3:4", "4:3", "9:16"),
        "MAX_IMAGES": 1,
    },
    "flux2max": {
        "PROVIDER": "flux",
        "MODEL": "flux-2-max",
        "VALID_RATIOS": ("1:1", "16:9", "3:2", "2:3", "3:4", "4:3", "9:16"),
        "MAX_IMAGES": 10,
    },
    "gptimage25": {
        "PROVIDER": "openai",
        "MODEL": "gpt-image-2-5",
        "VALID_RATIOS": ("auto", "1:1", "9:16", "16:9", "21:9", "3:2", "2:3", "3:4", "4:3", "4:5", "5:4"),
        "VALID_RESOLUTIONS": ("1K", "2K", "4K"),
        "MAX_IMAGES": 16,
    },
    "seedream45": {
        "PROVIDER": "bytedance",
        "MODEL": "seedream-4-5",
        "VALID_RATIOS": ("1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3"),
        "VALID_RESOLUTIONS": ("2K", "4K"),
        "MAX_IMAGES": 10,
    },
    "midjourneyv82": {
        "PROVIDER": "midjourney",
        "MODEL": "midjourney-v8-2",
        "VALID_RATIOS": ("1:1", "16:9", "3:2", "2:3", "3:4", "4:3", "9:16"),
        "VALID_RESOLUTIONS": ("1K", "2K"),
        "MAX_IMAGES": 1,
    },
    "grokimage20": {
        "PROVIDER": "xai",
        "MODEL": "grok-imagine-image-2-0",
        "VALID_RATIOS": ("auto", "1:1", "16:9", "3:2", "2:3", "3:4", "4:3", "9:16", "2:1", "1:2", "21:9"),
        "VALID_RESOLUTIONS": ("1K", "2K"),
        "MAX_IMAGES": 1,
    },
    "recraftv3": {
        "PROVIDER": "recraft",
        "MODEL": "recraft-v3",
        "VALID_RATIOS": ("1:1", "16:9", "3:2", "2:3", "3:4", "4:3", "9:16"),
        "ACCEPTS_IMAGES": False,
    },
    "ideogramv2turbo": {
        "PROVIDER": "ideogram",
        "MODEL": "ideogram-v2-turbo",
        "VALID_RATIOS": ("1:1", "16:9", "3:2", "2:3", "3:4", "4:3", "9:16"),
        "ACCEPTS_IMAGES": False,
    },
    # Image tools (added 2026-11): a source image in, an image out, no prompt.
    # "TOOL" picks the body; image upscale's `scale` rides the resolution picker.
    "imageupscale": {
        "V1_URL": f"{POLLO_GENERATION_BASE}/image-upscale",
        "TOOL": "upscale",
        "VALID_RESOLUTIONS": ("1x", "2x", "4x", "8x", "16x"),
        "MAX_IMAGES": 1,
    },
    "imagebgremove": {
        "V1_URL": f"{POLLO_GENERATION_BASE}/image-background-remove",
        "TOOL": "bgremove",
        "MAX_IMAGES": 1,
    },
}


def img_cfg(model_id: str) -> ImageCfg:
    """Return defaults and model-specific settings for an image model."""
    # The defaults supply every key a row leaves out.
    return cast("ImageCfg", {**_V1_IMAGE_DEFAULTS, **IMAGE_MODELS[model_id]})


def image_model_url(model_id: str) -> str:
    """Return the generation endpoint for an image model."""
    c = img_cfg(model_id)
    return c.get("V1_URL") or f"{POLLO_GENERATION_BASE}/{c.get('PROVIDER', '')}/{c.get('MODEL', '')}/image"


def _tool_payload(c: ImageCfg, image_url: str | None, **kw: JsonValue) -> Payload:
    """An image tool: {image} (+ upscale's integer scale from "2x"-style values)."""
    image = image_url or next(iter(as_str_list(kw.get("images"))), None)
    if not image:
        raise SourceImageRequiredError
    attrs: dict[str, JsonValue] = {"image": image}
    if c.get("TOOL") == "upscale":
        scale = str(kw.get("resolution") or "2x")
        attrs["scale"] = int(scale[:-1]) if scale in c["VALID_RESOLUTIONS"] else 2
    return {"input": attrs}


def _source_images(c: ImageCfg, image_url: str | None, kw: dict[str, JsonValue]) -> list[str]:
    """The reference images to send: none for text-only models, capped at the model's maximum."""
    if not c["ACCEPTS_IMAGES"]:
        return []
    images = ([image_url] if image_url else []) + as_str_list(kw.get("images"))
    return images[: c["MAX_IMAGES"]] if c["MAX_IMAGES"] else images


def image_payload(model_id: str, *, prompt: str, image_url: str | None, **kw: JsonValue) -> Payload:
    """Build the image API request body."""
    c = img_cfg(model_id)
    if c.get("TOOL"):
        return _tool_payload(c, image_url, **kw)
    aspect_ratio = as_str(kw.get("aspect_ratio")) or parse_aspect_ratio(c["DEFAULT_RATIO_KEYWORD"])
    resolution = as_str(kw.get("resolution"))
    images = _source_images(c, image_url, kw)
    # (value, sent only when) — a value of None is never sent
    candidates: dict[str, tuple[JsonValue, bool]] = {
        "aspectRatio": (aspect_ratio, not images or c["ASPECT_RATIO_WITH_IMAGES"]),
        "images": (images or None, True),
        "resolution": (resolution if resolution in c["VALID_RESOLUTIONS"] else None, True),
        "seed": (kw.get("seed") if c["HAS_SEED"] else None, True),
    }
    attrs: dict[str, JsonValue] = {"prompt": prompt}
    attrs.update({k: v for k, (v, allowed) in candidates.items() if v is not None and allowed})
    return {"input": attrs}

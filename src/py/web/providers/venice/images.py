"""Venice image generation, and editing with reference images."""

import base64
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

from web.jsonutil import as_list, as_object, body_of
from web.providers.openrouter import IMAGE_TIMEOUT
from web.providers.venice import client, models
from web.providers.venice.catalogue import image_price
from web.providers.venice.errors import ContentViolationError, EditOnlyModelError, NoImageReturnedError
from web.providers.venice.refs import data_urls
from web.providers.venice.types import ImageSettings, ImageTarget
from web.providers.venice.video import snap

if TYPE_CHECKING:
    from web.types import JsonValue


def _check_violation(resp: httpx.Response) -> None:
    """Reject images Venice marked as content violations.

    The violation flag means the response is not the requested image.
    """
    if (resp.headers.get("x-venice-is-content-violation") or "").lower() == "true":
        raise ContentViolationError


def generate_image(
    model_id: str,
    prompt: str,
    aspect_ratio: str | None = None,
    resolution: str | None = None,
    ref_paths: list[Path] | None = None,
) -> tuple[list[tuple[bytes, str]], float | None, ImageSettings]:
    """Generate an image and return its bytes, cost, and sent settings.

    Reference images use the model's edit twin; otherwise the text-to-image
    model runs.
    """
    info = models.find(models.get_catalogue().image, "image", model_id)
    aspect_ratio = snap(aspect_ratio, info.aspect_ratios)
    resolution = snap(resolution, info.resolutions)
    size: dict[str, str] = {}
    if aspect_ratio:
        size["aspect_ratio"] = aspect_ratio
    if resolution:
        size["resolution"] = resolution
    sent = ImageSettings(aspect_ratio=aspect_ratio, resolution=resolution)
    refs = [p for p in ref_paths or [] if p.is_file()]
    if refs and info.edit:
        refs = refs[: info.max_refs]
        images, cost = _edit_image(info.edit, prompt, refs, size)
        sent["refs_used"] = len(refs)
        return images, cost, sent
    if not info.generate:
        raise EditOnlyModelError
    images, cost = _new_image(info.generate, prompt, size)
    return images, cost, sent


def _edit_image(
    target: ImageTarget, prompt: str, refs: list[Path], size: dict[str, str]
) -> tuple[list[tuple[bytes, str]], float | None]:
    body: dict[str, JsonValue] = {
        "modelId": target.model,
        "prompt": prompt,
        "safe_mode": False,
        "images": data_urls(refs),
        **size,
    }
    resp = client.request(
        client.Call("POST", "/image/multi-edit", body, timeout=IMAGE_TIMEOUT, waiting_for="image"), log=True
    )
    _check_violation(resp)
    media_type = (resp.headers.get("content-type") or "image/png").split(";")[0].strip()
    if not media_type.startswith("image/"):
        raise NoImageReturnedError
    key, pricing, default_res = target.price
    return [(resp.content, media_type)], image_price(pricing, key, size.get("resolution"), default_res)


def _new_image(target: ImageTarget, prompt: str, size: dict[str, str]) -> tuple[list[tuple[bytes, str]], float | None]:
    body: dict[str, JsonValue] = {
        "model": target.model,
        "prompt": prompt,
        "safe_mode": False,
        "hide_watermark": True,
        "format": "png",
        **size,
    }
    resp = client.request(
        client.Call("POST", "/image/generate", body, timeout=IMAGE_TIMEOUT, waiting_for="image"), log=True
    )
    _check_violation(resp)
    encoded = as_list(as_object(body_of(resp)).get("images"))
    images = [(base64.b64decode(b64), "image/png") for b64 in encoded if isinstance(b64, str) and b64]
    if not images:
        raise NoImageReturnedError
    key, pricing, default_res = target.price
    return images, image_price(pricing, key, size.get("resolution"), default_res)

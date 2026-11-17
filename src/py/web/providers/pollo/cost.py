"""Pollo credit estimates, priced from stand-in media so nothing is uploaded."""

import httpx2

from web.auth import keyctx
from web.providers.pollo import catalogue
from web.providers.pollo import estimate as pollo_estimate
from web.providers.pollo.engine import AUDIO_GENERATORS, IMAGE_GENERATORS, VIDEO_GENERATORS
from web.providers.pollo.engine import audio_generator as get_audio_generator
from web.providers.pollo.engine import image_generator as get_image_generator
from web.providers.pollo.engine import video_generator as get_video_generator
from web.providers.pollo.errors import PolloError
from web.providers.pollo.models import MODEL_INFO
from web.providers.specs import CostQuery
from web.types import CreditEstimate


def estimate_cost(model_id: str, query: CostQuery) -> CreditEstimate | None:
    """Return Pollo's credit estimate, or ``None`` when it cannot be priced.

    Estimates are free and use stand-in media URLs, so no files are uploaded.
    """
    kind, aspect_ratio, resolution, n_images = query.kind, query.aspect_ratio, query.resolution, query.n_images
    try:
        if kind == "audio":
            key = catalogue.generator_key(model_id, AUDIO_GENERATORS)
            generator = get_audio_generator(
                key,
                api_key=keyctx.provider_key("pollo"),
                prompt=query.prompt or "estimate",
                voice_ref_url=pollo_estimate.PLACEHOLDERS["audio"],
                **(query.audio or {}),
            )
        elif kind == "image":
            generators = IMAGE_GENERATORS
            key = catalogue.generator_key(model_id, generators)
            generator = get_image_generator(
                key,
                api_key=keyctx.provider_key("pollo"),
                prompt="estimate",
                image_url=None,
                aspect_ratio=aspect_ratio if aspect_ratio in generators[key].VALID_RATIOS else None,
                resolution=resolution,
                images=[pollo_estimate.PLACEHOLDERS["image"]] * n_images or None,
            )
        else:
            key = catalogue.generator_key(model_id, VIDEO_GENERATORS)
            ratios = list(VIDEO_GENERATORS[key].VALID_RATIOS)
            generator = get_video_generator(
                key,
                api_key=keyctx.provider_key("pollo"),
                prompt="estimate",
                image_url=pollo_estimate.PLACEHOLDERS["image"] if n_images else None,
                # source-file models (upscale, tools…) price from stand-in files
                video_url=pollo_estimate.PLACEHOLDERS["video"] if MODEL_INFO.get(key, {}).get("video_input") else None,
                aspect_ratio=aspect_ratio if aspect_ratio in ratios else None,
                resolution=resolution,
                length=query.duration,
                generate_audio=query.generate_audio,
            )
        return pollo_estimate.estimate(generator)
    except (PolloError, ValueError, TypeError, httpx2.HTTPError):  # estimates must not block the composer
        return None

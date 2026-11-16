"""Credit estimates from Pollo's generation endpoints.

The ``.../estimate`` endpoints take the generation body and return a price
without starting a task. Form estimates are cached and use placeholder media
URLs because the price depends on settings, not file contents.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from http import HTTPStatus
from typing import TYPE_CHECKING

import requests

from web.core.cache import MISS, TTLCache
from web.core.cloudflare import is_cloudflare_block
from web.jsonutil import body_of

if TYPE_CHECKING:
    from web.providers.pollo.engine._shared import Payload
    from web.providers.pollo.engine.registry import PolloGenerator
    from web.types import CreditEstimate, JsonValue

log = logging.getLogger(__name__)

# Stand-ins for the request's media: what's priced is that there is an
# image, end frame or reference, not what it shows (Pollo accepts these,
# checked 2026-10-18). Not for an extend's source video: Pollo reads its
# length to price it ("Failed to fetch video duration" otherwise).
PLACEHOLDERS = {
    "image": "https://example.com/estimate.png",
    "video": "https://example.com/estimate.mp4",
    "audio": "https://example.com/estimate.mp3",
}
CACHE_SECONDS = 600
TIMEOUT = 15

# A refusal is cached too (it won't change while the form does), so a cached
# None is a real answer — hence MISS to tell it from a miss.
_cache: TTLCache[str, CreditEstimate | None] = TTLCache(CACHE_SECONDS, maxsize=1024)


def estimate(generator: PolloGenerator) -> CreditEstimate | None:
    """Return the request's estimated and undiscounted credit costs, if known.

    Returns ``None`` if Pollo has no estimate endpoint or cannot be reached.
    """
    url = generator.estimate_url
    if not url:
        return None
    payload = generator.get_payload()
    key = json.dumps([url, payload], sort_keys=True)
    hit = _cache.get(key, MISS)
    if hit is not MISS:
        return hit
    try:
        result, cacheable = _ask(url, payload, generator.api_key)
    except requests.RequestException:
        return None  # not reachable: ask again next time
    if cacheable:
        _cache.put(key, result)
    return result


def clear_cache() -> None:
    """Clear cached estimate responses."""
    _cache.clear()


def _ask(url: str, payload: Payload, api_key: str | None) -> tuple[CreditEstimate | None, bool]:
    """Return the estimate and whether it can be cached.

    Refusals can be cached; server hiccups and Cloudflare blocks cannot.
    """
    headers = {"x-api-key": api_key or "", "Content-Type": "application/json"}
    resp = requests.post(url, data=json.dumps(payload), headers=headers, timeout=TIMEOUT)
    if is_cloudflare_block(resp) or resp.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR:
        return None, False
    if resp.status_code != HTTPStatus.OK:
        log.warning("estimate %s answered HTTP %s: %s", url, resp.status_code, resp.text[:200])
        return None, True
    try:
        body = body_of(resp)
    except ValueError:
        return None, False
    return _credits(body.get("data", body) if isinstance(body, Mapping) else None), True


def _credits(data: JsonValue) -> CreditEstimate | None:
    """Extract discounted and undiscounted credit costs from an estimate.

    ``discountCost`` is used when available; ``totalCost`` is an older name
    for the undiscounted price.
    """
    if not isinstance(data, Mapping):
        return None
    full = _number(data.get("totalCost")) if data.get("totalCost") is not None else _number(data.get("cost"))
    discounted = _number(data.get("discountCost"))
    if discounted is not None:
        return {"credits": discounted, "full_credits": full if full is not None else discounted}
    if full is not None:
        return {"credits": full, "full_credits": full}
    return None


def _number(value: JsonValue) -> int | float | None:
    if not isinstance(value, (int, float, str)):
        return None
    try:
        n = float(value)
    except ValueError:
        return None
    return int(n) if n.is_integer() else round(n, 2)

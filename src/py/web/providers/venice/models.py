"""Venice's model catalogue per user: fetched, paired, priced from quotes, cached, listed."""

import threading
import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import NamedTuple

import httpx2

from web.core.cache import MISS, TTLCache
from web.jsonutil import as_object, as_objects, as_str, body_of
from web.providers.venice import client
from web.providers.venice.catalogue import (
    PREFIX,
    by_price,
    edit_model_for,
    edit_only_entry,
    image_entry,
    price_tag,
    res_rank,
    second_options,
    text_entry,
    usd_or_none,
    video_entry,
    video_family,
)
from web.providers.venice.errors import UnknownModelError, VeniceError
from web.providers.venice.types import (
    Catalogue,
    Entry,
    ImageEntry,
    Model,
    VideoEntry,
    parse_model,
)
from web.types import JsonValue, ModelEntry

CATALOGUE_TTL = 30 * 60


@dataclass(slots=True)
class _CachedCatalogue:
    at: float
    data: Catalogue


# Per tenant: the catalogue is built with the requesting user's key, and the
# balance is that account's (see client.tenant()).
_catalogue: dict[str, _CachedCatalogue] = {}


_catalogue_lock = threading.Lock()


QUOTE_TTL = 24 * 3600


QUOTE_SECONDS = 5  # videos are priced (for sorting) at ~5s, lowest resolution


# (model, duration, resolution) -> USD, or None if unpriced
_quotes: TTLCache[tuple[str, int | None, str | None], float | None] = TTLCache(QUOTE_TTL, maxsize=1024)


def is_venice(model_id: str | None) -> bool:
    """Return whether ``model_id`` belongs to Venice."""
    return bool(model_id and model_id.startswith(PREFIX))


def _fetch_models(kind: str) -> list[Model]:
    """Venice's online models of one kind."""
    data = as_object(body_of(client.request(client.Call("GET", "/models", params={"type": kind})))).get("data")
    return [model for raw in as_objects(data) if (model := parse_model(raw)) is not None]


def _build_catalogue() -> Catalogue:
    text = [text_entry(m) for m in _fetch_models("text")]

    edits = {m.id: m for m in _fetch_models("inpaint")}
    image: list[ImageEntry] = []
    paired: set[str] = set()
    for m in _fetch_models("image"):
        edit_id = edit_model_for(m.id, set(edits))
        edit = edits.get(edit_id) if edit_id else None
        if edit_id:
            paired.add(edit_id)
        image.append(image_entry(m, edit))
    # Edit models with no text-to-image twin: they only work on a reference image
    image.extend(edit_only_entry(m) for edit_id, m in edits.items() if edit_id not in paired)

    # Plain models: pair "…-text-to-video…" with "…-image-to-video…" under
    # one entry. Every other family is listed as it is.
    groups: dict[str, dict[str | None, Model]] = {}
    video: list[VideoEntry] = []
    for m in _fetch_models("video"):
        family = video_family(m)
        if family == "standard":
            key = m.id.replace("text-to-video", "*").replace("image-to-video", "*")
            groups.setdefault(key, {})[as_str(m.constraints.get("model_type"))] = m
        else:
            video.append(video_entry(family, m, m, None))
    for pair in groups.values():
        t2v, i2v = pair.get("text-to-video"), pair.get("image-to-video")
        first = t2v or i2v
        if first is not None:
            video.append(video_entry("standard", first, t2v, i2v))
    _price_videos(video)
    return Catalogue(text=by_price(text), image=by_price(image), video=by_price(video))


class _QuoteJob(NamedTuple):
    entry: VideoEntry
    model: str
    duration: int | None
    resolution: str | None


def _quote_video(job: _QuoteJob) -> float | None:
    """One video's quoted USD price, cached for a day."""
    key = (job.model, job.duration, job.resolution)
    cached = _quotes.get(key, MISS)
    if cached is not MISS:
        return cached
    body: dict[str, JsonValue] = {"model": job.model, "duration": f"{job.duration}s" if job.duration else "auto"}
    if job.resolution:
        body["resolution"] = job.resolution
    try:
        usd = quote_of(client.request(client.Call("POST", "/video/quote", body)))
    except VeniceError:
        usd = None
    _quotes.put(key, usd)
    return usd


def quote_of(resp: httpx2.Response) -> float | None:
    """The USD price in a ``/video/quote`` reply."""
    return usd_or_none(as_object(body_of(resp)).get("quote"))


def _price_videos(video: list[VideoEntry]) -> None:
    """Set video prices from Venice quotes at about five seconds.

    Quotes use each model's lowest resolution and are cached for a day.
    Models that work on a chat video remain unpriced because its duration is
    unknown up front.
    """
    jobs: list[_QuoteJob] = []
    for entry in video:
        target = entry.text or entry.image
        if entry.video_input or target is None:
            entry.public["price"] = None
            continue
        c = target.constraints
        seconds = second_options(c.durations)
        duration = min(seconds, key=lambda d: (abs(d - QUOTE_SECONDS), d)) if seconds else None
        res = min(c.resolutions, key=res_rank, default=None)
        jobs.append(_QuoteJob(entry, target.model, duration, res))

    with ThreadPoolExecutor(max_workers=8) as pool:
        for job, usd in zip(jobs, pool.map(_quote_video, jobs), strict=False):
            basis = " · ".join(x for x in (f"{job.duration}s" if job.duration else "", job.resolution or "") if x)
            job.entry.public["price"] = price_tag(usd, basis)


def get_catalogue(*, refresh: bool = False) -> Catalogue:
    """This user's catalogue, rebuilt when stale or on ``refresh``."""
    key = client.tenant()
    with _catalogue_lock:
        cached = _catalogue.get(key)
        if refresh or not cached or time.time() - cached.at > CATALOGUE_TTL:
            cached = _CachedCatalogue(time.time(), _build_catalogue())
            _catalogue[key] = cached
        return cached.data


def _entries(catalogue: Catalogue, kind: str) -> Sequence[Entry]:
    """The catalogue's entries of one kind (none for a kind Venice doesn't list)."""
    match kind:
        case "text":
            return catalogue.text
        case "image":
            return catalogue.image
        case "video":
            return catalogue.video
        case _:
            return []


def find[E: Entry](entries: Sequence[E], kind: str, model_id: str) -> E:
    """The entry for ``model_id`` (raises VeniceError if it isn't listed)."""
    entry = next((m for m in entries if m.id == model_id), None)
    if entry is None:
        raise UnknownModelError(kind, model_id[len(PREFIX) :])
    return entry


def list_models(kind: str, *, refresh: bool = False) -> list[ModelEntry]:
    """Venice's models of one kind (text | image | video), shaped like openrouter.list_*_models()."""
    if not client.is_configured() or kind not in ("text", "image", "video"):
        return []
    return [dict(m.public) for m in _entries(get_catalogue(refresh=refresh), kind)]


def model_info(kind: str, model_id: str) -> ModelEntry:
    """One model's public catalogue entry (raises VeniceError if unknown)."""
    return dict(find(_entries(get_catalogue(), kind), kind, model_id).public)


def clear() -> None:
    """Forget every user's catalogue and video quotes."""
    with _catalogue_lock:
        _catalogue.clear()
    _quotes.clear()

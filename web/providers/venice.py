"""Venice (https://venice.ai) text, image and video models for chat mode.

Listed in the chat's catalogues as "venice/<model id>" and billed to the
signed-in user's Venice account (their per-user Venice key), alongside OpenRouter's and Pollo's models.

  • text   — POST /chat/completions (OpenAI-compatible, streamed; tools on
             models that support function calling)
  • image  — POST /image/generate, or /image/multi-edit when reference images
             are sent. Venice splits these into separate models
             ("seedream-v5-pro" / "seedream-v5-pro-edit"); one catalogue entry
             covers both and the right one is picked per request.
  • video  — POST /video/queue, then /video/retrieve until the MP4 comes back.
             Text-to-video and image-to-video are separate models too
             ("…-text-to-video…" / "…-image-to-video…"), paired the same way.

Safe mode is always off (Venice blurs adult content otherwise), and Venice's
own system prompt is never added to chats.

Video job ids are "venice:<model>:<queue_id>" — retrieve needs the model.
"""

import base64
import contextlib
import json
import logging
import mimetypes
import os
import re
import shutil
import tempfile
import threading
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

import httpx

from web import keyctx, request_log, sse
from web.caches import on_keys_changed
from web.core.cache import MISS, TTLCache
from web.core.metadata import current_tenant
from web.jsonutil import as_list, as_number, as_object, as_objects, as_str, body_of
from web.providers.openrouter import CHAT_TIMEOUT, IMAGE_TIMEOUT, keepalive_socket_options
from web.providers.venice_errors import (
    AnswerTimeoutError,
    ApiKeyMissingError,
    ConnectionDroppedError,
    ContentViolationError,
    EditOnlyModelError,
    FirstAndLastFrameRequiredError,
    ImageToAnimateRequiredError,
    MotionImageRequiredError,
    NoImageReturnedError,
    NoJobIdError,
    PollDroppedError,
    ReferenceImagesRequiredError,
    RequestRejectedError,
    SourceVideoRequiredError,
    StreamDroppedError,
    TextToVideoOnlyError,
    UnknownModelError,
    VeniceError,
    VideoCheckFailedError,
    VideoDownloadFailedError,
    VideoNotReadyError,
)
from web.providers.venice_types import (
    Catalogue,
    Entry,
    ImageEntry,
    ImageSettings,
    ImageTarget,
    Model,
    PriceSpec,
    TextEntry,
    VideoConstraints,
    VideoEntry,
    VideoTarget,
    max_input_images,
    parse_model,
    strs,
    video_constraints,
)
from web.types import ChatChunk, JsonValue, ModelEntry, VideoJob

log = logging.getLogger(__name__)
VENICE_BASE = os.getenv("VENICE_BASE_URL", "https://api.venice.ai/api/v1").rstrip("/")
PREFIX = "venice/"
JOB_PREFIX = "venice:"
CATALOGUE_TTL = 30 * 60
DEFAULT_TIMEOUT = httpx.Timeout(30)
# Video model families, by what they need from the chat (see _video_family)
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
# Multi-angle models need a camera path; chat uses a slow quarter orbit
DEFAULT_CAMERA_TRAJECTORY: list[dict[str, int]] = [
    {"time": 0, "azimuth": 0, "elevation": 0, "distance": 1},
    {"time": 1, "azimuth": 90, "elevation": 10, "distance": 1},
]


@dataclass(slots=True)
class _CachedCatalogue:
    at: float
    data: Catalogue


_client = httpx.Client(transport=httpx.HTTPTransport(socket_options=keepalive_socket_options()))
# Per tenant: the catalogue is built with the requesting user's key, and the
# balance is that account's (see _tenant()).
_catalogue: dict[str, _CachedCatalogue] = {}
_catalogue_lock = threading.Lock()
_balance: dict[str, float | None] = {}  # tenant -> the x-venice-balance-usd header's last value
# Per-job state the poller needs after submit. A job is followed for minutes,
# not days, so JOB_STATE_TTL is generous; the cap stops a long-lived process
# accumulating an entry per video ever made.
JOB_STATE_TTL = 24 * 3600
_video_quotes: TTLCache[str, float] = TTLCache(JOB_STATE_TTL, maxsize=2048)  # job id -> quoted USD, its cost once done
_download_urls: TTLCache[str, str] = TTLCache(JOB_STATE_TTL, maxsize=2048)  # job id -> download link (private models)
# Finished videos live here between retrieve and download
_VIDEO_DIR = Path(tempfile.gettempdir()) / "venice-videos"
QUOTE_TTL = 24 * 3600
QUOTE_SECONDS = 5  # videos are priced (for sorting) at ~5s, lowest resolution
# (model, duration, resolution) -> USD, or None if unpriced
_quotes: TTLCache[tuple[str, int | None, str | None], float | None] = TTLCache(QUOTE_TTL, maxsize=1024)


def get_api_key() -> str:
    """Return the configured Venice API key, or an empty string."""
    return keyctx.provider_key("venice") or ""


def _tenant() -> str:
    """Return the signed-in user that owns the per-account caches.

    Outside a request, return an empty string; background pollers use the
    owner's key for each job.
    """
    return current_tenant() or ""


def is_configured() -> bool:
    """Return whether a Venice API key is configured."""
    return bool(get_api_key())


NAME: str = "venice"


def is_venice(model_id: str | None) -> bool:
    """Return whether ``model_id`` belongs to Venice."""
    return bool(model_id and model_id.startswith(PREFIX))


def is_venice_job(job_id: str | None) -> bool:
    """Return whether ``job_id`` belongs to Venice."""
    return bool(job_id and job_id.startswith(JOB_PREFIX))


def _headers() -> dict[str, str]:
    key = get_api_key()
    if not key:
        raise ApiKeyMissingError
    return {"Authorization": f"Bearer {key}"}


def _note_balance(resp: httpx.Response) -> None:
    value: str = resp.headers.get("x-venice-balance-usd") or ""
    if value:
        with contextlib.suppress(ValueError):
            _balance[_tenant()] = float(value)


def _error_message(resp: httpx.Response) -> str | None:
    """Venice's own explanation of an error reply, if it gave one."""
    try:
        body = body_of(resp)
    except ValueError:
        return resp.text[:500]
    if not isinstance(body, Mapping):
        return resp.text[:500]
    err = body.get("error") or body.get("message") or body
    message = as_str(err.get("message")) if isinstance(err, Mapping) else str(err)
    details = body.get("details")
    if details and isinstance(details, (Mapping, list)):
        message = f"{message}: {json.dumps(details)[:300]}"
    return message


def _raise_for_response(resp: httpx.Response) -> None:
    _note_balance(resp)
    if resp.status_code < 400:
        return
    raise RequestRejectedError(_error_message(resp), resp.status_code)


def _request(
    method: str,
    path: str,
    *,
    timeout: httpx.Timeout = DEFAULT_TIMEOUT,
    waiting_for: str = "response",
    log: bool = False,
    json_body: JsonValue = None,
    params: dict[str, str] | None = None,
) -> httpx.Response:
    """One Venice call. `log`: record it in the request log (web/request_log.py)."""
    if not log:
        return _send(method, path, timeout, waiting_for, json_body=json_body, params=params)
    with request_log.logged("venice", method, path, json_body) as outcome:
        resp = _send(method, path, timeout, waiting_for, check=False, json_body=json_body, params=params)
        outcome["status"] = resp.status_code
        outcome["flags"] = {k: v for k, v in resp.headers.items() if k.startswith("x-venice-is-")}
        outcome["response"] = request_log.response_of(resp)
        _raise_for_response(resp)
    return resp


def _send(
    method: str,
    path: str,
    timeout: httpx.Timeout,
    waiting_for: str,
    check: bool = True,
    json_body: JsonValue = None,
    params: dict[str, str] | None = None,
) -> httpx.Response:
    start = time.monotonic()
    try:
        resp = _client.request(
            method, f"{VENICE_BASE}{path}", headers=_headers(), timeout=timeout, json=json_body, params=params
        )
    except (httpx.RemoteProtocolError, httpx.ReadError, httpx.WriteError, httpx.ConnectError) as e:
        raise ConnectionDroppedError(round(time.monotonic() - start), waiting_for, e) from e
    except httpx.TimeoutException as e:
        raise AnswerTimeoutError(e) from e
    if check:  # else the caller checks, after logging the response
        _raise_for_response(resp)
    return resp


def _data_url(path: Path) -> str:
    media_type = mimetypes.guess_type(path.name)[0] or "image/png"
    return f"data:{media_type};base64,{base64.b64encode(path.read_bytes()).decode()}"


def _fetch_models(kind: str) -> list[Model]:
    """Venice's online models of one kind."""
    data = as_object(body_of(_request("GET", "/models", params={"type": kind}))).get("data")
    return [model for raw in as_objects(data) if (model := parse_model(raw)) is not None]


def _float(value: JsonValue) -> float | None:
    """The value as a float when it is a number or numeric text, else None."""
    if isinstance(value, (int, float, str)):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _usd(price: JsonValue) -> float | None:
    """A price as USD: a plain number, numeric text, or an object with a ``usd`` field."""
    if isinstance(price, Mapping):
        price = price.get("usd")
    return _float(price)


def _seconds(values: list[str]) -> list[int]:
    out: list[int] = []
    for v in values:
        with contextlib.suppress(ValueError):  # "auto", "1 gen" — not a length chat can ask for
            out.append(int(v.lower().rstrip("s")))
    return sorted(set(out))


def _uncensored(*models: Model | None) -> bool | None:
    """Venice's own "uncensored" flag on a model (on any of a pair)."""
    return any(m.uncensored for m in models if m) or None


def _privacy(*models: Model | None) -> str | None:
    """Return the least-private level across a model pair.

    Venice reports ``private`` for its own servers and ``anonymized`` for
    third-party providers that receive requests without user identity.
    """
    levels = {m.privacy for m in models if m} - {None}
    return "anonymized" if "anonymized" in levels else ("private" if levels else None)


def _edit_model_for(image_id: str, edit_ids: set[str]) -> str | None:
    """Find an image model's edit twin among the available inpaint models.

    The match may drop ``-image`` before adding ``-edit``.
    """
    for candidate in (f"{image_id}-edit", image_id.replace("-image", "", 1) + "-edit"):
        if candidate in edit_ids:
            return candidate
    return None


def _text_entry(m: Model) -> TextEntry:
    caps = m.capabilities
    prompt_usd, completion_usd = _usd(m.pricing.get("input")), _usd(m.pricing.get("output"))
    # Venice prices per million tokens; the picker expects per token
    prompt_price = prompt_usd / 1e6 if prompt_usd is not None else None
    completion_price = completion_usd / 1e6 if completion_usd is not None else None
    public: ModelEntry = {
        "id": PREFIX + m.id,
        "name": f"Venice: {m.name}",
        "context_length": m.context_length,
        "input_modalities": ["text", "image"] if caps.get("supportsVision") else ["text"],
        "supports_tools": bool(caps.get("supportsFunctionCalling")),
        "uncensored": _uncensored(m),
        "privacy": _privacy(m),
        "prompt_price": prompt_price,
        "completion_price": completion_price,
        "created": m.created,
        "price": _price_tag(completion_price * 1e6, "per 1M output tokens") if completion_price is not None else None,
    }
    return TextEntry(PREFIX + m.id, public, prompt_price, completion_price)


def _image_entry(m: Model, edit: Model | None) -> ImageEntry:
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
        "uncensored": _uncensored(m, edit),
        "privacy": _privacy(m, edit),
        "aspect_ratios": aspect_ratios,
        "resolutions": resolutions,
        "created": m.created,
        "conversational": False,
        # Reference images its edit twin takes (one when Venice doesn't say)
        "max_refs": max_refs if edit else None,
        "price": _price_tag(_image_price(m.pricing, "generation", None, default_res), default_res),
    }
    return ImageEntry(PREFIX + m.id, public, generate, edit_target, max_refs, aspect_ratios or [], resolutions or [])


def _edit_only_entry(m: Model) -> ImageEntry:
    """An edit model with no text-to-image twin: it only works on a reference image."""
    c = m.constraints
    default_res = as_str(c.get("defaultResolution"))
    max_refs = max_input_images(c)
    aspect_ratios, resolutions = strs(c.get("aspectRatios")), strs(c.get("resolutions"))
    public: ModelEntry = {
        "id": PREFIX + m.id,
        "name": f"Venice: {m.name} (edit only)",
        "input_modalities": ["text", "image"],
        "uncensored": _uncensored(m),
        "privacy": _privacy(m),
        "aspect_ratios": aspect_ratios,
        "resolutions": resolutions,
        "created": m.created,
        "conversational": False,
        "max_refs": max_refs,
        "price": _price_tag(_image_price(m.pricing, "inpaint", None, default_res), default_res),
    }
    edit_target = ImageTarget(m.id, PriceSpec("inpaint", m.pricing, default_res))
    return ImageEntry(PREFIX + m.id, public, None, edit_target, max_refs, aspect_ratios or [], resolutions or [])


def _build_catalogue() -> Catalogue:
    text = [_text_entry(m) for m in _fetch_models("text")]

    edits = {m.id: m for m in _fetch_models("inpaint")}
    image: list[ImageEntry] = []
    paired: set[str] = set()
    for m in _fetch_models("image"):
        edit_id = _edit_model_for(m.id, set(edits))
        edit = edits.get(edit_id) if edit_id else None
        if edit_id:
            paired.add(edit_id)
        image.append(_image_entry(m, edit))
    # Edit models with no text-to-image twin: they only work on a reference image
    image.extend(_edit_only_entry(m) for edit_id, m in edits.items() if edit_id not in paired)

    # Plain models: pair "…-text-to-video…" with "…-image-to-video…" under
    # one entry. Every other family is listed as it is.
    groups: dict[str, dict[str | None, Model]] = {}
    video: list[VideoEntry] = []
    for m in _fetch_models("video"):
        family = _video_family(m)
        if family == "standard":
            key = m.id.replace("text-to-video", "*").replace("image-to-video", "*")
            groups.setdefault(key, {})[as_str(m.constraints.get("model_type"))] = m
        else:
            video.append(_video_entry(family, m, m, None))
    for pair in groups.values():
        t2v, i2v = pair.get("text-to-video"), pair.get("image-to-video")
        first = t2v or i2v
        if first is not None:
            video.append(_video_entry("standard", first, t2v, i2v))
    _price_videos(video)
    return Catalogue(text=_by_price(text), image=_by_price(image), video=_by_price(video))


def _by_price[E: Entry](models: list[E]) -> list[E]:
    """Uncensored first (as the user asked), then cheapest first; unpriced last."""

    def key(m: E) -> tuple[bool, bool, int | float, str]:
        usd = as_number(as_object(m.public.get("price")).get("usd"))
        return (not m.public.get("uncensored"), usd is None, usd or 0, (as_str(m.public.get("name")) or "").lower())

    return sorted(models, key=key)


def _price_tag(usd: float | None, basis: str | None = None) -> dict[str, JsonValue] | None:
    return {"usd": round(usd, 4), "basis": basis or ""} if usd is not None else None


def _image_price(
    pricing: dict[str, JsonValue], key: str, resolution: str | None, default_res: str | None
) -> float | None:
    """One image's USD price: the resolution's tier if priced that way, else the flat price."""
    tiers = as_object(pricing.get("resolutions"))
    for res in (resolution, None, default_res):
        if res is None:
            flat = _usd(pricing.get(key))
            if flat is not None:
                return flat
        elif res in tiers:
            tier = _usd(tiers[res])
            if tier is not None:
                return tier
    prices = [p for p in (_usd(v) for v in tiers.values()) if p is not None]
    return min(prices) if prices else None


def _res_rank(res: str) -> int:
    """Rough vertical pixels, to find a model's lowest resolution ("480p", "768P", "2K", "4k")."""
    s = res.lower()
    if m := re.match(r"(\d+)p", s):
        return int(m.group(1))
    return {"1k": 1080, "2k": 1440, "4k": 2160}.get(s, 10_000)


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
        usd = _quote_of(_request("POST", "/video/quote", json_body=body))
    except VeniceError:
        usd = None
    _quotes.put(key, usd)
    return usd


def _quote_of(resp: httpx.Response) -> float | None:
    """The USD price in a ``/video/quote`` reply."""
    return _usd(as_object(body_of(resp)).get("quote"))


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
        seconds = _seconds(c.durations)
        duration = min(seconds, key=lambda d: (abs(d - QUOTE_SECONDS), d)) if seconds else None
        res = min(c.resolutions, key=_res_rank, default=None)
        jobs.append(_QuoteJob(entry, target.model, duration, res))

    with ThreadPoolExecutor(max_workers=8) as pool:
        for job, usd in zip(jobs, pool.map(_quote_video, jobs), strict=False):
            basis = " · ".join(x for x in (f"{job.duration}s" if job.duration else "", job.resolution or "") if x)
            job.entry.public["price"] = _price_tag(usd, basis)


def _video_family(m: Model) -> str:
    mtype = as_str(m.constraints.get("model_type"))
    if "reference-to-video" in m.id:
        return "reference"
    if "first-last-frame" in m.id or "transition" in m.id:
        return "frames"
    if "multi-angle" in m.id:
        return "angles"
    if "upscale" in m.id:
        return "upscale"
    if "motion-control" in m.id:
        return "motion"
    if mtype == "video":
        return "video"
    return "standard"


def _video_entry(family: str, first: Model, main: Model | None, i2v: Model | None) -> VideoEntry:
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
        "durations": _seconds(c.durations) or None,
        "resolutions": c.resolutions or None,
        "aspect_ratios": c.aspect_ratios or None,
        "frame_images": frames,
        "reference_images": family == "reference",
        "video_input": video_input,
        "uncensored": _uncensored(main, i2v),
        "privacy": _privacy(main, i2v),
        "generate_audio": c.audio_configurable,
        "created": first.created,
    }
    if family == "standard":
        text = VideoTarget(main.id, video_constraints(main.constraints)) if main else None
        image = VideoTarget(i2v.id, video_constraints(i2v.constraints)) if i2v else None
    else:
        text, image = None, VideoTarget(first.id, c)
    return VideoEntry(PREFIX + first.id, public, family, video_input, text, image)


def _get_catalogue(refresh: bool = False) -> Catalogue:
    key = _tenant()
    with _catalogue_lock:
        cached = _catalogue.get(key)
        if refresh or not cached or time.time() - cached.at > CATALOGUE_TTL:
            cached = _CachedCatalogue(time.time(), _build_catalogue())
            _catalogue[key] = cached
        return cached.data


@on_keys_changed
def clear_caches() -> None:
    """Clear catalogue, quote, balance, and job-state caches.

    Called when a user's keys change and by tests between cases.
    """
    with _catalogue_lock:
        _catalogue.clear()
    _quotes.clear()
    _video_quotes.clear()
    _download_urls.clear()
    _balance.clear()


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


def _find[E: Entry](entries: Sequence[E], kind: str, model_id: str) -> E:
    entry = next((m for m in entries if m.id == model_id), None)
    if entry is None:
        raise UnknownModelError(kind, model_id[len(PREFIX) :])
    return entry


def list_models(kind: str, refresh: bool = False) -> list[ModelEntry]:
    """Venice's models of one kind (text | image | video), shaped like openrouter.list_*_models()."""
    if not is_configured() or kind not in ("text", "image", "video"):
        return []
    return [dict(m.public) for m in _entries(_get_catalogue(refresh), kind)]


def model_info(kind: str, model_id: str) -> ModelEntry:
    """One model's public catalogue entry (raises VeniceError if unknown)."""
    return dict(_find(_entries(_get_catalogue(), kind), kind, model_id).public)


def get_balances() -> dict[str, float | None]:
    """Return the account's USD balance and bundled credits.

    Both values come from one rate-limits call. Venice spends BUNDLED_CREDITS
    after DIEM and before USD. The admin-only /billing/balance endpoint is not
    used; the USD figure
    lives in the body — not a response header, despite older API versions. If the
    endpoint can't be read, fall back to the balance a prior response's header
    reported for THIS user (via _note_balance) — never another account's.
    """
    key = _tenant()
    try:
        data = as_object(body_of(_request("GET", "/api_keys/rate_limits")))
    except VeniceError:
        return {"usd": _balance.get(key), "credits": None}
    balances = as_object(as_object(data.get("data") or data).get("balances"))
    usd = _float(balances.get("USD"))
    if usd is not None:
        _balance[key] = usd
    return {"usd": _balance.get(key), "credits": _float(balances.get("BUNDLED_CREDITS"))}


def stream_chat(
    model_id: str,
    messages: list[dict[str, JsonValue]],
    tools: list[dict[str, JsonValue]] | None = None,
    session_id: str | None = None,
    max_seconds: float | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> Iterator[ChatChunk]:
    """Yield chat-completion chunks with usage cost in USD.

    Cost comes from Venice's reported value or token counts and model prices.
    Venice has no session concept, so ``session_id`` only labels the request in the debug log.
    """
    log.debug("venice chat %s (session %s)", model_id, session_id)
    body: dict[str, JsonValue] = {
        "model": model_id[len(PREFIX) :],
        "messages": messages,
        "stream": True,
        "stream_options": {"include_usage": True},
        "venice_parameters": {"include_venice_system_prompt": False},
    }
    if tools:
        body["tools"] = tools
    start = time.monotonic()
    try:
        with (
            request_log.logged("venice", "POST", "/chat/completions", body) as outcome,
            _client.stream(
                "POST", f"{VENICE_BASE}/chat/completions", headers=_headers(), json=body, timeout=CHAT_TIMEOUT
            ) as resp,
        ):
            outcome["status"] = resp.status_code
            if resp.status_code >= 400:
                resp.read()
                outcome["response"] = request_log.response_of(resp)
            _raise_for_response(resp)
            chunks = sse.chat_chunks(resp.iter_lines(), _stream_error, max_seconds, should_stop)
            for chunk in request_log.chat_reply(chunks, outcome):
                usage = chunk.get("usage")
                if usage:
                    chunk["usage"] = {**usage, "cost": _chat_cost(model_id, usage, as_object(chunk).get("cost"))}
                yield chunk
    except (httpx.RemoteProtocolError, httpx.ReadError, httpx.WriteError) as e:
        raise StreamDroppedError(round(time.monotonic() - start), e) from e


def _stream_error(message: str, status: int | None) -> VeniceError:
    """A stream failure: the time cap as it is, an error chunk labelled as Venice's."""
    return VeniceError(message if status else f"Venice: {message}", status)


def _chat_cost(model_id: str, usage: dict[str, JsonValue], top_level_cost: JsonValue = None) -> float | None:
    cost = _usd(usage.get("cost")) if usage.get("cost") is not None else _usd(top_level_cost)
    if cost is not None:
        return cost
    try:
        info = _find(_get_catalogue().text, "text", model_id)
    except VeniceError:
        return None
    if info.prompt_price is None or info.completion_price is None:
        return None
    return round(
        (as_number(usage.get("prompt_tokens")) or 0) * info.prompt_price
        + (as_number(usage.get("completion_tokens")) or 0) * info.completion_price,
        6,
    )


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
    info = _find(_get_catalogue().image, "image", model_id)
    aspect_ratio = _snap(aspect_ratio, info.aspect_ratios)
    resolution = _snap(resolution, info.resolutions)
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
        "images": [_data_url(p) for p in refs],
        **size,
    }
    resp = _request("POST", "/image/multi-edit", json_body=body, timeout=IMAGE_TIMEOUT, waiting_for="image", log=True)
    _check_violation(resp)
    media_type = (resp.headers.get("content-type") or "image/png").split(";")[0].strip()
    if not media_type.startswith("image/"):
        raise NoImageReturnedError
    key, pricing, default_res = target.price
    return [(resp.content, media_type)], _image_price(pricing, key, size.get("resolution"), default_res)


def _new_image(target: ImageTarget, prompt: str, size: dict[str, str]) -> tuple[list[tuple[bytes, str]], float | None]:
    body: dict[str, JsonValue] = {
        "model": target.model,
        "prompt": prompt,
        "safe_mode": False,
        "hide_watermark": True,
        "format": "png",
        **size,
    }
    resp = _request("POST", "/image/generate", json_body=body, timeout=IMAGE_TIMEOUT, waiting_for="image", log=True)
    _check_violation(resp)
    encoded = as_list(as_object(body_of(resp)).get("images"))
    images = [(base64.b64decode(b64), "image/png") for b64 in encoded if isinstance(b64, str) and b64]
    if not images:
        raise NoImageReturnedError
    key, pricing, default_res = target.price
    return images, _image_price(pricing, key, size.get("resolution"), default_res)


MAX_VIDEO_REFS = 30
QUOTED_FIELDS = ("model", "duration", "aspect_ratio", "resolution", "audio", "upscale_factor")


def _snap(value: str | None, allowed: list[str]) -> str | None:
    """Value if allowed (or nothing is known), else None."""
    return value if value and (not allowed or value in allowed) else None


def submit_video(
    model_id: str,
    prompt: str,
    duration: int | None = None,
    aspect_ratio: str | None = None,
    resolution: str | None = None,
    generate_audio: bool | None = None,
    first_frame: Path | None = None,
    last_frame: Path | None = None,
    refs: list[Path] | None = None,
    source_video: Path | None = None,
) -> VideoJob:
    """Queue a video and return its id and sent settings.

    Reference models take ``refs`` (the first frame joins them if empty),
    first/last-frame models take both frames, and video models take
    ``source_video`` (motion control also takes an image).
    """
    info = _find(_get_catalogue().video, "video", model_id)
    family = info.family
    target = _video_model(info, first_frame)
    c = target.constraints
    frames = _VideoFrames(first_frame, last_frame, [p for p in refs or [] if p.is_file()], source_video)
    inputs, sent, image_used = _VIDEO_INPUTS.get(family, _standard_inputs)(frames)
    body: dict[str, JsonValue] = {"model": target.model, "prompt": prompt, **inputs}
    if family == "angles":
        body["camera_trajectory"] = DEFAULT_CAMERA_TRAJECTORY

    duration, body["duration"] = _video_duration(c, duration)
    resolution = _video_resolution(body, family, c, resolution)
    aspect_ratio = _snap(aspect_ratio, c.aspect_ratios)
    if image_used and not c.aspect_ratios:
        aspect_ratio = None  # the image sets the shape
    if aspect_ratio:
        body["aspect_ratio"] = aspect_ratio
    if c.audio_configurable and generate_audio is not None:
        body["audio"] = generate_audio

    quote = _video_quote(body)
    data = as_object(
        body_of(
            _request(
                "POST",
                "/video/queue",
                json_body=body,
                timeout=IMAGE_TIMEOUT,
                waiting_for="video job to start",
                log=True,
            )
        )
    )
    queue_id = data.get("queue_id")
    if not queue_id:
        raise NoJobIdError
    job_id = f"{JOB_PREFIX}{target.model}:{queue_id}"
    download_url = as_str(data.get("download_url"))
    if download_url:
        _download_urls.put(job_id, download_url)
    if quote is not None:
        _video_quotes.put(job_id, quote)
    audio = body.get("audio", c.audio or None)
    return {
        "id": job_id,
        "params": {
            "duration": duration,
            "aspect_ratio": aspect_ratio,
            "resolution": resolution,
            "generate_audio": audio,
            **sent,
        },
    }


def _video_model(info: VideoEntry, first_frame: Path | None) -> VideoTarget:
    """Select the Venice model and constraints for a video family.

    Standard families pair text-to-video with image-to-video; others use one
    model.
    """
    target = info.image if info.family != "standard" or first_frame else info.text
    if target is None:
        raise TextToVideoOnlyError if first_frame else ImageToAnimateRequiredError
    return target


@dataclass(frozen=True, slots=True)
class _VideoFrames:
    """The media the chat has on hand for a video request."""

    first: Path | None
    last: Path | None
    refs: list[Path]
    source_video: Path | None


# Each family's inputs: (body fields, settings to report, whether an image sets the shape)
VideoInputs = tuple[dict[str, JsonValue], dict[str, JsonValue], bool]


def _reference_inputs(f: _VideoFrames) -> VideoInputs:
    refs = (f.refs or ([f.first] if f.first else []))[:MAX_VIDEO_REFS]
    if not refs:
        raise ReferenceImagesRequiredError
    return {"reference_image_urls": [_data_url(p) for p in refs]}, {"refs_used": len(refs)}, False


def _frames_inputs(f: _VideoFrames) -> VideoInputs:
    if not (f.first and f.last):
        raise FirstAndLastFrameRequiredError
    return {"image_url": _data_url(f.first), "end_image_url": _data_url(f.last)}, {}, True


def _source_video_inputs(f: _VideoFrames) -> VideoInputs:
    if not f.source_video or not f.source_video.is_file():
        raise SourceVideoRequiredError
    return {"video_url": _data_url(f.source_video)}, {"source_video": f.source_video.name}, False


def _motion_inputs(f: _VideoFrames) -> VideoInputs:
    body, sent, _ = _source_video_inputs(f)
    image = f.first or (f.refs[0] if f.refs else None)
    if not image:
        raise MotionImageRequiredError
    return {**body, "image_url": _data_url(image)}, sent, True


def _standard_inputs(f: _VideoFrames) -> VideoInputs:
    """Standard image→video and multi-angle: the first frame, if any."""
    return ({"image_url": _data_url(f.first)}, {}, True) if f.first else ({}, {}, False)


_VIDEO_INPUTS: dict[str, Callable[[_VideoFrames], VideoInputs]] = {
    "reference": _reference_inputs,
    "frames": _frames_inputs,
    "video": _source_video_inputs,
    "upscale": _source_video_inputs,
    "motion": _motion_inputs,
}


def _video_duration(c: VideoConstraints, duration: int | None) -> tuple[int | None, str]:
    """Return the selected duration and its API representation.

    The requested value snaps to the nearest allowed length; unset values
    default to five seconds when supported.
    """
    allowed = c.durations
    seconds = _seconds(allowed)
    if not seconds:
        return None, allowed[0] if allowed else "auto"  # e.g. "Auto": follows the source video
    if not duration or duration not in seconds:
        target = duration or 5
        duration = min(seconds, key=lambda d: (abs(d - target), d))
    return duration, f"{duration}s"


def _video_resolution(
    body: dict[str, JsonValue], family: str, c: VideoConstraints, resolution: str | None
) -> str | None:
    """Put the resolution (an upscale's factor) on the body; the setting to report."""
    if family == "upscale":
        factor = {"2x": 2, "4x": 4}.get(str(resolution).lower()) or 2
        body["upscale_factor"] = factor
        return f"{factor}x"
    resolution = _snap(resolution, c.resolutions)
    if resolution:
        body["resolution"] = resolution
    return resolution


def _video_quote(body: dict[str, JsonValue]) -> float | None:
    """What Venice says the video will cost — nice to show, not needed to generate."""
    try:
        return _quote_of(
            _request("POST", "/video/quote", json_body={k: v for k, v in body.items() if k in QUOTED_FIELDS})
        )
    except VeniceError:
        return None


def _split_job(job_id: str) -> tuple[str, str]:
    model, _, queue_id = job_id[len(JOB_PREFIX) :].rpartition(":")
    return model, queue_id


def _video_file(job_id: str) -> Path:
    return _VIDEO_DIR / f"{_split_job(job_id)[1]}.mp4"


def _completed(job_id: str) -> dict[str, JsonValue]:
    """The poll result for a finished job, with its quoted cost."""
    return {"status": "completed", "usage": {"cost": _video_quotes.get(job_id)}}


def get_video(job_id: str) -> dict[str, JsonValue]:
    """Return Venice job status in OpenRouter's shape.

    The finished MP4 is held until ``download_video`` collects it.
    Network trouble and 5xx raise, for the poller's error budget.
    """
    if _video_file(job_id).is_file():
        return _completed(job_id)
    model, queue_id = _split_job(job_id)
    start = time.monotonic()
    try:
        with _client.stream(
            "POST",
            f"{VENICE_BASE}/video/retrieve",
            headers=_headers(),
            json={"model": model, "queue_id": queue_id},
            timeout=IMAGE_TIMEOUT,
        ) as resp:
            if resp.status_code >= 500 or resp.status_code == 429:
                resp.read()
                raise VideoCheckFailedError(resp.status_code)
            if resp.status_code >= 400:
                resp.read()
                try:
                    _raise_for_response(resp)
                except VeniceError as e:
                    return {"status": "failed", "error": str(e)}
            if (resp.headers.get("content-type") or "").startswith("video/"):
                _VIDEO_DIR.mkdir(parents=True, exist_ok=True)
                part = _video_file(job_id).with_suffix(".part")
                with part.open("wb") as f:
                    f.writelines(resp.iter_bytes())
                part.replace(_video_file(job_id))
                return _completed(job_id)
            resp.read()
            _note_balance(resp)
            data = as_object(body_of(resp))
    except (httpx.RemoteProtocolError, httpx.ReadError, httpx.WriteError, httpx.ConnectError) as e:
        raise PollDroppedError(round(time.monotonic() - start), e) from e
    status = str(data.get("status") or "").upper()
    if status in ("FAILED", "ERROR", "CANCELLED"):
        return {"status": "failed", "error": f"Venice: {data.get('error') or data.get('message') or 'video failed'}"}
    if status == "COMPLETED" and _download_urls.get(job_id) is not None:
        return _completed(job_id)
    return {"status": "in_progress"}


def download_video(job_id: str, dest: Path) -> None:
    """Copy a completed Venice video to ``dest``."""
    src = _video_file(job_id)
    if not src.is_file():
        url = _download_urls.get(job_id)
        if url:  # private models hand back a short-lived download link instead
            tmp = dest.with_suffix(dest.suffix + ".part")
            with _client.stream("GET", url, timeout=IMAGE_TIMEOUT, follow_redirects=True) as resp:
                if resp.status_code >= 400:
                    resp.read()
                    raise VideoDownloadFailedError(resp.status_code)
                with tmp.open("wb") as f:
                    f.writelines(resp.iter_bytes())
            tmp.replace(dest)
            return
        if get_video(job_id)["status"] != "completed" or not src.is_file():
            raise VideoNotReadyError
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(src, dest)  # the temp dir may be on another filesystem

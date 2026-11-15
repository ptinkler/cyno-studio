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
import os
import shutil
import tempfile
import threading
import time
from collections.abc import Iterator, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from http import HTTPStatus
from pathlib import Path
from typing import NamedTuple

import httpx

from web.auth import keyctx
from web.core import request_log, sse
from web.core.cache import MISS, TTLCache
from web.core.key_caches import on_keys_changed
from web.core.metadata import current_tenant
from web.jsonutil import as_list, as_number, as_object, as_objects, as_str, body_of
from web.providers.openrouter import CHAT_TIMEOUT, IMAGE_TIMEOUT, keepalive_socket_options
from web.providers.specs import StreamOptions, VideoRequest
from web.providers.venice_catalogue import (
    PREFIX,
    by_price,
    edit_model_for,
    edit_only_entry,
    float_or_none,
    image_entry,
    image_price,
    price_tag,
    res_rank,
    second_options,
    text_entry,
    usd_or_none,
    video_entry,
    video_family,
)
from web.providers.venice_errors import (
    AnswerTimeoutError,
    ApiKeyMissingError,
    ConnectionDroppedError,
    ContentViolationError,
    EditOnlyModelError,
    NoImageReturnedError,
    NoJobIdError,
    PollDroppedError,
    RequestRejectedError,
    StreamDroppedError,
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
    VideoEntry,
    parse_model,
)
from web.providers.venice_video import (
    DEFAULT_CAMERA_TRAJECTORY,
    VIDEO_INPUTS,
    VideoFrames,
    data_url,
    snap,
    standard_inputs,
    video_aspect_ratio,
    video_duration,
    video_model,
    video_resolution,
)
from web.types import ChatChunk, JsonValue, ModelEntry, VideoJob

log = logging.getLogger(__name__)
VENICE_BASE = os.getenv("VENICE_BASE_URL", "https://api.venice.ai/api/v1").rstrip("/")
JOB_PREFIX = "venice:"
CATALOGUE_TTL = 30 * 60
DEFAULT_TIMEOUT = httpx.Timeout(30)


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
    if resp.status_code < HTTPStatus.BAD_REQUEST:
        return
    raise RequestRejectedError(_error_message(resp), resp.status_code)


@dataclass(frozen=True)
class _Call:
    """One Venice API call: what is sent, how long to wait, and what the wait is for (named in the error)."""

    method: str
    path: str
    json_body: JsonValue = None
    params: dict[str, str] | None = None
    timeout: httpx.Timeout = field(default_factory=lambda: DEFAULT_TIMEOUT)  # Timeout is unhashable
    waiting_for: str = "response"


def _request(call: _Call, *, log: bool = False) -> httpx.Response:
    """One Venice call. `log`: record it in the request log (web/core/request_log.py)."""
    if not log:
        return _send(call)
    with request_log.logged("venice", call.method, call.path, call.json_body) as outcome:
        resp = _send(call, check=False)
        outcome["status"] = resp.status_code
        outcome["flags"] = {k: v for k, v in resp.headers.items() if k.startswith("x-venice-is-")}
        outcome["response"] = request_log.response_of(resp)
        _raise_for_response(resp)
    return resp


def _send(call: _Call, *, check: bool = True) -> httpx.Response:
    start = time.monotonic()
    try:
        resp = _client.request(
            call.method,
            f"{VENICE_BASE}{call.path}",
            headers=_headers(),
            timeout=call.timeout,
            json=call.json_body,
            params=call.params,
        )
    except (httpx.RemoteProtocolError, httpx.ReadError, httpx.WriteError, httpx.ConnectError) as e:
        raise ConnectionDroppedError(round(time.monotonic() - start), call.waiting_for, e) from e
    except httpx.TimeoutException as e:
        raise AnswerTimeoutError(e) from e
    if check:  # else the caller checks, after logging the response
        _raise_for_response(resp)
    return resp


def _fetch_models(kind: str) -> list[Model]:
    """Venice's online models of one kind."""
    data = as_object(body_of(_request(_Call("GET", "/models", params={"type": kind})))).get("data")
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
        usd = _quote_of(_request(_Call("POST", "/video/quote", body)))
    except VeniceError:
        usd = None
    _quotes.put(key, usd)
    return usd


def _quote_of(resp: httpx.Response) -> float | None:
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


def _get_catalogue(*, refresh: bool = False) -> Catalogue:
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


def list_models(kind: str, *, refresh: bool = False) -> list[ModelEntry]:
    """Venice's models of one kind (text | image | video), shaped like openrouter.list_*_models()."""
    if not is_configured() or kind not in ("text", "image", "video"):
        return []
    return [dict(m.public) for m in _entries(_get_catalogue(refresh=refresh), kind)]


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
        data = as_object(body_of(_request(_Call("GET", "/api_keys/rate_limits"))))
    except VeniceError:
        return {"usd": _balance.get(key), "credits": None}
    balances = as_object(as_object(data.get("data") or data).get("balances"))
    usd = float_or_none(balances.get("USD"))
    if usd is not None:
        _balance[key] = usd
    return {"usd": _balance.get(key), "credits": float_or_none(balances.get("BUNDLED_CREDITS"))}


def stream_chat(
    model_id: str, messages: list[dict[str, JsonValue]], options: StreamOptions | None = None
) -> Iterator[ChatChunk]:
    """Yield chat-completion chunks with usage cost in USD.

    Cost comes from Venice's reported value or token counts and model prices.
    Venice has no session concept, so ``session_id`` only labels the request in the debug log.
    """
    options = options or StreamOptions()
    log.debug("venice chat %s (session %s)", model_id, options.session_id)
    body: dict[str, JsonValue] = {
        "model": model_id[len(PREFIX) :],
        "messages": messages,
        "stream": True,
        "stream_options": {"include_usage": True},
        "venice_parameters": {"include_venice_system_prompt": False},
    }
    if options.tools:
        body["tools"] = options.tools
    start = time.monotonic()
    try:
        with (
            request_log.logged("venice", "POST", "/chat/completions", body) as outcome,
            _client.stream(
                "POST", f"{VENICE_BASE}/chat/completions", headers=_headers(), json=body, timeout=CHAT_TIMEOUT
            ) as resp,
        ):
            outcome["status"] = resp.status_code
            if resp.status_code >= HTTPStatus.BAD_REQUEST:
                resp.read()
                outcome["response"] = request_log.response_of(resp)
            _raise_for_response(resp)
            chunks = sse.chat_chunks(resp.iter_lines(), _stream_error, options.max_seconds, options.should_stop)
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
    cost = usd_or_none(usage.get("cost")) if usage.get("cost") is not None else usd_or_none(top_level_cost)
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
        "images": [data_url(p) for p in refs],
        **size,
    }
    resp = _request(_Call("POST", "/image/multi-edit", body, timeout=IMAGE_TIMEOUT, waiting_for="image"), log=True)
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
    resp = _request(_Call("POST", "/image/generate", body, timeout=IMAGE_TIMEOUT, waiting_for="image"), log=True)
    _check_violation(resp)
    encoded = as_list(as_object(body_of(resp)).get("images"))
    images = [(base64.b64decode(b64), "image/png") for b64 in encoded if isinstance(b64, str) and b64]
    if not images:
        raise NoImageReturnedError
    key, pricing, default_res = target.price
    return images, image_price(pricing, key, size.get("resolution"), default_res)


QUOTED_FIELDS = ("model", "duration", "aspect_ratio", "resolution", "audio", "upscale_factor")


def _remember_job(job_id: str, download_url: str | None, quote: float | None) -> None:
    """Keep what polling needs later: the download link and the quoted cost."""
    if download_url:
        _download_urls.put(job_id, download_url)
    if quote is not None:
        _video_quotes.put(job_id, quote)


def submit_video(req: VideoRequest) -> VideoJob:
    """Queue a video and return its id and sent settings.

    Reference models take ``req.refs`` (the first frame joins them if empty),
    first/last-frame models take both frames, and video models take
    ``req.source_video`` (motion control also takes an image).
    """
    info = _find(_get_catalogue().video, "video", req.model)
    family = info.family
    target = video_model(info, req.first_frame)
    c = target.constraints
    frames = VideoFrames(req.first_frame, req.last_frame, [p for p in req.refs if p.is_file()], req.source_video)
    inputs, sent, image_used = VIDEO_INPUTS.get(family, standard_inputs)(frames)
    body: dict[str, JsonValue] = {"model": target.model, "prompt": req.prompt, **inputs}
    if family == "angles":
        body["camera_trajectory"] = DEFAULT_CAMERA_TRAJECTORY

    duration, body["duration"] = video_duration(c, req.duration)
    resolution = video_resolution(body, family, c, req.resolution)
    aspect_ratio = video_aspect_ratio(req.aspect_ratio, c, image_used=image_used)
    if aspect_ratio:
        body["aspect_ratio"] = aspect_ratio
    if c.audio_configurable and req.generate_audio is not None:
        body["audio"] = req.generate_audio

    quote = _video_quote(body)
    data = as_object(
        body_of(
            _request(
                _Call("POST", "/video/queue", body, timeout=IMAGE_TIMEOUT, waiting_for="video job to start"), log=True
            )
        )
    )
    queue_id = data.get("queue_id")
    if not queue_id:
        raise NoJobIdError
    job_id = f"{JOB_PREFIX}{target.model}:{queue_id}"
    _remember_job(job_id, as_str(data.get("download_url")), quote)
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


def _video_quote(body: dict[str, JsonValue]) -> float | None:
    """What Venice says the video will cost — nice to show, not needed to generate."""
    try:
        return _quote_of(_request(_Call("POST", "/video/quote", {k: v for k, v in body.items() if k in QUOTED_FIELDS})))
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


def _early_result(job_id: str, resp: httpx.Response) -> dict[str, JsonValue] | None:
    """A retrieve response that settles the poll by itself, else None.

    Rate limits and 5xx raise (the poller's error budget); other client errors
    fail the job; a video body is saved until ``download_video`` collects it.
    """
    if resp.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR or resp.status_code == HTTPStatus.TOO_MANY_REQUESTS:
        resp.read()
        raise VideoCheckFailedError(resp.status_code)
    if resp.status_code >= HTTPStatus.BAD_REQUEST:
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
    return None


def _status_from_data(job_id: str, data: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """Map Venice's JSON status to OpenRouter's."""
    status = str(data.get("status") or "").upper()
    if status in ("FAILED", "ERROR", "CANCELLED"):
        return {"status": "failed", "error": f"Venice: {data.get('error') or data.get('message') or 'video failed'}"}
    if status == "COMPLETED" and _download_urls.get(job_id) is not None:
        return _completed(job_id)
    return {"status": "in_progress"}


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
            early = _early_result(job_id, resp)
            if early is not None:
                return early
            resp.read()
            _note_balance(resp)
            data = as_object(body_of(resp))
    except (httpx.RemoteProtocolError, httpx.ReadError, httpx.WriteError, httpx.ConnectError) as e:
        raise PollDroppedError(round(time.monotonic() - start), e) from e
    return _status_from_data(job_id, data)


def download_video(job_id: str, dest: Path) -> None:
    """Copy a completed Venice video to ``dest``."""
    src = _video_file(job_id)
    if not src.is_file():
        url = _download_urls.get(job_id)
        if url:  # private models hand back a short-lived download link instead
            tmp = dest.with_suffix(dest.suffix + ".part")
            with _client.stream("GET", url, timeout=IMAGE_TIMEOUT, follow_redirects=True) as resp:
                if resp.status_code >= HTTPStatus.BAD_REQUEST:
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

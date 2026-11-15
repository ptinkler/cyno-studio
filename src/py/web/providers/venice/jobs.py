"""Venice video jobs: queue, follow, and collect the finished MP4."""

import shutil
import tempfile
import time
from http import HTTPStatus
from pathlib import Path

import httpx

from web.core.cache import TTLCache
from web.jsonutil import as_object, as_str, body_of
from web.providers.openrouter import IMAGE_TIMEOUT
from web.providers.specs import VideoRequest
from web.providers.venice import client, models
from web.providers.venice.errors import (
    NoJobIdError,
    PollDroppedError,
    VeniceError,
    VideoCheckFailedError,
    VideoDownloadFailedError,
    VideoNotReadyError,
)
from web.providers.venice.video import (
    DEFAULT_CAMERA_TRAJECTORY,
    VIDEO_INPUTS,
    VideoFrames,
    standard_inputs,
    video_aspect_ratio,
    video_duration,
    video_model,
    video_resolution,
)
from web.types import JsonValue, VideoJob

JOB_PREFIX = "venice:"


# Per-job state the poller needs after submit. A job is followed for minutes,
# not days, so JOB_STATE_TTL is generous; the cap stops a long-lived process
# accumulating an entry per video ever made.
JOB_STATE_TTL = 24 * 3600


_video_quotes: TTLCache[str, float] = TTLCache(JOB_STATE_TTL, maxsize=2048)  # job id -> quoted USD, its cost once done


_download_urls: TTLCache[str, str] = TTLCache(JOB_STATE_TTL, maxsize=2048)  # job id -> download link (private models)


# Finished videos live here between retrieve and download
_VIDEO_DIR = Path(tempfile.gettempdir()) / "venice-videos"


def is_venice_job(job_id: str | None) -> bool:
    """Return whether ``job_id`` belongs to Venice."""
    return bool(job_id and job_id.startswith(JOB_PREFIX))


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
    info = models.find(models.get_catalogue().video, "video", req.model)
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
            client.request(
                client.Call("POST", "/video/queue", body, timeout=IMAGE_TIMEOUT, waiting_for="video job to start"),
                log=True,
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
        return models.quote_of(
            client.request(client.Call("POST", "/video/quote", {k: v for k, v in body.items() if k in QUOTED_FIELDS}))
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
            client.raise_for_response(resp)
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
        with client.http.stream(
            "POST",
            f"{client.VENICE_BASE}/video/retrieve",
            headers=client.headers(),
            json={"model": model, "queue_id": queue_id},
            timeout=IMAGE_TIMEOUT,
        ) as resp:
            early = _early_result(job_id, resp)
            if early is not None:
                return early
            resp.read()
            client.note_balance(resp)
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
            with client.http.stream("GET", url, timeout=IMAGE_TIMEOUT, follow_redirects=True) as resp:
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


def clear() -> None:
    """Forget the quoted costs and download links of followed jobs."""
    _video_quotes.clear()
    _download_urls.clear()

"""Submitting a built generation to Pollo, polling its task and fetching the results."""

import time
from collections.abc import Mapping, Sequence
from http import HTTPStatus
from pathlib import Path
from urllib.parse import urlsplit

import requests

from web.auth import keyctx
from web.core import request_log
from web.core.get_task import TaskResult, get_task_status
from web.jsonutil import as_object, as_objects, body_of
from web.providers.pollo import catalogue, uploads
from web.providers.pollo.engine import ERROR_STATUSES, SUCCESS_STATUSES
from web.providers.pollo.engine.registry import PolloGenerator
from web.providers.pollo.errors import (
    DownloadFailedError,
    ImageTimeoutError,
    ModelNotEnabledError,
    NonJsonReplyError,
    PollingGaveUpError,
    PolloError,
    RequestFailedError,
    SubmitRefusedError,
    VideoNotReadyError,
)
from web.types import JsonValue

POLL_INTERVAL = 4
POLL_TIMEOUT = 10 * 60
MAX_POLL_ERRORS = 6
DOWNLOAD_TIMEOUT = 120


def job(generator: PolloGenerator, params: dict[str, JsonValue] | None = None) -> dict[str, JsonValue]:
    """Submit a job and describe its id and sent settings.

    ``params`` overrides the video/image view of them (audio reports its own).
    """
    return {
        "id": catalogue.JOB_PREFIX + submit_task(generator),
        "params": {**(params or sent_params(generator)), **uploads.notice()},
    }


def sent_params(generator: PolloGenerator) -> dict[str, JsonValue]:
    """Return sent settings in chat's parameter names for display in the UI.

    The settings include any defaults filled in by the generator. A ``None``
    means a field was not sent (e.g. no aspectRatio when animating an
    image: the image sets it). Kling's quality tier ("mode") shows as the
    resolution, the way it's picked.
    """
    attrs = generator.payload_attrs or {}
    return {
        "aspect_ratio": attrs.get("aspectRatio"),
        "resolution": attrs.get("resolution") or attrs.get("mode"),
        "duration": attrs.get("duration") or attrs.get("length"),
        "generate_audio": attrs.get("generateAudio"),
    }


def get_video(job_id: str) -> dict[str, JsonValue]:
    """Return Pollo job status and result metadata in OpenRouter's shape.

    Transient poll failures raise, so the poller's error budget handles them.
    """
    task = _task_state(job_id[len(catalogue.JOB_PREFIX) :])
    if task["status"] == "transient":
        raise PolloError(str(task["error"]))
    return task


def download_video(job_id: str, dest: Path, index: int = 0) -> None:
    """Download a completed Pollo video job to ``dest``."""
    task = get_video(job_id)
    if task["status"] != "completed":
        raise VideoNotReadyError(task["status"])
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        with requests.get(task_urls(task)[index], stream=True, timeout=DOWNLOAD_TIMEOUT) as resp:
            resp.raise_for_status()
            with tmp.open("wb") as f:
                f.writelines(resp.iter_content(chunk_size=1 << 16))
    except requests.RequestException as e:
        raise DownloadFailedError("video", e) from e
    tmp.replace(dest)


def submit_task(generator: PolloGenerator) -> str:
    """Send a built generation request to Pollo (logged) and return its task id."""
    path = urlsplit(getattr(generator, "model_url", None) or "").path
    model = path.rstrip("/").rsplit("/", 1)[-1] or None
    with request_log.logged("pollo", "POST", path, _payload(generator), model=model) as outcome:
        return _submit_logged(generator, outcome)


def _payload(generator: PolloGenerator) -> dict[str, JsonValue] | None:
    """What the generator will send (None if it refuses to build one)."""
    try:
        return {"input": generator.get_payload()["input"]}
    except ValueError:  # send_request reports the real problem
        return None


def _submit_logged(generator: PolloGenerator, outcome: request_log.LogOutcome) -> str:
    try:
        resp = generator.send_request()
    except (ConnectionError, ValueError) as e:
        # ValueError: the generator refused the request (e.g. an
        # image-to-video-only model with no image) — nothing was sent
        raise SubmitRefusedError(e) from e
    outcome["status"] = resp.status_code
    outcome["response"] = request_log.response_of(resp)
    try:
        body = as_object(body_of(resp))
    except ValueError:
        raise NonJsonReplyError(resp.status_code, resp.text) from None
    data = body.get("data")
    data = dict(data) if isinstance(data, Mapping) else {}
    task_id = data.get("taskId")
    if not isinstance(task_id, str):
        task_id = None
    if not task_id and resp.status_code == HTTPStatus.NOT_FOUND and body.get("message") == "Not found":
        raise ModelNotEnabledError
    if not task_id:
        detail = "; ".join(str(i.get("message", "")) for i in as_objects(data.get("issues"))) or body.get("message")
        raise RequestFailedError(None if detail is None else str(detail), resp.status_code)
    return task_id


def _task_state(task_id: str) -> dict[str, JsonValue]:
    """Check a Pollo task's state and any result metadata.

    A ``transient`` status means retryable Cloudflare, network, or HTTP trouble,
    not a verdict on the generation.
    """
    try:
        results = get_task_status(task_id, keyctx.provider_key("pollo") or "")
    except (requests.RequestException, ValueError) as e:  # retry network/VPN hiccups
        return {"status": "transient", "error": f"Pollo: {e}"}
    status, fail_msg = results[0][0], results[0][1]
    if status == "cloudflare_blocked" or (status == "error" and (fail_msg or "").startswith("HTTP ")):
        return {"status": "transient", "error": f"Pollo: {fail_msg}"}
    if status in ERROR_STATUSES:
        # A failed generation isn't billed, even though Pollo still reports
        # the job's `credit` price with the verdict — so no credits are
        # recorded. The results go back as the response, so the request view
        # shows the failure rather than the "accepted" reply from submit.
        failed: dict[str, JsonValue] = {
            "status": "failed",
            "error": f"Pollo: {fail_msg or 'generation failed'}",
            "response": _task_response(results),
        }
        return failed
    if not all(r[0] in SUCCESS_STATUSES for r in results):
        return {"status": "in_progress"}
    urls = [r[2] for r in results if r[2]]
    if not urls:
        return {"status": "failed", "error": "Pollo finished but returned no file"}
    return {"status": "completed", "urls": urls, "credits": sum(r[3] for r in results if r[3] is not None) or None}


def _task_response(results: list[TaskResult]) -> dict[str, JsonValue]:
    """A task's results as the plain shape Pollo sent them, for the request view."""
    return {
        "generations": [
            {"status": st, "failMsg": msg, "url": url, "credit": credit} for st, msg, url, credit in results
        ]
    }


def task_urls(task: Mapping[str, JsonValue]) -> list[str]:
    """The result URLs of a completed task."""
    urls = task.get("urls")
    return [u for u in urls if isinstance(u, str)] if isinstance(urls, Sequence) and not isinstance(urls, str) else []


def task_credits(task: Mapping[str, JsonValue]) -> int | None:
    """The credits a task cost, when Pollo reported any."""
    credit_cost = task.get("credits")
    return credit_cost if isinstance(credit_cost, int) and not isinstance(credit_cost, bool) else None


def wait(task_id: str) -> dict[str, JsonValue]:
    """Poll an image task until it's done (or fails)."""
    deadline = time.time() + POLL_TIMEOUT
    errors = 0
    while time.time() < deadline:
        time.sleep(POLL_INTERVAL)
        task = _task_state(task_id)
        if task["status"] == "transient":
            errors += 1
            if errors >= MAX_POLL_ERRORS:
                raise PollingGaveUpError(task["error"])
            continue
        errors = 0
        if task["status"] == "failed":
            raise PolloError(str(task["error"]))
        if task["status"] == "completed":
            return task
    raise ImageTimeoutError


def download_image(url: str) -> tuple[bytes, str]:
    """Fetch a finished image: its bytes and media type."""
    try:
        resp = requests.get(url, timeout=DOWNLOAD_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as e:
        raise DownloadFailedError("image", e) from e
    media_type = (resp.headers.get("Content-Type") or "image/png").split(";")[0].strip()
    return resp.content, media_type

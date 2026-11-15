"""Pollo image, video and audio models for chat mode.

Chat's generate_image / generate_video tools normally run on OpenRouter
models; this module lets them run on Pollo's models too, through the payload
engine in web/providers/pollo_engine/. They're listed in the chat catalogues
as "pollo/<model key>" (e.g. "pollo/seedream", "pollo/seedance20fast") and
bill the signed-in user's Pollo account (their per-user Pollo key).

Images are generated synchronously, like OpenRouter's. Videos mirror
openrouter.submit_video / get_video / download_video, with job ids prefixed
"pollo:" so chat's background video poller knows which API to ask.

Pollo bills in credits, not dollars, so Pollo media records `credits` on
its media item rather than adding to the OpenRouter `cost`.
"""

import time
from collections.abc import Mapping, Sequence
from http import HTTPStatus
from pathlib import Path
from urllib.parse import urlsplit

import requests
from PIL import Image

from web.auth import keyctx
from web.core import request_log
from web.core.config import POLLO_API_TIMEOUT, POLLO_PLATFORM_BASE
from web.core.get_task import TaskResult, get_task_status
from web.jsonutil import as_object, as_objects, body_of
from web.providers import pollo_estimate
from web.providers.pollo_engine import (
    AUDIO_GENERATORS,
    ERROR_STATUSES,
    IMAGE_GENERATORS,
    SUCCESS_STATUSES,
    VIDEO_GENERATORS,
    closest_aspect_ratio,
)
from web.providers.pollo_engine import audio_generator as get_audio_generator
from web.providers.pollo_engine import image_generator as get_image_generator
from web.providers.pollo_engine import video_generator as get_video_generator
from web.providers.pollo_engine.registry import ModelSpec, PolloGenerator
from web.providers.pollo_errors import (
    ApiKeyMissingError,
    DownloadFailedError,
    EditInstructionRequiredError,
    ImageTimeoutError,
    LipsyncAudioFileRequiredError,
    LipsyncPortraitRequiredError,
    ModelNotEnabledError,
    NonJsonReplyError,
    PollingGaveUpError,
    PolloError,
    ReferenceFileRequiredError,
    ReferenceImageRequiredError,
    RequestFailedError,
    SourceVideoRequiredError,
    SubmitRefusedError,
    UnknownModelError,
    UploadFailedError,
    VideoNotReadyError,
    VoiceCloneReferenceRequiredError,
    VoiceListError,
)
from web.providers.pollo_models import MODEL_INFO, ModelInfo
from web.types import JsonValue, ModelEntry
from web.uploads import hosts as image_hosts

PREFIX = "pollo/"
JOB_PREFIX = "pollo:"
FOLLOW_IMAGE_RATIOS = ("adaptive", "auto")  # values meaning "match the input image"
POLL_INTERVAL = 4
POLL_TIMEOUT = 10 * 60
MAX_POLL_ERRORS = 6
DOWNLOAD_TIMEOUT = 120


def is_configured() -> bool:
    """Return whether a Pollo API key is configured."""
    return bool(keyctx.provider_key("pollo"))


NAME: str = "pollo"


def list_models(kind: str, *, refresh: bool = False) -> list[ModelEntry]:
    """List Pollo models for the uniform provider interface.

    Pollo has no text models; image, video and audio lists
    are already key-gated (empty without a Pollo key). Nothing is cached, so `refresh` has no effect.
    """
    _ = refresh
    if kind == "image":
        return list_image_models()
    if kind == "video":
        return list_video_models()
    if kind == "audio":
        return list_audio_models()
    return []


def is_pollo(model_id: str | None) -> bool:
    """Return whether ``model_id`` belongs to Pollo."""
    return bool(model_id and model_id.startswith(PREFIX))


def is_pollo_job(job_id: str | None) -> bool:
    """Return whether ``job_id`` belongs to Pollo."""
    return bool(job_id and job_id.startswith(JOB_PREFIX))


def _catalogue(generators: Mapping[str, ModelSpec]) -> list[tuple[str, ModelSpec, ModelInfo]]:
    """(key, spec, MODEL_INFO entry) for each model not marked deprecated."""
    if not is_configured():
        return []
    info = MODEL_INFO
    return [(key, spec, info[key]) for key, spec in generators.items() if not info.get(key, {}).get("deprecated")]


def list_image_models() -> list[ModelEntry]:
    """Pollo's image models, shaped like openrouter.list_image_models()."""
    return [
        {
            "id": PREFIX + key,
            "name": f"Pollo: {meta.get('label') or key}",
            "input_modalities": ["text", "image"] if spec.ACCEPTS_IMAGES else ["text"],
            "max_refs": spec.MAX_IMAGES or None,  # reference images it takes (None = unknown)
            "aspect_ratios": list(spec.VALID_RATIOS) or None,
            "resolutions": list(spec.VALID_RESOLUTIONS) or None,
            "tool": meta.get("tool") or None,  # a source image in, a result out (no prompt)
            "no_prompt": bool(meta.get("tool")),
            "created": None,
            "conversational": False,
            # Not enabled for this key — listed only behind "Show hidden"
            "hidden": meta.get("hidden") or None,
        }
        for key, spec, meta in _catalogue(IMAGE_GENERATORS)
    ]


def list_video_models() -> list[ModelEntry]:
    """Pollo's video models, shaped like openrouter.list_video_models()."""
    out: list[ModelEntry] = []
    for key, spec, meta in _catalogue(VIDEO_GENERATORS):
        # Motion models work on a source video + one reference image, so it has no
        # duration/resolution/aspect ratio (the source video sets those). Extend
        # continues a source video too, but the user picks the added duration
        # and resolution — it takes no image and no aspect ratio.
        typ = meta.get("type")
        recast = typ in _IMAGE_AND_VIDEO  # a reference image + a source video
        no_image = typ in _VIDEO_ONLY  # source-video families that take no first frame
        lipsync = typ == "lipsync"  # drive a portrait with an audio track
        # only the plain generators carry their own duration / aspect ratio;
        # the source-video / audio families derive the length from their input.
        # Extend alone lets the user pick the added duration.
        derived = recast or lipsync or no_image
        own_duration = not derived or typ == "extend"
        own_ratio = not derived
        out.append(
            {
                "id": PREFIX + key,
                "name": f"Pollo: {meta.get('label') or key}",
                "type": typ,
                "durations": (list(spec.VALID_LENGTHS) or None) if own_duration else None,
                "no_prompt": typ in _NO_PROMPT,  # the source file is the whole input
                "resolutions": None if recast else (list(spec.VALID_RESOLUTIONS) or None),
                "aspect_ratios": (list(spec.VALID_RATIOS) or None) if own_ratio else None,
                # recast/lipsync: the reference image rides on first_frame; extend/edit take none
                "frame_images": [] if no_image else ["first_frame"],
                "audio_input": lipsync,  # takes an uploaded audio track (lip sync)
                # reference-to-video branch (image/video/audio refs, [@name]
                # mentions): the allowed types, total cap and per-type limits.
                "ref_mode": _plain(ref_mode) if (ref_mode := meta.get("ref_mode")) else None,
                "video_input": bool(meta.get("video_input")),
                "modes": meta.get("modes") or None,
                "generate_audio": "generate_audio" in meta.get("options", []),
                "created": None,
                "hidden": meta.get("hidden") or None,
            }
        )
    return out


def _plain(value: Mapping[str, object]) -> dict[str, JsonValue]:
    """A JSON-literal table entry (a ``TypedDict``) as a plain JSON object."""
    return as_object(value)


def list_audio_models() -> list[ModelEntry]:
    """Pollo's speech and music models. `options` says which inputs the UI offers."""
    return [
        {
            "id": PREFIX + key,
            "name": f"Pollo: {meta.get('label') or key}",
            "type": meta.get("type"),
            "options": meta.get("options") or [],
            "audio_input": bool(meta.get("audio_input")),  # takes a reference clip (voice cloning)
            "created": None,
            "hidden": meta.get("hidden") or None,
        }
        for key, _spec, meta in _catalogue(AUDIO_GENERATORS)
    ]


def list_voices(page: int = 1, page_size: int = 50, **filters: str) -> dict[str, JsonValue]:
    """Pollo's official TTS voices ({"voices": [...], "total"}). A free GET."""
    params = {"page": page, "pageSize": page_size, **{k: v for k, v in filters.items() if v}}
    try:
        resp = requests.get(
            f"{POLLO_PLATFORM_BASE}/config/voice/items",
            params=params,
            headers={"x-api-key": keyctx.provider_key("pollo") or ""},
            timeout=POLLO_API_TIMEOUT,
        )
        resp.raise_for_status()
        body = as_object(body_of(resp))
    except (requests.RequestException, ValueError) as e:
        raise VoiceListError(e) from e
    keep = ("voiceId", "voiceName", "sampleAudio", "language", "gender", "age", "voiceStyle", "accent", "engineCode")
    voices: list[JsonValue] = [{k: v.get(k) for k in keep} for v in as_objects(body.get("data"))]
    return {"voices": voices, "total": body.get("total", len(voices))}


def submit_audio(
    model_id: str, prompt: str, source_audio: Path | None = None, **opts: JsonValue
) -> dict[str, JsonValue]:
    """Start a Pollo speech or music job.

    Returns the job id and settings actually sent, like ``submit_video``.
    """
    key = _generator_key(model_id, AUDIO_GENERATORS)
    image_hosts.take_upload_notes()  # start clean: notes describe this submit only
    if MODEL_INFO.get(key, {}).get("audio_input"):
        if not source_audio:
            raise VoiceCloneReferenceRequiredError
        opts["voice_ref_url"] = _upload(source_audio, "audio")
    try:
        generator = get_audio_generator(key, api_key=keyctx.provider_key("pollo"), prompt=prompt, **opts)
        generator.get_payload()
    except ValueError as e:
        raise PolloError(str(e)) from e
    return _job(generator, dict(generator.payload_attrs))


def _generator_key(model_id: str, generators: Mapping[str, ModelSpec]) -> str:
    if not is_configured():
        raise ApiKeyMissingError
    key = model_id[len(PREFIX) :]
    if key not in generators:
        raise UnknownModelError(key)
    return key


def _upload(path: Path, what: str = "image") -> str:
    """Upload a local file to the user's configured public host.

    Pollo only accepts URLs; the host and retention follow upload preferences.
    """
    try:
        return image_hosts.upload_file(path)
    except ValueError as e:
        raise UploadFailedError(what, e) from e


def _upload_ref_item(item: Mapping[str, object]) -> dict[str, JsonValue]:
    """Upload one image, video, or audio reference and shape it for Pollo.

    The result has ``url``, ``name`` (when supplied), and ``type``. Upload
    URLs are cached and reused across retries.
    """
    typ = str(item.get("type") or "image")
    path = item["path"]
    if not isinstance(path, Path):
        raise ReferenceFileRequiredError
    url = _upload(path, "video") if typ == "video" else _upload(path, "audio") if typ == "audio" else _upload(path)
    ref: dict[str, JsonValue] = {"url": url, "type": typ}
    if name := item.get("name"):
        ref["name"] = str(name)
    return ref


def _submit_ref_video_job(
    key: str,
    *,
    prompt: str,
    ref_items: list[dict[str, object]],
    aspect_ratio: str | None,
    resolution: str | None,
    duration: int | None,
    generate_audio: bool | None,
) -> dict[str, JsonValue]:
    """Submit a reference-to-video job using named image, video, or audio refs.

    The prompt can mention refs as ``[@name]``; the engine selects its refs
    payload branch whenever ``refs`` is present.
    """
    refs = [_upload_ref_item(ri) for ri in ref_items]
    # Some models (Kling 3.0 Omni) can't generate a soundtrack when a video ref
    # is present — Pollo rejects generateAudio:true in that case.
    no_audio = MODEL_INFO.get(key, {}).get("ref_mode", {}).get("no_audio_with_video")
    if generate_audio and no_audio and any(r.get("type") == "video" for r in refs):
        generate_audio = False
    generator = get_video_generator(
        key,
        api_key=keyctx.provider_key("pollo"),
        prompt=prompt,
        image_url=None,
        refs=refs,
        aspect_ratio=aspect_ratio,
        resolution=resolution,
        length=duration,
        generate_audio=generate_audio,
    )
    return _job(generator)


def generate_image(
    model_id: str,
    prompt: str,
    aspect_ratio: str | None = None,
    resolution: str | None = None,
    ref_paths: list[Path] | None = None,
) -> tuple[list[tuple[bytes, str]], int | None, dict[str, JsonValue]]:
    """Generate images on Pollo and wait for the results.

    Returns image bytes and media types, credits, and the settings actually
    sent. Reference images are uploaded first because Pollo accepts only URLs.
    """
    generators = IMAGE_GENERATORS
    key = _generator_key(model_id, generators)
    image_hosts.take_upload_notes()  # start clean: notes describe this submit only
    if aspect_ratio not in generators[key].VALID_RATIOS:
        aspect_ratio = None  # the generator falls back to 1:1
    images = [_upload(p) for p in ref_paths or []]

    generator = get_image_generator(
        key,
        api_key=keyctx.provider_key("pollo"),
        prompt=prompt,
        image_url=None,
        aspect_ratio=aspect_ratio,
        resolution=resolution,
        images=images or None,
    )
    task = _wait(submit_task(generator))
    sent = _sent_params(generator)
    return (
        [_download(u) for u in _task_urls(task)],
        _task_credits(task),
        {"aspect_ratio": sent["aspect_ratio"], "resolution": sent["resolution"], **_upload_notice()},
    )


# "needs a source video" label per source-video family (preserves wording)
_SRC_VIDEO_NEEDS = {
    "faceswap": "Face swap",
    "bgremove": "Background removal",
    "subtitle_remove": "Subtitle removal",
    "motion": "Motion",
    "extend": "Extending",
    "video_edit": "Editing",
    "upscale": "Upscaling",
}
# families that animate a reference image with a source video (image + video)
_IMAGE_AND_VIDEO = ("motion", "faceswap")
# families that work on a source video alone (no image)
_VIDEO_ONLY = ("extend", "video_edit", "upscale", "bgremove", "subtitle_remove")
# families that run with no prompt text
_NO_PROMPT = ("upscale", "bgremove", "subtitle_remove", "faceswap", "motion")
# families whose enhancement mode the user can pick
_TAKES_MODE = ("motion", "upscale", "subtitle_remove")


def _check_source_inputs(typ: str, prompt: str, source_video: Path | None, first_frame: Path | None) -> Path:
    """Raise unless the media and text this family needs are present; returns the source video."""
    if not source_video:
        raise SourceVideoRequiredError(_SRC_VIDEO_NEEDS[typ])
    if typ in _IMAGE_AND_VIDEO and not first_frame:
        raise ReferenceImageRequiredError(_SRC_VIDEO_NEEDS[typ])
    if typ == "video_edit" and not (prompt or "").strip():
        raise EditInstructionRequiredError
    return source_video


def _source_video_options(
    typ: str,
    *,
    first_frame: Path | None,
    resolution: str | None,
    duration: int | None,
    generate_audio: bool | None,
    mode: str | None,
) -> dict[str, JsonValue]:
    """The family-specific generator arguments of a source-video job."""
    if typ in _IMAGE_AND_VIDEO:  # the reference / face image rides along
        return {"image_url": _upload(first_frame) if first_frame else None, "mode": mode}
    kw: dict[str, JsonValue] = {"image_url": None, "resolution": resolution}
    if typ in _TAKES_MODE:  # resolution carries the one pick (scale / language); mode the rest
        kw["mode"] = mode
    if typ == "extend":  # extend lets the user pick added duration + audio
        kw.update(length=duration, generate_audio=generate_audio)
    return kw


def _submit_source_video_job(
    key: str,
    typ: str | None,
    *,
    prompt: str,
    source_video: Path | None,
    first_frame: Path | None,
    resolution: str | None,
    duration: int | None,
    generate_audio: bool | None,
    mode: str | None,
) -> dict[str, JsonValue] | None:
    """Submit a source-video job for a supported model family.

    Returns its job dict, or ``None`` when ``typ`` is not a source-video family
    so the caller can continue through the image/text path.
    """
    if typ not in (*_IMAGE_AND_VIDEO, *_VIDEO_ONLY):
        return None
    source = _check_source_inputs(typ, prompt, source_video, first_frame)
    # The source video goes to the host that takes larger files; both are URLs.
    kw: dict[str, JsonValue] = {
        "api_key": keyctx.provider_key("pollo"),
        "prompt": prompt,
        "video_url": _upload(source, "video"),
        **_source_video_options(
            typ,
            first_frame=first_frame,
            resolution=resolution,
            duration=duration,
            generate_audio=generate_audio,
            mode=mode,
        ),
    }
    generator = get_video_generator(key, **kw)
    return _job(generator)


def _submit_lipsync_job(
    key: str, prompt: str, first_frame: Path | None, source_audio: Path | None, resolution: str | None
) -> dict[str, JsonValue]:
    """Lip sync: a reference image (first frame) driven by an uploaded audio track.

    Both are uploaded to public URLs.
    """
    if not first_frame:
        raise LipsyncPortraitRequiredError
    if not source_audio:
        raise LipsyncAudioFileRequiredError
    generator = get_video_generator(
        key,
        api_key=keyctx.provider_key("pollo"),
        prompt=prompt,
        image_url=_upload(first_frame),
        audio_url=_upload(source_audio, "audio"),
        resolution=resolution,
    )
    return _job(generator)


def _video_ratio(key: str, aspect_ratio: str | None, first_frame: Path | None) -> str | None:
    """The aspect ratio to send: a valid one, else (with an image) the image's own shape."""
    ratios = list(VIDEO_GENERATORS[key].VALID_RATIOS)
    if aspect_ratio in ratios:
        return aspect_ratio
    if first_frame:
        # Some models (Seedance 2.0, Pollo Dance 2.0) take aspectRatio on the
        # image branch too, and the generator's fallback is 9:16 — so frame
        # the video like the image instead
        return _ratio_for_image(first_frame, ratios)
    return None


def submit_video(
    model_id: str,
    prompt: str,
    duration: int | None = None,
    aspect_ratio: str | None = None,
    resolution: str | None = None,
    *,
    generate_audio: bool | None = None,
    first_frame: Path | None = None,
    source_video: Path | None = None,
    source_audio: Path | None = None,
    mode: str | None = None,
    ref_items: list[dict[str, object]] | None = None,
) -> dict[str, JsonValue]:
    """Start a Pollo video job and return its id and sent settings.

    A first frame is uploaded first because Pollo accepts only URLs. Named
    ``ref_items`` route reference-mode models to their refs branch instead.
    """
    key = _generator_key(model_id, VIDEO_GENERATORS)
    image_hosts.take_upload_notes()  # start clean: notes describe this submit only
    typ = MODEL_INFO.get(key, {}).get("type")
    if ref_items and MODEL_INFO.get(key, {}).get("ref_mode"):
        return _submit_ref_video_job(
            key,
            prompt=prompt,
            ref_items=ref_items,
            aspect_ratio=aspect_ratio,
            resolution=resolution,
            duration=duration,
            generate_audio=generate_audio,
        )
    if typ == "lipsync":
        return _submit_lipsync_job(key, prompt, first_frame, source_audio, resolution)
    job = _submit_source_video_job(
        key,
        typ,
        prompt=prompt,
        source_video=source_video,
        first_frame=first_frame,
        resolution=resolution,
        duration=duration,
        generate_audio=generate_audio,
        mode=mode,
    )
    if job is not None:
        return job
    generator = get_video_generator(
        key,
        api_key=keyctx.provider_key("pollo"),
        prompt=prompt,
        image_url=_upload(first_frame) if first_frame else None,
        aspect_ratio=_video_ratio(key, aspect_ratio, first_frame),
        resolution=resolution,
        length=duration,
        generate_audio=generate_audio,
    )
    return _job(generator)


def estimate_cost(
    model_id: str,
    kind: str,
    duration: int | None = None,
    aspect_ratio: str | None = None,
    resolution: str | None = None,
    *,
    generate_audio: bool | None = None,
    n_images: int = 0,
    prompt: str = "",
    audio: Mapping[str, JsonValue] | None = None,
) -> dict[str, JsonValue] | None:
    """Return Pollo's credit estimate, or ``None`` when it cannot be priced.

    Estimates are free and use stand-in media URLs, so no files are uploaded.
    """
    try:
        if kind == "audio":
            key = _generator_key(model_id, AUDIO_GENERATORS)
            generator = get_audio_generator(
                key,
                api_key=keyctx.provider_key("pollo"),
                prompt=prompt or "estimate",
                voice_ref_url=pollo_estimate.PLACEHOLDERS["audio"],
                **(audio or {}),
            )
        elif kind == "image":
            generators = IMAGE_GENERATORS
            key = _generator_key(model_id, generators)
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
            key = _generator_key(model_id, VIDEO_GENERATORS)
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
                length=duration,
                generate_audio=generate_audio,
            )
        return pollo_estimate.estimate(generator)
    except (PolloError, ValueError, TypeError, requests.RequestException):  # estimates must not block the composer
        return None


def _job(generator: PolloGenerator, params: dict[str, JsonValue] | None = None) -> dict[str, JsonValue]:
    """Submit a job and describe its id and sent settings.

    ``params`` overrides the video/image view of them (audio reports its own).
    """
    return {
        "id": JOB_PREFIX + submit_task(generator),
        "params": {**(params or _sent_params(generator)), **_upload_notice()},
    }


def _upload_notice() -> dict[str, JsonValue]:
    """``upload_notice`` for the media card when a backup upload host was used."""
    notes = image_hosts.take_upload_notes()
    return {"upload_notice": "; ".join(notes)} if notes else {}


def _sent_params(generator: PolloGenerator) -> dict[str, JsonValue]:
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


def _ratio_for_image(path: Path, ratios: list[str]) -> str | None:
    """The model's "follow the image" ratio if it has one, else its closest ratio to the image's shape."""
    follow = next((r for r in ratios if r in FOLLOW_IMAGE_RATIOS), None)
    if follow:
        return follow
    numeric = tuple(r for r in ratios if ":" in r)
    if not numeric:
        return None
    with Image.open(path) as img:
        width, height = img.size
    return closest_aspect_ratio(width, height, numeric)


def get_video(job_id: str) -> dict[str, JsonValue]:
    """Return Pollo job status and result metadata in OpenRouter's shape.

    Transient poll failures raise, so the poller's error budget handles them.
    """
    task = _task_state(job_id[len(JOB_PREFIX) :])
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
        with requests.get(_task_urls(task)[index], stream=True, timeout=DOWNLOAD_TIMEOUT) as resp:
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


def _task_urls(task: Mapping[str, JsonValue]) -> list[str]:
    """The result URLs of a completed task."""
    urls = task.get("urls")
    return [u for u in urls if isinstance(u, str)] if isinstance(urls, Sequence) and not isinstance(urls, str) else []


def _task_credits(task: Mapping[str, JsonValue]) -> int | None:
    """The credits a task cost, when Pollo reported any."""
    credit_cost = task.get("credits")
    return credit_cost if isinstance(credit_cost, int) and not isinstance(credit_cost, bool) else None


def _wait(task_id: str) -> dict[str, JsonValue]:
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


def _download(url: str) -> tuple[bytes, str]:
    try:
        resp = requests.get(url, timeout=DOWNLOAD_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as e:
        raise DownloadFailedError("image", e) from e
    media_type = (resp.headers.get("Content-Type") or "image/png").split(";")[0].strip()
    return resp.content, media_type

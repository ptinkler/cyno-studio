"""Starting Pollo image, video and audio jobs: validate inputs, upload sources, build the generator."""

from pathlib import Path

from PIL import Image

from web.auth import keyctx
from web.providers.pollo import catalogue, tasks, uploads
from web.providers.pollo_engine import AUDIO_GENERATORS, IMAGE_GENERATORS, VIDEO_GENERATORS, closest_aspect_ratio
from web.providers.pollo_engine import audio_generator as get_audio_generator
from web.providers.pollo_engine import image_generator as get_image_generator
from web.providers.pollo_engine import video_generator as get_video_generator
from web.providers.pollo_errors import (
    EditInstructionRequiredError,
    LipsyncAudioFileRequiredError,
    LipsyncPortraitRequiredError,
    PolloError,
    ReferenceImageRequiredError,
    SourceVideoRequiredError,
    VoiceCloneReferenceRequiredError,
)
from web.providers.pollo_models import MODEL_INFO
from web.providers.specs import VideoRequest
from web.types import JsonValue
from web.uploads import hosts as image_hosts

FOLLOW_IMAGE_RATIOS = ("adaptive", "auto")  # values meaning "match the input image"


def submit_audio(
    model_id: str, prompt: str, source_audio: Path | None = None, **opts: JsonValue
) -> dict[str, JsonValue]:
    """Start a Pollo speech or music job.

    Returns the job id and settings actually sent, like ``submit_video``.
    """
    key = catalogue.generator_key(model_id, AUDIO_GENERATORS)
    image_hosts.take_upload_notes()  # start clean: notes describe this submit only
    if MODEL_INFO.get(key, {}).get("audio_input"):
        if not source_audio:
            raise VoiceCloneReferenceRequiredError
        opts["voice_ref_url"] = uploads.upload(source_audio, "audio")
    try:
        generator = get_audio_generator(key, api_key=keyctx.provider_key("pollo"), prompt=prompt, **opts)
        generator.get_payload()
    except ValueError as e:
        raise PolloError(str(e)) from e
    return tasks.job(generator, dict(generator.payload_attrs))


def _submit_ref_video_job(key: str, req: VideoRequest) -> dict[str, JsonValue]:
    """Submit a reference-to-video job using named image, video, or audio refs.

    The prompt can mention refs as ``[@name]``; the engine selects its refs
    payload branch whenever ``refs`` is present.
    """
    refs = [uploads.upload_ref_item(ri) for ri in req.ref_items]
    generate_audio = req.generate_audio
    # Some models (Kling 3.0 Omni) can't generate a soundtrack when a video ref
    # is present — Pollo rejects generateAudio:true in that case.
    no_audio = MODEL_INFO.get(key, {}).get("ref_mode", {}).get("no_audio_with_video")
    if generate_audio and no_audio and any(r.get("type") == "video" for r in refs):
        generate_audio = False
    generator = get_video_generator(
        key,
        api_key=keyctx.provider_key("pollo"),
        prompt=req.prompt,
        image_url=None,
        refs=refs,
        aspect_ratio=req.aspect_ratio,
        resolution=req.resolution,
        length=req.duration,
        generate_audio=generate_audio,
    )
    return tasks.job(generator)


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
    key = catalogue.generator_key(model_id, generators)
    image_hosts.take_upload_notes()  # start clean: notes describe this submit only
    if aspect_ratio not in generators[key].VALID_RATIOS:
        aspect_ratio = None  # the generator falls back to 1:1
    images = [uploads.upload(p) for p in ref_paths or []]

    generator = get_image_generator(
        key,
        api_key=keyctx.provider_key("pollo"),
        prompt=prompt,
        image_url=None,
        aspect_ratio=aspect_ratio,
        resolution=resolution,
        images=images or None,
    )
    task = tasks.wait(tasks.submit_task(generator))
    sent = tasks.sent_params(generator)
    return (
        [tasks.download_image(u) for u in tasks.task_urls(task)],
        tasks.task_credits(task),
        {"aspect_ratio": sent["aspect_ratio"], "resolution": sent["resolution"], **uploads.notice()},
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


def _check_source_inputs(typ: str, prompt: str, source_video: Path | None, first_frame: Path | None) -> Path:
    """Raise unless the media and text this family needs are present; returns the source video."""
    if not source_video:
        raise SourceVideoRequiredError(_SRC_VIDEO_NEEDS[typ])
    if typ in catalogue.IMAGE_AND_VIDEO and not first_frame:
        raise ReferenceImageRequiredError(_SRC_VIDEO_NEEDS[typ])
    if typ == "video_edit" and not (prompt or "").strip():
        raise EditInstructionRequiredError
    return source_video


def _source_video_options(typ: str, req: VideoRequest) -> dict[str, JsonValue]:
    """The family-specific generator arguments of a source-video job."""
    if typ in catalogue.IMAGE_AND_VIDEO:  # the reference / face image rides along
        return {"image_url": uploads.upload(req.first_frame) if req.first_frame else None, "mode": req.mode}
    kw: dict[str, JsonValue] = {"image_url": None, "resolution": req.resolution}
    if typ in catalogue.TAKES_MODE:  # resolution carries the one pick (scale / language); mode the rest
        kw["mode"] = req.mode
    if typ == "extend":  # extend lets the user pick added duration + audio
        kw.update(length=req.duration, generate_audio=req.generate_audio)
    return kw


def _submit_source_video_job(key: str, typ: str | None, req: VideoRequest) -> dict[str, JsonValue] | None:
    """Submit a source-video job for a supported model family.

    Returns its job dict, or ``None`` when ``typ`` is not a source-video family
    so the caller can continue through the image/text path.
    """
    if typ not in (*catalogue.IMAGE_AND_VIDEO, *catalogue.VIDEO_ONLY):
        return None
    source = _check_source_inputs(typ, req.prompt, req.source_video, req.first_frame)
    # The source video goes to the host that takes larger files; both are URLs.
    kw: dict[str, JsonValue] = {
        "api_key": keyctx.provider_key("pollo"),
        "prompt": req.prompt,
        "video_url": uploads.upload(source, "video"),
        **_source_video_options(typ, req),
    }
    generator = get_video_generator(key, **kw)
    return tasks.job(generator)


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
        image_url=uploads.upload(first_frame),
        audio_url=uploads.upload(source_audio, "audio"),
        resolution=resolution,
    )
    return tasks.job(generator)


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


def submit_video(req: VideoRequest) -> dict[str, JsonValue]:
    """Start a Pollo video job and return its id and sent settings.

    A first frame is uploaded first because Pollo accepts only URLs. Named
    ``req.ref_items`` route reference-mode models to their refs branch instead.
    """
    key = catalogue.generator_key(req.model, VIDEO_GENERATORS)
    image_hosts.take_upload_notes()  # start clean: notes describe this submit only
    typ = MODEL_INFO.get(key, {}).get("type")
    if req.ref_items and MODEL_INFO.get(key, {}).get("ref_mode"):
        return _submit_ref_video_job(key, req)
    if typ == "lipsync":
        return _submit_lipsync_job(key, req.prompt, req.first_frame, req.source_audio, req.resolution)
    job = _submit_source_video_job(key, typ, req)
    if job is not None:
        return job
    generator = get_video_generator(
        key,
        api_key=keyctx.provider_key("pollo"),
        prompt=req.prompt,
        image_url=uploads.upload(req.first_frame) if req.first_frame else None,
        aspect_ratio=_video_ratio(key, req.aspect_ratio, req.first_frame),
        resolution=req.resolution,
        length=req.duration,
        generate_audio=req.generate_audio,
    )
    return tasks.job(generator)


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

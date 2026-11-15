"""Venice video requests: which inputs each model family takes, and the length / size / shape it is sent."""

import base64
import mimetypes
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from web.providers.venice_catalogue import second_options
from web.providers.venice_errors import (
    FirstAndLastFrameRequiredError,
    ImageToAnimateRequiredError,
    MotionImageRequiredError,
    ReferenceImagesRequiredError,
    SourceVideoRequiredError,
    TextToVideoOnlyError,
)
from web.providers.venice_types import (
    VideoConstraints,
    VideoEntry,
    VideoTarget,
)
from web.types import JsonValue


def data_url(path: Path) -> str:
    """A local image as a base64 data URL, sent as is (Venice takes the full file)."""
    media_type = mimetypes.guess_type(path.name)[0] or "image/png"
    return f"data:{media_type};base64,{base64.b64encode(path.read_bytes()).decode()}"


# Multi-angle models need a camera path; chat uses a slow quarter orbit
DEFAULT_CAMERA_TRAJECTORY: list[dict[str, int]] = [
    {"time": 0, "azimuth": 0, "elevation": 0, "distance": 1},
    {"time": 1, "azimuth": 90, "elevation": 10, "distance": 1},
]


MAX_VIDEO_REFS = 30


def snap(value: str | None, allowed: list[str]) -> str | None:
    """Value if allowed (or nothing is known), else None."""
    return value if value and (not allowed or value in allowed) else None


def video_aspect_ratio(aspect_ratio: str | None, c: VideoConstraints, *, image_used: bool) -> str | None:
    """The aspect ratio to send: one the model allows; none when the image sets the shape."""
    if image_used and not c.aspect_ratios:
        return None
    return snap(aspect_ratio, c.aspect_ratios)


def video_model(info: VideoEntry, first_frame: Path | None) -> VideoTarget:
    """Select the Venice model and constraints for a video family.

    Standard families pair text-to-video with image-to-video; others use one
    model.
    """
    target = info.image if info.family != "standard" or first_frame else info.text
    if target is None:
        raise TextToVideoOnlyError if first_frame else ImageToAnimateRequiredError
    return target


@dataclass(frozen=True, slots=True)
class VideoFrames:
    """The media the chat has on hand for a video request."""

    first: Path | None
    last: Path | None
    refs: list[Path]
    source_video: Path | None


# Each family's inputs: (body fields, settings to report, whether an image sets the shape)
VideoInputs = tuple[dict[str, JsonValue], dict[str, JsonValue], bool]


def _reference_inputs(f: VideoFrames) -> VideoInputs:
    refs = (f.refs or ([f.first] if f.first else []))[:MAX_VIDEO_REFS]
    if not refs:
        raise ReferenceImagesRequiredError
    return {"reference_image_urls": [data_url(p) for p in refs]}, {"refs_used": len(refs)}, False


def _frames_inputs(f: VideoFrames) -> VideoInputs:
    if not (f.first and f.last):
        raise FirstAndLastFrameRequiredError
    return {"image_url": data_url(f.first), "end_image_url": data_url(f.last)}, {}, True


def _source_video_inputs(f: VideoFrames) -> VideoInputs:
    if not f.source_video or not f.source_video.is_file():
        raise SourceVideoRequiredError
    return {"video_url": data_url(f.source_video)}, {"source_video": f.source_video.name}, False


def _motion_inputs(f: VideoFrames) -> VideoInputs:
    body, sent, _ = _source_video_inputs(f)
    image = f.first or (f.refs[0] if f.refs else None)
    if not image:
        raise MotionImageRequiredError
    return {**body, "image_url": data_url(image)}, sent, True


def standard_inputs(f: VideoFrames) -> VideoInputs:
    """Standard image→video and multi-angle: the first frame, if any."""
    return ({"image_url": data_url(f.first)}, {}, True) if f.first else ({}, {}, False)


VIDEO_INPUTS: dict[str, Callable[[VideoFrames], VideoInputs]] = {
    "reference": _reference_inputs,
    "frames": _frames_inputs,
    "video": _source_video_inputs,
    "upscale": _source_video_inputs,
    "motion": _motion_inputs,
}


def video_duration(c: VideoConstraints, duration: int | None) -> tuple[int | None, str]:
    """Return the selected duration and its API representation.

    The requested value snaps to the nearest allowed length; unset values
    default to five seconds when supported.
    """
    allowed = c.durations
    seconds = second_options(allowed)
    if not seconds:
        return None, allowed[0] if allowed else "auto"  # e.g. "Auto": follows the source video
    if not duration or duration not in seconds:
        target = duration or 5
        duration = min(seconds, key=lambda d: (abs(d - target), d))
    return duration, f"{duration}s"


def video_resolution(
    body: dict[str, JsonValue], family: str, c: VideoConstraints, resolution: str | None
) -> str | None:
    """Put the resolution (an upscale's factor) on the body; the setting to report."""
    if family == "upscale":
        factor = {"2x": 2, "4x": 4}.get(str(resolution).lower()) or 2
        body["upscale_factor"] = factor
        return f"{factor}x"
    resolution = snap(resolution, c.resolutions)
    if resolution:
        body["resolution"] = resolution
    return resolution

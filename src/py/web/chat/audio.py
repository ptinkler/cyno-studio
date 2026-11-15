"""Audio generation (speech / music) through a Pollo job.

The video poller finishes it: audio rides the same job and download path, and is saved as .mp3.
"""

from collections.abc import Mapping
from typing import NotRequired, TypedDict, cast

from web.chat.errors import InvalidAudioJobError, PolloModelRequiredError
from web.chat.helpers import conversation_dir
from web.chat.models import AudioOptions
from web.core import request_log
from web.providers import pollo
from web.types import JsonValue

# AudioOptions fields that go to the model as-is
_OPTION_FIELDS = (
    "voice",
    "speed",
    "volume",
    "pitch",
    "instrumental",
    "vocal_gender",
    "style",
    "title",
    "negative_prompt",
    "duration",
)


class AudioJob(TypedDict):
    """A submitted audio job: its id, the parameters sent, and the request log."""

    id: str
    params: dict[str, JsonValue]
    log: NotRequired[dict[str, JsonValue] | None]


def audio_params(opts: AudioOptions) -> dict[str, JsonValue]:
    """The options the user set (unset ones are left to the model's defaults)."""
    values = cast("dict[str, JsonValue]", opts.model_dump())
    return {key: value for key in _OPTION_FIELDS if (value := values.get(key)) not in (None, "")}


def submit_audio_generation(conv_id: str, model: str, prompt: str, params: dict[str, JsonValue]) -> AudioJob:
    """Start the job. Returns the job plus "log": what was sent and answered."""
    if not pollo.is_pollo(model):
        raise PolloModelRequiredError
    request_log.forget_last()
    source_audio = params.get("source_audio")
    clip = conversation_dir(conv_id) / source_audio if isinstance(source_audio, str) else None
    job = pollo.submit_audio(model, prompt, clip, **{k: params[k] for k in _OPTION_FIELDS if k in params})
    job_id = job.get("id")
    job_params = job.get("params")
    if not isinstance(job_id, str) or not isinstance(job_params, Mapping):
        raise InvalidAudioJobError
    return {"id": job_id, "params": dict(job_params), "log": request_log.take_last()}

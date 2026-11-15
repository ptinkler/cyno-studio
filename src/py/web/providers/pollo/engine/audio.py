"""Audio API bodies: text-to-speech and text-to-music (Suno)."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict, cast

from web.core.config import POLLO_GENERATION_BASE
from web.providers.pollo.engine._shared import Payload, as_float, as_int, as_str
from web.providers.pollo.engine.errors import (
    AudioPromptRequiredError,
    AudioPromptTooLongError,
    StyleTitleMismatchError,
    VoiceReferenceRequiredError,
    VoiceRequiredError,
)

if TYPE_CHECKING:
    from web.types import JsonValue


class AudioRow(TypedDict, total=False):
    """One audio model's table row: its endpoint plus overrides of the defaults."""

    PROVIDER: str
    MODEL: str
    endpoint: str
    builder: str
    MAX_PROMPT: int
    NEEDS_VOICE: bool
    HAS_TUNING: bool
    HAS_DURATION: bool
    NEEDS_REF: bool


class AudioCfg(TypedDict):
    """An audio model's settings once the defaults are layered under its row."""

    PROVIDER: str
    MODEL: str
    endpoint: str
    builder: str
    MAX_PROMPT: int
    NEEDS_VOICE: bool
    HAS_TUNING: bool
    HAS_DURATION: bool
    NEEDS_REF: bool


_AUDIO_DEFAULTS: AudioRow = {
    "MAX_PROMPT": 3000,
    "NEEDS_VOICE": False,  # voiceId is required (ElevenLabs / MiniMax)
    "HAS_TUNING": False,  # speed / volume / pitch (Seed Audio)
    "HAS_DURATION": False,
    "NEEDS_REF": False,  # a reference voice clip (voice cloning)
}

# model_id -> overrides (plus PROVIDER / MODEL / endpoint / builder)
AUDIO_MODELS: dict[str, AudioRow] = {
    "seedaudio10": {
        "PROVIDER": "bytedance",
        "MODEL": "seed-audio-1-0",
        "endpoint": "text2speech",
        "builder": "speech",
        "HAS_TUNING": True,
    },
    "seedaudioref10": {
        "PROVIDER": "bytedance",
        "MODEL": "seed-audio-1-0",
        "endpoint": "ref2audio",
        "builder": "speech",
        "HAS_TUNING": True,
        "NEEDS_REF": True,
    },
    "minimaxspeech28hd": {
        "PROVIDER": "minimax",
        "MODEL": "speech-2-8-hd",
        "endpoint": "text2speech",
        "builder": "speech",
        "MAX_PROMPT": 5000,
        "NEEDS_VOICE": True,
    },
    "elevenv3": {
        "PROVIDER": "elevenlabs",
        "MODEL": "eleven-v3",
        "endpoint": "text2speech",
        "builder": "speech",
        "MAX_PROMPT": 5000,
        "NEEDS_VOICE": True,
    },
    "sunov45plus": {
        "PROVIDER": "suno",
        "MODEL": "suno-v4-5plus",
        "endpoint": "text2music",
        "builder": "music",
        "MAX_PROMPT": 5000,
    },
    "sunov5": {
        "PROVIDER": "suno",
        "MODEL": "suno-v5",
        "endpoint": "text2music",
        "builder": "music",
        "MAX_PROMPT": 5000,
    },
    "sunov55": {
        "PROVIDER": "suno",
        "MODEL": "suno-v5-5",
        "endpoint": "text2music",
        "builder": "music",
        "MAX_PROMPT": 5000,
        "HAS_DURATION": True,
    },
}


def cfg(model_id: str) -> AudioCfg:
    """Return the defaults and model-specific settings for an audio model."""
    # The defaults supply every key a row leaves out, and each row names its own endpoint.
    return cast("AudioCfg", {**_AUDIO_DEFAULTS, **AUDIO_MODELS[model_id]})


def audio_model_url(model_id: str) -> str:
    """Return the generation endpoint for an audio model."""
    c = cfg(model_id)
    return f"{POLLO_GENERATION_BASE}/{c['PROVIDER']}/{c['MODEL']}/{c['endpoint']}"


def _clamp(value: JsonValue, lo: float, hi: float) -> float:
    return max(lo, min(hi, as_float(value)))


def _voice_attrs(c: AudioCfg, kw: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """The voice a speech model needs: a stock voice id and/or a reference clip."""
    attrs: dict[str, JsonValue] = {}
    if c["NEEDS_VOICE"]:
        if not kw.get("voice"):
            raise VoiceRequiredError
        attrs["voiceId"] = kw["voice"]
    if c["NEEDS_REF"]:
        if not kw.get("voice_ref_url"):
            raise VoiceReferenceRequiredError
        # the shape of the spec's own voiceRefs example
        attrs["voiceRefs"] = [{"type": "audio", "name": "voice", "audioUrl": kw["voice_ref_url"]}]
    return attrs


def _tuning_attrs(kw: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """Speed / volume / pitch, clamped to the ranges the API accepts."""
    attrs: dict[str, JsonValue] = {}
    for name, lo, hi in (("speed", 0.5, 2), ("volume", 0.5, 2)):
        if (value := kw.get(name)) is not None:
            attrs[name] = _clamp(value, lo, hi)
    if (pitch := kw.get("pitch")) is not None:
        attrs["pitch"] = int(_clamp(pitch, -12, 12))
    return attrs


def _speech_payload(c: AudioCfg, prompt: str, **kw: JsonValue) -> Payload:
    attrs: dict[str, JsonValue] = {"prompt": prompt, **_voice_attrs(c, kw)}
    if c["HAS_TUNING"]:
        attrs.update(_tuning_attrs(kw))
    return {"input": attrs}


def _music_payload(c: AudioCfg, prompt: str, **kw: JsonValue) -> Payload:
    """Suno: a song description, or (with style + title together) lyrics."""
    style, title = (as_str(kw.get("style")) or "").strip(), (as_str(kw.get("title")) or "").strip()
    if bool(style) != bool(title):
        raise StyleTitleMismatchError
    attrs: dict[str, JsonValue] = {"prompt": prompt}
    if style:
        attrs.update(style=style, title=title)
    if kw.get("negative_prompt"):
        attrs["negativePrompt"] = kw["negative_prompt"]
    if kw.get("instrumental") is not None:
        attrs["instrumental"] = bool(kw["instrumental"])
    if kw.get("vocal_gender") in ("m", "f") and not kw.get("instrumental"):
        attrs["vocalGender"] = kw["vocal_gender"]
    if c["HAS_DURATION"] and (duration := kw.get("duration")):
        attrs["duration"] = as_int(duration)
    return {"input": attrs}


def audio_payload(model_id: str, *, prompt: str, **kw: JsonValue) -> Payload:
    """Build and validate a speech or music generation request body."""
    c = cfg(model_id)
    prompt = (prompt or "").strip()
    if not prompt:
        raise AudioPromptRequiredError
    if len(prompt) > c["MAX_PROMPT"]:
        raise AudioPromptTooLongError(c["MAX_PROMPT"])
    if c["builder"] == "speech":
        return _speech_payload(c, prompt, **kw)
    return _music_payload(c, prompt, **kw)

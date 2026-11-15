"""Video API bodies: the generic family plus Kling, extend, edit, upscale, lipsync and motion."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, NotRequired, Protocol, TypedDict, cast

from web.core.config import POLLO_GENERATION_BASE
from web.providers.pollo_engine._shared import Payload, as_str, parse_aspect_ratio, valid_length
from web.providers.pollo_engine.errors import (
    EditPromptRequiredError,
    FaceImageRequiredError,
    LipsyncAudioRequiredError,
    LipsyncImageRequiredError,
    LipsyncPromptRequiredError,
    ReferenceImageRequiredError,
    SourceVideoRequiredError,
    TextToVideoUnsupportedError,
    UnknownBuilderError,
    VideoAction,
)

if TYPE_CHECKING:
    from web.types import JsonValue


class VideoRow(TypedDict, total=False):
    """One video model's table row: overrides of the defaults, plus its endpoint."""

    PROVIDER: str
    MODEL: str
    V1_URL: str
    endpoint: str
    builder: str
    VALID_LENGTHS: tuple[int, ...]
    VALID_RESOLUTIONS: tuple[str, ...]
    VALID_RATIOS: tuple[str, ...]
    DEFAULT_RESOLUTION: str
    DEFAULT_LENGTH: int
    DEFAULT_RATIO: str
    FORCE_RESOLUTION: str
    DEFAULT_MODE: str
    MODE_DEFAULT: str
    MODES: tuple[str, ...]
    MODE_PRO_RESOLUTIONS: tuple[str, ...]
    HAS_GENERATE_AUDIO: bool
    HAS_WEB_SEARCH: bool
    HAS_SEED: bool
    HAS_IMAGE_TAIL: bool
    HAS_REFS: bool
    HAS_MODE: bool
    HAS_NEGATIVE_PROMPT_AUDIO: bool
    HAS_ASPECT_RATIO_ON_IMAGE: bool
    REF_TYPES: tuple[str, ...]
    MAX_REFS: int
    REF_HAS_SEED: bool
    REF_VALID_LENGTHS: tuple[int, ...]
    REF_VALID_RESOLUTIONS: tuple[str, ...]
    NEEDS_PROMPT: bool
    RESOLUTION_IS_MODE: bool
    MODE_ON_TEXT: bool
    TEXT_TO_VIDEO: bool
    IMAGE_TAIL_NEEDS_PRO: bool
    NO_AUDIO_WITH_IMAGE_TAIL: bool


class VideoCfg(TypedDict):
    """A video model's settings once the defaults are layered under its row."""

    VALID_LENGTHS: tuple[int, ...]
    VALID_RESOLUTIONS: tuple[str, ...]
    VALID_RATIOS: tuple[str, ...]
    DEFAULT_RESOLUTION: str
    DEFAULT_LENGTH: int
    HAS_GENERATE_AUDIO: bool
    HAS_WEB_SEARCH: bool
    HAS_SEED: bool
    HAS_IMAGE_TAIL: bool
    HAS_REFS: bool
    HAS_MODE: bool
    HAS_NEGATIVE_PROMPT_AUDIO: bool
    HAS_ASPECT_RATIO_ON_IMAGE: bool
    REF_TYPES: tuple[str, ...]
    MAX_REFS: int
    REF_HAS_SEED: bool
    REF_VALID_LENGTHS: tuple[int, ...]
    REF_VALID_RESOLUTIONS: tuple[str, ...]
    builder: str
    endpoint: str
    RESOLUTION_IS_MODE: bool
    MODE_ON_TEXT: bool
    TEXT_TO_VIDEO: bool
    IMAGE_TAIL_NEEDS_PRO: bool
    NO_AUDIO_WITH_IMAGE_TAIL: bool
    PROVIDER: NotRequired[str]
    MODEL: NotRequired[str]
    V1_URL: NotRequired[str]
    FORCE_RESOLUTION: NotRequired[str]
    DEFAULT_RATIO: NotRequired[str]
    DEFAULT_MODE: NotRequired[str]
    MODE_DEFAULT: NotRequired[str]
    MODES: NotRequired[tuple[str, ...]]
    MODE_PRO_RESOLUTIONS: NotRequired[tuple[str, ...]]
    NEEDS_PROMPT: NotRequired[bool]


class _Inputs(TypedDict):
    """A request's inputs resolved against a model's configuration."""

    refs: list[dict[str, JsonValue]] | None
    is_text_only: bool
    resolution: str
    length: int
    aspect_ratio: str
    image_tail: JsonValue
    seed: JsonValue
    generate_audio: JsonValue
    web_search: JsonValue
    mode: str | None
    negative_prompt: JsonValue
    audio_url: JsonValue


class _Builder(Protocol):
    """A family's body builder."""

    def __call__(self, c: VideoCfg, prompt: str, image_url: str | None, s: _Inputs, /, **kw: JsonValue) -> Payload: ...


# Config rows (introspected from the generator classes). Fields omitted here
# take the base defaults below.
_V1_VIDEO_DEFAULTS: VideoRow = {
    "VALID_LENGTHS": (),
    "VALID_RESOLUTIONS": (),
    "VALID_RATIOS": (),
    "DEFAULT_RESOLUTION": "",
    "DEFAULT_LENGTH": 5,
    "HAS_GENERATE_AUDIO": False,
    "HAS_WEB_SEARCH": False,
    "HAS_SEED": False,
    "HAS_IMAGE_TAIL": False,
    "HAS_REFS": False,
    "HAS_MODE": False,
    "HAS_NEGATIVE_PROMPT_AUDIO": False,
    "HAS_ASPECT_RATIO_ON_IMAGE": False,
    "REF_TYPES": ("image", "video", "audio"),
    "MAX_REFS": 0,
    "REF_HAS_SEED": True,
    "REF_VALID_LENGTHS": (),
    "REF_VALID_RESOLUTIONS": (),
    # dispatch + endpoint
    "builder": "generic",
    "endpoint": "video",
    # Kling post-processing flags (ignored by the generic builder)
    "RESOLUTION_IS_MODE": False,
    "MODE_ON_TEXT": True,
    "TEXT_TO_VIDEO": True,
    "IMAGE_TAIL_NEEDS_PRO": False,
    "NO_AUDIO_WITH_IMAGE_TAIL": False,
}

# Kling models share these base values (layered under each Kling row).
_KLING_BASE: VideoRow = {
    "PROVIDER": "kling-ai",
    "VALID_LENGTHS": (5, 10),
    "VALID_RATIOS": ("16:9", "9:16", "1:1"),
    "DEFAULT_RESOLUTION": "",
}

_UPSCALE_SCALES = ("original", "2x", "4x", "hd", "4K")
_UPSCALE_MODES = ("standard", "face", "denoise", "sharpen", "anime")

# model_id -> overrides of the defaults above (plus PROVIDER/MODEL)
VIDEO_MODELS: dict[str, VideoRow] = {
    "pollo20": {
        "PROVIDER": "pollo-ai",
        "MODEL": "pollo-v2",
        "VALID_LENGTHS": (5, 10),
        "VALID_RESOLUTIONS": ("480p", "720p", "1080p"),
        "VALID_RATIOS": ("16:9", "9:16", "4:3", "3:4", "1:1"),
        "DEFAULT_RESOLUTION": "480p",
        "HAS_GENERATE_AUDIO": True,
        "HAS_SEED": True,
        "HAS_REFS": True,
        "REF_TYPES": ("image",),
        "MAX_REFS": 7,
        "REF_VALID_LENGTHS": (1, 2, 3, 4, 5, 6, 7, 8),
        "REF_VALID_RESOLUTIONS": ("540p", "720p", "1080p"),
    },
    "pollo25": {
        "PROVIDER": "pollo-ai",
        "MODEL": "pollo-v2-5",
        "VALID_LENGTHS": (4, 5, 6, 7, 8, 9, 10, 11, 12, 15),
        "VALID_RESOLUTIONS": ("720p", "1080p"),
        "VALID_RATIOS": ("16:9", "9:16"),
        "DEFAULT_RESOLUTION": "720p",
        "HAS_GENERATE_AUDIO": True,
        "HAS_MODE": True,
        "MODE_DEFAULT": "basic",
    },
    "pollo30": {
        "PROVIDER": "pollo-ai",
        "MODEL": "pollo-v3-0",
        "VALID_LENGTHS": (4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15),
        "VALID_RESOLUTIONS": ("480p", "720p", "1080p", "4K"),
        "VALID_RATIOS": ("16:9", "4:3", "1:1", "3:4", "9:16", "21:9", "adaptive"),
        "DEFAULT_RESOLUTION": "480p",
        "HAS_GENERATE_AUDIO": True,
        "HAS_WEB_SEARCH": True,
        "HAS_SEED": True,
        "HAS_IMAGE_TAIL": True,
        "HAS_REFS": True,
        "HAS_MODE": True,
        "HAS_ASPECT_RATIO_ON_IMAGE": True,
        "MAX_REFS": 13,
        "MODE_PRO_RESOLUTIONS": ("1080p", "4K"),
    },
    "pollo30fast": {
        "PROVIDER": "pollo-ai",
        "MODEL": "pollo-v3-0-fast",
        "VALID_LENGTHS": (4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15),
        "VALID_RESOLUTIONS": ("480p", "720p"),
        "VALID_RATIOS": ("16:9", "4:3", "1:1", "3:4", "9:16", "21:9"),
        "DEFAULT_RESOLUTION": "480p",
        "HAS_GENERATE_AUDIO": True,
        "HAS_WEB_SEARCH": True,
        "HAS_SEED": True,
        "HAS_IMAGE_TAIL": True,
        "HAS_REFS": True,
        "HAS_ASPECT_RATIO_ON_IMAGE": True,
        "MAX_REFS": 13,
        "REF_HAS_SEED": False,
    },
    "seedance20": {
        "PROVIDER": "bytedance",
        "MODEL": "seedance-2-0",
        "VALID_LENGTHS": (4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15),
        "VALID_RESOLUTIONS": ("480p", "720p", "1080p", "4K"),
        "VALID_RATIOS": ("16:9", "4:3", "1:1", "3:4", "9:16", "21:9"),
        "DEFAULT_RESOLUTION": "480p",
        "HAS_GENERATE_AUDIO": True,
        "HAS_WEB_SEARCH": True,
        "HAS_SEED": True,
        "HAS_IMAGE_TAIL": True,
        "HAS_REFS": True,
        "HAS_ASPECT_RATIO_ON_IMAGE": True,
        "MAX_REFS": 15,
    },
    "seedance20fast": {
        "PROVIDER": "bytedance",
        "MODEL": "seedance-2-0-fast",
        "VALID_LENGTHS": (4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15),
        "VALID_RESOLUTIONS": ("480p", "720p"),
        "VALID_RATIOS": ("16:9", "4:3", "1:1", "3:4", "9:16", "21:9"),
        "DEFAULT_RESOLUTION": "480p",
        "HAS_GENERATE_AUDIO": True,
        "HAS_WEB_SEARCH": True,
        "HAS_SEED": True,
        "HAS_IMAGE_TAIL": True,
        "HAS_REFS": True,
        "HAS_ASPECT_RATIO_ON_IMAGE": True,
        "MAX_REFS": 15,
    },
    "seedance20mini": {
        "PROVIDER": "bytedance",
        "MODEL": "seedance-2-0-mini",
        "VALID_LENGTHS": (4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15),
        "VALID_RESOLUTIONS": ("480p", "720p"),
        "VALID_RATIOS": ("16:9", "4:3", "1:1", "3:4", "9:16", "21:9"),
        "DEFAULT_RESOLUTION": "480p",
        "HAS_GENERATE_AUDIO": True,
        "HAS_WEB_SEARCH": True,
        "HAS_SEED": True,
        "HAS_IMAGE_TAIL": True,
        "HAS_REFS": True,
        "HAS_ASPECT_RATIO_ON_IMAGE": True,
        "MAX_REFS": 15,
    },
    "seedance25": {
        "PROVIDER": "bytedance",
        "MODEL": "seedance-2-5",
        "VALID_LENGTHS": tuple(range(4, 31)),
        "VALID_RESOLUTIONS": ("480p", "720p", "1080p"),
        "VALID_RATIOS": ("16:9", "4:3", "1:1", "3:4", "9:16", "21:9", "adaptive"),
        "DEFAULT_RESOLUTION": "480p",
        "HAS_GENERATE_AUDIO": True,
        "HAS_WEB_SEARCH": True,
        "HAS_SEED": True,
        "HAS_IMAGE_TAIL": True,
        "HAS_REFS": True,
        "MAX_REFS": 50,
        "DEFAULT_RATIO": "adaptive",
    },
    "seedance25draft": {
        "PROVIDER": "bytedance",
        "MODEL": "seedance-2-5-draft",
        "VALID_LENGTHS": tuple(range(4, 31)),
        "VALID_RESOLUTIONS": ("480p",),
        "VALID_RATIOS": ("16:9", "4:3", "1:1", "3:4", "9:16", "21:9", "adaptive"),
        "DEFAULT_RESOLUTION": "480p",
        "HAS_GENERATE_AUDIO": True,
        "HAS_SEED": True,
        "HAS_IMAGE_TAIL": True,
        "HAS_REFS": True,
        "MAX_REFS": 50,
        "DEFAULT_RATIO": "adaptive",
        "FORCE_RESOLUTION": "480p",
    },
    "minimaxh3": {
        "PROVIDER": "minimax",
        "MODEL": "minimax-h3",
        "VALID_LENGTHS": (4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15),
        "VALID_RESOLUTIONS": ("480p", "768p", "2K"),
        "VALID_RATIOS": ("auto", "21:9", "16:9", "4:3", "1:1", "3:4", "9:16"),
        "DEFAULT_RESOLUTION": "480p",
        "HAS_IMAGE_TAIL": True,
        "HAS_REFS": True,
        "MAX_REFS": 15,
    },
    "minimaxh3max": {
        "PROVIDER": "minimax",
        "MODEL": "minimax-h3-max",
        "VALID_LENGTHS": (5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15),
        "VALID_RESOLUTIONS": ("480p", "768p", "1080p"),
        "VALID_RATIOS": ("auto", "21:9", "16:9", "4:3", "1:1", "3:4", "9:16"),
        "DEFAULT_RESOLUTION": "480p",
        "HAS_IMAGE_TAIL": True,
        "HAS_REFS": True,
        "MAX_REFS": 12,
    },
    "wan27": {
        "PROVIDER": "alibaba",
        "MODEL": "wan-v2-7",
        "VALID_LENGTHS": tuple(range(2, 16)),
        "VALID_RESOLUTIONS": ("720p", "1080p"),
        "VALID_RATIOS": ("16:9", "1:1", "4:3", "3:4", "9:16"),
        "DEFAULT_RESOLUTION": "720p",
        "HAS_SEED": True,
        "HAS_IMAGE_TAIL": True,
        "HAS_REFS": True,
        "HAS_NEGATIVE_PROMPT_AUDIO": True,
        "MAX_REFS": 10,
    },
    "wan30": {
        "PROVIDER": "alibaba",
        "MODEL": "wan-v3-0",
        "VALID_LENGTHS": tuple(range(2, 31)),
        "VALID_RESOLUTIONS": ("480p", "720p", "1080p"),
        "VALID_RATIOS": ("adaptive", "16:9", "9:16", "4:3", "3:4", "1:1"),
        "DEFAULT_RESOLUTION": "480p",
        "HAS_GENERATE_AUDIO": True,
        "HAS_SEED": True,
        "HAS_IMAGE_TAIL": True,
        "HAS_REFS": True,
        "REF_TYPES": ("image", "video", "audio", "file", "link"),
        "MAX_REFS": 22,
        "DEFAULT_RATIO": "adaptive",
    },
    "wan30prime": {
        "PROVIDER": "alibaba",
        "MODEL": "wan-v3-0-prime",
        "VALID_LENGTHS": tuple(range(2, 31)),
        "VALID_RESOLUTIONS": ("480p", "720p", "1080p"),
        "VALID_RATIOS": ("adaptive", "16:9", "9:16", "4:3", "3:4", "1:1"),
        "DEFAULT_RESOLUTION": "480p",
        "HAS_GENERATE_AUDIO": True,
        "HAS_SEED": True,
        "HAS_IMAGE_TAIL": True,
        "HAS_REFS": True,
        "REF_TYPES": ("image", "video", "audio", "file", "link"),
        "MAX_REFS": 22,
        "DEFAULT_RATIO": "adaptive",
    },
    # --- Newer frontier models (added 2026-11) ---
    "sora2": {
        "PROVIDER": "openai",
        "MODEL": "sora-2",
        "VALID_LENGTHS": (4, 8, 12, 16, 20),
        "VALID_RESOLUTIONS": (),
        "VALID_RATIOS": ("16:9", "9:16"),
        "DEFAULT_LENGTH": 8,
    },
    "sora2pro": {
        "PROVIDER": "openai",
        "MODEL": "sora-2-pro",
        "VALID_LENGTHS": (4, 8, 12, 16, 20),
        "VALID_RESOLUTIONS": ("720p", "1024p", "1080p"),
        "VALID_RATIOS": ("16:9", "9:16"),
        "DEFAULT_RESOLUTION": "720p",
        "DEFAULT_LENGTH": 8,
    },
    "veo31": {
        "PROVIDER": "google",
        "MODEL": "veo-3-1",
        "VALID_LENGTHS": (8,),
        "VALID_RESOLUTIONS": ("720p", "1080p"),
        "VALID_RATIOS": ("16:9", "9:16"),
        "DEFAULT_RESOLUTION": "720p",
        "DEFAULT_LENGTH": 8,
        "HAS_GENERATE_AUDIO": True,
        "HAS_IMAGE_TAIL": True,
    },
    "veo31fast": {
        "PROVIDER": "google",
        "MODEL": "veo-3-1-fast",
        "VALID_LENGTHS": (4, 6, 8),
        "VALID_RESOLUTIONS": ("720p", "1080p", "4K"),
        "VALID_RATIOS": ("16:9", "9:16"),
        "DEFAULT_RESOLUTION": "720p",
        "DEFAULT_LENGTH": 8,
        "HAS_GENERATE_AUDIO": True,
        "HAS_IMAGE_TAIL": True,
    },
    "veo31lite": {
        "PROVIDER": "google",
        "MODEL": "veo3-1-lite",
        "VALID_LENGTHS": (4, 6, 8),
        "VALID_RESOLUTIONS": ("720p", "1080p"),
        "VALID_RATIOS": ("16:9", "9:16"),
        "DEFAULT_RESOLUTION": "720p",
        "DEFAULT_LENGTH": 8,
        "HAS_IMAGE_TAIL": True,
    },
    "hailuo23": {
        "PROVIDER": "minimax",
        "MODEL": "hailuo-2-3",
        "VALID_LENGTHS": (6, 10),
        "VALID_RESOLUTIONS": ("768p", "1080p"),
        "VALID_RATIOS": (),
        "DEFAULT_RESOLUTION": "768p",
        "DEFAULT_LENGTH": 6,
    },
    "hailuo03": {
        "PROVIDER": "minimax",
        "MODEL": "hailuo-03",
        "VALID_LENGTHS": tuple(range(4, 16)),
        "VALID_RESOLUTIONS": ("480p", "768p", "2K"),
        "VALID_RATIOS": ("auto", "21:9", "16:9", "4:3", "1:1", "3:4", "9:16"),
        "DEFAULT_RESOLUTION": "768p",
        "HAS_IMAGE_TAIL": True,
    },
    "pollo26": {
        "PROVIDER": "pollo-ai",
        "MODEL": "pollo-v2-6",
        "VALID_LENGTHS": tuple(range(4, 16)),
        "VALID_RESOLUTIONS": ("480p", "720p", "1080p", "4K"),
        "VALID_RATIOS": ("16:9", "4:3", "1:1", "3:4", "9:16", "21:9"),
        "DEFAULT_RESOLUTION": "480p",
        "HAS_GENERATE_AUDIO": True,
        "HAS_WEB_SEARCH": True,
        "HAS_SEED": True,
        "HAS_IMAGE_TAIL": True,
    },
    "pollo26fast": {
        "PROVIDER": "pollo-ai",
        "MODEL": "pollo-v2-6-fast",
        "VALID_LENGTHS": tuple(range(4, 16)),
        "VALID_RESOLUTIONS": ("480p", "720p"),
        "VALID_RATIOS": ("16:9", "4:3", "1:1", "3:4", "9:16", "21:9"),
        "DEFAULT_RESOLUTION": "480p",
        "HAS_GENERATE_AUDIO": True,
        "HAS_WEB_SEARCH": True,
        "HAS_SEED": True,
        "HAS_IMAGE_TAIL": True,
    },
    "wan25": {
        "PROVIDER": "alibaba",
        "MODEL": "wan-v2-5",
        "VALID_LENGTHS": (5, 10),
        "VALID_RESOLUTIONS": ("480p", "720p", "1080p"),
        "VALID_RATIOS": ("16:9", "1:1", "4:3", "3:4", "9:16"),
        "DEFAULT_RESOLUTION": "720p",
        "HAS_GENERATE_AUDIO": True,
        "HAS_SEED": True,
    },
    "wan26": {
        "PROVIDER": "alibaba",
        "MODEL": "wan-v2-6",
        "VALID_LENGTHS": (5, 10),
        "VALID_RESOLUTIONS": ("720p", "1080p"),
        "VALID_RATIOS": ("1:1", "4:3", "3:4", "16:9", "9:16"),
        "DEFAULT_RESOLUTION": "720p",
        "HAS_GENERATE_AUDIO": True,
        "HAS_SEED": True,
    },
    "grokvideo15": {
        "PROVIDER": "xai",
        "MODEL": "grok-imagine-video-1-5",
        "VALID_LENGTHS": tuple(range(1, 16)),
        "VALID_RESOLUTIONS": ("480p", "720p", "1080p"),
        "VALID_RATIOS": (),
        "DEFAULT_RESOLUTION": "720p",
    },
    # Kling video: reuses the generic payload, then remaps the resolution
    # tier to a mode and applies end-frame rules
    "klingv21": {
        "MODEL": "kling-v2-1",
        "VALID_RESOLUTIONS": ("std", "pro"),
        "RESOLUTION_IS_MODE": True,
        "TEXT_TO_VIDEO": False,
        "builder": "kling",
    },
    "klingv21master": {"MODEL": "kling-v2-1-master", "builder": "kling"},
    "klingv25turbo": {
        "MODEL": "kling-v2-5-turbo",
        "VALID_RESOLUTIONS": ("std", "pro"),
        "HAS_IMAGE_TAIL": True,
        "RESOLUTION_IS_MODE": True,
        "MODE_ON_TEXT": False,
        "IMAGE_TAIL_NEEDS_PRO": True,
        "builder": "kling",
    },
    "klingvideoo1": {"MODEL": "kling-video-o1", "HAS_IMAGE_TAIL": True, "builder": "kling"},
    "klingv26": {
        "MODEL": "kling-v2-6",
        "HAS_IMAGE_TAIL": True,
        "HAS_GENERATE_AUDIO": True,
        "NO_AUDIO_WITH_IMAGE_TAIL": True,
        "builder": "kling",
    },
    "klingv3": {
        "MODEL": "kling-v3",
        "VALID_LENGTHS": tuple(range(3, 16)),
        "VALID_RESOLUTIONS": ("std", "pro", "4K"),
        "HAS_IMAGE_TAIL": True,
        "HAS_GENERATE_AUDIO": True,
        "RESOLUTION_IS_MODE": True,
        "builder": "kling",
    },
    "klingv3turbo": {
        "MODEL": "kling-v3-turbo",
        "VALID_LENGTHS": tuple(range(3, 16)),
        "VALID_RESOLUTIONS": ("720p", "1080p"),
        "builder": "kling",
    },
    "klingv3omni": {
        "MODEL": "kling-v3-omni",
        "VALID_LENGTHS": tuple(range(3, 16)),
        "VALID_RESOLUTIONS": ("std", "pro", "4K"),
        "HAS_IMAGE_TAIL": True,
        "HAS_GENERATE_AUDIO": True,
        "RESOLUTION_IS_MODE": True,
        "HAS_REFS": True,  # reference-to-video: image/video refs, [@name] mentions
        "REF_TYPES": ("image", "video"),  # no audio voice ref on Omni (docs 2026-11)
        "MAX_REFS": 7,
        "builder": "kling",
    },
    "klingv4": {
        "MODEL": "kling-v4",
        "VALID_LENGTHS": tuple(range(3, 31)),
        "VALID_RESOLUTIONS": ("720p", "1080p"),  # real resolutions, not std/pro tiers
        "VALID_RATIOS": ("21:9", "16:9", "9:16", "1:1", "adaptive"),
        "DEFAULT_RESOLUTION": "720p",
        "HAS_IMAGE_TAIL": True,
        "HAS_REFS": True,  # reference-to-video: image/video/audio refs, [@name] mentions
        "MAX_REFS": 15,
        "builder": "kling",
    },
    "klingv4flash": {
        "MODEL": "kling-v4-flash",
        "VALID_LENGTHS": tuple(range(3, 21)),
        "VALID_RESOLUTIONS": ("720p",),
        "VALID_RATIOS": ("21:9", "16:9", "9:16", "1:1", "adaptive"),
        "DEFAULT_RESOLUTION": "720p",
        "HAS_IMAGE_TAIL": True,
        "HAS_REFS": True,
        "REF_TYPES": ("image", "video"),  # audio voice refs unsupported by Flash (docs 2026-11)
        "MAX_REFS": 15,
        "builder": "kling",
    },
    "seedance25extend": {
        "PROVIDER": "bytedance",
        "MODEL": "seedance-2-5",
        "endpoint": "video-extend",
        "VALID_LENGTHS": tuple(range(4, 31)),
        "VALID_RESOLUTIONS": ("480p", "720p", "1080p"),
        "DEFAULT_RESOLUTION": "480p",
        "HAS_SEED": True,
        "HAS_GENERATE_AUDIO": True,
        "builder": "extend",
    },
    # Video-extend models (added 2026-11): continue a source video instead of
    # animating an image. All take the `_extend_payload` shape (video + prompt +
    # duration + resolution, plus generateAudio/seed where offered). Sora 2's and
    # Runway's extend endpoints use a different request shape and are left out.
    "pollov2extender": {
        "PROVIDER": "pollo-ai",
        "MODEL": "pollo-v2-extender",
        "endpoint": "video-extend",
        "VALID_LENGTHS": (4, 5, 6, 7, 8, 9, 10),
        "VALID_RESOLUTIONS": ("540p", "720p", "1080p"),
        "DEFAULT_RESOLUTION": "720p",
        "builder": "extend",
    },
    "geminiomniextend": {
        "PROVIDER": "google",
        "MODEL": "gemini-omni-1-1-flash",
        "endpoint": "video-extend",
        "VALID_LENGTHS": (4, 5, 6, 7, 8, 9, 10),
        "VALID_RESOLUTIONS": ("360p", "720p", "1080p", "4K"),
        "DEFAULT_RESOLUTION": "720p",
        "builder": "extend",
    },
    "flux3extend": {
        "PROVIDER": "flux",
        "MODEL": "flux-3",
        "endpoint": "video-extend",
        "VALID_LENGTHS": (4, 5, 6, 7, 8, 9, 10),
        "VALID_RESOLUTIONS": ("720p", "1080p"),
        "DEFAULT_RESOLUTION": "720p",
        "HAS_GENERATE_AUDIO": True,
        "builder": "extend",
    },
    "viduq2proextend": {
        "PROVIDER": "vidu",
        "MODEL": "viduq2-pro",
        "endpoint": "video-extend",
        "VALID_LENGTHS": (4, 5, 6, 7, 8, 9, 10),
        "VALID_RESOLUTIONS": ("540p", "720p", "1080p"),
        "DEFAULT_RESOLUTION": "720p",
        "builder": "extend",
    },
    "viduq2turboextend": {
        "PROVIDER": "vidu",
        "MODEL": "viduq2-turbo",
        "endpoint": "video-extend",
        "VALID_LENGTHS": (4, 5, 6, 7, 8, 9, 10),
        "VALID_RESOLUTIONS": ("540p", "720p", "1080p"),
        "DEFAULT_RESOLUTION": "720p",
        "builder": "extend",
    },
    # Video-edit models (added 2026-11): edit a source video from a text
    # instruction (`video` and `prompt` are both required). Minimal shape —
    # {video, prompt} plus a resolution where the model offers one; images/seed/
    # audio refinements are left for a later pass.
    "wanedit27": {
        "PROVIDER": "alibaba",
        "MODEL": "wan-v2-7",
        "endpoint": "video-edit",
        "VALID_RESOLUTIONS": ("720p", "1080p"),
        "DEFAULT_RESOLUTION": "720p",
        "builder": "edit",
    },
    "wanedit30": {
        "PROVIDER": "alibaba",
        "MODEL": "wan-v3-0",
        "endpoint": "video-edit",
        "VALID_RESOLUTIONS": ("480p", "720p", "1080p"),
        "DEFAULT_RESOLUTION": "720p",
        "builder": "edit",
    },
    "wanedit30prime": {
        "PROVIDER": "alibaba",
        "MODEL": "wan-v3-0-prime",
        "endpoint": "video-edit",
        "VALID_RESOLUTIONS": ("480p", "720p", "1080p"),
        "DEFAULT_RESOLUTION": "720p",
        "builder": "edit",
    },
    "geminiomniedit": {
        "PROVIDER": "google",
        "MODEL": "gemini-omni-1-1-flash",
        "endpoint": "video-edit",
        "VALID_RESOLUTIONS": ("360p", "720p", "1080p", "4K"),
        "DEFAULT_RESOLUTION": "720p",
        "builder": "edit",
    },
    "happyhorse10": {
        "PROVIDER": "alibaba",
        "MODEL": "happyhorse-1-0",
        "endpoint": "video-edit",
        "VALID_RESOLUTIONS": ("720p", "1080p"),
        "DEFAULT_RESOLUTION": "720p",
        "builder": "edit",
    },
    "viduq2proedit": {
        "PROVIDER": "vidu",
        "MODEL": "viduq2-pro",
        "endpoint": "video-edit",
        "VALID_RESOLUTIONS": ("540p", "720p", "1080p"),
        "DEFAULT_RESOLUTION": "720p",
        "builder": "edit",
    },
    "runwayalephedit": {
        "PROVIDER": "runway",
        "MODEL": "runway-gen-4-aleph",
        "endpoint": "video-edit",
        "builder": "edit",
    },
    "wananimatemix": {
        "PROVIDER": "alibaba",
        "MODEL": "wan-2-2-animate-mix",
        "endpoint": "motion",
        "HAS_MODE": True,
        "DEFAULT_MODE": "std",
        "builder": "motion",
    },
    # Motion / act (added 2026-11): a reference image animated by the motion of a
    # source video. Wan 2.2 Animate Mix is one of them;
    # the MODEL_INFO "type": "motion" sets the tag and submit routing.
    "wananimatemove": {
        "PROVIDER": "alibaba",
        "MODEL": "wan-2-2-animate-move",
        "endpoint": "motion",
        "HAS_MODE": True,
        "DEFAULT_MODE": "std",
        "builder": "motion",
    },
    "klingmotion26": {
        "PROVIDER": "kling-ai",
        "MODEL": "kling-v2-6",
        "endpoint": "motion",
        "HAS_MODE": True,
        "DEFAULT_MODE": "std",
        "builder": "motion",
    },
    "klingmotion3": {
        "PROVIDER": "kling-ai",
        "MODEL": "kling-v3",
        "endpoint": "motion",
        "HAS_MODE": True,
        "DEFAULT_MODE": "std",
        "builder": "motion",
    },
    "actionimitation": {
        "PROVIDER": "pollo-ai",
        "MODEL": "action-imitation",
        "endpoint": "motion",
        "builder": "motion",
    },
    "actionimitationv2": {
        "PROVIDER": "pollo-ai",
        "MODEL": "action-imitation-v2",
        "endpoint": "motion",
        "builder": "motion",
    },
    "runwayacttwo": {
        "PROVIDER": "runway",
        "MODEL": "runway-act-two",
        "endpoint": "motion",
        "builder": "motion",
    },
    # Video upscale (added 2026-11): {video, scale (+mode)}. The resolution
    # picker carries Pollo's `scale`; Pollo's own endpoint has no provider/model
    # segment, so it sets V1_URL.
    "pollovideoupscale": {
        "V1_URL": f"{POLLO_GENERATION_BASE}/upscale",
        "VALID_RESOLUTIONS": _UPSCALE_SCALES,
        "DEFAULT_RESOLUTION": "2x",
        "MODES": _UPSCALE_MODES,
        "builder": "upscale",
    },
    "topazvideoupscale": {
        "PROVIDER": "topaz",
        "MODEL": "topaz-video-upscale",
        "endpoint": "upscale",
        "VALID_RESOLUTIONS": _UPSCALE_SCALES,
        "DEFAULT_RESOLUTION": "2x",
        "MODES": _UPSCALE_MODES,
        "builder": "upscale",
    },
    # Video tools (added 2026-11): source video in, video out. Like upscale, the
    # resolution picker carries the one choice (output format / subtitle language).
    "videobgremove": {
        "V1_URL": f"{POLLO_GENERATION_BASE}/video-background-remove",
        "VALID_RESOLUTIONS": ("webm", "mov"),
        "DEFAULT_RESOLUTION": "webm",
        "builder": "bgremove",
    },
    "videosubtitleremove": {
        "V1_URL": f"{POLLO_GENERATION_BASE}/video-subtitle-remove",
        "VALID_RESOLUTIONS": ("en", "zh", "all", "ja", "ko", "ar"),
        "DEFAULT_RESOLUTION": "en",
        "MODES": ("standard", "advanced"),
        "builder": "subtitle",
    },
    # Face swap: the source video plus one face image (first_frame).
    "faceswap": {
        "V1_URL": f"{POLLO_GENERATION_BASE}/face-swap",
        "builder": "faceswap",
    },
    # Lip-sync (added 2026-11): drive a reference image (a portrait) with an
    # audio track. Shape {image, audio} (+prompt, +resolution where offered).
    "omnihuman": {
        "PROVIDER": "bytedance",
        "MODEL": "omnihuman",
        "endpoint": "lipsync",
        "builder": "lipsync",
    },
    "omnihuman15": {
        "PROVIDER": "bytedance",
        "MODEL": "omnihuman-v1-5",
        "endpoint": "lipsync",
        "builder": "lipsync",
    },
    "hedracharv3": {
        "PROVIDER": "hedra",
        "MODEL": "hedra-character-v3",
        "endpoint": "lipsync",
        "VALID_RESOLUTIONS": ("540p", "720p"),
        "DEFAULT_RESOLUTION": "540p",
        "builder": "lipsync",
    },
    "h3lipsync": {
        "PROVIDER": "pollo-ai",
        "MODEL": "h3-lipsync",
        "endpoint": "lipsync",
        "VALID_RESOLUTIONS": ("480p", "720p", "1080p"),
        "DEFAULT_RESOLUTION": "720p",
        "NEEDS_PROMPT": True,
        "builder": "lipsync",
    },
}


def cfg(model_id: str) -> VideoCfg:
    """Return default and model-specific settings for a video model."""
    row = VIDEO_MODELS[model_id]
    base = {**_V1_VIDEO_DEFAULTS}
    if row.get("builder") == "kling":
        base.update(_KLING_BASE)
    # The defaults supply every key a row leaves out.
    return cast("VideoCfg", {**base, **row})


def video_model_url(model_id: str) -> str:
    """Return the generation endpoint for a video model."""
    c = cfg(model_id)
    if v1_url := c.get("V1_URL"):
        return v1_url
    return f"{POLLO_GENERATION_BASE}/{c.get('PROVIDER', '')}/{c.get('MODEL', '')}/{c['endpoint']}"


def _normalize_refs(refs: JsonValue) -> list[dict[str, JsonValue]] | None:
    if not isinstance(refs, Sequence) or isinstance(refs, str):
        return None
    out: list[dict[str, JsonValue]] = []
    for ref in refs:
        if not isinstance(ref, Mapping):
            continue
        url = str(ref.get("url") or ref.get("image") or ref.get("video") or ref.get("audio") or "").strip()
        if not url:
            continue
        item: dict[str, JsonValue] = {"url": url}
        if ref.get("type"):
            item["type"] = ref["type"]
        # The handle the prompt mentions as [@name] (Kling 4.0 / Omni, MiniMax
        # H3…). Pollo defaults it to ref1, ref2… by position when omitted.
        if ref.get("name"):
            item["name"] = ref["name"]
        out.append(item)
    return out or None


def _resolve_resolution(c: VideoCfg, **kw: JsonValue) -> str:
    if forced := c.get("FORCE_RESOLUTION"):
        return forced
    return as_str(kw.get("resolution")) or c["DEFAULT_RESOLUTION"]


def _resolve_length(c: VideoCfg, **kw: JsonValue) -> int:
    length_str = str(kw.get("length") or c["DEFAULT_LENGTH"])
    if kw.get("refs") and c["REF_VALID_LENGTHS"]:
        length = int(length_str) if length_str.isdigit() else c["DEFAULT_LENGTH"]
        return min(c["REF_VALID_LENGTHS"], key=lambda v: abs(v - length))
    return valid_length(length_str, c["VALID_LENGTHS"], c["DEFAULT_LENGTH"])


def _resolve_aspect_ratio(c: VideoCfg, **kw: JsonValue) -> str:
    # the explicit kwarg, then a model default ("adaptive" on a few), else the
    # base "portrait" → 9:16.
    return as_str(kw.get("aspect_ratio")) or c.get("DEFAULT_RATIO") or parse_aspect_ratio("portrait")


def _resolve_mode(c: VideoCfg, resolution: str, mode: str | None) -> str | None:
    if not c["HAS_MODE"]:
        return None
    if pro_resolutions := c.get("MODE_PRO_RESOLUTIONS"):
        return "pro" if resolution.upper() in {r.upper() for r in pro_resolutions} else "basic"
    return mode or c.get("MODE_DEFAULT")


def _pick_mode(c: VideoCfg, **kw: JsonValue) -> str | None:
    """The requested mode when the model offers it, else the model's first mode."""
    modes = c.get("MODES", ())
    requested = as_str(kw.get("mode"))
    if requested in modes:
        return requested
    return modes[0] if modes else None


def _process_inputs(c: VideoCfg, image_url: str | None, **kw: JsonValue) -> _Inputs:
    """Resolve request inputs against a model's configuration.

    Use the caller's value or the model default; unsupported fields stay None.
    """
    refs = _normalize_refs(kw.get("refs")) if c["HAS_REFS"] else None
    resolution = _resolve_resolution(c, **kw)
    generate_audio = kw.get("generate_audio")
    web_search = kw.get("web_search")
    return {
        "refs": refs,
        "is_text_only": image_url is None,
        "resolution": resolution,
        "length": _resolve_length(c, **kw),
        "aspect_ratio": _resolve_aspect_ratio(c, **kw),
        "image_tail": kw.get("image_tail") if c["HAS_IMAGE_TAIL"] else None,
        "seed": kw.get("seed") if c["HAS_SEED"] else None,
        "generate_audio": (True if generate_audio is None else generate_audio) if c["HAS_GENERATE_AUDIO"] else None,
        "web_search": (False if web_search is None else web_search) if c["HAS_WEB_SEARCH"] else None,
        "mode": _resolve_mode(c, resolution, as_str(kw.get("mode"))),
        "negative_prompt": kw.get("negative_prompt") if c["HAS_NEGATIVE_PROMPT_AUDIO"] else None,
        "audio_url": kw.get("audio_url") if c["HAS_NEGATIVE_PROMPT_AUDIO"] else None,
    }


def _generic_payload(c: VideoCfg, prompt: str, image_url: str | None, s: _Inputs, **_: JsonValue) -> Payload:
    refs, is_text_only = s["refs"], s["is_text_only"]
    attrs: dict[str, JsonValue] = {"prompt": prompt}
    if refs:
        attrs["refs"] = refs
    elif not is_text_only:
        attrs["image"] = image_url
    attrs["duration"] = s["length"]
    if s["resolution"]:  # some models (Sora 2) have no resolution field
        attrs["resolution"] = s["resolution"]
    # Only send aspectRatio when the model actually offers one (a few, e.g.
    # Hailuo 2.3, take none and derive it from the image).
    if (refs or is_text_only or c["HAS_ASPECT_RATIO_ON_IMAGE"]) and c["VALID_RATIOS"]:
        attrs["aspectRatio"] = s["aspect_ratio"]

    has_refs = bool(refs)
    image_branch = not has_refs and not is_text_only
    candidates: dict[str, tuple[JsonValue, bool]] = {
        "imageTail": ((s["image_tail"] or None) if c["HAS_IMAGE_TAIL"] else None, image_branch),
        "generateAudio": (s["generate_audio"], True),
        "webSearch": (s["web_search"], not has_refs),
        "seed": (s["seed"], c["REF_HAS_SEED"] or not has_refs),
        "mode": (s["mode"] or None, True),
        "negativePrompt": (s["negative_prompt"] or None, True),
        "audio": (s["audio_url"] or None, not has_refs),
    }
    attrs.update({k: v for k, (v, allowed) in candidates.items() if v is not None and allowed})
    return {"input": attrs}


def _kling_payload(c: VideoCfg, prompt: str, image_url: str | None, s: _Inputs, **_: JsonValue) -> Payload:
    if s["is_text_only"] and not c["TEXT_TO_VIDEO"]:
        raise TextToVideoUnsupportedError(c.get("MODEL", ""))
    payload = _generic_payload(c, prompt, image_url, s)
    attrs = payload["input"]
    tier = attrs.pop("resolution", None)
    if tier in c["VALID_RESOLUTIONS"]:
        if not c["RESOLUTION_IS_MODE"]:
            attrs["resolution"] = tier
        elif c["MODE_ON_TEXT"] or not s["is_text_only"]:
            attrs["mode"] = tier
    if "imageTail" in attrs:
        if c["IMAGE_TAIL_NEEDS_PRO"]:
            attrs["mode"] = "pro"
        if c["NO_AUDIO_WITH_IMAGE_TAIL"]:
            attrs.pop("generateAudio", None)
    return payload


def _extend_payload(_c: VideoCfg, prompt: str, _image_url: str | None, s: _Inputs, **kw: JsonValue) -> Payload:
    video_url = kw.get("video_url")
    if not video_url:
        raise SourceVideoRequiredError(VideoAction.EXTEND)
    attrs: dict[str, JsonValue] = {"video": video_url}
    if prompt:
        attrs["prompt"] = prompt
    attrs["duration"] = s["length"]
    attrs["resolution"] = s["resolution"]
    if s["generate_audio"] is not None:
        attrs["generateAudio"] = s["generate_audio"]
    if s["seed"] is not None:
        attrs["seed"] = s["seed"]
    return {"input": attrs}


def _edit_payload(c: VideoCfg, prompt: str, _image_url: str | None, s: _Inputs, **kw: JsonValue) -> Payload:
    video_url = kw.get("video_url")
    if not video_url:
        raise SourceVideoRequiredError(VideoAction.EDIT)
    if not prompt:
        raise EditPromptRequiredError
    attrs: dict[str, JsonValue] = {"video": video_url, "prompt": prompt}
    if c["VALID_RESOLUTIONS"] and s["resolution"]:
        attrs["resolution"] = s["resolution"]
    return {"input": attrs}


def _upscale_payload(c: VideoCfg, _prompt: str, _image_url: str | None, s: _Inputs, **kw: JsonValue) -> Payload:
    """Build a video-upscale body containing the source, scale, and mode.

    Unknown scale or mode values fall back to the model defaults.
    """
    video_url = kw.get("video_url")
    if not video_url:
        raise SourceVideoRequiredError(VideoAction.UPSCALE)
    scales = {v.lower(): v for v in c["VALID_RESOLUTIONS"]}
    scale = scales.get(s["resolution"].lower(), c["DEFAULT_RESOLUTION"])
    return {"input": {"video": video_url, "scale": scale, "mode": _pick_mode(c, **kw)}}


def _bgremove_payload(c: VideoCfg, _prompt: str, _image_url: str | None, s: _Inputs, **kw: JsonValue) -> Payload:
    """Video background removal: {video, outputFormat} (webm / mov, both transparent)."""
    if not kw.get("video_url"):
        raise SourceVideoRequiredError(VideoAction.BGREMOVE)
    fmt = s["resolution"] if s["resolution"] in c["VALID_RESOLUTIONS"] else c["DEFAULT_RESOLUTION"]
    return {"input": {"video": kw["video_url"], "outputFormat": fmt}}


def _subtitle_payload(c: VideoCfg, _prompt: str, _image_url: str | None, s: _Inputs, **kw: JsonValue) -> Payload:
    """Subtitle removal: {video, language, tier}; unknown values fall back to the defaults."""
    if not kw.get("video_url"):
        raise SourceVideoRequiredError(VideoAction.SUBTITLE)
    lang = s["resolution"] if s["resolution"] in c["VALID_RESOLUTIONS"] else c["DEFAULT_RESOLUTION"]
    return {"input": {"video": kw["video_url"], "language": lang, "tier": _pick_mode(c, **kw)}}


def _faceswap_payload(_c: VideoCfg, _prompt: str, image_url: str | None, _s: _Inputs, **kw: JsonValue) -> Payload:
    """Face swap: the source video plus a face image."""
    if not kw.get("video_url"):
        raise SourceVideoRequiredError(VideoAction.FACESWAP)
    if not image_url:
        raise FaceImageRequiredError
    return {"input": {"video": kw["video_url"], "faceImage": image_url}}


def _lipsync_payload(c: VideoCfg, prompt: str, image_url: str | None, s: _Inputs, **kw: JsonValue) -> Payload:
    """Build a lip-sync body from a reference image and audio track.

    Include a prompt when supplied or required, and resolution when supported.
    """
    audio_url = kw.get("audio_url")
    if not image_url:
        raise LipsyncImageRequiredError
    if not audio_url:
        raise LipsyncAudioRequiredError
    if c.get("NEEDS_PROMPT") and not prompt:
        raise LipsyncPromptRequiredError
    attrs: dict[str, JsonValue] = {"image": image_url, "audio": audio_url}
    if prompt:
        attrs["prompt"] = prompt
    if c["VALID_RESOLUTIONS"] and s["resolution"]:
        attrs["resolution"] = s["resolution"]
    return {"input": attrs}


def _motion_payload(c: VideoCfg, _prompt: str, image_url: str | None, s: _Inputs, **kw: JsonValue) -> Payload:
    """Build a motion-transfer body from a reference image and source video.

    ``mode`` is sent only when the model supports it.
    """
    video_url = kw.get("video_url")
    if not video_url:
        raise SourceVideoRequiredError(VideoAction.MOTION)
    if not image_url:
        raise ReferenceImageRequiredError
    attrs: dict[str, JsonValue] = {"image": image_url, "video": video_url}
    if c["HAS_MODE"]:
        attrs["mode"] = s["mode"] or c.get("DEFAULT_MODE")
    return {"input": attrs}


_BUILDERS: dict[str, _Builder] = {
    "generic": _generic_payload,
    "kling": _kling_payload,
    "extend": _extend_payload,
    "edit": _edit_payload,
    "upscale": _upscale_payload,
    "bgremove": _bgremove_payload,
    "subtitle": _subtitle_payload,
    "faceswap": _faceswap_payload,
    "lipsync": _lipsync_payload,
    "motion": _motion_payload,
}


def video_payload(model_id: str, *, prompt: str, image_url: str | None, **kw: JsonValue) -> Payload:
    """Build the video API body for any model, dispatching on its family."""
    c = cfg(model_id)
    build = _BUILDERS.get(c["builder"])
    if build is None:
        raise UnknownBuilderError(c["builder"], model_id)
    return build(c, prompt, image_url, _process_inputs(c, image_url, **kw), **kw)

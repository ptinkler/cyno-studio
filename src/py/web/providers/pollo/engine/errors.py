"""Errors raised while building or sending a Pollo generation request.

Each carries its own message (these reach the user), so raise sites name the
situation rather than spelling out a sentence.
"""

from collections.abc import Iterable
from enum import StrEnum
from typing import ClassVar


class PayloadError(ValueError):
    """The request cannot be turned into a valid Pollo body."""


class NotANumberError(PayloadError):
    """A numeric request value was not numeric."""

    def __init__(self) -> None:
        """Build the fixed message."""
        super().__init__("Expected a number")


class NotAWholeNumberError(PayloadError):
    """A whole-number request value was not numeric."""

    def __init__(self) -> None:
        """Build the fixed message."""
        super().__init__("Expected a whole number")


# ── audio ──
class VoiceRequiredError(PayloadError):
    """The speech model needs a voice id."""

    def __init__(self) -> None:
        """Build the fixed message."""
        super().__init__("This speech model needs a voice")


class VoiceReferenceRequiredError(PayloadError):
    """The speech model clones a voice and needs a reference clip."""

    def __init__(self) -> None:
        """Build the fixed message."""
        super().__init__("This model needs a reference voice clip")


class StyleTitleMismatchError(PayloadError):
    """Suno lyrics mode needs style and title together."""

    def __init__(self) -> None:
        """Build the fixed message."""
        super().__init__("Style and title go together (lyrics mode) — give both or neither")


class AudioPromptRequiredError(PayloadError):
    """An audio request has no prompt."""

    def __init__(self) -> None:
        """Build the fixed message."""
        super().__init__("Audio needs a prompt")


class AudioPromptTooLongError(PayloadError):
    """The audio prompt is over the model's limit."""

    def __init__(self, limit: int) -> None:
        """Give the model's character limit."""
        super().__init__(f"The prompt is too long for this model (max {limit} characters)")


# ── image ──
class SourceImageRequiredError(PayloadError):
    """An image tool has no source image."""

    def __init__(self) -> None:
        """Build the fixed message."""
        super().__init__("This tool needs a source image")


# ── video ──
class VideoAction(StrEnum):
    """What a source-video model does, as the user-facing sentence starts."""

    EXTEND = "Extending"
    EDIT = "Editing"
    UPSCALE = "Upscaling"
    BGREMOVE = "Background removal"
    SUBTITLE = "Subtitle removal"
    FACESWAP = "Face swap"
    MOTION = "This model"


class SourceVideoRequiredError(PayloadError):
    """A source-video model was called without the video's URL."""

    def __init__(self, action: VideoAction) -> None:
        """Say which action needs the video."""
        super().__init__(f"{action} needs the source video's URL")


class EditPromptRequiredError(PayloadError):
    """Video editing needs an instruction."""

    def __init__(self) -> None:
        """Build the fixed message."""
        super().__init__("Editing needs an instruction prompt")


class FaceImageRequiredError(PayloadError):
    """Face swap needs the face image."""

    def __init__(self) -> None:
        """Build the fixed message."""
        super().__init__("Face swap needs a face image URL")


class LipsyncImageRequiredError(PayloadError):
    """Lip sync needs a portrait."""

    def __init__(self) -> None:
        """Build the fixed message."""
        super().__init__("Lip sync needs a reference image URL")


class LipsyncAudioRequiredError(PayloadError):
    """Lip sync needs an audio track."""

    def __init__(self) -> None:
        """Build the fixed message."""
        super().__init__("Lip sync needs an audio URL")


class LipsyncPromptRequiredError(PayloadError):
    """This lip-sync model needs a prompt."""

    def __init__(self) -> None:
        """Build the fixed message."""
        super().__init__("Lip sync needs a prompt")


class ReferenceImageRequiredError(PayloadError):
    """A motion model needs the reference image."""

    def __init__(self) -> None:
        """Build the fixed message."""
        super().__init__("This model needs a reference image URL")


class TextToVideoUnsupportedError(PayloadError):
    """The model only animates an image; it has no text-to-video mode."""

    def __init__(self, model: str) -> None:
        """Name the model."""
        super().__init__(f"{model} needs a source image (it has no text-to-video mode)")


class UnknownBuilderError(PayloadError):
    """A model row names a body builder that does not exist."""

    def __init__(self, builder: str, model_id: str) -> None:
        """Name the builder and the model that asked for it."""
        super().__init__(f"unknown builder {builder!r} for {model_id}")


# ── registry ──
class NoEndpointError(PayloadError):
    """A model has no endpoint URL configured."""

    def __init__(self, model_id: str) -> None:
        """Name the model."""
        super().__init__(f"No endpoint configured for {model_id}")


class UnsupportedModelError(PayloadError):
    """The model id is not in the registry for its kind."""

    kind_label: ClassVar[str]

    def __init__(self, model_id: str, available: Iterable[str]) -> None:
        """Name the model and list what is available."""
        super().__init__(f"Unsupported {self.kind_label}: {model_id}. Available: {', '.join(available)}")


class UnsupportedVideoModelError(UnsupportedModelError):
    """An unknown video model id."""

    kind_label = "model"


class UnsupportedImageModelError(UnsupportedModelError):
    """An unknown image model id."""

    kind_label = "image model"


class UnsupportedAudioModelError(UnsupportedModelError):
    """An unknown audio model id."""

    kind_label = "audio model"


# ── network (builtin ConnectionError so callers that catch it keep working) ──
class ApiUnreachableError(ConnectionError):
    """Pollo could not be reached."""

    def __init__(self, url: str, cause: Exception) -> None:
        """Name the endpoint and the network error."""
        super().__init__(f"Cannot reach API ({url}) — VPN/network may be down: {cause}")


class ApiTimeoutError(ConnectionError):
    """Pollo did not answer in time."""

    def __init__(self, url: str, cause: Exception) -> None:
        """Name the endpoint and the timeout."""
        super().__init__(f"API request timed out ({url}) — VPN/network may be slow: {cause}")


class CloudflareBlockedError(ConnectionError):
    """Cloudflare refused the request, usually because of the VPN's address."""

    def __init__(self, status: int) -> None:
        """Give the HTTP status Cloudflare answered with."""
        super().__init__(
            f"Cloudflare blocked the request (HTTP {status}). "
            "Check your VPN — you may need to enable it, switch regions, or your IP is flagged."
        )

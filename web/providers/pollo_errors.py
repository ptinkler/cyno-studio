"""Errors raised by the Pollo provider; each carries its own user-facing message."""

from web.providers.openrouter import OpenRouterError


class PolloError(OpenRouterError):
    """A Pollo request or generation failure.

    It subclasses OpenRouterError so chat handles it the same way, except
    moderation detection: Pollo answers 403 for "This model
    is not enabled for API access", which isn't a content block.
    """


class VoiceListError(PolloError):
    """The voice catalogue could not be loaded."""

    def __init__(self, cause: Exception) -> None:
        """Give the underlying error."""
        super().__init__(f"Couldn't load Pollo's voice list: {cause}")


class VoiceCloneReferenceRequiredError(PolloError):
    """A voice-cloning model was called without a reference clip."""

    def __init__(self) -> None:
        """Build the fixed message."""
        super().__init__("Voice cloning needs a reference clip — upload an audio file")


class ApiKeyMissingError(PolloError):
    """No Pollo key is set for this user."""

    def __init__(self) -> None:
        """Build the fixed message."""
        super().__init__("No Pollo API key set — add one in Settings → Keys")


class UnknownModelError(PolloError):
    """The model id is not a Pollo model we serve."""

    def __init__(self, key: str) -> None:
        """Name the model key."""
        super().__init__(f"Unknown Pollo model: {key}")


class UploadFailedError(PolloError):
    """A source file could not be hosted for Pollo to fetch."""

    def __init__(self, what: str, cause: Exception) -> None:
        """Name the kind of file (image, video, audio) and the reason."""
        super().__init__(f"Couldn't upload the {what} for Pollo: {cause}")


class ReferenceFileRequiredError(PolloError):
    """A reference item has no file."""

    def __init__(self) -> None:
        """Build the fixed message."""
        super().__init__("A reference needs a file")


class SourceVideoRequiredError(PolloError):
    """A source-video family was called without a video."""

    def __init__(self, action: str) -> None:
        """Say which action needs the video (for example ``Upscaling``)."""
        super().__init__(f"{action} needs a source video")


class ReferenceImageRequiredError(PolloError):
    """A family that animates a reference image was called without one."""

    def __init__(self, action: str) -> None:
        """Say which action needs the image."""
        super().__init__(f"{action} needs a reference image")


class EditInstructionRequiredError(PolloError):
    """Video editing needs an instruction prompt."""

    def __init__(self) -> None:
        """Build the fixed message."""
        super().__init__("Editing needs an instruction prompt")


class LipsyncPortraitRequiredError(PolloError):
    """Lip sync was called without a portrait."""

    def __init__(self) -> None:
        """Build the fixed message."""
        super().__init__("Lip sync needs a reference image")


class LipsyncAudioFileRequiredError(PolloError):
    """Lip sync was called without an audio file."""

    def __init__(self) -> None:
        """Build the fixed message."""
        super().__init__("Lip sync needs an audio file")


class VideoNotReadyError(PolloError):
    """A video download was asked for before the job completed."""

    def __init__(self, status: object) -> None:
        """Give the job's current status."""
        super().__init__(f"Pollo video isn't ready ({status})")


class DownloadFailedError(PolloError):
    """A finished result could not be downloaded."""

    def __init__(self, what: str, cause: Exception) -> None:
        """Name the kind of result (image, video) and the reason."""
        super().__init__(f"Couldn't download the Pollo {what}: {cause}")


class SubmitRefusedError(PolloError):
    """The generator refused to send the request (nothing was sent)."""

    def __init__(self, cause: Exception) -> None:
        """Give the generator's reason."""
        super().__init__(f"Pollo: {cause}")


class NonJsonReplyError(PolloError):
    """Pollo answered with something that isn't JSON."""

    def __init__(self, status: int, body: str) -> None:
        """Give the HTTP status and the start of the body."""
        super().__init__(f"Pollo returned non-JSON (HTTP {status}): {body[:200]}", status)


class ModelNotEnabledError(PolloError):
    """Pollo 404s a model that isn't enabled for this API key."""

    def __init__(self) -> None:
        """Build the fixed message (HTTP 404)."""
        super().__init__(
            "Pollo: this model isn't available to your API key (404 Not found) — "
            "it may not be enabled for API access yet",
            404,
        )


class RequestFailedError(PolloError):
    """Pollo rejected the request, with its own explanation if it gave one."""

    def __init__(self, detail: str | None, status: int) -> None:
        """Give Pollo's explanation (if any) and the HTTP status."""
        super().__init__(f"Pollo: {detail or f'request failed (HTTP {status})'}", status)


class PollingGaveUpError(PolloError):
    """Status checks kept failing, so we stopped waiting."""

    def __init__(self, last_error: object) -> None:
        """Give the last status error."""
        super().__init__(f"{last_error} (polling gave up)")


class ImageTimeoutError(PolloError):
    """The image did not finish within the polling window."""

    def __init__(self) -> None:
        """Build the fixed message."""
        super().__init__("Pollo: timed out waiting for the image")

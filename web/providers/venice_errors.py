"""Errors raised by the Venice provider; each carries its own user-facing message."""

from web.providers.openrouter import OpenRouterError


class VeniceError(OpenRouterError):
    """A Venice failure. Subclasses OpenRouterError so chat handles it the same way."""


class ApiKeyMissingError(VeniceError):
    """No Venice key is set for this user."""

    def __init__(self) -> None:
        """Build the fixed message (HTTP 503)."""
        super().__init__("No Venice API key set — add one in Settings → Keys", 503)


class RequestRejectedError(VeniceError):
    """Venice answered with an error status."""

    def __init__(self, message: str | None, status: int) -> None:
        """Give Venice's own message (if any) and the HTTP status."""
        super().__init__(f"Venice: {message or f'HTTP {status}'}", status)


class ConnectionDroppedError(VeniceError):
    """The connection dropped while waiting for a response; the request may still have been billed."""

    def __init__(self, waited_seconds: int, waiting_for: str, cause: Exception) -> None:
        """Say how long we waited, for what, and which network error ended it."""
        super().__init__(
            f"The connection to Venice dropped after {waited_seconds}s waiting "
            f"for the {waiting_for} ({type(cause).__name__}) — usually a network/VPN closing idle "
            "connections. It may still have been billed."
        )


class StreamDroppedError(VeniceError):
    """The connection dropped while a chat reply was streaming."""

    def __init__(self, waited_seconds: int, cause: Exception) -> None:
        """Say how long we waited and which network error ended it."""
        super().__init__(f"The connection to Venice dropped after {waited_seconds}s ({type(cause).__name__})")


class PollDroppedError(VeniceError):
    """The connection dropped while checking on a video job."""

    def __init__(self, waited_seconds: int, cause: Exception) -> None:
        """Say how long we waited and which network error ended it."""
        super().__init__(f"Venice connection dropped after {waited_seconds}s ({type(cause).__name__})")


class AnswerTimeoutError(VeniceError):
    """Venice did not answer in time."""

    def __init__(self, cause: Exception) -> None:
        """Name the kind of timeout (HTTP 504)."""
        super().__init__(f"Venice didn't answer in time ({type(cause).__name__})", 504)


class UnknownModelError(VeniceError):
    """The model id is not in Venice's catalogue."""

    def __init__(self, kind: str, model: str) -> None:
        """Name the model kind and the id (without the ``venice/`` prefix)."""
        super().__init__(f"Unknown Venice {kind} model: {model}")


class ContentViolationError(VeniceError):
    """Venice's filter blocked the image (HTTP 403)."""

    def __init__(self) -> None:
        """Build the fixed message."""
        super().__init__("Blocked by Venice's content filter (it flagged the image as a content violation)", status=403)


class EditOnlyModelError(VeniceError):
    """The image model can only edit, and no image was given."""

    def __init__(self) -> None:
        """Build the fixed message."""
        super().__init__("This Venice model only edits images: attach, pin or reference an image first")


class NoImageReturnedError(VeniceError):
    """Venice answered without an image."""

    def __init__(self) -> None:
        """Build the fixed message."""
        super().__init__("Venice returned no image")


class NoJobIdError(VeniceError):
    """Venice queued a video but returned no job id."""

    def __init__(self) -> None:
        """Build the fixed message."""
        super().__init__("Venice didn't return a job id")


class ImageToAnimateRequiredError(VeniceError):
    """The video model needs an image to animate."""

    def __init__(self) -> None:
        """Build the fixed message."""
        super().__init__("This Venice model needs an image to animate")


class TextToVideoOnlyError(VeniceError):
    """The video model can't animate an image."""

    def __init__(self) -> None:
        """Build the fixed message."""
        super().__init__("This Venice model can't animate an image — pick an image→video model")


class ReferenceImagesRequiredError(VeniceError):
    """The reference-to-video model got no references."""

    def __init__(self) -> None:
        """Build the fixed message."""
        super().__init__(
            "This Venice model makes a video from reference images: attach a character, "
            "pin an image or attach one first"
        )


class FirstAndLastFrameRequiredError(VeniceError):
    """The frames model needs two images."""

    def __init__(self) -> None:
        """Build the fixed message."""
        super().__init__(
            "This Venice model needs a first and a last frame: attach two images "
            "(the first is the start, the second the end)"
        )


class SourceVideoRequiredError(VeniceError):
    """The video-to-video model has no video to work on."""

    def __init__(self) -> None:
        """Build the fixed message."""
        super().__init__(
            "This Venice model works on a video: make or keep a video in this chat first (it uses the latest one)"
        )


class MotionImageRequiredError(VeniceError):
    """Motion control has no image of who should move."""

    def __init__(self) -> None:
        """Build the fixed message."""
        super().__init__("Motion control needs an image of who should move: attach or pin one")


class VideoCheckFailedError(VeniceError):
    """Venice failed (5xx or rate limit) while we checked a video job."""

    def __init__(self, status: int) -> None:
        """Give the HTTP status."""
        super().__init__(f"Venice: HTTP {status} while checking the video")


class VideoDownloadFailedError(VeniceError):
    """The finished video's download link failed."""

    def __init__(self, status: int) -> None:
        """Give the HTTP status."""
        super().__init__(f"Couldn't download the Venice video (HTTP {status})")


class VideoNotReadyError(VeniceError):
    """A video download was asked for before the job completed."""

    def __init__(self) -> None:
        """Build the fixed message."""
        super().__init__("The Venice video isn't ready")

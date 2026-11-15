"""Errors raised while preparing or running a chat turn.

Each carries its own user-facing message, so the text lives in one place and
the raise sites name the situation instead of spelling out a sentence.
"""

from web.providers.openrouter import OpenRouterError


class ModelNotSelectedError(OpenRouterError):
    """A turn needs a model of this kind, and none is picked."""

    def __init__(self, kind: str) -> None:
        """Name the missing model kind (text, image, video, audio)."""
        super().__init__(f"No {kind} model selected")


class PromptRequiredError(OpenRouterError):
    """A direct media mode was sent without any text."""

    def __init__(self, mode: str) -> None:
        """Name the mode (image, audio) that needs a text prompt."""
        super().__init__(f"{mode.capitalize()} mode needs a text prompt")


class VideoInputRequiredError(OpenRouterError):
    """Video mode needs a prompt or an image to start from."""

    def __init__(self) -> None:
        """Build the fixed message."""
        super().__init__("Video mode needs a prompt or an image")


class ToolImageRequiredError(OpenRouterError):
    """An image tool has no attached image to work on."""

    def __init__(self) -> None:
        """Build the fixed message."""
        super().__init__("This tool needs an image — attach one")


class PolloModelRequiredError(OpenRouterError):
    """Audio generation only runs on Pollo models."""

    def __init__(self) -> None:
        """Build the fixed message."""
        super().__init__("Audio generation needs a Pollo model")


class InvalidAudioJobError(TypeError):
    """Pollo accepted an audio request but returned a job we can't follow."""

    def __init__(self) -> None:
        """Build the fixed message."""
        super().__init__("Pollo returned an invalid audio job")


class EmptyPromptError(ValueError):
    """The prompt-enhancing model answered with nothing usable."""

    def __init__(self) -> None:
        """Build the fixed message."""
        super().__init__("The model returned no prompt")


class InvalidMediaItemError(TypeError):
    """A media item is missing the fields needed to regenerate it."""

    def __init__(self) -> None:
        """Build the fixed message."""
        super().__init__("Invalid media item for regeneration")

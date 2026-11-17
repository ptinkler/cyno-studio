"""Exceptions that tests make fakes raise, each with the message the scenario needs."""

import httpx

from web.providers.openrouter import OpenRouterError


class SeedOverloadedError(OpenRouterError):
    """A provider that says it is overloaded."""

    def __init__(self) -> None:
        """Build the fixed message."""
        super().__init__("[Seed] overloaded")


class InsufficientCreditsError(OpenRouterError):
    """A provider that has run out of credit (HTTP 402)."""

    def __init__(self) -> None:
        """Build the fixed message."""
        super().__init__("Insufficient credits", 402)


class UpstreamTimeoutError(OpenRouterError):
    """A provider whose upstream timed out (HTTP 502)."""

    def __init__(self) -> None:
        """Build the fixed message."""
        super().__init__("Upstream timed out", 502)


def server_disconnected() -> httpx.RemoteProtocolError:
    """The server closed the connection without answering (a real ``httpx.RemoteProtocolError``)."""
    return httpx.RemoteProtocolError("Server disconnected without sending a response.")


class NoRouteError(httpx.ConnectError):
    """No network route to the host."""

    def __init__(self) -> None:
        """Build the fixed message."""
        super().__init__("no route")

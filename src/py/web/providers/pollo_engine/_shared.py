"""Shared primitives for the Pollo engine family builders.

Includes terminal statuses, input-parsing helpers, and aspect-ratio maths.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, TypedDict

from web.providers.pollo_engine.errors import NotANumberError, NotAWholeNumberError

if TYPE_CHECKING:
    from web.types import JsonValue


class Payload(TypedDict):
    """A Pollo request body: every endpoint takes its fields under ``input``."""

    input: dict[str, JsonValue]


# Terminal task statuses from the Pollo API (used by the poller in pollo.py).
SUCCESS_STATUSES = ("succeed", "success", "succeeded", "complete", "completed")
ERROR_STATUSES = ("error", "failed")

_RATIO_WORDS = {"portrait": "9:16", "landscape": "16:9", "square": "1:1"}


def parse_aspect_ratio(mode: str = "portrait") -> str:
    """A ratio string from a mode word or a direct 'W:H' value (default 9:16)."""
    if ":" in mode:
        return mode
    return _RATIO_WORDS.get(mode, "9:16")


def valid_length(length_str: str, valid: tuple[int, ...], default: int) -> int:
    """Parse + validate a length against `valid` (empty = accept any)."""
    try:
        length = int(length_str)
    except (ValueError, TypeError):
        return default
    if valid:
        return length if length in valid else default
    return length


def closest_aspect_ratio(width: int, height: int, ratios: tuple[str, ...]) -> str:
    """The ratio in `ratios` closest to width/height."""
    actual = width / height
    return min(ratios, key=lambda r: abs(_ratio_value(r) - actual))


def _ratio_value(ratio: str) -> float:
    """A "W:H" ratio as a number."""
    w, h = (int(part) for part in ratio.split(":"))
    return w / h


def as_str(value: JsonValue) -> str | None:
    """A request value as text when it is a string, else None."""
    return value if isinstance(value, str) else None


def as_float(value: JsonValue) -> float:
    """A request value as a number; raises ValueError when it is not numeric."""
    if isinstance(value, (int, float, str)):
        return float(value)
    raise NotANumberError


def as_int(value: JsonValue) -> int:
    """A request value as a whole number; raises ValueError when it is not numeric."""
    if isinstance(value, (int, float, str)):
        return int(value)
    raise NotAWholeNumberError


def as_str_list(value: JsonValue) -> list[str]:
    """The strings in a request list value (anything else is empty)."""
    if isinstance(value, Sequence) and not isinstance(value, str):
        return [item for item in value if isinstance(item, str)]
    return []


def as_objects(value: JsonValue) -> list[Mapping[str, JsonValue]]:
    """The objects in a request list value (anything else is empty)."""
    if isinstance(value, Sequence) and not isinstance(value, str):
        return [item for item in value if isinstance(item, Mapping)]
    return []

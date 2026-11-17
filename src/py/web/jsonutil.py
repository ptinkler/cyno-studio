"""Narrow decoded JSON (``json.loads``, ``response.json()``) to the shapes code expects.

Decoded JSON is untyped, and provider replies are not guaranteed to match their
docs. These helpers take any value and return the expected shape, or an empty
one when the value is something else, so callers never index into the wrong type.
"""

import json
from collections.abc import Mapping, Sequence
from typing import Protocol, cast

from web.types import JsonValue


class _Decodable(Protocol):
    """An HTTP response whose body can be decoded as JSON (requests or httpx2)."""

    def json(self) -> object:
        """Decode the body (raises ValueError when it is not JSON)."""
        raise NotImplementedError


def body_of(response: _Decodable) -> JsonValue:
    """An HTTP response's decoded JSON body; raises ValueError when it is not JSON."""
    return cast("JsonValue", response.json())


def loads(text: str | bytes) -> JsonValue:
    """Decode JSON text; raises ValueError (``json.JSONDecodeError``) when it is not JSON."""
    return cast("JsonValue", json.loads(text))


def as_object(value: object) -> dict[str, JsonValue]:
    """The value as a JSON object (empty when it is not one)."""
    if isinstance(value, Mapping):
        return dict(cast("Mapping[str, JsonValue]", value))
    return {}


def as_list(value: object) -> list[JsonValue]:
    """The value as a JSON list (empty when it is not one)."""
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return list(cast("Sequence[JsonValue]", value))
    return []


def as_objects(value: object) -> list[dict[str, JsonValue]]:
    """The objects in a JSON list (anything else is skipped)."""
    return [as_object(item) for item in as_list(value) if isinstance(item, Mapping)]


def as_str(value: object) -> str | None:
    """The value when it is a string, else None."""
    return value if isinstance(value, str) else None


def as_int(value: object) -> int | None:
    """The value when it is a whole number (not a bool), else None."""
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def as_number(value: object) -> float | None:
    """The value when it is a number (not a bool), else None."""
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None

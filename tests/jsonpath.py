"""Typed reading of decoded JSON for tests.

``response.json()`` is untyped, so tests read replies through these helpers
instead. They return ordinary Python values (never wrappers), so what they hand
back is safe to pass anywhere, including request bodies and URLs.

``root`` is an HTTP response (decoded for you) or an already-decoded value;
``path`` is a chain of object keys and list indexes, so
``dig(reply, "messages", 0, "content")`` reads ``reply["messages"][0]["content"]``.
A step that doesn't exist yields ``None`` from :func:`dig`; the typed readers
(:func:`text`, :func:`integer`, :func:`number`, :func:`flag`, :func:`obj`,
:func:`rows`, :func:`seq`) fail the test with a clear message when the value
isn't the expected type.
"""

from collections.abc import Mapping, Sequence
from typing import Protocol, runtime_checkable

from web.jsonutil import body_of
from web.types import JsonValue


@runtime_checkable
class _Decodable(Protocol):
    """An HTTP response whose body can be decoded as JSON."""

    def json(self) -> object:
        """Decode the body."""
        raise NotImplementedError


type Root = _Decodable | JsonValue


def decode(root: Root) -> JsonValue:
    """The decoded value of a response, or the value itself when already decoded."""
    return body_of(root) if isinstance(root, _Decodable) else root


def dig(root: Root, *path: str | int) -> JsonValue:
    """The value at ``path`` below ``root`` (``None`` when any step is missing)."""
    value = decode(root)
    for step in path:
        if isinstance(step, str):
            value = value.get(step) if isinstance(value, Mapping) else None
        elif isinstance(value, Sequence) and not isinstance(value, str) and -len(value) <= step < len(value):
            value = value[step]
        else:
            return None
    return value


def text(root: Root, *path: str | int) -> str:
    """The string at ``path`` (fails the test if it is not one)."""
    value = dig(root, *path)
    assert isinstance(value, str), f"expected a string at {path!r}, got {value!r}"
    return value


def integer(root: Root, *path: str | int) -> int:
    """The whole number at ``path`` (fails the test if it is not one)."""
    value = dig(root, *path)
    assert isinstance(value, int), f"expected an integer at {path!r}, got {value!r}"
    assert not isinstance(value, bool), f"expected an integer at {path!r}, got a boolean"
    return value


def number(root: Root, *path: str | int) -> float:
    """The number at ``path`` (fails the test if it is not one)."""
    value = dig(root, *path)
    assert isinstance(value, (int, float)), f"expected a number at {path!r}, got {value!r}"
    assert not isinstance(value, bool), f"expected a number at {path!r}, got a boolean"
    return float(value)


def flag(root: Root, *path: str | int) -> bool:
    """The boolean at ``path`` (fails the test if it is not one)."""
    value = dig(root, *path)
    assert isinstance(value, bool), f"expected a boolean at {path!r}, got {value!r}"
    return value


def obj(root: Root, *path: str | int) -> dict[str, JsonValue]:
    """The object at ``path`` (fails the test if it is not one)."""
    value = dig(root, *path)
    assert isinstance(value, Mapping), f"expected an object at {path!r}, got {value!r}"
    return dict(value)


def seq(root: Root, *path: str | int) -> list[JsonValue]:
    """The list at ``path`` (fails the test if it is not one)."""
    value = dig(root, *path)
    assert isinstance(value, Sequence), f"expected a list at {path!r}, got {value!r}"
    assert not isinstance(value, str), f"expected a list at {path!r}, got a string"
    return list(value)


def rows(root: Root, *path: str | int) -> list[dict[str, JsonValue]]:
    """The list of objects at ``path`` (fails the test if it is not a list of objects)."""
    items = seq(root, *path)
    assert all(isinstance(item, Mapping) for item in items), f"expected a list of objects at {path!r}"
    return [obj(item) for item in items]


def must[T](value: T | None) -> T:
    """The value, failing the test if it is ``None`` (narrows optional results such as ``db.get_*``)."""
    assert value is not None, "expected a value, got None"
    return value

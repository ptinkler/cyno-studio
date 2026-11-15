"""Test doubles for functions that tests swap in with ``monkeypatch.setattr``."""

from collections.abc import Callable


def stub[T](produce: Callable[[], T]) -> Callable[..., T]:
    """A stand-in that ignores its arguments and returns ``produce()`` afresh on every call."""

    def call(*_args: object, **_kwargs: object) -> T:
        return produce()

    return call

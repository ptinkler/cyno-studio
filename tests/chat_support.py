"""Shared fakes and helpers for the chat tests: stand-ins for OpenRouter, Pollo and the pollers."""

import json
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, Self, cast

import sqlalchemy as sa
from fastapi.testclient import TestClient

from tests import jsonpath as jp
from tests.chat_fixtures import png_bytes
from web.core.get_task import TaskResult
from web.jsonutil import as_object
from web.providers import openrouter
from web.types import ChatChunk, JsonValue, ModelEntry, VideoJob

ROOT_DIR = Path(__file__).parent.parent.resolve()


@dataclass
class StreamCall:
    """One call made to the faked ``openrouter.stream_chat``."""

    model: str
    messages: list[dict[str, JsonValue]]
    tools: list[dict[str, JsonValue]] | None


class FakeStream:
    """Stands in for ``openrouter.stream_chat``: serves the queued replies in turn and records each call."""

    def __init__(self, *replies: Iterable[ChatChunk]) -> None:
        """Queue the replies, one per call."""
        self._replies = iter(replies)
        self.calls: list[StreamCall] = []

    def __call__(
        self,
        model: str,
        messages: list[dict[str, JsonValue]],
        tools: list[dict[str, JsonValue]] | None = None,
        session_id: str | None = None,
        **_kw: object,
    ) -> Iterator[ChatChunk]:
        """Record the call and hand back the next reply."""
        self.calls.append(StreamCall(model, messages, tools))
        return iter(next(self._replies))


@dataclass
class ImageCall:
    """One call made to the faked ``openrouter.generate_image``."""

    model: str
    prompt: str
    aspect_ratio: str | None
    resolution: str | None
    input_images: list[str] | None


class FakeImages:
    """Stands in for ``openrouter.generate_image``: records each request and returns ``count`` PNGs."""

    def __init__(self, count: int = 1, cost: float | None = 0.04) -> None:
        """Set how many pictures each call returns and what they cost."""
        self.count = count
        self.cost = cost
        self.calls: list[ImageCall] = []

    def __call__(
        self,
        model: str,
        prompt: str,
        aspect_ratio: str | None = None,
        resolution: str | None = None,
        input_images: list[str] | None = None,
        session_id: str | None = None,
    ) -> tuple[list[tuple[bytes, str]], float | None]:
        """Record the request and return the pictures."""
        self.calls.append(ImageCall(model, prompt, aspect_ratio, resolution, input_images))
        return [(png_bytes(), "image/png")] * self.count, self.cost


class FakeVideoSubmit:
    """Stands in for ``openrouter.submit_video``: remembers the first frame it was given."""

    def __init__(self, job_id: str) -> None:
        """Set the id of the job every submission returns."""
        self.job_id = job_id
        self.first_frame: str | None = None

    def __call__(
        self,
        model: str,
        prompt: str,
        duration: int | None = None,
        aspect_ratio: str | None = None,
        resolution: str | None = None,
        first_frame: str | None = None,
        generate_audio: bool | None = None,
        session_id: str | None = None,
    ) -> VideoJob:
        """Record the first frame and return the job."""
        self.first_frame = first_frame
        return {"id": self.job_id}


def loads_object(raw: str) -> dict[str, JsonValue]:
    """Decode a JSON object from text (the arguments or result a tool call carries)."""
    return as_object(cast("object", json.loads(raw)))


class NopeError(openrouter.OpenRouterError):
    """An OpenRouter failure (HTTP 500) with the message ``nope``."""

    def __init__(self) -> None:
        """Build the fixed message."""
        super().__init__("nope", 500)


class PollerStarts:
    """Stands in for ``chat_polling.start_video_poller``: records the jobs it was asked to follow."""

    def __init__(self) -> None:
        """Start with no jobs."""
        self.jobs: list[tuple[str, int, str, str]] = []

    def __call__(self, conv_id: str, message_id: int, media_id: str, job_id: str) -> None:
        """Record the job."""
        self.jobs.append((conv_id, message_id, media_id, job_id))


class GalleryBackfill(Protocol):
    """The part of the 0024 migration module that the test calls."""

    def backfill(self, conn: sa.Connection) -> int:
        """Backfill pure-gallery conversations and return the converted count."""
        raise NotImplementedError


class StreamSpy:
    """A stand-in ``openrouter.stream_chat`` that records each call and plays the next scripted reply."""

    def __init__(self, next_reply: Callable[[], Iterator[ChatChunk]]) -> None:
        """Play ``next_reply()`` for every call."""
        self._next_reply = next_reply
        self.messages: list[list[dict[str, JsonValue]]] = []
        self.tools: list[list[dict[str, JsonValue]] | None] = []

    def __call__(
        self,
        model: str,
        messages: list[dict[str, JsonValue]],
        tools: list[dict[str, JsonValue]] | None = None,
        session_id: str | None = None,
        max_seconds: float | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> Iterator[ChatChunk]:
        """Record what was sent and stream the next reply."""
        self.messages.append(messages)
        self.tools.append(tools)
        return self._next_reply()


class ImageApiSpy:
    """A stand-in ``openrouter.generate_image`` that records what it was asked for."""

    def __init__(self) -> None:
        """Start with nothing recorded."""
        self.prompt: str | None = None
        self.input_images: list[str] | None = None

    def __call__(
        self,
        model: str,
        prompt: str,
        aspect_ratio: str | None = None,
        resolution: str | None = None,
        input_images: list[str] | None = None,
        session_id: str | None = None,
    ) -> tuple[list[tuple[bytes, str]], float | None]:
        """Record the prompt and reference images, and return one picture."""
        self.prompt = prompt
        self.input_images = input_images
        return [(png_bytes(), "image/png")], None


class ChatImageSpy:
    """A stand-in ``openrouter.generate_image_chat`` that records the conversation it was given."""

    def __init__(self, cost: float | None = None) -> None:
        """Return one picture costing ``cost``."""
        self._cost = cost
        self.model: str | None = None
        self.messages: list[dict[str, JsonValue]] = []
        self.aspect_ratio: str | None = None

    def __call__(
        self,
        model: str,
        messages: list[dict[str, JsonValue]],
        aspect_ratio: str | None = None,
        session_id: str | None = None,
    ) -> tuple[list[tuple[bytes, str]], float | None]:
        """Record what was sent and return one picture."""
        self.model = model
        self.messages = messages
        self.aspect_ratio = aspect_ratio
        return [(png_bytes(), "image/png")], self._cost


def new_snippet(client: TestClient, name: str, content: str) -> int:
    """Create an instruction snippet and return its id."""
    return jp.integer(client.post("/api/chat/instructions", json={"name": name, "content": content}), "id")


def new_group(client: TestClient, name: str, snippet_ids: list[int]) -> int:
    """Create an instruction group and return its id."""
    body = {"name": name, "snippet_ids": snippet_ids}
    return jp.integer(client.post("/api/chat/instruction-groups", json=body), "id")


def no_statuses() -> Iterator[list[TaskResult]]:
    """An empty queue of Pollo task statuses."""
    return iter([])


@dataclass
class PolloCalls:
    """What the faked Pollo client was asked to do, and the task statuses it will report next."""

    generators: list[tuple[str, dict[str, JsonValue]]] = field(default_factory=list)
    uploads: list[str] = field(default_factory=list)
    statuses: Iterator[list[TaskResult]] = field(default_factory=no_statuses)

    def report(self, *rounds: list[TaskResult]) -> None:
        """Queue the statuses that successive polls of a Pollo task will see."""
        self.statuses = iter(rounds)


class FakeResponse:
    """A canned HTTP response, usable as a ``requests`` response and as a context manager."""

    def __init__(
        self,
        body: JsonValue,
        content: bytes = b"",
        content_type: str = "image/png",
        status_code: int = 200,
    ) -> None:
        self._body = body
        self.content = content
        self.status_code = status_code
        self.text = ""
        self.headers = {"Content-Type": content_type}

    def json(self) -> JsonValue:
        """The canned body."""
        return self._body

    def raise_for_status(self) -> None:
        """Never raises: every canned response is a success."""

    def iter_content(self, chunk_size: int | None = None) -> Iterator[bytes]:
        """The whole content as one chunk."""
        _ = chunk_size
        yield self.content

    def __enter__(self) -> Self:
        """Act as a context manager that yields itself."""
        return self

    def __exit__(self, *exc: object) -> bool:
        """Never swallow an exception."""
        return False


class FakeGenerator:
    """A Pollo image/video generator that records its call and answers "accepted"."""

    api_key = "pollo-test"

    def __init__(self, calls: PolloCalls, key: str, **kwargs: JsonValue) -> None:
        calls.generators.append((key, kwargs))
        self._kwargs = kwargs
        self.payload_attrs: dict[str, JsonValue] = {}

    def get_payload(self) -> dict[str, dict[str, JsonValue]]:
        """The request body: just what the fake saw."""
        return {"input": self.payload_attrs}

    def send_request(self) -> FakeResponse:
        """Pretend to submit the task."""
        self.payload_attrs = {
            name: self._kwargs.get(arg)
            for name, arg in (
                ("aspectRatio", "aspect_ratio"),
                ("resolution", "resolution"),
                ("duration", "length"),
                ("generateAudio", "generate_audio"),
            )
            if self._kwargs.get(arg) is not None
        }
        return FakeResponse({"code": "SUCCESS", "data": {"taskId": "task-1", "status": "waiting"}})


class FakeAudioGenerator:
    """A Pollo audio generator that records its call and answers with a task id."""

    api_key = "pollo-test"

    def __init__(self, calls: PolloCalls, key: str, attrs: dict[str, JsonValue], **kwargs: JsonValue) -> None:
        calls.generators.append((key, kwargs))
        self.payload_attrs = attrs

    def get_payload(self) -> dict[str, dict[str, JsonValue]]:
        """An empty request body."""
        return {"input": {}}

    def send_request(self) -> FakeResponse:
        """Pretend to submit the task."""
        return FakeResponse({"data": {"taskId": "task-1"}})


class RefusingGenerator:
    """A Pollo generator whose submit always gets ``reply`` back."""

    api_key = "k"

    def __init__(self, reply: FakeResponse) -> None:
        self._reply = reply
        self.payload_attrs: dict[str, JsonValue] = {}

    def get_payload(self) -> dict[str, dict[str, JsonValue]]:
        """An empty request body."""
        return {"input": {}}

    def send_request(self) -> FakeResponse:
        """The canned reply."""
        return self._reply


class InlineThread:
    """A stand-in for ``threading.Thread`` that runs its target as soon as it is started."""

    def __init__(self, target: Callable[..., None], args: Sequence[object] = (), **_kwargs: object) -> None:
        self._target = target
        self._args = args

    def start(self) -> None:
        """Run the target now, on the calling thread."""
        self._target(*self._args)


def by_id(models: list[ModelEntry]) -> dict[str, ModelEntry]:
    """Index catalogue entries by their ``id``."""
    return {jp.text(m, "id"): m for m in models}

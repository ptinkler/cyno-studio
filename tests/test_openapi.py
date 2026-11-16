"""The OpenAPI schema the frontend's types are generated from.

The turn routes stream events, which OpenAPI can't describe as a response body, so they publish the
event models under an event-stream media type instead.
"""

from web.api import app
from web.core.openapi import event_stream_only
from web.jsonutil import as_object
from web.types import JsonValue

EVENTS = ("StartEvent", "DeltaEvent", "MediaEvent", "CharactersEvent", "InstructionsEvent", "TitleEvent")
STREAM_ROUTES = (
    "/api/chat/conversations/{conv_id}/messages",
    "/api/chat/conversations/{conv_id}/retry",
    "/api/chat/conversations/{conv_id}/edit",
    "/api/chat/conversations/{conv_id}/reword",
)


def _content(path: str, method: str = "post") -> dict[str, JsonValue]:
    schema = as_object(app.openapi())
    operation = as_object(as_object(as_object(schema["paths"])[path])[method])
    return as_object(as_object(as_object(operation["responses"])["200"])["content"])


def test_turn_routes_are_event_streams_of_the_event_models() -> None:
    """Each streaming route is described only as an event stream that names every event."""
    for path in STREAM_ROUTES:
        content = _content(path)
        assert list(content) == ["text/event-stream"], path
        text = str(content["text/event-stream"])
        for name in EVENTS:
            assert f"#/components/schemas/{name}" in text, (path, name)


def test_the_event_models_are_in_the_schema() -> None:
    """The models are registered as components, so the frontend can generate types for them."""
    components = as_object(as_object(app.openapi())["components"])
    schemas = as_object(components["schemas"])
    for name in (*EVENTS, "ErrorEvent", "DoneEvent"):
        assert name in schemas


def test_other_responses_keep_their_json_body() -> None:
    """Only event streams lose the JSON body."""
    assert list(_content("/api/chat/status", "get")) == ["application/json"]


def test_event_stream_only_leaves_everything_else_alone() -> None:
    """Parameters, other methods and non-stream responses pass through unchanged."""
    json_body: JsonValue = {"schema": {"type": "object"}}
    schema: dict[str, JsonValue] = {
        "openapi": "3.1.0",
        "paths": {
            "/a": {
                "parameters": [{"name": "x", "in": "query"}],
                "post": {"responses": {"200": {"content": {"text/event-stream": {}, "application/json": json_body}}}},
                "get": {"responses": {"200": {"content": {"application/json": json_body}}}},
            }
        },
    }
    result = as_object(as_object(event_stream_only(schema))["paths"])
    item = as_object(result["/a"])
    assert item["parameters"] == [{"name": "x", "in": "query"}]
    assert item["get"] == as_object(as_object(schema["paths"])["/a"])["get"]
    post = as_object(as_object(as_object(as_object(item["post"])["responses"])["200"])["content"])
    assert list(post) == ["text/event-stream"]

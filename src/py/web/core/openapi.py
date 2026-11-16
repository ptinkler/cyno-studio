"""Post-processing of the generated OpenAPI schema."""

from collections.abc import Mapping

from web.jsonutil import as_object
from web.types import JsonValue

EVENT_STREAM = "text/event-stream"
JSON = "application/json"


def _response(response: JsonValue) -> JsonValue:
    """A response; for an event stream, without the JSON body FastAPI adds beside it."""
    body = as_object(response)
    content = as_object(body.get("content"))
    if EVENT_STREAM not in content:
        return response
    return {**body, "content": {media: schema for media, schema in content.items() if media != JSON}}


def _operation(operation: JsonValue) -> JsonValue:
    body = as_object(operation)
    if "responses" not in body:
        return operation
    responses = {status: _response(response) for status, response in as_object(body["responses"]).items()}
    return {**body, "responses": responses}


def event_stream_only(schema: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    """The schema with each event-stream response described only as an event stream.

    A streaming route lists its event models under `responses` so they reach the schema; FastAPI
    then also adds an `application/json` body for them, which the route never sends.
    """
    paths = {
        path: {method: _operation(operation) for method, operation in as_object(item).items()}
        for path, item in as_object(schema.get("paths")).items()
    }
    return {**schema, "paths": paths}

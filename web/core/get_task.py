"""Get task status from the Pollo API.

API Docs: https://docs.pollo.ai/task/get-task-status?playground=open
"""

import logging

import requests

from web.core.cloudflare import is_cloudflare_block
from web.core.config import POLLO_API_TIMEOUT, POLLO_PLATFORM_BASE, POLLO_TASK_BASE
from web.jsonutil import as_int, as_object, as_objects, as_str, body_of
from web.types import JsonValue

log = logging.getLogger(__name__)

# Each result tuple: (status, failMsg, url, credits)
TaskResult = tuple[str, str | None, str | None, int | None]


CLOUDFLARE_MESSAGE = "Cloudflare blocked the request — check your VPN or switch regions."


def get_task_status(task_id: str, api_key: str) -> list[TaskResult]:
    """Return one status result per task generation.

    Return a single ``("error", ...)`` or ``("cloudflare_blocked", ...)`` result
    when the status cannot be read.
    """
    url = f"{POLLO_TASK_BASE}/{task_id}/status"
    response = requests.request("GET", url, headers={"x-api-key": api_key}, timeout=POLLO_API_TIMEOUT)
    if is_cloudflare_block(response):
        return [("cloudflare_blocked", CLOUDFLARE_MESSAGE, None, None)]
    if response.status_code != 200:
        return [("error", _error_message(response), None, None)]
    try:
        data = as_object(as_object(body_of(response)).get("data"))
    except ValueError:
        return [("error", "Invalid JSON response", None, None)]

    # Generations come under "generations" or, in another response shape, "result"
    generations = as_objects(data.get("generations")) or as_objects(data.get("result"))
    if not generations:
        log.warning("task %s: no generations in the response", task_id)
        return [("error", "No generations found.", None, None)]
    results: list[TaskResult] = [
        (
            as_str(gen.get("status")) or "",
            as_str(gen.get("failMsg")),
            as_str(gen.get("url")) or as_str(gen.get("videoUrl")),
            _credit(gen.get("credit")),
        )
        for gen in generations
    ]
    # Only a task-level total: it goes on the first result
    top_credit = _credit(data.get("credit"))
    if top_credit and results[0][3] is None:
        results[0] = (*results[0][:3], top_credit)
    return results


def _error_message(response: requests.Response) -> str:
    """The first issue Pollo reports in an error response, else the HTTP status."""
    try:
        issues = as_objects(as_object(as_object(body_of(response)).get("data")).get("issues"))
    except ValueError:
        issues = []
    if issues:
        return as_str(issues[0].get("message")) or "No message provided."
    return f"HTTP {response.status_code}"


def _credit(value: JsonValue) -> int | None:
    """A credit count from the API (a string or an int), None if missing or unreadable."""
    if not isinstance(value, (int, float, str)):
        return None
    try:
        return int(value)
    except ValueError:
        return None


def get_credit_balance(api_key: str) -> dict[str, float] | None:
    """Fetch current credit balance from Pollo API.

    Returns {"availableCredits": N, "totalCredits": N} or None on failure.
    Credits are fractional (a job can cost 51.74), so these are floats.
    """
    headers = {"x-api-key": api_key}
    url = f"{POLLO_PLATFORM_BASE}/credit/balance"
    try:
        response = requests.get(url, headers=headers, timeout=POLLO_API_TIMEOUT)
        if response.status_code == 200:
            resp_json = as_object(body_of(response))
            # API wraps response in {"code":"SUCCESS","data":{...}}
            data = as_object(resp_json.get("data", resp_json))
            return {
                "availableCredits": as_int(data.get("availableCredits")) or 0,
                "totalCredits": as_int(data.get("totalCredits")) or 0,
            }
        log.warning("credit balance fetch returned HTTP %s from %s: %s", response.status_code, url, response.text[:300])
    except (requests.RequestException, ValueError) as e:
        log.warning("could not fetch the credit balance: %s", e)
    return None

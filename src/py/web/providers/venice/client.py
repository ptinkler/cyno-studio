"""The Venice HTTP client: base URL, auth header, error mapping, the shared connection, the balance."""

import contextlib
import json
import os
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from http import HTTPStatus

import httpx

from web.auth import keyctx
from web.core import request_log
from web.core.metadata import current_tenant
from web.jsonutil import as_object, as_str, body_of
from web.providers.openrouter import keepalive_socket_options
from web.providers.venice.catalogue import float_or_none
from web.providers.venice.errors import (
    AnswerTimeoutError,
    ApiKeyMissingError,
    ConnectionDroppedError,
    RequestRejectedError,
    VeniceError,
)
from web.types import JsonValue, VeniceBalances

VENICE_BASE = os.getenv("VENICE_BASE_URL", "https://api.venice.ai/api/v1").rstrip("/")


DEFAULT_TIMEOUT = httpx.Timeout(30)


http = httpx.Client(transport=httpx.HTTPTransport(socket_options=keepalive_socket_options()))


_balance: dict[str, float | None] = {}  # tenant -> the x-venice-balance-usd header's last value


def get_api_key() -> str:
    """Return the configured Venice API key, or an empty string."""
    return keyctx.provider_key("venice") or ""


def tenant() -> str:
    """Return the signed-in user that owns the per-account caches.

    Outside a request, return an empty string; background pollers use the
    owner's key for each job.
    """
    return current_tenant() or ""


def is_configured() -> bool:
    """Return whether a Venice API key is configured."""
    return bool(get_api_key())


def headers() -> dict[str, str]:
    """The auth header for the signed-in user's key (raises if they have none)."""
    key = get_api_key()
    if not key:
        raise ApiKeyMissingError
    return {"Authorization": f"Bearer {key}"}


def note_balance(resp: httpx.Response) -> None:
    """Remember the balance Venice reports in a reply's header, for this user."""
    value: str = resp.headers.get("x-venice-balance-usd") or ""
    if value:
        with contextlib.suppress(ValueError):
            _balance[tenant()] = float(value)


def _error_message(resp: httpx.Response) -> str | None:
    """Venice's own explanation of an error reply, if it gave one."""
    try:
        body = body_of(resp)
    except ValueError:
        return resp.text[:500]
    if not isinstance(body, Mapping):
        return resp.text[:500]
    err = body.get("error") or body.get("message") or body
    message = as_str(err.get("message")) if isinstance(err, Mapping) else str(err)
    details = body.get("details")
    if details and isinstance(details, (Mapping, list)):
        message = f"{message}: {json.dumps(details)[:300]}"
    return message


def raise_for_response(resp: httpx.Response) -> None:
    """Note the balance, then raise Venice's own message for an error reply."""
    note_balance(resp)
    if resp.status_code < HTTPStatus.BAD_REQUEST:
        return
    raise RequestRejectedError(_error_message(resp), resp.status_code)


@dataclass(frozen=True)
class Call:
    """One Venice API call: what is sent, how long to wait, and what the wait is for (named in the error)."""

    method: str
    path: str
    json_body: JsonValue = None
    params: dict[str, str] | None = None
    timeout: httpx.Timeout = field(default_factory=lambda: DEFAULT_TIMEOUT)  # Timeout is unhashable
    waiting_for: str = "response"


def request(call: Call, *, log: bool = False) -> httpx.Response:
    """One Venice call. `log`: record it in the request log (web/core/request_log.py)."""
    if not log:
        return _send(call)
    with request_log.logged("venice", call.method, call.path, call.json_body) as outcome:
        resp = _send(call, check=False)
        outcome["status"] = resp.status_code
        outcome["flags"] = {k: v for k, v in resp.headers.items() if k.startswith("x-venice-is-")}
        outcome["response"] = request_log.response_of(resp)
        raise_for_response(resp)
    return resp


def _send(call: Call, *, check: bool = True) -> httpx.Response:
    start = time.monotonic()
    try:
        resp = http.request(
            call.method,
            f"{VENICE_BASE}{call.path}",
            headers=headers(),
            timeout=call.timeout,
            json=call.json_body,
            params=call.params,
        )
    except (httpx.RemoteProtocolError, httpx.ReadError, httpx.WriteError, httpx.ConnectError) as e:
        raise ConnectionDroppedError(round(time.monotonic() - start), call.waiting_for, e) from e
    except httpx.TimeoutException as e:
        raise AnswerTimeoutError(e) from e
    if check:  # else the caller checks, after logging the response
        raise_for_response(resp)
    return resp


def get_balances() -> VeniceBalances:
    """Return the account's USD balance and bundled credits.

    Both values come from one rate-limits call. Venice spends BUNDLED_CREDITS
    after DIEM and before USD. The admin-only /billing/balance endpoint is not
    used; the USD figure
    lives in the body — not a response header, despite older API versions. If the
    endpoint can't be read, fall back to the balance a prior response's header
    reported for THIS user (via note_balance) — never another account's.
    """
    key = tenant()
    try:
        data = as_object(body_of(request(Call("GET", "/api_keys/rate_limits"))))
    except VeniceError:
        return {"usd": _balance.get(key), "credits": None}
    balances = as_object(as_object(data.get("data") or data).get("balances"))
    usd = float_or_none(balances.get("USD"))
    if usd is not None:
        _balance[key] = usd
    return {"usd": _balance.get(key), "credits": float_or_none(balances.get("BUNDLED_CREDITS"))}


def clear() -> None:
    """Forget the remembered balances."""
    _balance.clear()

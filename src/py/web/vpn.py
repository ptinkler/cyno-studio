"""Control VPN status and settings through Gluetun's API.

The routes expose status, restart and server-country controls, all talking to Gluetun's local control server.

Docs: https://github.com/qdm12/gluetun-wiki/blob/main/setup/advanced/control-server.md
"""

import json
import logging
import os
import time
from typing import Annotated

import httpx2
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from web.auth.users import require_admin
from web.core.metadata import User
from web.jsonutil import as_list, as_object, as_str, body_of
from web.types import JsonValue

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/vpn")

GLUETUN_API = "http://127.0.0.1:8000"
GLUETUN_API_KEY = os.getenv("GLUETUN_API_KEY", "")
_GLUETUN_HEADERS = {"X-API-Key": GLUETUN_API_KEY} if GLUETUN_API_KEY else {}

ALLOWED_VPN_COUNTRIES = [
    "United States",
    "United Kingdom",
    "Canada",
    "Australia",
    "Germany",
    "France",
    "Netherlands",
    "Japan",
    "Singapore",
    "Switzerland",
    "Sweden",
    "Brazil",
    "India",
    "South Korea",
    "Italy",
    "Spain",
    "Norway",
    "Denmark",
    "Ireland",
]


class VpnTunnel(BaseModel):
    """The tunnel's state as Gluetun reports it ("running", "stopped"; "unknown" / "unreachable" when it can't)."""

    status: str


class PublicIp(BaseModel):
    """The address the app reaches the internet from, and where that is."""

    ip: str | None
    country: str | None


class VpnStatus(BaseModel):
    """The tunnel, its exit address and the countries its servers are in."""

    vpn: VpnTunnel
    public_ip: PublicIp
    server_countries: list[str]


class VpnAction(BaseModel):
    """Whether a tunnel change was accepted, with a message to show."""

    ok: bool
    message: str


class VpnCountries(BaseModel):
    """The server countries that may be chosen."""

    countries: list[str]


class VpnCountryRequest(BaseModel):
    """Country requested for the VPN server."""

    country: str


def _gluetun_get(path: str, timeout: int = 3) -> httpx2.Response:
    return httpx2.get(f"{GLUETUN_API}{path}", headers=_GLUETUN_HEADERS, timeout=timeout)


def _gluetun_put(path: str, body: dict[str, JsonValue], timeout: int = 5) -> httpx2.Response:
    headers = {**_GLUETUN_HEADERS, "Content-Type": "application/json"}
    return httpx2.put(f"{GLUETUN_API}{path}", content=json.dumps(body), headers=headers, timeout=timeout)


def _gluetun_json(
    path: str,
    if_not_ok: dict[str, JsonValue],
    if_unreachable: dict[str, JsonValue],
    timeout: int = 3,
) -> dict[str, JsonValue]:
    """A Gluetun GET's JSON, or a stand-in when it fails or can't be reached."""
    try:
        r = _gluetun_get(path, timeout=timeout)
    except httpx2.HTTPError:  # any connection failure means unreachable
        return if_unreachable
    data = body_of(r)
    return as_object(data) if r.is_success and isinstance(data, dict) else if_not_ok


def _egress_ip() -> str | None:
    """The app's own egress IP, used when the control server reports none.

    In vpn mode the app shares gluetun's network, so this is the tunnel's exit IP.
    """
    for url in ("https://api.ipify.org", "https://icanhazip.com"):
        try:
            r = httpx2.get(url, timeout=6)
            if r.is_success and r.text.strip():
                return r.text.strip()
        except httpx2.HTTPError:
            log.debug("egress-IP lookup failed at %s; trying the next service", url, exc_info=True)
    return None


@router.get("/status")
def vpn_status(_admin: Annotated[User, Depends(require_admin)]) -> VpnStatus:
    """Current VPN status, public IP, and server country from Gluetun."""
    # Gluetun's /v1/publicip/ip returns the tunnel's exit IP under "public_ip"
    # (older builds used "ip"); normalise to {ip, country} for the UI.
    raw = _gluetun_json("/v1/publicip/ip", {}, {}, timeout=10)
    ip = as_str(raw.get("public_ip")) or as_str(raw.get("ip")) or _egress_ip()
    country = as_str(raw.get("country"))
    settings = _gluetun_json("/v1/vpn/settings", {}, {})
    # The public IP lookup's country stands in when settings name none
    countries = [c for c in as_list(settings.get("server_countries")) if isinstance(c, str)] or (
        [country] if country else []
    )
    tunnel = _gluetun_json("/v1/vpn/status", {"status": "unknown"}, {"status": "unreachable"})
    return VpnStatus(
        vpn=VpnTunnel(status=as_str(tunnel.get("status")) or "unknown"),
        public_ip=PublicIp(ip=ip, country=country),
        server_countries=countries,
    )


@router.post("/restart")
def vpn_restart(_admin: Annotated[User, Depends(require_admin)]) -> VpnAction:
    """Restart the VPN tunnel by cycling Gluetun's status off then on."""
    try:
        _gluetun_put("/v1/vpn/status", {"status": "stopped"})
        time.sleep(2)  # Gluetun needs a moment to tear the tunnel down before it is asked to start again
        r = _gluetun_put("/v1/vpn/status", {"status": "running"})
    except httpx2.HTTPError as e:
        raise HTTPException(502, detail=f"Cannot reach Gluetun control server: {e}") from e
    if r.is_success:
        return VpnAction(ok=True, message="VPN tunnel restarted — new IP in ~10s")
    return VpnAction(ok=False, message=f"Gluetun responded {r.status_code}")


@router.put("/country")
def vpn_change_country(data: VpnCountryRequest, _admin: Annotated[User, Depends(require_admin)]) -> VpnAction:
    """Change VPN server country. Body: {"country": "United Kingdom"}."""
    country = data.country.strip()
    if not country:
        raise HTTPException(400, detail="Missing 'country' field")
    if country not in ALLOWED_VPN_COUNTRIES:
        raise HTTPException(400, detail=f"Invalid country: '{country}'. Allowed: {', '.join(ALLOWED_VPN_COUNTRIES)}")
    try:
        r = _gluetun_put("/v1/vpn/settings", {"server_countries": [country]})
    except httpx2.HTTPError as e:
        raise HTTPException(502, detail=f"Cannot reach Gluetun control server: {e}") from e
    if not r.is_success:
        return VpnAction(ok=False, message=f"Gluetun responded {r.status_code}: {r.text}")
    return VpnAction(ok=True, message=f"Switching to {country} — new IP in ~10s")


@router.get("/countries")
def vpn_countries(_admin: Annotated[User, Depends(require_admin)]) -> VpnCountries:
    """The allowed VPN server countries."""
    return VpnCountries(countries=ALLOWED_VPN_COUNTRIES)

"""Admin routes for the pending-approval list of refused sign-ins."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from web.auth.users import require_admin
from web.core.metadata import SigninRequest, User, get_db, iso

router = APIRouter(prefix="/api/signin-requests")


class SigninRequestOut(BaseModel):
    """One refused sign-in."""

    identity: str  # provider:sub
    provider: str
    email: str | None
    name: str | None
    approved: bool
    last_seen: str | None


class SigninRequestList(BaseModel):
    """The whole list, newest first."""

    requests: list[SigninRequestOut]


def _out(row: SigninRequest) -> SigninRequestOut:
    return SigninRequestOut(
        identity=row.identity,
        provider=row.provider,
        email=row.email,
        name=row.name,
        approved=row.approved,
        last_seen=iso(row.last_seen),
    )


@router.get("")
def list_requests(_admin: Annotated[User, Depends(require_admin)]) -> SigninRequestList:
    """List refused sign-ins and the ones already approved."""
    return SigninRequestList(requests=[_out(r) for r in get_db().list_signin_requests()])


@router.post("/approve")
def approve(identity: str, _admin: Annotated[User, Depends(require_admin)]) -> SigninRequestList:
    """Let this sign-in in on its next attempt."""
    if not get_db().approve_signin_request(identity):
        raise HTTPException(status_code=404, detail="No such request")
    return list_requests(_admin)


@router.delete("")
def deny(identity: str, _admin: Annotated[User, Depends(require_admin)]) -> SigninRequestList:
    """Remove a request (deny it, or revoke an approval that was not yet used)."""
    if not get_db().delete_signin_request(identity):
        raise HTTPException(status_code=404, detail="No such request")
    return list_requests(_admin)

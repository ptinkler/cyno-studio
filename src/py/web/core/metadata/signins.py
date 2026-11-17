"""Refused sign-ins waiting for the admin, and the ones the admin let in."""

from datetime import datetime

from web.core.metadata._base import DBBase
from web.core.metadata.models import SigninRequest


def _now() -> datetime:
    return datetime.now().astimezone().replace(tzinfo=None)


class SigninMixin(DBBase):
    """Provide the pending-approval list for sign-ins no allow-list admitted."""

    def record_signin_request(self, identity: str, *, provider: str, email: str | None, name: str | None) -> None:
        """Remember a refused sign-in, or refresh the one already waiting."""
        with self._session() as session:
            row = session.get(SigninRequest, identity)
            if row:
                row.email, row.name, row.last_seen = email or row.email, name or row.name, _now()
            else:
                session.add(SigninRequest(identity=identity, provider=provider, email=email, name=name))
            session.commit()

    def signin_approved(self, identity: str) -> bool:
        """Return whether the admin has approved this ``provider:sub``."""
        with self._session() as session:
            row = session.get(SigninRequest, identity)
            return bool(row and row.approved)

    def list_signin_requests(self) -> list[SigninRequest]:
        """Return every request, newest first."""
        with self._session() as session:
            rows = session.query(SigninRequest).order_by(SigninRequest.last_seen.desc()).all()
            session.expunge_all()
            return rows

    def approve_signin_request(self, identity: str) -> bool:
        """Approve a request; return whether it existed."""
        with self._session() as session:
            row = session.get(SigninRequest, identity)
            if row:
                row.approved = True
                session.commit()
            return row is not None

    def delete_signin_request(self, identity: str) -> bool:
        """Deny (or revoke) a request; return whether it existed."""
        with self._session() as session:
            row = session.get(SigninRequest, identity)
            if row:
                session.delete(row)
                session.commit()
            return row is not None

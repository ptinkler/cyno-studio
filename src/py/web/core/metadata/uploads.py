"""Public upload URLs and their expiry, so dead ones can be scrubbed from what the app stored."""

from datetime import datetime

import sqlalchemy as sa

from web.core.metadata._base import DBBase
from web.core.metadata.models import ChatLibraryItem, ChatMessage, HostedUpload

_STORED_JSON = ((ChatMessage, ChatMessage.media_json), (ChatLibraryItem, ChatLibraryItem.item_json))


def _now() -> datetime:
    return datetime.now().astimezone().replace(tzinfo=None)


class UploadMixin(DBBase):
    """Track hosted upload URLs and blank the expired ones out of stored media."""

    def record_hosted_upload(self, url: str, expires_at: datetime) -> None:
        """Remember a URL until `expires_at` (a later upload of the same URL moves it)."""
        with self._session() as session:
            row = session.get(HostedUpload, url)
            if row:
                row.expires_at = max(row.expires_at, expires_at)
            else:
                session.add(HostedUpload(url=url, expires_at=expires_at))
            session.commit()

    def expired_hosted_uploads(self) -> list[str]:
        """The remembered URLs whose host has dropped the file by now."""
        with self._session() as session:
            rows = session.query(HostedUpload.url).filter(HostedUpload.expires_at <= _now()).all()
            return [r[0] for r in rows]

    def scrub_hosted_uploads(self, urls: list[str], placeholder: str) -> None:
        """Replace each URL in stored messages and library items, then forget it."""
        with self._session() as session:
            for url in urls:
                for model, column in (
                    (ChatMessage, ChatMessage.media_json),
                    (ChatLibraryItem, ChatLibraryItem.item_json),
                ):
                    session.execute(
                        sa.update(model)
                        .where(column.contains(url, autoescape=True))
                        .values({column.key: sa.func.replace(column, url, placeholder)})
                    )
                session.execute(sa.delete(HostedUpload).where(HostedUpload.url == url))
            session.commit()

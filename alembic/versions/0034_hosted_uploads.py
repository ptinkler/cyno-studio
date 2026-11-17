"""add hosted_uploads, public upload URLs awaiting expiry.

Revision ID: 0034
Revises: 0033
Create Date: 2026-11-17

Each URL a source file was uploaded to, with when its host drops it; a periodic job scrubs expired ones from
stored requests. downgrade() drops the table.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0034"
down_revision: str | Sequence[str] | None = "0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the table."""
    if not sa.inspect(op.get_bind()).has_table("hosted_uploads"):
        op.create_table(
            "hosted_uploads",
            sa.Column("url", sa.String(length=1000), primary_key=True),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_hosted_uploads_expires_at", "hosted_uploads", ["expires_at"])


def downgrade() -> None:
    """Drop the table."""
    op.drop_table("hosted_uploads")

"""add signin_requests, the admin's pending-approval list.

Revision ID: 0033
Revises: 0032
Create Date: 2026-11-17

A sign-in no allow-list admits is recorded here (keyed by provider:sub, since an X account has no email) so
the admin can approve it from Settings instead of editing .env. downgrade() drops the table.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0033"
down_revision: str | Sequence[str] | None = "0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the table."""
    if not sa.inspect(op.get_bind()).has_table("signin_requests"):
        op.create_table(
            "signin_requests",
            sa.Column("identity", sa.String(length=300), primary_key=True),
            sa.Column("provider", sa.String(length=32), nullable=False),
            sa.Column("email", sa.String(length=320), nullable=True),
            sa.Column("name", sa.String(length=255), nullable=True),
            sa.Column("approved", sa.Boolean(), nullable=False, server_default="0"),
            sa.Column("first_seen", sa.DateTime(), nullable=False),
            sa.Column("last_seen", sa.DateTime(), nullable=False),
        )


def downgrade() -> None:
    """Drop the table."""
    op.drop_table("signin_requests")

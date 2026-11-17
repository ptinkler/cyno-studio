"""let users.email be null.

Revision ID: 0032
Revises: 0031
Create Date: 2026-11-16

A sign-in that has no email (X) is an account without one, found by (provider, provider_sub), instead of one
with an invented address. The unique index stays: it allows any number of nulls. downgrade() fills any null
with a placeholder first, since the old column required a value.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0032"
down_revision: str | Sequence[str] | None = "0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _email_is_required() -> bool:
    column = next(c for c in sa.inspect(op.get_bind()).get_columns("users") if c["name"] == "email")
    return not column["nullable"]


def upgrade() -> None:
    """Allow a null email."""
    if _email_is_required():
        with op.batch_alter_table("users") as batch_op:
            batch_op.alter_column("email", existing_type=sa.String(length=320), nullable=True)


def downgrade() -> None:
    """Give every email-less account a placeholder, then require an email again."""
    op.execute(sa.text("UPDATE users SET email = id || '@no-email.invalid' WHERE email IS NULL"))
    if not _email_is_required():
        with op.batch_alter_table("users") as batch_op:
            batch_op.alter_column("email", existing_type=sa.String(length=320), nullable=False)

"""Добавляет уникальный email пользователя.

Revision ID: 20260906_0002
Revises: 20260906_0001
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260906_0002"
down_revision: str | None = "20260906_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("email", sa.String(length=320), nullable=False)
    )
    op.create_unique_constraint("uq_users_email", "users", ["email"])


def downgrade() -> None:
    op.drop_constraint("uq_users_email", "users", type_="unique")
    op.drop_column("users", "email")

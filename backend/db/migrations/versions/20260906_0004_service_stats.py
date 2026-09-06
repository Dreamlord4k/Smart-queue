"""Добавляет статистику фактического времени приёма.

Revision ID: 20260906_0004
Revises: 20260906_0003
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260906_0004"
down_revision: str | None = "20260906_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "service_stats",
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ema_estimate", sa.Float(), nullable=False),
        sa.Column("variance", sa.Float(), nullable=False),
        sa.Column("n_observations", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "ema_estimate >= 0", name="ck_service_stats_ema_nonnegative"
        ),
        sa.CheckConstraint(
            "variance >= 0", name="ck_service_stats_variance_nonnegative"
        ),
        sa.CheckConstraint(
            "n_observations > 0", name="ck_service_stats_observations_positive"
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["sessions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("session_id"),
    )


def downgrade() -> None:
    op.drop_table("service_stats")

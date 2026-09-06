"""Добавляет аудит перестановок очереди.

Revision ID: 20260906_0005
Revises: 20260906_0004
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260906_0005"
down_revision: str | None = "20260906_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "queue_move_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "queue_entry_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("moved_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("old_position", sa.Integer(), nullable=False),
        sa.Column("new_position", sa.Integer(), nullable=False),
        sa.Column(
            "moved_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "new_position > 0", name="ck_queue_move_logs_new_position_positive"
        ),
        sa.CheckConstraint(
            "old_position > 0", name="ck_queue_move_logs_old_position_positive"
        ),
        sa.ForeignKeyConstraint(
            ["moved_by"], ["users.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["queue_entry_id"], ["queue_entries.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_queue_move_logs_queue_entry_id",
        "queue_move_logs",
        ["queue_entry_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_queue_move_logs_queue_entry_id", table_name="queue_move_logs"
    )
    op.drop_table("queue_move_logs")

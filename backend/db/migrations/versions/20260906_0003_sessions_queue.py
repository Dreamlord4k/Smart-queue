"""Создаёт сессии и записи очереди.

Revision ID: 20260906_0003
Revises: 20260906_0002
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260906_0003"
down_revision: str | None = "20260906_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    session_status = postgresql.ENUM(
        "planned", "active", "paused", "closed", "cancelled", name="session_status"
    )
    queue_entry_status = postgresql.ENUM(
        "waiting", "called", "done", "skipped", "absent", name="queue_entry_status"
    )

    op.create_table(
        "sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("teacher_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("course_name", sa.String(length=255), nullable=False),
        sa.Column("room", sa.String(length=255), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("duration_default", sa.Integer(), nullable=False),
        sa.Column("capacity", sa.Integer(), server_default="1", nullable=False),
        sa.Column("status", session_status, server_default="planned", nullable=False),
        sa.Column("frozen", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "capacity > 0", name="ck_sessions_capacity_positive"
        ),
        sa.CheckConstraint(
            "duration_default > 0", name="ck_sessions_duration_positive"
        ),
        sa.ForeignKeyConstraint(["teacher_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "queue_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("student_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("status", queue_entry_status, server_default="waiting", nullable=False),
        sa.Column("locked", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("lock_reason", sa.Text(), nullable=True),
        sa.Column("absence_reason", sa.Text(), nullable=True),
        sa.Column("channel", sa.Integer(), nullable=True),
        sa.Column("called_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "channel IS NULL OR channel > 0", name="ck_queue_entries_channel_positive"
        ),
        sa.CheckConstraint(
            "position > 0", name="ck_queue_entries_position_positive"
        ),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["student_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "session_id", "student_id", name="uq_queue_session_student"
        ),
    )


def downgrade() -> None:
    op.drop_table("queue_entries")
    op.drop_table("sessions")
    postgresql.ENUM(name="queue_entry_status").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="session_status").drop(op.get_bind(), checkfirst=True)

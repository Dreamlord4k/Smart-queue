"""Добавляет Telegram-линковку и журнал уведомлений.

Revision ID: 20260907_0006
Revises: 20260906_0005
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260907_0006"
down_revision: str | None = "20260906_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    notification_type = postgresql.ENUM(
        "soft", "buffer", "hard_call", name="notification_type"
    )
    notification_status = postgresql.ENUM(
        "pending", "sent", "failed", name="notification_status"
    )

    op.create_table(
        "telegram_link_codes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_index(
        "ix_telegram_link_codes_user_id", "telegram_link_codes", ["user_id"]
    )

    op.create_table(
        "notification_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("queue_entry_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("recipient_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_key", sa.String(length=160), nullable=False),
        sa.Column("type", notification_type, nullable=False),
        sa.Column(
            "status", notification_status, server_default="pending", nullable=False
        ),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["queue_entry_id"], ["queue_entries.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["recipient_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "event_key", "recipient_id", name="uq_notification_event_recipient"
        ),
    )
    op.create_index(
        "ix_notification_logs_queue_entry_id",
        "notification_logs",
        ["queue_entry_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_notification_logs_queue_entry_id", table_name="notification_logs"
    )
    op.drop_table("notification_logs")
    op.drop_index(
        "ix_telegram_link_codes_user_id", table_name="telegram_link_codes"
    )
    op.drop_table("telegram_link_codes")
    postgresql.ENUM(name="notification_status").drop(
        op.get_bind(), checkfirst=True
    )
    postgresql.ENUM(name="notification_type").drop(op.get_bind(), checkfirst=True)

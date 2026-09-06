from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, Enum as SAEnum, ForeignKey, Integer, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.group import Base

if TYPE_CHECKING:
    from models.session import Session


class QueueEntryStatus(str, Enum):
    WAITING = "waiting"
    CALLED = "called"
    DONE = "done"
    SKIPPED = "skipped"
    ABSENT = "absent"


class QueueEntry(Base):
    __tablename__ = "queue_entries"
    __table_args__ = (
        UniqueConstraint("session_id", "student_id", name="uq_queue_session_student"),
        CheckConstraint("position > 0", name="ck_queue_entries_position_positive"),
        CheckConstraint("channel IS NULL OR channel > 0", name="ck_queue_entries_channel_positive"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    session_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    student_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[QueueEntryStatus] = mapped_column(
        SAEnum(
            QueueEntryStatus,
            name="queue_entry_status",
            values_callable=lambda enum: [item.value for item in enum],
        ),
        nullable=False,
        default=QueueEntryStatus.WAITING,
    )
    locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    lock_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    absence_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    channel: Mapped[int | None] = mapped_column(Integer, nullable=True)
    called_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    session: Mapped[Session] = relationship(back_populates="entries")

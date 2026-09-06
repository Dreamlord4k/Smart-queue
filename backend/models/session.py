from __future__ import annotations

from datetime import date, datetime, time
from enum import Enum
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, Enum as SAEnum, ForeignKey, Integer, String, Time, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.group import Base

if TYPE_CHECKING:
    from models.queue_entry import QueueEntry


class SessionStatus(str, Enum):
    PLANNED = "planned"
    ACTIVE = "active"
    PAUSED = "paused"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class Session(Base):
    __tablename__ = "sessions"
    __table_args__ = (
        CheckConstraint("duration_default > 0", name="ck_sessions_duration_positive"),
        CheckConstraint("capacity > 0", name="ck_sessions_capacity_positive"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    teacher_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    course_name: Mapped[str] = mapped_column(String(255), nullable=False)
    room: Mapped[str] = mapped_column(String(255), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    duration_default: Mapped[int] = mapped_column(Integer, nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[SessionStatus] = mapped_column(
        SAEnum(
            SessionStatus,
            name="session_status",
            values_callable=lambda enum: [item.value for item in enum],
        ),
        nullable=False,
        default=SessionStatus.PLANNED,
    )
    frozen: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    entries: Mapped[list[QueueEntry]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )

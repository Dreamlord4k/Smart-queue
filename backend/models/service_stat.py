from __future__ import annotations

from uuid import UUID

from sqlalchemy import CheckConstraint, Float, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.group import Base


class ServiceStat(Base):
    __tablename__ = "service_stats"
    __table_args__ = (
        CheckConstraint("ema_estimate >= 0", name="ck_service_stats_ema_nonnegative"),
        CheckConstraint("variance >= 0", name="ck_service_stats_variance_nonnegative"),
        CheckConstraint(
            "n_observations > 0", name="ck_service_stats_observations_positive"
        ),
    )

    session_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    ema_estimate: Mapped[float] = mapped_column(Float, nullable=False)
    variance: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    n_observations: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

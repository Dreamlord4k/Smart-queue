from __future__ import annotations

from datetime import date, datetime, time, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session as DatabaseSession

from backend.auth.dependencies import get_current_user, get_db, require_role
from backend.models.queue_entry import QueueEntry, QueueEntryStatus
from backend.models.session import Session, SessionStatus
from backend.models.user import User, UserRole
from backend.queue.eta import (
    ACTIVE_STATUSES,
    calculate_eta_ranges,
    normalize_active_positions,
)


router = APIRouter(tags=["queue"])


class AbsenceRequest(BaseModel):
    absence_reason: str | None = Field(default=None, max_length=2000)

    @field_validator("absence_reason")
    @classmethod
    def normalize_optional_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class EtaQueueEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    student_id: UUID
    position: int
    status: QueueEntryStatus
    eta_start: datetime | None = None
    eta_end: datetime | None = None


class AbsenceResponse(BaseModel):
    id: UUID
    session_id: UUID
    status: QueueEntryStatus
    absence_reason: str | None
    active_queue: list[EtaQueueEntryResponse]


class QueueStateEntryResponse(EtaQueueEntryResponse):
    student_name: str
    locked: bool
    lock_reason: str | None
    absence_reason: str | None


class QueueStateResponse(BaseModel):
    session_id: UUID
    entries: list[QueueStateEntryResponse]


class MyQueueResponse(BaseModel):
    entry_id: UUID
    session_id: UUID
    course_name: str
    teacher_name: str
    room: str
    date: date
    start_time: time
    position: int | None
    eta_start: datetime | None
    eta_end: datetime | None
    status: QueueEntryStatus


def _active_entries(db: DatabaseSession, session_id: UUID) -> list[QueueEntry]:
    return list(
        db.scalars(
            select(QueueEntry)
            .where(
                QueueEntry.session_id == session_id,
                QueueEntry.status.in_(ACTIVE_STATUSES),
            )
            .order_by(QueueEntry.position, QueueEntry.created_at, QueueEntry.id)
        ).all()
    )


def _eta_response(
    reception: Session, entries: list[QueueEntry]
) -> list[EtaQueueEntryResponse]:
    eta_ranges = calculate_eta_ranges(reception, entries)
    return [
        EtaQueueEntryResponse(
            id=entry.id,
            student_id=entry.student_id,
            position=entry.position,
            status=entry.status,
            eta_start=eta_ranges.get(entry.id, (None, None))[0],
            eta_end=eta_ranges.get(entry.id, (None, None))[1],
        )
        for entry in entries
    ]


@router.post(
    "/students/me/queues/{entry_id}/absence", response_model=AbsenceResponse
)
def mark_absent(
    entry_id: UUID,
    payload: AbsenceRequest,
    student: User = Depends(require_role(UserRole.STUDENT)),
    db: DatabaseSession = Depends(get_db),
) -> AbsenceResponse:
    entry = db.scalar(
        select(QueueEntry).where(QueueEntry.id == entry_id).with_for_update()
    )
    if entry is None:
        raise HTTPException(status_code=404, detail="Запись очереди не найдена")
    if entry.student_id != student.id:
        raise HTTPException(status_code=403, detail="Можно изменить только свою запись")
    if entry.status not in ACTIVE_STATUSES:
        raise HTTPException(status_code=409, detail="Запись уже не входит в активную очередь")

    reception = db.get(Session, entry.session_id)
    if reception is None:
        raise HTTPException(status_code=404, detail="Сессия не найдена")

    released_channel = entry.channel if entry.status == QueueEntryStatus.CALLED else None
    entry.status = QueueEntryStatus.ABSENT
    entry.absence_reason = payload.absence_reason
    entry.channel = None
    db.flush()

    active_entries = _active_entries(db, reception.id)
    normalize_active_positions(active_entries)

    if released_channel is not None:
        next_entry = next(
            (
                candidate
                for candidate in active_entries
                if candidate.status == QueueEntryStatus.WAITING
            ),
            None,
        )
        if next_entry is not None:
            next_entry.status = QueueEntryStatus.CALLED
            next_entry.channel = released_channel
            next_entry.called_at = datetime.now(timezone.utc)

    db.commit()
    return AbsenceResponse(
        id=entry.id,
        session_id=entry.session_id,
        status=entry.status,
        absence_reason=entry.absence_reason,
        active_queue=_eta_response(reception, active_entries),
    )


@router.get("/students/me/queues", response_model=list[MyQueueResponse])
def list_my_queues(
    student: User = Depends(require_role(UserRole.STUDENT)),
    db: DatabaseSession = Depends(get_db),
) -> list[MyQueueResponse]:
    rows = db.execute(
        select(QueueEntry, Session, User)
        .join(Session, QueueEntry.session_id == Session.id)
        .join(User, Session.teacher_id == User.id)
        .where(
            QueueEntry.student_id == student.id,
            Session.status.in_(
                (SessionStatus.PLANNED, SessionStatus.ACTIVE, SessionStatus.PAUSED)
            ),
        )
        .order_by(Session.date, Session.start_time, Session.id)
    ).all()

    cards: list[MyQueueResponse] = []
    for entry, reception, teacher in rows:
        active_entries = _active_entries(db, reception.id)
        eta_range = calculate_eta_ranges(reception, active_entries).get(entry.id)
        cards.append(
            MyQueueResponse(
                entry_id=entry.id,
                session_id=reception.id,
                course_name=reception.course_name,
                teacher_name=teacher.full_name,
                room=reception.room,
                date=reception.date,
                start_time=reception.start_time,
                position=entry.position if entry.status in ACTIVE_STATUSES else None,
                eta_start=eta_range[0] if eta_range else None,
                eta_end=eta_range[1] if eta_range else None,
                status=entry.status,
            )
        )
    return cards


@router.get("/sessions/{session_id}/queue", response_model=QueueStateResponse)
def get_queue_state(
    session_id: UUID,
    current_user: User = Depends(get_current_user),
    db: DatabaseSession = Depends(get_db),
) -> QueueStateResponse:
    reception = db.get(Session, session_id)
    if reception is None:
        raise HTTPException(status_code=404, detail="Сессия не найдена")

    is_owner = (
        current_user.role == UserRole.TEACHER
        and reception.teacher_id == current_user.id
    )
    is_participant = db.scalar(
        select(QueueEntry.id).where(
            QueueEntry.session_id == session_id,
            QueueEntry.student_id == current_user.id,
        )
    )
    if not is_owner and is_participant is None:
        raise HTTPException(status_code=403, detail="Нет доступа к этой очереди")

    rows = db.execute(
        select(QueueEntry, User)
        .join(User, QueueEntry.student_id == User.id)
        .where(QueueEntry.session_id == session_id)
        .order_by(QueueEntry.position, QueueEntry.created_at, QueueEntry.id)
    ).all()
    active_entries = [entry for entry, _ in rows if entry.status in ACTIVE_STATUSES]
    eta_ranges = calculate_eta_ranges(reception, active_entries)
    entries = [
        QueueStateEntryResponse(
            id=entry.id,
            student_id=entry.student_id,
            student_name=student.full_name,
            position=entry.position,
            status=entry.status,
            locked=entry.locked,
            lock_reason=entry.lock_reason if is_owner else None,
            absence_reason=entry.absence_reason if is_owner else None,
            eta_start=eta_ranges.get(entry.id, (None, None))[0],
            eta_end=eta_ranges.get(entry.id, (None, None))[1],
        )
        for entry, student in rows
    ]
    return QueueStateResponse(session_id=session_id, entries=entries)

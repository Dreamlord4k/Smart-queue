from __future__ import annotations

from datetime import date, datetime, time, timezone
from enum import Enum
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session as DatabaseSession

from backend.auth.dependencies import get_current_user, get_db, require_role
from backend.logging_config import log_operation, log_route_errors
from backend.models.queue_entry import QueueEntry, QueueEntryStatus
from backend.models.queue_move_log import QueueMoveLog
from backend.models.service_stat import ServiceStat
from backend.models.session import Session, SessionStatus
from backend.models.user import User, UserRole
from backend.queue.eta import (
    ACTIVE_STATUSES,
    calculate_eta_ranges,
    normalize_active_positions,
    update_ema,
)
from backend.realtime.events import publish_session_event


router = APIRouter(tags=["queue"])


class QueuePlacement(str, Enum):
    BEFORE = "before"
    AFTER = "after"


class AbsenceRequest(BaseModel):
    absence_reason: str | None = Field(default=None, max_length=2000)

    @field_validator("absence_reason")
    @classmethod
    def normalize_optional_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class ReorderRequest(BaseModel):
    entry_id: UUID
    target_entry_id: UUID | None = None
    placement: QueuePlacement


class LockRequest(BaseModel):
    locked: bool
    lock_reason: str | None = Field(default=None, max_length=2000)

    @field_validator("lock_reason")
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


class ReorderResponse(BaseModel):
    entry_id: UUID
    old_position: int
    new_position: int
    moved_at: datetime
    active_queue: list[EtaQueueEntryResponse]


class LockResponse(BaseModel):
    id: UUID
    session_id: UUID
    status: QueueEntryStatus
    locked: bool
    lock_reason: str | None
    absence_reason: str | None
    active_queue: list[EtaQueueEntryResponse]


class QueueTransitionResponse(BaseModel):
    id: UUID
    session_id: UUID
    status: QueueEntryStatus
    released_channel: int
    next_entry_id: UUID | None
    ema_estimate: float | None
    variance: float | None
    n_observations: int
    active_queue: list[EtaQueueEntryResponse]


class QueueStateEntryResponse(EtaQueueEntryResponse):
    student_name: str
    channel: int | None
    called_at: datetime | None
    locked: bool
    lock_reason: str | None
    absence_reason: str | None


class QueueStateResponse(BaseModel):
    session_id: UUID
    frozen: bool
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


def _active_entries(
    db: DatabaseSession, session_id: UUID, *, lock: bool = False
) -> list[QueueEntry]:
    statement = (
        select(QueueEntry)
        .where(
            QueueEntry.session_id == session_id,
            QueueEntry.status.in_(ACTIVE_STATUSES),
        )
        .order_by(QueueEntry.position, QueueEntry.created_at, QueueEntry.id)
    )
    if lock:
        statement = statement.with_for_update()
    return list(db.scalars(statement).all())


def _eta_response(
    db: DatabaseSession, reception: Session, entries: list[QueueEntry]
) -> list[EtaQueueEntryResponse]:
    service_stat = db.get(ServiceStat, reception.id)
    eta_ranges = calculate_eta_ranges(
        reception,
        entries,
        ema_estimate=service_stat.ema_estimate if service_stat else None,
        variance=service_stat.variance if service_stat else 0.0,
    )
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


def _lock_reception_and_entry(
    db: DatabaseSession, entry_id: UUID
) -> tuple[Session, QueueEntry]:
    existing_entry = db.get(QueueEntry, entry_id)
    if existing_entry is None:
        raise HTTPException(status_code=404, detail="Запись очереди не найдена")

    reception = db.scalar(
        select(Session)
        .where(Session.id == existing_entry.session_id)
        .with_for_update()
    )
    if reception is None:
        raise HTTPException(status_code=404, detail="Сессия не найдена")

    entry = db.scalar(
        select(QueueEntry).where(QueueEntry.id == entry_id).with_for_update()
    )
    if entry is None:
        raise HTTPException(status_code=404, detail="Запись очереди не найдена")
    return reception, entry


def _call_next(
    active_entries: list[QueueEntry], channel: int, called_at: datetime
) -> QueueEntry | None:
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
        next_entry.channel = channel
        next_entry.called_at = called_at
    return next_entry


def _update_service_stat(
    db: DatabaseSession,
    reception: Session,
    real_time: float,
) -> ServiceStat:
    service_stat = db.scalar(
        select(ServiceStat)
        .where(ServiceStat.session_id == reception.id)
        .with_for_update()
    )
    previous_ema = service_stat.ema_estimate if service_stat else None
    previous_variance = service_stat.variance if service_stat else 0.0
    ema_estimate, variance = update_ema(
        previous_ema, previous_variance, real_time
    )
    if service_stat is None:
        service_stat = ServiceStat(
            session_id=reception.id,
            ema_estimate=ema_estimate,
            variance=variance,
            n_observations=1,
        )
        db.add(service_stat)
    else:
        service_stat.ema_estimate = ema_estimate
        service_stat.variance = variance
        service_stat.n_observations += 1
    return service_stat


def _owned_waiting_entry(
    db: DatabaseSession,
    session_id: UUID,
    entry_id: UUID,
    student: User,
) -> tuple[Session, QueueEntry]:
    reception = db.scalar(
        select(Session).where(Session.id == session_id).with_for_update()
    )
    if reception is None:
        raise HTTPException(status_code=404, detail="Сессия не найдена")

    entry = db.scalar(
        select(QueueEntry)
        .where(
            QueueEntry.id == entry_id,
            QueueEntry.session_id == session_id,
        )
        .with_for_update()
    )
    if entry is None:
        raise HTTPException(status_code=404, detail="Запись очереди не найдена")
    if entry.student_id != student.id:
        raise HTTPException(status_code=403, detail="Можно изменить только свою запись")
    if entry.status != QueueEntryStatus.WAITING:
        raise HTTPException(
            status_code=409, detail="Изменять можно только ожидающую запись"
        )
    return reception, entry


def _transition_called_entry(
    session_id: UUID,
    entry_id: UUID,
    target_status: QueueEntryStatus,
    teacher: User,
    db: DatabaseSession,
) -> QueueTransitionResponse:
    reception = db.scalar(
        select(Session).where(Session.id == session_id).with_for_update()
    )
    if reception is None:
        raise HTTPException(status_code=404, detail="Сессия не найдена")
    if reception.teacher_id != teacher.id:
        raise HTTPException(
            status_code=403, detail="Управлять приёмом может только владелец сессии"
        )
    if reception.status != SessionStatus.ACTIVE:
        raise HTTPException(
            status_code=409, detail="Завершать приём можно только в активной сессии"
        )

    entry = db.scalar(
        select(QueueEntry)
        .where(
            QueueEntry.id == entry_id,
            QueueEntry.session_id == session_id,
        )
        .with_for_update()
    )
    if entry is None:
        raise HTTPException(status_code=404, detail="Запись очереди не найдена")
    if entry.status != QueueEntryStatus.CALLED or entry.channel is None:
        raise HTTPException(
            status_code=409,
            detail="Завершить или пропустить можно только текущую запись канала",
        )
    if not 1 <= entry.channel <= reception.capacity:
        raise HTTPException(status_code=409, detail="У записи некорректный канал")

    previous_stat = db.get(ServiceStat, reception.id)
    ema_before = previous_stat.ema_estimate if previous_stat else None
    position_before = entry.position
    now = datetime.now(timezone.utc)
    released_channel = entry.channel
    service_stat: ServiceStat | None = None
    if target_status == QueueEntryStatus.DONE:
        if entry.called_at is None:
            raise HTTPException(
                status_code=409, detail="У текущей записи отсутствует время вызова"
            )
        called_at = entry.called_at
        if called_at.tzinfo is None:
            called_at = called_at.replace(tzinfo=timezone.utc)
        real_time = max((now - called_at).total_seconds(), 0.0)
        entry.finished_at = now
        service_stat = _update_service_stat(db, reception, real_time)

    entry.status = target_status
    entry.channel = None
    db.flush()

    active_entries = _active_entries(db, reception.id, lock=True)
    normalize_active_positions(active_entries)
    next_entry = _call_next(active_entries, released_channel, now)
    db.flush()

    if service_stat is None:
        service_stat = db.get(ServiceStat, reception.id)
    response = QueueTransitionResponse(
        id=entry.id,
        session_id=reception.id,
        status=entry.status,
        released_channel=released_channel,
        next_entry_id=next_entry.id if next_entry else None,
        ema_estimate=service_stat.ema_estimate if service_stat else None,
        variance=service_stat.variance if service_stat else None,
        n_observations=service_stat.n_observations if service_stat else 0,
        active_queue=_eta_response(db, reception, active_entries),
    )
    db.commit()
    publish_session_event(
        reception.id,
        "queue.done"
        if target_status == QueueEntryStatus.DONE
        else "queue.skipped",
    )
    log_operation(
        "queue.done" if target_status == QueueEntryStatus.DONE else "queue.skipped",
        session_id=reception.id,
        entry_id=entry.id,
        actor_id=teacher.id,
        position_before=position_before,
        released_channel=released_channel,
        next_entry_id=next_entry.id if next_entry else None,
        ema_before=ema_before,
        ema_after=service_stat.ema_estimate if service_stat else None,
    )
    return response


@router.patch(
    "/sessions/{session_id}/queue/reorder", response_model=ReorderResponse
)
@log_route_errors("queue.reordered")
def reorder_own_entry(
    session_id: UUID,
    payload: ReorderRequest,
    student: User = Depends(require_role(UserRole.STUDENT)),
    db: DatabaseSession = Depends(get_db),
) -> ReorderResponse:
    reception, entry = _owned_waiting_entry(
        db, session_id, payload.entry_id, student
    )
    if entry.locked:
        raise HTTPException(
            status_code=409,
            detail="Сначала снимите фиксацию со своей записи",
        )
    if reception.frozen:
        raise HTTPException(
            status_code=409, detail="Порядок этой сессии уже заморожен"
        )

    active_entries = _active_entries(db, session_id, lock=True)
    source = next(
        (candidate for candidate in active_entries if candidate.id == entry.id),
        None,
    )
    if source is None:
        raise HTTPException(
            status_code=409, detail="Запись уже не входит в активную очередь"
        )

    movable_entries = [
        candidate
        for candidate in active_entries
        if not candidate.locked and candidate.id != source.id
    ]
    if payload.target_entry_id is None:
        insert_at = len(movable_entries)
    else:
        if payload.target_entry_id == source.id:
            raise HTTPException(
                status_code=409, detail="Исходная и целевая записи совпадают"
            )
        target = next(
            (
                candidate
                for candidate in active_entries
                if candidate.id == payload.target_entry_id
            ),
            None,
        )
        if target is None:
            raise HTTPException(status_code=404, detail="Целевая запись не найдена")
        if target.status != QueueEntryStatus.WAITING:
            raise HTTPException(
                status_code=409,
                detail="Переставлять запись можно только среди ожидающих",
            )
        if target.locked:
            raise HTTPException(
                status_code=409, detail="Целевое место зафиксировано"
            )
        target_index = movable_entries.index(target)
        insert_at = target_index + (
            1 if payload.placement == QueuePlacement.AFTER else 0
        )

    movable_entries.insert(insert_at, source)
    movable = iter(movable_entries)
    reordered = [
        candidate if candidate.locked else next(movable)
        for candidate in active_entries
    ]

    old_position = source.position
    new_position = reordered.index(source) + 1
    if new_position == old_position:
        raise HTTPException(
            status_code=409, detail="Запрошенная перестановка не меняет порядок"
        )

    for position, candidate in enumerate(reordered, start=1):
        candidate.position = position
    move_log = QueueMoveLog(
        queue_entry_id=source.id,
        moved_by=student.id,
        old_position=old_position,
        new_position=source.position,
    )
    db.add(move_log)
    db.flush()
    db.refresh(move_log)

    response = ReorderResponse(
        entry_id=source.id,
        old_position=old_position,
        new_position=source.position,
        moved_at=move_log.moved_at,
        active_queue=_eta_response(db, reception, reordered),
    )
    db.commit()
    publish_session_event(reception.id, "queue.reordered")
    log_operation(
        "queue.reordered",
        session_id=reception.id,
        entry_id=source.id,
        actor_id=student.id,
        position_before=old_position,
        position_after=source.position,
    )
    return response


@router.patch(
    "/sessions/{session_id}/queue/{entry_id}/lock",
    response_model=LockResponse,
)
@log_route_errors("queue.locked")
def set_own_entry_lock(
    session_id: UUID,
    entry_id: UUID,
    payload: LockRequest,
    student: User = Depends(require_role(UserRole.STUDENT)),
    db: DatabaseSession = Depends(get_db),
) -> LockResponse:
    reception, entry = _owned_waiting_entry(db, session_id, entry_id, student)
    locked_before = entry.locked
    entry.locked = payload.locked
    entry.lock_reason = payload.lock_reason if payload.locked else None
    db.flush()

    active_entries = _active_entries(db, reception.id, lock=True)
    response = LockResponse(
        id=entry.id,
        session_id=entry.session_id,
        status=entry.status,
        locked=entry.locked,
        lock_reason=entry.lock_reason,
        absence_reason=entry.absence_reason,
        active_queue=_eta_response(db, reception, active_entries),
    )
    db.commit()
    publish_session_event(reception.id, "queue.locked")
    log_operation(
        "queue.locked",
        session_id=reception.id,
        entry_id=entry.id,
        actor_id=student.id,
        locked_before=locked_before,
        locked_after=entry.locked,
    )
    return response


@router.post(
    "/sessions/{session_id}/queue/{entry_id}/done",
    response_model=QueueTransitionResponse,
)
@log_route_errors("queue.done")
def finish_current(
    session_id: UUID,
    entry_id: UUID,
    teacher: User = Depends(require_role(UserRole.TEACHER)),
    db: DatabaseSession = Depends(get_db),
) -> QueueTransitionResponse:
    return _transition_called_entry(
        session_id, entry_id, QueueEntryStatus.DONE, teacher, db
    )


@router.post(
    "/sessions/{session_id}/queue/{entry_id}/skip",
    response_model=QueueTransitionResponse,
)
@log_route_errors("queue.skipped")
def skip_current(
    session_id: UUID,
    entry_id: UUID,
    teacher: User = Depends(require_role(UserRole.TEACHER)),
    db: DatabaseSession = Depends(get_db),
) -> QueueTransitionResponse:
    return _transition_called_entry(
        session_id, entry_id, QueueEntryStatus.SKIPPED, teacher, db
    )


@router.post(
    "/students/me/queues/{entry_id}/absence", response_model=AbsenceResponse
)
@log_route_errors("queue.absent")
def mark_absent(
    entry_id: UUID,
    payload: AbsenceRequest,
    student: User = Depends(require_role(UserRole.STUDENT)),
    db: DatabaseSession = Depends(get_db),
) -> AbsenceResponse:
    reception, entry = _lock_reception_and_entry(db, entry_id)
    if entry.student_id != student.id:
        raise HTTPException(status_code=403, detail="Можно изменить только свою запись")
    if entry.status not in ACTIVE_STATUSES:
        raise HTTPException(status_code=409, detail="Запись уже не входит в активную очередь")

    position_before = entry.position
    status_before = entry.status.value
    released_channel = entry.channel if entry.status == QueueEntryStatus.CALLED else None
    entry.status = QueueEntryStatus.ABSENT
    entry.absence_reason = payload.absence_reason
    entry.channel = None
    db.flush()

    active_entries = _active_entries(db, reception.id)
    normalize_active_positions(active_entries)

    if released_channel is not None:
        _call_next(active_entries, released_channel, datetime.now(timezone.utc))

    response = AbsenceResponse(
        id=entry.id,
        session_id=entry.session_id,
        status=entry.status,
        absence_reason=entry.absence_reason,
        active_queue=_eta_response(db, reception, active_entries),
    )
    db.commit()
    publish_session_event(reception.id, "queue.absent")
    log_operation(
        "queue.absent",
        session_id=reception.id,
        entry_id=entry.id,
        actor_id=student.id,
        position_before=position_before,
        status_before=status_before,
        released_channel=released_channel,
    )
    return response


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
        service_stat = db.get(ServiceStat, reception.id)
        eta_range = calculate_eta_ranges(
            reception,
            active_entries,
            ema_estimate=service_stat.ema_estimate if service_stat else None,
            variance=service_stat.variance if service_stat else 0.0,
        ).get(entry.id)
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
    service_stat = db.get(ServiceStat, reception.id)
    eta_ranges = calculate_eta_ranges(
        reception,
        active_entries,
        ema_estimate=service_stat.ema_estimate if service_stat else None,
        variance=service_stat.variance if service_stat else 0.0,
    )
    entries = [
        QueueStateEntryResponse(
            id=entry.id,
            student_id=entry.student_id,
            student_name=student.full_name,
            position=entry.position,
            status=entry.status,
            channel=entry.channel,
            called_at=entry.called_at,
            locked=entry.locked,
            lock_reason=entry.lock_reason if is_owner else None,
            absence_reason=entry.absence_reason if is_owner else None,
            eta_start=eta_ranges.get(entry.id, (None, None))[0],
            eta_end=eta_ranges.get(entry.id, (None, None))[1],
        )
        for entry, student in rows
    ]
    return QueueStateResponse(
        session_id=session_id,
        frozen=reception.frozen,
        entries=entries,
    )

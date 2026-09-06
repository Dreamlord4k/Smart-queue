from datetime import date, datetime, time, timezone
from math import ceil
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session as DatabaseSession

from backend.auth.dependencies import get_db, require_role
from backend.models.group import Group
from backend.models.queue_entry import QueueEntry, QueueEntryStatus
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


router = APIRouter(prefix="/sessions", tags=["sessions"])

ALLOWED_STATUS_TRANSITIONS = {
    SessionStatus.PLANNED: {SessionStatus.ACTIVE, SessionStatus.CANCELLED},
    SessionStatus.ACTIVE: {
        SessionStatus.PAUSED,
        SessionStatus.CLOSED,
        SessionStatus.CANCELLED,
    },
    SessionStatus.PAUSED: {
        SessionStatus.ACTIVE,
        SessionStatus.CLOSED,
        SessionStatus.CANCELLED,
    },
    SessionStatus.CLOSED: set(),
    SessionStatus.CANCELLED: set(),
}


class CreateSessionRequest(BaseModel):
    course_name: str = Field(min_length=1, max_length=255)
    room: str = Field(min_length=1, max_length=255)
    date: date
    start_time: time
    duration_default: int = Field(gt=0)
    capacity: int = Field(default=1, gt=0)
    group_ids: list[UUID] = Field(default_factory=list)
    student_ids: list[UUID] = Field(default_factory=list)

    @field_validator("course_name", "room")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("Поле не может быть пустым")
        return normalized


class QueueEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    student_id: UUID
    position: int
    status: QueueEntryStatus


class SessionResponse(BaseModel):
    id: UUID
    teacher_id: UUID
    course_name: str
    room: str
    date: date
    start_time: time
    duration_default: int
    capacity: int
    status: SessionStatus
    frozen: bool
    created_at: datetime
    queue: list[QueueEntryResponse]


class FreezeResponse(BaseModel):
    id: UUID
    frozen: bool


class SessionSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    teacher_id: UUID
    course_name: str
    room: str
    date: date
    start_time: time
    duration_default: int
    capacity: int
    status: SessionStatus
    frozen: bool
    created_at: datetime


class SessionReportResponse(BaseModel):
    accepted_count: int
    skipped_count: int
    average_service_seconds: float | None
    planned_duration_seconds: float
    actual_duration_seconds: float | None
    average_eta_error_seconds: float | None


class UpdateSessionRequest(BaseModel):
    status: SessionStatus | None = None
    duration_default: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def require_change(self) -> "UpdateSessionRequest":
        if self.status is None and self.duration_default is None:
            raise ValueError("Нужно передать status или duration_default")
        return self


class UpdateSessionResponse(SessionSummaryResponse):
    report: SessionReportResponse | None = None


class AddParticipantRequest(BaseModel):
    student_id: UUID


class EtaQueueEntryResponse(QueueEntryResponse):
    eta_start: datetime | None = None
    eta_end: datetime | None = None


class ParticipantMutationResponse(BaseModel):
    session_id: UUID
    entry_id: UUID
    active_queue: list[EtaQueueEntryResponse]


def _load_participants(
    payload: CreateSessionRequest, db: DatabaseSession
) -> list[User]:
    group_ids = set(payload.group_ids)
    if group_ids:
        existing_group_ids = set(
            db.scalars(select(Group.id).where(Group.id.in_(group_ids))).all()
        )
        if existing_group_ids != group_ids:
            raise HTTPException(status_code=422, detail="Одна или несколько групп не найдены")

    explicit_ids = set(payload.student_ids)
    explicit_students = []
    if explicit_ids:
        explicit_students = list(
            db.scalars(
                select(User).where(
                    User.id.in_(explicit_ids), User.role == UserRole.STUDENT
                )
            ).all()
        )
        if {student.id for student in explicit_students} != explicit_ids:
            raise HTTPException(
                status_code=422,
                detail="Явный список содержит неизвестного пользователя или преподавателя",
            )

    group_students = []
    if group_ids:
        group_students = list(
            db.scalars(
                select(User).where(
                    User.group_id.in_(group_ids), User.role == UserRole.STUDENT
                )
            ).all()
        )

    unique_students = {
        student.id: student for student in [*group_students, *explicit_students]
    }
    return sorted(
        unique_students.values(),
        key=lambda student: (student.full_name.casefold(), student.id.int),
    )


def _owned_session(
    session_id: UUID,
    teacher: User,
    db: DatabaseSession,
) -> Session:
    reception = db.scalar(
        select(Session).where(Session.id == session_id).with_for_update()
    )
    if reception is None:
        raise HTTPException(status_code=404, detail="Сессия не найдена")
    if reception.teacher_id != teacher.id:
        raise HTTPException(
            status_code=403, detail="Управлять может только владелец сессии"
        )
    return reception


def _active_entries(
    session_id: UUID,
    db: DatabaseSession,
    *,
    lock: bool = False,
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


def _eta_queue(
    reception: Session,
    entries: list[QueueEntry],
    db: DatabaseSession,
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


def _fill_free_channels(
    reception: Session,
    entries: list[QueueEntry],
    called_at: datetime,
) -> None:
    used_channels = {
        entry.channel
        for entry in entries
        if entry.status == QueueEntryStatus.CALLED and entry.channel is not None
    }
    waiting = iter(
        entry for entry in entries if entry.status == QueueEntryStatus.WAITING
    )
    for channel in range(1, reception.capacity + 1):
        if channel in used_channels:
            continue
        entry = next(waiting, None)
        if entry is None:
            break
        entry.status = QueueEntryStatus.CALLED
        entry.channel = channel
        entry.called_at = called_at


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _session_report(
    reception: Session,
    entries: list[QueueEntry],
) -> SessionReportResponse:
    completed = sorted(
        (
            entry
            for entry in entries
            if entry.status == QueueEntryStatus.DONE
            and entry.called_at is not None
            and entry.finished_at is not None
        ),
        key=lambda entry: (_aware(entry.called_at), _aware(entry.finished_at), entry.id),
    )
    durations = [
        max(
            (_aware(entry.finished_at) - _aware(entry.called_at)).total_seconds(),
            0.0,
        )
        for entry in completed
    ]

    predicted_duration = float(reception.duration_default * 60)
    previous_ema: float | None = None
    previous_variance = 0.0
    eta_errors: list[float] = []
    for actual_duration in durations:
        eta_errors.append(abs(actual_duration - predicted_duration))
        previous_ema, previous_variance = update_ema(
            previous_ema, previous_variance, actual_duration
        )
        predicted_duration = previous_ema

    actual_duration: float | None = None
    if completed:
        actual_duration = max(
            (
                _aware(completed[-1].finished_at)
                - _aware(completed[0].called_at)
            ).total_seconds(),
            0.0,
        )
    planned_waves = ceil(len(entries) / reception.capacity) if entries else 0
    return SessionReportResponse(
        accepted_count=sum(
            entry.status == QueueEntryStatus.DONE for entry in entries
        ),
        skipped_count=sum(
            entry.status == QueueEntryStatus.SKIPPED for entry in entries
        ),
        average_service_seconds=(
            sum(durations) / len(durations) if durations else None
        ),
        planned_duration_seconds=float(
            planned_waves * reception.duration_default * 60
        ),
        actual_duration_seconds=actual_duration,
        average_eta_error_seconds=(
            sum(eta_errors) / len(eta_errors) if eta_errors else None
        ),
    )


@router.post("", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
def create_session(
    payload: CreateSessionRequest,
    teacher: User = Depends(require_role(UserRole.TEACHER)),
    db: DatabaseSession = Depends(get_db),
) -> SessionResponse:
    participants = _load_participants(payload, db)
    reception = Session(
        teacher_id=teacher.id,
        course_name=payload.course_name,
        room=payload.room,
        date=payload.date,
        start_time=payload.start_time,
        duration_default=payload.duration_default,
        capacity=payload.capacity,
        status=SessionStatus.PLANNED,
        frozen=False,
    )
    db.add(reception)

    try:
        db.flush()
        entries = [
            QueueEntry(
                session_id=reception.id,
                student_id=student.id,
                position=position,
                status=QueueEntryStatus.WAITING,
            )
            for position, student in enumerate(participants, start=1)
        ]
        db.add_all(entries)
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise

    db.refresh(reception)
    return SessionResponse(
        id=reception.id,
        teacher_id=reception.teacher_id,
        course_name=reception.course_name,
        room=reception.room,
        date=reception.date,
        start_time=reception.start_time,
        duration_default=reception.duration_default,
        capacity=reception.capacity,
        status=reception.status,
        frozen=reception.frozen,
        created_at=reception.created_at,
        queue=[QueueEntryResponse.model_validate(entry) for entry in entries],
    )


@router.get("/mine", response_model=list[SessionSummaryResponse])
def list_my_sessions(
    teacher: User = Depends(require_role(UserRole.TEACHER)),
    db: DatabaseSession = Depends(get_db),
) -> list[SessionSummaryResponse]:
    receptions = db.scalars(
        select(Session)
        .where(Session.teacher_id == teacher.id)
        .order_by(Session.date, Session.start_time, Session.id)
    ).all()
    return [SessionSummaryResponse.model_validate(item) for item in receptions]


@router.patch("/{session_id}", response_model=UpdateSessionResponse)
def update_session(
    session_id: UUID,
    payload: UpdateSessionRequest,
    teacher: User = Depends(require_role(UserRole.TEACHER)),
    db: DatabaseSession = Depends(get_db),
) -> UpdateSessionResponse:
    reception = _owned_session(session_id, teacher, db)
    current_status = reception.status
    target_status = payload.status

    if (
        payload.duration_default is not None
        and current_status in {SessionStatus.CLOSED, SessionStatus.CANCELLED}
    ):
        raise HTTPException(
            status_code=409,
            detail="Нельзя менять длительность завершённой сессии",
        )
    if target_status is not None and target_status != current_status:
        if target_status not in ALLOWED_STATUS_TRANSITIONS[current_status]:
            raise HTTPException(status_code=409, detail="Недопустимый переход статуса")
        if target_status == SessionStatus.ACTIVE and not reception.frozen:
            raise HTTPException(
                status_code=409,
                detail="Перед запуском необходимо заморозить список",
            )

    if payload.duration_default is not None:
        reception.duration_default = payload.duration_default

    if target_status is not None and target_status != current_status:
        reception.status = target_status
        if target_status == SessionStatus.ACTIVE:
            active_entries = _active_entries(session_id, db, lock=True)
            _fill_free_channels(
                reception, active_entries, datetime.now(timezone.utc)
            )

    db.flush()
    report = None
    if reception.status == SessionStatus.CLOSED:
        all_entries = list(
            db.scalars(
                select(QueueEntry).where(QueueEntry.session_id == session_id)
            ).all()
        )
        report = _session_report(reception, all_entries)
    response = UpdateSessionResponse(
        **SessionSummaryResponse.model_validate(reception).model_dump(),
        report=report,
    )
    db.commit()
    publish_session_event(reception.id, "session.updated")
    return response


@router.post(
    "/{session_id}/participants",
    response_model=ParticipantMutationResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_participant(
    session_id: UUID,
    payload: AddParticipantRequest,
    teacher: User = Depends(require_role(UserRole.TEACHER)),
    db: DatabaseSession = Depends(get_db),
) -> ParticipantMutationResponse:
    reception = _owned_session(session_id, teacher, db)
    if reception.status in {SessionStatus.CLOSED, SessionStatus.CANCELLED}:
        raise HTTPException(
            status_code=409, detail="Нельзя менять состав завершённой сессии"
        )

    student = db.scalar(
        select(User).where(
            User.id == payload.student_id,
            User.role == UserRole.STUDENT,
        )
    )
    if student is None:
        raise HTTPException(status_code=404, detail="Студент не найден")
    existing_entry = db.scalar(
        select(QueueEntry.id).where(
            QueueEntry.session_id == session_id,
            QueueEntry.student_id == student.id,
        )
    )
    if existing_entry is not None:
        raise HTTPException(
            status_code=409, detail="Студент уже был участником этой сессии"
        )

    active_entries = _active_entries(session_id, db, lock=True)
    entry = QueueEntry(
        session_id=session_id,
        student_id=student.id,
        position=max((item.position for item in active_entries), default=0) + 1,
        status=QueueEntryStatus.WAITING,
    )
    db.add(entry)
    db.flush()
    active_entries.append(entry)
    response = ParticipantMutationResponse(
        session_id=session_id,
        entry_id=entry.id,
        active_queue=_eta_queue(reception, active_entries, db),
    )
    db.commit()
    publish_session_event(reception.id, "participant.added")
    return response


@router.delete(
    "/{session_id}/participants/{entry_id}",
    response_model=ParticipantMutationResponse,
)
def remove_participant(
    session_id: UUID,
    entry_id: UUID,
    teacher: User = Depends(require_role(UserRole.TEACHER)),
    db: DatabaseSession = Depends(get_db),
) -> ParticipantMutationResponse:
    reception = _owned_session(session_id, teacher, db)
    if reception.status in {SessionStatus.CLOSED, SessionStatus.CANCELLED}:
        raise HTTPException(
            status_code=409, detail="Нельзя менять состав завершённой сессии"
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
    if entry.status != QueueEntryStatus.WAITING:
        raise HTTPException(
            status_code=409,
            detail="Историю вызова, завершения, пропуска или отказа удалять нельзя",
        )

    db.delete(entry)
    db.flush()
    active_entries = _active_entries(session_id, db, lock=True)
    normalize_active_positions(active_entries)
    response = ParticipantMutationResponse(
        session_id=session_id,
        entry_id=entry_id,
        active_queue=_eta_queue(reception, active_entries, db),
    )
    db.commit()
    publish_session_event(reception.id, "participant.removed")
    return response


@router.post("/{session_id}/freeze", response_model=FreezeResponse)
def freeze_session(
    session_id: UUID,
    teacher: User = Depends(require_role(UserRole.TEACHER)),
    db: DatabaseSession = Depends(get_db),
) -> FreezeResponse:
    reception = _owned_session(session_id, teacher, db)
    if not reception.frozen:
        reception.frozen = True
        db.commit()
        db.refresh(reception)
        publish_session_event(reception.id, "session.frozen")
    return FreezeResponse(id=reception.id, frozen=reception.frozen)

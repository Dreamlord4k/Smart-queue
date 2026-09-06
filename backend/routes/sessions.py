from datetime import date, datetime, time
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session as DatabaseSession

from auth.dependencies import get_db, require_role
from models.group import Group
from models.queue_entry import QueueEntry, QueueEntryStatus
from models.session import Session, SessionStatus
from models.user import User, UserRole


router = APIRouter(prefix="/sessions", tags=["sessions"])


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

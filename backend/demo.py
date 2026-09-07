from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from uuid import UUID, uuid5

from sqlalchemy import delete, select
from sqlalchemy.orm import Session as DatabaseSession

from backend.auth.security import hash_password
from backend.models.group import Group
from backend.models.notification_log import NotificationLog
from backend.models.queue_entry import QueueEntry, QueueEntryStatus
from backend.models.queue_move_log import QueueMoveLog
from backend.models.service_stat import ServiceStat
from backend.models.session import Session, SessionStatus
from backend.models.telegram_link_code import TelegramLinkCode
from backend.models.user import User, UserRole


DEMO_NAMESPACE = UUID("aa391806-25cd-4e39-9be4-65c541f3fd7a")
DEMO_GROUP_ID = uuid5(DEMO_NAMESPACE, "group")
DEMO_TEACHER_ID = uuid5(DEMO_NAMESPACE, "teacher")
DEMO_ACTIVE_SESSION_ID = uuid5(DEMO_NAMESPACE, "active-session")
DEMO_PLANNED_SESSION_ID = uuid5(DEMO_NAMESPACE, "planned-session")
DEMO_TEACHER_EMAIL = "demo-ui-teacher@example.invalid"
DEMO_STUDENT_EMAIL = "demo-ui-student08@example.invalid"
DEMO_PASSWORD = "Demo-UI-Internal-Password!"

STUDENT_NAMES = (
    "Анна Алексеева",
    "Борис Белов",
    "Виктория Волкова",
    "Глеб Громов",
    "Дарья Денисова",
    "Егор Ершов",
    "Жанна Жукова",
    "Илья Иванов",
)


def demo_student_id(index: int) -> UUID:
    return uuid5(DEMO_NAMESPACE, f"student-{index:02d}")


def demo_entry_id(session_id: UUID, student_id: UUID) -> UUID:
    return uuid5(DEMO_NAMESPACE, f"entry:{session_id}:{student_id}")


def is_demo_user(user: User) -> bool:
    return user.id == DEMO_TEACHER_ID or user.id in {
        demo_student_id(index) for index in range(1, len(STUDENT_NAMES) + 1)
    }


def _upsert_group(db: DatabaseSession) -> Group:
    group = db.get(Group, DEMO_GROUP_ID)
    if group is None:
        group = Group(id=DEMO_GROUP_ID, name="DEMO-UI — РИ-000001")
        db.add(group)
    else:
        group.name = "DEMO-UI — РИ-000001"
    return group


def _upsert_user(
    db: DatabaseSession,
    *,
    user_id: UUID,
    email: str,
    full_name: str,
    role: UserRole,
    group_id: UUID | None,
) -> User:
    user = db.get(User, user_id)
    if user is None:
        user = User(
            id=user_id,
            email=email,
            full_name=full_name,
            password_hash=hash_password(DEMO_PASSWORD),
            role=role,
            group_id=group_id,
        )
        db.add(user)
    else:
        user.email = email
        user.full_name = full_name
        user.role = role
        user.group_id = group_id
        user.telegram_id = None
    return user


def _upsert_session(
    db: DatabaseSession,
    *,
    session_id: UUID,
    course_name: str,
    room: str,
    start_at: datetime,
    status: SessionStatus,
    frozen: bool,
) -> Session:
    reception = db.get(Session, session_id)
    if reception is None:
        reception = Session(id=session_id, teacher_id=DEMO_TEACHER_ID)
        db.add(reception)
    reception.course_name = course_name
    reception.room = room
    reception.date = start_at.date()
    reception.start_time = start_at.time().replace(tzinfo=None, microsecond=0)
    reception.duration_default = 7
    reception.capacity = 2
    reception.status = status
    reception.frozen = frozen
    return reception


def reset_demo_ui(db: DatabaseSession) -> dict[str, str]:
    """Восстанавливает стабильный набор DEMO-UI, не меняя UUID аккаунтов."""
    _upsert_group(db)
    _upsert_user(
        db,
        user_id=DEMO_TEACHER_ID,
        email=DEMO_TEACHER_EMAIL,
        full_name="DEMO-UI Преподаватель",
        role=UserRole.TEACHER,
        group_id=None,
    )
    student_ids = []
    for index, full_name in enumerate(STUDENT_NAMES, start=1):
        student_id = demo_student_id(index)
        student_ids.append(student_id)
        _upsert_user(
            db,
            user_id=student_id,
            email=f"demo-ui-student{index:02d}@example.invalid",
            full_name=f"DEMO-UI {full_name}",
            role=UserRole.STUDENT,
            group_id=DEMO_GROUP_ID,
        )
    db.flush()

    demo_user_ids = [DEMO_TEACHER_ID, *student_ids]
    existing_session_ids = list(
        db.scalars(select(Session.id).where(Session.teacher_id == DEMO_TEACHER_ID)).all()
    )
    entry_ids = list(
        db.scalars(
            select(QueueEntry.id).where(QueueEntry.session_id.in_(existing_session_ids))
        ).all()
    ) if existing_session_ids else []
    if entry_ids:
        db.execute(delete(NotificationLog).where(NotificationLog.queue_entry_id.in_(entry_ids)))
        db.execute(delete(QueueMoveLog).where(QueueMoveLog.queue_entry_id.in_(entry_ids)))
    db.execute(delete(TelegramLinkCode).where(TelegramLinkCode.user_id.in_(demo_user_ids)))
    if existing_session_ids:
        db.execute(delete(ServiceStat).where(ServiceStat.session_id.in_(existing_session_ids)))
        db.execute(delete(QueueEntry).where(QueueEntry.session_id.in_(existing_session_ids)))
        db.execute(
            delete(Session).where(
                Session.teacher_id == DEMO_TEACHER_ID,
                Session.id.not_in(
                    [DEMO_ACTIVE_SESSION_ID, DEMO_PLANNED_SESSION_ID]
                ),
            )
        )

    now = datetime.now(timezone.utc)
    active = _upsert_session(
        db,
        session_id=DEMO_ACTIVE_SESSION_ID,
        course_name="DEMO-UI: защита лабораторных",
        room="Р-101",
        start_at=now - timedelta(minutes=10),
        status=SessionStatus.ACTIVE,
        frozen=True,
    )
    planned = _upsert_session(
        db,
        session_id=DEMO_PLANNED_SESSION_ID,
        course_name="DEMO-UI: свободная очередь",
        room="Р-102",
        start_at=now + timedelta(hours=1),
        status=SessionStatus.PLANNED,
        frozen=False,
    )
    db.flush()

    entries: list[QueueEntry] = []
    for position, student_id in enumerate(student_ids, start=1):
        entries.append(
            QueueEntry(
                id=demo_entry_id(active.id, student_id),
                session_id=active.id,
                student_id=student_id,
                position=position,
                status=(
                    QueueEntryStatus.CALLED if position <= active.capacity
                    else QueueEntryStatus.WAITING
                ),
                channel=position if position <= active.capacity else None,
                called_at=now if position <= active.capacity else None,
                locked=position == 5,
                lock_reason="DEMO-UI: согласовано с преподавателем" if position == 5 else None,
            )
        )
        entries.append(
            QueueEntry(
                id=demo_entry_id(planned.id, student_id),
                session_id=planned.id,
                student_id=student_id,
                position=position,
                status=QueueEntryStatus.WAITING,
                locked=position == 4,
                lock_reason="DEMO-UI: параллельная защита" if position == 4 else None,
            )
        )
    db.add_all(entries)
    db.commit()
    return {
        "active_session_id": str(DEMO_ACTIVE_SESSION_ID),
        "planned_session_id": str(DEMO_PLANNED_SESSION_ID),
        "teacher_email": DEMO_TEACHER_EMAIL,
        "student_email": DEMO_STUDENT_EMAIL,
        "seed_date": date.today().isoformat(),
    }

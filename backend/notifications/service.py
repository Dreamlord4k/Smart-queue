from __future__ import annotations

from datetime import datetime, timezone
from math import ceil
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DatabaseSession

from backend.config import TELEGRAM_SOFT_THRESHOLD_SECONDS
from backend.models.notification_log import (
    NotificationLog,
    NotificationStatus,
    NotificationType,
)
from backend.models.queue_entry import QueueEntry, QueueEntryStatus
from backend.models.queue_move_log import QueueMoveLog  # noqa: F401 — завершает регистрацию mapper
from backend.models.service_stat import ServiceStat
from backend.models.session import Session, SessionStatus
from backend.models.user import User
from backend.notifications.transport import NotificationTransport
from backend.queue.eta import ACTIVE_STATUSES, calculate_eta_ranges


QUEUE_NOTIFICATION_EVENTS = {"queue.done", "queue.skipped", "session.updated"}


def _deliver(
    db: DatabaseSession,
    notification: NotificationLog,
    transport: NotificationTransport,
) -> None:
    if notification.status == NotificationStatus.SENT:
        return
    recipient = db.get(User, notification.recipient_id)
    if recipient is None or recipient.telegram_id is None:
        return

    notification.attempts += 1
    try:
        transport.send(recipient.telegram_id, notification.message)
    except Exception as exc:  # Транспорт не должен откатывать очередь.
        notification.status = NotificationStatus.FAILED
        notification.last_error = str(exc)[:2000]
    else:
        notification.status = NotificationStatus.SENT
        notification.last_error = None
        notification.sent_at = datetime.now(timezone.utc)
    db.commit()


def _create_or_retry(
    db: DatabaseSession,
    *,
    entry: QueueEntry,
    notification_type: NotificationType,
    message: str,
    transport: NotificationTransport,
) -> NotificationLog | None:
    recipient = db.get(User, entry.student_id)
    if recipient is None or recipient.telegram_id is None:
        return None

    event_key = f"{notification_type.value}:{entry.id}"
    notification = db.scalar(
        select(NotificationLog).where(
            NotificationLog.event_key == event_key,
            NotificationLog.recipient_id == recipient.id,
        )
    )
    if notification is None:
        notification = NotificationLog(
            queue_entry_id=entry.id,
            recipient_id=recipient.id,
            event_key=event_key,
            type=notification_type,
            status=NotificationStatus.PENDING,
            message=message,
        )
        db.add(notification)
        try:
            # Сначала фиксируем уникальный лог: повторный обработчик не сможет
            # отправить то же логическое уведомление вторично.
            db.commit()
        except IntegrityError:
            db.rollback()
            notification = db.scalar(
                select(NotificationLog).where(
                    NotificationLog.event_key == event_key,
                    NotificationLog.recipient_id == recipient.id,
                )
            )
    if notification is not None:
        _deliver(db, notification, transport)
    return notification


def process_queue_event(
    db: DatabaseSession,
    event: dict[str, Any],
    transport: NotificationTransport,
) -> list[NotificationLog]:
    if event.get("type") not in QUEUE_NOTIFICATION_EVENTS:
        return []
    try:
        session_id = UUID(str(event["session_id"]))
    except (KeyError, TypeError, ValueError):
        return []

    reception = db.get(Session, session_id)
    if reception is None or reception.status != SessionStatus.ACTIVE:
        return []
    entries = list(
        db.scalars(
            select(QueueEntry)
            .where(
                QueueEntry.session_id == session_id,
                QueueEntry.status.in_(ACTIVE_STATUSES),
            )
            .order_by(QueueEntry.position, QueueEntry.created_at, QueueEntry.id)
        ).all()
    )

    created: list[NotificationLog] = []
    for entry in entries:
        if entry.status != QueueEntryStatus.CALLED:
            continue
        notification = _create_or_retry(
            db,
            entry=entry,
            notification_type=NotificationType.HARD_CALL,
            message="Заходите, ваша очередь.",
            transport=transport,
        )
        if notification is not None:
            created.append(notification)

    buffer_entry = next(
        (entry for entry in entries if entry.status == QueueEntryStatus.WAITING), None
    )
    if buffer_entry is not None:
        notification = _create_or_retry(
            db,
            entry=buffer_entry,
            notification_type=NotificationType.BUFFER,
            message="Подходите к кабинету, будьте рядом.",
            transport=transport,
        )
        if notification is not None:
            created.append(notification)
    return created


def run_soft_notifications(
    db: DatabaseSession,
    transport: NotificationTransport,
    *,
    now: datetime | None = None,
) -> list[NotificationLog]:
    current_time = now or datetime.now(timezone.utc)
    receptions = list(
        db.scalars(
            select(Session).where(Session.status == SessionStatus.ACTIVE)
        ).all()
    )
    created: list[NotificationLog] = []
    for reception in receptions:
        entries = list(
            db.scalars(
                select(QueueEntry)
                .where(
                    QueueEntry.session_id == reception.id,
                    QueueEntry.status.in_(ACTIVE_STATUSES),
                )
                .order_by(QueueEntry.position, QueueEntry.created_at, QueueEntry.id)
            ).all()
        )
        stat = db.get(ServiceStat, reception.id)
        eta_ranges = calculate_eta_ranges(
            reception,
            entries,
            now=current_time,
            ema_estimate=stat.ema_estimate if stat else None,
            variance=stat.variance if stat else 0.0,
        )
        for entry in entries:
            if entry.status != QueueEntryStatus.WAITING:
                continue
            eta = eta_ranges.get(entry.id)
            if eta is None:
                continue
            seconds_until = max((eta[0] - current_time).total_seconds(), 0.0)
            if seconds_until > TELEGRAM_SOFT_THRESHOLD_SECONDS:
                continue
            low_minutes = max(0, ceil(seconds_until / 60))
            high_minutes = max(
                low_minutes, ceil(max((eta[1] - current_time).total_seconds(), 0) / 60)
            )
            notification = _create_or_retry(
                db,
                entry=entry,
                notification_type=NotificationType.SOFT,
                message=f"Скоро ваша очередь, ETA {low_minutes}–{high_minutes} мин.",
                transport=transport,
            )
            if notification is not None:
                created.append(notification)
    return created


def retry_failed_notifications(
    db: DatabaseSession,
    transport: NotificationTransport,
) -> int:
    notifications = list(
        db.scalars(
            select(NotificationLog)
            .where(
                NotificationLog.status.in_(
                    (NotificationStatus.PENDING, NotificationStatus.FAILED)
                )
            )
            .order_by(NotificationLog.created_at)
        ).all()
    )
    for notification in notifications:
        _deliver(db, notification, transport)
    return len(notifications)

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DatabaseSession

from backend.auth.dependencies import get_db, require_role
from backend.config import (
    TELEGRAM_BOT_USERNAME,
    TELEGRAM_LINK_CODE_TTL_SECONDS,
    TELEGRAM_WEBHOOK_SECRET,
)
from backend.models.telegram_link_code import TelegramLinkCode
from backend.models.user import User, UserRole
from backend.notifications.transport import NotificationTransport, TelegramTransport


router = APIRouter(prefix="/telegram", tags=["telegram"])


class TelegramLinkResponse(BaseModel):
    linked: bool
    code: str | None = None
    expires_at: datetime | None = None
    deep_link: str | None = None


class TelegramSender(BaseModel):
    id: int


class TelegramChat(BaseModel):
    id: int


class TelegramMessage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    text: str | None = None
    sender: TelegramSender = Field(alias="from")
    chat: TelegramChat


class TelegramUpdate(BaseModel):
    update_id: int
    message: TelegramMessage | None = None


class TelegramUpdateResult(BaseModel):
    accepted: bool
    chat_id: int | None = None
    reply: str | None = None


def get_telegram_transport() -> NotificationTransport:
    return TelegramTransport()


def _link_code_from_text(text: str | None) -> str | None:
    if not text:
        return None
    parts = text.strip().split(maxsplit=1)
    if not parts:
        return None
    if parts[0].lower() == "/start":
        return parts[1].strip() if len(parts) == 2 else None
    return parts[0]


def handle_telegram_update(
    payload: TelegramUpdate,
    db: DatabaseSession,
) -> TelegramUpdateResult:
    if payload.message is None:
        return TelegramUpdateResult(accepted=False)
    message = payload.message
    code = _link_code_from_text(message.text)
    if code is None:
        return TelegramUpdateResult(
            accepted=False,
            chat_id=message.chat.id,
            reply="Отправьте код привязки из настроек Smart Queue.",
        )

    now = datetime.now(timezone.utc)
    link_code = db.scalar(
        select(TelegramLinkCode)
        .where(TelegramLinkCode.code == code)
        .with_for_update()
    )
    if link_code is None or link_code.used_at is not None:
        return TelegramUpdateResult(
            accepted=False,
            chat_id=message.chat.id,
            reply="Код недействителен или уже использован.",
        )
    expires_at = link_code.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= now:
        return TelegramUpdateResult(
            accepted=False,
            chat_id=message.chat.id,
            reply="Срок действия кода истёк. Выпустите новый код в настройках.",
        )

    user = db.get(User, link_code.user_id)
    if user is None:
        return TelegramUpdateResult(accepted=False, chat_id=message.chat.id)
    user.telegram_id = message.sender.id
    link_code.used_at = now
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return TelegramUpdateResult(
            accepted=False,
            chat_id=message.chat.id,
            reply="Этот Telegram уже связан с другим аккаунтом.",
        )
    return TelegramUpdateResult(
        accepted=True,
        chat_id=message.chat.id,
        reply="Telegram успешно привязан к вашему аккаунту Smart Queue.",
    )


@router.post("/link/init", response_model=TelegramLinkResponse)
def init_telegram_link(
    student: User = Depends(require_role(UserRole.STUDENT)),
    db: DatabaseSession = Depends(get_db),
) -> TelegramLinkResponse:
    if student.telegram_id is not None:
        return TelegramLinkResponse(linked=True)

    now = datetime.now(timezone.utc)
    db.execute(
        update(TelegramLinkCode)
        .where(
            TelegramLinkCode.user_id == student.id,
            TelegramLinkCode.used_at.is_(None),
        )
        .values(used_at=now)
    )
    code = secrets.token_urlsafe(9)
    expires_at = now + timedelta(seconds=TELEGRAM_LINK_CODE_TTL_SECONDS)
    db.add(
        TelegramLinkCode(user_id=student.id, code=code, expires_at=expires_at)
    )
    db.commit()
    deep_link = (
        f"https://t.me/{TELEGRAM_BOT_USERNAME}?start={code}"
        if TELEGRAM_BOT_USERNAME
        else None
    )
    return TelegramLinkResponse(
        linked=False,
        code=code,
        expires_at=expires_at,
        deep_link=deep_link,
    )


@router.post("/webhook", status_code=status.HTTP_200_OK)
def telegram_webhook(
    payload: TelegramUpdate,
    secret: str | None = Header(
        default=None, alias="X-Telegram-Bot-Api-Secret-Token"
    ),
    db: DatabaseSession = Depends(get_db),
    transport: NotificationTransport = Depends(get_telegram_transport),
) -> dict[str, bool]:
    if TELEGRAM_WEBHOOK_SECRET and not secrets.compare_digest(
        secret or "", TELEGRAM_WEBHOOK_SECRET
    ):
        raise HTTPException(status_code=403, detail="Некорректный секрет webhook")

    result = handle_telegram_update(payload, db)
    if result.chat_id is not None and result.reply:
        try:
            transport.send(result.chat_id, result.reply)
        except Exception:
            # Привязка уже зафиксирована и не должна откатываться из-за ответа бота.
            pass
    return {"ok": True}

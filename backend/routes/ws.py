from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from redis.exceptions import RedisError
from sqlalchemy import select

from backend.auth.dependencies import SessionLocal
from backend.auth.security import TokenError, decode_token
from backend.models.queue_entry import QueueEntry
from backend.models.session import Session
from backend.models.user import User, UserRole
from backend.realtime.events import stream_session_events


router = APIRouter(tags=["realtime"])


def _websocket_access(token: str, session_id: UUID) -> None:
    try:
        payload = decode_token(token, expected_type="access")
        user_id = UUID(payload["sub"])
        token_role = UserRole(payload["role"])
    except (TokenError, ValueError, KeyError) as exc:
        raise PermissionError("unauthorized") from exc

    with SessionLocal() as db:
        user = db.get(User, user_id)
        reception = db.get(Session, session_id)
        if user is None or user.role != token_role or reception is None:
            raise PermissionError("unauthorized")
        if user.role == UserRole.TEACHER:
            allowed = reception.teacher_id == user.id
        else:
            allowed = db.scalar(
                select(QueueEntry.id).where(
                    QueueEntry.session_id == session_id,
                    QueueEntry.student_id == user.id,
                )
            ) is not None
        if not allowed:
            raise PermissionError("forbidden")
@router.websocket("/ws/sessions/{session_id}")
async def session_updates(
    websocket: WebSocket,
    session_id: UUID,
    token: str = Query(min_length=1),
) -> None:
    try:
        _websocket_access(token, session_id)
    except PermissionError as exc:
        await websocket.close(code=4403 if str(exc) == "forbidden" else 4401)
        return

    await websocket.accept()
    try:
        async for event in stream_session_events(session_id):
            await websocket.send_json(event)
    except WebSocketDisconnect:
        return
    except RedisError:
        await websocket.close(code=1011, reason="Realtime временно недоступен")

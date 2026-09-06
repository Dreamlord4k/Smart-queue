from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timezone
from functools import lru_cache
import json
import logging
from typing import Any
from uuid import UUID, uuid4

from redis import Redis
from redis.asyncio import Redis as AsyncRedis
from redis.exceptions import RedisError

from backend.config import REDIS_URL


logger = logging.getLogger(__name__)


def session_channel(session_id: UUID) -> str:
    return f"session:{session_id}"


@lru_cache(maxsize=1)
def _publisher() -> Redis:
    return Redis.from_url(REDIS_URL, decode_responses=True)


def publish_session_event(session_id: UUID, event_type: str) -> dict[str, Any]:
    event = {
        "event_id": str(uuid4()),
        "type": event_type,
        "session_id": str(session_id),
        "occurred_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        _publisher().publish(session_channel(session_id), json.dumps(event))
    except RedisError:
        # Бизнес-операция уже сохранена: недоступный realtime не должен её откатывать.
        logger.warning("Не удалось опубликовать realtime-событие", exc_info=True)
    return event


async def stream_session_events(session_id: UUID) -> AsyncIterator[dict[str, Any]]:
    client = AsyncRedis.from_url(REDIS_URL, decode_responses=True)
    pubsub = client.pubsub()
    try:
        await pubsub.subscribe(session_channel(session_id))
        yield {
            "event_id": str(uuid4()),
            "type": "realtime.ready",
            "session_id": str(session_id),
            "occurred_at": datetime.now(timezone.utc).isoformat(),
        }
        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue
            try:
                event = json.loads(message["data"])
            except (KeyError, TypeError, json.JSONDecodeError):
                continue
            if isinstance(event, dict):
                yield event
    finally:
        await pubsub.unsubscribe(session_channel(session_id))
        await pubsub.aclose()
        await client.aclose()

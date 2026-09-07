from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx
from redis.asyncio import Redis as AsyncRedis

from backend.auth.dependencies import SessionLocal
from backend.config import (
    REDIS_URL,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_SOFT_INTERVAL_SECONDS,
)
from backend.notifications import (
    process_queue_event,
    retry_failed_notifications,
    run_soft_notifications,
)
from backend.notifications.transport import TelegramTransport
from backend.routes.telegram import TelegramUpdate, handle_telegram_update


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
transport = TelegramTransport()


def _handle_update(payload: dict[str, Any]) -> None:
    update = TelegramUpdate.model_validate(payload)
    with SessionLocal() as db:
        result = handle_telegram_update(update, db)
    if result.chat_id is not None and result.reply:
        transport.send(result.chat_id, result.reply)


def _handle_queue_event(event: dict[str, Any]) -> None:
    with SessionLocal() as db:
        process_queue_event(db, event, transport)


def _run_background_delivery() -> None:
    with SessionLocal() as db:
        retry_failed_notifications(db, transport)
        run_soft_notifications(db, transport)


async def poll_telegram() -> None:
    if not TELEGRAM_BOT_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN не задан: long polling отключён")
        return
    api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
    offset: int | None = None
    async with httpx.AsyncClient(timeout=40) as client:
        await client.post(f"{api_url}/deleteWebhook", json={"drop_pending_updates": False})
        while True:
            try:
                response = await client.post(
                    f"{api_url}/getUpdates",
                    json={"offset": offset, "timeout": 30, "allowed_updates": ["message"]},
                )
                response.raise_for_status()
                for payload in response.json().get("result", []):
                    offset = int(payload["update_id"]) + 1
                    try:
                        await asyncio.to_thread(_handle_update, payload)
                    except Exception:
                        logger.exception("Не удалось обработать Telegram update")
            except Exception:
                logger.exception("Ошибка Telegram long polling")
                await asyncio.sleep(5)


async def consume_queue_events() -> None:
    client = AsyncRedis.from_url(REDIS_URL, decode_responses=True)
    pubsub = client.pubsub()
    try:
        await pubsub.psubscribe("session:*")
        async for message in pubsub.listen():
            if message.get("type") != "pmessage":
                continue
            try:
                event = json.loads(message["data"])
            except (KeyError, TypeError, json.JSONDecodeError):
                continue
            if isinstance(event, dict):
                await asyncio.to_thread(_handle_queue_event, event)
    finally:
        await pubsub.punsubscribe("session:*")
        await pubsub.aclose()
        await client.aclose()


async def run_background_delivery() -> None:
    while True:
        try:
            await asyncio.to_thread(_run_background_delivery)
        except Exception:
            logger.exception("Ошибка фоновой доставки уведомлений")
        await asyncio.sleep(TELEGRAM_SOFT_INTERVAL_SECONDS)


async def main() -> None:
    if not TELEGRAM_BOT_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN не задан: worker ожидает конфигурацию")
        await asyncio.Event().wait()
        return
    await asyncio.gather(
        poll_telegram(),
        consume_queue_events(),
        run_background_delivery(),
    )


if __name__ == "__main__":
    asyncio.run(main())

from __future__ import annotations

from typing import Protocol

import httpx

from backend.config import TELEGRAM_BOT_TOKEN


class NotificationTransport(Protocol):
    def send(self, telegram_id: int, message: str) -> None: ...


class TelegramTransport:
    def __init__(self, token: str = TELEGRAM_BOT_TOKEN) -> None:
        self._token = token

    def send(self, telegram_id: int, message: str) -> None:
        if not self._token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN не настроен")
        response = httpx.post(
            f"https://api.telegram.org/bot{self._token}/sendMessage",
            json={"chat_id": telegram_id, "text": message},
            timeout=10,
        )
        response.raise_for_status()

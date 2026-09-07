"""Структурное логирование операций очереди.

Единственное место настройки JSON-форматтера: все роуты берут логгер
и хелперы отсюда. Формат — один JSON-объект на строку, только
безопасные поля (id, позиции, EMA). Токены, пароли и заголовки
авторизации в логи не пишутся никогда — хелпер отбрасывает
запрещённые ключи, даже если их передали по ошибке.
"""

from __future__ import annotations

import functools
import json
import logging
from datetime import datetime, timezone
from typing import Any, Callable, TypeVar

from fastapi import HTTPException

LOGGER_NAME = "smart_queue.queue"

# Ключи, которым нет места в логах ни при каких условиях.
FORBIDDEN_LOG_KEYS = frozenset(
    {
        "access_token",
        "refresh_token",
        "password",
        "password_hash",
        "authorization",
        "token",
    }
)

F = TypeVar("F", bound=Callable[..., Any])


class JsonFormatter(logging.Formatter):
    """Одна строка — один JSON-объект с ts/level/logger и полями операции."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
        }
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            payload.update(fields)
        else:
            payload["msg"] = record.getMessage()
        if record.exc_info:
            payload["traceback"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def get_queue_logger() -> logging.Logger:
    """Логгер операций очереди с JSON-хендлером (идемпотентно)."""
    logger = logging.getLogger(LOGGER_NAME)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    # propagate=True оставлен намеренно: так записи видят и uvicorn/root,
    # и pytest-caplog в тестах.
    return logger


def _sanitize(fields: dict[str, Any]) -> dict[str, Any]:
    return {
        key: (str(value) if not isinstance(value, (bool, int, float, type(None))) else value)
        for key, value in fields.items()
        if key.lower() not in FORBIDDEN_LOG_KEYS
    }


def log_operation(op: str, **fields: Any) -> None:
    """Info-запись об успешной операции очереди."""
    get_queue_logger().info(op, extra={"fields": {"op": op, **_sanitize(fields)}})


def log_route_errors(op: str) -> Callable[[F], F]:
    """Декоратор эндпоинтов: неожиданное исключение — в лог с traceback, дальше как было."""

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return func(*args, **kwargs)
            except HTTPException:
                raise
            except Exception:
                get_queue_logger().exception(op, extra={"fields": {"op": op}})
                raise

        return wrapper  # type: ignore[return-value]

    return decorator

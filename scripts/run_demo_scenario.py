from __future__ import annotations

import argparse
from collections.abc import Callable
import json
import os
from pathlib import Path
import random
import time
from typing import Any, Protocol

from redis import Redis

from backend.auth.dependencies import SessionLocal
from backend.notifications.service import process_queue_event, run_soft_notifications
from backend.routes.telegram import TelegramUpdate, handle_telegram_update

if __package__:
    from scripts.generate_demo_data import DEFAULT_STATE_PATH, DemoApi
else:
    from generate_demo_data import DEFAULT_STATE_PATH, DemoApi


class EventSource(Protocol):
    def next_event(
        self, session_id: str, expected_type: str, timeout: float = 3
    ) -> dict[str, Any]: ...

    def close(self) -> None: ...


class RedisEventSource:
    def __init__(self, redis_url: str, session_ids: list[str]) -> None:
        self.client = Redis.from_url(redis_url, decode_responses=True)
        self.pubsub = self.client.pubsub()
        self.pubsub.subscribe(*(f"session:{session_id}" for session_id in session_ids))
        confirmations = len(session_ids)
        deadline = time.monotonic() + 3
        while confirmations and time.monotonic() < deadline:
            message = self.pubsub.get_message(timeout=0.2)
            if message and message.get("type") == "subscribe":
                confirmations -= 1
        if confirmations:
            raise RuntimeError("Не удалось подписаться на realtime-каналы Redis")

    def next_event(
        self, session_id: str, expected_type: str, timeout: float = 3
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            message = self.pubsub.get_message(timeout=0.2)
            if not message or message.get("type") != "message":
                continue
            try:
                event = json.loads(message["data"])
            except (KeyError, TypeError, json.JSONDecodeError):
                continue
            if (
                event.get("session_id") == session_id
                and event.get("type") == expected_type
            ):
                return event
        raise RuntimeError(
            f"Не получено realtime-событие {expected_type} для сессии {session_id}"
        )

    def close(self) -> None:
        self.pubsub.close()
        self.client.close()


class FakeTelegramTransport:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []

    def send(self, telegram_id: int, message: str) -> None:
        self.sent.append((telegram_id, message))


def _entry_for(session: dict[str, Any], student_id: str) -> dict[str, Any]:
    return next(
        entry for entry in session["queue"] if entry["student_id"] == student_id
    )


def _link_synthetic_telegram(
    api: DemoApi,
    students: list[dict[str, Any]],
    session_factory: Callable[..., Any],
) -> None:
    for index, student in enumerate(students, start=1):
        token = api.login(student["email"], student["password"])
        link = api.request("POST", "/telegram/link/init", token=token)
        if link["linked"]:
            continue
        payload = TelegramUpdate.model_validate(
            {
                "update_id": index,
                "message": {
                    "text": f"/start {link['code']}",
                    "from": {"id": 900_000_000 + index},
                    "chat": {"id": 900_000_000 + index},
                },
            }
        )
        with session_factory() as db:
            result = handle_telegram_update(payload, db)
        if not result.accepted:
            raise RuntimeError(f"Не удалось привязать fake Telegram: {student['email']}")


def _scaled_delay(
    duration_minutes: int,
    delay_scale: float,
    rng: random.Random,
) -> float:
    mean = duration_minutes * 60 * max(delay_scale, 0)
    if mean == 0:
        return 0
    return min(max(rng.gauss(mean, mean * 0.25), 0.05), 5.0)


def run_demo_scenario(
    api: DemoApi,
    state: dict[str, Any],
    events: EventSource,
    *,
    session_factory: Callable[..., Any] = SessionLocal,
    delay_scale: float = 0.02,
    sleep: Callable[[float], None] = time.sleep,
    output: Callable[[str], None] = print,
) -> dict[str, Any]:
    rng = random.Random(int(state["seed"]))
    teacher_token = api.login(
        state["teacher"]["email"], state["teacher"]["password"]
    )
    students = state["students"]
    sessions = sorted(state["sessions"], key=lambda item: item["capacity"])
    single, parallel = sessions
    common_id = state["common_student_id"]
    absent_student = students[-1]

    _link_synthetic_telegram(api, students, session_factory)
    telegram = FakeTelegramTransport()
    observed_events: list[dict[str, Any]] = []

    def mutate(
        method: str,
        path: str,
        *,
        token: str,
        session_id: str,
        event_type: str,
        json_body: dict[str, Any] | None = None,
        expected: tuple[int, ...] = (200,),
        notify: bool = False,
    ) -> Any:
        result = api.request(
            method,
            path,
            token=token,
            json_body=json_body,
            expected=expected,
        )
        event = events.next_event(session_id, event_type)
        observed_events.append(event)
        if notify:
            with session_factory() as db:
                process_queue_event(db, event, telegram)
        return result

    absent_token = api.login(absent_student["email"], absent_student["password"])
    absent_entry = _entry_for(single, absent_student["id"])
    absence = mutate(
        "POST",
        f"/students/me/queues/{absent_entry['id']}/absence",
        token=absent_token,
        session_id=single["id"],
        event_type="queue.absent",
        json_body={"absence_reason": "Синтетическая причина: пара в другом корпусе"},
    )
    if absence["status"] != "absent" or not absence["absence_reason"]:
        raise RuntimeError("Контрольная точка отказа не пройдена")

    queues = api.request("GET", "/students/me/queues", token=absent_token)
    statuses = {item["session_id"]: item["status"] for item in queues}
    if statuses.get(single["id"]) != "absent" or statuses.get(parallel["id"]) != "waiting":
        raise RuntimeError("Статусы общего студента между сессиями смешались")
    output("✓ Отказ сохранён только в одной сессии; вторая очередь независима")

    common = next(student for student in students if student["id"] == common_id)
    common_token = api.login(common["email"], common["password"])
    own_entry = _entry_for(parallel, common_id)
    target_entry = next(
        entry for entry in parallel["queue"] if entry["student_id"] != common_id
    )
    mutate(
        "PATCH",
        f"/sessions/{parallel['id']}/queue/reorder",
        token=common_token,
        session_id=parallel["id"],
        event_type="queue.reordered",
        json_body={
            "entry_id": own_entry["id"],
            "target_entry_id": target_entry["id"],
            "placement": "before",
        },
    )
    lock = mutate(
        "PATCH",
        f"/sessions/{parallel['id']}/queue/{own_entry['id']}/lock",
        token=common_token,
        session_id=parallel["id"],
        event_type="queue.locked",
        json_body={
            "locked": True,
            "lock_reason": "Синтетическая причина: пересечение расписания",
        },
    )
    if lock["lock_reason"] == absence["absence_reason"]:
        raise RuntimeError("lock_reason и absence_reason не должны смешиваться")
    output("✓ Собственная запись переставлена и зафиксирована с отдельной причиной")

    for reception in sessions:
        mutate(
            "POST",
            f"/sessions/{reception['id']}/freeze",
            token=teacher_token,
            session_id=reception["id"],
            event_type="session.frozen",
        )
        mutate(
            "PATCH",
            f"/sessions/{reception['id']}",
            token=teacher_token,
            session_id=reception["id"],
            event_type="session.updated",
            json_body={"status": "active"},
            notify=True,
        )

    with session_factory() as db:
        run_soft_notifications(db, telegram)

    reception_results = []
    for reception in sessions:
        queue = api.request(
            "GET", f"/sessions/{reception['id']}/queue", token=teacher_token
        )
        called = sorted(
            (entry for entry in queue["entries"] if entry["status"] == "called"),
            key=lambda entry: entry["channel"],
        )
        if len(called) != reception["capacity"]:
            raise RuntimeError("Количество активных каналов не совпало с capacity")

        delay = _scaled_delay(1, delay_scale, rng)
        sleep(delay)
        done = mutate(
            "POST",
            f"/sessions/{reception['id']}/queue/{called[0]['id']}/done",
            token=teacher_token,
            session_id=reception["id"],
            event_type="queue.done",
            notify=True,
        )
        if done["ema_estimate"] is None or done["n_observations"] != 1:
            raise RuntimeError("EMA не обновилась после done")

        queue = api.request(
            "GET", f"/sessions/{reception['id']}/queue", token=teacher_token
        )
        called = sorted(
            (entry for entry in queue["entries"] if entry["status"] == "called"),
            key=lambda entry: entry["channel"],
        )
        sleep(_scaled_delay(1, delay_scale, rng))
        skipped = mutate(
            "POST",
            f"/sessions/{reception['id']}/queue/{called[-1]['id']}/skip",
            token=teacher_token,
            session_id=reception["id"],
            event_type="queue.skipped",
            notify=True,
        )
        if skipped["n_observations"] != 1:
            raise RuntimeError("skip не должен добавлять EMA-наблюдение")
        reception_results.append(
            {
                "session_id": reception["id"],
                "capacity": reception["capacity"],
                "ema_estimate": done["ema_estimate"],
                "eta_entries": len(done["active_queue"]),
            }
        )
        output(
            f"✓ capacity={reception['capacity']}: done/skip обновили каналы, EMA и ETA"
        )

    reports = []
    for reception in sessions:
        closed = mutate(
            "PATCH",
            f"/sessions/{reception['id']}",
            token=teacher_token,
            session_id=reception["id"],
            event_type="session.updated",
            json_body={"status": "closed"},
        )
        reports.append(closed["report"])

    notification_types = {
        "soft" if "Скоро" in message else
        "buffer" if "Подходите" in message else
        "hard_call"
        for _, message in telegram.sent
    }
    if notification_types != {"soft", "buffer", "hard_call"}:
        raise RuntimeError("Сработали не все три типа fake Telegram-уведомлений")
    output(
        f"✓ Realtime: {len(observed_events)} событий; fake Telegram: "
        f"{len(telegram.sent)} сообщений, внешних запросов 0"
    )
    output("✓ Сессии закрыты, отчёты «до/после» сформированы")

    return {
        "events": observed_events,
        "telegram_messages": telegram.sent,
        "notification_types": sorted(notification_types),
        "sessions": reception_results,
        "reports": reports,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Сквозной демо-сценарий Smart Queue")
    parser.add_argument("--state", default=DEFAULT_STATE_PATH)
    parser.add_argument("--api-url")
    parser.add_argument("--redis-url", default=os.environ.get("REDIS_URL"))
    parser.add_argument("--delay-scale", type=float, default=0.02)
    args = parser.parse_args()
    if not args.redis_url:
        parser.error("Передайте --redis-url или задайте REDIS_URL")

    state = json.loads(Path(args.state).read_text(encoding="utf-8"))
    api_url = args.api_url or state["api_url"] or "http://backend:8000"
    events = RedisEventSource(
        args.redis_url, [session["id"] for session in state["sessions"]]
    )
    try:
        summary = run_demo_scenario(
            DemoApi(api_url),
            state,
            events,
            delay_scale=args.delay_scale,
        )
    finally:
        events.close()
    print(json.dumps(summary["sessions"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

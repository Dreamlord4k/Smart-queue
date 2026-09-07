from __future__ import annotations

import argparse
from datetime import date, timedelta
import json
import os
from pathlib import Path
import re
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

import httpx
from sqlalchemy import create_engine, text


DEMO_PASSWORD = "Demo-T013-Password!"
DEFAULT_STATE_PATH = "/demo/state.json"
STUDENT_NAMES = [
    "Алексеева Анна",
    "Белов Борис",
    "Васильева Вера",
    "Громов Глеб",
    "Иванова Ирина",
    "Козлов Кирилл",
    "Морозова Мария",
    "Петров Павел",
    "Смирнов Сергей",
    "Фёдорова Софья",
]


class DemoApiError(RuntimeError):
    pass


class DemoApi:
    def __init__(
        self,
        base_url: str,
        *,
        client: Any | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.client = client or httpx.Client(timeout=15)

    def request(
        self,
        method: str,
        path: str,
        *,
        token: str | None = None,
        json_body: dict[str, Any] | None = None,
        expected: tuple[int, ...] = (200,),
    ) -> Any:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        response = self.client.request(
            method,
            f"{self.base_url}{path}" if self.base_url else path,
            headers=headers,
            json=json_body,
        )
        if response.status_code not in expected:
            raise DemoApiError(
                f"{method} {path}: HTTP {response.status_code}: {response.text}"
            )
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    def login(self, email: str, password: str = DEMO_PASSWORD) -> str:
        body = self.request(
            "POST",
            "/auth/login",
            json_body={"email": email, "password": password},
        )
        return str(body["access_token"])


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", value.lower()).strip("-")
    if not slug:
        raise ValueError("run-id должен содержать латинские буквы или цифры")
    return slug[:32]


def _group_rows(run_id: str) -> list[tuple[UUID, str]]:
    return [
        (
            uuid5(NAMESPACE_URL, f"smart-queue:{run_id}:group:{index}"),
            f"Демо {run_id} — ИВТ-{index:02d}",
        )
        for index in (1, 2)
    ]


def _account_rows(run_id: str) -> tuple[dict[str, str], list[dict[str, str]]]:
    teacher = {
        "email": f"demo.t013.{run_id}.teacher@example.com",
        "full_name": "Демидов Дмитрий",
        "password": DEMO_PASSWORD,
    }
    students = [
        {
            "email": f"demo.t013.{run_id}.student{index:02d}@example.com",
            "full_name": full_name,
            "password": DEMO_PASSWORD,
        }
        for index, full_name in enumerate(STUDENT_NAMES, start=1)
    ]
    return teacher, students


def _delete_existing_accounts(
    api: DemoApi,
    accounts: list[dict[str, str]],
) -> None:
    for account in accounts:
        try:
            token = api.login(account["email"], account["password"])
        except DemoApiError:
            continue
        api.request("DELETE", "/auth/me", token=token, expected=(204,))


def _replace_demo_groups(
    db_url: str,
    groups: list[tuple[UUID, str]],
) -> None:
    engine = create_engine(db_url, pool_pre_ping=True)
    try:
        with engine.begin() as connection:
            for group_id, _ in groups:
                connection.execute(
                    text("DELETE FROM groups WHERE id = :group_id"),
                    {"group_id": group_id},
                )
            for group_id, name in groups:
                connection.execute(
                    text("INSERT INTO groups (id, name) VALUES (:id, :name)"),
                    {"id": group_id, "name": name},
                )
    finally:
        engine.dispose()


def _register_accounts(
    api: DemoApi,
    teacher: dict[str, str],
    students: list[dict[str, str]],
    groups: list[tuple[UUID, str]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    teacher_response = api.request(
        "POST",
        "/auth/register",
        json_body={**teacher, "role": "teacher"},
        expected=(201,),
    )
    student_responses = []
    for index, student in enumerate(students):
        student_responses.append(
            api.request(
                "POST",
                "/auth/register",
                json_body={
                    **student,
                    "role": "student",
                    "group_id": str(groups[index % len(groups)][0]),
                },
                expected=(201,),
            )
        )
    return teacher_response, student_responses


def generate_demo_data(
    api: DemoApi,
    *,
    db_url: str,
    run_id: str = "demo",
    session_date: date | None = None,
    state_path: str = DEFAULT_STATE_PATH,
) -> dict[str, Any]:
    normalized_run_id = _slug(run_id)
    groups = _group_rows(normalized_run_id)
    teacher, students = _account_rows(normalized_run_id)

    # Очистка пользователей идёт через публичный API. Прямой SQL ограничен
    # группами, для которых в MVP нет create/delete endpoint.
    _delete_existing_accounts(api, [teacher, *students])
    _replace_demo_groups(db_url, groups)
    teacher_response, student_responses = _register_accounts(
        api, teacher, students, groups
    )
    teacher_token = api.login(teacher["email"], teacher["password"])

    demo_date = session_date or (date.today() + timedelta(days=1))
    session_specs = [
        {
            "course_name": "Алгоритмы — поток 1",
            "room": "Р-123",
            "date": demo_date.isoformat(),
            "start_time": "10:00:00",
            "duration_default": 1,
            "capacity": 1,
        },
        {
            "course_name": "Сети — поток 2",
            "room": "Р-321",
            "date": demo_date.isoformat(),
            "start_time": "10:20:00",
            "duration_default": 1,
            "capacity": 2,
        },
    ]
    sessions = []
    for spec in session_specs:
        created = api.request(
            "POST",
            "/sessions",
            token=teacher_token,
            json_body={
                **spec,
                "group_ids": [str(group_id) for group_id, _ in groups],
                "student_ids": [],
            },
            expected=(201,),
        )
        queue = created["queue"]
        names_by_id = {
            response["id"]: student["full_name"]
            for response, student in zip(student_responses, students, strict=True)
        }
        actual_names = [names_by_id[entry["student_id"]] for entry in queue]
        if actual_names != sorted(actual_names, key=str.casefold):
            raise RuntimeError("API создал очередь не в алфавитном порядке")
        sessions.append(
            {
                "id": created["id"],
                "course_name": created["course_name"],
                "capacity": created["capacity"],
                "queue": queue,
            }
        )

    state = {
        "run_id": normalized_run_id,
        "seed": 1307,
        "api_url": api.base_url,
        "date": demo_date.isoformat(),
        "teacher": {**teacher, "id": teacher_response["id"]},
        "students": [
            {**student, "id": response["id"]}
            for student, response in zip(students, student_responses, strict=True)
        ],
        "groups": [
            {"id": str(group_id), "name": name} for group_id, name in groups
        ],
        "sessions": sessions,
        "common_student_id": student_responses[8]["id"],
    }
    destination = Path(state_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return state


def main() -> None:
    parser = argparse.ArgumentParser(description="Генератор демо-данных Smart Queue")
    parser.add_argument("--api-url", default="http://backend:8000")
    parser.add_argument("--db-url", default=os.environ.get("DB_URL"))
    parser.add_argument("--run-id", default="demo")
    parser.add_argument("--date", type=date.fromisoformat)
    parser.add_argument("--state", default=DEFAULT_STATE_PATH)
    args = parser.parse_args()
    if not args.db_url:
        parser.error("Передайте --db-url или задайте DB_URL")

    state = generate_demo_data(
        DemoApi(args.api_url),
        db_url=args.db_url,
        run_id=args.run_id,
        session_date=args.date,
        state_path=args.state,
    )
    print(
        f"Готово: {len(state['groups'])} группы, {len(state['students'])} студентов, "
        f"{len(state['sessions'])} сессии. Состояние: {args.state}"
    )


if __name__ == "__main__":
    main()

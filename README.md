# Умная очередь на сдачу лабораторных и экзаменов

Веб-сервис для вуза: преподаватель создаёт сессию приёма и ведёт очередь,
студент видит позицию и расчётное время (ETA), получает уведомления в Telegram.
Подробности продукта — `PRODUCT.md`, техническая спецификация — `docs/TECH_SPEC.md`,
план этапов — `PLAN.md`, декомпозиция задач — `TASKS.md`.

## Требования

- Docker и Docker Compose.
- Для frontend-проверок отдельно: Node.js 22 и npm.

## Быстрый старт

```bash
cp .env.example .env
docker compose up --build
```

- Frontend: http://localhost:5173
- Backend API: http://localhost:8000
- Проверка живости: `GET http://localhost:8000/health` → `{"status":"ok"}`

Остановка с удалением данных:

```bash
docker compose down -v
```

## Порты

| Сервис   | Порт по умолчанию | Переменная     |
|----------|-------------------|----------------|
| Frontend | 5173              | `FRONTEND_PORT`|
| Backend  | 8000              | `BACKEND_PORT` |
| Postgres | внутренний 5432   | —              |

Пример запуска backend на другом порту (порт 8000 уже занят):

```bash
BACKEND_PORT=18000 docker compose up --build backend
```

## Миграции базы

При старте backend-контейнер автоматически применяет все миграции
(`alembic upgrade head`). Вручную — так:

```bash
docker compose exec backend alembic -c /workspace/backend/alembic.ini upgrade head
```

## Backend-тесты

Выполняются в backend-контейнере. Для demo-тестов каталог `scripts` монтируется
отдельно, потому что его включение в production-образ относится к T-014:

```bash
docker compose run --rm \
  -v "$PWD/scripts:/workspace/scripts:ro" \
  backend python -m pytest -q -p no:cacheprovider /tests
```

Ожидается **53 passed**, включая сквозной синтетический сценарий.

## Frontend-проверки

```bash
cd frontend
npm ci
npm test -- --run
npm run build
```

## Запуск по локальной сети (демо с телефона)

`.env.example` уже содержит подсказку: замените `192.168.1.10` на IP машины
с Docker и перезапустите compose.

```bash
VITE_API_BASE_URL=http://192.168.1.10:8000
CORS_ORIGINS=http://192.168.1.10:5173
PUBLIC_BASE_URL=http://192.168.1.10:8000
```

- `VITE_API_BASE_URL` — адрес backend API, который вшит во frontend при сборке.
- `CORS_ORIGINS` — адрес frontend, с которого backend разрешает запросы.
- После смены переменных пересоберите frontend: `docker compose up --build`.

## Воспроизводимый демо-сценарий

Генератор создаёт только синтетические данные в namespace `demo`: две группы,
преподавателя, десять студентов и две сессии одного дня с общими участниками.
У сессий разные `capacity`: 1 и 2. Повторный запуск сначала удаляет только
собственные demo-аккаунты через API и создаёт тот же изолированный набор заново.

Для безопасного fake Telegram-прогона остановите bot worker: сценарий читает
настоящие realtime-события Redis, но передаёт их в память fake-транспорту и не
обращается к Telegram API.

```bash
docker compose up -d postgres redis backend frontend
docker compose stop bot
mkdir -p /tmp/smart-queue-demo
docker compose run --rm --no-deps \
  -v "$PWD/scripts:/workspace/scripts:ro" \
  -v /tmp/smart-queue-demo:/demo \
  backend python /workspace/scripts/generate_demo_data.py --api-url http://backend:8000
docker compose run --rm --no-deps \
  -v "$PWD/scripts:/workspace/scripts:ro" \
  -v /tmp/smart-queue-demo:/demo \
  backend python /workspace/scripts/run_demo_scenario.py
```

Сценарий автоматически выполняет через публичный API:

1. отказ с отдельным `absence_reason` и проверку независимости второй очереди;
2. self-reorder и фиксацию с отдельным `lock_reason`;
3. заморозку и запуск обеих сессий;
4. `done`/`skip` со случайными короткими задержками, пересчёт EMA/ETA и каналов;
5. закрытие сессий и формирование отчётов «до/после».

В консоли должны появиться пять строк с `✓`, включая подтверждение
`capacity=1`, `capacity=2`, realtime и всех трёх Telegram-триггеров. Для
мгновенного технического прогона добавьте сценарию `--delay-scale 0`.

Учётные записи синтетические. Преподаватель:
`demo.t013.demo.teacher@example.com`; студенты:
`demo.t013.demo.student01@example.com` … `student10@example.com`.
Общий пароль: `Demo-T013-Password!`.

## Структура репозитория

- `backend/` — FastAPI: модели, маршруты `/auth`, `/sessions`, очереди, ETA.
- `frontend/` — React SPA (Vite): экраны студента и преподавателя.
- `scripts/` — воспроизводимый генератор и сквозной API-сценарий.
- `tests/` — backend-тесты, включая demo-сценарий без внешней отправки.
- `docs/` — спецификация и отчёты исполнителей (`docs/agent/tasks/<ID>/`).

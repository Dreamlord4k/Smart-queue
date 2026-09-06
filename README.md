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

Выполняются в запущенном backend-контейнере (тесты примонтированы в `/tests`):

```bash
docker compose exec backend python -m pytest -q -p no:cacheprovider /tests/auth /tests/sessions /tests/queue
```

Ожидается **29 passed**: `tests/auth` (5), `tests/sessions` (10),
`tests/queue` (14).

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

## Структура репозитория

- `backend/` — FastAPI: модели, маршруты `/auth`, `/sessions`, очереди, ETA.
- `frontend/` — React SPA (Vite): экраны студента и преподавателя.
- `tests/` — backend-тесты (auth, sessions, queue).
- `docs/` — спецификация и отчёты исполнителей (`docs/agent/tasks/<ID>/`).

# Умная очередь

Smart Queue — система управления потоком людей и временем ожидания.
Первый сценарий — экзамены и лабораторные работы в вузе, но механизм
очереди не привязан к ним и переносится на любой процесс с очередью.

## Проблема

- Студент не знает, когда его примут, и вынужден ждать возле аудитории.
- Преподаватель вручную управляет порядком: опоздания, пропуски,
  перестановки и постоянные вопросы «кто следующий?».
- Время приёма трудно прогнозировать: статичный список не учитывает,
  кто идёт быстрее, а кто медленнее.

## Решение

- Преподаватель создаёт сессию и добавляет участников — система формирует очередь.
- Студент видит свою позицию и динамический ETA (расчётное время ожидания, временное окно).
- Преподаватель управляет приёмом одной кнопкой; очередь пересчитывается
  после каждого фактического изменения (завершение, пропуск, отказ, перестановка).
- Realtime и Telegram позволяют студенту не дежурить у аудитории.

## Для кого

### Студент

Сидит у аудитории и ждёт своей защиты: видит позицию, временное окно
и статус, получает уведомления, может сам подвинуть свою карточку,
зафиксировать место или отказаться от сессии с причиной.

### Преподаватель

Ведёт приём: видит всех участников и их состояния, завершает и пропускает
одной кнопкой, добавляет опоздавших на лету, замораживает порядок,
закрывает сессию с отчётом.

## Features

### Для студента

- Личные очереди: предмет, преподаватель, аудитория, дата и время, позиция, статус.
- Динамический ETA — пересчёт после каждого изменения очереди.
- Reorder только собственной карточки (drag-and-drop или кнопки на тач-экранах).
- Lock места с необязательной причиной.
- Отказ от конкретной сессии с отдельной причиной (запись остаётся в истории).
- Telegram-уведомления: «скоро», «подходите», «заходите».
- Живые обновления без перезагрузки страницы.

### Для преподавателя

- Создание сессии с мультивыбором групп и отдельных студентов.
- Добавление студента в очередь, в том числе опоздавшего, без пересоздания
  сессии (доступно, пока сессия не закрыта и не отменена).
- Управление приёмом: done / skip одной кнопкой; следующий поднимается автоматически.
- Freeze списка: после заморозки порядок не меняет никто.
- Изменение длительности приёма на лету.
- Несколько параллельных каналов через `capacity`.
- Отчёт после закрытия: принято/пропущено, средняя длительность,
  плановое vs фактическое время, средняя ошибка ETA.

Подробности продукта: `PRODUCT.md`, `docs/TECH_SPEC.md`, `PLAN.md`, `TASKS.md`.

## Польза для преподавателя

- Меньше ручного управления очередью и объявлений «кто следующий».
- Всегда видно актуальное состояние участников и их причины.
- Пропуски и опоздания обрабатываются парой кликов, опоздавшего можно
  добавить прямо в текущую очередь.
- После завершения приёма следующий участник поднимается автоматически.
- Параллельные каналы (`capacity`) для потока из нескольких проверяющих.
- После сессии — данные о ходе приёма и точности ETA.

## До и после

### Без системы

- Студент не знает, когда его примут.
- Преподаватель вручную управляет порядком.
- Много вопросов «кто следующий?».
- Пропуски и опоздания требуют ручной обработки.
- Время приёма трудно прогнозировать.

### С Smart Queue

- Студент видит позицию и временное окно.
- Порядок управляется системой.
- Следующий участник назначается автоматически.
- Пропуски и отказы учитываются в состоянии очереди.
- ETA пересчитывается по фактическому времени приёма.

## Как это работает

### ETA для пользователя

ETA — динамическое окно времени, а не точная минута. Это прогноз:
система смотрит, сколько длился приём по факту, и сдвигает окно
всех остальных. Прогноз может ошибаться — отчёт после сессии показывает,
насколько именно.

### ETA для разработчика

Используется EMA:

```text
new_average = alpha * actual_duration + (1 - alpha) * old_average
```

В текущей реализации `alpha = 0.3` (`backend/config.py`, `EMA_ALPHA`).
Первое наблюдение становится начальным средним; дисперсия ведётся
экспоненциальным сглаживанием и задаёт ширину окна. При `capacity > 1`
прогноз жадно распределяется по нескольким каналам
(`backend/queue/eta.py`). ETA всегда остаётся прогнозом, а не гарантией.

### Realtime

```text
Backend → PostgreSQL commit → Redis Pub/Sub → WebSocket → Frontend
```

WebSocket — быстрый путь. Опрос примерно каждые 5 секунд — страховка
от рассинхронизации при обрыве соединения. Важно: Redis здесь только
шина событий, а не основная база данных — источником правды остаётся PostgreSQL.

## Architecture

```text
Browser
  |
  v
NGINX (единая внешняя точка входа)
  |
  +-----> Frontend (React/Vite)
  |
  +-----> FastAPI backend
            |
      +-----+-----+
      |           |
      v           v
  PostgreSQL   Redis
  (данные)     (Pub/Sub)
      |
      v
  WebSocket ---> Browser

FastAPI / notification worker ---> Telegram Bot API (внешняя интеграция)
```

- **PostgreSQL** — persistent business state, source of truth.
- **Redis** — realtime/event distribution, состояние переживает рестарт по необходимости.
- **FastAPI** — business logic и API.
- **React/Vite** — frontend.
- **NGINX** — reverse proxy и единая внешняя точка входа.
- **Docker Compose** — orchestration нескольких контейнеров.

## Tech Stack

### Backend

- Python 3.12
- FastAPI
- SQLAlchemy 2.0
- Alembic
- PyJWT, argon2-cffi, httpx, redis-py

### Frontend

- React 19
- Vite 7
- TypeScript
- Vitest

### Infrastructure

- PostgreSQL 16
- Redis 7
- Docker
- Docker Compose
- NGINX 1.27

### Integrations

- Telegram Bot API

### CI

- GitHub Actions

## Quick Start

### Requirements

- Docker и Docker Compose.
- Для frontend-проверок отдельно: Node.js 22 и npm.

### Свои секреты

```bash
cp .env.example .env
openssl rand -hex 32
```

```bash
POSTGRES_PASSWORD=<случайный пароль>
JWT_SECRET=<вывод openssl rand -hex 32>
```

`TELEGRAM_BOT_TOKEN` и `TELEGRAM_WEBHOOK_SECRET` нужны только для запуска
с настоящим ботом; локально оставьте пустыми. Реальные значения — только
в локальном `.env`, он не коммитится.

### Run

```bash
docker compose up --build
```

- Приложение: http://localhost (nginx → frontend + API)
- Напрямую: frontend http://localhost:5173, API http://localhost:8000
- Демо с телефона в той же сети — в `.env`:

```bash
CORS_ORIGINS=http://192.168.1.10
VITE_API_BASE_URL=http://192.168.1.10/api
PUBLIC_BASE_URL=http://192.168.1.10
```

### Check

```bash
curl http://localhost/health
```

Проверяет backend, Postgres и Redis (503, если что-то недоступно).
Миграции применяются сами при старте backend (`alembic upgrade head`
в CMD образа). Вручную:

```bash
docker compose exec backend alembic -c /workspace/backend/alembic.ini upgrade head
```

### Stop

```bash
docker compose down
```

> НЕ используйте `docker compose down -v`, если нужно сохранить данные
> PostgreSQL — флаг `-v` удаляет volumes вместе с базой.

## Configuration

Все переменные — в `.env.example`: порты (`BACKEND_PORT`, `NGINX_HTTP_PORT`,
`NGINX_HTTPS_PORT`), `DB_URL`, `JWT_SECRET` и TTL токенов, `CORS_ORIGINS`,
`VITE_API_BASE_URL`, `PUBLIC_BASE_URL`, Telegram (`TELEGRAM_BOT_TOKEN`,
`TELEGRAM_BOT_USERNAME`, `TELEGRAM_WEBHOOK_SECRET`), `DOMAIN` и
`LETSENCRYPT_EMAIL` для HTTPS. Порт backend меняется так:

```bash
BACKEND_PORT=18000 docker compose up --build backend
```

## Deployment

Короткий сценарий: `.env` → запуск → HTTPS → webhook → обновление.

Есть единый мастер, который показывает состояние и предлагает локальный
запуск, production HTTPS, безопасное обновление, досев групп или диагностику
(`.env` не перезаписывает, volumes не удаляет):

```bash
./scripts/deploy/setup.sh
```

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\deploy\setup.ps1
```

### Production (домен + HTTPS)

Направьте A-запись домена на сервер (регистратор или DuckDNS),
откройте порты 80/443 и заполните в `.env`:

```bash
DOMAIN=queue.example.edu
LETSENCRYPT_EMAIL=admin@example.edu
PUBLIC_BASE_URL=https://queue.example.edu
CORS_ORIGINS=https://queue.example.edu
VITE_API_BASE_URL=https://queue.example.edu/api
```

```bash
./scripts/deploy/issue_certificate.sh
```

Проверка конфигов без запуска:

```bash
docker compose config --quiet
docker compose -f docker-compose.yml -f scripts/deploy/docker-compose.https.yml config --quiet
```

Обновление сертификата по cron:

```cron
17 3 * * * cd /srv/smart-queue && ./scripts/deploy/renew_certificate.sh
```

### Telegram webhook

Секрет сверяется с заголовком `X-Telegram-Bot-Api-Secret-Token`:

```bash
curl -X POST "https://api.telegram.org/bot<TOKEN>/setWebhook" \
  -d url=https://queue.example.edu/telegram/webhook \
  -d secret_token=<TELEGRAM_WEBHOOK_SECRET>
```

Локально webhook не нужен — бот работает в long polling, без токена опрос отключён.

### Обновление на боевом сервере

```bash
git pull origin main
docker compose up --build -d
```

На проде с HTTPS — с оверлеем:

```bash
docker compose -f docker-compose.yml -f scripts/deploy/docker-compose.https.yml up --build -d
```

Проверка:

```bash
docker compose exec backend alembic -c /workspace/backend/alembic.ini upgrade head
curl https://<домен>/health
```

Данные и сессии сохраняются (Postgres в volume, без `-v`). Токены живы,
пока тот же `JWT_SECRET`. `.env` не перезаписывать. Фронт после — Ctrl+F5.

## Testing

Backend (в контейнере):

```bash
docker compose run --rm -v "$PWD/scripts:/workspace/scripts:ro" \
  backend python -m pytest -q -p no:cacheprovider /tests
```

Папки: `auth`, `sessions`, `groups`, `queue`, `notifications`, `realtime`, `infra`, `demo`.

Фронт:

```bash
cd frontend && npm ci && npm test -- --run && npm run build
```

CI (GitHub Actions на push/PR в `main`, автоматического деплоя нет — это CI, не CD):

- backend: зависимости, миграции, проверка compose-конфигов, pytest, smoke всего контура (health, API, frontend, WebSocket upgrade);
- frontend: тесты и production-сборка.

## Reliability and Recovery

- PostgreSQL — persistent state в volume `postgres_data`; данные переживают
  пересоздание контейнеров.
- Redis можно пересоздать: источник правды — Postgres, очередь восстанавливается из базы.
- Backend можно перезапускать: миграции идемпотентны (`upgrade head`).
- Клиент после обрыва догоняет состояние опросом каждые 5 секунд.
- Backup нужен прежде всего для PostgreSQL.

> Для production следующий этап — автоматизировать регулярный PostgreSQL
> backup и проверку восстановления (сейчас автоматизации нет).

## Демо-панель для комиссии

В `.env` включите режим и перезапустите backend:

```bash
DEMO_MODE=true
docker compose up --build -d backend frontend nginx
```

Один раз создайте стабильный набор данных:

```bash
docker compose run --rm --no-deps -v "$PWD/scripts:/workspace/scripts:ro" \
  backend python /workspace/scripts/seed_demo_ui.py
```

Слева появятся кнопки «Демо-препод» и «Демо-студент». Откройте их в разных
вкладках: токены хранятся отдельно для каждой вкладки, а изменения активной
очереди передаются через realtime. Кнопка «Сбросить демо» восстанавливает
исходные две очереди; открытая demo-вкладка делает тот же сброс каждые 30 минут.
При `DEMO_MODE=false` панель и demo-login недоступны.

## Demo Account

> Только синтетическая учётная запись для демонстрации.
> Реальных персональных данных не содержит.

Логин `demo.t013.demo.student01@example.com` … `student10@example.com`,
преподаватель `demo.t013.demo.teacher@example.com`, пароль `Demo-T013-Password!`
(создаются `scripts/generate_demo_data.py`, значение по умолчанию в коде скрипта).

## Как увидеть живьём

Короткий сценарий защиты:

1. Открыть teacher (демо-препод).
2. Открыть student в другом окне (демо-студент).
3. Открыть очередь.
4. Показать ETA-окно студента.
5. Изменить состояние очереди (отказ/перестановка).
6. Показать realtime без refresh во втором окне.
7. Показать freeze и lock.
8. Показать done/skip.
9. Показать `capacity=2` (два канала).
10. Показать отчёт план/факт.

Синтетика для сценария (2 группы, 10 студентов, 2 сессии):

```bash
docker compose up -d postgres redis backend frontend
docker compose stop bot
mkdir -p /tmp/smart-queue-demo
docker compose run --rm --no-deps -v "$PWD/scripts:/workspace/scripts:ro" \
  -v /tmp/smart-queue-demo:/demo backend \
  python /workspace/scripts/generate_demo_data.py --api-url http://backend:8000
docker compose run --rm --no-deps -v "$PWD/scripts:/workspace/scripts:ro" \
  -v /tmp/smart-queue-demo:/demo backend \
  python /workspace/scripts/run_demo_scenario.py
```

Сценарий ставит пять `✓`: отказ, reorder + lock, freeze, `done`/`skip` с пересчётом, отчёты.
Telegram идёт в fake-транспорт (29 сообщений, 0 запросов наружу). Для мгновенного
прогона добавьте `--delay-scale 0`. Вручную те же шаги видны в двух окнах:
позиции и окна времени пересчитываются сразу в обоих.

## Troubleshooting

### Port already in use

`Bind 0.0.0.0:8000` — старый стенд не погашен или хвост Docker держит проброс:
`docker compose down`, висящих найти (`lsof -i :PORT`, `docker ps -a`) и снести,
либо соседние порты. Переменные — в одной строке с командой или через `export`.

### Environment variables

`VAR=x` без `export` не уходит в дочерний процесс. Проверка:
`docker compose config | grep VAR`.

### CORS

CORS 400 на OPTIONS — дефолт разрешает только localhost. Задать `CORS_ORIGINS` +
`VITE_API_BASE_URL` и пересобрать фронт (Vite вшивает адрес в build).
Без суффикса `/api` — 404 на все запросы: `VITE_API_BASE_URL=https://<домен>/api`.

### HTTPS / DNS

Серт не выпускается: `.sh` запускать в Git Bash, сначала `curl http://<домен>/health`
снаружи, `DOMAIN` — FQDN с точкой, на вопрос EFF — N. 502 от nginx: подъём с оверлеем
+ `--force-recreate nginx`. Снаружи: только inbound 80/443, проброс на IP этого PC,
белый IP = резолв `nslookup`. DNS: `A` на IP, TTL 300, Cloudflare только DNS-only.

### Telegram

С сервера недоступен `api.telegram.org` — нужен egress (VPN на хосте + split tunneling).
Проверка: `curl.exe https://api.telegram.org --max-time 10`. Webhook не встаёт —
не перепутать 3 секрета: `BOT_TOKEN`, `WEBHOOK_SECRET`, `JWT_SECRET`.
В PowerShell `curl` — алиас, использовать `curl.exe`.

### Database / migrations

Backend падает на старте: пароль в `POSTGRES_PASSWORD` и `DB_URL` различаются,
пустой `JWT_SECRET`. Группы при регистрации: создания через API нет by design —
seed через `INSERT` + `RETURNING id`.

### Realtime

Нет живых обновлений: проверить WS `ws://<хост>/ws/sessions/<id>` и события Redis
`session:{id}`; при обрыве клиент опрашивает API каждые 5 секунд — рассинхрон
закрывается сам, страница не нужна в перезагрузке.

Золотое правило — по шагам, не прыгать: HTTP снаружи → серт → HTTPS → webhook → дым с LTE.

```bash
curl http://<домен>/health                                   # 1. виден снаружи
./scripts/deploy/issue_certificate.sh                       # 2. серт
docker compose -f docker-compose.yml \
  -f scripts/deploy/docker-compose.https.yml up -d --force-recreate nginx  # 3. https
curl -X POST "https://api.telegram.org/bot<TOKEN>/setWebhook" \
  -d url=https://<домен>/telegram/webhook \
  -d secret_token=<TELEGRAM_WEBHOOK_SECRET>                 # 4. webhook
# 5. дымовой прогон сценария и фронта с мобильного интернета
```

## Beyond Exams

> Smart Queue — это не только очередь на экзамен.
> Это универсальный механизм управления потоком людей и временем ожидания.

Механизм (сессия → очередь → ETA → вызов) не привязан к экзаменам.
Потенциальные направления (roadmap, не реализовано):

- лабораторные работы;
- деканат;
- студенческий офис;
- получение документов;
- консультации;
- другие университетские сервисы с потоком посетителей.

## Roadmap

### Возможный следующий этап инфраструктуры

- Несколько backend replicas.
- Отдельный migration job.
- Централизованные логи.
- Metrics.
- Rate limiting.
- Более зрелая production auth.
- Backup/restore automation.
- Load balancing.

> Docker Compose подходит для текущего MVP; при существенном росте нагрузки
> архитектуру можно горизонтально масштабировать.

## Project Structure

```text
backend/    — backend/API/business logic (FastAPI)
frontend/   — React frontend (Vite)
bot/        — Telegram worker
tests/      — backend tests
scripts/    — deployment/demo scripts
docs/       — documentation
nginx/      — reverse proxy configuration
```

## Known Limitations

MVP-ограничения, подтверждённые кодом:

- Регистрация преподавателя открыта всем — нужно усиление.
- Refresh token rotation не реализован (токен многоразовый до истечения).
- WebSocket принимает токен в query-параметре — credentials можно сделать безопаснее.
- Токены фронта хранятся в localStorage/sessionStorage — хранение можно усилить.
- Redis Pub/Sub — шина событий без durable log: пропущенное событие закрывается polling-фallback.

## Документы

- `PRODUCT.md` — продукт и границы MVP.
- `docs/TECH_SPEC.md` — полная техническая спецификация.
- `PLAN.md` — этапы.
- `TASKS.md` — декомпозиция (T-001–T-014, все DONE).
- `docs/` — обзоры и отчёты исполнителей (`docs/agent/tasks/<ID>/`).

# Умная очередь

Живая очередь на сдачу лабораторных и экзаменов без толпы под дверью.
Преподаватель ведёт приём одной кнопкой, студент видит свою позицию
и время-окно, а не «ждите, вас позовут». Для студентов и преподавателей
ИРИТ-РТФ: часы ожидания у аудитории превращаются в точный ETA и три
Telegram-уведомления — «скоро», «подходите», «заходите».

## Что реализовано

Всё из `TASKS.md` (T-001–T-014, все DONE):

- **Аккаунты** — регистрация/логин, JWT access+refresh, роли студент/преподаватель, группы, удаление профиля.
- **Сессии** — создание с мультивыбором групп и студентов, очередь сразу по алфавиту; дашборд преподавателя; старт/пауза/закрытие/отмена, длительность на лету, добавление и удаление участников, заморозка списка.
- **Очереди студента** — «Мои очереди», отказ от сессии с причиной, self-reorder только своей карточки, фиксация места с `lock_reason`, завершение и пропуск преподавателем, несколько параллельных каналов (`capacity`).
- **ETA/EMA** — скользящее среднее фактического времени (`alpha=0.3`), дисперсия, жадный пересчёт по каналам, диапазон вместо точной цифры.
- **Отчёты** — принято/пропущено, средняя длительность, плановое vs фактическое время, средняя ошибка ETA.
- **Реалтайм** — Redis pub/sub (`session:{id}`), WebSocket, fallback-опрос каждые 5 секунд.
- **Telegram** — привязка одноразовым кодом, webhook с секретом, три уведомления (мягкое/буфер/финал), дедупликация, локально — long polling.
- **CI** — GitHub Actions на push/PR в `main`: миграции, pytest, smoke всего контура, тесты и сборка фронта.

Подробности: `PRODUCT.md`, `docs/TECH_SPEC.md`, `PLAN.md`, `TASKS.md`.

## Свои секреты

```bash
cp .env.example .env
openssl rand -hex 32
```

Сгенерированную строку впишите в `.env`:

```bash
POSTGRES_PASSWORD=<случайный пароль>
JWT_SECRET=<вывод openssl rand -hex 32>
```

- `TELEGRAM_BOT_TOKEN` и `TELEGRAM_WEBHOOK_SECRET` нужны только для
глобального запуска с настоящим ботом; локально оставьте пустыми.
- Реальные значения — только в локальном `.env`, он не коммитится.

## Запуск локально

```bash
docker compose up --build
```

- Приложение: http://localhost (nginx → frontend + API)
- Напрямую: frontend http://localhost:5173, API http://localhost:8000
- Health: `curl http://localhost/health`
- Порт backend меняется так: `BACKEND_PORT=18000 docker compose up --build backend`
- Миграции применяются сами при старте backend. Вручную:

```bash
docker compose exec backend alembic -c /workspace/backend/alembic.ini upgrade head
```

Остановка с удалением данных: `docker compose down -v`

Демо с телефона в той же сети — в `.env`:

```bash
CORS_ORIGINS=http://192.168.1.10
VITE_API_BASE_URL=http://192.168.1.10/api
PUBLIC_BASE_URL=http://192.168.1.10
```

## Запуск глобально (домен + HTTPS)

Направьте A-запись домена на сервер (регистратор или DuckDNS),
откройте порты 80/443 и заполните в `.env`:

```bash
DOMAIN=queue.example.edu
LETSENCRYPT_EMAIL=admin@example.edu
PUBLIC_BASE_URL=https://queue.example.edu
CORS_ORIGINS=https://queue.example.edu
VITE_API_BASE_URL=https://queue.example.edu/api
TELEGRAM_BOT_TOKEN=<токен от BotFather>
TELEGRAM_BOT_USERNAME=<username без @>
TELEGRAM_WEBHOOK_SECRET=<случайная строка>
```

Выпуск сертификата и переход nginx на TLS:

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

Webhook Telegram (секрет сверяется с заголовком `X-Telegram-Bot-Api-Secret-Token`):

```bash
curl -X POST "https://api.telegram.org/bot<TOKEN>/setWebhook" \
  -d url=https://queue.example.edu/telegram/webhook \
  -d secret_token=<TELEGRAM_WEBHOOK_SECRET>
```

Локально webhook не нужен — бот работает в long polling, без токена опрос отключён.

## Обновление на боевом сервере

```bash
git pull origin main
docker compose up --build -d
```

На проде с HTTPS — с оверлеем:

```bash
docker compose -f docker-compose.yml -f scripts/deploy/docker-compose.https.yml up --build -d
```

Проверка после обновления:

```bash
docker compose exec backend alembic -c /workspace/backend/alembic.ini upgrade head
curl https://<домен>/health
```

Что сохраняется, а что нет:

- Данные и сессии сохраняются: Postgres живёт в volume — главное, не добавлять `-v` к `down`.
- Токены живы, пока тот же `JWT_SECRET` — refresh продолжает работать без перелогина.
- `.env` не перезаписывать: `git pull` его не трогает, образец лежит в `.env.example`.
- Фронт после обновления — жёсткая перезагрузка в браузере (Ctrl+F5), иначе старый бандл из кэша.

## Тесты

Backend (в контейнере, всего 50+):

```bash
docker compose run --rm -v "$PWD/scripts:/workspace/scripts:ro" \
  backend python -m pytest -q -p no:cacheprovider /tests
```

Папки: `auth`, `sessions`, `groups`, `queue`, `notifications`, `realtime`, `infra`, `demo`.

Фронт:

```bash
cd frontend && npm ci && npm test -- --run && npm run build
```

## Как увидеть живьём

Синтетика (2 группы, 10 студентов, 2 сессии; логин `demo.t013.demo.student01@example.com`, пароль `Demo-T013-Password!`):

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

Сценарий ставит пять `✓`: отказ, reorder + lock, freeze, `done`/`skip` с пересчётом, отчёты. Без внешней отправки: realtime читается из Redis, Telegram идёт в fake-транспорт (29 сообщений, 0 запросов наружу).

Вручную в двух окнах (студент + преподаватель):

- **ETA** — откройте «Мои очереди» в двух окнах, нажмите «Завершить текущую»: позиции и окна времени пересчитаются сразу в обоих.
- **Фиксация** — студент ставит чек-марк с причиной, карточка блокируется для перестановки.
- **Freeze** — после «Заморозить список» drag-and-drop отклоняется сервером.
- **Done/skip** — канал освобождается, следующий вызывается автоматически, ETA пересчитывается при `capacity=2`.
- **Отчёт** — после «Закрыть сессию»: принято/пропущено, план vs факт, ошибка ETA.
- **Realtime** — события прилетают по WebSocket; при обрыве — опрос каждые 5 секунд.

## Troubleshooting (Windows PC → домен)

Боевой опыт деплоя, сжато: симптом → причина → лечение.

| Симптом | Причина | Лечение |
|---|---|---|
| `Bind 0.0.0.0:8000` | Старый стенд не погашен или хвост Docker держит проброс | `docker compose down`; висящих найти (`lsof -i :PORT`, `docker ps -a`) и снести; либо соседние порты. Переменные — в одной строке с командой или через `export` |
| Env не применился | `VAR=x` без `export` не уходит в дочерний процесс | `export VAR=...` заранее или префикс в той же строке. Проверка: `docker compose config \| grep VAR` |
| CORS 400 на OPTIONS | Дефолт разрешает только localhost | Задать `CORS_ORIGINS` + `VITE_API_BASE_URL` и пересобрать фронт (Vite вшивает адрес в build) |
| Фронт бьёт в дефолт | Нужные строки закомментированы | Раскомментировать 2 строки под домен, LAN-пример не трогать |
| 404 на все запросы API | nginx отдаёт API под `/api` | `VITE_API_BASE_URL=https://<домен>/api` — с суффиксом |
| Backend падает на старте | Пароль в `POSTGRES_PASSWORD` и `DB_URL` различаются; пустой `JWT_SECRET` | Синхронизировать пароли; задать секрет. Ручной INSERT в `groups` — с `gen_random_uuid()` |
| Нечего выбрать при регистрации | Создания групп через API нет by design | Seed: `INSERT` групп + `RETURNING id` |
| Серт не выпускается | `.sh` в PowerShell молча не выполняется; нет доступа снаружи; `DOMAIN` не FQDN | Только Git Bash (или ручные docker-команды); сначала `curl http://<домен>/health` снаружи; `DOMAIN` с точкой; на вопрос EFF — N |
| 502 от nginx | Стартовал до серта и не пересоздавался | Подъём с оверлеем + `--force-recreate nginx` после выпуска; plain `up` без оверлея убивает https |
| Нет доступа снаружи | Firewall / роутер / CGNAT | Только inbound 80/443; проброс на IP этого PC (статический lease); белый IP = резолв `nslookup` |
| `curl` с двумя `-d` падает | В PowerShell `curl` — алиас | `curl.exe`; вместо `tail` — `--tail` |
| Telegram недоступен с сервера | `api.telegram.org` без egress | VPN на хосте + split tunneling только `api.telegram.org`. Проверка: `curl.exe https://api.telegram.org --max-time 10` |
| Webhook не встаёт | Перепутаны 3 секрета | `BOT_TOKEN` от BotFather, `WEBHOOK_SECRET` свой рандом, `JWT_SECRET` свой hex |
| Dev-фронт режет чужой Host | Фильтр Vite | `allowedHosts` в `vite.config` (уже в коде) |
| Падает CI | Lock рассинхрон; rollup linux-optional | `npm install` (в контейнере, если нет node), lock не удалять |
| DNS | — | `A` на IP, TTL 300; Cloudflare только DNS-only |

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

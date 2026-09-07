#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"
cd "$PROJECT_ROOT"

SCENARIO=""
FORCE_HTTPS=false
FAILURES=0
SERVICES=(postgres redis backend bot frontend nginx)

GROUP_SEED_PYTHON=$(cat <<'PY'
from scripts.generate_demo_data import _group_rows
from backend.auth.dependencies import SessionLocal
from backend.models.group import Group

rows = _group_rows("bootstrap")
with SessionLocal() as db:
    for group_id, name in rows:
        group = db.get(Group, group_id)
        if group is None:
            db.add(Group(id=group_id, name=name))
        else:
            group.name = name
    db.commit()
print(f"Групп готово: {len(rows)}")
PY
)

ok() { printf '✓ %s\n' "$1"; }
fail() { printf '✗ %s\n  Что исправить: %s\n' "$1" "$2" >&2; }
note() { printf '  %s\n' "$1"; }

run_step() {
  local title="$1" remedy="$2"
  shift 2
  if "$@"; then
    ok "$title"
  else
    fail "$title" "$remedy"
    return 1
  fi
}

diagnostic_step() {
  if ! run_step "$@"; then
    FAILURES=$((FAILURES + 1))
  fi
  return 0
}

usage() {
  cat <<'EOF'
Использование: scripts/deploy/setup.sh [--scenario 1..5] [--https]

Без --scenario скрипт показывает интерактивное меню. Enter выбирает
безопасную проверку здоровья (сценарий 5), которая ничего не изменяет.
EOF
}

while (($#)); do
  case "$1" in
    --scenario)
      SCENARIO="${2:-}"
      shift 2
      ;;
    --https)
      FORCE_HTTPS=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      fail "Неизвестный аргумент: $1" "Запустите с --help."
      exit 2
      ;;
  esac
done

load_env() {
  if [[ -f .env ]]; then
    set -a
    # shellcheck disable=SC1091
    . ./.env
    set +a
  fi
}

ensure_env() {
  if [[ -f .env ]]; then
    note ".env уже существует — оставлен без изменений."
    return 0
  fi
  if [[ ! -f .env.example ]]; then
    return 1
  fi
  cp .env.example .env
  note "Создан .env из .env.example. Пароли оставлены явными плейсхолдерами."
  note "Перед production замените POSTGRES_PASSWORD, пароль внутри DB_URL и JWT_SECRET."
}

check_docker() {
  command -v docker >/dev/null 2>&1 &&
    docker compose version >/dev/null 2>&1 &&
    docker info >/dev/null 2>&1
}

container_health() {
  local service="$1" container status
  container="$(docker compose ps -q "$service" 2>/dev/null)"
  [[ -n "$container" ]] || return 1
  status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container" 2>/dev/null)"
  [[ "$status" == "healthy" || "$status" == "running" ]]
}

wait_services() {
  local deadline=$((SECONDS + 180)) service pending
  while ((SECONDS < deadline)); do
    pending=0
    for service in "${SERVICES[@]}"; do
      if ! container_health "$service"; then
        pending=1
      fi
    done
    ((pending == 0)) && return 0
    sleep 3
  done
  for service in "${SERVICES[@]}"; do
    container_health "$service" || note "$service не перешёл в healthy/running"
  done
  return 1
}

check_services_once() {
  local service failed=0
  for service in "${SERVICES[@]}"; do
    if ! container_health "$service"; then
      note "$service не находится в healthy/running"
      failed=1
    fi
  done
  ((failed == 0))
}

wait_seed_services() {
  local deadline=$((SECONDS + 120))
  while ((SECONDS < deadline)); do
    if container_health postgres && container_health backend; then
      return 0
    fi
    sleep 3
  done
  return 1
}

certificate_exists() {
  [[ -n "${DOMAIN:-}" ]] || return 1
  container_health nginx || return 1
  docker compose exec -T nginx test -f "/etc/letsencrypt/live/${DOMAIN}/fullchain.pem" >/dev/null 2>&1
}

https_configured() {
  certificate_exists ||
    [[ "${PUBLIC_BASE_URL:-}" == https://* || "${VITE_API_BASE_URL:-}" == https://* ]]
}

http_base_url() {
  local port="${NGINX_HTTP_PORT:-80}"
  if [[ "$port" == "80" ]]; then
    printf 'http://localhost'
  else
    printf 'http://localhost:%s' "$port"
  fi
}

https_base_url() {
  local port="${NGINX_HTTPS_PORT:-443}"
  if [[ "$port" == "443" ]]; then
    printf 'https://%s' "${DOMAIN}"
  else
    printf 'https://%s:%s' "${DOMAIN}" "$port"
  fi
}

check_health_url() {
  curl --fail --silent --show-error --max-time 15 "$1/health" >/dev/null
}

check_groups_url() {
  local response count
  response="$(curl --fail --silent --show-error --max-time 15 "$1/api/groups")" || return 1
  count="$(printf '%s' "$response" | grep -o '"id"' | wc -l | tr -d ' ')"
  [[ "$count" -ge 2 ]]
}

seed_groups() {
  docker compose run --rm --no-deps \
    -v "$PROJECT_ROOT/scripts:/workspace/scripts:ro" \
    backend python -c "$GROUP_SEED_PYTHON"
}

apply_migrations() {
  docker compose exec -T backend \
    alembic -c /workspace/backend/alembic.ini upgrade head
}

compose_up_plain() {
  docker compose up --build -d
}

compose_up_https() {
  docker compose -f docker-compose.yml \
    -f scripts/deploy/docker-compose.https.yml up --build -d
}

validate_production_env() {
  local invalid=0 jwt_secret="${JWT_SECRET:-}"
  if [[ "${POSTGRES_PASSWORD:-change-me}" == "change-me" ]]; then
    fail "POSTGRES_PASSWORD не настроен" "Замените change-me в .env и синхронно обновите пароль внутри DB_URL."
    invalid=1
  fi
  if [[ "${DB_URL:-}" == *change-me* || -z "${DB_URL:-}" ]]; then
    fail "DB_URL не настроен" "Укажите тот же пароль PostgreSQL в DB_URL внутри .env."
    invalid=1
  fi
  if [[ "$jwt_secret" == "change-me" || ${#jwt_secret} -lt 32 ]]; then
    fail "JWT_SECRET небезопасен" "Впишите в .env собственную строку длиной не менее 32 символов; скрипт не генерирует секреты молча."
    invalid=1
  fi
  if [[ -z "${DOMAIN:-}" || "${DOMAIN}" == "queue.example.edu" ]]; then
    fail "DOMAIN не настроен" "Впишите реальный домен в .env и направьте его A-запись на сервер."
    invalid=1
  fi
  if [[ -z "${LETSENCRYPT_EMAIL:-}" || "${LETSENCRYPT_EMAIL}" == "admin@example.edu" ]]; then
    fail "LETSENCRYPT_EMAIL не настроен" "Впишите настоящий email для Let's Encrypt в .env."
    invalid=1
  fi
  ((invalid == 0))
}

issue_certificate() {
  scripts/deploy/issue_certificate.sh
}

check_telegram_webhook() {
  local expected response
  [[ -n "${TELEGRAM_BOT_TOKEN:-}" ]] || {
    note "TELEGRAM_BOT_TOKEN пуст."
    return 1
  }
  [[ -n "${DOMAIN:-}" ]] || return 1
  expected="https://${DOMAIN}/api/telegram/webhook"
  response="$(curl --fail --silent --show-error --max-time 15 \
    "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getWebhookInfo")" || return 1
  [[ "$response" == *'"ok":true'* && "$response" == *"\"url\":\"${expected}\""* ]]
}

print_state() {
  local running=0 cert="нет" groups="недоступно" service base
  [[ -f .env ]] && ok ".env найден" || note ".env отсутствует"
  if check_docker; then
    for service in "${SERVICES[@]}"; do
      container_health "$service" && running=$((running + 1))
    done
    certificate_exists && cert="да"
    base="$(http_base_url)"
    https_configured && base="$(https_base_url)"
    if check_groups_url "$base"; then groups="есть (минимум 2)"; fi
    note "Запущено сервисов: ${running}/${#SERVICES[@]}"
    note "Сертификат для ${DOMAIN:-не задан}: $cert"
    note "Группы: $groups"
  else
    note "Docker/Compose или daemon пока недоступны"
  fi
}

summary() {
  local base
  if https_configured || [[ "$FORCE_HTTPS" == true || "$SCENARIO" == "2" ]]; then
    base="$(https_base_url)"
  else
    base="$(http_base_url)"
  fi
  printf '\nИтоговые адреса:\n'
  printf '  Frontend: %s/\n' "$base"
  printf '  API:      %s/api\n' "$base"
  printf '  Health:   %s/health\n' "$base"
  if [[ "$base" == https://* ]]; then
    printf '  Telegram: %s/api/telegram/webhook\n' "$base"
  else
    printf '  Telegram: не применяется без публичного HTTPS\n'
  fi
}

prepare_environment() {
  run_step "Docker и Compose готовы" \
    "Установите Docker Desktop/Engine с Compose v2 и запустите daemon." check_docker
  run_step ".env подготовлен без перезаписи" \
    "Верните .env.example в корень проекта или создайте .env вручную." ensure_env
  load_env
}

start_full_stack() {
  local use_https="${1:-false}"
  if [[ "$use_https" == true ]]; then
    run_step "Контейнеры собраны и запущены с HTTPS-overlay" \
      "Проверьте docker compose logs и свободны ли порты 80/443." compose_up_https
  else
    run_step "Контейнеры собраны и запущены" \
      "Проверьте docker compose logs и освободите занятые порты из .env." compose_up_plain
  fi
  run_step "Все сервисы healthy" \
    "Выполните docker compose ps и docker compose logs <service>; исправьте первый unhealthy-контейнер." wait_services
  run_step "Миграции применены" \
    "Проверьте DB_URL/POSTGRES_PASSWORD и логи backend, затем повторите alembic upgrade head." apply_migrations
  run_step "Две группы посеяны идемпотентно" \
    "Убедитесь, что postgres и backend healthy и DB_URL указывает на этот Postgres." seed_groups
}

enable_https() {
  validate_production_env || return 1
  run_step "Сертификат выпущен и HTTPS-overlay включён" \
    "Проверьте A-запись DOMAIN, внешний доступ к 80/443 и LETSENCRYPT_EMAIL." issue_certificate
  run_step "Все сервисы healthy после включения HTTPS" \
    "Проверьте docker compose с HTTPS-overlay и nginx logs." wait_services
  run_step "HTTPS health отвечает" \
    "Проверьте сертификат, DNS и порт 443." check_health_url "$(https_base_url)"
}

scenario_local() {
  prepare_environment
  start_full_stack false
  local base="$(http_base_url)"
  run_step "HTTP health отвечает" \
    "Проверьте nginx/backend logs и адрес $base/health." check_health_url "$base"
  if [[ "$FORCE_HTTPS" == true ]]; then
    enable_https
  fi
  summary
}

scenario_production() {
  FORCE_HTTPS=true
  prepare_environment
  validate_production_env || return 1
  start_full_stack false
  run_step "HTTP health до выпуска сертификата отвечает" \
    "Проверьте проброс порта 80, firewall, DNS и nginx/backend logs." check_health_url "http://${DOMAIN}"
  enable_https
  summary
}

scenario_update() {
  prepare_environment
  run_step "Код обновлён fast-forward без сноса данных" \
    "Уберите незакоммиченные конфликты и убедитесь, что origin/main доступен; volumes не удаляйте." \
    git pull --ff-only origin main
  local use_https=false
  https_configured && use_https=true
  [[ "$FORCE_HTTPS" == true ]] && use_https=false
  start_full_stack "$use_https"
  local base="$(http_base_url)"
  if [[ "$FORCE_HTTPS" == true ]]; then
    enable_https
    base="$(https_base_url)"
  elif [[ "$use_https" == true ]]; then
    base="$(https_base_url)"
  fi
  run_step "Health после обновления отвечает" \
    "Проверьте миграции и логи backend/nginx; данные остаются в postgres volume." check_health_url "$base"
  summary
}

scenario_groups() {
  prepare_environment
  run_step "Postgres и backend запущены" \
    "Проверьте DB_URL/POSTGRES_PASSWORD и логи postgres/backend." \
    docker compose up --build -d postgres redis backend
  run_step "Postgres и backend healthy" \
    "Выполните docker compose ps и docker compose logs postgres backend." wait_seed_services
  run_step "Миграции применены" \
    "Проверьте подключение backend к Postgres." apply_migrations
  run_step "Две группы посеяны идемпотентно" \
    "Проверьте доступность Postgres и права пользователя DB_URL." seed_groups
  ok "Остальные данные и volumes не изменялись"
}

scenario_health() {
  diagnostic_step "Docker и Compose готовы" \
    "Установите Docker Desktop/Engine с Compose v2 и запустите daemon." check_docker
  if ! check_docker; then
    fail "Диагностика остановлена" "Без работающего Docker нельзя проверить контейнеры. Никаких изменений не сделано."
    return 1
  fi
  diagnostic_step "Все сервисы healthy" \
    "Выполните docker compose ps и docker compose logs <service>; затем поднимите отсутствующие сервисы." check_services_once
  local base="$(http_base_url)"
  https_configured && base="$(https_base_url)"
  diagnostic_step "Health отвечает" \
    "Проверьте nginx/backend logs, CORS не влияет на curl; ожидаемый адрес: $base/health." check_health_url "$base"
  diagnostic_step "В базе есть минимум две группы" \
    "Выберите сценарий 4 — он досеет только две детерминированные группы." check_groups_url "$base"
  diagnostic_step "Telegram webhook установлен на актуальный URL" \
    "Задайте TELEGRAM_BOT_TOKEN и установите webhook на https://DOMAIN/api/telegram/webhook." check_telegram_webhook
  if certificate_exists; then
    diagnostic_step "HTTPS health отвечает" \
      "Проверьте DNS, сертификат, порт 443 и nginx logs." check_health_url "$(https_base_url)"
  else
    fail "HTTPS-сертификат не найден" "Для production выберите сценарий 2; для локального запуска HTTPS не обязателен."
    FAILURES=$((FAILURES + 1))
  fi
  summary
  if ((FAILURES > 0)); then
    fail "Проверка завершена: проблем — $FAILURES" "Исправьте пункты выше и повторите сценарий 5."
    return 1
  fi
  ok "Проверка здоровья завершена без ошибок"
}

load_env
printf 'Текущее состояние:\n'
print_state

if [[ -z "$SCENARIO" ]]; then
  cat <<'EOF'

Выберите сценарий:
1) с нуля локально
2) прод-HTTPS с нуля
3) обновить код без сноса данных
4) только досеять группы
5) проверка здоровья (безопасный вариант по Enter)
EOF
  read -r -p '> ' SCENARIO
  SCENARIO="${SCENARIO:-5}"
fi

case "$SCENARIO" in
  1) scenario_local ;;
  2) scenario_production ;;
  3) scenario_update ;;
  4) scenario_groups ;;
  5) scenario_health ;;
  *)
    fail "Неизвестный сценарий: $SCENARIO" "Введите число от 1 до 5."
    exit 2
    ;;
esac

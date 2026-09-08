#!/bin/sh

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(dirname "$SCRIPT_DIR")
cd "$PROJECT_ROOT"

MODE=local

usage() {
  printf '%s\n' \
    'Использование: scripts/local-up.sh [--prod]' \
    '  без флага  — локальный HTTP-запуск' \
    '  --prod     — production-запуск с HTTPS-overlay'
}

step() { printf '\n[%s] %s\n' "$1" "$2"; }
ok() { printf '✓ %s\n' "$1"; }
warn() { printf '⚠ %s\n' "$1" >&2; }

die() {
  printf '✗ %s\nЧто делать дальше: %s\n' "$1" "$2" >&2
  exit 1
}

case "${1:-}" in
  '') ;;
  --prod) MODE=prod ;;
  -h|--help) usage; exit 0 ;;
  *) usage >&2; die "Неизвестный аргумент: $1" "Запустите без аргументов или с --prod." ;;
esac

[ "$#" -le 1 ] || die "Передано слишком много аргументов" "Запустите без аргументов или только с --prod."

compose() {
  if [ "$MODE" = prod ]; then
    docker compose -f docker-compose.yml -f scripts/deploy/docker-compose.https.yml "$@"
  else
    docker compose "$@"
  fi
}

env_value() {
  key=$1
  value=$(awk -v wanted="$key" '
    /^[[:space:]]*#/ { next }
    index($0, wanted "=") == 1 { result = substr($0, length(wanted) + 2) }
    END { print result }
  ' .env | tr -d '\r')
  case "$value" in
    \"*\") value=${value#\"}; value=${value%\"} ;;
    \'*\') value=${value#\'}; value=${value%\'} ;;
  esac
  printf '%s' "$value"
}

env_or_default() {
  value=$(env_value "$1")
  if [ -n "$value" ]; then
    printf '%s' "$value"
  else
    printf '%s' "$2"
  fi
}

validate_port_number() {
  case "$1" in
    ''|*[!0-9]*) die "Некорректный порт для $2" "Укажите в .env целое число от 1 до 65535." ;;
  esac
  [ "$1" -ge 1 ] && [ "$1" -le 65535 ] ||
    die "Порт $1 для $2 вне допустимого диапазона" "Укажите в .env порт от 1 до 65535."
}

container_names_for_project() {
  compose ps --format '{{.Name}}' 2>/dev/null || true
}

published_containers() {
  docker ps --filter "publish=$1" --format '{{.Names}} {{.Ports}}' 2>/dev/null || true
}

check_port() {
  port=$1
  label=$2
  published=$(published_containers "$port")

  if [ -n "$published" ]; then
    own_names=$(container_names_for_project)
    foreign=''
    old_ifs=$IFS
    IFS='
'
    for line in $published; do
      name=${line%% *}
      if ! printf '%s\n' "$own_names" | grep -Fqx "$name"; then
        foreign="${foreign}${line}\n"
      fi
    done
    IFS=$old_ifs

    if [ -z "$foreign" ]; then
      printf '  Порт %s (%s) занят текущим compose-проектом и будет освобождён на шаге down:\n%s\n' \
        "$port" "$label" "$published"
      return 0
    fi

    printf '  Обнаружены контейнеры:\n%b' "$foreign" >&2
    die "Порт $port ($label) занят чужим Docker-контейнером" \
      "Остановите указанный контейнер либо измените соответствующий порт в .env."
  fi

  owner=''
  if command -v lsof >/dev/null 2>&1; then
    owner=$(lsof -nP -iTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)
  elif command -v ss >/dev/null 2>&1; then
    owner=$(ss -ltnp "sport = :$port" 2>/dev/null | awk 'NR > 1' || true)
  elif command -v netstat >/dev/null 2>&1; then
    owner=$(netstat -an 2>/dev/null | awk -v port="$port" '$0 ~ "[.:]" port "[[:space:]].*LISTEN"' || true)
  else
    warn "Не найдены lsof, ss или netstat: порт $port нельзя проверить надёжно."
  fi

  if [ -n "$owner" ]; then
    printf '  Владелец порта:\n%s\n' "$owner" >&2
    die "Порт $port ($label) занят" \
      "Остановите указанный процесс либо измените соответствующий порт в .env."
  fi

  ok "Порт $port ($label) свободен"
}

step '1/8' 'Обновление кода'
if ! command -v git >/dev/null 2>&1; then
  warn "Git не установлен — продолжаю с текущей копией кода. Что делать дальше: установите Git и обновите репозиторий вручную."
elif [ ! -d .git ]; then
  warn "Каталог не является Git-репозиторием — продолжаю без pull. Что делать дальше: проверьте, что запущен скрипт из клона проекта."
elif git pull --ff-only; then
  ok 'Код обновлён fast-forward'
else
  warn "git pull не выполнен — продолжаю с текущим кодом. Что делать дальше: проверьте сеть, ветку и незакоммиченные изменения."
fi

step '2/8' 'Проверка .env и обязательных настроек'
if [ ! -f .env ]; then
  [ -f .env.example ] || die '.env и .env.example отсутствуют' 'Верните .env.example или создайте .env вручную.'
  cp .env.example .env
  printf '%s\n' \
    '✓ Создан .env из .env.example; существующие файлы не перезаписывались.' \
    '✗ Запуск намеренно остановлен: секреты нельзя генерировать или подставлять молча.' \
    'Что делать дальше: заполните POSTGRES_PASSWORD, тот же пароль внутри DB_URL и JWT_SECRET длиной не менее 32 символов, затем запустите скрипт повторно.' >&2
  exit 2
fi
ok '.env найден и не будет перезаписан'

POSTGRES_PASSWORD_VALUE=$(env_value POSTGRES_PASSWORD)
DB_URL_VALUE=$(env_value DB_URL)
JWT_SECRET_VALUE=$(env_value JWT_SECRET)
VITE_API_BASE_URL_VALUE=$(env_value VITE_API_BASE_URL)

[ -n "$POSTGRES_PASSWORD_VALUE" ] && [ "$POSTGRES_PASSWORD_VALUE" != change-me ] ||
  die 'POSTGRES_PASSWORD не заполнен' 'Замените change-me в .env и укажите тот же пароль внутри DB_URL.'
[ -n "$DB_URL_VALUE" ] || die 'DB_URL не заполнен' 'Укажите строку подключения PostgreSQL в .env.'
case "$DB_URL_VALUE" in
  *change-me*) die 'DB_URL содержит плейсхолдер' 'Укажите в DB_URL тот же реальный пароль, что и в POSTGRES_PASSWORD.' ;;
esac
[ -n "$JWT_SECRET_VALUE" ] && [ "$JWT_SECRET_VALUE" != change-me ] && [ "${#JWT_SECRET_VALUE}" -ge 32 ] ||
  die 'JWT_SECRET отсутствует или короче 32 символов' 'Впишите собственный секрет длиной не менее 32 символов; значение не выводите и не коммитьте.'
[ -n "$VITE_API_BASE_URL_VALUE" ] || die 'VITE_API_BASE_URL не заполнен' 'Укажите адрес API с обязательным суффиксом /api.'
case "$VITE_API_BASE_URL_VALUE" in
  */api) ;;
  *) die 'VITE_API_BASE_URL не оканчивается на /api' 'Исправьте адрес в .env, например http://localhost/api или https://domain.example/api.' ;;
esac

DOMAIN_VALUE=$(env_value DOMAIN)
if [ "$MODE" = prod ]; then
  case "$DOMAIN_VALUE" in
    ''|localhost|queue.example.edu|*://*|*' '*)
      die 'DOMAIN не является рабочим FQDN' 'Укажите в .env реальный домен без схемы, например queue.emka.lol.'
      ;;
    *.*) ;;
    *) die 'DOMAIN должен содержать точку' 'Укажите FQDN без https://, например queue.emka.lol.' ;;
  esac
  case "$VITE_API_BASE_URL_VALUE" in
    https://*/api) ;;
    *) die 'Production VITE_API_BASE_URL должен использовать HTTPS и /api' 'Укажите https://<DOMAIN>/api и пересоберите frontend.' ;;
  esac
fi
ok "Конфигурация режима $MODE прошла preflight; значения секретов не выводились"

step '3/8' 'Проверка Docker и портов'
command -v docker >/dev/null 2>&1 || die 'Docker не найден' 'Установите Docker Desktop или Docker Engine и повторите запуск.'
docker compose version >/dev/null 2>&1 || die 'Docker Compose v2 недоступен' 'Установите Compose plugin и проверьте команду docker compose version.'
docker info >/dev/null 2>&1 || die 'Docker daemon не отвечает' 'Запустите Docker Desktop/daemon и дождитесь его готовности.'

HTTP_PORT=$(env_or_default NGINX_HTTP_PORT 80)
BACKEND_PORT_VALUE=$(env_or_default BACKEND_PORT 8000)
FRONTEND_PORT_VALUE=$(env_or_default FRONTEND_PORT 5173)
HTTPS_PORT=$(env_or_default NGINX_HTTPS_PORT 443)

validate_port_number "$HTTP_PORT" NGINX_HTTP_PORT
validate_port_number "$BACKEND_PORT_VALUE" BACKEND_PORT
validate_port_number "$FRONTEND_PORT_VALUE" FRONTEND_PORT
[ "$MODE" = local ] || validate_port_number "$HTTPS_PORT" NGINX_HTTPS_PORT

seen_ports=' '
for port_spec in "$HTTP_PORT:NGINX_HTTP_PORT" "$BACKEND_PORT_VALUE:BACKEND_PORT" "$FRONTEND_PORT_VALUE:FRONTEND_PORT"; do
  port=${port_spec%%:*}
  label=${port_spec#*:}
  case "$seen_ports" in
    *" $port "*) continue ;;
  esac
  check_port "$port" "$label"
  seen_ports="$seen_ports$port "
done
if [ "$MODE" = prod ]; then
  case "$seen_ports" in
    *" $HTTPS_PORT "*) ;;
    *) check_port "$HTTPS_PORT" NGINX_HTTPS_PORT ;;
  esac
fi

step '4/8' 'Остановка прежних контейнеров без удаления данных'
if compose down --remove-orphans; then
  ok 'Контейнеры остановлены; volumes не удалялись'
else
  die 'docker compose down завершился ошибкой' 'Проверьте docker compose ps и права Docker; не используйте down -v.'
fi

step '5/8' 'Сборка и запуск контейнеров'
if compose up --build -d; then
  ok 'Контейнеры собраны и запущены в фоне'
else
  die 'docker compose up завершился ошибкой' 'Посмотрите docker compose logs, исправьте первую ошибку сборки/запуска и повторите скрипт.'
fi

if [ "$MODE" = prod ]; then
  if [ "$HTTPS_PORT" = 443 ]; then
    BASE_URL="https://$DOMAIN_VALUE"
  else
    BASE_URL="https://$DOMAIN_VALUE:$HTTPS_PORT"
  fi
else
  if [ "$HTTP_PORT" = 80 ]; then
    BASE_URL='http://localhost'
  else
    BASE_URL="http://localhost:$HTTP_PORT"
  fi
fi
HEALTH_URL="$BASE_URL/health"

step '6/8' "Ожидание health не более 90 секунд: $HEALTH_URL"
command -v curl >/dev/null 2>&1 || die 'curl не найден' 'Установите curl и повторите запуск для проверки /health.'
deadline=$(( $(date +%s) + 90 ))
healthy=false
while [ "$(date +%s)" -le "$deadline" ]; do
  response=$(curl --fail --silent --show-error --max-time 5 "$HEALTH_URL" 2>/dev/null || true)
  if printf '%s' "$response" | grep -Eq '"status"[[:space:]]*:[[:space:]]*"ok"'; then
    healthy=true
    break
  fi
  sleep 3
done

if [ "$healthy" != true ]; then
  printf '%s\n' 'Последние логи backend:' >&2
  compose logs --tail=80 backend >&2 || true
  die 'Health не стал успешным за 90 секунд' \
    "Исправьте первую ошибку в логах backend, проверьте PostgreSQL/Redis и повторите: curl $HEALTH_URL"
fi
ok 'Health вернул status=ok'

step '7/8' 'Контрольное применение миграций'
if compose exec -T backend alembic -c /workspace/backend/alembic.ini upgrade head; then
  ok 'Alembic находится на head; повторный прогон безопасен'
else
  printf '%s\n' 'Последние логи backend:' >&2
  compose logs --tail=80 backend >&2 || true
  die 'Контрольный прогон миграций завершился ошибкой' 'Проверьте DB_URL, пароль PostgreSQL и состояние backend, затем повторите скрипт.'
fi

step '8/8' 'Итоговое состояние'
compose ps
printf '\nГотовые URL:\n  Frontend: %s/\n  API:      %s/api\n  Health:   %s/health\n' \
  "$BASE_URL" "$BASE_URL" "$BASE_URL"
ok "Docker-окружение запущено в режиме $MODE"


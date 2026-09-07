#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(dirname "$(dirname "$SCRIPT_DIR")")
cd "$PROJECT_ROOT"

if [ -f .env ]; then
  set -a
  . ./.env
  set +a
fi

: "${DOMAIN:?Укажите DOMAIN в .env}"
: "${LETSENCRYPT_EMAIL:?Укажите LETSENCRYPT_EMAIL в .env}"

docker compose up -d nginx
docker compose run --rm --entrypoint certbot certbot certonly \
  --webroot --webroot-path /var/www/certbot \
  --domain "$DOMAIN" --email "$LETSENCRYPT_EMAIL" \
  --agree-tos --no-eff-email --non-interactive
docker compose -f docker-compose.yml -f scripts/deploy/docker-compose.https.yml \
  up -d --force-recreate nginx

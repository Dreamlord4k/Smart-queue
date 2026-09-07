#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(dirname "$(dirname "$SCRIPT_DIR")")
cd "$PROJECT_ROOT"

docker compose run --rm --entrypoint certbot certbot renew \
  --webroot --webroot-path /var/www/certbot --quiet
docker compose -f docker-compose.yml -f scripts/deploy/docker-compose.https.yml \
  exec nginx nginx -s reload

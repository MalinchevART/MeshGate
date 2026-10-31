#!/usr/bin/env bash
# Restore на backup в ТЕКУЩАТА (нова/чиста) инсталация.
# Употреба: bash deploy/restore.sh <файл.dump>
# Стекът трябва да е вдигнат поне на ниво postgres: docker compose up -d postgres
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT/deploy"
FILE="${1:?укажи .dump файл}"

[ -f "$FILE" ] || { echo "Няма файл: $FILE"; exit 1; }

# спираме api (да не пише по време на restore), вдигаме чист postgres ако не е вдигнат
docker compose stop api web 2>/dev/null || true
docker compose up -d postgres
sleep 3

docker compose exec -T postgres pg_restore --clean --if-exists -U "${POSTGRES_USER:-meshgate}" \
  -d "${POSTGRES_DB:-meshgate}" < "$FILE"

docker compose up -d
echo "✔ Restore готов. Провери историята в Packet Explorer (данните трябва да са налице)."

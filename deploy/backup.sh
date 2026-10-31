#!/usr/bin/env bash
# Backup: pg_dump (custom format) + копие на compose конфигурацията.
# Употреба: bash deploy/backup.sh [изходна_папка]  (по подразбиране deploy/backups/)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT/deploy"
OUT="${1:-backups}"
STAMP="$(date +%Y%m%d-%H%M%S)"
mkdir -p "$OUT"

docker compose exec -T postgres pg_dump -Fc -U "${POSTGRES_USER:-meshgate}" "${POSTGRES_DB:-meshgate}" \
  > "$OUT/meshgate-$STAMP.dump" < /dev/null
cp .env "$OUT/meshgate-$STAMP.env" 2>/dev/null || true
cp docker-compose.yml "$OUT/meshgate-$STAMP-compose.yml"

echo "✔ Backup: $OUT/meshgate-$STAMP.dump (+ env/compose копия)"

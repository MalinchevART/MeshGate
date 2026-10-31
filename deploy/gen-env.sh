#!/usr/bin/env bash
# Генерира deploy/.env със случайни тайни (еднократно; .env не се комитва).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

if [ -f .env ]; then echo "deploy/.env вече съществува — не презаписвам."; exit 0; fi

rand() { openssl rand -hex "${1:-24}"; }

# Начална парола по подразбиране за първо влизане (синхронизирана с
# app/security.py DEFAULT_ADMIN_PASSWORD). Системата показва банер + меню за смяна.
ADMIN_PASS='P@sswordG@te'
cat > .env <<EOF
# Генерирано от gen-env.sh на $(date +%Y-%m-%d). НЕ СЕ КОМИТВА.
POSTGRES_USER=meshgate
POSTGRES_PASSWORD=$(rand 18)
POSTGRES_DB=meshgate

MESHGATE_SECRET_KEY=$(rand 32)
MESHGATE_ADMIN_USER=admin
MESHGATE_ADMIN_PASSWORD=${ADMIN_PASS}

EMQX_DASHBOARD_PASSWORD=$(rand 16)
EMQX_INGEST_USER=meshgate-ingest
EMQX_INGEST_PASSWORD=$(rand 18)

MESHGATE_EMULATOR_USER=meshgate-emulator
MESHGATE_EMULATOR_PASSWORD=$(rand 18)
EMULATOR_NODES=6
EMULATOR_INTERVAL=5

RETENTION_PACKETS_RAW=14
RETENTION_EVENTS=365
EOF
chmod 600 .env
echo "✔ Създаден deploy/.env"
echo "  Администратор в UI:  admin / ${ADMIN_PASS}"
echo "  (запиши си паролата; тя е и в .env под MESHGATE_ADMIN_PASSWORD)"

#!/usr/bin/env bash
# End-to-End приемъчни тестове на MeshGate (checklist от docs/04-mvp-scope.md).
# Пуска се от корена на репото:  bash deploy/e2e.sh
# Покрива: §1 чиста инсталация, §4 оцеляване след рестарт, §9 backup/restore.
# §2,3,5,6,7,8,10 се пускат вътрешно като pytest интеграционни тестове.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT/deploy"

export PATH="$PATH:/c/Program Files/Docker/Docker/resources/bin"

declare -A RESULT
ok()   { RESULT[$1]="PASS ✔"; echo "  ✔ $1: $2"; }
fail() { RESULT[$1]="FAIL ✘"; echo "  ✘ $1: $2"; }

# .env тайни
set -a; source ./.env 2>/dev/null; set +a
ADMIN_USER="${MESHGATE_ADMIN_USER:-admin}"
ADMIN_PASS="${MESHGATE_ADMIN_PASSWORD:-admin}"
BASE="http://localhost/api"
JAR="$(mktemp)"

# Docker двигател трябва да е жив преди каквото и да е
if ! docker info >/dev/null 2>&1; then
  echo "✘ Docker двигателът не отговаря. Стартирай Docker Desktop и изчакай ~30 s."
  exit 1
fi

api_login() {
  curl -s -c "$JAR" -X POST "$BASE/v1/auth/login" \
    -H 'Content-Type: application/json' \
    -d "{\"username\":\"$ADMIN_USER\",\"password\":\"$ADMIN_PASS\"}" >/dev/null
}

wait_healthy() {
  for i in $(seq 1 60); do
    status=$(curl -s -m 3 "$BASE/v1/system/health" 2>/dev/null | python -c "import sys,json;print(json.load(sys.stdin).get('data',{}).get('status',''))" 2>/dev/null)
    if [ "$status" = "ok" ] || [ "$status" = "degraded" ]; then return 0; fi
    sleep 5
  done
  return 1
}

echo "=== §1: чиста инсталация през Docker Compose ==="
docker compose down -v --remove-orphans >/dev/null 2>&1
if docker compose up -d --build --wait >/tmp/meshgate-e2e-build.log 2>&1 && wait_healthy; then
  ok "1-clean-install" "стекът е вдигнат и здрав от нулата"
else
  fail "1-clean-install" "вж. /tmp/meshgate-e2e-build.log"
  tail -20 /tmp/meshgate-e2e-build.log
fi

echo "=== Модулни + интеграционни тестове (§2,3,5,6,7,8,10) ==="
docker compose --profile test up -d remote-broker >/dev/null 2>&1
sleep 2
if docker compose exec -T api python -m pytest tests/unit -q 2>&1 | tail -3; then
  ok "unit-tests" "модулните тестове минават"
else
  fail "unit-tests" "модулните тестове грешат"
fi
if docker compose exec -T api python -m pytest tests/integration -q 2>&1 | tee /tmp/meshgate-e2e-int.log | tail -3; then
  ok "2,3,5,6,7,8,10-integration" "интеграционните тестове минават"
else
  fail "2,3,5,6,7,8,10-integration" "вж. /tmp/meshgate-e2e-int.log"
fi

echo "=== §4: данните оцеляват рестарт на стека ==="
api_login
CRED=$(curl -s -b "$JAR" -X POST "$BASE/v1/broker/credentials" \
  -H 'Content-Type: application/json' -d '{"username":"e2e-restart-dev","topics":["mesh/e2e/#"]}')
DEV_USER=$(echo "$CRED" | python -c "import sys,json;print(json.load(sys.stdin)['data']['username'])")
DEV_PASS=$(echo "$CRED" | python -c "import sys,json;print(json.load(sys.stdin)['data']['password'])")
MARKER="restart-$(date +%s)"
count_packets() {
  curl -s -b "$JAR" "$BASE/v1/packets?topic=mesh/e2e/$MARKER" \
    | python -c "import sys,json;print(len(json.load(sys.stdin).get('data',[])))" 2>/dev/null || echo 0
}
docker run --rm --network meshgate_meshnet eclipse-mosquitto:2.0.20 \
  mosquitto_pub -h emqx -p 1883 -u "$DEV_USER" -P "$DEV_PASS" \
  -t "mesh/e2e/$MARKER" -m "{\"marker\":\"$MARKER\"}"
sleep 2
FOUND_BEFORE=$(count_packets)
docker compose restart >/dev/null 2>&1
if wait_healthy && [ "$FOUND_BEFORE" -ge 1 ]; then
  FOUND_AFTER=$(count_packets)
  if [ "$FOUND_AFTER" -ge 1 ]; then
    ok "4-restart-persistence" "пакетът на тема mesh/e2e/$MARKER оцеля рестарта"
  else
    fail "4-restart-persistence" "маркерът изчезна след рестарт"
  fi
else
  fail "4-restart-persistence" "няма здраве след рестарт или маркерът не се записа"
fi

echo "=== §9: backup -> restore в нова инсталация ==="
bash backup.sh /tmp/meshgate-e2e-backup >/dev/null 2>&1
DUMP=$(ls -t /tmp/meshgate-e2e-backup/*.dump 2>/dev/null | head -1)
if [ -z "$DUMP" ]; then
  fail "9-backup-restore" "backup файлът не се създаде"
else
  docker compose down -v --remove-orphans >/dev/null 2>&1
  docker compose up -d postgres >/dev/null 2>&1
  # чистата база има нужда от initdb време преди restore
  for i in $(seq 1 30); do
    docker compose exec -T postgres pg_isready -U "${POSTGRES_USER:-meshgate}" >/dev/null 2>&1 && break
    sleep 2
  done
  # restore с --clean върху празна схема, после целият стек
  if docker compose exec -T postgres pg_restore --clean --if-exists -U "${POSTGRES_USER:-meshgate}" \
      -d "${POSTGRES_DB:-meshgate}" < "$DUMP" >/dev/null 2>&1 \
     && docker compose up -d --wait >/dev/null 2>&1 && wait_healthy; then
    api_login
    FOUND=$(curl -s -b "$JAR" "$BASE/v1/packets?topic=mesh/e2e/$MARKER" \
      | python -c "import sys,json;print(len(json.load(sys.stdin).get('data',[])))" 2>/dev/null || echo 0)
    if [ "$FOUND" -ge 1 ]; then
      ok "9-backup-restore" "данните се възстановиха в чиста инсталация ($DUMP)"
    else
      fail "9-backup-restore" "restore мина, но маркерът липсва"
    fi
  else
    fail "9-backup-restore" "restore процедурата грешка"
  fi
fi

echo
echo "================ ПРИЕМЪЧЕН CHECKLIST ================"
for key in "1-clean-install" "unit-tests" "2,3,5,6,7,8,10-integration" "4-restart-persistence" "9-backup-restore"; do
  printf "  %-32s %s\n" "$key" "${RESULT[$key]:-—}"
done
echo "====================================================="
PASS=$(printf '%s\n' "${RESULT[@]}" | grep -c PASS || true)
FAIL=$(printf '%s\n' "${RESULT[@]}" | grep -c FAIL || true)
echo "  $PASS групи минават, $FAIL грешат"
[ "$FAIL" = "0" ]

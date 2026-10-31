#!/usr/bin/env bash
# MeshGate управленско меню (стартира се през meshgate.cmd или: bash deploy/menu.sh)
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"
export PATH="$PATH:/c/Program Files/Docker/Docker/resources/bin"
BASE="http://localhost/api"
JAR="$(mktemp)"
ADMIN_USER=""

api() { # api METHOD PATH [JSON]
  local m="$1" p="$2" body="${3:-}"
  if [ -n "$body" ]; then
    curl -s -b "$JAR" -c "$JAR" -X "$m" "$BASE$p" -H 'Content-Type: application/json' -d "$body"
  else
    curl -s -b "$JAR" -c "$JAR" -X "$m" "$BASE$p"
  fi
}

stack_up() { docker compose ps --status running -q api 2>/dev/null | grep -q .; }

login() {
  [ -n "${LOGGED:-}" ] && return 0
  echo "(Нужен е администраторски вход)"
  read -rp "Потребител [admin]: " u
  u="${u:-admin}"
  read -rsp "Парола: " p; echo
  code=$(curl -s -o /dev/null -w '%{http_code}' -c "$JAR" \
    -X POST "$BASE/v1/auth/login" -H 'Content-Type: application/json' \
    -d "{\"username\":\"$u\",\"password\":\"$p\"}")
  if [ "$code" = "200" ]; then ADMIN_USER="$u"; LOGGED=1; ok "вход като $u"; return 0; fi
  echo "  [!!] Входът неуспешен ($code)."
  return 1
}

ok()  { echo "  [OK] $1"; }
bad() { echo "  [!!] $1"; }
pause_k() { read -rp "Enter за менюто…" _; }

change_admin_password() {
  login || return
  echo "Смяна на парола за: $ADMIN_USER"
  read -rsp "Текуща парола: " old; echo
  read -rsp "Нова парола (мин. 8 знака): " new; echo
  read -rsp "Нова парола повторно: " new2; echo
  [ "$new" = "$new2" ] || { bad "паролите не съвпадат"; return; }
  code=$(curl -s -o /dev/null -w '%{http_code}' -b "$JAR" \
    -X POST "$BASE/v1/auth/change-password" -H 'Content-Type: application/json' \
    -d "{\"old_password\":\"$old\",\"new_password\":\"$new\"}")
  [ "$code" = "200" ] && ok "паролата на $ADMIN_USER е сменена" || bad "грешка ($code) — вярна ли е текущата парола?"
}

create_user() {
  login || return
  read -rp "Потребителско име: " u
  read -rsp "Парола (мин. 8 знака): " p; echo
  echo "Роля: 1) viewer (само гледане)  2) operator  3) admin"
  read -rp "Избор [1]: " r
  case "${r:-1}" in 2) role=operator;; 3) role=admin;; *) role=viewer;; esac
  code=$(curl -s -o /dev/null -w '%{http_code}' -b "$JAR" \
    -X POST "$BASE/v1/users" -H 'Content-Type: application/json' \
    -d "{\"username\":\"$u\",\"password\":\"$p\",\"role\":\"$role\"}")
  [ "$code" = "201" ] && ok "създаден потребител '$u' ($role)" || bad "грешка ($code)"
}

list_users() {
  login || return
  api GET /v1/users | python -c "
import sys, json
d = json.load(sys.stdin).get('data', [])
print(f'  {\"потребител\":<20} {\"роля\":<10}')
for u in d:
    print(f'  {u[\"username\"]:<20} {u[\"role\"]:<10}')
"
}

reset_user_password() {
  login || return
  list_users
  read -rp "Потребителско име: " uname
  uid=$(api GET /v1/users | python -c "
import sys, json
for u in json.load(sys.stdin).get('data', []):
    if u['username'] == '$uname':
        print(u['id']); break
")
  [ -n "$uid" ] || { bad "няма такъв потребител"; return; }
  read -rsp "Нова парола (мин. 8 знака): " p; echo
  code=$(curl -s -o /dev/null -w '%{http_code}' -b "$JAR" \
    -X POST "$BASE/v1/users/$uid/password" -H 'Content-Type: application/json' \
    -d "{\"new_password\":\"$p\"}")
  [ "$code" = "200" ] && ok "паролата на '$uname' е сменена" || bad "грешка ($code)"
}

emulator_running() {
  docker compose --profile demo ps --status running -q emulator 2>/dev/null | grep -q .
}

toggle_emulator() {
  if emulator_running; then
    docker compose --profile demo stop emulator >/dev/null 2>&1
    ok "демо възлите са спрени"
  else
    if docker compose --profile demo up -d emulator >/dev/null 2>&1; then
      ok "демо възлите работят (mesh/emul/# — виж Packet Explorer)"
    else
      bad "емулаторът не тръгна — първо вдигни стека"
    fi
  fi
}

run_tests() {
  echo "1) Бързи тестове (модулни + интеграционни — не пипат данните)"
  echo "2) Пълен приемъчен e2e (ВНИМАНИЕ: изтрива данните и започва от нулата)"
  read -rp "Избор: [1]: " t
  case "${t:-1}" in
    2) bash e2e.sh ;;
    *)
      docker compose --profile test up -d remote-broker >/dev/null 2>&1
      docker compose exec -T api python -m pytest tests/unit -q
      docker compose exec -T api python -m pytest tests/integration -q
      ;;
  esac
}

show_status() {
  if ! stack_up; then bad "стекът не работи — пусни избор 1"; return; fi
  curl -s -m 5 "$BASE/v1/system/health" | python -m json.tool 2>/dev/null || bad "API не отговаря"
  docker compose ps --format "table {{.Service}}\t{{.Status}}" 2>/dev/null
}

restart_service() {
  echo "Услуги: api, emqx, postgres, traefik, web, emulator"
  read -rp "Коя услуга да рестартирам: " svc
  [ -n "$svc" ] || { bad "няма избрано"; return; }
  case "$svc" in
    api|emqx|postgres|traefik|web|emulator) ;;
    *) bad "няма такава услуга"; return ;;
  esac
  if docker compose restart "$svc"; then
    ok "$svc рестартиран (изчакай ~30 s за здраве при api)"
  else
    bad "рестартът не успя"
  fi
}

restore_backup() {
  if ! ls backups/*.dump >/dev/null 2>&1; then
    bad "няма backup файлове в deploy/backups/"
    return
  fi
  echo "Налични backup-и:"
  ls -t backups/*.dump | head -10
  read -rp "Кой файл (име от списъка): " f
  [ -f "$f" ] || { bad "няма такъв файл"; return; }
  read -rp "ВНИМАНИЕ: restore ще замени правилата/потребителите с данните от $f. Продължи? Напиши ДА: " c
  [ "$c" = "ДА" ] || { echo "отказано"; return; }
  bash restore.sh "$f"
}

while true; do
  echo
  echo "=============== MeshGate управление ==============="
  emu_state="спрени"; emulator_running && emu_state="работят"
  echo " Стек: $(stack_up && echo работи || echo СПРЯН) | Демо възли: $emu_state"
  echo "===================================================="
  echo "  1) Стартирай стека        2) Спри стека"
  echo "  3) Статус и здраве        4) Логове (последни редове)"
  echo "  5) Смени admin парола     6) Нов потребител"
  echo "  7) Потребители            8) Демо възли вкл/изкл"
  echo "  9) Тестове               10) Backup сега"
  echo " 11) Ресет парола (админ)  12) Отвори конзолата"
  echo " 13) Рестарт на услуга     14) Restore от backup"
  echo " 15) Комплект за пренос (zip в MeshGateProject/_transfer)"
  echo "  0) Изход"
  read -rp "Избор: " choice
  case "$choice" in
    1) docker compose up -d && ok "стекът тръгва (изчакай ~30 s за здраве)" ;;
    2) docker compose stop && ok "стекът е спрян (данните остават)" ;;
    3) show_status ;;
    4) read -rp "Услуга [api]: " svc; docker compose logs --tail 40 "${svc:-api}" ;;
    5) change_admin_password ;;
    6) create_user ;;
    7) list_users ;;
    8) toggle_emulator ;;
    9) run_tests ;;
    10) bash backup.sh ;;
    11) reset_user_password ;;
    12) cmd //c start http://localhost/ 2>/dev/null || echo "Отвори http://localhost/ ръчно" ;;
    13) restart_service ;;
    14) restore_backup ;;
    15) cmd //c make-kit.cmd 2>/dev/null || echo "Пусни deploy\\make-kit.cmd с двоен клик" ;;
    0) break ;;
    *) echo "Няма такъв избор" ;;
  esac
done

#!/usr/bin/env bash
# MeshGate инсталатор за Windows (от Git Bash или през install-meshgate.cmd).
# Проверява какво има на компютъра, ПИТА за разрешение преди инсталация,
# вдига стека, чака здраве и предлага демо възлите. Идемпотентен е.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"
export PATH="$PATH:/c/Program Files/Docker/Docker/resources/bin"
DOCKER_DESKTOP="/c/Program Files/Docker/Docker/Docker Desktop.exe"

ok()   { echo "  [OK] $1"; }
bad()  { echo "  [!!] $1"; }
ask()  { # ask "въпрос" [подразбирано Y] → 0 = да
  local def="${2:-Y}" answ
  if [ "$def" = "Y" ]; then read -rp "$1 [Y/n] " answ
  else read -rp "$1 [y/N] " answ; fi
  answ="${answ:-$def}"
  case "$answ" in [yYdD]*) return 0;; *) return 1;; esac
}

wait_engine() { # чака двигателят максимум $1 минути (по 5 s опит)
  local tries="$1" i
  for i in $(seq 1 "$tries"); do
    if docker info >/dev/null 2>&1; then return 0; fi
    sleep 5
  done
  return 1
}

install_docker() {
  if ! command -v winget >/dev/null 2>&1; then
    bad "Няма winget. Инсталирай Docker Desktop ръчно: https://www.docker.com/products/docker-desktop/"
    bad "после пусни инсталатора отново."
    exit 1
  fi
  echo "  (winget инсталира Docker Desktop; възможен е UAC прозорец — одобри го)"
  winget install --id Docker.DockerDesktop -e \
    --accept-package-agreements --accept-source-agreements --silent || {
    bad "winget не успя. Инсталирай Docker Desktop ръчно и пусни инсталатора пак."
    exit 1
  }
}

echo "============================================"
echo "   MeshGate — инсталация / обновяване"
echo "============================================"

# ---------- 1/5 Docker ----------
echo
echo "-- 1/5 Docker --"
if docker info >/dev/null 2>&1; then
  ok "Docker двигателът работи (v$(docker version --format '{{.Server.Version}}' 2>/dev/null))"
else
  if [ -f "$DOCKER_DESKTOP" ]; then
    echo "  Docker Desktop е инсталиран, но двигателът не работи — стартирам го…"
    "$DOCKER_DESKTOP" &
    echo "  Чакам двигателят да е готов (до 3 мин)…"
    if wait_engine 36; then
      ok "двигателят е готов"
    else
      echo "  Двигателят не стана готов. Възможна е ПРЕКЪСНАТА/СЧУПЕНА инсталация"
      echo "  (Docker Desktop не се стартира докрай)."
      if ask "Да преинсталирам ли Docker Desktop през winget"; then
        install_docker
        "$DOCKER_DESKTOP" &
        echo "  Чакам двигателят да е готов (до 5 мин; първи старт след преинсталация)…"
        if wait_engine 60; then ok "двигателят е готов след преинсталация"
        else
          bad "и след преинсталация двигателът не стана. Стартирай Docker Desktop"
          bad "ръчно, изчакай позеленяване и пусни инсталатора отново."
          exit 1
        fi
      else
        bad "спирам тук. Пусни Docker Desktop ръчно и стартирай инсталатора пак."
        exit 1
      fi
    fi
  else
    echo "  Docker Desktop липсва на тази машина."
    if ask "Да инсталирам ли Docker Desktop през winget (~5 мин)"; then
      install_docker
    else
      bad "без Docker стекът не може да работи. Пусни инсталатора, когато решиш."
      exit 1
    fi
    "$DOCKER_DESKTOP" &
    echo "  Чакам двигателят да е готов (до 5 мин; първи старт отнема повече)…"
    if wait_engine 60; then ok "двигателят е готов"; else
      bad "двигателят не стана готов за 5 минути. Стартирай Docker Desktop ръчно,"
      bad "изчакай да позеленее и пусни инсталатора отново."
      exit 1
    fi
  fi
fi

# ---------- 2/5 Конфигурация ----------
echo
echo "-- 2/5 Конфигурация (deploy/.env) --"
if [ -f .env ]; then
  ok ".env съществува — използваме съществуващите тайни"
else
  bash gen-env.sh
fi
set -a; source ./.env; set +a
ADMIN_USER="${MESHGATE_ADMIN_USER:-admin}"
ADMIN_PASS="${MESHGATE_ADMIN_PASSWORD:-}"

# ---------- 3/5 Изграждане и старт ----------
echo
echo "-- 3/5 Изграждане и старт на стека (първи път отнема няколко минути) --"
if docker compose up -d --build; then
  ok "стекът е стартиран"
else
  bad "стартирането не успя — прегледай грешките по-горе или: docker compose logs"
  exit 1
fi

# ---------- 4/5 Здраве ----------
echo
echo "-- 4/5 Изчакване системата да е готова --"
healthy=0
for _ in $(seq 1 60); do
  st=$(curl -s -m 3 http://localhost/api/v1/system/health 2>/dev/null \
    | python -c "import sys,json;print(json.load(sys.stdin).get('data',{}).get('status',''))" 2>/dev/null)
  if [ "$st" = "ok" ] || [ "$st" = "degraded" ]; then healthy=1; break; fi
  sleep 5
done
if [ "$healthy" = "1" ]; then ok "системата е здрава ($st)"; else
  bad "системата не стана здрава за 5 минути. Диагностика: docker compose logs api"
  exit 1
fi

# ---------- 5/5 Демо възли ----------
echo
echo "-- 5/5 Демо възли (емулатор) --"
if docker compose --profile demo ps --status running -q emulator 2>/dev/null | grep -q .; then
  ok "емулаторът вече работи"
elif ask "Да пусна ли демо възлите (тестов трафик в mesh/emul/#)"; then
  if docker compose --profile demo up -d emulator >/dev/null 2>&1; then
    ok "емулаторът работи: ${EMULATOR_NODES:-6} възли"
  else
    echo "  [i] Емулаторът не тръгна (не е фатално) — може да го пуснеш от менюто."
  fi
else
  echo "  [i] Без демо възли. Пускат се по-късно: meshgate.cmd → избор 8."
fi

echo
echo "============================================"
echo "   ГОТОВО — MeshGate работи"
echo "============================================"
echo "  Уеб конзола : http://localhost/"
echo "  Потребител  : $ADMIN_USER"
echo "  Парола      : $ADMIN_PASS"
echo "  MQTT        : localhost:1883 (само с per-device креденшъли)"
echo
echo "  Първо нещо: смени паролата — meshgate.cmd (двоен клик) -> избор 5"
echo "  Управление/тестове/backup/комплект: meshgate.cmd"
if ask "Да отворя ли уеб конзолата сега"; then
  cmd //c start http://localhost/ 2>/dev/null || echo "Отвори ръчно http://localhost/"
fi
echo "============================================"

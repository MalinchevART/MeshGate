#!/usr/bin/env bash
# MeshGate Linux installer + continuity service (ADR-009).
# One command on a fresh Debian/Ubuntu-class machine:
#   bash deploy/install-linux.sh
# What it does:
#   1. installs Docker Engine + Compose plugin + git if missing (apt),
#   2. generates deploy/.env if missing (prints the initial admin password),
#   3. brings the stack up (docker compose up -d),
#   4. optionally installs a systemd unit (meshgate.service) so the stack
#      survives reboots — run with: sudo bash deploy/install-linux.sh --service
# Idempotent: safe to run again at any time.
set -euo pipefail
cd "$(dirname "$0")"

ok()  { echo "  [OK] $1"; }
bad() { echo "  [!!] $1"; }

echo "============================================"
echo "  MeshGate - Linux install (check / fix / run)"
echo "============================================"

# --- 1. Docker -------------------------------------------------------------
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  ok "Docker + Compose present"
else
  echo "  ... installing Docker Engine + Compose (official apt repo)"
  sudo apt-get update -y
  sudo apt-get install -y ca-certificates curl gnupg
  sudo install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | \
    sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg 2>/dev/null || true
  . /etc/os-release
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" | \
    sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
  sudo apt-get update -y
  sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  sudo systemctl enable --now docker
  ok "Docker installed"
fi

# docker group: run compose without sudo (needs re-login to take effect)
if ! id -nG "$USER" 2>/dev/null | grep -qw docker; then
  echo "  ... adding $USER to the docker group (re-login to apply)"
  sudo usermod -aG docker "$USER" || true
fi

# --- 2. .env (secrets) ------------------------------------------------------
if [ ! -f .env ]; then
  echo "  ... generating deploy/.env (initial admin password below)"
  bash gen-env.sh
else
  ok "deploy/.env present"
fi

# --- 3. stack ---------------------------------------------------------------
echo "  ... docker compose up -d"
if ! docker compose up -d; then
  bad "compose up failed - is the docker daemon running?"
  exit 1
fi

echo "  ... waiting for the api healthcheck"
for i in $(seq 1 60); do
  st=$(docker inspect --format '{{.State.Health.Status}}' meshgate-api-1 2>/dev/null || echo starting)
  [ "$st" = "healthy" ] && break
  sleep 3
done
ok "api: $st"

ADMIN_PW=$(grep -E '^MESHGATE_ADMIN_PASSWORD=' .env | cut -d= -f2- || true)
echo ""
echo "============================================================"
echo "  MeshGate is up:  http://localhost/"
echo "  Initial admin password: ${ADMIN_PW:-<see deploy/.env>}"
echo "  (the UI asks you to change it on first login)"
echo "============================================================"

# --- 4. optional systemd continuity (survives reboot) ------------------------
if [ "${1:-}" = "--service" ]; then
  echo "  ... installing systemd unit (meshgate.service)"
  sudo tee /etc/systemd/system/meshgate.service > /dev/null <<UNIT
[Unit]
Description=MeshGate stack (docker compose)
Requires=docker.service
After=docker.service network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=$(pwd)
ExecStart=/usr/bin/docker compose up -d
ExecStop=/usr/bin/docker compose down
TimeoutStartSec=300

[Install]
WantedBy=multi-user.target
UNIT
  sudo systemctl daemon-reload
  sudo systemctl enable meshgate.service
  ok "meshgate.service enabled - the stack starts on boot"
fi

echo "Done. Watchdog (optional): watch -n 60 'docker compose ps'"

#!/usr/bin/env bash
# MeshGate ONE-COMMAND bootstrap for a fresh machine (ADR-009).
#
#   curl -fsSL <raw-url>/deploy/bootstrap.sh | bash
#   -- or, after cloning:  bash deploy/bootstrap.sh
#
# Clones the repo (if run outside it), delegates to the OS installer:
#   Windows (Git Bash): install-meshgate.cmd via cmd.exe
#   Linux/macOS:        install-linux.sh (add --service for systemd)
set -euo pipefail

REPO="${MESHGATE_REPO:-https://github.com/nmalinchev-nlm/MeshGate.git}"
DIR="${MESHGATE_DIR:-$HOME/meshgate}"

# already inside the repo?  (a deploy/ directory with docker-compose.yml)
if [ -f "$(dirname "$0")/docker-compose.yml" ]; then
  echo "MeshGate bootstrap: running from an existing checkout."
  cd "$(dirname "$0")"
else
  echo "MeshGate bootstrap: cloning $REPO -> $DIR"
  command -v git >/dev/null 2>&1 || {
    echo "git is missing - install it first (https://git-scm.com)"; exit 1; }
  [ -d "$DIR" ] || git clone "$REPO" "$DIR"
  cd "$DIR"
fi

case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*)
    echo "Windows detected - handing over to install-meshgate.cmd"
    cmd //c "deploy\\install-meshgate.cmd" 2>/dev/null || cmd /c "install-meshgate.cmd"
    ;;
  *)
    echo "Linux/macOS detected - running install-linux.sh"
    bash deploy/install-linux.sh "$@"
    ;;
esac

echo ""
echo "Bootstrap done. Web UI: http://localhost/"

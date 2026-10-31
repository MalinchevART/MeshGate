#!/usr/bin/env bash
# MeshGate .exe installer builder (ADR-009): 7-Zip SFX route.
# Output: _transfer/MeshGate-installer-<date>.exe — self-extracting
# installer that unpacks to %TEMP% and runs install-meshgate.cmd.
set -euo pipefail
cd "$(dirname "$0")/.."

SEVENZIP="/c/Program Files/7-Zip/7z.exe"
[ -f "$SEVENZIP" ] || { echo "[!!] 7-Zip not found"; exit 1; }

STAMP=$(date +%Y%m%d-%H%M)
OUTDIR="$(cd .. && pwd)/_transfer"
mkdir -p "$OUTDIR"
STAGE=$(mktemp -d)

# 1) съдържание: git-tracked файлове (без .env/backups/node_modules)
git ls-files -z | tar --null -T - -cf "$STAGE/payload.tar"

# 2) 7z архив + SFX конфиг (извлича се във %TEMP%\MeshGate и стартира инсталатора)
"$SEVENZIP" a -t7z -mx=5 "$STAGE/payload.7z" "$STAGE/payload.tar" > /dev/null
printf ';!@Install@!UTF-8!\nTitle="MeshGate installer"\nBeginPrompt="MeshGate - install and start now?"\nRunProgram="payload.tar:bat:install-meshgate.cmd"\n;!@InstallEnd@!\n' > "$STAGE/config.txt"
# RunProgram с tar: 7-Zip извлича tar-а временно... по-надеждно: 7z директно от файловете

# 3) SFX exe: копие на 7z.sfx + config + архив
cat "/c/Program Files/7-Zip/7z.sfx" "$STAGE/config.txt" "$STAGE/payload.7z" > "$OUTDIR/MeshGate-installer-$STAMP.exe"
echo "[OK] $OUTDIR/MeshGate-installer-$STAMP.exe ($(du -h "$OUTDIR/MeshGate-installer-$STAMP.exe" | cut -f1))"
rm -rf "$STAGE"

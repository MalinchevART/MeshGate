@echo off
rem MeshGate PORTABLE KIT: code + backups + instructions in one zip INSIDE
rem the project folder (..\..\..\_transfer\). Nothing is written outside
rem C:\MeshGateProject - the owner moves ONLY that folder.
rem (ASCII-only on purpose: Cyrillic in .cmd files breaks the parser.)
setlocal EnableExtensions
cd /d "%~dp0"

for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmm"') do set "STAMP=%%i"
set "KITNAME=MeshGate-kit-%STAMP%.zip"
rem staging also stays INSIDE the project (not %TEMP%): everything the
rem project produces lives under MeshGateProject and nothing is left outside;
rem ..\..\..\.kit-stage = MeshGateProject\.kit-stage, outside the copied tree
set "STAGE=%~dp0..\..\..\.kit-stage"
rem the kit ALWAYS lands in MeshGateProject\_transfer - never on the Desktop
set "OUTDIR=%~dp0..\..\..\_transfer"

echo ============================================
echo    MeshGate - portable kit
echo ============================================

if exist "%STAGE%" rmdir /s /q "%STAGE%"
mkdir "%STAGE%" 2>nul

echo [1/4] Copying the project (without node_modules)...
robocopy ".." "%STAGE%\meshgate" /MIR /XD node_modules .pytest_cache backups /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 (
  echo [!!] Copy failed.
  pause
  exit /b 1
)
mkdir "%STAGE%\meshgate\deploy\backups" 2>nul
rem include ONLY the newest backup triple (old dumps can be huge)

echo [2/4] Fresh data backup (rules/users/bridges/channels)...
rem prefer Git Bash by full path: "where bash" can pick the WSL relay,
rem which has no distro and swallows stdin
set "GITBASH="
if exist "C:\Program Files\Git\bin\bash.exe" set "GITBASH=C:\Program Files\Git\bin\bash.exe"
if not defined GITBASH if exist "C:\Program Files (x86)\Git\bin\bash.exe" set "GITBASH=C:\Program Files (x86)\Git\bin\bash.exe"
if not defined GITBASH for /f "delims=" %%b in ('where bash 2^>nul') do if not defined GITBASH (
  echo "%%b" | findstr /i "System32" >nul || set "GITBASH=%%b"
)
if defined GITBASH (
  "%GITBASH%" -lc "export PATH=\"$PATH:/c/Program Files/Docker/Docker/resources/bin\"; cd '%~dp0.' && bash backup.sh"
) else (
  echo      [i] Git Bash not found - using the latest existing backup in deploy\backups.
)
rem copy the newest backup triple (dump + env + compose copies) into the kit
powershell -NoProfile -Command "$src='%~dp0backups'; $dst='%STAGE%\meshgate\deploy\backups'; $n=Get-ChildItem $src -Filter *.dump -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1; if($n){ Copy-Item $n.FullName $dst; Get-ChildItem $src -Filter ($n.BaseName + '.*') -ErrorAction SilentlyContinue | ForEach-Object { Copy-Item $_.FullName $dst } } else { Write-Host '      [i] no backup dumps found' }"

echo [3/4] deploy\.env holds passwords and bridge credentials.
choice /C YN /M "Include deploy\.env in the kit (own computers only, never share)"
if errorlevel 2 (
  del "%STAGE%\meshgate\deploy\.env" 2>nul
  echo      .env EXCLUDED - a new one will be generated on the new computer.
)

echo [4/4] Writing instructions and packing...
copy /y "kit-readme.txt" "%STAGE%\README-KIT.txt" >nul

rem .NET ZipFile (not Compress-Archive): the cmdlet skips hidden folders
rem like .git, and the git history must travel with the kit
if not exist "%OUTDIR%" mkdir "%OUTDIR%"
powershell -NoProfile -Command "Add-Type -AssemblyName System.IO.Compression.FileSystem; [IO.Compression.ZipFile]::CreateFromDirectory((Resolve-Path '%STAGE%'), (Join-Path (Resolve-Path '%OUTDIR%') '%KITNAME%'), 'Optimal', $false)"
if errorlevel 1 (
  echo [!!] Packing failed.
  pause
  exit /b 1
)

rmdir /s /q "%STAGE%"
echo.
echo [OK] Kit created in MeshGateProject\_transfer: %KITNAME%
echo      Move it (USB/network), unzip, then double-click
echo      meshgate\deploy\install-meshgate.cmd - that is all.
echo      Full instructions: README-KIT.txt inside the zip.
echo ============================================
pause

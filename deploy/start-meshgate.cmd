@echo off
rem MeshGate CONTINUOUS RUNNER (double-click me).
rem One entry point for day-to-day operation:
rem   1. checks prerequisites and installs what is missing (delegates to
rem      install-meshgate.cmd, which is idempotent),
rem   2. brings the stack up,
rem   3. opens the web UI in the default browser,
rem   4. stays open as a WATCHDOG: if a container goes down it restarts
rem      the stack (docker compose up -d) every cycle and reports health.
rem ASCII-only on purpose: Cyrillic in .cmd files breaks the parser.
setlocal EnableExtensions
cd /d "%~dp0"
title MeshGate runner

echo ============================================
echo    MeshGate - start / check / keep running
echo ============================================

rem --- 1. prerequisites (install if missing) ---
if not exist "install-meshgate.cmd" (
  echo [!!] Run me from the deploy folder of the project.
  pause
  exit /b 1
)
rem install-meshgate.cmd is idempotent: it only installs what is missing.
call install-meshgate.cmd
if errorlevel 1 (
  echo [!!] Installer reported a problem - fix it and run again.
  pause
  exit /b 1
)

rem --- 2. open the UI once the stack answers ---
timeout /t 5 /nobreak >nul
start "" http://localhost/

rem --- 3. watchdog loop: report + self-heal every 60 s ---
echo.
echo Watchdog: checking every 60 s. Press Ctrl+C to stop WATCHING
echo (the containers keep running - stopping them is via meshgate.cmd).
echo.

:watch
for /f "delims=" %%h in ('docker compose ps --format "{{.Name}} {{.State}}" 2^>nul ^| find /c "running"') do set "RUNNING=%%h"
rem 7 services: api web emulator remote-broker traefik postgres emqx
if "%RUNNING%"=="7" (
  echo [%date% %time%] OK: all 7 containers running.
) else (
  echo [%date% %time%] [!] Only %RUNNING%/7 containers running - bringing the stack up...
  docker compose up -d >nul 2>nul
  if exist "install-meshgate.cmd" rem (stack self-heals via restart policy too)
)
timeout /t 60 /nobreak >nul
goto :watch

@echo off
rem MeshGate management menu: start/stop, passwords, users, demo, tests,
rem backup/restore, per-service restart, portable kit.
rem (ASCII-only on purpose; Bulgarian menu lives in menu.sh via Git Bash.)
setlocal EnableExtensions
cd /d "%~dp0"

rem prefer Git Bash by full path: "where bash" can pick the WSL relay
set "GITBASH="
if exist "C:\Program Files\Git\bin\bash.exe" set "GITBASH=C:\Program Files\Git\bin\bash.exe"
if not defined GITBASH if exist "C:\Program Files (x86)\Git\bin\bash.exe" set "GITBASH=C:\Program Files (x86)\Git\bin\bash.exe"
if not defined GITBASH for /f "delims=" %%b in ('where bash 2^>nul') do if not defined GITBASH (
  echo "%%b" | findstr /i "System32" >nul || set "GITBASH=%%b"
)
if not defined GITBASH (
  echo [!] Git Bash not found. Install Git (https://git-scm.com/download/win)
  echo     or run MeshGate via deploy\install-meshgate.cmd first.
  pause
  exit /b 1
)
"%GITBASH%" menu.sh
pause

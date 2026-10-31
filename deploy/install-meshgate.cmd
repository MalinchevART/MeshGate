@echo off
rem MeshGate INSTALLER: checks what the computer has, ASKS PERMISSION,
rem installs what is missing and brings the stack up. Idempotent.
rem (ASCII-only on purpose: Cyrillic in .cmd files breaks the parser.
rem  Bulgarian prompts live in install-meshgate.sh via Git Bash.)
setlocal EnableExtensions
cd /d "%~dp0"

rem --- 0. Git Bash (needed by the shell part) ---
rem prefer Git Bash by full path: "where bash" can pick the WSL relay
set "GITBASH="
if exist "C:\Program Files\Git\bin\bash.exe" set "GITBASH=C:\Program Files\Git\bin\bash.exe"
if not defined GITBASH if exist "C:\Program Files (x86)\Git\bin\bash.exe" set "GITBASH=C:\Program Files (x86)\Git\bin\bash.exe"
if not defined GITBASH for /f "delims=" %%b in ('where bash 2^>nul') do if not defined GITBASH (
  echo "%%b" | findstr /i "System32" >nul || set "GITBASH=%%b"
)
if defined GITBASH goto :bash_ok
echo [!] Git Bash is missing (git).
echo     MeshGate needs it for its install and management scripts.
choice /C YN /M "Install Git now via winget"
if errorlevel 2 (
  echo Install Git manually from https://git-scm.com/download/win
  echo and run this installer again.
  pause
  exit /b 1
)
where winget >nul 2>nul
if errorlevel 1 (
  echo [!!] No winget on this machine. Install Git manually:
  echo      https://git-scm.com/download/win
  pause
  exit /b 1
)
echo ... installing Git (winget, ~1 min; a UAC prompt may appear - accept it)
winget install --id Git.Git -e --accept-source-agreements --accept-package-agreements --silent
rem the current cmd session does not see the new PATH yet - add the standard location
set "PATH=%PATH%;C:\Program Files\Git\cmd;C:\Program Files\Git\bin;C:\Program Files\Git\usr\bin"
set "GITBASH=C:\Program Files\Git\bin\bash.exe"
if not exist "%GITBASH%" (
  echo [!!] Git was installed but bash is not reachable in this session.
  echo      Close this window and run install-meshgate.cmd again.
  pause
  exit /b 1
)
:bash_ok
rem Docker CLI must be in PATH for compose's credential helper
set "PATH=%PATH%;C:\Program Files\Docker\Docker\resources\bin"
"%GITBASH%" install-meshgate.sh
pause

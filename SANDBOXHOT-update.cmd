@echo off
rem ============================================================
rem  SANDBOXHOT updater - double-click to run an update now.
rem  First run: saves the API key to .env (local only, git-ignored),
rem  registers a Windows task that runs every 4 hours, then updates.
rem  Put this file in the SANDBOXHOT folder (next to run.py).
rem  Needs the campus network or the Tongji VPN to call the models.
rem ============================================================
setlocal
cd /d "%~dp0"

rem Paste your key between = and " in your LOCAL copy only. Leave empty on GitHub.
set "SBH_KEY="

if not exist "run.py" (
  echo [X] Put this file in the SANDBOXHOT folder, next to run.py.
  goto :end
)
where git >nul 2>&1 || (echo [X] Git is not installed: https://git-scm.com/download/win & goto :end)
set "PY="
where py >nul 2>&1 && set "PY=py"
if not defined PY where python >nul 2>&1 && set "PY=python"
if not defined PY (echo [X] Python is not installed: https://www.python.org/downloads/ & goto :end)

rem 1) API key -> .env (only if .env does not exist yet)
if not exist ".env" (
  if defined SBH_KEY (
    (echo TONGJI_API_KEY=%SBH_KEY%)> ".env"
    echo [OK] API key saved to .env
  ) else (
    powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\set_key.ps1"
  )
)

rem 1b) Tongji VPN account for automatic MotionPro connection (only once, stored encrypted in .env)
findstr /b /c:"TONGJI_VPN_USER=" ".env" >nul 2>&1
if errorlevel 1 (
  echo.
  echo Save your Tongji VPN account once so updates can connect the VPN automatically.
  powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\set_vpn.ps1"
)

rem 2) Scheduled task every 4 hours (only once)
schtasks /query /tn SANDBOXHOT >nul 2>&1
if errorlevel 1 (
  powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\install_task.ps1" -Hours 4
)

rem 3) Update now
echo.
echo Updating SANDBOXHOT ... (this can take a few minutes)
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\update.ps1"
echo.
%PY% run.py budget
echo.
echo Log: %CD%\state\last_update.log
echo Site: https://baibaigao.github.io/SANDBOXHOT/  (refreshes a few minutes after the push)

:end
echo.
pause

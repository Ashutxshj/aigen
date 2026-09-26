@echo off
REM Double-click to launch the AIGen Lead Launcher.
REM Runs the local server with german's venv Python (the email-automation tool,
REM renamed on disk; its venv has openpyxl), then opens the button page.

setlocal
set "HERE=%~dp0"
set "PY=%HERE%..\german\.venv\Scripts\python.exe"

if not exist "%PY%" (
  echo Could not find Python venv at:
  echo   %PY%
  echo Make sure german\.venv exists, then run again.
  pause
  exit /b 1
)

cd /d "%HERE%"
"%PY%" server.py

echo.
echo Server stopped.
pause

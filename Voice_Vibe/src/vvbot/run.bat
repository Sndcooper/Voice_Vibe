@echo off
rem Voice Vibe Telegram bot (GPL-2.0-only fork, see UPSTREAM.md).
rem Usage: run.bat [run|set-token|pair|unpair|status]
setlocal
set "HERE=%~dp0"
set "PY=%HERE%..\..\..\venvs\telegram-bot\Scripts\python.exe"
if not exist "%PY%" (
  set "PY=%HERE%..\..\.venv\Scripts\python.exe"
)
if not exist "%PY%" (
  echo Run setup.ps1 -Bot from the repository root. See docs\SETUP.md.
  exit /b 1
)
cd /d "%HERE%..\.."
rem src\ holds both vvbot and the stdlib-only vvhub.protocol / vvhub.secrets it imports.
set "PYTHONPATH=%HERE%.."
"%PY%" -m vvbot %*

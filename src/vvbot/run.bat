@echo off
rem Voice Vibe Telegram bot (GPL-2.0-only fork, see UPSTREAM.md).
rem Usage: run.bat [run|set-token|pair|unpair|status]
setlocal
set "HERE=%~dp0"
set "PY=%HERE%..\..\..\venvs\telegram-bot\Scripts\python.exe"
if not exist "%PY%" (
  echo venvs\telegram-bot is missing. See src\vvbot\UPSTREAM.md.
  exit /b 1
)
rem src\ holds both vvbot and the stdlib-only vvhub.protocol / vvhub.secrets it imports.
set "PYTHONPATH=%HERE%.."
"%PY%" -m vvbot %*

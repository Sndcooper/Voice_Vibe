@echo off
REM Launch Voice Vibe. Keep this window open; close it or press Ctrl+C to quit.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo No virtual environment found. Run setup first:
    echo   uv venv --python 3.11
    echo   uv pip install -e ".[cuda]"
    exit /b 1
)
".venv\Scripts\python.exe" -m voicevibe %*

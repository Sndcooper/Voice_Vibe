@echo off
REM Launch Voice Vibe in the background: no console window, tray icon + orb only.
REM Pass --console as the first argument to keep a visible window for debugging.
setlocal
cd /d "%~dp0"

REM Environments and model caches live next to the repo, in ..\venvs
REM (see ..\TASK.md). The old in-repo .venv is still used if present alone.
set "VENVS=%~dp0..\venvs"
set "PY=%VENVS%\voicevibe\Scripts\python.exe"
set "PYW=%VENVS%\voicevibe\Scripts\pythonw.exe"
if not exist "%PY%" (
    set "PY=.venv\Scripts\python.exe"
    set "PYW=.venv\Scripts\pythonw.exe"
) else (
    if not defined HF_HOME set "HF_HOME=%VENVS%\hf-cache"
    if not defined UV_CACHE_DIR set "UV_CACHE_DIR=%VENVS%\uv-cache"
)

if not exist "%PY%" (
    echo No virtual environment found. Run setup first:
    echo   uv venv --python 3.11 ..\venvs\voicevibe
    echo   uv pip install --python ..\venvs\voicevibe\Scripts\python.exe -e ".[cuda,screen,wakeword]"
    exit /b 1
)

set "ARGS=%*"

REM Login autostart, off unless asked: run.bat --autostart on, off or status
if /I "%~1"=="--autostart" goto :autostart
REM The control panel window (also in the tray menu): run.bat --ui
if /I "%~1"=="--ui" goto :ui

REM `shift` does not rewrite %*, so strip the flag from the string instead.
if /I not "%~1"=="--console" goto :check_diagnostic
set "ARGS=%ARGS:~9%"
REM The hub starts hidden first if /health doesn't answer (it outlives this window).
"%PY%" -m vvhub.ui.launcher hub
"%PY%" -m voicevibe %ARGS%
exit /b %errorlevel%

:check_diagnostic
REM Diagnostic modes print to stdout, so they need a console regardless.
if "%ARGS%"=="" goto :background
echo %ARGS% | findstr /I /C:"--check" /C:"--test" /C:"--mic-test" /C:"--wake-test" /C:"--list-devices" /C:"--key-test" /C:"--say" /C:"--help" /C:"--version" /C:"--suggest-replacements" >nul
if errorlevel 1 goto :background
"%PY%" -m voicevibe %ARGS%
exit /b %errorlevel%

:background
if not exist "%PYW%" (
    echo pythonw.exe is missing from the virtual environment; running with a console.
    "%PY%" -m voicevibe %ARGS%
    exit /b %errorlevel%
)
REM Hub first (only if /health doesn't answer), then Voice Vibe, both detached
REM so they outlive this window. The old way if the launcher itself fails.
"%PY%" -m vvhub.ui.launcher start %ARGS%
if errorlevel 1 start "" "%PYW%" -m voicevibe %ARGS%
exit /b 0

:autostart
"%PY%" -m vvhub.ui.launcher autostart %2
exit /b %errorlevel%

:ui
start "" "%PYW%" -m vvhub.ui
exit /b 0

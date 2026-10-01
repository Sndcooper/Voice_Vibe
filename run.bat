@echo off
REM Launch Voice Vibe in the background: no console window, tray icon + overlay only.
REM Pass --console as the first argument to keep a visible window for debugging.
REM Diagnostics (--check, --mic-test, --test, --list-devices, --key-test, --help,
REM --version) print to this window.
setlocal
cd /d "%~dp0"
REM The shared venv also has the full Voice_Vibe editable install. Always load
REM this app's source first, including in child processes.
set "PYTHONPATH=%~dp0src;%PYTHONPATH%"

set "PY=%~dp0.venv\Scripts\python.exe"
set "PYW=%~dp0.venv\Scripts\pythonw.exe"
REM Fall back to the shared workspace venv this project was developed in.
if not exist "%PY%" (
    set "PY=%~dp0..\venvs\voicevibe\Scripts\python.exe"
    set "PYW=%~dp0..\venvs\voicevibe\Scripts\pythonw.exe"
    if not defined HF_HOME set "HF_HOME=%~dp0..\venvs\hf-cache"
)

if not exist "%PY%" (
    echo No virtual environment found. Run setup first:
    echo   powershell -ExecutionPolicy Bypass -File .\setup.ps1
    exit /b 1
)

set "ARGS=%*"

REM `shift` does not rewrite %*, so strip the flag from the string instead.
if /I not "%~1"=="--console" goto :check_diagnostic
set "ARGS=%ARGS:~9%"
"%PY%" -m voicevibe %ARGS%
exit /b %errorlevel%

:check_diagnostic
if "%ARGS%"=="" goto :background
echo %ARGS% | findstr /I /C:"--check" /C:"--test" /C:"--mic-test" /C:"--list-devices" /C:"--key-test" /C:"--help" /C:"--version" >nul
if errorlevel 1 goto :background
"%PY%" -m voicevibe %ARGS%
exit /b %errorlevel%

:background
if not exist "%PYW%" (
    echo pythonw.exe is missing from the virtual environment; running with a console.
    "%PY%" -m voicevibe %ARGS%
    exit /b %errorlevel%
)
start "" "%PYW%" -m voicevibe %ARGS%
exit /b 0

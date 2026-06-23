@echo off
setlocal enabledelayedexpansion

set SCRIPT_DIR=%~dp0
for %%i in ("%SCRIPT_DIR%..") do set REPO_ROOT=%%~fi

if not defined ECLIPSE_PYTHON set ECLIPSE_PYTHON=%REPO_ROOT%\.venv\Scripts\python.exe
if not defined ECLIPSE_WAKE_THRESHOLD set ECLIPSE_WAKE_THRESHOLD=0.5
if not defined ECLIPSE_WAKE_TIMEOUT_SECONDS set ECLIPSE_WAKE_TIMEOUT_SECONDS=
if not defined ECLIPSE_COMMAND_SECONDS set ECLIPSE_COMMAND_SECONDS=5
if not defined ECLIPSE_WHISPER_MODEL set ECLIPSE_WHISPER_MODEL=small
if not defined ECLIPSE_LANGUAGE set ECLIPSE_LANGUAGE=es
if not defined ECLIPSE_BUILTIN_WAKEWORD set ECLIPSE_BUILTIN_WAKEWORD=hey_jarvis
if not defined ECLIPSE_WAKEWORD_MODEL set ECLIPSE_WAKEWORD_MODEL=
if not defined ECLIPSE_STORE set ECLIPSE_STORE=

if not exist "%ECLIPSE_PYTHON%" (
  echo Configured Python environment is missing or not executable: %ECLIPSE_PYTHON% >&2
  echo Set ECLIPSE_PYTHON to the wake runtime Python, or run scripts\setup.bat to create %REPO_ROOT%\.venv. >&2
  exit /b 2
)

set CMD="%ECLIPSE_PYTHON%" -m eclipse_agent wake-efficient --iterations 0 --wake-threshold %ECLIPSE_WAKE_THRESHOLD% --builtin-wakeword %ECLIPSE_BUILTIN_WAKEWORD% --command-seconds %ECLIPSE_COMMAND_SECONDS% --model %ECLIPSE_WHISPER_MODEL% --language %ECLIPSE_LANGUAGE% --execute --speak --route-execute --confirmed

if not "%ECLIPSE_WAKE_TIMEOUT_SECONDS%"=="" set CMD=!CMD! --wake-timeout-seconds %ECLIPSE_WAKE_TIMEOUT_SECONDS%
if not "%ECLIPSE_WAKEWORD_MODEL%"=="" set CMD=!CMD! --wakeword-model %ECLIPSE_WAKEWORD_MODEL%
if not "%ECLIPSE_STORE%"=="" set CMD=!CMD! --store %ECLIPSE_STORE%

echo Eclipse startup: builtin wakeword fallback %ECLIPSE_BUILTIN_WAKEWORD% is active.
if not "%ECLIPSE_WAKEWORD_MODEL%"=="" (
  echo Eclipse startup: preferred custom wakeword model %ECLIPSE_WAKEWORD_MODEL% configured.
) else (
  echo Eclipse startup: no custom wakeword model configured.
)
echo PYTHONPATH=%REPO_ROOT%\src

if "%ECLIPSE_START_DRY_RUN%"=="1" (
  echo Command: !CMD!
  exit /b 0
)

cd /d "%REPO_ROOT%"
if defined PYTHONPATH (
  set PYTHONPATH=%REPO_ROOT%\src;%PYTHONPATH%
) else (
  set PYTHONPATH=%REPO_ROOT%\src
)

!CMD!

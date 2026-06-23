@echo off
setlocal enabledelayedexpansion

REM Eclipse one-command Windows setup: create a virtualenv and install the agent.

set SCRIPT_DIR=%~dp0
for %%i in ("%SCRIPT_DIR%..") do set REPO_ROOT=%%~fi
set VENV_DIR=%REPO_ROOT%\.venv
set VENV_PY=%VENV_DIR%\Scripts\python.exe

REM Pick a base Python interpreter: prefer the py launcher, fall back to python.
set BASE_PY=
where py >nul 2>&1 && set BASE_PY=py
if not defined BASE_PY where python >nul 2>&1 && set BASE_PY=python
if not defined BASE_PY (
  echo No Python found. Install Python 3.11+ and ensure 'py' or 'python' is on PATH. >&2
  exit /b 1
)

if "%ECLIPSE_SETUP_DRY_RUN%"=="1" (
  echo DRY RUN: would use base Python '%BASE_PY%'
  echo DRY RUN: %BASE_PY% -m venv "%VENV_DIR%"
  echo DRY RUN: "%VENV_PY%" -m pip install --upgrade pip
  echo DRY RUN: "%VENV_PY%" -m pip install -e "%REPO_ROOT%[voice,dev]"
  exit /b 0
)

if not exist "%VENV_PY%" (
  echo Creating virtual environment at %VENV_DIR% ...
  %BASE_PY% -m venv "%VENV_DIR%" || exit /b 1
)

echo Upgrading pip ...
"%VENV_PY%" -m pip install --upgrade pip || exit /b 1

echo Installing Eclipse (editable) with voice + dev extras ...
"%VENV_PY%" -m pip install -e "%REPO_ROOT%[voice,dev]" || exit /b 1

echo.
echo Eclipse environment ready.
echo   Check capabilities:  "%VENV_PY%" -m eclipse_agent diagnostics
echo   Start the agent:     scripts\start_eclipse.bat
echo.
echo Optional extras:
echo   Live notifications:  "%VENV_PY%" -m pip install -e "%REPO_ROOT%[notifications]"
echo   Browser automation:  npm install -g agent-browser

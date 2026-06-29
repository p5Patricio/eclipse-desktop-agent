@echo off
REM Build the standalone Eclipse executable with PyInstaller.
REM Output: dist\eclipse-agent\eclipse-agent.exe
setlocal
set SCRIPT_DIR=%~dp0
for %%i in ("%SCRIPT_DIR%..") do set REPO_ROOT=%%~fi
cd /d "%REPO_ROOT%"

if not defined ECLIPSE_PYTHON set ECLIPSE_PYTHON=%REPO_ROOT%\.venv\Scripts\python.exe
if not exist "%ECLIPSE_PYTHON%" (
  echo Python environment not found: %ECLIPSE_PYTHON% >&2
  echo Run scripts\setup.bat first, then pip install pyinstaller. >&2
  exit /b 2
)

"%ECLIPSE_PYTHON%" -m PyInstaller --noconfirm packaging\eclipse-agent.spec ^
  --distpath dist --workpath build\pyi
if errorlevel 1 exit /b 1

echo.
echo Build complete: dist\eclipse-agent\eclipse-agent.exe

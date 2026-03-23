@echo off
REM ============================================================
REM  uninstall-service.bat
REM  Stops and removes the Windows Service Manager service.
REM  Must be run as Administrator.
REM ============================================================
cd /d "%~dp0"

net session >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo ERROR: Please run as Administrator.
    pause
    exit /b 1
)

echo Stopping and removing Windows Service Manager service...
venv\Scripts\python backend\win_service.py stop
venv\Scripts\python backend\win_service.py remove

echo.
echo Service has been removed.
pause

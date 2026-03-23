@echo off
REM ============================================================
REM  uninstall-service.bat
REM  Stops and removes the Windows Service Manager service.
REM  Must be run as Administrator.
REM ============================================================
cd /d "%~dp0"

net session >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo ERROR: Bitte als Administrator ausfuehren.
    pause
    exit /b 1
)

echo Stoppe und entferne Windows Service Manager Dienst...
venv\Scripts\python backend\win_service.py stop
venv\Scripts\python backend\win_service.py remove

echo.
echo Dienst wurde entfernt.
pause

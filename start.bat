@echo off
REM ============================================================
REM  start.bat
REM  Starts the Windows Service Manager using the local venv.
REM  Run setup.bat first if venv\ does not exist yet.
REM ============================================================
cd /d "%~dp0"

if not exist venv\Scripts\python.exe (
    echo ERROR: Virtual environment not found.
    echo Please run setup.bat first.
    pause
    exit /b 1
)

echo Starting Windows Service Manager...
echo Backend: http://localhost:8080
echo Press Ctrl+C to stop.
echo.

venv\Scripts\python backend\main.py
pause

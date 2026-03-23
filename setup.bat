@echo off
REM ============================================================
REM  setup.bat
REM  Run this ONCE on the Windows Server to set up the
REM  local virtual environment from the offline wheels\ folder.
REM  No internet connection required.
REM ============================================================
cd /d "%~dp0"

echo ============================================================
echo  Windows Service Manager - Setup
echo ============================================================
echo.

REM --- Check Python ---
where python >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo ERROR: Python not found in PATH.
    echo Install Python 3.9+ from the offline installer, then re-run setup.bat.
    pause
    exit /b 1
)
python --version

REM --- Check wheels folder ---
if not exist wheels\ (
    echo ERROR: wheels\ folder not found.
    echo Run prepare_offline.bat on a machine with internet first.
    pause
    exit /b 1
)

REM --- Remove old venv if it exists ---
if exist venv\ (
    echo Removing existing venv...
    rmdir /s /q venv
)

REM --- Create virtual environment ---
echo.
echo Creating virtual environment...
python -m venv venv
if %ERRORLEVEL% neq 0 (
    echo ERROR: Failed to create virtual environment.
    pause
    exit /b 1
)

REM --- Install packages from local wheels (no internet) ---
echo.
echo Installing packages from wheels\ (offline)...
venv\Scripts\pip install --no-index --find-links=wheels -r backend\requirements.txt
if %ERRORLEVEL% neq 0 (
    echo ERROR: Package installation failed.
    pause
    exit /b 1
)

REM --- Run pywin32 post-install (registers DLLs) ---
echo.
echo Running pywin32 post-install...
venv\Scripts\python venv\Lib\site-packages\pywin32_postinstall.py -install
if %ERRORLEVEL% neq 0 (
    echo WARNING: pywin32 post-install step failed.
    echo The service may still work - check if it runs correctly.
)

REM --- Create logs folder ---
if not exist logs mkdir logs

echo.
echo ============================================================
echo  Setup complete!
echo  Run start.bat to launch the Service Manager.
echo ============================================================
pause

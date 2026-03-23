@echo off
REM ============================================================
REM  prepare_offline.bat
REM  Run this ONCE on a machine WITH internet access.
REM  Creates the wheels\ folder with all packages for offline
REM  installation on the Windows Server.
REM ============================================================
cd /d "%~dp0"

echo Checking Python...
where python >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo ERROR: Python not found in PATH.
    echo Install Python 3.9+ from https://www.python.org/downloads/
    pause
    exit /b 1
)
python --version

echo.
echo Downloading packages into wheels\ ...
if not exist wheels mkdir wheels

pip download -r backend\requirements.txt -d wheels\
if %ERRORLEVEL% neq 0 (
    echo ERROR: pip download failed.
    pause
    exit /b 1
)

echo.
echo Done. The wheels\ folder contains:
dir /b wheels\

echo.
echo ============================================================
echo  Next steps:
echo  1. Copy the entire project folder to the Windows Server
echo  2. Run setup.bat once on the server
echo  3. Run start.bat to launch the service
echo ============================================================
pause

@echo off
REM ============================================================
REM  install-service.bat
REM  Installs the Windows Service Manager as a native Windows
REM  Service. Must be run as Administrator.
REM ============================================================
cd /d "%~dp0"

net session >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo ERROR: Please run as Administrator.
    pause
    exit /b 1
)

if not exist venv\Scripts\python.exe (
    echo ERROR: Virtual environment not found.
    echo Please run setup.bat first.
    pause
    exit /b 1
)

REM Remove previous installation if present (ignore errors)
venv\Scripts\python backend\win_service.py stop >nul 2>&1
venv\Scripts\python backend\win_service.py remove >nul 2>&1

echo Installing Windows Service Manager as a Windows service...
venv\Scripts\python backend\win_service.py install
if %ERRORLEVEL% neq 0 (
    echo.
    echo ERROR: Installation failed.
    pause
    exit /b 1
)

echo.
echo Service installed successfully.
echo.
echo Next steps:
echo   - Start:     venv\Scripts\python backend\win_service.py start
echo   - Stop:      venv\Scripts\python backend\win_service.py stop
echo   - Uninstall: venv\Scripts\python backend\win_service.py remove
echo.
echo Or via Windows Services (services.msc):
echo   Service name: WindowsServiceManager
echo.
pause

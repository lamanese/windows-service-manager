@echo off
REM ============================================================
REM  install-service.bat
REM  Installs the Windows Service Manager as a native Windows
REM  Service. Must be run as Administrator.
REM ============================================================
cd /d "%~dp0"

net session >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo ERROR: Bitte als Administrator ausfuehren.
    pause
    exit /b 1
)

if not exist venv\Scripts\python.exe (
    echo ERROR: Virtual environment nicht gefunden.
    echo Bitte zuerst setup.bat ausfuehren.
    pause
    exit /b 1
)

REM Remove previous installation if present (ignore errors)
venv\Scripts\python backend\win_service.py stop >nul 2>&1
venv\Scripts\python backend\win_service.py remove >nul 2>&1

echo Installiere Windows Service Manager als Windows-Dienst...
venv\Scripts\python backend\win_service.py install
if %ERRORLEVEL% neq 0 (
    echo.
    echo FEHLER bei der Installation.
    pause
    exit /b 1
)

echo.
echo Dienst erfolgreich installiert.
echo.
echo Naechste Schritte:
echo   - Starten:       venv\Scripts\python backend\win_service.py start
echo   - Stoppen:        venv\Scripts\python backend\win_service.py stop
echo   - Deinstallieren: venv\Scripts\python backend\win_service.py remove
echo.
echo Oder ueber die Windows-Dienstverwaltung (services.msc):
echo   Dienstname: WindowsServiceManager
echo.
pause

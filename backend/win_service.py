"""
Windows Service wrapper for the Service Manager FastAPI application.

Allows installing, starting, stopping, and removing the application as a
native Windows Service using pywin32's ServiceFramework.

Usage (run as Administrator):
    python win_service.py install     Install the service
    python win_service.py start       Start the service
    python win_service.py stop        Stop the service
    python win_service.py remove      Uninstall the service
    python win_service.py restart     Restart the service
"""
from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

import servicemanager
import win32event
import win32service
import win32serviceutil

# Resolve project root (one level above backend/)
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
_BACKEND_DIR = str(Path(__file__).resolve().parent)


class ServiceManagerSvc(win32serviceutil.ServiceFramework):
    """Native Windows Service that runs the FastAPI/uvicorn server."""

    _svc_name_ = "WindowsServiceManager"
    _svc_display_name_ = "Windows Service Manager"
    _svc_description_ = (
        "Web dashboard for managing Windows services. "
        "Provides a web interface on the configured port."
    )

    # Use the python.exe that installed the service, not PythonService.exe.
    # This avoids error 1053 caused by PythonService.exe not finding the
    # script or its dependencies.
    _exe_name_ = sys.executable
    _exe_args_ = f'"{Path(__file__).resolve()}"'

    def __init__(self, args: list) -> None:
        super().__init__(args)
        self.stop_event = win32event.CreateEvent(None, 0, 0, None)
        self._server = None
        self._thread = None

    # ── Service control callbacks ────────────────────────────────────────

    def SvcStop(self) -> None:
        """Called by the SCM when the service should stop."""
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        win32event.SetEvent(self.stop_event)
        if self._server is not None:
            self._server.should_exit = True

    def SvcDoRun(self) -> None:
        """Called by the SCM to start the service."""
        # Set working directory to project root so config.yaml and
        # frontend/ are found correctly.
        os.chdir(_PROJECT_ROOT)

        # Ensure backend/ is importable
        if _BACKEND_DIR not in sys.path:
            sys.path.insert(0, _BACKEND_DIR)

        try:
            servicemanager.LogMsg(
                servicemanager.EVENTLOG_INFORMATION_TYPE,
                servicemanager.PYS_SERVICE_STARTED,
                (self._svc_name_, ""),
            )
            self._run_server()
        except Exception as exc:
            servicemanager.LogErrorMsg(f"{self._svc_name_} failed: {exc}")
            self.SvcStop()

    # ── Server logic ─────────────────────────────────────────────────────

    def _run_server(self) -> None:
        """Start uvicorn in a background thread and wait for the stop event."""
        import uvicorn

        from config import config
        from main import app

        uvi_config = uvicorn.Config(
            app,
            host=config.server.host,
            port=config.server.port,
            log_level="info",
        )
        self._server = uvicorn.Server(uvi_config)

        self._thread = threading.Thread(target=self._server.run, daemon=True)
        self._thread.start()

        # Block until the SCM signals us to stop
        win32event.WaitForSingleObject(self.stop_event, win32event.INFINITE)

        # Graceful shutdown
        self._server.should_exit = True
        self._thread.join(timeout=15)

        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STOPPED,
            (self._svc_name_, ""),
        )


if __name__ == "__main__":
    if len(sys.argv) == 1:
        # Started by the SCM — dispatch as a service
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(ServiceManagerSvc)
        servicemanager.StartServiceCtrlDispatcher()
    else:
        # CLI: install / remove / start / stop / restart
        win32serviceutil.HandleCommandLine(ServiceManagerSvc)

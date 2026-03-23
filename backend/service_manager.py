"""
Windows Service Manager module.

Wraps pywin32 to enumerate, start, stop, and restart Windows services.
On non-Windows platforms the win32 imports are skipped gracefully so that
the module can still be imported for unit testing.
"""
from __future__ import annotations

import asyncio
import time

# pywin32 is Windows-only; wrap imports so the module loads on other platforms
try:
    import win32service
    import win32con
    import pywintypes
except ImportError:  # pragma: no cover
    win32service = None  # type: ignore[assignment]
    win32con = None  # type: ignore[assignment]
    pywintypes = None  # type: ignore[assignment]



# ---------------------------------------------------------------------------
# Custom exception hierarchy
# ---------------------------------------------------------------------------


class ServiceError(Exception):
    """Base class for all service-related errors."""


class ServiceNotFoundError(ServiceError):
    """Raised when a service name is not found in the SCM."""


class ServicePermissionError(ServiceError):
    """Raised when the process lacks permission to control the service."""


class ServiceAlreadyRunningError(ServiceError):
    """Raised when start is requested for an already-running service."""


class ServiceAlreadyStoppedError(ServiceError):
    """Raised when stop is requested for an already-stopped service."""


class ServiceTimeoutError(ServiceError):
    """Raised when a state transition does not complete within the timeout."""


# ---------------------------------------------------------------------------
# Status mapping
# ---------------------------------------------------------------------------

# Maps win32service dwCurrentState integer values to API status strings.
# Constants are defined here as literals so the module works on non-Windows.
_STATUS_MAP: dict[int, str] = {
    1: "stopped",    # SERVICE_STOPPED
    2: "starting",   # SERVICE_START_PENDING
    3: "stopping",   # SERVICE_STOP_PENDING
    4: "running",    # SERVICE_RUNNING
    5: "starting",   # SERVICE_CONTINUE_PENDING
    6: "stopping",   # SERVICE_PAUSE_PENDING
    7: "stopped",    # SERVICE_PAUSED
}

_STARTUP_TYPE_MAP: dict[int, str] = {
    0: "Boot",
    1: "System",
    2: "Automatic",
    3: "Manual",
    4: "Disabled",
}


def _map_status(dw_current_state: int) -> str:
    return _STATUS_MAP.get(dw_current_state, "unknown")


def _map_win_error(exc: Exception, service_name: str) -> ServiceError:
    """
    Convert a pywintypes.error into a domain-specific ServiceError.

    Args:
        exc: The pywintypes.error exception instance.
        service_name: Name of the service being operated on.

    Returns:
        A ServiceError subclass with a descriptive message.
    """
    winerror = exc.args[0] if exc.args else 0
    if winerror == 5:  # ERROR_ACCESS_DENIED
        return ServicePermissionError(
            f"Insufficient privileges to control service '{service_name}'"
        )
    if winerror == 1060:  # ERROR_SERVICE_DOES_NOT_EXIST
        return ServiceNotFoundError(f"Service '{service_name}' does not exist")
    if winerror == 1056:  # ERROR_SERVICE_ALREADY_RUNNING
        return ServiceAlreadyRunningError(
            f"Service '{service_name}' is already running"
        )
    if winerror == 1062:  # ERROR_SERVICE_NOT_ACTIVE
        return ServiceAlreadyStoppedError(
            f"Service '{service_name}' is already stopped"
        )
    if winerror == 1053:  # ERROR_SERVICE_REQUEST_TIMEOUT
        return ServiceTimeoutError(
            f"Service '{service_name}' did not respond within the timeout"
        )
    return ServiceError(
        f"Windows error {winerror} while controlling service '{service_name}': {exc}"
    )


# ---------------------------------------------------------------------------
# ServiceManager class
# ---------------------------------------------------------------------------


class ServiceManager:
    """
    Synchronous wrapper around pywin32 for Windows service management.

    All methods are synchronous and blocking. Callers in an async context
    should wrap them with ``asyncio.to_thread()``.

    Uses explicit try/finally blocks for all SCM and service handles to
    prevent handle leaks, as required by the Windows SCM contract.
    """

    def __init__(self, timeout_seconds: int = 30, poll_interval_ms: int = 500) -> None:
        """
        Initialize ServiceManager with state-transition settings.

        Args:
            timeout_seconds: Maximum seconds to wait for a service to
                             reach its target state after a command.
            poll_interval_ms: Milliseconds between status polls.
        """
        self.timeout_seconds = timeout_seconds
        self.poll_interval_ms = poll_interval_ms

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_services(self) -> list[dict]:
        """
        Enumerate all Win32 services (running and stopped).

        Returns:
            List of dicts with keys: name, display_name, status, pid,
            startup_type, logon_as.
            pid is None when the service is not running.

        Raises:
            ServiceError: On SCM connection or enumeration failure.
            ServicePermissionError: When access is denied.
        """
        if win32service is None:
            raise ServiceError("pywin32 is not available on this platform")

        scm_handle = win32service.OpenSCManager(
            None,
            None,
            win32service.SC_MANAGER_CONNECT | win32service.SC_MANAGER_ENUMERATE_SERVICE,
        )
        try:
            services_raw = win32service.EnumServicesStatus(
                scm_handle,
                win32service.SERVICE_WIN32,
                win32service.SERVICE_STATE_ALL,
            )
        finally:
            win32service.CloseServiceHandle(scm_handle)

        result = []
        for svc in services_raw:
            name = svc[0]
            display_name = svc[1]
            status_tuple = svc[2]
            dw_current_state = status_tuple[1]
            pid = status_tuple[2] if dw_current_state == 4 else None
            svc_cfg = self._get_service_config(name)
            result.append(
                {
                    "name": name,
                    "display_name": display_name,
                    "status": _map_status(dw_current_state),
                    "pid": pid,
                    "startup_type": svc_cfg["startup_type"],
                    "logon_as": svc_cfg["logon_as"],
                }
            )

        return result

    def start_service(self, name: str) -> None:
        """
        Start a stopped Windows service and wait for it to reach 'running'.

        Args:
            name: The Windows service internal SCM name.

        Raises:
            ServiceNotFoundError: Service does not exist.
            ServicePermissionError: Insufficient OS privileges.
            ServiceAlreadyRunningError: Service is already running.
            ServiceTimeoutError: Service did not start within timeout.
            ServiceError: Any other Windows API error.
        """
        if win32service is None:
            raise ServiceError("pywin32 is not available on this platform")

        try:
            scm_handle = win32service.OpenSCManager(
                None,
                None,
                win32service.SC_MANAGER_CONNECT,
            )
            try:
                svc_handle = win32service.OpenService(
                    scm_handle,
                    name,
                    win32service.SERVICE_START | win32service.SERVICE_QUERY_STATUS,
                )
                try:
                    win32service.StartService(svc_handle, None)
                finally:
                    win32service.CloseServiceHandle(svc_handle)
            finally:
                win32service.CloseServiceHandle(scm_handle)
        except pywintypes.error as exc:
            raise _map_win_error(exc, name) from exc

        self._wait_for_state(name, target_state=4)  # SERVICE_RUNNING = 4

    def stop_service(self, name: str) -> None:
        """
        Stop a running Windows service and wait for it to reach 'stopped'.

        Args:
            name: The Windows service internal SCM name.

        Raises:
            ServiceNotFoundError: Service does not exist.
            ServicePermissionError: Insufficient OS privileges.
            ServiceAlreadyStoppedError: Service is already stopped.
            ServiceTimeoutError: Service did not stop within timeout.
            ServiceError: Any other Windows API error.
        """
        if win32service is None:
            raise ServiceError("pywin32 is not available on this platform")

        try:
            scm_handle = win32service.OpenSCManager(
                None,
                None,
                win32service.SC_MANAGER_CONNECT,
            )
            try:
                svc_handle = win32service.OpenService(
                    scm_handle,
                    name,
                    win32service.SERVICE_STOP | win32service.SERVICE_QUERY_STATUS,
                )
                try:
                    win32service.ControlService(
                        svc_handle, win32service.SERVICE_CONTROL_STOP
                    )
                finally:
                    win32service.CloseServiceHandle(svc_handle)
            finally:
                win32service.CloseServiceHandle(scm_handle)
        except pywintypes.error as exc:
            raise _map_win_error(exc, name) from exc

        self._wait_for_state(name, target_state=1)  # SERVICE_STOPPED = 1

    def restart_service(self, name: str) -> None:
        """
        Restart a Windows service.

        If the service is running, it is stopped first, then started.
        If the service is already stopped, it is simply started.

        Args:
            name: The Windows service internal SCM name.

        Raises:
            ServiceNotFoundError: Service does not exist.
            ServicePermissionError: Insufficient OS privileges.
            ServiceTimeoutError: Service did not reach target state within timeout.
            ServiceError: Any other Windows API error.
        """
        try:
            self.stop_service(name)
        except ServiceAlreadyStoppedError:
            pass  # Already stopped – proceed to start

        self.start_service(name)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_service_config(self, name: str) -> dict:
        """
        Query service configuration (startup type, logon account) from SCM.

        Returns dict with startup_type and logon_as keys.
        Returns None values for both on any error (non-Windows, permission, etc.).
        """
        if win32service is None:
            return {"startup_type": None, "logon_as": None}
        try:
            scm_handle = win32service.OpenSCManager(
                None,
                None,
                win32service.SC_MANAGER_CONNECT,
            )
            try:
                svc_handle = win32service.OpenService(
                    scm_handle,
                    name,
                    win32service.SERVICE_QUERY_CONFIG,
                )
                try:
                    cfg = win32service.QueryServiceConfig(svc_handle)
                    # cfg is a tuple: (ServiceType, StartType, ErrorControl, BinaryPathName,
                    #   LoadOrderGroup, TagId, Dependencies, ServiceStartName, DisplayName)
                    start_type_int = cfg[1]
                    logon_as = cfg[7] if cfg[7] else None
                    return {
                        "startup_type": _STARTUP_TYPE_MAP.get(start_type_int),
                        "logon_as": logon_as,
                    }
                finally:
                    win32service.CloseServiceHandle(svc_handle)
            finally:
                win32service.CloseServiceHandle(scm_handle)
        except Exception:
            return {"startup_type": None, "logon_as": None}

    def _query_status(self, name: str) -> int:
        """
        Query the current dwCurrentState for a service.

        Args:
            name: The Windows service internal SCM name.

        Returns:
            Integer dwCurrentState value.

        Raises:
            ServiceError subclasses on failure.
        """
        try:
            scm_handle = win32service.OpenSCManager(
                None,
                None,
                win32service.SC_MANAGER_CONNECT,
            )
            try:
                svc_handle = win32service.OpenService(
                    scm_handle,
                    name,
                    win32service.SERVICE_QUERY_STATUS,
                )
                try:
                    status = win32service.QueryServiceStatusEx(svc_handle)
                    return status["CurrentState"]
                finally:
                    win32service.CloseServiceHandle(svc_handle)
            finally:
                win32service.CloseServiceHandle(scm_handle)
        except pywintypes.error as exc:
            raise _map_win_error(exc, name) from exc

    def _wait_for_state(self, name: str, target_state: int) -> None:
        """
        Poll service status until it reaches the target state or times out.

        Args:
            name: The Windows service internal SCM name.
            target_state: The integer dwCurrentState to wait for.

        Raises:
            ServiceTimeoutError: If the target state is not reached in time.
        """
        deadline = time.monotonic() + self.timeout_seconds
        interval = self.poll_interval_ms / 1000.0

        while time.monotonic() < deadline:
            current_state = self._query_status(name)
            if current_state == target_state:
                return
            time.sleep(interval)

        target_label = _map_status(target_state)
        raise ServiceTimeoutError(
            f"Service '{name}' did not reach '{target_label}' state "
            f"within {self.timeout_seconds} seconds"
        )


def _create_service_manager() -> ServiceManager:
    """Instantiate ServiceManager from the loaded application config."""
    from config import config

    return ServiceManager(
        timeout_seconds=config.service_control.timeout_seconds,
        poll_interval_ms=config.service_control.poll_interval_ms,
    )


service_manager: ServiceManager = _create_service_manager()

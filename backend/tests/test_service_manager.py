"""
Tests for service_manager.py – ServiceManager with mocked pywin32.

All win32service / pywintypes calls are intercepted via the sys.modules
stubs injected in conftest.py, so these tests run on non-Windows platforms.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

# Ensure backend is importable
_backend_dir = str(Path(__file__).parent.parent)
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

# Import after sys.modules stubs are in place (conftest.py does that at
# collection time, so the stubs are already present here).
import service_manager as sm
from service_manager import (
    ServiceAlreadyRunningError,
    ServiceAlreadyStoppedError,
    ServiceManager,
    ServiceNotFoundError,
    ServicePermissionError,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_manager() -> ServiceManager:
    """Return a ServiceManager with a very short timeout to avoid slow tests."""
    return ServiceManager(timeout_seconds=1, poll_interval_ms=50)


def _pywintypes_error(winerror: int) -> Exception:
    """Create a pywintypes.error-like exception with the given Windows error code."""
    err = sm.pywintypes.error(winerror, "", "")
    err.args = (winerror, "", "")
    return err


# ---------------------------------------------------------------------------
# list_services
# ---------------------------------------------------------------------------


def test_list_services_returns_filtered(mock_win32service):
    """list_services should return only services whose names pass the filter."""
    # Raw SCM data: (name, display_name, (svc_type, state, pid, ...))
    raw = [
        ("MyService",    "My Service Display",    (16, 4, 1234, 0, 0, 0, 0)),
        ("OtherService", "Other Service Display",  (16, 1, 0,    0, 0, 0, 0)),
        ("MyOtherSvc",   "My Other Svc Display",   (16, 1, 0,    0, 0, 0, 0)),
    ]
    mock_win32service.OpenSCManager.return_value = MagicMock(name="scm_handle")
    mock_win32service.EnumServicesStatus.return_value = raw

    manager = _make_manager()
    # Patch the module-level win32service reference inside service_manager
    with patch.object(sm, "win32service", mock_win32service):
        services = manager.list_services()

    names = [s["name"] for s in services]
    assert "MyService" in names
    assert "OtherService" in names
    assert "MyOtherSvc" in names
    assert len(services) == 3


def test_list_services_status_mapping(mock_win32service):
    """Integer state values from the SCM should map to the correct status strings."""
    raw = [
        ("Svc1", "Svc1 Display", (16, 4, 100, 0, 0, 0, 0)),  # running
        ("Svc2", "Svc2 Display", (16, 1, 0,   0, 0, 0, 0)),  # stopped
        ("Svc3", "Svc3 Display", (16, 2, 0,   0, 0, 0, 0)),  # starting
        ("Svc4", "Svc4 Display", (16, 3, 0,   0, 0, 0, 0)),  # stopping
    ]
    mock_win32service.OpenSCManager.return_value = MagicMock()
    mock_win32service.EnumServicesStatus.return_value = raw

    manager = _make_manager()
    with patch.object(sm, "win32service", mock_win32service):
        services = manager.list_services()

    by_name = {s["name"]: s for s in services}
    assert by_name["Svc1"]["status"] == "running"
    assert by_name["Svc2"]["status"] == "stopped"
    assert by_name["Svc3"]["status"] == "starting"
    assert by_name["Svc4"]["status"] == "stopping"


# ---------------------------------------------------------------------------
# start_service
# ---------------------------------------------------------------------------


def test_start_service_success(mock_win32service):
    """start_service should complete without raising when pywin32 succeeds."""
    scm_handle = MagicMock(name="scm")
    svc_handle = MagicMock(name="svc")
    mock_win32service.OpenSCManager.return_value = scm_handle
    mock_win32service.OpenService.return_value = svc_handle
    mock_win32service.StartService.return_value = None

    # _wait_for_state needs QueryServiceStatusEx to return the running state
    mock_win32service.QueryServiceStatusEx.return_value = {"CurrentState": 4}

    manager = _make_manager()
    with patch.object(sm, "win32service", mock_win32service), \
         patch.object(sm, "pywintypes", sm.pywintypes):
        manager.start_service("MyService")  # Should not raise

    mock_win32service.StartService.assert_called_once()


def test_stop_service_success(mock_win32service):
    """stop_service should call ControlService with SERVICE_CONTROL_STOP."""
    scm_handle = MagicMock(name="scm")
    svc_handle = MagicMock(name="svc")
    mock_win32service.OpenSCManager.return_value = scm_handle
    mock_win32service.OpenService.return_value = svc_handle
    mock_win32service.ControlService.return_value = None
    mock_win32service.QueryServiceStatusEx.return_value = {"CurrentState": 1}

    manager = _make_manager()
    with patch.object(sm, "win32service", mock_win32service), \
         patch.object(sm, "pywintypes", sm.pywintypes):
        manager.stop_service("MyService")

    mock_win32service.ControlService.assert_called_once_with(
        svc_handle, mock_win32service.SERVICE_CONTROL_STOP
    )


# ---------------------------------------------------------------------------
# Error mapping: start_service
# ---------------------------------------------------------------------------


def test_start_service_not_found(mock_win32service):
    """winerror 1060 (ERROR_SERVICE_DOES_NOT_EXIST) should raise ServiceNotFoundError."""
    mock_win32service.OpenSCManager.return_value = MagicMock()
    mock_win32service.OpenService.side_effect = _pywintypes_error(1060)

    manager = _make_manager()
    with patch.object(sm, "win32service", mock_win32service), \
         patch.object(sm, "pywintypes", sm.pywintypes):
        with pytest.raises(ServiceNotFoundError):
            manager.start_service("GhostService")


def test_start_service_permission_denied(mock_win32service):
    """winerror 5 (ERROR_ACCESS_DENIED) should raise ServicePermissionError."""
    mock_win32service.OpenSCManager.return_value = MagicMock()
    mock_win32service.OpenService.side_effect = _pywintypes_error(5)

    manager = _make_manager()
    with patch.object(sm, "win32service", mock_win32service), \
         patch.object(sm, "pywintypes", sm.pywintypes):
        with pytest.raises(ServicePermissionError):
            manager.start_service("ProtectedService")


def test_start_service_already_running(mock_win32service):
    """winerror 1056 (ERROR_SERVICE_ALREADY_RUNNING) should raise ServiceAlreadyRunningError."""
    mock_win32service.OpenSCManager.return_value = MagicMock()
    mock_win32service.OpenService.return_value = MagicMock()
    mock_win32service.StartService.side_effect = _pywintypes_error(1056)

    manager = _make_manager()
    with patch.object(sm, "win32service", mock_win32service), \
         patch.object(sm, "pywintypes", sm.pywintypes):
        with pytest.raises(ServiceAlreadyRunningError):
            manager.start_service("AlreadyRunning")


# ---------------------------------------------------------------------------
# Error mapping: stop_service
# ---------------------------------------------------------------------------


def test_stop_service_already_stopped(mock_win32service):
    """winerror 1062 (ERROR_SERVICE_NOT_ACTIVE) should raise ServiceAlreadyStoppedError."""
    mock_win32service.OpenSCManager.return_value = MagicMock()
    mock_win32service.OpenService.return_value = MagicMock()
    mock_win32service.ControlService.side_effect = _pywintypes_error(1062)

    manager = _make_manager()
    with patch.object(sm, "win32service", mock_win32service), \
         patch.object(sm, "pywintypes", sm.pywintypes):
        with pytest.raises(ServiceAlreadyStoppedError):
            manager.stop_service("AlreadyStopped")


# ---------------------------------------------------------------------------
# restart_service
# ---------------------------------------------------------------------------


def test_restart_service_calls_stop_then_start(mock_win32service):
    """restart_service must call stop_service and then start_service in order."""
    manager = _make_manager()

    call_order = []

    def _stop(name):
        call_order.append("stop")

    def _start(name):
        call_order.append("start")

    with patch.object(manager, "stop_service", side_effect=_stop), \
         patch.object(manager, "start_service", side_effect=_start):
        manager.restart_service("SomeService")

    assert call_order == ["stop", "start"]


def test_restart_service_starts_even_if_already_stopped(mock_win32service):
    """restart_service should start a service that was already stopped (no exception)."""
    manager = _make_manager()

    def _stop_raises(name):
        raise ServiceAlreadyStoppedError("already stopped")

    start_called = []

    def _start(name):
        start_called.append(name)

    with patch.object(manager, "stop_service", side_effect=_stop_raises), \
         patch.object(manager, "start_service", side_effect=_start):
        manager.restart_service("StoppedService")

    assert start_called == ["StoppedService"]

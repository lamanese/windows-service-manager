"""
Shared pytest fixtures for Windows Service Manager backend tests.

Patches win32service, win32con, and pywintypes at the sys.modules level
so all tests can run on non-Windows platforms without pywin32 installed.
"""

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml


# ---------------------------------------------------------------------------
# Inject mock pywin32 modules before any application code is imported.
# ---------------------------------------------------------------------------


class _MockPywintypes(types.ModuleType):
    """Minimal pywintypes stub."""

    class error(Exception):
        """Mimics pywintypes.error; args[0] is the Windows error code."""
        pass


_win32con_mod = MagicMock(name="win32con")
_pywintypes_mod = _MockPywintypes("pywintypes")

# A single shared pywintypes stub is fine; win32service is re-created per test.
sys.modules.setdefault("win32con", _win32con_mod)
sys.modules.setdefault("pywintypes", _pywintypes_mod)

# Make sure backend/ is on the path so imports work during testing.
_backend_dir = str(Path(__file__).parent.parent)
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

# Bootstrap win32service in sys.modules with a fresh mock so that the first
# import of service_manager picks it up.  Tests that need to control behaviour
# will replace it via patch.object.
_initial_win32service = MagicMock(name="win32service")
_initial_win32service.SC_MANAGER_CONNECT = 0x0001
_initial_win32service.SC_MANAGER_ENUMERATE_SERVICE = 0x0004
_initial_win32service.SERVICE_WIN32 = 0x30
_initial_win32service.SERVICE_STATE_ALL = 0x03
_initial_win32service.SERVICE_START = 0x0010
_initial_win32service.SERVICE_STOP = 0x0020
_initial_win32service.SERVICE_QUERY_STATUS = 0x0004
_initial_win32service.SERVICE_CONTROL_STOP = 0x00000001
_initial_win32service.SERVICE_RUNNING = 4
_initial_win32service.SERVICE_STOPPED = 1
sys.modules.setdefault("win32service", _initial_win32service)


def _fresh_win32service() -> MagicMock:
    """Return a brand-new MagicMock that mimics win32service with constants set."""
    mock = MagicMock(name="win32service")
    mock.SC_MANAGER_CONNECT = 0x0001
    mock.SC_MANAGER_ENUMERATE_SERVICE = 0x0004
    mock.SERVICE_WIN32 = 0x30
    mock.SERVICE_STATE_ALL = 0x03
    mock.SERVICE_START = 0x0010
    mock.SERVICE_STOP = 0x0020
    mock.SERVICE_QUERY_STATUS = 0x0004
    mock.SERVICE_CONTROL_STOP = 0x00000001
    mock.SERVICE_RUNNING = 4
    mock.SERVICE_STOPPED = 1
    return mock


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_config_yaml(tmp_path):
    """Return a factory that writes a config.yaml under tmp_path."""

    def _write(data: dict) -> Path:
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(data), encoding="utf-8")
        return config_file

    return _write


@pytest.fixture()
def tmp_log_dir(tmp_path):
    """Return a temporary directory for log files."""
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    return log_dir


@pytest.fixture()
def mock_win32service():
    """Return a fresh win32service mock per test so there is no state leakage."""
    return _fresh_win32service()


@pytest.fixture()
def mock_pywintypes():
    """Return the pywintypes stub (provides pywintypes.error)."""
    return _pywintypes_mod

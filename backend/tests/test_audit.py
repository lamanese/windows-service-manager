"""
Tests for audit.py – AuditLogger.
"""

import json
import logging
import re
import sys
from pathlib import Path

import pytest

# Ensure backend is importable
_backend_dir = str(Path(__file__).parent.parent)
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from audit import AuditLogger


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_logger(log_path: str, max_bytes: int = 10 * 1024 * 1024, backup_count: int = 5) -> AuditLogger:
    """Create a fresh AuditLogger, clearing any existing handlers first."""
    # Remove cached handlers so each test gets a clean logger instance
    root = logging.getLogger("audit")
    root.handlers.clear()
    return AuditLogger(log_path=log_path, max_bytes=max_bytes, backup_count=backup_count)


def _read_lines(log_path: str) -> list[str]:
    return [line for line in Path(log_path).read_text(encoding="utf-8").splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_log_creates_file(tmp_path):
    """After the first log() call the log file must exist on disk."""
    log_path = str(tmp_path / "audit.log")
    logger = _make_logger(log_path)

    logger.log(
        action="start",
        service_name="TestSvc",
        client_ip="127.0.0.1",
        result="success",
    )

    assert Path(log_path).exists()


def test_log_json_format(tmp_path):
    """Each log line must be valid JSON containing all 7 required fields."""
    log_path = str(tmp_path / "audit.log")
    logger = _make_logger(log_path)

    logger.log(
        action="stop",
        service_name="Spooler",
        client_ip="10.0.0.1",
        result="error",
        detail="Access denied",
        duration_ms=42,
    )

    lines = _read_lines(log_path)
    assert len(lines) == 1

    entry = json.loads(lines[0])
    required_fields = {"timestamp", "action", "service_name", "client_ip", "result", "detail", "duration_ms"}
    assert required_fields == set(entry.keys())

    assert entry["action"] == "stop"
    assert entry["service_name"] == "Spooler"
    assert entry["client_ip"] == "10.0.0.1"
    assert entry["result"] == "error"
    assert entry["detail"] == "Access denied"
    assert entry["duration_ms"] == 42


def test_log_timestamp_iso8601(tmp_path):
    """The timestamp field must conform to ISO 8601 format."""
    log_path = str(tmp_path / "audit.log")
    logger = _make_logger(log_path)

    logger.log(
        action="restart",
        service_name="WinRM",
        client_ip="192.168.1.1",
        result="success",
    )

    lines = _read_lines(log_path)
    entry = json.loads(lines[0])
    # ISO 8601 with UTC offset: YYYY-MM-DDTHH:MM:SS.ffffff+HH:MM or ...Z
    iso8601_pattern = re.compile(
        r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
    )
    assert iso8601_pattern.match(entry["timestamp"]), (
        f"Timestamp '{entry['timestamp']}' does not match ISO 8601"
    )


def test_log_multiple_entries(tmp_path):
    """Three log() calls must produce exactly three JSON lines in the file."""
    log_path = str(tmp_path / "audit.log")
    logger = _make_logger(log_path)

    for i in range(3):
        logger.log(
            action="start",
            service_name=f"Svc{i}",
            client_ip="1.2.3.4",
            result="success",
            duration_ms=i * 10,
        )

    lines = _read_lines(log_path)
    assert len(lines) == 3

    for idx, line in enumerate(lines):
        entry = json.loads(line)
        assert entry["service_name"] == f"Svc{idx}"


def test_log_creates_directory(tmp_path):
    """AuditLogger must create the parent directory if it does not exist."""
    nested = tmp_path / "deep" / "nested" / "logs" / "audit.log"

    _make_logger(str(nested))

    assert nested.parent.exists()


def test_rotation(tmp_path):
    """Writing enough data to exceed max_bytes should trigger file rotation."""
    log_path = str(tmp_path / "audit.log")
    max_bytes = 200  # very small to force rotation quickly
    logger = _make_logger(log_path, max_bytes=max_bytes, backup_count=2)

    # Write enough entries to exceed max_bytes
    for i in range(20):
        logger.log(
            action="start",
            service_name=f"ServiceWithLongName{i:04d}",
            client_ip="192.168.100.200",
            result="success",
            detail=None,
            duration_ms=i,
        )

    # Flush handlers
    for handler in logging.getLogger("audit").handlers:
        handler.flush()

    backup_file = Path(log_path + ".1")
    assert backup_file.exists(), "Rotation backup file audit.log.1 was not created"

"""
Audit logging module for Windows Service Manager.

Writes JSON Lines entries to a rotating log file. Each entry records
a service action (start/stop/restart) with client IP, result, and duration.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path


class AuditLogger:
    """
    Thread-safe audit logger that writes JSON Lines to a rotating file.

    Each log entry contains a timestamp, action, service name, client IP,
    result (success/error), optional detail, and action duration in ms.
    The underlying RotatingFileHandler is thread-safe by design.
    """

    def __init__(self, log_path: str, max_bytes: int, backup_count: int) -> None:
        """
        Initialize the AuditLogger.

        Creates the log directory if it does not exist.

        Args:
            log_path: Path to the audit log file (e.g. "logs/audit.log").
            max_bytes: Maximum file size in bytes before rotation.
            backup_count: Number of backup files to retain.
        """
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)

        self._logger = logging.getLogger("audit")
        self._logger.setLevel(logging.INFO)
        # Avoid adding duplicate handlers if module is reloaded
        if not self._logger.handlers:
            handler = RotatingFileHandler(
                log_path,
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding="utf-8",
            )
            handler.setFormatter(logging.Formatter("%(message)s"))
            self._logger.addHandler(handler)

    def log(
        self,
        action: str,
        service_name: str,
        client_ip: str,
        result: str,
        detail: str | None = None,
        duration_ms: int = 0,
    ) -> None:
        """
        Write a single audit log entry as a JSON Line.

        Args:
            action: One of "start", "stop", "restart".
            service_name: The Windows service internal SCM name.
            client_ip: Client IP address extracted from request headers.
            result: One of "success", "error".
            detail: Human-readable error message when result is "error",
                    None on success.
            duration_ms: Duration of the action in milliseconds.
        """
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "service_name": service_name,
            "client_ip": client_ip,
            "result": result,
            "detail": detail,
            "duration_ms": duration_ms,
        }
        self._logger.info(json.dumps(entry, ensure_ascii=False))


def _create_audit_logger() -> AuditLogger:
    """Instantiate AuditLogger from the loaded application config."""
    from config import config

    log_path = config.logging.audit_log
    max_bytes = config.logging.max_size_mb * 1024 * 1024
    backup_count = config.logging.backup_count
    return AuditLogger(log_path=log_path, max_bytes=max_bytes, backup_count=backup_count)


audit_logger: AuditLogger = _create_audit_logger()

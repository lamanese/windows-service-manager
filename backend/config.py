"""
Configuration module for Windows Service Manager.

Loads config.yaml from the application root (one level above backend/),
validates it with Pydantic, and exposes a module-level singleton.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8080
    name: str = ""


class LoggingConfig(BaseModel):
    audit_log: str = "logs/audit.log"
    max_size_mb: int = 10
    backup_count: int = 5


class ServiceFilter(BaseModel):
    type: str  # "prefix" or "contains"
    value: str


class RateLimitConfig(BaseModel):
    max_requests: int = 10
    window_seconds: int = 60


class ServiceControlConfig(BaseModel):
    timeout_seconds: int = 30
    poll_interval_ms: int = 500


class UiDefaultsConfig(BaseModel):
    show_startup_type: bool = False
    show_logon_as: bool = False
    filter_status: str = "all"
    filter_startup_type: str = "all"


class AppConfig(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    service_filters: list[ServiceFilter] = Field(default_factory=list)
    service_exclude: list[str] = Field(default_factory=list)
    rate_limit: RateLimitConfig = Field(default_factory=RateLimitConfig)
    service_control: ServiceControlConfig = Field(default_factory=ServiceControlConfig)
    ui_defaults: UiDefaultsConfig = Field(default_factory=UiDefaultsConfig)


def matches_filter(
    service_name: str,
    filters: list[ServiceFilter],
    exclude: list[str],
) -> bool:
    """
    Determine whether a service name passes the configured filters.

    The exclude list takes precedence: if the service name appears in the
    exclude list, returns False immediately regardless of filters.

    If no filters are configured, all non-excluded services are matched.
    Filter conditions are evaluated with OR logic: a service passes if it
    matches ANY of the configured filters.

    Args:
        service_name: The Windows service internal name.
        filters: List of ServiceFilter objects (type + value).
        exclude: List of service names that must never be matched.

    Returns:
        True if the service should be included, False otherwise.
    """
    if service_name in exclude:
        return False

    if not filters:
        return True

    for f in filters:
        if f.type == "prefix":
            if service_name.lower().startswith(f.value.lower()):
                return True
        elif f.type == "contains":
            if f.value.lower() in service_name.lower():
                return True

    return False


def load_config(path: str = "config.yaml") -> AppConfig:
    """
    Load and validate application configuration from a YAML file.

    If the file does not exist, returns an AppConfig with all defaults.
    If the file is malformed YAML or contains invalid field types, raises
    a descriptive error to abort startup.

    Args:
        path: Path to the config.yaml file.

    Returns:
        Validated AppConfig instance.

    Raises:
        SystemExit: If YAML is malformed or Pydantic validation fails.
    """
    config_path = Path(path)

    if not config_path.exists():
        return AppConfig()

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        print(f"ERROR: config.yaml is malformed: {exc}", file=sys.stderr)
        sys.exit(1)

    if raw is None:
        return AppConfig()

    try:
        return AppConfig.model_validate(raw)
    except Exception as exc:
        print(f"ERROR: config.yaml has invalid fields: {exc}", file=sys.stderr)
        sys.exit(1)


def get_config() -> AppConfig:
    """Return the cached module-level AppConfig singleton."""
    return config


# Resolve path relative to main.py location (parent of this file's directory)
_config_path = Path(__file__).parent.parent / "config.yaml"
config: AppConfig = load_config(str(_config_path))

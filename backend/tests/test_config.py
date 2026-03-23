"""
Tests for config.py – load_config and matches_filter.
"""

import sys
from pathlib import Path

import pytest
import yaml

# Ensure backend is importable
_backend_dir = str(Path(__file__).parent.parent)
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from config import AppConfig, ServiceFilter, load_config, matches_filter


# ---------------------------------------------------------------------------
# load_config
# ---------------------------------------------------------------------------


def test_load_default_config(tmp_path):
    """load_config with a non-existent path should return all-default AppConfig."""
    non_existent = str(tmp_path / "does_not_exist.yaml")

    cfg = load_config(non_existent)

    assert isinstance(cfg, AppConfig)
    assert cfg.server.host == "0.0.0.0"
    assert cfg.server.port == 8080
    assert cfg.logging.audit_log == "logs/audit.log"
    assert cfg.logging.max_size_mb == 10
    assert cfg.logging.backup_count == 5
    assert cfg.rate_limit.max_requests == 10
    assert cfg.rate_limit.window_seconds == 60
    assert cfg.service_filters == []
    assert cfg.service_exclude == []


def test_load_custom_config(tmp_path):
    """load_config with a valid config.yaml should populate all fields."""
    data = {
        "server": {"host": "127.0.0.1", "port": 9090},
        "logging": {"audit_log": "custom/audit.log", "max_size_mb": 20, "backup_count": 3},
        "service_filters": [{"type": "prefix", "value": "My"}],
        "service_exclude": ["ExcludedSvc"],
        "rate_limit": {"max_requests": 5, "window_seconds": 30},
        "service_control": {"timeout_seconds": 15, "poll_interval_ms": 250},
    }
    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.dump(data), encoding="utf-8")

    cfg = load_config(str(config_file))

    assert cfg.server.host == "127.0.0.1"
    assert cfg.server.port == 9090
    assert cfg.logging.audit_log == "custom/audit.log"
    assert cfg.logging.max_size_mb == 20
    assert cfg.logging.backup_count == 3
    assert len(cfg.service_filters) == 1
    assert cfg.service_filters[0].type == "prefix"
    assert cfg.service_filters[0].value == "My"
    assert cfg.service_exclude == ["ExcludedSvc"]
    assert cfg.rate_limit.max_requests == 5
    assert cfg.rate_limit.window_seconds == 30
    assert cfg.service_control.timeout_seconds == 15
    assert cfg.service_control.poll_interval_ms == 250


# ---------------------------------------------------------------------------
# matches_filter
# ---------------------------------------------------------------------------


def test_matches_filter_prefix():
    """A service whose name starts with the filter value (case-insensitive) should match."""
    filters = [ServiceFilter(type="prefix", value="my")]

    assert matches_filter("MyService", filters, []) is True
    assert matches_filter("MYAPP", filters, []) is True
    assert matches_filter("myThing", filters, []) is True


def test_matches_filter_contains():
    """A service whose name contains the filter value (case-insensitive) should match."""
    filters = [ServiceFilter(type="contains", value="sql")]

    assert matches_filter("SQLBrowser", filters, []) is True
    assert matches_filter("MySqlServer", filters, []) is True
    assert matches_filter("MSSQLSERVER", filters, []) is True


def test_matches_filter_exclude():
    """An excluded service should return False even when it matches a filter."""
    filters = [ServiceFilter(type="prefix", value="my")]
    exclude = ["MyService"]

    assert matches_filter("MyService", filters, exclude) is False


def test_matches_filter_or_logic():
    """A service matching any single filter out of multiple should return True."""
    filters = [
        ServiceFilter(type="prefix", value="sql"),
        ServiceFilter(type="contains", value="agent"),
    ]

    # Matches second filter
    assert matches_filter("SqlAgent", filters, []) is True
    # Matches first filter
    assert matches_filter("SQLBrowser", filters, []) is True


def test_matches_filter_no_match():
    """A service matching none of the filters should return False."""
    filters = [
        ServiceFilter(type="prefix", value="sql"),
        ServiceFilter(type="contains", value="agent"),
    ]

    assert matches_filter("Spooler", filters, []) is False
    assert matches_filter("WinRM", filters, []) is False


def test_matches_filter_empty_filters():
    """When no filters are configured, all non-excluded services should match."""
    assert matches_filter("AnyService", [], []) is True
    assert matches_filter("AnotherService", [], []) is True


def test_matches_filter_empty_filters_with_exclude():
    """Excluded services should still be excluded even with no filter list."""
    assert matches_filter("ExcludedSvc", [], ["ExcludedSvc"]) is False
    assert matches_filter("SafeSvc", [], ["ExcludedSvc"]) is True

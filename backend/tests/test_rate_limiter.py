"""
Tests for rate_limiter.py – RateLimiter.
"""

import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure backend is importable
_backend_dir = str(Path(__file__).parent.parent)
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from rate_limiter import RateLimiter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_limiter(max_requests: int = 10, window_seconds: int = 60) -> RateLimiter:
    return RateLimiter(max_requests=max_requests, window_seconds=window_seconds)


def _fill_requests(limiter: RateLimiter, client_ip: str, count: int) -> None:
    """Record `count` requests for client_ip without going through is_allowed."""
    for _ in range(count):
        limiter.record(client_ip)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_allows_under_limit():
    """9 requests from the same IP should all be allowed (limit is 10)."""
    limiter = _make_limiter(max_requests=10)
    ip = "10.0.0.1"

    _fill_requests(limiter, ip, 9)

    allowed, retry_after = limiter.is_allowed(ip)

    assert allowed is True
    assert retry_after == 0


def test_blocks_at_limit():
    """After 10 recorded requests the 11th check should be blocked."""
    limiter = _make_limiter(max_requests=10)
    ip = "10.0.0.2"

    _fill_requests(limiter, ip, 10)

    allowed, retry_after = limiter.is_allowed(ip)

    assert allowed is False
    assert retry_after >= 1


def test_different_ips_independent():
    """10 requests from IP-A and 10 from IP-B must both stay within their own limits."""
    limiter = _make_limiter(max_requests=10)
    ip_a = "192.168.1.1"
    ip_b = "192.168.1.2"

    _fill_requests(limiter, ip_a, 10)
    _fill_requests(limiter, ip_b, 10)

    # Both are exactly at the limit so the *next* request should be blocked,
    # but currently they are at max – is_allowed checks len >= max_requests.
    allowed_a, _ = limiter.is_allowed(ip_a)
    allowed_b, _ = limiter.is_allowed(ip_b)

    # Both are at exactly max_requests so both should be blocked now
    assert allowed_a is False
    assert allowed_b is False

    # Verify independence: fill 9 requests for ip_a and 10 for ip_b
    limiter2 = _make_limiter(max_requests=10)
    _fill_requests(limiter2, ip_a, 9)
    _fill_requests(limiter2, ip_b, 10)

    allowed_a2, _ = limiter2.is_allowed(ip_a)
    allowed_b2, _ = limiter2.is_allowed(ip_b)

    assert allowed_a2 is True   # ip_a still under limit
    assert allowed_b2 is False  # ip_b is at limit


def test_sliding_window_resets():
    """After the window period elapses, requests from the same IP should be allowed again."""
    window = 2  # short window for testing
    limiter = _make_limiter(max_requests=3, window_seconds=window)
    ip = "172.16.0.1"

    # Record the maximum number of requests at a fixed past time
    past_time = time.time() - (window + 1)  # older than the window

    with limiter._lock:
        limiter._requests[ip] = [past_time, past_time, past_time]

    # All three timestamps are outside the window; next request should be allowed
    allowed, retry_after = limiter.is_allowed(ip)

    assert allowed is True
    assert retry_after == 0


def test_record_increments_count():
    """Each record() call should increase the tracked request count for the IP."""
    limiter = _make_limiter(max_requests=5)
    ip = "10.1.1.1"

    for i in range(1, 4):
        limiter.record(ip)
        with limiter._lock:
            assert len(limiter._requests[ip]) == i


def test_is_allowed_does_not_record():
    """is_allowed() must not record the request; count should remain unchanged."""
    limiter = _make_limiter(max_requests=5)
    ip = "10.2.2.2"

    _fill_requests(limiter, ip, 3)

    limiter.is_allowed(ip)
    limiter.is_allowed(ip)

    with limiter._lock:
        assert len(limiter._requests[ip]) == 3


def test_retry_after_is_positive_integer():
    """When blocked, retry_after must be a positive integer (at least 1)."""
    limiter = _make_limiter(max_requests=1, window_seconds=60)
    ip = "10.3.3.3"

    limiter.record(ip)

    allowed, retry_after = limiter.is_allowed(ip)

    assert allowed is False
    assert isinstance(retry_after, int)
    assert retry_after >= 1

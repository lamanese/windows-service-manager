"""
In-memory sliding window rate limiter for Windows Service Manager.

Tracks per-IP request timestamps and enforces a configurable request cap
over a rolling time window. Thread-safe via threading.Lock.
"""

import math
import threading
import time
from collections import defaultdict


class RateLimiter:
    """
    Per-IP sliding-window rate limiter backed by an in-memory timestamp list.

    Thread-safe: all mutations are protected by a threading.Lock so that the
    limiter works correctly when called from asyncio thread-pool workers as
    well as from the main async context.
    """

    def __init__(self, max_requests: int = 10, window_seconds: int = 60) -> None:
        """
        Initialize the rate limiter.

        Args:
            max_requests: Maximum number of requests allowed per IP within
                          the rolling window.
            window_seconds: Length of the sliding window in seconds.
        """
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def is_allowed(self, client_ip: str) -> tuple[bool, int]:
        """
        Check whether a new request from client_ip is within the rate limit.

        Removes timestamps that fall outside the current window before
        deciding. Does NOT record the current request; call ``record()``
        separately after the action completes.

        Args:
            client_ip: The client IP address string.

        Returns:
            A tuple ``(allowed, retry_after_seconds)``.
            ``retry_after_seconds`` is 0 when ``allowed`` is True.
        """
        with self._lock:
            now = time.time()
            self._cleanup(client_ip, now)
            timestamps = self._requests[client_ip]
            if len(timestamps) >= self.max_requests:
                oldest = timestamps[0]
                retry_after = math.ceil(oldest + self.window_seconds - now)
                return False, max(retry_after, 1)
            return True, 0

    def record(self, client_ip: str) -> None:
        """
        Record a completed request for the given IP.

        Should be called after an action endpoint completes (success or
        failure) so that the timestamp contributes to future rate checks.

        Args:
            client_ip: The client IP address string.
        """
        with self._lock:
            self._requests[client_ip].append(time.time())

    def cleanup_stale(self) -> None:
        """
        Remove IP entries with no timestamps in the last window period.

        Called periodically by a background task to prevent unbounded memory
        growth from IPs that sent requests long ago and have since gone quiet.
        """
        with self._lock:
            now = time.time()
            cutoff = now - self.window_seconds
            stale_ips = [
                ip
                for ip, timestamps in self._requests.items()
                if not timestamps or timestamps[-1] < cutoff
            ]
            for ip in stale_ips:
                del self._requests[ip]

    def _cleanup(self, client_ip: str, now: float) -> None:
        """
        Remove timestamps outside the current window for a single IP.

        Must be called with ``self._lock`` already held.

        Args:
            client_ip: The IP whose timestamp list to trim.
            now: Current time as a float (seconds since epoch).
        """
        cutoff = now - self.window_seconds
        timestamps = self._requests[client_ip]
        # Find the first index still within the window
        i = 0
        while i < len(timestamps) and timestamps[i] < cutoff:
            i += 1
        self._requests[client_ip] = timestamps[i:]

"""
FastAPI application entry point for Windows Service Manager.

Defines all API endpoints, wires dependencies (config, audit, rate limiter,
service manager), and serves the frontend as static files.
"""

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from audit import audit_logger
from config import config
from rate_limiter import RateLimiter
from service_manager import (
    ServiceAlreadyRunningError,
    ServiceAlreadyStoppedError,
    ServiceError,
    ServiceNotFoundError,
    ServicePermissionError,
    ServiceTimeoutError,
    service_manager,
)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------

rate_limiter = RateLimiter(
    max_requests=config.rate_limit.max_requests,
    window_seconds=config.rate_limit.window_seconds,
)


# ---------------------------------------------------------------------------
# Lifespan (startup / shutdown)
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start background cleanup task for the rate limiter on startup."""
    cleanup_task = asyncio.create_task(_rate_limiter_cleanup_loop())
    yield
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass


async def _rate_limiter_cleanup_loop() -> None:
    """Periodically purge stale IP entries from the rate limiter."""
    while True:
        await asyncio.sleep(300)  # every 5 minutes
        rate_limiter.cleanup_stale()


# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(title="Windows Service Manager", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------


def get_client_ip(request: Request) -> str:
    """
    Extract the real client IP address from the request.

    Reads the first value from the X-Forwarded-For header when set by a
    reverse proxy, falling back to the direct connection host.

    Args:
        request: The incoming FastAPI request.

    Returns:
        Client IP address string.
    """
    forwarded_for = request.headers.get("X-Forwarded-For", "").strip()
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# ---------------------------------------------------------------------------
# Rate-limit dependency
# ---------------------------------------------------------------------------


async def check_rate_limit(request: Request) -> str:
    """
    FastAPI dependency that enforces the per-IP rate limit.

    Returns the client IP on success. Raises HTTP 429 when the limit is
    exceeded, including a Retry-After header.

    Args:
        request: The incoming FastAPI request.

    Returns:
        The client IP string for use by the endpoint.

    Raises:
        HTTPException: 429 when the rate limit is exceeded.
    """
    client_ip = get_client_ip(request)
    allowed, retry_after = rate_limiter.is_allowed(client_ip)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=(
                f"Maximum {rate_limiter.max_requests} actions per minute. "
                f"Try again in {retry_after} seconds"
            ),
            headers={"Retry-After": str(retry_after)},
        )
    return client_ip


# ---------------------------------------------------------------------------
# Global exception handler
# ---------------------------------------------------------------------------


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch all unhandled exceptions and return a safe 500 response."""
    logger.exception("Unhandled exception on %s %s", request.method, request.url)
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "detail": "An unexpected error occurred",
        },
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/api/services")
async def get_services() -> dict:
    """
    Return the list of Windows services matching the configured filters.

    No rate limiting is applied to this read-only endpoint.

    Returns:
        JSON object with ``services`` list and ``timestamp``.

    Raises:
        HTTPException: 500 on SCM connection or enumeration failure.
    """
    try:
        all_services = await asyncio.to_thread(service_manager.list_services)
    except ServicePermissionError as exc:
        raise HTTPException(
            status_code=403,
            detail={"error": "Permission denied", "detail": str(exc)},
        )
    except ServiceError as exc:
        raise HTTPException(
            status_code=500,
            detail={"error": "Failed to enumerate services", "detail": str(exc)},
        )

    filters = config.service_filters
    exclude = config.service_exclude

    if filters or exclude:
        from config import matches_filter

        all_services = [
            svc
            for svc in all_services
            if matches_filter(svc["name"], filters, exclude)
            or matches_filter(svc["display_name"], filters, exclude)
        ]

    return {
        "services": all_services,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.post("/api/services/{name}/start")
async def start_service(
    name: str, client_ip: str = Depends(check_rate_limit)
) -> dict:
    """
    Start a Windows service.

    Args:
        name: Windows service internal SCM name.
        client_ip: Injected by the rate-limit dependency.

    Returns:
        JSON with success, service, action, status.

    Raises:
        HTTPException: 404/403/409/504/500 on failure.
    """
    start_ms = time.monotonic()
    try:
        await asyncio.to_thread(service_manager.start_service, name)
        duration_ms = int((time.monotonic() - start_ms) * 1000)
        rate_limiter.record(client_ip)
        audit_logger.log(
            action="start",
            service_name=name,
            client_ip=client_ip,
            result="success",
            detail=None,
            duration_ms=duration_ms,
        )
        return {"success": True, "service": name, "action": "start", "status": "running"}
    except (ServiceError, Exception) as exc:
        duration_ms = int((time.monotonic() - start_ms) * 1000)
        rate_limiter.record(client_ip)
        audit_logger.log(
            action="start",
            service_name=name,
            client_ip=client_ip,
            result="error",
            detail=str(exc),
            duration_ms=duration_ms,
        )
        raise _service_error_to_http(exc, name) from exc


@app.post("/api/services/{name}/stop")
async def stop_service(
    name: str, client_ip: str = Depends(check_rate_limit)
) -> dict:
    """
    Stop a Windows service.

    Args:
        name: Windows service internal SCM name.
        client_ip: Injected by the rate-limit dependency.

    Returns:
        JSON with success, service, action, status.

    Raises:
        HTTPException: 404/403/409/504/500 on failure.
    """
    start_ms = time.monotonic()
    try:
        await asyncio.to_thread(service_manager.stop_service, name)
        duration_ms = int((time.monotonic() - start_ms) * 1000)
        rate_limiter.record(client_ip)
        audit_logger.log(
            action="stop",
            service_name=name,
            client_ip=client_ip,
            result="success",
            detail=None,
            duration_ms=duration_ms,
        )
        return {"success": True, "service": name, "action": "stop", "status": "stopped"}
    except (ServiceError, Exception) as exc:
        duration_ms = int((time.monotonic() - start_ms) * 1000)
        rate_limiter.record(client_ip)
        audit_logger.log(
            action="stop",
            service_name=name,
            client_ip=client_ip,
            result="error",
            detail=str(exc),
            duration_ms=duration_ms,
        )
        raise _service_error_to_http(exc, name) from exc


@app.post("/api/services/{name}/restart")
async def restart_service(
    name: str, client_ip: str = Depends(check_rate_limit)
) -> dict:
    """
    Restart a Windows service.

    Args:
        name: Windows service internal SCM name.
        client_ip: Injected by the rate-limit dependency.

    Returns:
        JSON with success, service, action, status.

    Raises:
        HTTPException: 404/403/504/500 on failure (409 is never raised for restart).
    """
    start_ms = time.monotonic()
    try:
        await asyncio.to_thread(service_manager.restart_service, name)
        duration_ms = int((time.monotonic() - start_ms) * 1000)
        rate_limiter.record(client_ip)
        audit_logger.log(
            action="restart",
            service_name=name,
            client_ip=client_ip,
            result="success",
            detail=None,
            duration_ms=duration_ms,
        )
        return {"success": True, "service": name, "action": "restart", "status": "running"}
    except (ServiceError, Exception) as exc:
        duration_ms = int((time.monotonic() - start_ms) * 1000)
        rate_limiter.record(client_ip)
        audit_logger.log(
            action="restart",
            service_name=name,
            client_ip=client_ip,
            result="error",
            detail=str(exc),
            duration_ms=duration_ms,
        )
        raise _service_error_to_http(exc, name) from exc


# ---------------------------------------------------------------------------
# Static frontend (must come last so it does not shadow API routes)
# ---------------------------------------------------------------------------

_frontend_dir = str(Path(__file__).parent.parent / "frontend")
if Path(_frontend_dir).exists():
    app.mount("/", StaticFiles(directory=_frontend_dir, html=True), name="frontend")


# ---------------------------------------------------------------------------
# Error mapping helper
# ---------------------------------------------------------------------------


def _service_error_to_http(exc: Exception, service_name: str) -> HTTPException:
    """
    Convert a ServiceError (or unknown exception) into a FastAPI HTTPException.

    Args:
        exc: The caught exception.
        service_name: Name of the service for error messages.

    Returns:
        HTTPException with the appropriate status code and body.
    """
    if isinstance(exc, ServiceNotFoundError):
        return HTTPException(
            status_code=404,
            detail={
                "error": "Service not found",
                "detail": f"Service '{service_name}' is not in the managed service list",
            },
        )
    if isinstance(exc, ServicePermissionError):
        return HTTPException(
            status_code=403,
            detail={
                "error": "Permission denied",
                "detail": str(exc),
            },
        )
    if isinstance(exc, (ServiceAlreadyRunningError, ServiceAlreadyStoppedError)):
        return HTTPException(
            status_code=409,
            detail={
                "error": "Conflict",
                "detail": str(exc),
            },
        )
    if isinstance(exc, ServiceTimeoutError):
        return HTTPException(
            status_code=504,
            detail={
                "error": "Timeout",
                "detail": str(exc),
            },
        )
    return HTTPException(
        status_code=500,
        detail={
            "error": "Internal server error",
            "detail": str(exc),
        },
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run(app, host=config.server.host, port=config.server.port)

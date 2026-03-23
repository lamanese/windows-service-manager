# Windows Service Manager -- Architecture Document

**Version:** 1.0  
**Date:** 2026-02-26  
**Status:** Approved

---

## 1. Component Overview

The application follows a layered architecture with four distinct modules, a single-file frontend, and supporting infrastructure files.

```
┌──────────────────────────────────────────────────────────┐
│                      Browser (Client)                    │
│                    frontend/index.html                   │
└──────────────────┬───────────────────────────────────────┘
                   │ HTTP (JSON + HTML)
                   ▼
┌──────────────────────────────────────────────────────────┐
│                  FastAPI Application                     │
│                    backend/main.py                       │
│                                                          │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────┐  │
│  │ config.py   │  │ audit.py     │  │ rate_limiter.py│  │
│  │ (Config)    │  │ (AuditLogger)│  │ (RateLimiter)  │  │
│  └─────────────┘  └──────────────┘  └────────────────┘  │
│         │                │                               │
│  ┌──────┴──────────────────────────────────────────────┐ │
│  │            service_manager.py                       │ │
│  │            (WindowsServiceManager)                  │ │
│  └─────────────────────┬───────────────────────────────┘ │
└────────────────────────┼─────────────────────────────────┘
                         │ pywin32 API
                         ▼
              ┌─────────────────────┐
              │  Windows Service    │
              │  Control Manager    │
              │  (SCM)              │
              └─────────────────────┘
```

### Module Responsibilities

| Module | File | Responsibility |
|--------|------|----------------|
| **App / Router** | `backend/main.py` | FastAPI application setup, endpoint definitions, dependency injection, static file serving, startup/shutdown lifecycle, CORS and middleware |
| **Service Manager** | `backend/service_manager.py` | Wraps `pywin32` (`win32service`, `win32serviceutil`). Enumerates services, reads status, sends start/stop/restart commands. Applies service filters and exclusions from config |
| **Config** | `backend/config.py` | Loads and validates `config.yaml` via PyYAML. Provides a typed dataclass/Pydantic model with defaults for all fields |
| **Audit Logger** | `backend/audit.py` | Writes JSON Lines entries to `logs/audit.log` using Python `logging.handlers.RotatingFileHandler`. Ensures append-only, rotating log files |
| **Rate Limiter** | `backend/rate_limiter.py` | In-memory per-IP rate limiting for action endpoints (start/stop/restart). Enforces 10 actions per IP per minute |
| **Frontend** | `frontend/index.html` | Single HTML file with embedded JavaScript. Uses Tailwind CSS via CDN. Polls `GET /api/services` every 5 seconds. Sends POST requests for actions. Renders status badges, buttons, toast notifications |

---

## 2. API Contracts

All API endpoints are served under the FastAPI application on the configured host and port (default `0.0.0.0:8080`).

### 2.1 GET /

**Description:** Serves the frontend HTML page.

- **Response:** `200 OK` with `Content-Type: text/html`
- **Body:** Contents of `frontend/index.html`

---

### 2.2 GET /api/services

**Description:** Returns the list of Windows services matching the configured filters, excluding any explicitly excluded services.

**Request:**
- Method: `GET`
- Headers: None required
- Query Parameters: None

**Response (200 OK):**
```json
{
  "services": [
    {
      "name": "MyAppWorker",
      "display_name": "MyApp Background Worker",
      "status": "running",
      "pid": 4821
    },
    {
      "name": "MyAppScheduler",
      "display_name": "MyApp Scheduler Service",
      "status": "stopped",
      "pid": null
    }
  ],
  "timestamp": "2026-02-26T14:23:05.123Z"
}
```

**Field Definitions:**

| Field | Type | Description |
|-------|------|-------------|
| `services` | `array` | List of service objects |
| `services[].name` | `string` | Windows service name (the internal SCM name) |
| `services[].display_name` | `string` | Human-readable display name |
| `services[].status` | `string` | One of: `"running"`, `"stopped"`, `"starting"`, `"stopping"`, `"unknown"` |
| `services[].pid` | `int \| null` | Process ID if running, `null` otherwise |
| `timestamp` | `string` | ISO 8601 timestamp of when the snapshot was taken |

**Error Responses:**

| Status | Condition | Body |
|--------|-----------|------|
| `500` | SCM connection failure or unexpected OS error | `{"error": "Failed to enumerate services", "detail": "<message>"}` |

---

### 2.3 POST /api/services/{name}/start

**Description:** Starts a stopped Windows service.

**Request:**
- Method: `POST`
- Path Parameter: `name` (string) -- the Windows service name (not the display name)
- Headers: `X-Forwarded-For` (optional, set by reverse proxy)
- Body: None

**Response (200 OK):**
```json
{
  "success": true,
  "service": "MyAppWorker",
  "action": "start",
  "status": "running"
}
```

**Error Responses:**

| Status | Condition | Body |
|--------|-----------|------|
| `404` | Service name not in filtered list | `{"error": "Service not found", "detail": "Service 'Foo' is not in the managed service list"}` |
| `409` | Service is already running | `{"error": "Conflict", "detail": "Service 'MyAppWorker' is already running"}` |
| `403` | Insufficient OS permissions to control service | `{"error": "Permission denied", "detail": "Insufficient privileges to start service 'MyAppWorker'"}` |
| `429` | Rate limit exceeded (>10 actions/min for this IP) | `{"error": "Rate limit exceeded", "detail": "Maximum 10 actions per minute. Try again in <N> seconds"}` |
| `500` | Unexpected error during service start | `{"error": "Internal server error", "detail": "<message>"}` |
| `504` | Service did not reach desired state within timeout | `{"error": "Timeout", "detail": "Service 'MyAppWorker' did not reach 'running' state within 30 seconds"}` |

---

### 2.4 POST /api/services/{name}/stop

**Description:** Stops a running Windows service.

**Request:**
- Method: `POST`
- Path Parameter: `name` (string)
- Headers: `X-Forwarded-For` (optional)
- Body: None

**Response (200 OK):**
```json
{
  "success": true,
  "service": "MyAppWorker",
  "action": "stop",
  "status": "stopped"
}
```

**Error Responses:**

| Status | Condition | Body |
|--------|-----------|------|
| `404` | Service name not in filtered list | `{"error": "Service not found", "detail": "Service 'Foo' is not in the managed service list"}` |
| `409` | Service is already stopped | `{"error": "Conflict", "detail": "Service 'MyAppWorker' is already stopped"}` |
| `403` | Insufficient OS permissions | `{"error": "Permission denied", "detail": "Insufficient privileges to stop service 'MyAppWorker'"}` |
| `429` | Rate limit exceeded | `{"error": "Rate limit exceeded", "detail": "Maximum 10 actions per minute. Try again in <N> seconds"}` |
| `500` | Unexpected error | `{"error": "Internal server error", "detail": "<message>"}` |
| `504` | Service did not stop within timeout | `{"error": "Timeout", "detail": "Service 'MyAppWorker' did not reach 'stopped' state within 30 seconds"}` |

---

### 2.5 POST /api/services/{name}/restart

**Description:** Restarts a Windows service. If the service is running, it will be stopped first then started. If the service is stopped, it will simply be started.

**Request:**
- Method: `POST`
- Path Parameter: `name` (string)
- Headers: `X-Forwarded-For` (optional)
- Body: None

**Response (200 OK):**
```json
{
  "success": true,
  "service": "MyAppWorker",
  "action": "restart",
  "status": "running"
}
```

**Error Responses:**

| Status | Condition | Body |
|--------|-----------|------|
| `404` | Service name not in filtered list | `{"error": "Service not found", "detail": "..."}` |
| `403` | Insufficient OS permissions | `{"error": "Permission denied", "detail": "..."}` |
| `429` | Rate limit exceeded | `{"error": "Rate limit exceeded", "detail": "..."}` |
| `500` | Unexpected error during restart | `{"error": "Internal server error", "detail": "..."}` |
| `504` | Service did not reach running state within timeout | `{"error": "Timeout", "detail": "..."}` |

Note: Restart does NOT return `409`. It is always valid to restart a service regardless of its current state.

---

## 3. Windows-Specific Considerations

### 3.1 pywin32 Modules Used

| Module | Usage |
|--------|-------|
| `win32service` | Core module: `OpenSCManager`, `OpenService`, `EnumServicesStatus`, `QueryServiceStatusEx`, `StartService`, `ControlService`, `CloseServiceHandle` |
| `win32serviceutil` | Convenience utilities (optional): `QueryServiceStatus` |
| `win32con` | Windows constants (used indirectly via win32service constants) |
| `pywintypes` | Exception type `pywintypes.error` for catching Windows API errors |

### 3.2 SCM Permissions Required

The application process must run under an account with the following SCM access rights:

| Permission | win32service Constant | Required For |
|------------|----------------------|--------------|
| SC_MANAGER_CONNECT | `win32service.SC_MANAGER_CONNECT` | Connecting to the SCM |
| SC_MANAGER_ENUMERATE_SERVICE | `win32service.SC_MANAGER_ENUMERATE_SERVICE` | Listing services |
| SERVICE_START | `win32service.SERVICE_START` | Starting a service |
| SERVICE_STOP | `win32service.SERVICE_STOP` | Stopping a service |
| SERVICE_QUERY_STATUS | `win32service.SERVICE_QUERY_STATUS` | Reading service status |
| SERVICE_INTERROGATE | `win32service.SERVICE_INTERROGATE` | Querying extended status |

**Recommended approach:** Run the FastAPI application under an account that is a member of the local `Administrators` group, or grant explicit service control permissions via `sc sdset` for each managed service. When deployed via NSSM as a Windows service, the NSSM service should run as `LocalSystem` or a dedicated service account with the permissions above.

### 3.3 Service Status Mapping

The `win32service.QueryServiceStatusEx` function returns a `dwCurrentState` integer. Map these to the API status strings:

| win32service Constant | Integer Value | API Status String | Badge Color |
|----------------------|---------------|-------------------|-------------|
| `SERVICE_RUNNING` | 4 | `"running"` | Green |
| `SERVICE_STOPPED` | 1 | `"stopped"` | Red |
| `SERVICE_START_PENDING` | 2 | `"starting"` | Yellow |
| `SERVICE_STOP_PENDING` | 3 | `"stopping"` | Yellow |
| `SERVICE_CONTINUE_PENDING` | 5 | `"starting"` | Yellow |
| `SERVICE_PAUSE_PENDING` | 6 | `"stopping"` | Yellow |
| `SERVICE_PAUSED` | 7 | `"stopped"` | Red |
| Any other value | -- | `"unknown"` | Grey |

### 3.4 Service Control Codes

| Action | Method | win32service Constant |
|--------|--------|----------------------|
| Start | `win32service.StartService(handle, None)` | N/A (function call) |
| Stop | `win32service.ControlService(handle, ...)` | `win32service.SERVICE_CONTROL_STOP` |

### 3.5 SCM Handle Lifecycle

All SCM and service handles **must** be closed with `win32service.CloseServiceHandle()` in a `finally` block to prevent handle leaks. The `service_manager.py` module must use context managers or explicit try/finally patterns:

```python
scm_handle = win32service.OpenSCManager(None, None, access)
try:
    svc_handle = win32service.OpenService(scm_handle, service_name, svc_access)
    try:
        # ... perform operations ...
    finally:
        win32service.CloseServiceHandle(svc_handle)
finally:
    win32service.CloseServiceHandle(scm_handle)
```

### 3.6 Timeout and Polling for State Transitions

After sending a start or stop command, the service does not transition immediately. The service manager must poll `QueryServiceStatusEx` until the desired state is reached or a timeout occurs:

- **Poll interval:** 500ms
- **Timeout:** 30 seconds
- **If timeout is exceeded:** Return HTTP `504`

### 3.7 Service Enumeration

Use `win32service.EnumServicesStatus` with service type `win32service.SERVICE_WIN32` and state `win32service.SERVICE_STATE_ALL` to get both running and stopped services. Then apply the configured filters (prefix / contains) and exclusions in Python.

---

## 4. Rate Limiting Design

### Strategy: In-Memory Sliding Window with Timestamp List

Rate limiting applies only to **action endpoints** (start, stop, restart) -- not to `GET /api/services` or `GET /`.

### Data Structure

```python
# Module: backend/rate_limiter.py

from collections import defaultdict
import time
import threading

class RateLimiter:
    def __init__(self, max_requests: int = 10, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def is_allowed(self, client_ip: str) -> tuple[bool, int]:
        """
        Returns (allowed: bool, retry_after_seconds: int).
        retry_after_seconds is 0 if allowed.
        """
        ...

    def record(self, client_ip: str) -> None:
        """Record a request for the given IP."""
        ...

    def _cleanup(self, client_ip: str, now: float) -> None:
        """Remove timestamps older than the window."""
        ...
```

### Algorithm

1. On each action request, extract `client_ip` from `X-Forwarded-For` header (first value) or fall back to `request.client.host`.
2. Call `is_allowed(client_ip)`:
   - Acquire lock.
   - Remove all timestamps for this IP older than `now - window_seconds`.
   - If the remaining count >= `max_requests`, return `(False, retry_after)` where `retry_after = ceil(oldest_remaining_timestamp + window_seconds - now)`.
   - Otherwise return `(True, 0)`.
3. If not allowed, return HTTP `429` immediately with `Retry-After` header.
4. If allowed, proceed with the action. After the action completes (success or failure), call `record(client_ip)` to append `time.time()`.

### Periodic Cleanup

A background task runs every 5 minutes to remove stale IP entries (IPs with no timestamps in the last 5 minutes) to prevent unbounded memory growth.

### FastAPI Integration

Rate limiting is implemented as a **dependency** injected into the three action endpoints:

```python
async def check_rate_limit(request: Request):
    client_ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    if not client_ip:
        client_ip = request.client.host
    allowed, retry_after = rate_limiter.is_allowed(client_ip)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Maximum {rate_limiter.max_requests} actions per minute. Try again in {retry_after} seconds",
            headers={"Retry-After": str(retry_after)}
        )
```

---

## 5. Config Schema

### File: `config.yaml`

```yaml
server:
  host: "0.0.0.0"        # string, default: "0.0.0.0"
  port: 8080              # int, default: 8080

logging:
  audit_log: "logs/audit.log"  # string (file path), default: "logs/audit.log"
  max_size_mb: 10              # int, default: 10
  backup_count: 5              # int, default: 5

service_filters:               # list of filter objects, default: [] (matches ALL services)
  - type: "prefix"             # string, one of: "prefix", "contains"
    value: "MyApp"             # string, the filter value

service_exclude:               # list of strings (service names to exclude), default: []
  - "MyAppUninstaller"

rate_limit:
  max_requests: 10             # int, default: 10
  window_seconds: 60           # int, default: 60

service_control:
  timeout_seconds: 30          # int, default: 30
  poll_interval_ms: 500        # int, default: 500
```

### Pydantic Model

```python
# backend/config.py

from pydantic import BaseModel, Field

class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8080

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

class AppConfig(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    service_filters: list[ServiceFilter] = Field(default_factory=list)
    service_exclude: list[str] = Field(default_factory=list)
    rate_limit: RateLimitConfig = Field(default_factory=RateLimitConfig)
    service_control: ServiceControlConfig = Field(default_factory=ServiceControlConfig)
```

### Loading Logic

1. Look for `config.yaml` in the application root directory.
2. If the file does not exist, use all defaults.
3. If the file exists but is malformed YAML, raise a startup error with a descriptive message.
4. Validate using Pydantic. Invalid field types cause a startup error.
5. The loaded config is stored as a module-level singleton, accessed by other modules via `from config import get_config`.

---

## 6. Audit Log Schema

### Format: JSON Lines (one JSON object per line)

### File: `logs/audit.log`

### Rotation: `RotatingFileHandler` with `maxBytes = max_size_mb * 1024 * 1024` and `backupCount = backup_count`

### Schema per Line

```json
{
  "timestamp": "2026-02-26T14:23:05.123456+01:00",
  "action": "restart",
  "service_name": "MyAppWorker",
  "client_ip": "10.0.1.42",
  "result": "success",
  "detail": null,
  "duration_ms": 3245
}
```

### Field Definitions

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `timestamp` | `string` | Yes | ISO 8601 with timezone, generated via `datetime.now(timezone.utc).isoformat()` |
| `action` | `string` | Yes | One of: `"start"`, `"stop"`, `"restart"` |
| `service_name` | `string` | Yes | The Windows service name (internal SCM name) |
| `client_ip` | `string` | Yes | Client IP, extracted from `X-Forwarded-For` header (first value) or `request.client.host` |
| `result` | `string` | Yes | One of: `"success"`, `"error"` |
| `detail` | `string \| null` | Yes | Error message if `result` is `"error"`, `null` on success |
| `duration_ms` | `int` | Yes | Duration of the action in milliseconds (from request to final status confirmation) |

### Audit Logger Implementation

```python
# backend/audit.py

import json
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime, timezone

class AuditLogger:
    def __init__(self, log_path: str, max_bytes: int, backup_count: int):
        self._logger = logging.getLogger("audit")
        self._logger.setLevel(logging.INFO)
        handler = RotatingFileHandler(
            log_path, maxBytes=max_bytes, backupCount=backup_count
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
        self._logger.addHandler(handler)

    def log(self, action: str, service_name: str, client_ip: str,
            result: str, detail: str | None, duration_ms: int) -> None:
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
```

---

## 7. Error Handling

### HTTP Status Code Matrix

| Status Code | Condition | When Returned |
|-------------|-----------|---------------|
| **200** | Action completed successfully | All endpoints on success |
| **404** | Service not found in the managed list | Action endpoints when `{name}` does not match any filtered service |
| **403** | OS-level permission denied | Action endpoints when `pywintypes.error` indicates access denied (winerror 5 / `ERROR_ACCESS_DENIED`) |
| **409** | Service already in desired state | `start` when already running; `stop` when already stopped. NOT returned for `restart` |
| **429** | Rate limit exceeded | Action endpoints when IP exceeds 10 actions/minute |
| **500** | Unexpected internal error | Any endpoint on unhandled exceptions, SCM connection failures |
| **504** | Timeout waiting for state transition | Action endpoints when service does not reach target state within `timeout_seconds` |

### Error Response Shape

All error responses follow a consistent JSON structure:

```json
{
  "error": "<short error category>",
  "detail": "<human-readable description>"
}
```

### pywintypes.error Mapping

The `pywintypes.error` exception contains a tuple `(winerror, funcname, strerror)`. Map `winerror` values:

| winerror | Windows Name | HTTP Status | error String |
|----------|-------------|-------------|--------------|
| 5 | `ERROR_ACCESS_DENIED` | 403 | `"Permission denied"` |
| 1060 | `ERROR_SERVICE_DOES_NOT_EXIST` | 404 | `"Service not found"` |
| 1056 | `ERROR_SERVICE_ALREADY_RUNNING` | 409 | `"Conflict"` |
| 1062 | `ERROR_SERVICE_NOT_ACTIVE` | 409 | `"Conflict"` |
| 1053 | `ERROR_SERVICE_REQUEST_TIMEOUT` | 504 | `"Timeout"` |
| Other | -- | 500 | `"Internal server error"` |

### Global Exception Handler

Register a global exception handler in FastAPI to catch unhandled `pywintypes.error` and any other exceptions, ensuring no stack traces leak to the client:

```python
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    # Log full traceback to application log (not audit log)
    logger.exception("Unhandled exception")
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "detail": "An unexpected error occurred"}
    )
```

---

## 8. Project Directory Layout

```
windows-service-manager/
├── backend/
│   ├── main.py                 # FastAPI app, endpoint definitions, middleware, lifespan
│   ├── service_manager.py      # WindowsServiceManager class (pywin32 wrapper)
│   ├── config.py               # AppConfig Pydantic model, load_config(), get_config()
│   ├── audit.py                # AuditLogger class (JSON Lines + RotatingFileHandler)
│   ├── rate_limiter.py         # RateLimiter class (in-memory sliding window)
│   └── requirements.txt        # Python dependencies
├── frontend/
│   └── index.html              # Single-file frontend (HTML + Tailwind CSS CDN + JS)
├── docs/
│   └── ARCHITECTURE.md         # This document
├── config.yaml                 # Application configuration
├── logs/                       # Audit log directory (created at startup if missing)
│   └── .gitkeep
├── start.bat                   # Manual start script: cd backend && python main.py
└── README.md                   # Setup and deployment instructions
```

### File Purposes

| File | Owner Module | Description |
|------|-------------|-------------|
| `backend/main.py` | App | Entry point. Initializes FastAPI, mounts static frontend, defines all 5 endpoints, wires up config/audit/rate-limiter/service-manager as dependencies |
| `backend/service_manager.py` | Service | Contains `WindowsServiceManager` with methods: `list_services() -> list[ServiceInfo]`, `start_service(name) -> ServiceInfo`, `stop_service(name) -> ServiceInfo`, `restart_service(name) -> ServiceInfo`. All methods raise domain exceptions mapped to HTTP errors in `main.py` |
| `backend/config.py` | Config | Pydantic models for config schema. `load_config(path: str) -> AppConfig` loads and validates YAML. `get_config() -> AppConfig` returns cached singleton |
| `backend/audit.py` | Logging | `AuditLogger` class wrapping `RotatingFileHandler`. Single `log()` method writes JSON Lines |
| `backend/rate_limiter.py` | Security | `RateLimiter` class with `is_allowed()` and `record()`. Thread-safe via `threading.Lock` |
| `backend/requirements.txt` | Build | Lists: `fastapi`, `uvicorn[standard]`, `pywin32`, `pyyaml`, `pydantic` |
| `frontend/index.html` | UI | Complete SPA in one file. Fetches `/api/services` every 5s. Renders service table with status badges and action buttons. Shows toast notifications for action results |
| `config.yaml` | Config | User-editable YAML configuration |
| `start.bat` | Ops | `cd /d %~dp0\backend && python main.py` |
| `README.md` | Docs | Installation, configuration, deployment via NSSM |

### requirements.txt Contents

```
fastapi>=0.110.0,<1.0.0
uvicorn[standard]>=0.29.0,<1.0.0
pywin32>=306
pyyaml>=6.0,<7.0
pydantic>=2.0,<3.0
```

---

## ADR-001: No Authentication in MVP

**Context:** The spec explicitly states no auth in MVP. Access is controlled via network segmentation and reverse proxy.

**Decision:** No authentication or authorization middleware is included. All endpoints are publicly accessible on the bound interface.

**Consequences:**
- The application MUST be deployed behind a reverse proxy (e.g., IIS, nginx) that handles HTTPS termination and network-level access control.
- Audit logging with client IP serves as the accountability mechanism.
- A future iteration can add API key or basic auth middleware without changing the endpoint contracts.

---

## ADR-002: Synchronous pywin32 Calls in Async Framework

**Context:** FastAPI is async, but pywin32 calls are synchronous and blocking. Service state transitions (polling) can take up to 30 seconds.

**Decision:** Run all `service_manager.py` methods in a thread pool executor via `asyncio.to_thread()` to prevent blocking the event loop.

**Consequences:**
- Action endpoints use `await asyncio.to_thread(service_manager.start_service, name)`.
- The thread pool size limits concurrent service operations. The default executor is sufficient for expected load.
- The `RateLimiter` uses `threading.Lock` because it is accessed from both the async context (via dependency) and potentially from the thread pool.

---

## ADR-003: In-Memory Rate Limiting

**Context:** The spec requires rate limiting at 10 actions per IP per minute. The application runs as a single process.

**Decision:** Use a simple in-memory dict with timestamp lists. No external store (Redis, etc.).

**Consequences:**
- Rate limit state is lost on application restart. This is acceptable for the MVP.
- Memory usage is bounded because the cleanup task removes stale entries.
- If the application is ever scaled to multiple processes, this approach must be replaced with a shared store.

# Windows Service Manager

## Overview

Windows Service Manager is a lightweight web application for managing Windows services through a browser. The backend is a FastAPI server (Python) that communicates with the Windows Service Control Manager (SCM) via the pywin32 API. The frontend is a single HTML file with embedded JavaScript that displays all services in a table and provides start, stop, and restart actions. The application is designed for administrators and operators who need to control services on Windows servers without Remote Desktop access.

---

## Prerequisites

- **Operating System:** Windows 10 / Windows Server 2016 or newer
- **Python:** 3.9 or newer (64-bit recommended)
- **pywin32:** Installed automatically via `requirements.txt`; must run under an account with access to the Service Control Manager
- **Administrator privileges:** Required for starting/stopping/restarting Windows services
- **Network:** The server must be reachable from the administrator's browser

---

## Installation

### 1. Copy repository/files

Copy the project directory to the target Windows server, for example:

```
C:\Tools\windows-service-manager\
```

Expected directory structure:

```
windows-service-manager\
├── backend\
│   ├── main.py
│   ├── service_manager.py
│   ├── config.py
│   ├── audit.py
│   ├── rate_limiter.py
│   ├── win_service.py
│   └── requirements.txt
├── frontend\
│   └── index.html
├── docs\
│   └── ARCHITECTURE.md
├── config.yaml
├── logs\
│   └── .gitkeep
├── start.bat
├── install-service.bat
├── uninstall-service.bat
└── README.md
```

### 2. Install dependencies

Open a command prompt **as Administrator** and run:

```bat
cd C:\Tools\windows-service-manager
pip install -r backend\requirements.txt
```

### 3. Configure

Edit `config.yaml` in the project root. Key settings:

**Service filters** define which services are displayed. Without filters, **all** Win32 services are shown.

```yaml
service_filters:
  # Show all services whose name starts with "MyApp"
  - type: "prefix"
    value: "MyApp"

  # Show all services whose name contains "Worker"
  - type: "contains"
    value: "Worker"
```

Filter types:

| Type | Description | Example |
|------|-------------|---------|
| `prefix` | Name starts with the given value (case-insensitive) | `"MyApp"` matches `MyAppWorker`, `myappscheduler` |
| `contains` | Name contains the given value (case-insensitive) | `"Worker"` matches `MyAppWorker`, `BackgroundWorker` |

Multiple filters are combined with **OR** logic: a service is shown if it matches at least one filter.

**Exclude list** prevents specific services from being shown even if they match a filter:

```yaml
service_exclude:
  - "MyAppUninstaller"
  - "MyAppSetup"
```

### 4. Manual start (testing)

```bat
start.bat
```

Or directly:

```bat
cd C:\Tools\windows-service-manager
python backend\main.py
```

The web interface is then available at `http://localhost:8080` (or the port configured in `config.yaml`).

### 5. Install as a Windows Service

The application can register itself as a native Windows Service — no third-party tools required.

```bat
:: Run as Administrator
install-service.bat
```

Or manually:

```bat
python backend\win_service.py install
python backend\win_service.py start
```

The service appears in `services.msc` as **Windows Service Manager**.

To uninstall:

```bat
uninstall-service.bat
```

Or manually:

```bat
python backend\win_service.py stop
python backend\win_service.py remove
```

---

## Configuration (config.yaml)

The configuration file is located in the project root (`config.yaml`). All fields are optional and have sensible defaults. If the file is missing, all defaults are used.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `server.host` | string | `"0.0.0.0"` | Bind address. `0.0.0.0` = all network interfaces. |
| `server.port` | int | `8080` | TCP port the server listens on. |
| `logging.audit_log` | string | `"logs/audit.log"` | Path to the audit log file (relative to project root or absolute). |
| `logging.max_size_mb` | int | `10` | Maximum audit log file size in MB before rotation. |
| `logging.backup_count` | int | `5` | Number of rotated backup files to keep. |
| `service_filters` | list | `[]` (all) | List of filter objects (`type` + `value`). Empty = all services. |
| `service_filters[].type` | string | - | `"prefix"` or `"contains"`. |
| `service_filters[].value` | string | - | The filter value (case-insensitive). |
| `service_exclude` | list of strings | `[]` | Service names that are never shown, even if a filter matches. |
| `rate_limit.max_requests` | int | `10` | Maximum actions (start/stop/restart) per IP per time window. |
| `rate_limit.window_seconds` | int | `60` | Length of the rate limit time window in seconds. |
| `service_control.timeout_seconds` | int | `30` | Timeout in seconds to wait for a service to reach its target state. |
| `service_control.poll_interval_ms` | int | `500` | Interval in milliseconds between status polls during a state transition. |

---

## API Reference

All endpoints are available at the configured host and port. Error responses always follow the schema `{"error": "<category>", "detail": "<description>"}`.

| Method | Path | Description | Example Response (200) |
|--------|------|-------------|----------------------|
| `GET` | `/` | Serves the frontend HTML page. | HTML document |
| `GET` | `/api/services` | Returns all filtered Windows services with status. | `{"services": [{"name": "MyAppWorker", "display_name": "MyApp Background Worker", "status": "running", "pid": 4821}], "timestamp": "2026-02-26T14:23:05.123456+00:00"}` |
| `POST` | `/api/services/{name}/start` | Starts the service with the internal SCM name `{name}`. | `{"success": true, "service": "MyAppWorker", "action": "start", "status": "running"}` |
| `POST` | `/api/services/{name}/stop` | Stops the service with the internal SCM name `{name}`. | `{"success": true, "service": "MyAppWorker", "action": "stop", "status": "stopped"}` |
| `POST` | `/api/services/{name}/restart` | Restarts the service (stop + start; if already stopped: start only). | `{"success": true, "service": "MyAppWorker", "action": "restart", "status": "running"}` |

**Possible error codes for action endpoints:**

| HTTP Status | Meaning |
|------------|---------|
| `403` | Insufficient privileges to control the service |
| `404` | Service not in the filtered list |
| `409` | Service already in target state (start/stop only, not restart) |
| `429` | Rate limit exceeded; `Retry-After` header indicates wait time |
| `500` | Unexpected internal error |
| `504` | Service did not reach target state within the timeout |

---

## Audit Log

All actions (start, stop, restart) are logged in an audit log file using **JSON Lines** format (one JSON object per line).

**Location:** `logs/audit.log` (configurable via `logging.audit_log`)

**Rotation:** Automatic via `RotatingFileHandler`. When `max_size_mb` is reached, the file is rotated; up to `backup_count` backup files are kept (e.g., `audit.log.1`, `audit.log.2`).

**Example entry:**

```json
{"timestamp": "2026-02-26T14:23:05.123456+00:00", "action": "restart", "service_name": "MyAppWorker", "client_ip": "10.0.1.42", "result": "success", "detail": null, "duration_ms": 3245}
```

**Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `timestamp` | string | ISO 8601 with timezone (UTC) |
| `action` | string | `"start"`, `"stop"`, or `"restart"` |
| `service_name` | string | Internal SCM name of the service |
| `client_ip` | string | Client IP address (from `X-Forwarded-For` or direct connection) |
| `result` | string | `"success"` or `"error"` |
| `detail` | string \| null | Error message on `"error"`, otherwise `null` |
| `duration_ms` | int | Duration of the action in milliseconds |

---

## Security Notes

- **No authentication in MVP:** The application has no login. Access must be secured via network segmentation (VPN, firewall) or a reverse proxy.
- **Rate limiting:** Action endpoints are limited to 10 actions per IP per minute to mitigate abuse.
- **Service filters:** Only explicitly configured services are accessible via the API. System services not in the filtered list cannot be controlled.
- **No direct HTTPS:** The application binds on HTTP. HTTPS termination must be handled by a reverse proxy (e.g., nginx, IIS, Caddy) in front of the Service Manager.
- **Audit log:** All actions are logged with client IP and serve as an accountability mechanism.

---

## Project Structure

```
windows-service-manager/
├── backend/
│   ├── main.py                 # FastAPI app, endpoints, middleware, lifespan
│   ├── service_manager.py      # WindowsServiceManager (pywin32 wrapper)
│   ├── config.py               # AppConfig (Pydantic), load_config(), get_config()
│   ├── audit.py                # AuditLogger (JSON Lines + RotatingFileHandler)
│   ├── rate_limiter.py         # RateLimiter (in-memory sliding window)
│   ├── win_service.py          # Native Windows Service wrapper (pywin32)
│   └── requirements.txt        # Python dependencies
├── frontend/
│   └── index.html              # Single-file frontend (HTML + Tailwind CSS CDN + JS)
├── docs/
│   └── ARCHITECTURE.md         # Architecture documentation
├── config.yaml                 # Application configuration (editable)
├── logs/                       # Audit log directory (created on startup)
│   └── .gitkeep
├── start.bat                   # Manual start script for testing
├── install-service.bat         # Install as Windows Service
├── uninstall-service.bat       # Uninstall Windows Service
└── README.md                   # This file
```

---

## Running Tests

```bat
cd C:\Tools\windows-service-manager
pytest backend\tests\
```

For verbose output:

```bat
pytest backend\tests\ -v --tb=short
```

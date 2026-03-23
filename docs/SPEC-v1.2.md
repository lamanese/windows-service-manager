# Windows Service Manager v1.2 -- Technical Specification

**Version:** 1.2  
**Date:** 2026-02-27  
**Status:** Draft  
**Authors:** Architect Agent  
**Depends on:** v1.0 (current production baseline)

---

## Table of Contents

1. [Overview](#1-overview)
2. [Scope and Goals](#2-scope-and-goals)
3. [Backward Compatibility](#3-backward-compatibility)
4. [Backend Changes](#4-backend-changes)
   - 4.1 [New API Response Fields](#41-new-api-response-fields)
   - 4.2 [win32service.QueryServiceConfig() Integration](#42-win32servicequeryserviceconfig-integration)
   - 4.3 [psutil Port Detection Strategy](#43-psutil-port-detection-strategy)
   - 4.4 [Updated list_services() Flow](#44-updated-list_services-flow)
   - 4.5 [Error Handling Table](#45-error-handling-table)
   - 4.6 [Dependency Changes](#46-dependency-changes)
5. [Frontend Changes](#5-frontend-changes)
   - 5.1 [Optional Column Toggles](#51-optional-column-toggles)
   - 5.2 [Filter Bar](#52-filter-bar)
   - 5.3 [Session Persistence](#53-session-persistence)
   - 5.4 [UI Layout (Updated)](#54-ui-layout-updated)
6. [API Contract (v1.2)](#6-api-contract-v12)
7. [Architecture Diagram](#7-architecture-diagram)
8. [Testing Requirements](#8-testing-requirements)
9. [Migration Notes](#9-migration-notes)

---

## 1. Overview

v1.2 extends the Windows Service Manager with two user-facing features:

- **Optional Columns:** Three new data fields per service (`startup_type`, `logon_as`, `ports`) exposed via the API and rendered as togglable table columns in the frontend.
- **Filter Bar:** A client-side filter bar with a text search input and two dropdown filters, enabling users to narrow the service list without backend round-trips.

Both features are purely additive. No existing API fields, endpoints, or behaviors are modified.

---

## 2. Scope and Goals

| Goal | Description |
|------|-------------|
| **G1** | Expose service startup type (Automatic / Manual / Disabled / Boot / System) in the API |
| **G2** | Expose the "Log On As" account name for each service in the API |
| **G3** | Expose listening TCP ports for running services via psutil |
| **G4** | Allow users to toggle visibility of the three new columns in the UI |
| **G5** | Provide a filter bar (text search + status dropdown + startup-type dropdown) with AND logic |
| **G6** | Persist column visibility and filter state within the browser session (JS state, no localStorage) |
| **G7** | Maintain full backward compatibility with v1.0 API consumers |

### Out of Scope

- WebSocket push notifications
- Persistent user preferences (localStorage / cookies)
- Backend-side filtering for the new fields
- Authentication or authorization changes

---

## 3. Backward Compatibility

All changes in v1.2 are **strictly additive**:

| Aspect | v1.0 | v1.2 | Breaking? |
|--------|------|------|-----------|
| `GET /api/services` response fields per service | `name`, `display_name`, `status`, `pid` | + `startup_type`, `logon_as`, `ports` | No -- new fields only |
| `POST` action endpoints | unchanged | unchanged | No |
| Frontend HTML structure | Single table with 3 columns | Same table + optional columns + filter bar | No -- progressive enhancement |
| config.yaml | unchanged | unchanged | No |
| requirements.txt | pywin32, fastapi, etc. | + `psutil` (new optional dependency) | No -- additive |

Existing API consumers that do not read the new fields will continue to work without modification.

---

## 4. Backend Changes

### 4.1 New API Response Fields

Three new fields are added to each service dict returned by `ServiceManager.list_services()`:

| Field | Type | Description |
|-------|------|-------------|
| `startup_type` | `str \| null` | Human-readable startup type: `"Automatic"`, `"Manual"`, `"Disabled"`, `"Boot"`, `"System"`, or `"Unknown"`. `null` if the config query fails. |
| `logon_as` | `str \| null` | The account under which the service runs (e.g., `"LocalSystem"`, `"NT AUTHORITY\\NetworkService"`, `".\myuser"`). `null` if the config query fails. |
| `ports` | `list[int] \| null` | Sorted list of unique TCP LISTEN ports for running services. Empty list `[]` if the service is running but has no listening ports (or on AccessDenied). `null` only when psutil is not installed or unavailable. |

### 4.2 win32service.QueryServiceConfig() Integration

The `win32service.QueryServiceConfig()` function returns a tuple. We use the following indexed positions:

| Index | Key (logical name) | Win32 Type | Usage |
|-------|---------------------|-----------|-------|
| 1 | `StartType` | `DWORD` | Maps to human-readable string (see mapping table) |
| 7 | `ServiceStartName` | `LPCTSTR` | Used directly as `logon_as` value |

**StartType Integer-to-String Mapping:**

| Integer Value | Win32 Constant | String Value |
|---------------|----------------|--------------|
| 0 | `SERVICE_BOOT_START` | `"Boot"` |
| 1 | `SERVICE_SYSTEM_START` | `"System"` |
| 2 | `SERVICE_AUTO_START` | `"Automatic"` |
| 3 | `SERVICE_DEMAND_START` | `"Manual"` |
| 4 | `SERVICE_DISABLED` | `"Disabled"` |

Any other value maps to `"Unknown"`.

**Implementation strategy in `service_manager.py`:**

```python
_STARTUP_TYPE_MAP: dict[int, str] = {
    0: "Boot",
    1: "System",
    2: "Automatic",
    3: "Manual",
    4: "Disabled",
}

def _query_service_config(scm_handle, service_name: str) -> tuple[str | None, str | None]:
    """
    Query startup type and logon account for a single service.

    Opens the service with SERVICE_QUERY_CONFIG access, calls
    QueryServiceConfig(), and extracts StartType (index 1) and
    ServiceStartName (index 7).

    Returns:
        (startup_type, logon_as) -- either may be None on failure.
    """
    try:
        svc_handle = win32service.OpenService(
            scm_handle,
            service_name,
            win32service.SERVICE_QUERY_CONFIG,
        )
        try:
            cfg = win32service.QueryServiceConfig(svc_handle)
            start_type_int = cfg[1]
            service_start_name = cfg[7]
            startup_type = _STARTUP_TYPE_MAP.get(start_type_int, "Unknown")
            logon_as = service_start_name or None
            return startup_type, logon_as
        finally:
            win32service.CloseServiceHandle(svc_handle)
    except Exception:
        return None, None
```

The SCM handle opened in `list_services()` (with `SC_MANAGER_CONNECT | SC_MANAGER_ENUMERATE_SERVICE`) is reused for the config queries to avoid opening a new SCM handle per service. The service-level handle requires `SERVICE_QUERY_CONFIG` access.

### 4.3 psutil Port Detection Strategy

**Dependency:** `psutil` (added to `requirements.txt`).

**Import pattern:** Conditional import at module level, matching the existing pywin32 pattern:

```python
try:
    import psutil
    _PSUTIL_AVAILABLE = True
except ImportError:
    psutil = None
    _PSUTIL_AVAILABLE = False
```

**Port detection algorithm:**

```python
def _get_listening_ports(pid: int | None) -> list[int] | None:
    """
    Return sorted unique TCP LISTEN ports for a given process ID.

    Args:
        pid: The service process ID. None if the service is not running.

    Returns:
        - None if psutil is unavailable (_PSUTIL_AVAILABLE is False).
        - [] (empty list) if:
            - pid is None (service not running)
            - pid is valid but no TCP LISTEN connections found
            - AccessDenied or any other exception during query
        - list[int] of sorted unique port numbers otherwise.
    """
    if not _PSUTIL_AVAILABLE:
        return None

    if pid is None:
        return []

    try:
        connections = psutil.net_connections(kind='tcp')
        ports = sorted({
            conn.laddr.port
            for conn in connections
            if conn.pid == pid and conn.status == 'LISTEN'
        })
        return ports
    except (psutil.AccessDenied, Exception):
        return []
```

**Key design decisions:**

1. We use `psutil.net_connections(kind='tcp')` (system-wide) rather than `psutil.Process(pid).connections()` because the latter requires per-process access rights that are often restricted for system services. The system-wide call retrieves all connections once and we filter by PID in Python, which is both more reliable and more efficient when querying many services (one syscall instead of N).

2. The fallback on any exception is `[]` (empty list), not `null`. This distinguishes "psutil is available but we could not determine ports" from "psutil is not installed at all."

3. For services that are not running (`pid is None`), we return `[]` because there is no process to query.

### 4.4 Updated list_services() Flow

The enhanced `list_services()` method performs the following steps:

```
1. Open SCM handle (SC_MANAGER_CONNECT | SC_MANAGER_ENUMERATE_SERVICE)
2. EnumServicesStatus() -> raw service list
3. For each service in the raw list:
   a. Extract name, display_name, status, pid (existing logic)
   b. Call _query_service_config(scm_handle, name) -> (startup_type, logon_as)
   c. Call _get_listening_ports(pid) -> ports
   d. Append all 7 fields to the result dict
4. Close SCM handle
5. Return result list
```

**Performance note:** The SCM handle is opened once and reused for all per-service `QueryServiceConfig` calls. The `psutil.net_connections()` call is made once outside the loop and the result is filtered per-service by PID inside the loop (optimization for large service lists):

```python
# Optimization: single psutil call, reuse across all services
if _PSUTIL_AVAILABLE:
    try:
        all_connections = psutil.net_connections(kind='tcp')
    except Exception:
        all_connections = None
else:
    all_connections = None

# Inside the per-service loop:
if all_connections is None and not _PSUTIL_AVAILABLE:
    ports = None
elif all_connections is None:
    ports = []
else:
    ports = sorted({
        conn.laddr.port
        for conn in all_connections
        if conn.pid == pid and conn.status == 'LISTEN'
    }) if pid else []
```

### 4.5 Error Handling Table

| Field | Condition | Value | Type |
|-------|-----------|-------|------|
| `startup_type` | Config query succeeds, known StartType int | `"Automatic"`, `"Manual"`, `"Disabled"`, `"Boot"`, `"System"` | `str` |
| `startup_type` | Config query succeeds, unknown StartType int | `"Unknown"` | `str` |
| `startup_type` | Config query fails (AccessDenied, service handle error, any exception) | `null` | `null` |
| `logon_as` | Config query succeeds, ServiceStartName is non-empty | The account string (e.g., `"LocalSystem"`) | `str` |
| `logon_as` | Config query succeeds, ServiceStartName is empty string | `null` | `null` |
| `logon_as` | Config query fails (any exception) | `null` | `null` |
| `ports` | psutil unavailable (`_PSUTIL_AVAILABLE is False`) | `null` | `null` |
| `ports` | psutil available, service not running (`pid is None`) | `[]` | `list` |
| `ports` | psutil available, service running, no LISTEN ports found | `[]` | `list` |
| `ports` | psutil available, service running, LISTEN ports found | `[80, 443, 8080]` (sorted, unique) | `list[int]` |
| `ports` | psutil available, `net_connections()` raises AccessDenied | `[]` | `list` |
| `ports` | psutil available, `net_connections()` raises any other exception | `[]` | `list` |

### 4.6 Dependency Changes

**requirements.txt** -- add:

```
psutil>=5.9.0
```

`psutil` is treated as an optional-but-expected dependency. The backend functions correctly without it, but `ports` will always be `null`.

---

## 5. Frontend Changes

### 5.1 Optional Column Toggles

Three new columns are added to the service table, each hidden by default and controlled by a checkbox toggle:

| Column Header | Data Field | Default Visibility |
|---------------|------------|--------------------|
| Starttyp | `startup_type` | Hidden |
| Anmeldung | `logon_as` | Hidden |
| Ports | `ports` | Hidden |

**Toggle UI:**

A row of labeled checkboxes is placed between the header bar and the table:

```html
<div id="column-toggles" class="...">
  <label><input type="checkbox" id="col-startup-type"> Starttyp</label>
  <label><input type="checkbox" id="col-logon-as"> Anmeldung</label>
  <label><input type="checkbox" id="col-ports"> Ports</label>
</div>
```

**Behavior:**

- Checking a box immediately shows the corresponding `<th>` and all `<td>` cells in that column.
- Unchecking hides them.
- Column visibility state is stored in a JS object (`columnVisibility`) and consulted during `renderServices()`.
- No localStorage or cookies -- state resets on page reload.

**Rendering logic for cell content:**

| Field | `null` | `[]` | Value |
|-------|--------|------|-------|
| `startup_type` | `"--"` (gray text) | n/a | Display the string directly |
| `logon_as` | `"--"` (gray text) | n/a | Display the string directly |
| `ports` | `"n/a"` (gray text, with title="psutil nicht verfuegbar") | `"–"` (dash, meaning no ports) | Comma-separated list, e.g., `"80, 443, 8080"` |

### 5.2 Filter Bar

A filter bar is placed between the column toggles and the table. It contains three controls:

| Control | Type | Placeholder / Label | Filters On |
|---------|------|---------------------|------------|
| Text search | `<input type="text">` | `"Dienst suchen..."` | `name`, `display_name` (case-insensitive substring match) |
| Status dropdown | `<select>` | `"Alle Status"` | `status` field (exact match) |
| Startup-type dropdown | `<select>` | `"Alle Starttypen"` | `startup_type` field (exact match) |

**Dropdown options:**

Status dropdown:
- `""` -- Alle Status (no filter)
- `"running"` -- Running
- `"stopped"` -- Stopped
- `"starting"` -- Starting
- `"stopping"` -- Stopping

Startup-type dropdown:
- `""` -- Alle Starttypen (no filter)
- `"Automatic"` -- Automatic
- `"Manual"` -- Manual
- `"Disabled"` -- Disabled
- `"Boot"` -- Boot
- `"System"` -- System

**Filter logic:**

All three filters are combined with **AND** logic. A service is displayed only if it matches ALL active filters:

```javascript
function applyFilters(services) {
    const textFilter = filterState.text.toLowerCase();
    const statusFilter = filterState.status;
    const startupFilter = filterState.startupType;

    return services.filter(svc => {
        // Text search: match name or display_name
        if (textFilter) {
            const matchesText =
                svc.name.toLowerCase().includes(textFilter) ||
                svc.display_name.toLowerCase().includes(textFilter);
            if (!matchesText) return false;
        }

        // Status dropdown: exact match
        if (statusFilter && svc.status !== statusFilter) {
            return false;
        }

        // Startup-type dropdown: exact match
        if (startupFilter && svc.startup_type !== startupFilter) {
            return false;
        }

        return true;
    });
}
```

**Important:** Filtering is performed entirely client-side on `lastServices`. No backend changes are required for the filter bar.

### 5.3 Session Persistence

Both column visibility and filter state are kept in plain JavaScript variables:

```javascript
// Column visibility state (session-only, resets on reload)
const columnVisibility = {
    startupType: false,
    logonAs: false,
    ports: false,
};

// Filter state (session-only, resets on reload)
const filterState = {
    text: '',
    status: '',
    startupType: '',
};
```

Event listeners on the checkboxes and filter inputs update these objects and trigger a re-render via `renderServices(lastServices)`.

No `localStorage`, `sessionStorage`, or cookies are used. State lives only for the lifetime of the current page session.

### 5.4 UI Layout (Updated)

```
┌─────────────────────────────────────────────────────────────────┐
│  Service Manager                                [Refresh]       │
│  Stand: 14:23:05                                                │
├─────────────────────────────────────────────────────────────────┤
│  Spalten: [ ] Starttyp  [ ] Anmeldung  [ ] Ports               │
├─────────────────────────────────────────────────────────────────┤
│  [  Dienst suchen...        ] [Alle Status ▼] [Alle Starttyp ▼]│
├─────────────────────────────────────────────────────────────────┤
│  Dienst         | Status   | (Starttyp) | (Anmeldung) | (Ports)│  Aktionen  │
├─────────────────────────────────────────────────────────────────┤
│  MyApp Worker   | Running  | Automatic  | LocalSystem | 8080   │  [>][#][R] │
│  MyApp Sched    | Stopped  | Manual     | .\svcuser   | --     │  [>][#][R] │
│  MyApp API      | Running  | Automatic  | LocalSystem | 80,443 │  [>][#][R] │
└─────────────────────────────────────────────────────────────────┘
```

Columns marked with `( )` are only visible when the corresponding checkbox is checked. The `Aktionen` column always remains the rightmost column.

---

## 6. API Contract (v1.2)

### GET /api/services -- Response

```json
{
  "services": [
    {
      "name": "MyAppWorker",
      "display_name": "MyApp Background Worker",
      "status": "running",
      "pid": 4821,
      "startup_type": "Automatic",
      "logon_as": "LocalSystem",
      "ports": [8080]
    },
    {
      "name": "MyAppScheduler",
      "display_name": "MyApp Scheduler Service",
      "status": "stopped",
      "pid": null,
      "startup_type": "Manual",
      "logon_as": ".\\svcuser",
      "ports": []
    },
    {
      "name": "MyAppLegacy",
      "display_name": "MyApp Legacy Bridge",
      "status": "running",
      "pid": 1234,
      "startup_type": null,
      "logon_as": null,
      "ports": null
    }
  ],
  "timestamp": "2026-02-27T14:23:05.123456+00:00"
}
```

**Third example** demonstrates the error case: `startup_type` and `logon_as` are `null` because `QueryServiceConfig` failed (e.g., AccessDenied on that specific service), and `ports` is `null` because psutil is not installed.

### POST endpoints -- unchanged

All `POST /api/services/{name}/{start|stop|restart}` endpoints remain identical to v1.0.

---

## 7. Architecture Diagram

```
                        ┌──────────────────────────────────┐
                        │         Browser (Client)          │
                        │       frontend/index.html         │
                        │                                   │
                        │  ┌─────────────┐ ┌─────────────┐ │
                        │  │Column Toggle│ │ Filter Bar  │ │
                        │  │ (checkboxes)│ │(text+2 drop)│ │
                        │  └─────────────┘ └─────────────┘ │
                        │  ┌─────────────────────────────┐ │
                        │  │  Service Table (7 columns)  │ │
                        │  │  name, display_name, status │ │
                        │  │  startup_type*, logon_as*,  │ │
                        │  │  ports*, actions             │ │
                        │  │  (* = togglable)            │ │
                        │  └─────────────────────────────┘ │
                        └──────────────┬───────────────────┘
                                       │ HTTP (JSON)
                                       ▼
┌──────────────────────────────────────────────────────────────────┐
│                      FastAPI Application                         │
│                        backend/main.py                           │
│                                                                  │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────────────────┐│
│  │ config.py   │  │ audit.py     │  │ rate_limiter.py          ││
│  └─────────────┘  └──────────────┘  └──────────────────────────┘│
│                                                                  │
│  ┌──────────────────────────────────────────────────────────────┐│
│  │                   service_manager.py                         ││
│  │                                                              ││
│  │  list_services()                                             ││
│  │    ├── win32service.EnumServicesStatus()  → name,disp,status ││
│  │    ├── win32service.QueryServiceConfig()  → startup, logon   ││
│  │    └── psutil.net_connections(kind='tcp') → ports            ││
│  │                                                              ││
│  │  start_service() / stop_service() / restart_service()        ││
│  │    └── (unchanged from v1.0)                                 ││
│  └──────────────────────────────────────────────────────────────┘│
└───────────────────────────┬──────────────────────────────────────┘
                            │
              ┌─────────────┼─────────────┐
              │             │             │
              ▼             ▼             ▼
     ┌──────────────┐ ┌─────────┐ ┌──────────────┐
     │ Windows SCM  │ │ psutil  │ │ config.yaml  │
     │ (pywin32)    │ │ (TCP)   │ │ (unchanged)  │
     └──────────────┘ └─────────┘ └──────────────┘
```

---

## 8. Testing Requirements

### Backend Unit Tests

| Test Case | Module | Assertion |
|-----------|--------|-----------|
| `_STARTUP_TYPE_MAP` covers all 5 values | `service_manager.py` | Map returns correct string for 0, 1, 2, 3, 4 |
| Unknown StartType returns `"Unknown"` | `service_manager.py` | Input `99` yields `"Unknown"` |
| `_query_service_config` returns `(None, None)` on exception | `service_manager.py` | Mock `OpenService` to raise; verify tuple |
| `_get_listening_ports` returns `None` when psutil unavailable | `service_manager.py` | Patch `_PSUTIL_AVAILABLE = False` |
| `_get_listening_ports` returns `[]` when pid is None | `service_manager.py` | Call with `pid=None` |
| `_get_listening_ports` returns sorted unique ports | `service_manager.py` | Mock connections with duplicates, verify sorted unique |
| `_get_listening_ports` returns `[]` on AccessDenied | `service_manager.py` | Mock `net_connections` to raise `psutil.AccessDenied` |
| `list_services` includes all 7 fields | `service_manager.py` | Mock all deps; verify dict keys |
| API response includes new fields | `main.py` | Integration test via TestClient |

### Frontend Tests (Manual / E2E)

| Test Case | Expected Result |
|-----------|-----------------|
| Page loads with all new columns hidden | Only Dienst, Status, Aktionen columns visible |
| Check "Starttyp" checkbox | Starttyp column appears with correct values |
| Uncheck "Starttyp" checkbox | Starttyp column disappears |
| Type "worker" in search box | Only services with "worker" in name/display_name shown |
| Select "Running" from status dropdown | Only running services shown |
| Select "Manual" from startup-type dropdown | Only manual services shown |
| Combine text + status + startup-type | AND logic applied; only matching services shown |
| Clear all filters | All services shown again |
| Reload page | All toggles reset to hidden, all filters cleared |
| Service with `ports: null` | Cell shows "n/a" with tooltip |
| Service with `ports: []` | Cell shows "--" |
| Service with `ports: [80, 443]` | Cell shows "80, 443" |

---

## 9. Migration Notes

### For Backend Developers

1. **File to modify:** `/projects/windows-service-manager/backend/service_manager.py`
   - Add `_STARTUP_TYPE_MAP` constant
   - Add `_query_service_config()` helper function
   - Add psutil conditional import and `_PSUTIL_AVAILABLE` flag
   - Add `_get_listening_ports()` helper function
   - Modify `list_services()` to include the three new fields per service dict
   - The SCM handle scope in `list_services()` must be extended: keep the handle open while iterating to call `_query_service_config()` per service

2. **File to modify:** `/projects/windows-service-manager/backend/requirements.txt`
   - Add `psutil>=5.9.0`

3. **No changes needed in:** `main.py`, `config.py`, `audit.py`, `rate_limiter.py`
   - The `GET /api/services` endpoint in `main.py` serializes whatever `list_services()` returns; the new fields flow through automatically.

### For Frontend Developers

1. **File to modify:** `/projects/windows-service-manager/frontend/index.html`
   - Add column toggle checkboxes (HTML + JS state)
   - Add filter bar (HTML: 1 input + 2 selects)
   - Add `columnVisibility` and `filterState` JS objects
   - Modify `renderServices()` to conditionally render optional `<th>` / `<td>` elements
   - Add `applyFilters()` function called before rendering
   - Wire event listeners on checkboxes and filter controls to trigger re-render

2. **Styling:** Use existing Tailwind CSS classes. No new CSS framework or build step required.

---

*End of specification.*

# PROJECT-STATUS: Windows Service Manager
**Stand:** 26. Februar 2026  
**Version:** 1.1 – MVP + Bestätigungs-Dialog

---

## Was wurde gebaut

Ein lokales Web-Dashboard für Windows Server, das Entwicklern ohne RDP-Zugang erlaubt, Windows-Dienste einer Applikation zu überwachen und zu steuern (Start / Stop / Restart).

---

## Fertige Komponenten

| Datei | Beschreibung | Status |
|-------|-------------|--------|
| `backend/main.py` | FastAPI App, alle 5 Endpoints, Middleware | ✅ |
| `backend/service_manager.py` | pywin32 Wrapper (list/start/stop/restart) | ✅ |
| `backend/config.py` | Config-Loader (Pydantic), prefix + contains Filter | ✅ |
| `backend/audit.py` | JSON Lines Audit-Logger, RotatingFileHandler | ✅ |
| `backend/rate_limiter.py` | In-Memory Rate Limiter (10/min pro IP) | ✅ |
| `backend/requirements.txt` | fastapi, uvicorn, pywin32, pyyaml, pydantic | ✅ |
| `backend/tests/` | Unit Tests für alle Module (mock pywin32) | ✅ |
| `frontend/index.html` | Single-file Frontend, Tailwind CDN, Vanilla JS, Bestätigungs-Dialog | ✅ |
| `config.yaml` | Beispiel-Konfiguration mit Kommentaren | ✅ |
| `start.bat` | Manueller Start-Script | ✅ |
| `README.md` | Setup + Deployment-Anleitung (inkl. NSSM) | ✅ |
| `docs/ARCHITECTURE.md` | Vollständige Architektur-Dokumentation | ✅ |

---

## Architektur-Entscheidungen (ADRs)

**ADR-001 – Kein Auth im MVP**  
Zugangskontrolle erfolgt über Netzwerksegmentierung + Reverse Proxy. Audit-Log mit Client-IP als Accountability-Mechanismus. Auth kann später als Middleware ergänzt werden ohne API-Änderungen.

**ADR-002 – Synchrone pywin32 Calls in async Framework**  
Alle service_manager Methoden laufen via `asyncio.to_thread()` um den Event Loop nicht zu blockieren. State-Transitions werden per Polling überwacht (500ms Intervall, 30s Timeout → HTTP 504).

**ADR-003 – In-Memory Rate Limiting**  
Einfaches Sliding-Window dict mit Timestamps. Verliert State bei Restart. Bei Multi-Process Deployment muss auf Redis gewechselt werden.

---

## Changelog

**v1.1** – Bestätigungs-Dialog für alle Aktionen
- Jeder Button (Start/Stop/Restart) öffnet einen modalen Bestätigungs-Dialog
- Start → grüner Bestätigungs-Button
- Stop → roter Bestätigungs-Button  
- Restart → orangener Bestätigungs-Button
- Escape oder Klick auf Hintergrund schließt Dialog ohne Aktion
- API wird erst nach expliziter Bestätigung aufgerufen (verhindert versehentliche Aktionen)

**v1.0** – MVP
- Service-Liste mit Status-Badges
- Start / Stop / Restart Buttons
- Audit-Logging mit Client-IP
- Rate Limiting (10 Aktionen/min pro IP)
- config.yaml mit prefix + contains Filter

---

## Bekannte Limitierungen

- `pywin32` läuft nur auf Windows – kein lokales Testing auf Mac/Linux ohne Mock
- Rate-Limiting verliert State bei App-Neustart
- Kein Auth (by design, MVP)
- Single-Process only (Rate Limiter ist in-memory)
- Config wird beim Start geladen – Änderungen erfordern App-Neustart

---

## Deployment

```bat
# 1. Python 3.10+ auf Windows Server installieren
# 2. Abhängigkeiten
cd backend
pip install -r requirements.txt

# 3. Config anpassen
notepad ..\config.yaml

# 4. Manuell testen
..\start.bat

# 5. Als Windows-Dienst via NSSM
nssm install ServiceManager python main.py
nssm set ServiceManager AppDirectory C:\path\to\windows-service-manager\backend
nssm start ServiceManager
```

---

## Mögliche nächste Features

| Feature | Aufwand | Beschreibung |
|---------|---------|-------------|
| **Auth / API Key** | Klein | Header-basierter API Key als Middleware |
| **Config Hot-Reload** | Klein | config.yaml ohne Neustart neu laden (watchdog) |
| **Audit Log Viewer** | Mittel | `/logs` Endpoint + UI-Tab zum Durchsuchen der Logs |
| **Service Groups** | Mittel | Dienste gruppieren (z.B. "Frontend", "Backend") und Gruppe als Ganzes steuern |
| **Webhook / Alerts** | Mittel | Benachrichtigung via Teams/Slack wenn Dienst unerwartet stoppt |
| **Multi-Server** | Gross | Mehrere Windows Server über eine UI verwalten |
| **Login / LDAP** | Gross | Active Directory Integration für Benutzer-Auth |

---

## Prompt für neue Features (nächste Session)

```
The project in projects/windows-service-manager/ is already built and complete (v1.0).
Read the existing code in backend/ and frontend/index.html first.
Also read docs/ARCHITECTURE.md for the full architecture context.

Then create an agent team to add the following feature:
[FEATURE BESCHREIBUNG]

Spawn: architect, backend-dev, frontend-dev, test-engineer
Constraint: Do not break existing functionality. Add tests for new code.
```

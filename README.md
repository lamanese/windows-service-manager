# Windows Service Manager

## Ueberblick

Windows Service Manager ist eine leichtgewichtige Web-Anwendung zur Verwaltung von Windows-Diensten ueber einen Browser. Das Backend ist ein FastAPI-Server (Python), der ueber die pywin32-API mit dem Windows Service Control Manager (SCM) kommuniziert. Das Frontend ist eine einzelne HTML-Datei mit eingebettetem JavaScript, die alle Dienste in einer Tabelle anzeigt und Start-, Stop- und Neustart-Aktionen ermooglicht. Die Anwendung richtet sich an Administratoren und Betreiber, die Dienste auf Windows-Servern ohne Remote-Desktop-Zugang kontrollieren muessen.

---

## Voraussetzungen

- **Betriebssystem:** Windows 10 / Windows Server 2016 oder neuer
- **Python:** 3.9 oder neuer (64-Bit empfohlen)
- **pywin32:** Wird automatisch ueber `requirements.txt` installiert; muss unter einem Konto mit Zugriff auf den Service Control Manager ausgefuehrt werden
- **Administratorrechte:** Benoetigt fuer Start/Stop/Neustart von Windows-Diensten
- **Netzwerk:** Der Server muss vom Browser des Administrators erreichbar sein

---

## Installation

### 1. Repository/Dateien kopieren

Kopieren Sie das Projektverzeichnis auf den Ziel-Windows-Server, zum Beispiel nach:

```
C:\Tools\windows-service-manager\
```

Die erwartete Verzeichnisstruktur:

```
windows-service-manager\
├── backend\
│   ├── main.py
│   ├── service_manager.py
│   ├── config.py
│   ├── audit.py
│   ├── rate_limiter.py
│   └── requirements.txt
├── frontend\
│   └── index.html
├── docs\
│   └── ARCHITECTURE.md
├── config.yaml
├── logs\
│   └── .gitkeep
├── start.bat
└── README.md
```

### 2. Abhaengigkeiten installieren

Oeffnen Sie eine Eingabeaufforderung **als Administrator** und fuehren Sie aus:

```bat
cd C:\Tools\windows-service-manager
pip install -r backend\requirements.txt
```

### 3. Konfiguration anpassen

Bearbeiten Sie `config.yaml` im Stammverzeichnis. Die wichtigsten Einstellungen:

**Service-Filter** legen fest, welche Dienste angezeigt werden. Ohne Filter werden **alle** Win32-Dienste angezeigt.

```yaml
service_filters:
  # Zeigt alle Dienste, deren Name mit "MyApp" beginnt
  - type: "prefix"
    value: "MyApp"

  # Zeigt alle Dienste, deren Name "Worker" enthaelt
  - type: "contains"
    value: "Worker"
```

Filtertypen:

| Typ | Beschreibung | Beispiel |
|-----|-------------|---------|
| `prefix` | Name beginnt mit dem angegebenen Wert (Gross-/Kleinschreibung egal) | `"MyApp"` trifft `MyAppWorker`, `myappscheduler` |
| `contains` | Name enthaelt den angegebenen Wert (Gross-/Kleinschreibung egal) | `"Worker"` trifft `MyAppWorker`, `BackgroundWorker` |

Mehrere Filter werden mit **ODER** verknuepft: Ein Dienst wird angezeigt, wenn er mindestens einen Filter erfuellt.

**Ausschlussliste** verhindert, dass bestimmte Dienste trotz passender Filter angezeigt werden:

```yaml
service_exclude:
  - "MyAppUninstaller"
  - "MyAppSetup"
```

### 4. Manuell starten (Testen)

```bat
start.bat
```

Oder direkt:

```bat
cd C:\Tools\windows-service-manager
python backend\main.py
```

Die Weboberflaeche ist dann unter `http://localhost:8080` erreichbar (oder dem in `config.yaml` konfigurierten Port).

### 5. Als Windows-Dienst registrieren (NSSM)

Fuer den Produktionsbetrieb empfehlen wir [NSSM (Non-Sucking Service Manager)](https://nssm.cc/):

```bat
nssm install ServiceManager "C:\Python310\python.exe" "C:\Tools\windows-service-manager\backend\main.py"
nssm set ServiceManager AppDirectory "C:\Tools\windows-service-manager"
nssm set ServiceManager AppStdout "C:\Tools\windows-service-manager\logs\service-manager.log"
nssm set ServiceManager AppStderr "C:\Tools\windows-service-manager\logs\service-manager-error.log"
nssm start ServiceManager
```

Passen Sie den Python-Pfad (`C:\Python310\python.exe`) entsprechend Ihrer Installation an. Fuer den Dienst sollte ein Konto mit Administratorrechten oder expliziten SCM-Berechtigungen verwendet werden.

---

## Konfiguration (config.yaml)

Die Konfigurationsdatei liegt im Stammverzeichnis des Projekts (`config.yaml`). Alle Felder sind optional und haben sinnvolle Standardwerte. Fehlt die Datei, werden alle Standardwerte verwendet.

| Schluessel | Typ | Standard | Beschreibung |
|-----------|-----|---------|-------------|
| `server.host` | string | `"0.0.0.0"` | Bind-Adresse des Backends. `0.0.0.0` = alle Netzwerkschnittstellen. |
| `server.port` | int | `8080` | TCP-Port, auf dem der Server lauscht. |
| `logging.audit_log` | string | `"logs/audit.log"` | Pfad zur Audit-Log-Datei (relativ zum Projektstamm oder absolut). |
| `logging.max_size_mb` | int | `10` | Maximale Groesse der Audit-Log-Datei in MB vor der Rotation. |
| `logging.backup_count` | int | `5` | Anzahl rotierter Backup-Dateien, die aufbewahrt werden. |
| `service_filters` | Liste | `[]` (alle) | Liste von Filterobjekten (`type` + `value`). Leer = alle Dienste. |
| `service_filters[].type` | string | - | `"prefix"` oder `"contains"`. |
| `service_filters[].value` | string | - | Der Filterwert (Gross-/Kleinschreibung egal). |
| `service_exclude` | Liste von strings | `[]` | Dienstnamen, die niemals angezeigt werden, auch wenn ein Filter zutrifft. |
| `rate_limit.max_requests` | int | `10` | Maximale Aktionen (Start/Stop/Restart) pro IP pro Zeitfenster. |
| `rate_limit.window_seconds` | int | `60` | Laenge des Rate-Limit-Zeitfensters in Sekunden. |
| `service_control.timeout_seconds` | int | `30` | Timeout in Sekunden, den das Backend auf den Zielstatus eines Dienstes wartet. |
| `service_control.poll_interval_ms` | int | `500` | Abstand in Millisekunden zwischen Statusabfragen waehrend einer Zustandsaenderung. |

---

## API-Referenz

Alle Endpunkte sind unter dem konfigurierten Host und Port erreichbar. Fehlerantworten folgen immer dem Schema `{"error": "<Kategorie>", "detail": "<Beschreibung>"}`.

| Methode | Pfad | Beschreibung | Beispiel-Antwort (200) |
|--------|------|-------------|----------------------|
| `GET` | `/` | Liefert die Frontend-HTML-Seite. | HTML-Dokument |
| `GET` | `/api/services` | Gibt alle gefilterten Windows-Dienste mit Status zurueck. | `{"services": [{"name": "MyAppWorker", "display_name": "MyApp Background Worker", "status": "running", "pid": 4821}], "timestamp": "2026-02-26T14:23:05.123456+00:00"}` |
| `POST` | `/api/services/{name}/start` | Startet den Dienst mit dem internen SCM-Namen `{name}`. | `{"success": true, "service": "MyAppWorker", "action": "start", "status": "running"}` |
| `POST` | `/api/services/{name}/stop` | Stoppt den Dienst mit dem internen SCM-Namen `{name}`. | `{"success": true, "service": "MyAppWorker", "action": "stop", "status": "stopped"}` |
| `POST` | `/api/services/{name}/restart` | Startet den Dienst neu (Stop + Start; wenn bereits gestoppt: nur Start). | `{"success": true, "service": "MyAppWorker", "action": "restart", "status": "running"}` |

**Moegliche Fehlercodes fuer Aktions-Endpunkte:**

| HTTP-Status | Bedeutung |
|------------|----------|
| `403` | Unzureichende Rechte zum Steuern des Dienstes |
| `404` | Dienst nicht in der gefilterten Liste |
| `409` | Dienst bereits im Zielzustand (nur bei Start/Stop, nicht bei Restart) |
| `429` | Rate Limit ueberschritten; `Retry-After`-Header gibt Wartezeit an |
| `500` | Unerwarteter interner Fehler |
| `504` | Dienst hat den Zielzustand nicht innerhalb des Timeouts erreicht |

---

## Audit-Log

Alle Aktionen (Start, Stop, Restart) werden in einer Audit-Log-Datei im Format **JSON Lines** (eine JSON-Zeile pro Eintrag) protokolliert.

**Speicherort:** `logs/audit.log` (konfigurierbar ueber `logging.audit_log`)

**Rotation:** Automatisch via `RotatingFileHandler`. Bei Erreichen von `max_size_mb` wird die Datei rotiert; bis zu `backup_count` Backup-Dateien werden aufbewahrt (z. B. `audit.log.1`, `audit.log.2`).

**Beispieleintrag:**

```json
{"timestamp": "2026-02-26T14:23:05.123456+00:00", "action": "restart", "service_name": "MyAppWorker", "client_ip": "10.0.1.42", "result": "success", "detail": null, "duration_ms": 3245}
```

**Felder:**

| Feld | Typ | Beschreibung |
|-----|-----|-------------|
| `timestamp` | string | ISO 8601 mit Zeitzone (UTC) |
| `action` | string | `"start"`, `"stop"` oder `"restart"` |
| `service_name` | string | Interner SCM-Name des Dienstes |
| `client_ip` | string | IP-Adresse des Clients (aus `X-Forwarded-For` oder direkter Verbindung) |
| `result` | string | `"success"` oder `"error"` |
| `detail` | string \| null | Fehlermeldung bei `"error"`, sonst `null` |
| `duration_ms` | int | Dauer der Aktion in Millisekunden |

---

## Sicherheitshinweise

- **Kein Login im MVP:** Die Anwendung hat keine Authentifizierung. Der Zugriff muss ueber Netzwerksegmentierung (VPN, Firewall) oder einen vorgelagerten Reverse Proxy abgesichert werden.
- **Rate Limiting:** Aktions-Endpunkte sind auf 10 Aktionen pro IP pro Minute begrenzt, um Missbrauch einzuschraenken.
- **Service-Filter:** Nur explizit konfigurierte Dienste sind ueber die API erreichbar. Systemdienste, die nicht in der gefilterten Liste erscheinen, koennen nicht gesteuert werden.
- **Kein HTTPS direkt:** Die Anwendung bindet auf HTTP. HTTPS-Terminierung muss durch einen Reverse Proxy (z. B. nginx, IIS, Caddy) erfolgen, der vor dem Service Manager betrieben wird.
- **Audit-Log:** Alle Aktionen werden mit Client-IP protokolliert und dienen als Nachweismechanismus.

---

## Projektstruktur

```
windows-service-manager/
├── backend/
│   ├── main.py                 # FastAPI-App, Endpunkte, Middleware, Lifespan
│   ├── service_manager.py      # WindowsServiceManager (pywin32-Wrapper)
│   ├── config.py               # AppConfig (Pydantic), load_config(), get_config()
│   ├── audit.py                # AuditLogger (JSON Lines + RotatingFileHandler)
│   ├── rate_limiter.py         # RateLimiter (In-Memory Sliding Window)
│   └── requirements.txt        # Python-Abhaengigkeiten
├── frontend/
│   └── index.html              # Einzeldatei-Frontend (HTML + Tailwind CSS CDN + JS)
├── docs/
│   └── ARCHITECTURE.md         # Architektur-Dokumentation
├── config.yaml                 # Anwendungskonfiguration (bearbeitbar)
├── logs/                       # Audit-Log-Verzeichnis (wird beim Start angelegt)
│   └── .gitkeep
├── start.bat                   # Manuelles Start-Skript fuer Tests
└── README.md                   # Diese Datei
```

---

## Tests ausfuehren

```bat
cd C:\Tools\windows-service-manager
pytest backend\tests\
```

Fuer ausfuehrliche Ausgabe:

```bat
pytest backend\tests\ -v --tb=short
```

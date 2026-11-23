# Setup und technische Details

Ergänzung zum [README](../README.md): lokaler Start, interne API, n8n- und Airtable-Einrichtung.

## App lokal starten (ohne Airtable, ohne Docker)

```bash
source .venv/bin/activate
flask --app app:create_app run --port 8000 --debug
```

Dann http://localhost:8000 öffnen. Ohne `AIRTABLE_API_TOKEN` läuft die App mit Demo-Daten im Speicher
(`REPOSITORY=memory`, gehen beim Neustart verloren). Demo-Logins: `lena@hubrent-demo.example`,
`jonas@…` (1 Strike), `mira@…` (3 Strikes), Passwort `hubrent-demo`.

Tipp: Lokal ohne laufendes n8n `N8N_EVENT_WEBHOOK_URL=` in der `.env` leer lassen. Dann landen die Events
samt Bestätigungs- und Storno-Links im Terminal-Log, statt erfolglos an n8n zu gehen.

| Seite | Zweck |
|---|---|
| `/` | Landingpage mit Ablauf und Strike-Erklärung |
| `/register`, `/login` | Konto anlegen / anmelden (Logout per POST) |
| `/geraete` | Katalog mit Filter nach Kategorie und Hub, „jetzt frei“-Badge |
| `/geraete/<id>` | Detail + Buchungsformular, Live-Preis per HTMX (`/api/verfuegbarkeit`) |
| `/konto` | Reservierungen, Bestätigen/Stornieren, Strike-Karte, offene Gebühren |
| `/r/<token>/bestaetigen`, `/r/<token>/stornieren` | Links aus der Mail: GET zeigt nur an, erst der Button (POST) ändert etwas |
| `/terminal`, `/terminal/<hub_id>` | Hub-Terminal im Kiosk-Look: **Abholen** per PIN (Ziffernblock, Fach öffnet sich), **Rückgabe** per Reservierungscode (`HR-` darf fehlen). Nach 5 Fehlversuchen pro Minute ist das Terminal kurz gesperrt. |

## Interne API für n8n

Alle Aufrufe brauchen den Header `X-Internal-Secret: <INTERNAL_API_SECRET>` (sonst `401`; ist kein Secret
gesetzt, ist die API abgeschaltet: `503`). Alle Aktionen sind **idempotent**: Ist nichts (mehr) zu tun, kommt
`200` mit `"changed": false`, und es entstehen keine doppelten Strikes, Gebühren oder Erinnerungen.

| Methode & Pfad | Wirkung |
|---|---|
| `GET /api/internal/health` | Healthcheck |
| `POST /api/internal/reservations/<id>/reminder-sent` | setzt `reminder_sent_at`, liefert frische Links (`links.confirm`, `links.cancel`) |
| `POST /api/internal/reservations/<id>/auto-cancel` | `PENDING → CANCELLED_AUTO`, nur wenn die Frist erreicht ist |
| `POST /api/internal/reservations/<id>/no-show` | `CONFIRMED → NO_SHOW`, Strike + ggf. Gebühr |

Die Antwort enthält alles für die Mail: `changed`, `message`, `reservation` (Code, Status, Zeiten in Berliner
Zeit, PIN), `customer` (Name, E-Mail, Strike-Stand, `strike_text`), `device`, `hub`, `fee` (`{"amount": "55.00",
"currency": "EUR"}`) und bei `reminder-sent` die `links`. Unbekannte ID: `404`.

```bash
curl -X POST -H "X-Internal-Secret: $INTERNAL_API_SECRET" http://localhost:8000/api/internal/reservations/<id>/no-show
```

## n8n-Workflows einrichten

Was welcher Workflow tut und wie er mit den Geschäftsregeln zusammenhängt: [n8n/README.md](../n8n/README.md).

**Einrichten:**

1. Docker Desktop starten, `docker compose up -d`, n8n unter http://localhost:5678 öffnen und Owner-Konto anlegen.
2. Workflows importieren (feste IDs, damit der Error-Workflow verknüpft bleibt):
   ```bash
   docker compose exec n8n n8n import:workflow --separate --input=/workflows
   ```
3. In n8n zwei Credentials anlegen:
   - **SMTP** (Gmail): Host `smtp.gmail.com`, Port `465`, SSL an, User = deine Gmail-Adresse, Passwort = **App-Passwort**
     (Google-Konto → Sicherheit → 2-Faktor an → App-Passwörter).
   - **Airtable Personal Access Token**: derselbe Token wie in der `.env`.
4. In jedem Workflow die Nodes mit rotem Warnsymbol öffnen und das passende Credential auswählen
   (Mail-Nodes in WF-01 und WF-99, Airtable-Nodes in WF-01 bis WF-04).
5. In der `.env` `MAIL_FROM` (deine Gmail-Adresse) und `ADMIN_EMAIL` setzen, dann `docker compose up -d` erneut.
6. Erst WF-99, dann WF-01 aktivieren. WF-02 bis WF-04 **nur für Demo und Tests** aktivieren.

**Achtung Airtable-Limit:** Der Gratis-Tarif erlaubt 1.000 API-Aufrufe pro Monat. WF-02 bis WF-04 machen zusammen
3 Abfragen pro Minute (180 pro Stunde), dazu kommen die Aufrufe der Flask-App. Nach der Demo wieder deaktivieren.

## Airtable einrichten

1. Auf airtable.com eine **leere Base** anlegen. Die Base-ID (`app…`) steht in der URL.
2. Unter *Builder Hub → Personal access tokens* einen Token erstellen:
   Scopes `data.records:read`, `data.records:write`, `schema.bases:read`, `schema.bases:write`,
   Zugriff nur auf diese Base.
3. `cp .env.example .env` und `AIRTABLE_API_TOKEN`, `AIRTABLE_BASE_ID` eintragen
   (optional `SEED_EMAIL_BASE=du@gmail.com`).
4. Tabellen anlegen und Demo-Daten schreiben:

```bash
python -m scripts.setup_airtable --dry-run   # zeigt nur den Plan
python -m scripts.setup_airtable
python -m scripts.seed                       # --reset leert vorher Reservierungen, Strikes, Gebühren, EventLog
```

Beide Skripte sind **idempotent**: Mehrfaches Ausführen ergänzt nur, was fehlt, und erzeugt keine Duplikate.
Demo-Logins: `lena`, `jonas` (1 Strike, 3/5), `mira` (3 Strikes), Passwort `hubrent-demo`.

**Abweichungen vom Datenmodell der Spezifikation** (Formel-, Autonumber- und „Created time“-Felder
sind laut Airtable-API-Doku beim Anlegen nicht zuverlässig möglich, siehe [`app/repository/airtable_schema.py`](../app/repository/airtable_schema.py)):

| Spezifikation | Umsetzung |
|---|---|
| `reservation_code` als Formel/Autonumber (`HR-000123`) | Textfeld, Flask erzeugt einen Zufallscode (`HR-7K3QXM`, ohne 0/O/1/I/L) |
| `created_at` als *Created time* | Datumsfeld, Flask schreibt es beim Anlegen |
| `device_id`, `hub_id`, `customer_id` … per `RECORD_ID()`-Formel | Textfelder mit der Record-ID, zusätzlich zur Verknüpfung |
| `email` als Typ *Email* (Primärfeld) | Textfeld (welche Typen als Primärfeld erlaubt sind, ist nicht dokumentiert) |
| StrikeEvents/Fees ohne Primärfeld | lesbares Primärfeld `label`, z. B. `NO_SHOW → 2 Strike(s)` |

Filter in n8n werden dadurch einfach, z. B. `AND({status}='PENDING', {reminder_sent_at}=BLANK())`.

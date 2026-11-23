# Demo-Skript: HubRent in 2 Minuten

Ziel des Videos: zeigen, dass der komplette Reservierungsprozess **ohne manuelles Nachfassen** läuft und in n8n nachvollziehbar ist.
Gedreht wird in einzelnen Takes. Die Wartezeiten zwischen den Schritten werden herausgeschnitten.

## Vorbereitung (einmalig, ca. 15 min)

1. In der `.env` die Demo-Fristen setzen, dann `docker compose up -d`:
   ```
   DEMO_MODE=true
   REMINDER_HOURS_BEFORE=6          # → Erinnerung 6 min vor Start
   CONFIRM_DEADLINE_HOURS_BEFORE=3  # → Auto-Storno 3 min vor Start
   LATE_CANCEL_HOURS_BEFORE=3
   SEED_EMAIL_BASE=deine@gmail.com  # Demo-Kunden landen als deine+lena@gmail.com in deinem Postfach
   ```
   Im Demo-Modus werden alle Fristen durch 60 geteilt: Abholfenster 30 s vor bis 2 min nach Start, Startzeiten im Minutentakt.
   Dass jeder Ablauf so unter 10 Minuten bleibt, prüft `tests/test_demo_timeline.py`.
2. `python -m scripts.seed --reset` für einen sauberen Stand.
3. In n8n WF-99, WF-01, WF-02, WF-03 und WF-04 aktivieren. **Nach dem Dreh wieder deaktivieren** (Airtable-Limit).
4. Fenster anordnen: Browser mit HubRent, Gmail, n8n (Executions-Liste), Airtable (Tabelle *Reservations*).

## Drehplan

| Zeit im Video | Szene | Was geklickt wird | Was zu sehen ist |
|---|---|---|---|
| 0:00–0:10 | **Intro** | Startseite | Claim „Werkzeug, wann du es brauchst“. Sprechtext: Problem No-Shows, manuelles Nachtelefonieren. |
| 0:10–0:25 | **Buchen** | Als *Lena* einloggen → Akku-Bohrhammer → Hub Neukölln → 4 Stunden, Start in **7 min** → Reservieren | Erfolgsseite „Reserviert!“, Status *Unbestätigt*. In Airtable erscheint die Zeile mit `PENDING`. |
| 0:25–0:40 | **Erinnerung (WF-02)** | n8n: Execution von *Erinnerung T-48h* öffnen (ca. 1 min nach der Buchung) | Ablauf Airtable-Suche → Flask → Mail Dispatcher. In Gmail: Mail „Bitte bestätige deine Reservierung“ mit zwei Buttons. |
| 0:40–0:55 | **Bestätigen** | In der Mail „Ja, ich hole es ab“ → auf der Seite bestätigen | Seite mit PIN, Fach und Abholfenster. Zweite Mail „Deine PIN für Akku-Bohrhammer“. |
| 0:55–1:15 | **Abholen + Rückgabe** | Menü *Hub-Terminal* → Hub Neukölln → PIN am Ziffernblock → OK; danach Tab *Rückgabe* → Code eingeben | Fach leuchtet auf, Tür schwingt auf. Bei der Rückgabe: „Pünktlich zurückgegeben“. Mail „Danke für die Rückgabe“. |
| 1:15–1:35 | **No-Show (WF-04)** | Vorher gedreht: *Jonas* (1 Strike) bucht die Parkettschleifmaschine kurzfristig (Start in 2 min, „verbindlich“ anhaken) und holt nicht ab | n8n-Execution *No-Show-Check*, Mail „Nicht abgeholt“ mit **Strike 2 und 55,00 € Gebühr**. In *Mein Konto*: Strike-Karte 2 Strikes, offene Gebühr. |
| 1:35–1:50 | **Auto-Storno (WF-03)** | Vorher gedreht: Buchung mit Start in 8 min, nicht bestätigen | Mail „Deine Reservierung wurde freigegeben“, kein Strike. Gerät ist im Katalog wieder frei. |
| 1:50–2:00 | **Abschluss** | n8n-Übersicht mit den fünf Workflows | Pitch: *„Die App ist das Schaufenster, die Prozesse laufen automatisiert in n8n und lassen sich ohne Code anpassen.“* |

## Optionale Zusatzszene (wenn Zeit bleibt)

- **Idempotenz live:** In n8n eine No-Show-Execution erneut ausführen. Flask antwortet `"changed": false`, es kommt kein zweiter Strike und keine zweite Mail.
- **Fehlerfall:** Flask-Container kurz stoppen (`docker compose stop web`), einen Cron-Lauf abwarten. WF-99 schickt eine Admin-Mail mit der Fehlermeldung.

## Zeitplan für einen Dreh am Stück (T = erste Buchung)

| T + | Aktion |
|---|---|
| 0:00 | Lena bucht Bohrhammer, Start T+7 · Jonas bucht Parkettschleifer kurzfristig, Start T+2 · Mira bucht Teppichreiniger, Start T+8 (nicht bestätigen) |
| ~1:00 | Erinnerungsmail an Lena → bestätigen → PIN-Mail |
| ~5:00 | No-Show-Mail an Jonas (Abholfenster T+2 bis T+4 vorbei, nächster Cron-Lauf) |
| ~5:00 | Auto-Storno-Mail an Mira (Frist T+8 − 3 min) |
| 6:30–9:00 | Lena holt am Terminal ab (ab T+6:30) und gibt zurück |

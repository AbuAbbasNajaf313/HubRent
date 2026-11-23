# HubRent

Fiktiver Geräteverleih mit 24/7-Schließfach-Hubs in Baumärkten. Reservierungen,
Bestätigungen, Stornos, No-Shows und ein faires **Strike-System** laufen automatisiert
über **n8n + Airtable**. Die Flask-App ist das Schaufenster, die Prozesse laufen im Hintergrund.

Vollständige Spezifikation: [`docs/SPEC.md`](docs/SPEC.md)

## Stand

| Meilenstein | Status |
|---|---|
| 1. Projektgerüst, Docker, `.env.example` | ✅ |
| 2. Domain-Logik + Tests (Preise, Verfügbarkeit, Statusmaschine, Strikes, Tokens) | ✅ |
| 2b. Service-Schicht + Repository-Schnittstelle + In-Memory-Repo + Event-Publisher | ✅ |
| 3. Airtable-Setup-Skript + Seed-Daten + `AirtableRepository` | ⏳ |
| 4. Flask-Web-Schicht (Login, Katalog, Buchung, Konto, Token-Links) | ⏳ |
| 5. Interne API für n8n | ⏳ |
| 6. n8n-Workflows (Mail, T-48h, T-24h, No-Show, Error) | ⏳ |
| 7. Hub-Terminal-Simulator | ⏳ |
| 8. How-to-Guide + Demo-Skript | ⏳ |

## Tests

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pytest -q
```

## Architektur in einem Satz

`domain/` enthält die Regeln (ohne I/O, Uhrzeit als Parameter), `services/` die Anwendungsfälle,
`repository/` den Datenzugriff (Airtable oder In-Memory), `web/` die Oberfläche.
n8n entscheidet, **wann** etwas passiert, Flask entscheidet, **ob** es erlaubt ist.

## Wichtige Konzepte (fürs Studium)

- **Statusmaschine** (`app/domain/rules.py`): erlaubte Übergänge als Tabelle. Unerlaubte werfen `InvalidTransition`.
- **Dependency Injection der Uhr**: Jede Regel bekommt `now` übergeben, dadurch sind Fristen ohne Tricks testbar.
- **Repository-Pattern** (`app/repository/base.py`): Services hängen von einer Abstraktion ab, nicht von Airtable.
- **Idempotenz** (`app/services/rentals.py`): n8n darf Aufrufe wiederholen, ohne doppelte Strikes zu erzeugen.
- **Decimal statt float** für Geld, **Token-Hashing** statt Klartext-Tokens.

## Bekannte Grenzen (Demo)

- Airtable hat keine Transaktionen. Gleichzeitige Buchungen werden per Nachkontrolle abgefangen, im Grenzfall scheitern dann beide Buchungen statt einer Doppelbuchung.
- Gebühren werden in Phase 1 nur erfasst (`Fees`, Status `OPEN`), Zahlung folgt in Phase 2 (Stripe).

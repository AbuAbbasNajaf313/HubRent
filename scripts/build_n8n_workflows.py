"""Erzeugt die importierbaren n8n-Workflows unter ``n8n/workflows/``.

Aufruf:  python -m scripts.build_n8n_workflows

Warum ein Generator statt von Hand exportierter JSON-Dateien?
- Die Mail-Vorlagen liegen lesbar und testbar in ``n8n/src/mail_templates.js``.
- Zeitgrenzen, Header-Namen und Pfade stehen an einer Stelle, passend zu Flask.
- Die Dateien enthalten **keine Credentials**. Gmail-SMTP und Airtable-Token werden
  nach dem Import in n8n ausgewählt (siehe README).

Wer Workflows später in der n8n-Oberfläche ändert, exportiert sie einfach erneut
nach ``n8n/workflows/``. Dieser Generator beschreibt den Startstand.

Feste Workflow-IDs sorgen dafür, dass der Verweis auf den Error-Workflow (WF-99)
nach ``n8n import:workflow`` direkt stimmt.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "n8n" / "workflows"
MAIL_JS = ROOT / "n8n" / "src" / "mail_templates.js"

WEBHOOK_PATH = "hubrent-event"
IDS = {
    "WF-01": "hubrentWf01Mails",
    "WF-02": "hubrentWf02Remnd",
    "WF-03": "hubrentWf03Dline",
    "WF-04": "hubrentWf04NoSho",
    "WF-99": "hubrentWf99Error",
}
SCHEDULE_MINUTES = 1  # Demo-tauglich; Workflows nur für die Demo aktivieren (Airtable-Limit!)

# Ausdrücke, die in mehreren Workflows vorkommen (n8n-Expressions, JavaScript)
NOW_EXPR = "$now.toUTC().toISO()"
HOUR_UNIT = "($env.DEMO_MODE === 'true' ? 'minutes' : 'hours')"
MINUTE_UNIT = "($env.DEMO_MODE === 'true' ? 'seconds' : 'minutes')"
SELF_WEBHOOK = f"($env.N8N_SELF_WEBHOOK_URL || 'http://localhost:5678/webhook/{WEBHOOK_PATH}')"


def _id(name: str) -> str:
    """Stabile Node-IDs, damit ein erneuter Build keinen unnötigen Diff erzeugt."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"hubrent:{name}"))


def node(name: str, type_: str, version: float, position: tuple[int, int], parameters: dict[str, Any], **extra: Any) -> dict:
    return {
        "id": _id(name),
        "name": name,
        "type": f"n8n-nodes-base.{type_}",
        "typeVersion": version,
        "position": list(position),
        "parameters": parameters,
        **extra,
    }


def connect(*pairs: tuple[str, str] | tuple[str, str, int]) -> dict:
    """("A", "B") verbindet Ausgang 0 von A mit B; ("If", "B", 1) nimmt Ausgang 1 (false)."""
    conns: dict[str, Any] = {}
    for pair in pairs:
        src, dst, out = (*pair, 0) if len(pair) == 2 else pair
        outputs = conns.setdefault(src, {"main": []})["main"]
        while len(outputs) <= out:
            outputs.append([])
        outputs[out].append({"node": dst, "type": "main", "index": 0})
    return conns


def workflow(key: str, name: str, nodes: list[dict], connections: dict, error_workflow: bool = True) -> dict:
    settings: dict[str, Any] = {"executionOrder": "v1", "timezone": "Europe/Berlin"}
    if error_workflow:
        settings["errorWorkflow"] = IDS["WF-99"]
    return {
        "id": IDS[key],
        "name": f"HubRent – {name}",
        "active": False,  # bewusst aus: erst nach Credential-Auswahl aktivieren
        "nodes": nodes,
        "connections": connections,
        "settings": settings,
        "pinData": {},
        "tags": [],
    }


def if_true(name: str, position: tuple[int, int], left: str) -> dict:
    return node(
        name,
        "if",
        2,
        position,
        {
            "conditions": {
                "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose"},
                "conditions": [
                    {
                        "id": _id(name + ":cond"),
                        "leftValue": left,
                        "rightValue": "",
                        "operator": {"type": "boolean", "operation": "true", "singleValue": True},
                    }
                ],
                "combinator": "and",
            },
            "options": {},
        },
    )


def http_post(name: str, position: tuple[int, int], url: str, header: str, secret_env: str, body: str | None = None) -> dict:
    params: dict[str, Any] = {
        "method": "POST",
        "url": url,
        "sendHeaders": True,
        "headerParameters": {"parameters": [{"name": header, "value": f"={{{{ $env.{secret_env} }}}}"}]},
        "options": {"timeout": 10000},
    }
    if body is not None:
        params.update({"sendBody": True, "specifyBody": "json", "jsonBody": body})
    # Wiederholen ist gefahrlos, weil die interne API idempotent ist.
    return node(name, "httpRequest", 4.2, position, params, retryOnFail=True, maxTries=3, waitBetweenTries=2000)


def airtable_search(name: str, position: tuple[int, int], formula: str) -> dict:
    return node(
        name,
        "airtable",
        2.1,
        position,
        {
            "operation": "search",
            "base": {"__rl": True, "mode": "id", "value": "={{ $env.AIRTABLE_BASE_ID }}"},
            "table": {"__rl": True, "mode": "id", "value": "Reservations"},  # Airtable akzeptiert auch den Namen
            "filterByFormula": formula,
            "returnAll": True,
            "options": {"fields": ["reservation_code", "status", "start_at"]},
        },
    )


def schedule(position: tuple[int, int]) -> dict:
    return node(
        "Alle 1 Minute",
        "scheduleTrigger",
        1.2,
        position,
        {"rule": {"interval": [{"field": "minutes", "minutesInterval": SCHEDULE_MINUTES}]}},
    )


# --- WF-01 Mail Dispatcher --------------------------------------------------------------

def wf01() -> dict:
    nodes = [
        node(
            "Event von Flask",
            "webhook",
            2,
            (0, 300),
            {"httpMethod": "POST", "path": WEBHOOK_PATH, "responseMode": "responseNode", "options": {}},
            webhookId=_id("webhook"),
        ),
        node(
            "Secret korrekt?",
            "if",
            2,
            (220, 300),
            {
                "conditions": {
                    "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "strict"},
                    "conditions": [
                        {
                            "id": _id("secret:cond"),
                            "leftValue": "={{ $json.headers['x-hubrent-secret'] }}",
                            "rightValue": "={{ $env.N8N_WEBHOOK_SECRET }}",
                            "operator": {"type": "string", "operation": "equals"},
                        }
                    ],
                    "combinator": "and",
                },
                "options": {},
            },
        ),
        node(
            "Antwort 401",
            "respondToWebhook",
            1.1,
            (440, 420),
            {"respondWith": "json", "responseBody": '={"error": "unauthorized"}', "options": {"responseCode": 401}},
        ),
        node(
            "Antwort 200",
            "respondToWebhook",
            1.1,
            (440, 200),
            {"respondWith": "json", "responseBody": '={"ok": true}', "options": {"responseCode": 200}},
        ),
        node("Mail bauen", "code", 2, (660, 200), {"jsCode": MAIL_JS.read_text(encoding="utf-8")}),
        if_true("Mail nötig?", (880, 100), "={{ $json.send }}"),
        node(
            "Mail senden (Gmail SMTP)",
            "emailSend",
            2.1,
            (1100, 100),
            {
                "fromEmail": "={{ $env.MAIL_FROM }}",
                "toEmail": "={{ $json.to }}",
                "subject": "={{ $json.subject }}",
                "emailFormat": "both",
                "text": "={{ $json.text }}",
                "html": "={{ $json.html }}",
                "options": {"appendAttribution": False},
            },
        ),
        node(
            "EventLog-Eintrag",
            "set",
            3.4,
            (880, 320),
            {
                "assignments": {
                    "assignments": [
                        {"id": _id("log:type"), "name": "event_type", "value": "={{ $json.event }}", "type": "string"},
                        {"id": _id("log:src"), "name": "source", "value": "n8n", "type": "string"},
                        {"id": _id("log:res"), "name": "reservation_id", "value": "={{ $json.reservation_id }}", "type": "string"},
                        {
                            "id": _id("log:payload"),
                            "name": "payload",
                            "value": "={{ JSON.stringify({ mail_sent: $json.send, to: $json.to || null, subject: $json.subject || null }) }}",
                            "type": "string",
                        },
                        {"id": _id("log:at"), "name": "created_at", "value": f"={{{{ {NOW_EXPR} }}}}", "type": "string"},
                    ]
                },
                "options": {},
            },
        ),
        node(
            "EventLog in Airtable",
            "airtable",
            2.1,
            (1100, 320),
            {
                "operation": "create",
                "base": {"__rl": True, "mode": "id", "value": "={{ $env.AIRTABLE_BASE_ID }}"},
                "table": {"__rl": True, "mode": "id", "value": "EventLog"},
                "columns": {"mappingMode": "autoMapInputData", "value": {}, "matchingColumns": [], "schema": []},
                "options": {"typecast": True},
            },
            # Protokollieren ist "best effort": Ohne Airtable sollen die Mails trotzdem rausgehen.
            onError="continueRegularOutput",
        ),
    ]
    connections = connect(
        ("Event von Flask", "Secret korrekt?"),
        ("Secret korrekt?", "Antwort 200", 0),
        ("Secret korrekt?", "Antwort 401", 1),
        ("Antwort 200", "Mail bauen"),
        ("Mail bauen", "Mail nötig?"),
        ("Mail bauen", "EventLog-Eintrag"),
        ("Mail nötig?", "Mail senden (Gmail SMTP)", 0),
        ("EventLog-Eintrag", "EventLog in Airtable"),
    )
    return workflow("WF-01", "Mail Dispatcher", nodes, connections)


# --- WF-02/03/04: Cron → Airtable → Flask → Mail ----------------------------------------

def timed(key: str, name: str, formula: str, api_action: str, event: str) -> dict:
    nodes = [
        schedule((0, 300)),
        airtable_search("Fällige Reservierungen suchen", (220, 300), formula),
        http_post(
            f"Flask: {api_action}",
            (440, 300),
            f"={{{{ $env.HUBRENT_API_URL }}}}/api/internal/reservations/{{{{ $json.id }}}}/{api_action}",
            "X-Internal-Secret",
            "INTERNAL_API_SECRET",
        ),
        if_true("Geändert?", (660, 300), "={{ $json.changed }}"),
        http_post(
            "An Mail Dispatcher",
            (880, 200),
            f"={{{{ {SELF_WEBHOOK} }}}}",
            "X-HubRent-Secret",
            "N8N_WEBHOOK_SECRET",
            body=f"={{{{ JSON.stringify(Object.assign({{}}, $json, {{ event: '{event}' }})) }}}}",
        ),
    ]
    connections = connect(
        ("Alle 1 Minute", "Fällige Reservierungen suchen"),
        ("Fällige Reservierungen suchen", f"Flask: {api_action}"),
        (f"Flask: {api_action}", "Geändert?"),
        ("Geändert?", "An Mail Dispatcher", 0),
    )
    return workflow(key, name, nodes, connections)


def formula(condition: str) -> str:
    """Airtable-Formel als n8n-Expression. "Jetzt" kommt von n8n, nicht von Airtables NOW()."""
    return "={{ " + condition + " }}"


def wf02() -> dict:
    f = formula(
        "\"AND({status}='PENDING', NOT({reminder_sent_at}), IS_BEFORE({start_at}, DATEADD(DATETIME_PARSE('\" + "
        f"{NOW_EXPR} + \"'), \" + ($env.REMINDER_HOURS_BEFORE || 48) + \", '\" + {HOUR_UNIT} + \"')))\""
    )
    return timed("WF-02", "Erinnerung T-48h", f, "reminder-sent", "reservation.reminder")


def wf03() -> dict:
    f = formula(
        "\"AND({status}='PENDING', IS_BEFORE({start_at}, DATEADD(DATETIME_PARSE('\" + "
        f"{NOW_EXPR} + \"'), \" + ($env.CONFIRM_DEADLINE_HOURS_BEFORE || 24) + \", '\" + {HOUR_UNIT} + \"')))\""
    )
    return timed("WF-03", "Deadline T-24h", f, "auto-cancel", "reservation.auto_cancelled")


def wf04() -> dict:
    f = formula(
        "\"AND({status}='CONFIRMED', NOT({picked_up_at}), IS_BEFORE(DATEADD({start_at}, \" + "
        f"($env.PICKUP_WINDOW_AFTER_MIN || 120) + \", '\" + {MINUTE_UNIT} + \"'), DATETIME_PARSE('\" + {NOW_EXPR} + \"')))\""
    )
    return timed("WF-04", "No-Show-Check", f, "no-show", "reservation.no_show")


# --- WF-99 Error Handler -----------------------------------------------------------------

def wf99() -> dict:
    nodes = [
        node("Fehler in einem Workflow", "errorTrigger", 1, (0, 300), {}),
        node(
            "Admin benachrichtigen",
            "emailSend",
            2.1,
            (240, 300),
            {
                "fromEmail": "={{ $env.MAIL_FROM }}",
                "toEmail": "={{ $env.ADMIN_EMAIL }}",
                "subject": "=HubRent-Fehler in {{ $json.workflow.name }}",
                "emailFormat": "text",
                "text": (
                    "=Workflow: {{ $json.workflow.name }}\n"
                    "Node: {{ $json.execution.lastNodeExecuted }}\n"
                    "Fehler: {{ $json.execution.error.message }}\n"
                    "Ausführung: {{ $json.execution.url }}\n"
                    "Zeit: {{ $now.setZone('Europe/Berlin').toFormat('dd.MM.yyyy HH:mm:ss') }}"
                ),
                "options": {"appendAttribution": False},
            },
        ),
    ]
    return workflow("WF-99", "Error Handler", nodes, connect(("Fehler in einem Workflow", "Admin benachrichtigen")), error_workflow=False)


WORKFLOWS = {
    "wf01_mail_dispatcher.json": wf01,
    "wf02_reminder_t48.json": wf02,
    "wf03_deadline_t24.json": wf03,
    "wf04_no_show_check.json": wf04,
    "wf99_error_handler.json": wf99,
}


def build() -> dict[str, dict]:
    return {filename: fn() for filename, fn in WORKFLOWS.items()}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for filename, wf in build().items():
        (OUT / filename).write_text(json.dumps(wf, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"✓ n8n/workflows/{filename}  ({wf['name']}, {len(wf['nodes'])} Nodes)")


if __name__ == "__main__":
    main()

"""Strukturprüfung der n8n-Workflow-Dateien (ohne laufendes n8n)."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from scripts.build_n8n_workflows import IDS, MAIL_JS, OUT, WEBHOOK_PATH, build

FILES = sorted(OUT.glob("*.json"))
NODE = shutil.which("node")


def load(name: str) -> dict:
    return json.loads((OUT / name).read_text(encoding="utf-8"))


def test_all_five_workflows_exist_and_are_current():
    assert {f.name for f in FILES} == set(build())
    for filename, expected in build().items():
        assert load(filename) == expected, f"{filename} veraltet: python -m scripts.build_n8n_workflows ausführen"


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_basic_structure(path):
    wf = json.loads(path.read_text(encoding="utf-8"))
    assert wf["name"].startswith("HubRent – ") and wf["active"] is False
    assert len(wf["id"]) == 16 and wf["id"].isalnum()
    names = [n["name"] for n in wf["nodes"]]
    assert len(names) == len(set(names))
    assert len({n["id"] for n in wf["nodes"]}) == len(names)
    for src, conn in wf["connections"].items():
        assert src in names
        for output in conn["main"]:
            for target in output:
                assert target["node"] in names


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_no_credentials_or_secrets_in_files(path):
    text = path.read_text(encoding="utf-8")
    wf = json.loads(text)
    assert all("credentials" not in n for n in wf["nodes"])
    assert not re.search(r"pat[A-Za-z0-9]{14}\.", text)  # Airtable-Token-Muster
    assert "bitte-" not in text


def test_error_workflow_is_linked_everywhere_except_itself():
    for filename in build():
        settings = load(filename)["settings"]
        if filename.startswith("wf99"):
            assert "errorWorkflow" not in settings
        else:
            assert settings["errorWorkflow"] == IDS["WF-99"]


def test_webhook_path_matches_flask_config():
    env_example = (Path(__file__).parent.parent / ".env.example").read_text(encoding="utf-8")
    hook = next(n for n in load("wf01_mail_dispatcher.json")["nodes"] if n["type"].endswith(".webhook"))
    assert hook["parameters"]["path"] == WEBHOOK_PATH
    assert f"/webhook/{WEBHOOK_PATH}" in env_example


def test_mail_dispatcher_embeds_current_templates_and_checks_secret():
    wf = load("wf01_mail_dispatcher.json")
    code = next(n for n in wf["nodes"] if n["name"] == "Mail bauen")
    assert code["parameters"]["jsCode"] == MAIL_JS.read_text(encoding="utf-8")
    check = next(n for n in wf["nodes"] if n["name"] == "Secret korrekt?")
    cond = check["parameters"]["conditions"]["conditions"][0]
    # Flask sendet "X-HubRent-Secret"; n8n liefert Header kleingeschrieben
    assert "x-hubrent-secret" in cond["leftValue"] and "N8N_WEBHOOK_SECRET" in cond["rightValue"]
    log = next(n for n in wf["nodes"] if n["name"] == "EventLog in Airtable")
    assert log["onError"] == "continueRegularOutput"


@pytest.mark.parametrize(
    "filename, action",
    [("wf02_reminder_t48.json", "reminder-sent"), ("wf03_deadline_t24.json", "auto-cancel"), ("wf04_no_show_check.json", "no-show")],
)
def test_timed_workflows_call_internal_api_with_secret(filename, action):
    nodes = {n["name"]: n for n in load(filename)["nodes"]}
    call = nodes[f"Flask: {action}"]["parameters"]
    assert call["url"].endswith(f"/api/internal/reservations/{{{{ $json.id }}}}/{action}")
    assert call["headerParameters"]["parameters"][0]["name"] == "X-Internal-Secret"
    assert nodes[f"Flask: {action}"]["retryOnFail"] is True


# --- Airtable-Formeln: Expression mit Node auswerten und das Ergebnis prüfen ----------------

def evaluate(expression: str, env: dict[str, str]) -> str:
    inner = expression.removeprefix("={{").removesuffix("}}").strip()
    script = (
        "const $env = " + json.dumps(env) + ";"
        "const $now = { toUTC: () => ({ toISO: () => '2026-11-23T11:00:00.000Z' }) };"
        "process.stdout.write(String(" + inner + "));"
    )
    proc = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=20, check=True)
    return proc.stdout


@pytest.mark.skipif(NODE is None, reason="Node.js nicht installiert")
@pytest.mark.parametrize(
    "filename, demo, expected",
    [
        (
            "wf02_reminder_t48.json",
            "false",
            "AND({status}='PENDING', NOT({reminder_sent_at}), IS_BEFORE({start_at}, "
            "DATEADD(DATETIME_PARSE('2026-11-23T11:00:00.000Z'), 48, 'hours')))",
        ),
        (
            "wf03_deadline_t24.json",
            "true",
            "AND({status}='PENDING', IS_BEFORE({start_at}, DATEADD(DATETIME_PARSE('2026-11-23T11:00:00.000Z'), 24, 'minutes')))",
        ),
        (
            "wf04_no_show_check.json",
            "false",
            "AND({status}='CONFIRMED', NOT({picked_up_at}), IS_BEFORE(DATEADD({start_at}, 120, 'minutes'), "
            "DATETIME_PARSE('2026-11-23T11:00:00.000Z')))",
        ),
    ],
)
def test_airtable_formulas(filename, demo, expected):
    search = next(n for n in load(filename)["nodes"] if n["type"].endswith(".airtable"))
    env = {
        "DEMO_MODE": demo,
        "REMINDER_HOURS_BEFORE": "48",
        "CONFIRM_DEADLINE_HOURS_BEFORE": "24",
        "PICKUP_WINDOW_AFTER_MIN": "120",
    }
    result = evaluate(search["parameters"]["filterByFormula"], env)
    assert result == expected
    assert result.count("(") == result.count(")")

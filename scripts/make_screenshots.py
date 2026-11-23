"""Erzeugt die Screenshots für README und Doku unter ``docs/img/``.

Aufruf:  python -m scripts.make_screenshots   (braucht Google Chrome und Node.js)

Die Szenen werden mit fester Uhrzeit und Demo-Daten nachgestellt (Flask-Testclient),
als HTML gespeichert und mit Chrome im Headless-Modus fotografiert. So entstehen auch
Bilder von Zuständen, die man live erst abwarten müsste (Fach öffnet sich, No-Show-Mail).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from werkzeug.security import generate_password_hash

from app import create_app
from app.config import AppConfig
from app.domain.models import RentalType
from app.repository.memory_repo import InMemoryRepository
from app.seed_data import DEMO_PASSWORD, build_seed, load_into_memory
from app.services.events import RecordingPublisher

ROOT = Path(__file__).resolve().parent.parent
IMG = ROOT / "docs" / "img"
MAIL_JS = ROOT / "n8n" / "src" / "mail_templates.js"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
BERLIN = ZoneInfo("Europe/Berlin")


def berlin(*args) -> datetime:
    return datetime(*args, tzinfo=BERLIN)


class Clock:
    def __init__(self, t: datetime) -> None:
        self.t = t

    def __call__(self) -> datetime:
        return self.t


def shoot(html: str, name: str, width: int, height: int, workdir: Path) -> None:
    html = html.replace('<script src="https://unpkg.com/htmx.org@2.0.4" defer></script>', "")  # kein Server dahinter
    html = re.sub(r'<meta http-equiv="refresh"[^>]*>', "", html)
    page = workdir / f"{name}.html"
    page.write_text(html, encoding="utf-8")
    out = IMG / f"{name}.png"
    subprocess.run(
        [
            CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1",
            f"--window-size={width},{height}", "--virtual-time-budget=6000",
            f"--screenshot={out}", page.as_uri(),
        ],
        check=True, capture_output=True, timeout=60,
    )
    print(f"✓ docs/img/{out.name}")


def render_mail(body: dict) -> str:
    script = (
        "const items=[{json:{body:" + json.dumps(body) + "}}];const $input={all:()=>items};"
        "const CODE=" + json.dumps(MAIL_JS.read_text(encoding="utf-8")) + ";"
        "process.stdout.write(new Function('$input', CODE)($input)[0].json.html);"
    )
    return subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout


def main() -> None:
    if not Path(CHROME).exists() or shutil.which("node") is None:
        raise SystemExit("Google Chrome und Node.js werden benötigt.")
    IMG.mkdir(parents=True, exist_ok=True)

    repo = InMemoryRepository()
    seed = build_seed(password_hasher=lambda p: generate_password_hash(p, method="pbkdf2:sha256:1000"))
    load_into_memory(repo, seed)
    clock = Clock(berlin(2026, 11, 23, 12))
    app = create_app(AppConfig(secret_key="screens"), repo=repo, publisher=RecordingPublisher(), clock=clock)
    app.config.update(WTF_CSRF_ENABLED=False)
    svc = app.extensions["hubrent"].rentals
    lena, jonas = (repo.get_customer_by_email(c.email) for c in seed.customers[:2])
    client = app.test_client()

    # Szenen vorbereiten: Jonas hat eine offene und eine nicht abgeholte Reservierung
    pending = svc.book(jonas.id, "type-TR", "hub-TH", RentalType.DAY, berlin(2026, 11, 28, 10), clock.t)
    no_show = svc.book(jonas.id, "type-PS", "hub-TH", RentalType.DAY, berlin(2026, 11, 22, 10), berlin(2026, 11, 21, 9), binding_accepted=True)
    ns = svc.mark_no_show(no_show.reservation.id, berlin(2026, 11, 22, 12, 5))
    lena_res = svc.book(lena.id, "type-HD", "hub-NK", RentalType.FOUR_HOURS, berlin(2026, 11, 24, 10), clock.t, binding_accepted=True).reservation

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        get = lambda path: client.get(path).get_data(as_text=True)  # noqa: E731

        shoot(get("/"), "01-startseite", 1280, 760, work)
        shoot(get("/geraete"), "02-katalog", 1280, 900, work)

        detail = get("/geraete/type-PS?hub=hub-TH")
        quote = get("/api/verfuegbarkeit?device_type_id=type-PS&hub_id=hub-TH&rental_type=WEEKEND"
                    "&weekend_start=" + berlin(2026, 11, 27, 14).isoformat().replace("+", "%2B"))
        detail = detail.replace('<p class="text-sm text-stone-500">Preis wird berechnet …</p>', quote)
        detail = detail.replace('checked id="rental_type-0"', 'id="rental_type-0"').replace('id="rental_type-2"', 'checked id="rental_type-2"')
        shoot(detail, "03-buchung", 1280, 720, work)

        client.post("/login", data={"email": jonas.email, "password": DEMO_PASSWORD})
        get("/konto")  # Begrüßungsmeldung abholen, damit sie nicht im Bild steht
        shoot(get("/konto"), "04-mein-konto", 1280, 560, work)

        # PIN-Mail vor der Abholung rendern: danach zeigt das System die PIN bewusst nicht mehr
        confirmed = {"event": "reservation.confirmed", **svc.details(repo.get_reservation(lena_res.id))}
        shoot(render_mail(confirmed), "06-mail-pin", 640, 600, work)

        clock.t = berlin(2026, 11, 24, 9, 50)
        opened = client.post("/terminal/hub-NK/abholen", data={"pin": lena_res.pin}).get_data(as_text=True)
        shoot(opened, "05-terminal", 1280, 760, work)
        no_show_body = {"event": "reservation.no_show", **svc.details(ns.reservation), "fee": {"amount": str(ns.fee)}}
        shoot(render_mail(no_show_body), "07-mail-no-show", 640, 480, work)
        reminder = svc.send_reminder(pending.reservation.id, berlin(2026, 11, 26, 11))
        reminder_body = {"event": "reservation.reminder", **svc.details(reminder.reservation, token=reminder.token)}
        shoot(render_mail(reminder_body), "08-mail-erinnerung", 640, 560, work)


if __name__ == "__main__":
    main()

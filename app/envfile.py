"""Minimaler ``.env``-Leser, damit die Skripte auch ohne Docker laufen.

Docker Compose liest die ``.env`` selbst (``env_file``). Lokal sorgt diese
Funktion dafür, dass ``python -m scripts.seed`` dieselben Werte sieht.
Bereits gesetzte Umgebungsvariablen haben Vorrang.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import MutableMapping


def load_env_file(path: str | Path = ".env", env: MutableMapping[str, str] | None = None) -> bool:
    env = os.environ if env is None else env
    path = Path(path)
    if not path.is_file():
        return False
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.removeprefix("export ").partition("=")
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        env.setdefault(key, value)
    return True

"""Prüft, ob das Enddatum erreicht ist (für GitHub Actions).

Schreibt "beendet=true" oder "beendet=false" in $GITHUB_OUTPUT.
"""

from __future__ import annotations

import os

from .config import end_datetime, is_over, load_config


def main() -> None:
    cfg = load_config()
    over = is_over(cfg)
    print(f"Enddatum: {end_datetime(cfg):%d.%m.%Y %H:%M %Z} – beendet: {over}")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"beendet={'true' if over else 'false'}\n")


if __name__ == "__main__":
    main()

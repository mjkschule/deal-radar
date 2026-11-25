"""Prüft, ob das Enddatum erreicht ist (für GitHub Actions).

Schreibt "beendet=true" oder "beendet=false" in $GITHUB_OUTPUT.
"""

from __future__ import annotations

import os

from .config import end_datetime, is_over, load_config


def main() -> None:
    cfg = load_config()
    over = is_over(cfg)  # nur bei nach_ende: aus; sonst Wunschlisten-Modus (1x täglich)
    end = end_datetime(cfg)
    print(f"Enddatum: {end:%d.%m.%Y %H:%M %Z} – " if end else "Enddatum: nie – ", end="")
    print(f"nach dem Ende: {cfg.get('nach_ende', 'wunschliste')} – abschalten: {over}")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"beendet={'true' if over else 'false'}\n")


if __name__ == "__main__":
    main()

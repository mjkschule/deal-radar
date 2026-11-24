"""Speichern im Repo: data/state.json, data/verlauf.json, data/verlauf.csv."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from .models import Offer

CSV_FIELDS = ["zeit", "produkt_id", "quelle", "shop", "titel", "preis", "versand",
              "vergleichspreis", "status", "grund", "url"]


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except json.JSONDecodeError:
        # Beschädigte Datei nicht überschreiben, sondern sichern
        path.rename(path.with_suffix(".kaputt.json"))
        return default


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def append_csv(path: Path, now_iso: str, offers: list[Offer]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with path.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, delimiter=";")
        if new:
            w.writeheader()
        for o in offers:
            if o.price is None:
                continue
            w.writerow({
                "zeit": now_iso, "produkt_id": o.product_id, "quelle": o.source, "shop": o.shop,
                "titel": o.title[:200], "preis": f"{o.price:.2f}".replace(".", ","),
                "versand": "" if o.shipping is None else f"{o.shipping:.2f}".replace(".", ","),
                "vergleichspreis": f"{o.compare_price:.2f}".replace(".", ","),
                "status": o.status, "grund": o.status_reason, "url": o.url,
            })


def append_history(history: dict, product_id: str, now_iso: str, best: float | None, low: float | None,
                   max_points: int = 500) -> None:
    """Ein Punkt pro Lauf und Produkt für die Sparkline."""
    pts = history.setdefault(product_id, [])
    pts.append({"t": now_iso, "bester": best, "tief": low})
    del pts[:-max_points]

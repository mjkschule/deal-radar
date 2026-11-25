"""Einmalige Bereinigungen gespeicherter Daten (laufen im Suchlauf, damit es keine Konflikte mit den
Commits des Radars gibt). Jede Bereinigung läuft genau einmal (Merker in state["bereinigt"]).

wunschpreis (26.11.2026): Bis dahin wurden Bestätigungs-Mails des idealo-Preisweckers als Angebot
gelesen – der Preis darin war dein WUNSCHPREIS. Entfernt werden deshalb alle bisher gespeicherten
Postfach-Angebote; Tiefstpreis und Preisverlauf werden ohne sie neu berechnet. Echte Preisalarme
kommen beim nächsten Lesen des Postfachs (letzte 14 Tage) korrekt wieder.
"""

from __future__ import annotations

import csv
import datetime as dt
from pathlib import Path

from .storage import CSV_FIELDS

QUELLE = "postfach"


def _num(v: str) -> float | None:
    try:
        return float(v.replace(",", ".")) if v else None
    except ValueError:
        return None


def drop_postfach_offers(state: dict, history: dict, csv_path: Path, aktuell_stunden: int = 48) -> list[str]:
    done = state.setdefault("bereinigt", {})
    if done.get("wunschpreis"):
        return []
    notes = []
    affected = set()
    for pid, store in (state.get("angebote") or {}).items():
        for k in [k for k, d in store.items() if d.get("source") == QUELLE]:
            store.pop(k)
            affected.add(pid)
    rows = []
    if csv_path.exists():
        with csv_path.open(encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f, delimiter=";"))
        bad = [r for r in rows if r.get("quelle") == QUELLE]
        affected |= {r["produkt_id"] for r in bad}
        if bad:
            rows = [r for r in rows if r.get("quelle") != QUELLE]
            with csv_path.open("w", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else CSV_FIELDS, delimiter=";")
                w.writeheader()
                w.writerows(rows)
    lows = state.get("tiefstpreis") or {}
    for pid in [p for p, low in lows.items() if low and low.get("source") == QUELLE]:
        affected.add(pid)
    # Tiefstpreis und Verlauf der betroffenen Produkte aus dem Protokoll (verlauf.csv) neu berechnen
    for pid in sorted(affected):
        ok = [(dt.datetime.fromisoformat(r["zeit"]), _num(r["vergleichspreis"]), r) for r in rows
              if r["produkt_id"] == pid and r.get("status") == "ok" and _num(r["vergleichspreis"]) is not None]
        low = lows.get(pid)
        if low and low.get("source") == QUELLE:
            if ok:
                t, v, r = min(ok, key=lambda x: x[1])
                lows[pid] = {"product_id": pid, "source": r["quelle"], "shop": r["shop"], "title": r["titel"],
                             "url": r["url"], "price": _num(r["preis"]), "shipping": _num(r["versand"]),
                             "vergleichspreis": v, "status": "ok", "last_seen": r["zeit"], "first_seen": r["zeit"],
                             "hints": [], "leasing": {}, "abzuege": []}
            else:
                lows.pop(pid)
        mine = sorted(((dt.datetime.fromisoformat(r["zeit"]), r) for r in rows if r["produkt_id"] == pid),
                      key=lambda x: x[0])
        for pt in history.get(pid, []):
            t = dt.datetime.fromisoformat(pt["t"])
            latest: dict[str, tuple] = {}  # je Angebot (Shop + Link) der letzte Stand bis t – wie current_best
            for ts, r in mine:
                if ts > t:
                    break
                latest[f"{r['shop'].lower()}|{r['url']}"] = (ts, r)
            window = [_num(r["vergleichspreis"]) for ts, r in latest.values()
                      if r.get("status") == "ok" and ts >= t - dt.timedelta(hours=aktuell_stunden)
                      and _num(r["vergleichspreis"]) is not None]
            before = [v for ts, v, _ in ok if ts <= t]
            pt["bester"] = min(window) if window else None
            pt["tief"] = min(before) if before else None
        shop_prices = (state.get("gemeldet_shop_preis") or {}).get(pid)
        if shop_prices:
            shop_prices[:] = [x for x in shop_prices if "preisalarm" not in x]
        notes.append(pid)
    state["warteschlange"] = [w for w in state.get("warteschlange") or [] if "Preisalarm" not in (w.get("shop") or "")]
    done["wunschpreis"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    return notes

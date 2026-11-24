"""Deal-Score 0–100 (vorläufige Version, wird in Phase 4 verfeinert).

Verglichen wird NUR mit dem eigenen Preisverlauf des Radars – nie mit UVP oder
Streichpreisen der Shops:

    Score = 50 + 250 × (Median − Preis) / Median   (+10, wenn Preis ≤ Allzeit-Tiefstpreis)

    Preis = Median            -> 50
    Preis 10 % unter Median   -> 75
    Preis 20 % unter Median   -> 100
    Preis 10 % über Median    -> 25

Der Median stammt aus den besten Preisen der letzten 90 Tage. Gibt es weniger als
MIN_PUNKTE Messpunkte, ist der Score unbekannt (None, Anzeige „–“).
"""

from __future__ import annotations

import datetime as dt
import statistics

MIN_PUNKTE = 5
TAGE = 90


def history_median(points: list[dict], now: dt.datetime, days: int = TAGE) -> tuple[float | None, int]:
    """Median der besten Preise im Zeitraum und Anzahl der Messpunkte."""
    cutoff = now - dt.timedelta(days=days)
    vals = []
    for p in points or []:
        if p.get("bester") is None:
            continue
        try:
            if dt.datetime.fromisoformat(p["t"]) < cutoff:
                continue
        except (KeyError, ValueError):
            continue
        vals.append(float(p["bester"]))
    return (statistics.median(vals) if vals else None), len(vals)


def deal_score(price: float | None, points: list[dict], alltime_low: float | None, now: dt.datetime) -> int | None:
    if price is None:
        return None
    median, n = history_median(points, now)
    if median is None or n < MIN_PUNKTE or median <= 0:
        return None
    score = 50 + 250 * (median - price) / median
    if alltime_low is not None and price <= alltime_low + 0.005:
        score += 10
    return int(round(max(0, min(100, score))))

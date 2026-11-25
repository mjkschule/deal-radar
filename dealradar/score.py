"""Deal-Score 0–100.

Verglichen wird NUR mit dem eigenen Preisverlauf des Radars – nie mit UVP oder
Streichpreisen der Shops ("statt 119 €" wird ignoriert). Verglichen wird der Effektivpreis
(inkl. Versand, abzüglich Gutschein usw.).

    Score = 50 + 250 × (Median − Preis) / Median
            + 10, wenn Preis ≤ Allzeit-Tiefstpreis
            +  5, wenn Preis höchstens 2 % über dem Allzeit-Tiefstpreis

    Preis = Median            -> 50
    Preis 10 % unter Median   -> 75
    Preis 20 % unter Median   -> 100
    Preis 10 % über Median    -> 25

Der Median stammt aus den besten Preisen der letzten 90 Tage (ein Punkt je Lauf). Gibt es weniger
als MIN_PUNKTE Messpunkte, ist der Score unbekannt (None, Anzeige „–“).
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
    elif alltime_low is not None and price <= alltime_low * 1.02:
        score += 5
    return int(round(max(0, min(100, score))))


def explain(price: float | None, points: list[dict], alltime_low: float | None, now: dt.datetime) -> str:
    """Kurze Begründung für die Anzeige, z. B. 'Median 90 Tage: 99,00 € (36 Messungen) · Tiefstpreis: 89,00 €'."""
    median, n = history_median(points, now)
    fmt = lambda v: f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " €"
    if median is None or n < MIN_PUNKTE:
        return f"noch zu wenig Preisverlauf ({n} von {MIN_PUNKTE} Messungen)"
    out = f"Median 90 Tage: {fmt(median)} ({n} Messungen)"
    if alltime_low is not None:
        out += f" · Tiefstpreis: {fmt(alltime_low)}"
    return out

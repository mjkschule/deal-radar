"""Datenquellen. Jede Quelle ist ein eigenes Modul mit:

    NAME: str                      – Anzeigename
    def fetch(products, ctx) -> list[Offer]

Wirft eine Quelle einen Fehler, laufen alle anderen weiter (siehe main.py).
Eine Quelle kann `Skipped` werfen, wenn sie absichtlich nicht läuft (z. B. fehlende Schlüssel).
"""

from __future__ import annotations

import datetime as dt
import html
import re
from dataclasses import dataclass, field

from ..http import Http


class Skipped(Exception):
    """Quelle absichtlich übersprungen (z. B. keine API-Schlüssel)."""


@dataclass
class Context:
    http: Http
    config: dict
    env: dict
    now: dt.datetime
    cache: dict = field(default_factory=dict)   # dauerhafter Zwischenspeicher (state.json)
    notes: list[str] = field(default_factory=list)  # Hinweise für den Quellenstatus


def strip_tags(text: str) -> str:
    """HTML entfernen und Leerraum zusammenfassen."""
    t = re.sub(r"<(script|style)\b.*?</\1>", " ", text or "", flags=re.S | re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", html.unescape(t)).strip()


def all_sources():
    """Reihenfolge = Reihenfolge der Abfrage."""
    from . import dealblogs, ebay, hersteller, leasingmarkt, mydealz, postfach, shop, sparneuwagen

    return [mydealz, *dealblogs.SOURCES, ebay, shop, hersteller, postfach, leasingmarkt, sparneuwagen]

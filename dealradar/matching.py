"""Passt ein Angebotstitel zu einem Produkt? Ausschlusswörter, Mindestwerte, Hinweise."""

from __future__ import annotations

import html
import re

from .config import Product


def normalize(text: str) -> str:
    """Kleinbuchstaben, Satzzeichen weg, 24" -> 24 zoll."""
    t = html.unescape(text or "").lower()
    t = re.sub(r"(\d)\s*(?:\"|″|”|“|''|-?zoll)", r"\1 zoll", t)
    t = re.sub(r"[^0-9a-zäöüß]+", " ", t)
    return f" {t.strip()} "


def _compact(text: str) -> str:
    return normalize(text).replace(" ", "")


def _phrase_hits(phrase: str, norm_text: str, compact_text: str) -> bool:
    words = normalize(phrase).split()
    if not words:
        return False
    tokens = set(norm_text.split())
    if all(w in tokens for w in words):
        return True
    # Modellnummern auch ohne/mit Leerzeichen erkennen ("DHP 490 RFX3")
    comp = "".join(words)
    return len(comp) >= 5 and any(c.isdigit() for c in comp) and comp in compact_text


def matches(product: Product, text: str) -> bool:
    """True, wenn mindestens ein Suchbegriff des Produkts im Text vorkommt."""
    norm = normalize(text)
    comp = norm.replace(" ", "")
    return any(_phrase_hits(p, norm, comp) for p in product.suchbegriffe)


def excluded_word(product: Product, text: str) -> str | None:
    """Gibt das erste gefundene Ausschlusswort zurück (oder None)."""
    norm = normalize(text)
    comp = norm.replace(" ", "")
    for word in product.ausschluss:
        nw = normalize(word)
        if nw.strip() and nw in norm:
            return word
        c = nw.replace(" ", "")
        if len(c) >= 5 and any(ch.isdigit() for ch in c) and c in comp:
            return word
    return None


def check_minimums(product: Product, text: str) -> tuple[str | None, list[str]]:
    """Prüft Mindestwerte wie {Hz: 75}.

    Rückgabe: (Grund für Aussortieren oder None, Liste von Prüf-Hinweisen)
    """
    hints: list[str] = []
    t = html.unescape(text or "")
    for unit, minimum in product.mindestwerte.items():
        rx = re.compile(rf"(\d+(?:[.,]\d+)?)\s*{re.escape(unit)}\b", re.I)
        values = []
        for m in rx.finditer(t):
            try:
                values.append(float(m.group(1).replace(",", ".")))
            except ValueError:
                pass
        if not values:
            hints.append(f"bitte prüfen: {unit} ≥ {minimum:g}")
        elif max(values) < minimum:
            return f"nur {max(values):g} {unit} (mind. {minimum:g})", hints
    return None, hints


def missing_required(product: Product, text: str) -> list[str]:
    """Hinweise für Pflichtwörter, die im Text nicht vorkommen."""
    norm = normalize(text)
    out = []
    for word in product.pflicht_hinweise:
        if normalize(word) not in norm:
            out.append(f"bitte prüfen: {word}")
    return out

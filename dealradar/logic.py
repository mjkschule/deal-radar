"""Bewertung der Angebote: guter Deal?, verdächtig?, schon gemeldet?

Regeln (siehe config.yaml -> regeln):
  * Melden, wenn Preis <= Zielpreis ODER mind. 10 % unter dem bisherigen Tiefstpreis.
  * Ausschlusswörter / zu kleine Mindestwerte -> "ausgeschlossen" (nicht melden)
  * Preis < 40 % des Medians -> "verdächtig" (nicht melden)
  * Leasing: falsche Laufzeit, zu wenig km, Gewerbe, zu hohe Sonderzahlung -> "nicht passend"
  * Gleiches Angebot (Shop + Link bzw. Shop + Preis) nur einmal; erneut nur, wenn billiger.
"""

from __future__ import annotations

import datetime as dt
import re
import statistics
from dataclasses import dataclass

from . import bewertung
from .config import Product
from .matching import check_minimums, excluded_word, missing_required
from .models import AUSGESCHLOSSEN, NICHT_PASSEND, NICHT_VERFUEGBAR, OK, VERDAECHTIG, Offer


@dataclass
class Alert:
    product: Product
    offer: Offer
    previous_low: float | None
    reasons: list[str]


def _fmt(v: float) -> str:
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def classify(product: Product, offer: Offer) -> None:
    """Setzt offer.status (ausgeschlossen / nicht passend) und ergänzt Hinweise."""
    if offer.status == NICHT_VERFUEGBAR:
        return
    text = f"{offer.title} {offer.text}"
    word = excluded_word(product, offer.title)
    if word:
        offer.status, offer.status_reason = AUSGESCHLOSSEN, f"Ausschlusswort „{word}“"
        return
    reason, hints = check_minimums(product, text)
    if reason:
        offer.status, offer.status_reason = AUSGESCHLOSSEN, reason
        return
    if bewertung.ean_mismatch(product.ean, offer.ean):
        offer.status, offer.status_reason = AUSGESCHLOSSEN, f"andere EAN ({offer.ean})"
        return
    offer.hints = _unique(offer.hints + hints + missing_required(product, text) + bewertung.condition_hints(text))
    if "gebraucht/B-Ware" in offer.hints and not product.b_ware:
        offer.status, offer.status_reason = AUSGESCHLOSSEN, "B-Ware/gebraucht (beim Produkt b_ware: true setzen)"
        return
    offer.vertrauen = bewertung.trust_flags(offer)

    if product.is_leasing:
        cfg = product.leasing
        lease = offer.leasing
        months, min_km = cfg.get("laufzeit_monate"), cfg.get("min_km_jahr")
        max_down = cfg.get("max_sonderzahlung")
        if lease.get("gewerbe"):
            offer.status, offer.status_reason = NICHT_PASSEND, "nur für Gewerbekunden"
        elif months and lease.get("monate") and lease["monate"] != months:
            offer.status, offer.status_reason = NICHT_PASSEND, f"Laufzeit {lease['monate']} statt {months} Monate"
        elif min_km and lease.get("km") and lease["km"] < min_km:
            offer.status, offer.status_reason = NICHT_PASSEND, f"nur {lease['km']:,} km/Jahr".replace(",", ".")
        elif max_down is not None and lease.get("sonderzahlung") is not None and lease["sonderzahlung"] > max_down:
            offer.status, offer.status_reason = NICHT_PASSEND, f"Sonderzahlung {_fmt(lease['sonderzahlung'])} €"
        extra = []
        if lease.get("monate") is None:
            extra.append("Laufzeit unbekannt")
        if lease.get("km") is None:
            extra.append("km/Jahr unbekannt")
        if lease.get("sonderzahlung") is None:
            extra.append("Sonderzahlung unbekannt")
        if lease.get("bereitstellung") is None:
            extra.append("Bereitstellungskosten unbekannt")
        offer.hints = _unique(offer.hints + extra)


def _unique(items: list[str]) -> list[str]:
    out = []
    for i in items:
        if i not in out:
            out.append(i)
    return out


def reference_median(product: Product, offers: list[Offer], stored: dict) -> float:
    """Bezugswert für "verdächtig": Median aus aktuellen + gespeicherten Preisen.

    Bei wenig Daten zählt der Zielpreis mit. Der Bezugswert ist höchstens der Zielpreis:
    Bei allgemeinen Suchen ("Multifunktionsdrucker") streuen die Preise stark, ein
    Median von z. B. 160 € würde sonst ein echtes 39-€-Angebot als verdächtig markieren.
    """
    values = [o.compare_price for o in offers if o.status in (OK, VERDAECHTIG) and o.compare_price]
    values += [d.get("vergleichspreis") for d in stored.values()
               if d.get("status") in (OK, VERDAECHTIG) and d.get("vergleichspreis")]
    if len(values) < 5:
        values.append(product.zielpreis)
    return min(statistics.median(values), product.zielpreis)


# Welche Quelle "gewinnt", wenn mehrere dasselbe Angebot melden (kleiner = besser):
# direkt beim Shop gelesen > offizielle API > Community > Blogs > Postfach
_QUELLEN_RANG = {"shop": 0, "hersteller": 0, "ebay": 1, "leasingmarkt": 1, "mydealz": 2, "sparneuwagen": 2,
                 "postfach": 4}


def norm_shop(name: str) -> str:
    """'www.Media-Markt.de' -> 'mediamarkt', 'Amazon.de' -> 'amazon'"""
    t = (name or "").lower().strip()
    t = re.sub(r"^https?://", "", t).removeprefix("www.")
    t = re.sub(r"\.(de|com|net|eu|at|ch)(/.*)?$", "", t)
    return re.sub(r"[^a-z0-9äöüß]", "", t)


def merge_duplicates(offers: list[Offer]) -> list[Offer]:
    """Gleiches Angebot aus mehreren Quellen (gleicher Shop + gleicher Preis inkl. Versand)
    nur einmal behalten; die anderen Quellen stehen in `weitere_quellen`."""
    groups: dict[tuple, list[Offer]] = {}
    out: list[Offer] = []
    for o in offers:
        if o.compare_price is None or o.leasing:
            out.append(o)
            continue
        groups.setdefault((o.product_id, norm_shop(o.shop), round(o.compare_price, 2)), []).append(o)
    for group in groups.values():
        group.sort(key=lambda o: (_QUELLEN_RANG.get(o.source, 3), o.shipping is None))
        keep = group[0]
        others = [o.source for o in group[1:] if o.source != keep.source]
        keep.weitere_quellen = sorted(set(keep.weitere_quellen + others))
        for o in group[1:]:  # Hinweise der anderen (z. B. "nur mit Prime") nicht verlieren
            keep.hints = _unique(keep.hints + [h for h in o.hints if h != "Versand unbekannt"])
        if keep.shipping is not None and "Versand unbekannt" in keep.hints:
            keep.hints.remove("Versand unbekannt")
        out.append(keep)
    return out


def evaluate(product: Product, offers: list[Offer], state: dict, rules: dict,
             after_classify=None) -> list[Alert]:
    """Bewertet die Angebote eines Produkts. Ändert nur offer.status, nicht den state
    (gemeldet wird erst nach erfolgreichem Versand mit mark_reported).
    after_classify(offers): optional, z. B. abgelaufene/ausgeblendete Angebote markieren."""
    for o in offers:
        classify(product, o)
    if after_classify:
        after_classify(offers)
    stored = state.setdefault("angebote", {}).get(product.id, {})
    median = reference_median(product, offers, stored)
    limit = rules.get("verdacht_unter_median", 0.4)
    for o in offers:
        if o.status == OK and o.compare_price is not None and o.compare_price < limit * median:
            o.status, o.status_reason = VERDAECHTIG, f"unter {int(limit * 100)} % des Medians ({_fmt(median)} €)"

    low = (state.get("tiefstpreis") or {}).get(product.id)
    prev_low = low.get("vergleichspreis") if low else None
    discount = rules.get("rabatt_vs_tiefstpreis", 0.10)
    reported = state.setdefault("gemeldet", {})
    shop_prices = set(state.setdefault("gemeldet_shop_preis", {}).get(product.id, []))

    alerts: list[Alert] = []
    for o in sorted((o for o in offers if o.status == OK and o.compare_price is not None),
                    key=lambda o: o.compare_price):
        reasons = []
        if o.target_value is not None and o.target_value <= product.zielpreis:
            reasons.append("Zielpreis erreicht")
        if prev_low and o.compare_price <= prev_low * (1 - discount):
            reasons.append(f"mind. {int(discount * 100)} % unter bisherigem Tiefstpreis")
        if not reasons:
            continue
        if o.key in reported and o.compare_price >= reported[o.key]:
            continue  # schon gemeldet und nicht billiger geworden
        if shop_price_key(o) in shop_prices:
            continue  # gleicher Shop + gleicher Preis schon gemeldet
        shop_prices.add(shop_price_key(o))  # auch innerhalb dieses Laufs nur einmal
        alerts.append(Alert(product, o, prev_low, reasons))
    return alerts


def shop_price_key(o: Offer) -> str:
    return f"{o.shop.lower()}|{o.price:.2f}"


def mark_reported(state: dict, alert: Alert) -> None:
    o = alert.offer
    state.setdefault("gemeldet", {})[o.key] = o.compare_price
    lst = state.setdefault("gemeldet_shop_preis", {}).setdefault(o.product_id, [])
    entry = shop_price_key(o)
    if entry not in lst:
        lst.append(entry)


def remember(product: Product, offers: list[Offer], state: dict, now: dt.datetime, rules: dict) -> None:
    """Speichert Angebote (für Startseite & Median) und aktualisiert den Tiefstpreis."""
    store = state.setdefault("angebote", {}).setdefault(product.id, {})
    iso = now.isoformat(timespec="seconds")
    for o in offers:
        if o.price is None:
            continue
        old = store.get(o.key)
        o.first_seen = old.get("first_seen", iso) if old and old.get("vergleichspreis") == o.compare_price else iso
        o.last_seen = iso
        store[o.key] = o.to_dict()
    # Alte Einträge vergessen
    cutoff = now - dt.timedelta(days=rules.get("vergessen_nach_tagen", 7))
    for k in [k for k, d in store.items() if dt.datetime.fromisoformat(d["last_seen"]) < cutoff]:
        store.pop(k)
    # Tiefstpreis seit Start (nur "ok"-Angebote)
    oks = [o for o in offers if o.status == OK and o.compare_price is not None]
    if oks:
        best = min(oks, key=lambda o: o.compare_price)
        lows = state.setdefault("tiefstpreis", {})
        cur = lows.get(product.id)
        if not cur or best.compare_price < cur["vergleichspreis"]:
            lows[product.id] = best.to_dict()


def current_best(product: Product, state: dict, now: dt.datetime, rules: dict) -> dict | None:
    """Günstigstes "ok"-Angebot, das in den letzten X Stunden gesehen wurde."""
    store = (state.get("angebote") or {}).get(product.id, {})
    cutoff = now - dt.timedelta(hours=rules.get("aktuell_stunden", 48))
    fresh = [d for d in store.values() if d.get("status") == OK and d.get("vergleichspreis") is not None
             and dt.datetime.fromisoformat(d["last_seen"]) >= cutoff]
    return min(fresh, key=lambda d: d["vergleichspreis"]) if fresh else None


def offers_by_status(product: Product, state: dict, now: dt.datetime, rules: dict, statuses: tuple) -> list[dict]:
    store = (state.get("angebote") or {}).get(product.id, {})
    cutoff = now - dt.timedelta(hours=rules.get("aktuell_stunden", 48))
    rows = [d for d in store.values() if d.get("status") in statuses
            and dt.datetime.fromisoformat(d["last_seen"]) >= cutoff]
    return sorted(rows, key=lambda d: d.get("vergleichspreis") or 0)

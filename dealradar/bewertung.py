"""Bewertung eines Angebots (Phase 4): Effektivpreis, Bedingungen, Vertrauen, Kaufen-oder-Warten.

Effektivpreis = Preis + Versand − Gutschein − Cashback − Zahlungsrabatt
  * Gutschein: aus dem Deal-Postfach, nur wenn Shop passt, Mindestbestellwert erreicht und gültig
  * Cashback / Zahlungsrabatt: aus config.yaml -> effektivpreis (derzeit leer = nicht eingerechnet)
  Der Rechenweg steht in Meldung und Startseite.

Bedingungen (gelb, aber Deal bleibt): Neukunden, Mitgliedschaft (Prime, Club …), nur App, nur lokal,
Mindestbestellwert, Gutschein-Code nötig.
Vertrauensprüfung (gelb "prüfen"): Marketplace-Händler, schwache Händlerbewertung, Versand aus dem
Ausland, lange Lieferzeit, keine Rückgabe. Preis < 40 % des Medians -> "verdächtig" (logic.py).
"""

from __future__ import annotations

import datetime as dt
import re

from .models import Offer

# ---------------------------------------------------------------- Effektivpreis


def _eur(v: float) -> str:
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " €"


def _norm(name: str) -> str:
    from .logic import norm_shop  # (Import hier, um Kreisbezug zu vermeiden)
    return norm_shop(name)


def apply_effective(offers: list[Offer], cfg: dict, coupons: list[dict], now: dt.datetime) -> None:
    """Trägt Abzüge (Gutschein, Cashback, Zahlart) in die Angebote ein (nicht bei Leasing)."""
    eff = cfg.get("effektivpreis") or {}
    cashback = {_norm(k): float(v) for k, v in (eff.get("cashback") or {}).items() if v}
    pay_pct = float(eff.get("zahlungsrabatt_prozent") or 0)
    pay_shops = {_norm(s) for s in eff.get("zahlungsrabatt_nur_shops") or []}
    use_coupons = eff.get("gutscheine_aus_postfach", True)
    today = now.date().isoformat()
    for o in offers:
        if o.leasing or o.price is None:
            continue
        o.abzuege = []
        shop = _norm(o.shop)
        if use_coupons:
            best = None
            for c in coupons:
                if _norm(c.get("domain") or c.get("shop", "")) != shop:
                    continue
                if c.get("gueltig_bis") and c["gueltig_bis"] < today:
                    continue
                if c.get("mindestbestellwert") and o.price < c["mindestbestellwert"]:
                    continue
                value = (round(o.price * c["rabatt_prozent"] / 100, 2) if c.get("rabatt_prozent")
                         else float(c.get("rabatt_euro") or 0))
                if value > 0 and (best is None or value > best[0]):
                    what = f'{c["rabatt_prozent"]} %' if c.get("rabatt_prozent") else _eur(value)
                    best = (min(value, o.price), f"Gutschein {what} (Code in deiner Mail vom "
                                                 f"{dt.date.fromisoformat(c['mail_vom']).strftime('%d.%m.')})")
            if best:
                o.abzuege.append({"art": "gutschein", "betrag": best[0], "text": best[1]})
        if shop in cashback:
            base = o.price - sum(a["betrag"] for a in o.abzuege)
            o.abzuege.append({"art": "cashback", "betrag": round(base * cashback[shop] / 100, 2),
                              "text": f"Cashback {cashback[shop]:g} %"})
        if pay_pct and (not pay_shops or shop in pay_shops):
            base = o.price + (o.shipping or 0) - sum(a["betrag"] for a in o.abzuege)
            o.abzuege.append({"art": "zahlart", "betrag": round(base * pay_pct / 100, 2),
                              "text": f"Zahlungsrabatt {pay_pct:g} %"})


def rechenweg(o: Offer | dict) -> str:
    """'79,99 € + 4,95 € Versand − 16,00 € Gutschein 20 % (…) = 68,94 €' – leer, wenn nichts dazukommt."""
    d = o if isinstance(o, dict) else o.to_dict()
    price, ship, cuts = d.get("price"), d.get("shipping"), d.get("abzuege") or []
    if price is None or d.get("leasing") or (not ship and not cuts):
        return ""
    parts = [_eur(price)]
    if ship:
        parts.append(f"+ {_eur(ship)} Versand")
    parts += [f"− {_eur(a['betrag'])} {a['text']}" for a in cuts]
    total = price + (ship or 0) - sum(a["betrag"] for a in cuts)
    return " ".join(parts) + f" = {_eur(round(total, 2))}"


# ---------------------------------------------------------------- Bedingungen & Vertrauen

BEDINGUNGEN = {"Gutschein/Code nötig", "nur für Neukunden", "evtl. nur per App", "Newsletter-Anmeldung nötig",
               "evtl. nur mit Prime", "evtl. nur lokal/in der Filiale", "Mitgliedschaft nötig", "Mindestbestellwert"}

_MBW_RE = re.compile(r"mindestbestellwert|\bmbw\b|ab\s*\d+\s*(?:€|euro)\s*(?:bestellwert|einkaufswert|warenwert)", re.I)
_MEMBER_RE = re.compile(r"mitglied|member|club-?preis|plus-?mitglied|payback-?karte|nur mit \w+card|\bvip\b", re.I)
_ABROAD_RE = re.compile(r"versand aus (?:china|hong ?kong|asien|dem ausland|uk|großbritannien|usa|polen|tschechien)|"
                        r"\bimport\b|eu-?import|aus china|china-?lager|ausländische[rn]? händler", re.I)
_DELIVERY_RE = re.compile(r"lieferzeit[:\s]*(?:ca\.\s*)?(\d+)\s*(?:-\s*\d+\s*)?(tage|werktage|wochen)|"
                          r"(\d+)\s*(?:-\s*\d+\s*)?(wochen)\s*lieferzeit", re.I)
_NO_RETURN_RE = re.compile(r"keine rückgabe|rückgabe ausgeschlossen|kein rückgaberecht|vom umtausch ausgeschlossen", re.I)
_RATING_RE = re.compile(r"\((\d{2,3}(?:[.,]\d)?) % positiv\)")


def condition_hints(text: str) -> list[str]:
    """Zusätzliche Bedingungen, die prices.detect_hints noch nicht kennt."""
    out = []
    if _MEMBER_RE.search(text or ""):
        out.append("Mitgliedschaft nötig")
    if _MBW_RE.search(text or ""):
        out.append("Mindestbestellwert")
    return out


def trust_flags(o: Offer) -> list[str]:
    """Gelbe Warnungen der Vertrauensprüfung."""
    text = f"{o.title} {o.text} {' '.join(o.hints)}"
    flags = []
    if "Marketplace-Händler" in o.hints:
        flags.append("Marketplace-Händler – Verkäufer prüfen")
    m = _RATING_RE.search(text)
    if m and float(m.group(1).replace(",", ".")) < 97:
        flags.append(f"Händlerbewertung nur {m.group(1)} % positiv")
    if _ABROAD_RE.search(text) or any(h.startswith("Versand aus ") for h in o.hints):
        flags.append("Versand aus dem Ausland")
    m = _DELIVERY_RE.search(text)
    if m:
        n = int(m.group(1) or m.group(3))
        unit = (m.group(2) or m.group(4)).lower()
        days = n * 7 if unit.startswith("woche") else n
        if days > 7:
            flags.append(f"lange Lieferzeit ({n} {unit})")
    if _NO_RETURN_RE.search(text):
        flags.append("keine Rückgabe möglich")
    return flags


def ean_mismatch(product_ean: str, offer_ean: str) -> bool:
    a, b = (product_ean or "").strip().lstrip("0"), (offer_ean or "").strip().lstrip("0")
    return bool(a and b and a != b)


# ---------------------------------------------------------------- Kaufen oder warten

def aktionstage(cfg: dict, year: int) -> dict[str, dt.date]:
    raw = cfg.get("aktionstage") or {}
    def d(key, default):
        return dt.date.fromisoformat(str(raw.get(key, default)))
    return {"black_friday": d("black_friday", f"{year}-11-27"), "cyber_monday": d("cyber_monday", f"{year}-11-30"),
            "weihnachten": d("weihnachten", f"{year}-12-24")}


def buy_or_wait(cfg: dict, now: dt.datetime, score: int | None, target_reached: bool) -> str:
    """Kurzer Hinweis: kaufen, warten oder abwägen – mit Blick auf Black Friday, Cyber Monday, Weihnachten."""
    days = aktionstage(cfg, now.year)
    today = now.date()
    bf, cm, xmas = days["black_friday"], days["cyber_monday"], days["weihnachten"]
    if target_reached or (score is not None and score >= 85):
        why = "Zielpreis erreicht" if target_reached else f"sehr guter Preis (Score {score})"
        return f"✅ Kaufen: {why}"
    if today < bf:
        n = (bf - today).days
        return f"⏳ Eher warten: Black Friday ist in {n} Tag{'en' if n != 1 else ''} ({bf:%d.%m.})"
    if today < cm:
        return f"⏳ Eher warten: Cyber Monday ({cm:%d.%m.}) bringt oft noch einmal Deals"
    if today == cm:
        return "🤔 Heute ist Cyber Monday – danach wird es bis Weihnachten selten günstiger"
    if today <= xmas - dt.timedelta(days=4):
        return f"🤔 Bis Weihnachten selten günstiger – für Lieferung bis {xmas:%d.%m.} spätestens um den " \
               f"{xmas - dt.timedelta(days=4):%d.%m.} bestellen"
    return ""

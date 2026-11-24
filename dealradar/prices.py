"""Preis-Parser: wandelt Texte wie "1.234,56 €" oder "99 €/mtl., 36 Mon." in Zahlen um.

Alle Funktionen sind reine Funktionen ohne Netzwerkzugriff und deshalb gut testbar
(siehe tests/test_prices.py).
"""

from __future__ import annotations

import html
import re

_SPACES = "    "

# Eine "Zahl" im Text: Ziffern mit Tausender-/Dezimaltrennern, optional ",-"
_NUM = r"\d[\d.,   ]*(?:,-|,–|\.-)?"
_CUR = r"(?:€|eur\b|euro\b)"

_MONEY_RE = re.compile(
    rf"(?:{_CUR}\s*(?P<a>{_NUM}))|(?:(?P<b>{_NUM})\s*{_CUR})",
    re.IGNORECASE,
)


def to_number(raw: str | None, german: bool = True) -> float | None:
    """Wandelt eine Zahl als Text in float um.

    german=True: "26.930" = 26930 (Punkt als Tausendertrenner), "19,99" = 19.99
    german=False (z. B. JSON-LD): "199.9" = 199.9
    """
    if raw is None:
        return None
    s = str(raw).strip()
    for ch in _SPACES + "'":
        s = s.replace(ch, "")
    s = re.sub(r"[,.][-–]+$", "", s)  # "19,-" -> "19"
    s = s.rstrip(".,")
    if not s or not re.fullmatch(r"[\d.,]+", s):
        return None
    if "," in s and "." in s:
        # Der zuletzt stehende Trenner ist der Dezimaltrenner
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        head, _, tail = s.rpartition(",")
        if s.count(",") == 1 and len(tail) in (1, 2):
            s = head + "." + tail
        else:
            s = s.replace(",", "")
    elif "." in s:
        head, _, tail = s.rpartition(".")
        if s.count(".") > 1 or (german and len(tail) == 3):
            s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return None


def parse_price(text: str | None) -> float | None:
    """Erster Geldbetrag im Text, z. B. "nur 184,90 € statt 249 €" -> 184.9."""
    if not text:
        return None
    t = html.unescape(text)
    if re.search(r"\b(kostenlos|gratis|for free|geschenkt)\b", t, re.I) and not _MONEY_RE.search(t):
        return 0.0
    for m in _MONEY_RE.finditer(t):
        val = to_number(m.group("a") or m.group("b"))
        if val is not None:
            return val
    return None


_FREE_SHIPPING = re.compile(
    r"versandkostenfrei|versandfrei|kostenlose[rn]?\s+versand|gratis[-\s]?versand|"
    r"versand(?:kosten)?\s*(?::\s*)?(?:frei|kostenlos|gratis|0[,.]00\s*€)|"
    r"inkl\.?\s*(?:versand|vsk)|inklusive\s+versand|vsk[-\s]?frei|keine\s+versandkosten|"
    r"0[,.]00\s*€\s*versand|free\s+shipping",
    re.IGNORECASE,
)
_SHIP_COST = [
    re.compile(rf"(?:zzgl\.?|\+|plus)\s*(?P<n>{_NUM})\s*(?:€|eur\b|euro\b)?\s*(?:versand|vsk)(?!kostenfrei|frei|kostenlos)", re.I),
    re.compile(rf"(?:versand(?:kosten)?|vsk)\s*(?::|von|ab|kostet)?\s*(?P<n>{_NUM})\s*(?:€|eur\b|euro\b)", re.I),
    re.compile(rf"(?P<n>{_NUM})\s*(?:€|eur\b|euro\b)\s*(?:versand|vsk)(?!kostenfrei|frei|kostenlos)", re.I),
]


def parse_shipping(text: str | None) -> float | None:
    """Versandkosten aus Text. 0.0 = versandkostenfrei, None = nicht ermittelbar."""
    if not text:
        return None
    t = html.unescape(text)
    for rx in _SHIP_COST:
        m = rx.search(t)
        if m:
            val = to_number(m.group("n"))
            if val is not None and val < 100:  # Plausibilität: Versand < 100 €
                return val
    if _FREE_SHIPPING.search(t):
        return 0.0
    return None


_HINTS = [
    (re.compile(r"gutschein|gutscheincode|rabattcode|coupon|\bcode\b|promo-?code", re.I), "Gutschein/Code nötig"),
    (re.compile(r"neukunde|erstbestellung|first order", re.I), "nur für Neukunden"),
    (re.compile(r"marketplace|marktplatz|drittanbieter|dritthändler|verkauf durch", re.I), "Marketplace-Händler"),
    (re.compile(r"\bapp\b|app-exklusiv|in der app", re.I), "evtl. nur per App"),
    (re.compile(r"newsletter", re.I), "Newsletter-Anmeldung nötig"),
    (re.compile(r"cashback|payback|shoop|igraal", re.I), "Preis evtl. inkl. Cashback/Payback"),
    (re.compile(r"\bprime\b", re.I), "evtl. nur mit Prime"),
    (re.compile(r"gebraucht|refurbished|generalüberholt|b-ware|wie neu", re.I), "gebraucht/B-Ware"),
    (re.compile(r"\blokal\b|\bfiliale\b|nur vor ort", re.I), "evtl. nur lokal/in der Filiale"),
]


def detect_hints(text: str | None) -> list[str]:
    """Hinweise wie "Gutschein nötig" oder "nur für Neukunden" aus dem Text."""
    if not text:
        return []
    t = html.unescape(text)
    return [label for rx, label in _HINTS if rx.search(t)]


# ---------------------------------------------------------------- Leasing ---

_EFF_RE = re.compile(rf"eff(?:ektiv|\.)?(?:e\s+rate)?\s*:?\s*(?P<n>{_NUM})\s*(?:€|eur\b|euro\b)", re.I)
_RATE_RES = [
    re.compile(rf"(?P<n>{_NUM})\s*(?:€|eur\b|euro\b)\s*(?:brutto\s*|netto\s*)?(?:/|pro|je|im|i\.)?\s*(?:monat|mtl|mon\b|monatlich|m\b)", re.I),
    re.compile(rf"(?:mtl\.?|monatlich|monatsrate|rate)\s*:?\s*(?:nur\s*|ab\s*)?(?P<n>{_NUM})\s*(?:€|eur\b|euro\b)", re.I),
]
_MONTHS_RE = re.compile(r"(?P<n>\d{2})\s*(?:monate|monaten|mon\b|mon\.|m\b|-monat)", re.I)
_KM_RE = re.compile(
    r"(?P<n>\d{1,3}(?:[.\s]\d{3})|\d{4,6}|\d{1,2})\s*(?P<u>tkm|tsd\.?\s*km|t\s*km|km|kilometer\w*)",
    re.I,
)
_DOWN_RE = [
    re.compile(rf"(?:sonderzahlung|anzahlung)\s*(?:von|:|in höhe von)?\s*(?P<n>{_NUM})\s*(?:€|eur\b|euro\b)", re.I),
    re.compile(rf"(?P<n>{_NUM})\s*(?:€|eur\b|euro\b)\s*(?:sonderzahlung|anzahlung)", re.I),
]
_NO_DOWN_RE = re.compile(r"ohne\s+(?:sonderzahlung|anzahlung)|keine\s+(?:sonderzahlung|anzahlung)|0\s*€\s*(?:sonderzahlung|anzahlung)", re.I)
_PROV_RE = [
    re.compile(rf"(?:bereitstellung\w*|überführung\w*|üf|zulassung\w*|überführungs-\s*und\s*zulassungskosten)\s*(?:kosten)?\s*(?::|von)?\s*(?P<n>{_NUM})\s*(?:€|eur\b|euro\b)", re.I),
    re.compile(rf"(?P<n>{_NUM})\s*(?:€|eur\b|euro\b)\s*(?:bereitstellung\w*|überführung\w*|üf\b|zulassung\w*)", re.I),
]
_PROV_INCL_RE = re.compile(r"inkl\.?\s*(?:üf|überführung|bereitstellung)|überführung\s*inklusive", re.I)


def parse_leasing(text: str | None) -> dict:
    """Liest Leasingdaten aus einem Text.

    Rückgabe (fehlende Werte = None):
      rate, monate, km, sonderzahlung, bereitstellung, effektiv_angegeben, gewerbe
    """
    out = {"rate": None, "monate": None, "km": None, "sonderzahlung": None,
           "bereitstellung": None, "effektiv_angegeben": None, "gewerbe": False}
    if not text:
        return out
    t = html.unescape(text)

    m = _EFF_RE.search(t)
    if m:
        out["effektiv_angegeben"] = to_number(m.group("n"))
    # Effektiv-Angaben entfernen, damit sie nicht als Rate gelesen werden
    t_wo_eff = _EFF_RE.sub(" ", t)
    for rx in _RATE_RES:
        m = rx.search(t_wo_eff)
        if m:
            val = to_number(m.group("n"))
            if val is not None and 10 <= val <= 5000:
                out["rate"] = val
                break

    for m in _MONTHS_RE.finditer(t):
        n = int(m.group("n"))
        if 12 <= n <= 72:
            out["monate"] = n
            break

    for m in _KM_RE.finditer(t):
        unit = m.group("u").lower().replace(" ", "")
        val = to_number(m.group("n").replace(" ", "."))
        if val is None:
            continue
        if unit.startswith(("tkm", "tsd", "t")) and not unit.startswith("km") and val < 1000:
            val *= 1000
        if 2500 <= val <= 100000:
            out["km"] = int(val)
            break

    if _NO_DOWN_RE.search(t):
        out["sonderzahlung"] = 0.0
    else:
        for rx in _DOWN_RE:
            m = rx.search(t)
            if m:
                out["sonderzahlung"] = to_number(m.group("n"))
                break

    provision = None
    for rx in _PROV_RE:
        for m in rx.finditer(t):
            val = to_number(m.group("n"))
            if val is not None and val < 5000:
                provision = (provision or 0) + val
        if provision is not None:
            break
    if provision is None and _PROV_INCL_RE.search(t):
        provision = 0.0
    out["bereitstellung"] = provision

    out["gewerbe"] = bool(re.search(r"gewerbe|\bnetto\b|business|firmenkunden", t, re.I)) and not re.search(
        r"privat", t, re.I
    )
    return out

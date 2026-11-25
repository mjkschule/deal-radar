"""Rabattknaller: große Preisnachlässe in ganzen Kategorien – unabhängig von deiner Produktliste.

Gelesen werden die Einträge, die mydealz (Kategorie-Gruppen + Feed mit Temperatur) und die Deal-Blogs
in diesem Lauf ohnehin liefern (sources.RAW). Ein Deal ist ein Rabattknaller, wenn

  * er zu einer Kategorie aus config.yaml (rabattknaller.kategorien) passt,
  * er höchstens max_preis kostet und
  * er mindestens ab_prozent unter dem PREISVERGLEICH liegt (PVG, idealo, Geizhals, „Vergleichspreis“ –
    NICHT UVP oder Streichpreis des Shops, die sind oft geschönt), oder er bei mydealz sehr „heiß“ ist
    (Temperatur ab hitze_ab °, also viele positive Stimmen der Community).

Meldungen: ab sofort_ab_prozent sofort (Ruhezeiten gelten), sonst in der Tagesübersicht um 19 Uhr.
Abgelaufene mydealz-Deals und von dir ausgeblendete Angebote werden nicht gemeldet.
"""

from __future__ import annotations

import datetime as dt
import html
import re

from . import ablauf, meldungen, prices
from .models import OK, Offer

DEFAULTS = {"aktiv": False, "ab_prozent": 30, "sofort_ab_prozent": 40, "hitze_ab": 300, "hitze_feed": "trending",
            "neu_melden_ab_prozent_billiger": 5, "kategorien": {}}

_DEG = re.compile(r"^\s*(\d{2,5})\s*°\s*[-–]\s*")
# Nur echte Preisvergleiche zählen als Bezugspreis
_PVG_BEFORE = re.compile(
    r"(?:pvg|vgp|preisvergleich|vergleichspreis|idealo|geizhals|günstigster\s+(?:preis|anbieter)|nächst(?:er|bester)"
    r"(?:\s+preis)?|sonst\s+(?:ab|mind(?:estens)?\.?))(?:\s*\([^)]{0,20}\))?"
    r"[^\d€]{0,40}?(?:(?:ab|von|bei|liegt|aktuell|rund|ca\.?|mind\.?)\s+)*$", re.I)


def settings(cfg: dict) -> dict:
    return {**DEFAULTS, **(cfg.get("rabattknaller") or {})}


def _fold(s: str) -> str:
    return (s or "").lower().replace("ß", "ss").replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")


def _has(text: str, term: str) -> bool:
    """Kurze Begriffe (bis 3 Zeichen, z. B. „Ah“, „2x“) als ganzes Wort, längere als Wortteil."""
    t, w = _fold(text), _fold(term)
    if len(w) <= 3:
        return re.search(rf"(?<![a-z0-9]){re.escape(w)}(?![a-z0-9])", t) is not None
    return w in t


def category_of(title: str, text: str, kats: dict) -> str | None:
    for key, k in kats.items():
        if k.get("muss") and not all(_has(title, w) for w in k["muss"]):
            continue
        if k.get("eines_von") and not any(_has(title, w) for w in k["eines_von"]):
            continue
        if k.get("zusatz_eines_von") and not any(_has(text, w) for w in k["zusatz_eines_von"]):
            continue
        if any(_has(title, w) for w in k.get("ausschluss") or []):
            continue
        return key
    return None


def reference_price(text: str, price: float) -> float | None:
    """Niedrigster genannter Preisvergleich (z. B. „PVG 229 €“, „idealo ab 213 €“) – über dem Deal-Preis."""
    refs = []
    t = html.unescape(text)
    for m in prices._MONEY_RE.finditer(t):
        val = prices.to_number(m.group("a") or m.group("b"))
        if val is None or val <= price:
            continue
        before = t[max(0, m.start() - 70):m.start()]
        if re.search(r"(?:uvp|statt|streichpreis|unverbindlich)[^\d€]{0,12}$", before, re.I):
            continue
        if _PVG_BEFORE.search(before) or re.match(r"^\s*\)?\s*(?:pvg|vgp)\b", t[m.end():m.end() + 8], re.I):
            refs.append(val)
    return min(refs) if refs else None


def heat_map(raw: dict) -> dict[str, int]:
    """Link -> mydealz-Temperatur (aus dem Feed mit „620° - …“ im Titel)."""
    heat = {}
    for it in raw.get("mydealz", []):
        m = _DEG.match(it.get("title") or "")
        if m:
            heat[it["link"].split("#")[0]] = int(m.group(1))
    return heat


def find(raw: dict, cfg: dict, product_urls: set[str] | None = None) -> list[Offer]:
    """Alle Rabattknaller dieses Laufs (noch ohne Ablauf-Prüfung), höchster Rabatt zuerst."""
    s = settings(cfg)
    kats = s["kategorien"] or {}
    heat = heat_map(raw)
    found: dict[str, Offer] = {}
    for source, items in raw.items():
        for it in items:
            link = (it.get("link") or "").split("#")[0]
            if not link or link in found or link in (product_urls or set()):
                continue
            title = _DEG.sub("", it.get("title") or "").strip()
            text = f"{title} {it.get('description') or ''}"
            key = category_of(title, text, kats)
            if not key:
                continue
            price = None
            if it.get("price_raw"):
                price = prices.to_number(re.sub(r"[^\d.,]", "", it["price_raw"]))
            price = price or prices.parse_price(title) or prices.parse_price((it.get("description") or "")[:300])
            k = kats[key]
            if not price or price <= 0 or price > float(k.get("max_preis") or 1e9):
                continue
            ref = reference_price(text[:2500], price)
            pct = round((ref - price) / ref * 100) if ref else None
            if pct is not None and pct > 80:
                continue  # unplausibel (falscher Bezugspreis gelesen)
            deg = heat.get(link)
            hot = deg is not None and deg >= int(s["hitze_ab"])
            if not ((pct is not None and pct >= int(s["ab_prozent"])) or hot):
                continue
            shipping = prices.parse_shipping(title, price)
            hints = [h for h in prices.detect_hints(text) if h != "Versand unbekannt"]
            o = Offer(product_id=f"knaller:{key}", source=source, shop=it.get("merchant") or source, title=title,
                      url=link, price=price, shipping=shipping, hints=hints, text=text[:600])
            o.knaller = {"kategorie": key, "kategorie_name": k.get("name", key), "bezug": ref, "rabatt": pct,
                         "hitze": deg, "heiss": hot}
            found[link] = o
    return sorted(found.values(), key=lambda o: (-(o.knaller["rabatt"] or 0), -(o.knaller["hitze"] or 0)))


def to_dict(o: Offer, now_iso: str, old: dict | None) -> dict:
    d = o.to_dict()
    d.update(o.knaller)
    d["first_seen"] = (old or {}).get("first_seen", now_iso)
    d["last_seen"] = now_iso
    d["h"] = meldungen.offer_hash(o.key)
    return d


def update(state: dict, offers: list[Offer], http, cfg: dict, now: dt.datetime, ignored: dict,
           budget: dict | None = None) -> list[Offer]:
    """Ablauf/Ausblenden prüfen, im state merken und die NEU zu meldenden zurückgeben."""
    s = settings(cfg)
    ablauf.apply_ignored(offers, ignored)
    ablauf.check([o for o in offers if o.status == OK], state, http, cfg, now, budget)
    store = state.setdefault("rabattknaller", {"angebote": {}, "gemeldet": {}})
    known, reported = store.setdefault("angebote", {}), store.setdefault("gemeldet", {})
    iso = now.isoformat(timespec="seconds")
    new = []
    for o in offers:
        if o.status != OK:
            known.pop(o.key, None)
            continue
        known[o.key] = to_dict(o, iso, known.get(o.key))
        last = reported.get(o.key)
        if last is None or o.compare_price < last * (1 - float(s["neu_melden_ab_prozent_billiger"]) / 100):
            new.append(o)
    # nach 48 Stunden ohne neuen Treffer vergessen
    cutoff = now - dt.timedelta(hours=(cfg.get("regeln") or {}).get("aktuell_stunden", 48))
    for k in [k for k, d in known.items() if dt.datetime.fromisoformat(d["last_seen"]) < cutoff]:
        known.pop(k)
    for k in [k for k in reported if k not in known]:
        reported.pop(k)
    return new


def current(state: dict) -> list[dict]:
    rows = list(((state.get("rabattknaller") or {}).get("angebote") or {}).values())
    return sorted(rows, key=lambda d: (-(d.get("rabatt") or 0), -(d.get("hitze") or 0)))


def describe(d: dict) -> str:
    """„−35 % ggü. Preisvergleich 299 € · 🔥 620°“"""
    parts = []
    if d.get("rabatt") is not None:
        parts.append(f"−{d['rabatt']} % ggü. Preisvergleich {prices_fmt(d['bezug'])}")
    if d.get("hitze") is not None:
        parts.append(f"🔥 {d['hitze']}°")
    return " · ".join(parts)


def prices_fmt(v) -> str:
    from .logic import _fmt
    return f"{_fmt(v)} €"


def route(o: Offer, cfg: dict, now: dt.datetime) -> str:
    s = settings(cfg)
    pct = o.knaller.get("rabatt")
    if pct is None or pct < int(s["sofort_ab_prozent"]):
        return meldungen.UEBERSICHT
    return meldungen.RUHE if meldungen.quiet_now(cfg, now) else meldungen.SOFORT


def format_alert(o: Offer) -> str:
    esc = lambda x: html.escape(str(x), quote=False)  # noqa: E731
    k = o.knaller
    ship = ("inkl. Versand" if o.shipping == 0 else f"+ {prices_fmt(o.shipping)} Versand" if o.shipping else "")
    lines = [f"💥 <b>Rabattknaller: {esc(k['kategorie_name'])}</b>",
             f"<b>{esc(o.title[:160])}</b>",
             f"💶 <b>{prices_fmt(o.price)}</b>{' ' + ship if ship else ''} bei {esc(o.shop)}"]
    if describe(k):
        lines.append(esc(describe(k)))
    conds = [h for h in o.hints if h]
    if conds:
        lines.append("📋 " + esc(" · ".join(conds[:4])))
    lines.append(f"<i>Quelle: {esc(o.source)} · nicht auf deiner Produktliste</i>")
    lines.append(f"🔗 <a href=\"{html.escape(o.url)}\">Zum Angebot</a>")
    return "\n".join(lines)


def buttons(o: Offer) -> list[list[dict]]:
    return [[{"text": "🙈 Ignorieren", "callback_data": f"i:knaller:{meldungen.offer_hash(o.key)}"}],
            [{"text": "🔗 Zum Angebot", "url": o.url}]]

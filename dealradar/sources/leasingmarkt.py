"""LeasingMarkt.de: Angebotsliste eines Modells (z. B. /leasing-opel-frontera?tg=PRIVATE).

Die Liste enthält strukturierte Daten (Laufzeit, Freikilometer, Monatsrate) für jede
Kombination. Sonderzahlung und Überführung stehen nur auf der Detailseite; diese wird
nur für wenige, passende Kandidaten geladen und 24 Stunden zwischengespeichert.
robots.txt erlaubt die genutzten Seiten (Stand: 24.11.2026).
"""

from __future__ import annotations

import datetime as dt
import json
import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from .. import prices
from ..config import Product
from ..models import Offer
from . import Context, strip_tags

NAME = "leasingmarkt"
BASE = "https://www.leasingmarkt.de"


def _js_string_from(page: str, start: int) -> str:
    """Dekodiert ein JavaScript-String-Literal ab Position `start` bis zum schließenden
    (nicht maskierten) Anführungszeichen. So bleiben Zeichen wie  Nav10\"  in
    Überschriften korrekt erhalten."""
    j = start
    while j < len(page):
        c = page[j]
        if c == "\\":
            j += 2
        elif c == '"':
            break
        else:
            j += 1
    return json.loads('"' + page[start:j] + '"')


def parse_listings(page: str) -> tuple[list[dict], int]:
    """Gibt (Liste der Angebote, Gesamtseiten) aus einer Ergebnisseite zurück.

    Die Daten stecken als JSON in einem JavaScript-String (self.__next_f.push([1,"..."])).
    Dieser String wird erst sauber dekodiert, danach wird das JSON gelesen."""
    marker = '\\"initialResult\\":'
    i = page.find(marker)
    if i >= 0:
        s = _js_string_from(page, i)
        key = '"initialResult":'
    else:  # falls die Daten einmal unmaskiert in der Seite stehen
        s, key = page, '"initialResult":'
    k = s.find(key)
    if k < 0:
        raise ValueError("Seitenaufbau unbekannt (initialResult fehlt)")
    obj, _ = json.JSONDecoder().raw_decode(s[k + len(key):])
    return obj.get("listings", []), int(obj.get("totalPages") or 1)


def _page_url(base_url: str, page: int) -> str:
    p = urlparse(base_url)
    q = dict(parse_qsl(p.query))
    if page > 1:
        q["p"] = str(page)
    return urlunparse(p._replace(query=urlencode(q)))


def parse_detail_costs(page: str) -> dict:
    """Sonderzahlung (Anzahlung) und Bereitstellung (Überführung + Zulassung) von der Detailseite."""
    t = strip_tags(page)
    out = {"sonderzahlung": None, "bereitstellung": None}
    m = re.search(r"Anzahlung\s+(\d[\d.,]*)\s*€", t)
    if m:
        out["sonderzahlung"] = prices.to_number(m.group(1))
    total = 0.0
    found = False
    for label in ("Überführungskosten", "Zulassungskosten", "Bereitstellungskosten"):
        m = re.search(rf"{label}\s+(\d[\d.,]*)\s*€", t)
        if m:
            total += prices.to_number(m.group(1)) or 0
            found = True
    if found:
        out["bereitstellung"] = round(total, 2)
    return out


def select_offers(listing: dict, months: int, min_km: int) -> tuple[dict | None, dict | None]:
    """(beste passende Variante, beste nicht passende Variante mit gleicher Laufzeit)."""
    variants = list(listing.get("offers") or [])
    if listing.get("leasingOffer"):
        variants.append(listing["leasingOffer"])
    same = [v for v in variants if v.get("duration") == months and v.get("monthlyRate")]
    good = [v for v in same if (v.get("includedMileage") or 0) >= min_km]
    bad = [v for v in same if (v.get("includedMileage") or 0) < min_km]
    best = min(good, key=lambda v: v["monthlyRate"]) if good else None
    worst = min(bad, key=lambda v: v["monthlyRate"]) if bad else None
    return best, worst


def _detail_url(listing: dict, variant_id) -> str:
    path = listing.get("url") or f"/leasing/pkw/x/{listing['id']}"
    path = re.sub(r"adVariant=\d+", f"adVariant={variant_id}", path)
    return BASE + path if path.startswith("/") else path


def fetch(products: list[Product], ctx: Context) -> list[Offer]:
    leasing_products = [p for p in products if p.is_leasing and p.leasing.get("leasingmarkt_url")]
    if not leasing_products:
        ctx.notes.append("kein Leasing-Produkt mit leasingmarkt_url")
        return []
    max_pages = int(ctx.config.get("leasingmarkt_max_seiten", 20))
    max_details = int(ctx.config.get("leasingmarkt_max_details", 4))
    cache = ctx.cache.setdefault("leasingmarkt_details", {})
    now = ctx.now
    offers: list[Offer] = []
    pages_read = details = 0
    for prod in leasing_products:
        months = int(prod.leasing.get("laufzeit_monate", 36))
        min_km = int(prod.leasing.get("min_km_jahr", 15000))
        listings: list[dict] = []
        total_pages = 1
        page = 1
        bad_pages = []
        while page <= min(total_pages, max_pages):
            html = ctx.http.get(_page_url(prod.leasing["leasingmarkt_url"], page))
            try:
                ls, total_pages = parse_listings(html)
            except ValueError:  # eine kaputte Seite überspringen, nicht die ganze Quelle verlieren
                if page == 1:
                    raise
                bad_pages.append(page)
                ls = []
            listings.extend(ls)
            pages_read += 1
            page += 1
        if bad_pages:
            ctx.notes.append(f"Seite(n) {', '.join(map(str, bad_pages))} nicht lesbar")
        electric = [l for l in listings if str(l.get("fuelCategory", "")).lower().startswith("elektro")]
        candidates = []
        for l in electric:
            if "gewerbe" in str(l.get("targetGroup", "")).lower() and "privat" not in str(l.get("targetGroup", "")).lower():
                continue
            best, worst = select_offers(l, months, min_km)
            chosen = best or worst
            if not chosen:
                continue
            lease = {"rate": float(chosen["monthlyRate"]), "monate": chosen.get("duration"),
                     "km": chosen.get("includedMileage"), "sonderzahlung": None, "bereitstellung": None,
                     "gewerbe": False}
            title = f"{l.get('makeName', '')} {l.get('modelName', '')}: {l.get('headline', '')}".strip()
            hints = []
            if l.get("availability"):
                hints.append(str(l["availability"]))
            o = Offer(product_id=prod.id, source=NAME, shop="LeasingMarkt.de", title=title,
                      url=_detail_url(l, chosen.get("id")), price=lease["rate"], leasing=lease,
                      hints=hints, text=title)
            candidates.append((o, l, chosen))
        # Detailseiten für die günstigsten passenden Kandidaten
        candidates.sort(key=lambda c: c[0].price)
        for o, l, chosen in candidates:
            if o.leasing["km"] < min_km:
                continue
            key = str(chosen.get("id"))
            cached = cache.get(key)
            fresh = cached and (now - dt.datetime.fromisoformat(cached["t"])) < dt.timedelta(hours=24)
            if not fresh and details < max_details and o.price <= prod.zielpreis * 1.3:
                try:
                    costs = parse_detail_costs(ctx.http.get(o.url))
                    cached = {"t": now.isoformat(), **costs}
                    cache[key] = cached
                    details += 1
                except Exception as e:
                    ctx.notes.append(f"Detailseite {l.get('id')}: {e}")
            if cached:
                o.leasing["sonderzahlung"] = cached.get("sonderzahlung")
                o.leasing["bereitstellung"] = cached.get("bereitstellung")
        offers.extend(o for o, _, _ in candidates)
        ctx.notes.append(f"{len(listings)} Angebote geprüft, {len(electric)} elektrisch")
    ctx.notes.insert(0, f"{pages_read} Seiten, {details} Detailseiten geladen")
    # Alte Cache-Einträge entfernen
    for k in [k for k, v in cache.items() if (now - dt.datetime.fromisoformat(v["t"])).days > 3]:
        cache.pop(k, None)
    return offers

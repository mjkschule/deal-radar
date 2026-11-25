"""Shop-Produktseiten: liest den Preis aus maschinenlesbaren Angaben (schema.org).

Reihenfolge: JSON-LD (Product/Offer) -> Meta-Tag product:price:amount -> Microdata itemprop="price".
Seiten, deren robots.txt den Abruf verbietet, werden übersprungen.
"""

from __future__ import annotations

import json
import re
from urllib.parse import urlparse

from .. import prices
from ..config import Product
from ..models import NICHT_VERFUEGBAR, Offer
from . import Context, strip_tags

NAME = "shop"


def _walk_offers(obj, out: list[dict]) -> None:
    if isinstance(obj, list):
        for x in obj:
            _walk_offers(x, out)
        return
    if not isinstance(obj, dict):
        return
    t = obj.get("@type")
    types = t if isinstance(t, list) else [t]
    is_offer = any(x in ("Offer", "AggregateOffer") for x in types) or (
        t is None and ("price" in obj or "lowPrice" in obj) and ("priceCurrency" in obj or "availability" in obj)
    )
    if is_offer:
        out.append(obj)
    for k, v in obj.items():
        if k != "@context":
            _walk_offers(v, out)


def _shipping_from_offer(o: dict) -> float | None:
    sd = o.get("shippingDetails")
    sd = sd[0] if isinstance(sd, list) and sd else sd
    if isinstance(sd, dict):
        rate = sd.get("shippingRate")
        rate = rate[0] if isinstance(rate, list) and rate else rate
        if isinstance(rate, dict) and rate.get("value") is not None:
            return prices.to_number(str(rate["value"]), german=False)
    return None


def extract_price(html_text: str) -> dict | None:
    """Gibt {"price", "shipping", "available", "name"} zurück oder None."""
    name = None
    gtin = ""
    for block in re.findall(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', html_text, re.S | re.I):
        try:
            data = json.loads(block.strip())
        except json.JSONDecodeError:
            continue
        found: list[dict] = []
        _walk_offers(data, found)
        nodes = data if isinstance(data, list) else [data]
        for n in nodes:
            if isinstance(n, dict) and n.get("@type") == "Product" and n.get("name"):
                name = n["name"]
                gtin = next((str(n[k]).strip() for k in ("gtin13", "gtin", "gtin14", "gtin12", "gtin8", "ean")
                             if n.get(k)), "")
        candidates = []
        for o in found:
            if str(o.get("priceCurrency", "EUR")).upper() not in ("EUR", ""):
                continue
            raw = o.get("price", o.get("lowPrice"))
            val = prices.to_number(str(raw), german=False) if raw is not None else None
            if val is not None and val > 0:
                avail = str(o.get("availability", ""))
                candidates.append({"price": val, "shipping": _shipping_from_offer(o),
                                   "available": not re.search(r"OutOfStock|SoldOut|Discontinued", avail)})
        if candidates:
            best = min(candidates, key=lambda c: (not c["available"], c["price"]))
            best["name"] = name
            best["ean"] = gtin if re.fullmatch(r"\d{8,14}", gtin or "") else ""
            return best

    m = re.search(r'<meta[^>]+(?:property|name)=["\'](?:product:price:amount|og:price:amount)["\'][^>]*content=["\']([^"\']+)', html_text, re.I)
    if not m:
        m = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]*(?:property|name)=["\'](?:product:price:amount|og:price:amount)', html_text, re.I)
    if m:
        val = prices.to_number(m.group(1), german=False)
        if val:
            return {"price": val, "shipping": None, "available": True, "name": name}

    vals = []
    for m in re.finditer(r'itemprop=["\']price["\'][^>]*content=["\']([^"\']+)', html_text, re.I):
        v = prices.to_number(m.group(1), german=False)
        if v:
            vals.append(v)
    if vals:
        # Mehrere Preise (z. B. UVP + Angebot): der niedrigste ist der Verkaufspreis
        return {"price": min(vals), "shipping": None, "available": True, "name": name}
    return None


def fetch(products: list[Product], ctx: Context) -> list[Offer]:
    offers: list[Offer] = []
    total = ok = 0
    problems = []
    for prod in products:
        for url in prod.shop_urls:
            total += 1
            host = urlparse(url).netloc.removeprefix("www.")
            try:
                page = ctx.http.get(url)
            except Exception as e:
                problems.append(f"{host}: {e}")
                continue
            info = extract_price(page)
            if not info:
                problems.append(f"{host}: kein maschinenlesbarer Preis gefunden")
                continue
            ok += 1
            # Versand nur aus den strukturierten Daten übernehmen. Allgemeine Banner wie
            # "versandkostenfrei ab 50 €" wären irreführend -> sonst "Versand unbekannt".
            shipping = info["shipping"]
            hints = [] if shipping is not None else ["Versand unbekannt"]
            o = Offer(product_id=prod.id, source=NAME, shop=host, title=info.get("name") or prod.name,
                      url=url, price=info["price"], shipping=shipping, hints=hints, text=info.get("name") or "",
                      ean=info.get("ean") or "")
            if not info["available"]:
                o.status, o.status_reason = NICHT_VERFUEGBAR, "laut Shop nicht lieferbar"
            offers.append(o)
    if total:
        ctx.notes.append(f"{ok}/{total} Shop-Seiten gelesen")
    ctx.notes.extend(problems[:4])
    if total and ok == 0:
        raise RuntimeError("; ".join(problems[:3]) or "keine Shop-Seite lesbar")
    return offers

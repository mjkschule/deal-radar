"""eBay Browse API (offizielle Schnittstelle, kostenloser Developer-Account).

Benötigt die GitHub-Secrets EBAY_CLIENT_ID und EBAY_CLIENT_SECRET (Production-Keyset).
Ohne Schlüssel wird die Quelle als "deaktiviert" angezeigt – kein Fehler.
"""

from __future__ import annotations

import base64
import json
import urllib.parse

from .. import prices
from ..config import Product
from ..matching import matches
from ..models import Offer
from . import Context, Skipped

NAME = "ebay"
TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
SEARCH_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"


def get_token(ctx: Context, client_id: str, secret: str) -> str:
    basic = base64.b64encode(f"{client_id}:{secret}".encode()).decode()
    body = urllib.parse.urlencode({"grant_type": "client_credentials",
                                   "scope": "https://api.ebay.com/oauth/api_scope"}).encode()
    status, text = ctx.http.request(TOKEN_URL, data=body, method="POST", headers={
        "Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded"})
    if status != 200:
        raise RuntimeError(f"eBay-Anmeldung fehlgeschlagen (HTTP {status}) – Schlüssel prüfen")
    return json.loads(text)["access_token"]


def offers_from_response(data: dict, product: Product) -> list[Offer]:
    out = []
    for it in data.get("itemSummaries", []) or []:
        title = it.get("title", "")
        if not matches(product, title):
            continue
        price = it.get("price") or {}
        if price.get("currency") != "EUR":
            continue
        value = prices.to_number(str(price.get("value")), german=False)
        if value is None:
            continue
        shipping = None
        for opt in it.get("shippingOptions") or []:
            cost = (opt.get("shippingCost") or {}).get("value")
            if cost is not None:
                c = prices.to_number(str(cost), german=False)
                shipping = c if shipping is None else min(shipping, c)
        seller = it.get("seller") or {}
        hints = [f"eBay-Händler: {seller.get('username', '?')}"
                 + (f" ({seller.get('feedbackPercentage')} % positiv)" if seller.get("feedbackPercentage") else "")]
        if shipping is None:
            hints.append("Versand unbekannt")
        if it.get("itemLocation", {}).get("country") not in (None, "DE"):
            hints.append(f"Versand aus {it['itemLocation']['country']}")
        out.append(Offer(product_id=product.id, source=NAME, shop="eBay", title=title,
                         url=it.get("itemWebUrl", ""), price=value, shipping=shipping, hints=hints, text=title))
    return out


def fetch(products: list[Product], ctx: Context) -> list[Offer]:
    cid, secret = ctx.env.get("EBAY_CLIENT_ID"), ctx.env.get("EBAY_CLIENT_SECRET")
    if not cid or not secret:
        raise Skipped("deaktiviert – keine eBay-API-Schlüssel hinterlegt")
    token = get_token(ctx, cid, secret)
    offers: list[Offer] = []
    searched = 0
    for prod in products:
        if prod.is_leasing:
            continue
        q = prod.ebay_suche or prod.suchbegriffe[0]
        lo, hi = round(prod.zielpreis * 0.3, 2), round(prod.zielpreis * 2.5, 2)
        params = {
            "q": q, "limit": "50", "sort": "price",
            "filter": f"buyingOptions:{{FIXED_PRICE}},conditions:{{NEW}},deliveryCountry:DE,"
                      f"price:[{lo}..{hi}],priceCurrency:EUR",
        }
        status, text = ctx.http.request(f"{SEARCH_URL}?{urllib.parse.urlencode(params)}", headers={
            "Authorization": f"Bearer {token}",
            "X-EBAY-C-MARKETPLACE-ID": "EBAY_DE",
            "X-EBAY-C-ENDUSERCTX": "contextualLocation=country%3DDE",
        })
        if status != 200:
            ctx.notes.append(f"Suche '{q}': HTTP {status}")
            continue
        searched += 1
        offers.extend(offers_from_response(json.loads(text), prod))
    ctx.notes.append(f"{searched} Suchen ausgeführt")
    return offers

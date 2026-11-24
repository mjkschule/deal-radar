"""Sparneuwagen.de: Haupt-RSS-Feed (https://www.sparneuwagen.de/feed/).

Nur der Haupt-Feed ist laut robots.txt erlaubt (Kategorie-Feeds sind gesperrt).
Er enthält die neuesten Leasing-Deals aller Marken; gefiltert wird nach Suchbegriffen.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from .. import prices
from ..config import Product
from ..matching import matches
from ..models import Offer
from . import Context, strip_tags

NAME = "sparneuwagen"
FEED = "https://www.sparneuwagen.de/feed/"


def parse_feed(xml_text: str) -> list[dict]:
    root = ET.fromstring(xml_text.encode("utf-8"))
    items = []
    for it in root.iter("item"):
        cats = [(c.text or "").strip() for c in it.findall("category")]
        items.append({
            "title": (it.findtext("title") or "").strip(),
            "link": (it.findtext("link") or "").strip(),
            "description": strip_tags(it.findtext("description") or ""),
            "categories": cats,
        })
    return items


def offer_from_item(item: dict, product: Product) -> Offer | None:
    text = f"{item['title']} {item['description']}"
    lease = prices.parse_leasing(text)
    if lease["rate"] is None:
        return None
    cats = {c.lower() for c in item["categories"]}
    if "gewerbe" in cats and "privat" not in cats:
        lease["gewerbe"] = True
    elif "privat" in cats:
        lease["gewerbe"] = False
    hints = prices.detect_hints(text)
    return Offer(product_id=product.id, source=NAME, shop="sparneuwagen.de", title=item["title"],
                 url=item["link"], price=lease["rate"], leasing=lease, hints=hints,
                 text=text + " " + " ".join(item["categories"]))


def fetch(products: list[Product], ctx: Context) -> list[Offer]:
    leasing_products = [p for p in products if p.is_leasing]
    if not leasing_products:
        return []
    items = parse_feed(ctx.http.get(FEED))
    offers = []
    for prod in leasing_products:
        for item in items:
            if matches(prod, item["title"] + " " + " ".join(item["categories"])):
                o = offer_from_item(item, prod)
                if o:
                    offers.append(o)
    ctx.notes.append(f"{len(items)} Artikel im Feed")
    return offers

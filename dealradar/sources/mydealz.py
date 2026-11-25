"""mydealz: öffentliche RSS-Feeds der Gruppen (z. B. https://www.mydealz.de/rss/gruppe/makita).

Die mydealz-Suche selbst ist per robots.txt gesperrt und wird NICHT verwendet.
Stattdessen werden die Gruppen-Feeds gelesen und nach den Suchbegriffen gefiltert.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from .. import prices
from ..config import Product
from ..matching import matches
from ..models import Offer
from . import Context, strip_tags

NAME = "mydealz"
BASE = "https://www.mydealz.de/rss/"
PEPPER_NS = "http://www.pepper.com/rss"


def feed_paths(products: list[Product], always: list[str]) -> list[str]:
    paths: list[str] = []
    for p in always:
        if p not in paths:
            paths.append(p)
    for prod in products:
        for g in prod.mydealz_gruppen:
            path = g if "/" in g or g in ("new", "hot") else f"gruppe/{g}"
            if path not in paths:
                paths.append(path)
    return paths


def parse_feed(xml_text: str) -> list[dict]:
    """Liest die Einträge eines mydealz-RSS-Feeds."""
    items = []
    root = ET.fromstring(xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text)
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        desc = strip_tags(it.findtext("description") or "")
        merchant_el = None
        for child in it:
            if child.tag.endswith("merchant"):
                merchant_el = child
                break
        merchant = merchant_el.get("name") if merchant_el is not None else None
        price_raw = merchant_el.get("price") if merchant_el is not None else None
        items.append({
            "title": title,
            "link": link,
            "description": desc,
            "merchant": merchant or "",
            "price_raw": price_raw,
            "pubdate": it.findtext("pubDate") or "",
        })
    return items


def offer_from_item(item: dict, product: Product) -> Offer | None:
    text = f"{item['title']} {item['description']}"
    shop = item["merchant"] or "unbekannt"
    if product.is_leasing:
        lease = prices.parse_leasing(f"{item['title']} {item['description'][:600]}")
        if lease["rate"] is None:
            return None  # kein Leasingangebot (z. B. Kauf)
        return Offer(product_id=product.id, source=NAME, shop=shop, title=item["title"], url=item["link"],
                     price=lease["rate"], leasing=lease, hints=prices.detect_hints(item["title"]), text=text)
    price = prices.to_number(re.sub(r"[^\d.,]", "", item["price_raw"])) if item["price_raw"] else None
    if price is None:
        price = prices.parse_price(item["title"])
    if price is None:
        return None
    # Titel zuerst (dort steht meist "inkl. Versand"), dann die Beschreibung
    shipping = prices.parse_shipping(item["title"], price)
    if shipping is None:
        shipping = prices.parse_shipping(item["description"], price)
    hints = prices.detect_hints(text)
    if shipping is None:
        hints.append("Versand unbekannt")
    return Offer(product_id=product.id, source=NAME, shop=shop, title=item["title"], url=item["link"],
                 price=price, shipping=shipping, hints=hints, text=text)


def fetch(products: list[Product], ctx: Context) -> list[Offer]:
    always = ctx.config.get("mydealz_immer") or []
    paths = feed_paths(products, always)
    offers: list[Offer] = []
    errors = []
    seen_links: set[tuple[str, str]] = set()
    ok = 0
    for path in paths:
        try:
            items = parse_feed(ctx.http.get(BASE + path))
            ok += 1
        except Exception as e:  # einzelner Feed kaputt -> andere weiter
            errors.append(f"{path}: {e}")
            continue
        for prod in products:
            relevant = path in always or path.split("/")[-1] in prod.mydealz_gruppen or path in prod.mydealz_gruppen
            if not relevant:
                continue
            for item in items:
                if (prod.id, item["link"]) in seen_links:
                    continue
                if not matches(prod, item["title"]):
                    continue
                offer = offer_from_item(item, prod)
                if offer:
                    seen_links.add((prod.id, item["link"]))
                    offers.append(offer)
    ctx.notes.append(f"{ok}/{len(paths)} Feeds gelesen")
    if errors:
        ctx.notes.extend(errors[:3])
        if ok == 0:
            raise RuntimeError("; ".join(errors[:3]))
    return offers

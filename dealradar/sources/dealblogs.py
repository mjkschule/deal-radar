"""Deal-Blogs: öffentliche RSS-Feeds von mein-deal.com, MyTopDeals, Schnäppchenfuchs und Dealdoktor.

Geprüft am 25.11.2026: robots.txt erlaubt die Feeds, die Nutzungsbedingungen verbieten keinen
automatischen Abruf (Kopien sind "für den privaten, nicht kommerziellen Gebrauch gestattet").
Jeder Blog ist eine eigene Quelle (eigener Status, einzeln abschaltbar in config.yaml -> quellen).
Gesucht wird nur in den Titeln; Preis aus dem Titel ("für 47,45€ (statt 64€)"), Shop aus der
Kategorie oder dem Text ("bei Amazon").
"""

from __future__ import annotations

import datetime as dt
import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

from .. import prices
from ..config import Product
from ..matching import matches
from ..models import Offer
from . import Context, strip_tags

# Name: (Feed, Parameter zum Blättern). Ein Feed enthält nur die letzten 10–16 Beiträge
# (in der Black Week weniger als 2 Stunden) – deshalb wird geblättert, bis der letzte Lauf
# lückenlos erreicht ist (höchstens MAX_SEITEN; robots.txt erlaubt die Parameter).
BLOGS = {
    "mein-deal": ("https://www.mein-deal.com/feed/", "paged"),
    "mytopdeals": ("https://www.mytopdeals.net/feed/", "paged"),
    "schnaeppchenfuchs": ("https://schnaeppchenfuchs.com/rss", "page"),
    "dealdoktor": ("https://www.dealdoktor.de/feed/", "paged"),
}
MAX_SEITEN = 6
ERSTER_LAUF_STUNDEN = 3  # ohne gespeicherten letzten Abruf so weit zurück lesen

# Bekannte Händler (für die Shop-Erkennung aus Kategorie und Text)
SHOPS = [
    "Amazon", "MediaMarkt", "Saturn", "Otto", "eBay", "Lidl", "Kaufland", "Aldi", "Netto", "Penny", "Tchibo",
    "Galaxus", "Alternate", "notebooksbilliger", "Cyberport", "Baur", "Rossmann", "dm", "IKEA", "Decathlon",
    "Zalando", "About You", "Euronics", "Expert", "Conrad", "Hornbach", "OBI", "Bauhaus", "Toom", "Proshop",
    "Mindfactory", "Coolblue", "Philips", "Tefal", "Cosori", "Ninja", "Makita", "Bosch", "WMF", "Douglas",
    "Shop Apotheke", "Media Markt", "Smyths", "Thalia", "Apple", "Samsung", "Xiaomi", "Office-Partner",
]
_SHOP_RE = re.compile(r"\b(?:bei|von|im)\s+(" + "|".join(re.escape(s) for s in SHOPS) + r")\b", re.I)


def parse_feed(xml_text: str) -> list[dict]:
    root = ET.fromstring(xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text)
    items = []
    for it in root.iter("item"):
        body = ""
        for child in it:
            if child.tag.endswith("encoded"):
                body = child.text or ""
        items.append({
            "title": strip_tags(it.findtext("title") or ""),
            "link": (it.findtext("link") or "").strip(),
            "description": strip_tags((it.findtext("description") or "") + " " + body)[:1500],
            "categories": [(c.text or "").strip() for c in it.findall("category")],
            "date": _date(it.findtext("pubDate")),
        })
    return items


def _date(raw: str | None) -> dt.datetime | None:
    try:
        return parsedate_to_datetime(raw) if raw else None
    except (TypeError, ValueError):
        return None


def shop_of(item: dict, blog: str) -> str:
    for c in item["categories"]:
        for s in SHOPS:
            if c.lower() == s.lower():
                return s
    m = _SHOP_RE.search(f"{item['title']} {item['description']}")
    if m:
        name = m.group(1)
        return next(s for s in SHOPS if s.lower() == name.lower())
    return blog


def offer_from_item(item: dict, product: Product, blog: str) -> Offer | None:
    if product.is_leasing:
        return None  # Leasing kommt über LeasingMarkt/Sparneuwagen/mydealz
    price = prices.parse_price(item["title"])
    from_text = price is None
    if from_text:  # MyTopDeals nennt den Preis oft erst im Text ("… ab 9,15€ erhältlich")
        price = prices.parse_price(item["description"][:300])
    if not price or price <= 0:
        return None  # kein Preis oder Gratis-Aktion
    shipping = prices.parse_shipping(item["title"], price)
    if shipping is None:
        shipping = prices.parse_shipping(item["description"], price)
    text = f"{item['title']} {item['description']}"
    hints = prices.detect_hints(text)
    if shipping is None:
        hints.append("Versand unbekannt")
    if from_text:
        hints.append("Preis aus dem Beitragstext")
    return Offer(product_id=product.id, source=blog, shop=shop_of(item, blog), title=item["title"],
                 url=item["link"], price=price, shipping=shipping, hints=hints, text=text)


class BlogSource:
    """Eine Datenquelle je Blog (verhält sich wie ein Quellen-Modul: NAME + fetch)."""

    def __init__(self, name: str, url: str, page_param: str):
        self.NAME = name
        self.url = url
        self.page_param = page_param

    def page_url(self, n: int) -> str:
        return self.url if n == 1 else f"{self.url}?{self.page_param}={n}"

    def read_items(self, ctx: Context) -> tuple[list[dict], int]:
        """Blättert, bis der Beitrag vom letzten Abruf erreicht ist. (Beiträge, gelesene Seiten)"""
        store = ctx.cache.setdefault("blogs", {})
        last = store.get(self.NAME)
        since = (dt.datetime.fromisoformat(last) - dt.timedelta(minutes=15) if last
                 else ctx.now - dt.timedelta(hours=ERSTER_LAUF_STUNDEN))
        items: list[dict] = []
        seen: set[str] = set()
        pages = 0
        for n in range(1, MAX_SEITEN + 1):
            try:
                batch = parse_feed(ctx.http.get(self.page_url(n)))
            except Exception:
                if n == 1:
                    raise
                break  # weitere Seiten sind nur eine Ergänzung
            pages += 1
            new = [i for i in batch if i["link"] not in seen]
            seen.update(i["link"] for i in new)
            items.extend(new)
            dates = [i["date"] for i in batch if i["date"]]
            if not new or not dates or min(dates) <= since:
                break
        store[self.NAME] = ctx.now.isoformat(timespec="seconds")
        return items, pages

    def fetch(self, products: list[Product], ctx: Context) -> list[Offer]:
        items, pages = self.read_items(ctx)
        offers = []
        for prod in products:
            for item in items:
                if matches(prod, item["title"]):
                    o = offer_from_item(item, prod, self.NAME)
                    if o:
                        offers.append(o)
        ctx.notes.append(f"{len(items)} Beiträge ({pages} Feed-Seite{'n' if pages != 1 else ''})")
        return offers


SOURCES = [BlogSource(name, url, param) for name, (url, param) in BLOGS.items()]

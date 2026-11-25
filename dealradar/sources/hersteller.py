"""Herstellershops (shops.yaml): Produktseite über die Sitemap finden, Preis aus JSON-LD lesen.

Ablauf je Shop:
  1. Sitemap (bzw. die Produkt-Sitemaps eines Sitemap-Index) höchstens 1x pro Tag laden –
     oder sofort, wenn sich deine Produkte/Suchbegriffe geändert haben.
  2. Für jedes Produkt die Adressen heraussuchen, in denen ein Suchbegriff vorkommt
     (z. B. "EY401D" in ".../easy-fry-deluxe-ey401d/...").
  3. Höchstens MAX_SEITEN Produktseiten pro Produkt und Lauf abrufen und den Preis lesen
     (gleiche Logik wie die Quelle "shop").
Gespeichert werden nur die Treffer, nicht die ganze Sitemap.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re
from pathlib import Path
from urllib.parse import unquote, urlparse

import yaml

from ..config import ROOT, Product
from ..matching import matches
from ..models import NICHT_VERFUEGBAR, Offer
from . import Context, Skipped
from .shop import extract_price

NAME = "hersteller"
MAX_SEITEN = 2
SITEMAP_STUNDEN = 24


def load_shops(path: Path | None = None) -> list[dict]:
    path = path or ROOT / "shops.yaml"
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [s for s in data.get("shops") or [] if s.get("aktiv", True) and s.get("sitemap")]


def sitemap_urls(xml_text: str) -> tuple[list[str], bool]:
    """(<loc>-Adressen, ist_index)"""
    locs = [unquote(x.strip()).replace("&amp;", "&") for x in re.findall(r"<loc>\s*([^<]+?)\s*</loc>", xml_text)]
    return locs, "<sitemapindex" in xml_text[:2000]


def _get_text(ctx: Context, url: str) -> str:
    return ctx.http.get(url)  # robots.txt wird in http.get geprüft (keine .gz-Sitemaps)


def collect(ctx: Context, sitemap: str) -> list[str]:
    """Alle Produktadressen eines Shops (folgt einem Sitemap-Index zu den Produkt-Sitemaps)."""
    locs, is_index = sitemap_urls(_get_text(ctx, sitemap))
    if not is_index:
        return locs
    out: list[str] = []
    for child in locs:
        if "product" in child.lower() or "produkt" in child.lower():
            out.extend(sitemap_urls(_get_text(ctx, child))[0])
    return out


def slug_text(url: str) -> str:
    """Adresse als Text: /p/easy-fry-deluxe-ey401d/1510001458 -> 'p easy fry deluxe ey401d 1510001458'"""
    p = urlparse(url)
    return re.sub(r"[^0-9a-zA-ZäöüÄÖÜß]+", " ", unquote(p.path)).strip()


def product_signature(products: list[Product]) -> str:
    raw = "|".join(f"{p.id}:{','.join(p.suchbegriffe)}" for p in sorted(products, key=lambda p: p.id))
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


def find_pages(products: list[Product], urls: list[str]) -> dict[str, list[str]]:
    hits: dict[str, list[str]] = {}
    for prod in products:
        if prod.is_leasing:
            continue
        found = [u for u in urls if matches(prod, slug_text(u))]
        if found:
            hits[prod.id] = found[:MAX_SEITEN]
    return hits


def fetch(products: list[Product], ctx: Context) -> list[Offer]:
    shops = load_shops()
    if not shops:
        raise Skipped("keine Shops in shops.yaml")
    cache = ctx.cache.setdefault("hersteller", {})
    sig = product_signature(products)
    offers: list[Offer] = []
    notes, errors = [], []
    for s in shops:
        name = s["name"]
        entry = cache.get(name) or {}
        fresh = (entry.get("signatur") == sig and entry.get("stand")
                 and ctx.now - dt.datetime.fromisoformat(entry["stand"]) < dt.timedelta(hours=SITEMAP_STUNDEN))
        if not fresh:
            try:
                urls = collect(ctx, s["sitemap"])
            except Exception as e:
                errors.append(f"{name}: Sitemap nicht lesbar ({e})")
                continue
            entry = {"stand": ctx.now.isoformat(timespec="seconds"), "signatur": sig,
                     "seiten": len(urls), "treffer": find_pages(products, urls)}
            cache[name] = entry
        by_id = {p.id: p for p in products}
        read = 0
        for pid, urls in (entry.get("treffer") or {}).items():
            prod = by_id.get(pid)
            if not prod:
                continue
            for url in urls:
                try:
                    info = extract_price(ctx.http.get(url))
                except Exception as e:
                    errors.append(f"{name}: {e}")
                    continue
                if not info:
                    continue
                read += 1
                hints = [] if info["shipping"] is not None else ["Versand unbekannt"]
                o = Offer(product_id=pid, source=NAME, shop=name, title=info.get("name") or prod.name, url=url,
                          price=info["price"], shipping=info["shipping"], hints=hints, text=info.get("name") or "",
                          ean=info.get("ean") or "")
                if not info["available"]:
                    o.status, o.status_reason = NICHT_VERFUEGBAR, "laut Hersteller nicht lieferbar"
                offers.append(o)
        notes.append(f"{name}: {entry.get('seiten', 0)} Seiten, {len(entry.get('treffer') or {})} passende Produkte, "
                     f"{read} gelesen")
    ctx.notes.extend(notes + errors[:3])
    if errors and not notes:
        raise RuntimeError("; ".join(errors[:3]))
    return offers

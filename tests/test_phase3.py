"""Tests für Phase 3: Deal-Blog-Feeds, Herstellershops per Sitemap, Gmail-Postfach, Duplikate."""

import datetime as dt
from email.message import EmailMessage
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from dealradar import logic
from dealradar.config import load_config, parse_products
from dealradar.models import Offer
from dealradar.sources import Context, Skipped, dealblogs, hersteller, postfach

TZ = ZoneInfo("Europe/Berlin")
NOW = dt.datetime(2026, 11, 25, 12, 0, tzinfo=TZ)

PRODUCTS = parse_products([
    {"id": "tefal-ey401d", "name": "Tefal Easy Fry Deluxe EY401D", "suchbegriffe": ["EY401D"], "zielpreis": 60},
    {"id": "philips-hd9255", "name": "Philips Airfryer HD9255", "suchbegriffe": ["HD9255"], "zielpreis": 55},
    {"id": "auto", "name": "Opel Frontera", "suchbegriffe": ["Frontera"], "zielpreis": 250, "typ": "leasing"},
])


class FakeHttp:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def get(self, url, headers=None):
        self.calls.append(url)
        if url not in self.routes:
            raise RuntimeError(f"404 {url}")
        return self.routes[url]


def ctx(routes=None, env=None, cache=None):
    return Context(http=FakeHttp(routes or {}), config=load_config(), env=env or {}, now=NOW, cache=cache or {})


# ---------- Deal-Blogs ----------

FEED = """<?xml version="1.0"?><rss xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel>
<item><title>🍟 Philips Airfryer 5000 HD9255/90 für 79,99€ (statt 119€)</title>
<link>https://blog.example/philips-hd9255</link><category>Küche</category><category>Amazon</category>
<description><![CDATA[<p>Bei Amazon gibt es den Airfryer gerade günstig.</p>]]></description></item>
<item><title>[Ab 64,99€] Tefal Easy Fry Deluxe EY401D</title><link>https://blog.example/tefal</link>
<description>Bei MediaMarkt bekommt ihr die Fritteuse inkl. Versand.</description></item>
<item><title>Tefal EY401D Heißluftfritteuse</title><link>https://blog.example/tefal2</link>
<description>Aktuell bei Otto ab 61,90€ erhältlich.</description></item>
<item><title>Philips HD9255 Gewinnspiel – gratis 0€</title><link>https://blog.example/gratis</link><description>x</description></item>
<item><title>Opel Frontera Leasing für 199€ im Monat</title><link>https://blog.example/opel</link><description>x</description></item>
</channel></rss>"""


def test_blog_feed_offers():
    src = dealblogs.SOURCES[0]
    c = ctx({src.url: FEED})
    offers = src.fetch(PRODUCTS, c)
    got = sorted((o.product_id, o.price, o.shop, o.shipping) for o in offers)
    assert got == [("philips-hd9255", 79.99, "Amazon", None),
                   ("tefal-ey401d", 61.9, "Otto", None),
                   ("tefal-ey401d", 64.99, "MediaMarkt", 0.0)]
    tefal_text = next(o for o in offers if o.price == 61.9)
    assert "Preis aus dem Beitragstext" in tefal_text.hints
    assert all(o.source == "mein-deal" for o in offers)
    assert c.notes == ["5 Beiträge (1 Feed-Seite)"]  # Beiträge ohne Datum -> nicht weiterblättern


def _feed(*items):
    body = "".join(f"<item><title>{t}</title><link>https://b/{t}</link><pubDate>{d}</pubDate></item>" for t, d in items)
    return f"<rss><channel>{body}</channel></rss>"


def test_blog_pages_until_last_run():
    src = dealblogs.SOURCES[0]
    p1 = _feed(("a", "Wed, 25 Nov 2026 10:50:00 +0000"), ("b", "Wed, 25 Nov 2026 10:20:00 +0000"))
    p2 = _feed(("c", "Wed, 25 Nov 2026 09:40:00 +0000"), ("d", "Wed, 25 Nov 2026 09:10:00 +0000"))
    p3 = _feed(("e", "Wed, 25 Nov 2026 08:00:00 +0000"))
    routes = {src.url: p1, src.url + "?paged=2": p2, src.url + "?paged=3": p3}
    # letzter Abruf 10:30 Uhr Berlin = 09:30 UTC -> Seite 2 reicht bis 09:10 UTC, Seite 3 nicht nötig
    c = ctx(routes, cache={"blogs": {"mein-deal": "2026-11-25T10:30:00+01:00"}})
    items, pages = src.read_items(c)
    assert pages == 2 and [i["title"] for i in items] == ["a", "b", "c", "d"]
    assert c.cache["blogs"]["mein-deal"] == NOW.isoformat(timespec="seconds")
    # Seite 2 kaputt -> Seite 1 reicht trotzdem
    c2 = ctx({src.url: p1}, cache={"blogs": {"mein-deal": "2026-11-25T08:00:00+01:00"}})
    assert src.read_items(c2)[1] == 1
    assert dealblogs.SOURCES[2].page_url(2) == "https://schnaeppchenfuchs.com/rss?page=2"


def test_all_blog_sources_registered():
    from dealradar.sources import all_sources
    names = [s.NAME for s in all_sources()]
    for n in ("mein-deal", "mytopdeals", "schnaeppchenfuchs", "dealdoktor", "hersteller", "postfach"):
        assert n in names
        assert isinstance(load_config()["quellen"][n], bool)  # jede Quelle hat einen Schalter


# ---------- Herstellershops ----------

TEFAL_MAP = """<urlset><url><loc>https://www.tefal.de/p/easy-fry-deluxe-ey401d/1510001458</loc></url>
<url><loc>https://www.tefal.de/p/easy-fry-grill-ey5058/123</loc></url></urlset>"""
COSORI_INDEX = """<sitemapindex><sitemap><loc>https://cosori.de/sitemap_products_1.xml?from=1&amp;to=2</loc></sitemap>
<sitemap><loc>https://cosori.de/sitemap_blogs_1.xml</loc></sitemap></sitemapindex>"""
COSORI_PRODUCTS = "<urlset><url><loc>https://cosori.de/products/turbo-blaze</loc></url></urlset>"
PAGE = ('<script type="application/ld+json">{"@type":"Product","name":"Easy Fry Deluxe EY401D",'
        '"offers":{"@type":"Offer","price":"69.99","priceCurrency":"EUR","availability":"InStock"}}</script>')


def test_hersteller_finds_page_via_sitemap_and_caches(monkeypatch):
    monkeypatch.setattr(hersteller, "load_shops", lambda: [
        {"name": "Tefal", "sitemap": "https://www.tefal.de/sm.xml"},
        {"name": "Cosori", "sitemap": "https://cosori.de/sitemap.xml"},
    ])
    routes = {
        "https://www.tefal.de/sm.xml": TEFAL_MAP,
        "https://www.tefal.de/p/easy-fry-deluxe-ey401d/1510001458": PAGE,
        "https://cosori.de/sitemap.xml": COSORI_INDEX,
        "https://cosori.de/sitemap_products_1.xml?from=1&to=2": COSORI_PRODUCTS,
    }
    c = ctx(routes)
    offers = hersteller.fetch(PRODUCTS, c)
    assert [(o.product_id, o.shop, o.price) for o in offers] == [("tefal-ey401d", "Tefal", 69.99)]
    assert "https://cosori.de/sitemap_blogs_1.xml" not in c.http.calls  # nur Produkt-Sitemaps
    # zweiter Lauf: Sitemaps kommen aus dem Zwischenspeicher, nur die Produktseite wird geladen
    c2 = ctx(routes, cache=c.cache)
    hersteller.fetch(PRODUCTS, c2)
    assert c2.http.calls == ["https://www.tefal.de/p/easy-fry-deluxe-ey401d/1510001458"]
    # neues Produkt -> Sitemap wird sofort neu gelesen
    more = PRODUCTS + parse_products([{"id": "neu", "name": "X", "suchbegriffe": ["EY5058"], "zielpreis": 1}])
    c3 = ctx(routes, cache=c.cache)
    hersteller.fetch(more, c3)
    assert "https://www.tefal.de/sm.xml" in c3.http.calls


def test_shops_yaml_is_valid():
    shops = hersteller.load_shops()
    assert {s["name"] for s in shops} == {"Tefal", "Cosori"}
    assert not any("ninja" in s["sitemap"] or "philips" in s["sitemap"] for s in shops)


# ---------- Gmail-Postfach ----------

def mail(sender, subject, html, date="Tue, 24 Nov 2026 10:00:00 +0100"):
    m = EmailMessage()
    m["From"], m["Subject"], m["Date"] = sender, subject, date
    m.set_content("Bitte HTML anzeigen")
    m.add_alternative(html, subtype="html")
    return m


MAILS = [
    mail("idealo <preisalarm@idealo.de>", "Preisalarm: Philips Airfryer HD9255/90 jetzt für 74,90 €",
         '<p>Der Preis ist gefallen!</p><a href="https://www.idealo.de/preisvergleich/OffersOfProduct/123.html?uid=GEHEIM">Ansehen</a>'),
    mail("Otto Newsletter <news@mail.otto.de>", "Nur heute: 20 % Rabatt!",
         "<p>Mit dem Gutscheincode XMAS20 bekommst du 20 % Rabatt ab 50 € Mindestbestellwert, gültig bis 30.11.2026</p>"),
    mail("MediaMarkt <info@newsletter.mediamarkt.de>", "10 € geschenkt",
         "<p>Code: MM10EURO – 10 € Rabatt ab 100 €. Gültig bis 01.11.2026</p>"),  # abgelaufen
    mail("Freund <max@example.org>", "Hallo", "<p>Kein Gutschein hier, nur 20 % gute Laune</p>"),
]


def test_postfach_not_configured_is_skipped():
    with pytest.raises(Skipped, match="nicht eingerichtet"):
        postfach.fetch(PRODUCTS, ctx())


def test_postfach_alarm_and_coupons(monkeypatch):
    monkeypatch.setattr(postfach, "read_mails", lambda env, since: MAILS)
    c = ctx(env={"DEAL_MAIL_ADRESSE": "a@gmail.com", "DEAL_MAIL_APP_PASSWORT": "x"})
    offers = postfach.fetch(PRODUCTS, c)
    assert len(offers) == 1
    o = offers[0]
    assert (o.product_id, o.price, o.shop) == ("philips-hd9255", 74.9, "idealo (Preisalarm)")
    assert o.url == "https://www.idealo.de/preisvergleich/OffersOfProduct/123.html"  # ohne ?uid=
    g = c.cache["gutscheine"]
    assert g == [{"shop": "Otto Newsletter", "domain": "otto.de", "rabatt_prozent": 20, "rabatt_euro": None,
                  "mindestbestellwert": 50.0, "gueltig_bis": "2026-11-30", "mail_vom": "2026-11-24"}]
    # Codes und Mail-Adressen dürfen NIE gespeichert werden (Repo ist öffentlich)
    assert "XMAS20" not in str(c.cache) and "@" not in str(c.cache)


# ---------- Duplikate ----------

def offer(source, shop, price, shipping=0.0, hints=None):
    return Offer(product_id="p", source=source, shop=shop, title="t", url=f"https://{source}/x", price=price,
                 shipping=shipping, hints=hints or [])


def test_merge_duplicates_across_sources():
    offers = [
        offer("mein-deal", "Amazon", 79.99, None, ["Versand unbekannt"]),
        offer("mydealz", "amazon.de", 79.99, 0.0, ["nur mit Prime"]),
        offer("dealdoktor", "Amazon", 79.99, None),
        offer("mydealz", "MediaMarkt", 79.99),   # anderer Shop -> bleibt
        offer("shop", "www.media-markt.de", 85.0),  # anderer Preis -> bleibt
    ]
    merged = logic.merge_duplicates(offers)
    assert len(merged) == 3
    amazon = next(o for o in merged if logic.norm_shop(o.shop) == "amazon")
    assert amazon.source == "mydealz"  # Community vor Blogs
    assert amazon.weitere_quellen == ["dealdoktor", "mein-deal"]
    assert amazon.hints == ["nur mit Prime"]
    assert logic.norm_shop("www.Media-Markt.de") == logic.norm_shop("MediaMarkt") == "mediamarkt"


def test_merge_prefers_direct_shop_reading():
    merged = logic.merge_duplicates([offer("mydealz", "Tefal", 69.99), offer("hersteller", "tefal.de", 69.99)])
    assert len(merged) == 1 and merged[0].source == "hersteller" and merged[0].weitere_quellen == ["mydealz"]


def test_alert_names_other_sources():
    from dealradar.telegram import format_alert
    p = PRODUCTS[1]
    o = offer("mydealz", "Amazon", 49.0)
    o.product_id, o.weitere_quellen = p.id, ["mein-deal"]
    assert "Quelle: mydealz (auch: mein-deal)" in format_alert(logic.Alert(p, o, None, ["Zielpreis erreicht"]))

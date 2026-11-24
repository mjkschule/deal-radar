"""Tests der Quellen-Parser mit kleinen, selbst geschriebenen Beispieldaten (keine Netzwerkzugriffe)."""

import json

from dealradar.config import Product
from dealradar.products_edit import append_product, parse_issue_form, parse_telegram_command, slugify
from dealradar.robots import Robots
from dealradar.sources import ebay, leasingmarkt, mydealz, shop, sparneuwagen

MYDEALZ_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss xmlns:pepper="http://www.pepper.com/rss" version="2.0"><channel><title>t</title>
<item><title><![CDATA[Makita DHP490RFX3 Set (2x 3,0 Ah) für 199,99€ inkl. Versand]]></title>
<link>https://www.mydealz.de/deals/makita-1</link>
<description><![CDATA[<strong>199,99€ - Beispielshop</strong><p>Mit Gutscheincode MAKITA10</p>]]></description>
<pepper:merchant name="Beispielshop" price="199,99€"/></item>
<item><title><![CDATA[Bosch Akkuschrauber 49€]]></title><link>https://www.mydealz.de/deals/bosch-2</link>
<description><![CDATA[x]]></description><pepper:merchant name="Shop2" price="49€"/></item>
</channel></rss>"""


def test_mydealz_feed_parsing():
    items = mydealz.parse_feed(MYDEALZ_RSS)
    assert len(items) == 2
    assert items[0]["merchant"] == "Beispielshop"
    p = Product(id="makita", name="Makita", suchbegriffe=["DHP490RFX3"], zielpreis=215)
    o = mydealz.offer_from_item(items[0], p)
    assert o.price == 199.99
    assert o.shipping == 0.0
    assert "Gutschein/Code nötig" in o.hints


def test_mydealz_feed_paths():
    p = Product(id="x", name="x", suchbegriffe=["x"], zielpreis=1, mydealz_gruppen=["makita", "new"])
    assert mydealz.feed_paths([p], ["new", "hot"]) == ["new", "hot", "gruppe/makita"]


def test_shop_jsonld():
    page = """<html><script type="application/ld+json">{"@context":"https://schema.org","@type":"Product",
    "name":"Epson ET-2922","offers":{"@type":"Offer","price":"179.90","priceCurrency":"EUR",
    "availability":"https://schema.org/InStock","shippingDetails":{"shippingRate":{"value":"4.95"}}}}</script></html>"""
    info = shop.extract_price(page)
    assert info["price"] == 179.90 and info["shipping"] == 4.95 and info["available"]
    assert info["name"] == "Epson ET-2922"


def test_shop_jsonld_nested_offer_without_type():
    page = """<script type="application/ld+json">{"@type":"Product","name":"X",
    "offers":[{"price":199.9,"priceCurrency":"EUR","availability":"InStock"}]}</script>"""
    assert shop.extract_price(page)["price"] == 199.9


def test_shop_microdata_takes_lowest():
    page = '<span itemprop="price" content="109.00"></span><span itemprop="price" content="73.78"></span>'
    assert shop.extract_price(page)["price"] == 73.78


def test_shop_out_of_stock():
    page = """<script type="application/ld+json">{"@type":"Offer","price":"10","priceCurrency":"EUR",
    "availability":"https://schema.org/OutOfStock"}</script>"""
    assert shop.extract_price(page)["available"] is False


def test_leasingmarkt_listing_parsing():
    data = {"currentPage": 1, "totalPages": 3, "listings": [{
        "id": 1, "targetGroup": "Nur Privatkunden", "fuelCategory": "Elektro", "makeName": "Opel",
        "modelName": "Frontera", "headline": "Frontera Electric Edition", "url": "/leasing/pkw/opel-frontera/1?adVariant=11",
        "leasingOffer": {"id": 11, "duration": 48, "includedMileage": 10000, "monthlyRate": 199},
        "offers": [{"id": 12, "duration": 36, "includedMileage": 10000, "monthlyRate": 219},
                   {"id": 13, "duration": 36, "includedMileage": 15000, "monthlyRate": 239},
                   {"id": 14, "duration": 36, "includedMileage": 20000, "monthlyRate": 259}]}]}
    page = 'xx self.__next_f.push([1,"{\\"initialResult\\":' + json.dumps(data).replace('"', '\\"') + '}"])'
    listings, pages = leasingmarkt.parse_listings(page)
    assert pages == 3 and len(listings) == 1
    best, worst = leasingmarkt.select_offers(listings[0], 36, 15000)
    assert best["id"] == 13 and worst["id"] == 12
    assert leasingmarkt._detail_url(listings[0], 13).endswith("adVariant=13")


def test_leasingmarkt_detail_costs():
    page = ("<div>Einmalige Kosten inkl. MwSt.</div><div>Anzahlung</div><div>0,00 €</div>"
            "<div>Überführungskosten</div><div>1.323,30 €</div><div>Zulassungskosten</div><div>169,00 €</div>")
    assert leasingmarkt.parse_detail_costs(page) == {"sonderzahlung": 0.0, "bereitstellung": 1492.3}


def test_sparneuwagen_item():
    xml = """<?xml version="1.0"?><rss version="2.0"><channel><item>
    <title>Opel Frontera Electric Leasing für 199 Euro im Monat brutto [sofort verfügbar]</title>
    <link>https://www.sparneuwagen.de/opel-frontera-1/</link>
    <description><![CDATA[Für 199 Euro brutto monatlich bei 36 Monaten Laufzeit und 15.000 Kilometern jährlich]]></description>
    <category><![CDATA[Privat]]></category><category><![CDATA[Elektro]]></category></item></channel></rss>"""
    items = sparneuwagen.parse_feed(xml)
    p = Product(id="f", name="f", suchbegriffe=["Frontera Electric"], zielpreis=250, typ="leasing")
    o = sparneuwagen.offer_from_item(items[0], p)
    assert o.price == 199.0 and o.leasing["monate"] == 36 and o.leasing["km"] == 15000
    assert o.leasing["gewerbe"] is False


def test_ebay_response():
    data = {"itemSummaries": [
        {"title": "Makita DHP490RFX3 Set NEU", "price": {"value": "209.00", "currency": "EUR"},
         "shippingOptions": [{"shippingCost": {"value": "0.00", "currency": "EUR"}}],
         "itemWebUrl": "https://www.ebay.de/itm/1", "seller": {"username": "werkzeugprofi", "feedbackPercentage": "99.8"},
         "itemLocation": {"country": "DE"}},
        {"title": "Bosch etwas anderes", "price": {"value": "10", "currency": "EUR"}, "itemWebUrl": "x"}]}
    p = Product(id="m", name="m", suchbegriffe=["DHP490RFX3"], zielpreis=215)
    offers = ebay.offers_from_response(data, p)
    assert len(offers) == 1
    assert offers[0].price == 209.0 and offers[0].shipping == 0.0
    assert "werkzeugprofi" in offers[0].hints[0]


def test_robots_wildcards():
    r = Robots("User-agent: *\nDisallow: /search\nDisallow: */feed/\nAllow: /feed/$\nDisallow: /*?sort=\n")
    ua = "DealRadar/1.0"
    assert r.can_fetch(ua, "https://x.de/feed/")
    assert not r.can_fetch(ua, "https://x.de/category/a/feed/")
    assert not r.can_fetch(ua, "https://x.de/search?q=1")
    assert not r.can_fetch(ua, "https://x.de/list?sort=price")
    assert r.can_fetch(ua, "https://x.de/rss/gruppe/makita")


def test_robots_specific_agent_group():
    r = Robots("User-agent: *\nAllow: /\n\nUser-agent: DealRadar\nDisallow: /\n")
    assert not r.can_fetch("DealRadar/1.0 (test)", "https://x.de/a")
    assert r.can_fetch("OtherBot", "https://x.de/a")


def test_telegram_command_and_issue_form(tmp_path):
    cmd = parse_telegram_command("/neu Bosch PSR 18; 89,90; PSR 18 LI-2, PSR18")
    assert cmd == {"name": "Bosch PSR 18", "zielpreis": 89.9, "suchbegriffe": ["PSR 18 LI-2", "PSR18"]}
    body = ("### Name\n\nDe'Longhi Magnifica S\n\n### Kategorie\n\nhaushalt\n\n### Suchbegriffe\n\nMagnifica S\nECAM 22.110\n\n"
            "### Zielpreis (€)\n\n249\n\n### Ausschlusswörter\n\n_No response_\n\n### Shop-URLs\n\nhttps://shop.test/p/1\n")
    prod = parse_issue_form(body)
    assert prod["suchbegriffe"] == ["Magnifica S", "ECAM 22.110"]
    assert prod["zielpreis"] == 249.0 and prod["shop_urls"] == ["https://shop.test/p/1"]
    assert "ausschluss" not in prod
    f = tmp_path / "products.yaml"
    f.write_text("# Kommentar bleibt\n- id: a\n  name: A\n  suchbegriffe: [a]\n  zielpreis: 1\n", encoding="utf-8")
    entry = append_product(f, prod)
    assert entry["id"] == slugify("De'Longhi Magnifica S") == "de-longhi-magnifica-s"
    text = f.read_text(encoding="utf-8")
    assert text.startswith("# Kommentar bleibt") and "Magnifica S" in text
    assert append_product(f, prod)["id"] == "de-longhi-magnifica-s-2"

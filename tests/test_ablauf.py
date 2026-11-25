"""Abgelaufene (mydealz) und von Hand ausgeblendete Angebote."""

import datetime as dt

from dealradar import ablauf, botdata, logic, page
from dealradar.config import load_config, parse_products
from dealradar.http import FetchError
from dealradar.meldungen import offer_hash
from dealradar.models import ABGELAUFEN, IGNORIERT, OK, Offer

CFG = load_config()
NOW = dt.datetime(2026, 11, 25, 20, 0, tzinfo=dt.timezone(dt.timedelta(hours=1)))
DEAL = "https://www.mydealz.de/deals/makita-dhp490rfx3-set-2877733"
P = parse_products([{"id": "makita", "name": "Makita DHP490RFX3", "suchbegriffe": ["DHP490RFX3"],
                     "zielpreis": 215, "kategorie": "werkzeug"}])[0]

EXPIRED_HTML = ('<div class="text--b">Leider ist dieser Deal mittlerweile abgelaufen</div>'
                '<script>{"commentCount":19,"isExpired":true,"threadExpiryBanners":{}}</script>')
ACTIVE_HTML = '<script>{"filter":{"expired":null},"isExpired":false}</script>'


class FakeHttp:
    def __init__(self, pages):
        self.pages, self.calls = pages, []

    def get(self, url):
        self.calls.append(url)
        page_ = self.pages.get(url)
        if isinstance(page_, Exception):
            raise page_
        return page_


def offer(url=DEAL, price=184.0, shop="BAUR"):
    return Offer(product_id="makita", source="mydealz", shop=shop, title="Makita DHP490RFX3 Set", url=url,
                 price=price, shipping=0.0)


def test_detects_expiry_flag_and_text():
    assert ablauf.expired_from_html(EXPIRED_HTML) is True
    assert ablauf.expired_from_html(ACTIVE_HTML) is False
    assert ablauf.expired_from_html("<p>Leider ist dieser Deal mittlerweile abgelaufen</p>") is True
    assert ablauf.expired_from_html("<p>irgendwas</p>") is None
    # zweite Seiten-Fassung (reines HTML, so bekommt sie das Radar)
    html2 = ('<div id="thread_details_2877733" class="aGrid thread--expired thread thread--deal">'
             '<span class="size--all-m">Dieser Deal ist vor 5 Min. abgelaufen</span>')
    assert ablauf.expired_from_html(html2) is True
    assert ablauf.expired_from_html(html2.split("<span")[0]) is True
    assert ablauf.expired_from_html('<div id="thread_details_1" class="aGrid thread thread--deal">') is False
    assert ablauf.checkable(DEAL) and not ablauf.checkable("https://www.baur.de/p/123")
    assert not ablauf.checkable("https://www.mydealz.de/rss/gruppe/makita")


def test_expired_offer_is_hidden_and_not_alerted():
    state, http = {}, FakeHttp({DEAL: EXPIRED_HTML})
    o = offer()
    alerts = logic.evaluate(P, [o], state, CFG["regeln"],
                            after_classify=lambda offs: ablauf.check(ablauf.candidates(offs), state, http, CFG, NOW))
    assert o.status == ABGELAUFEN and alerts == []
    logic.remember(P, [o], state, NOW, CFG["regeln"])
    assert logic.current_best(P, state, NOW, CFG["regeln"]) is None       # kein Preis mehr auf der Startseite
    assert "tiefstpreis" not in state or "makita" not in state["tiefstpreis"]
    html = page.product_card(P, state, {}, NOW, CFG["regeln"], page.ZoneInfo("Europe/Berlin"), CFG)
    assert "Kein aktuelles Angebot" in html and "Abgelaufen / ausgeblendet (1)" in html
    # abgelaufen bleibt abgelaufen: keine zweite Abfrage
    ablauf.check([offer()], state, http, CFG, NOW + dt.timedelta(hours=10))
    assert len(http.calls) == 1


def test_active_deal_rechecked_after_interval_and_budget():
    state, http = {}, FakeHttp({DEAL: ACTIVE_HTML})
    o = offer()
    ablauf.check([o], state, http, CFG, NOW)
    assert o.status == OK and len(http.calls) == 1
    ablauf.check([offer()], state, http, CFG, NOW + dt.timedelta(hours=1))
    assert len(http.calls) == 1                                          # noch frisch
    http.pages[DEAL] = EXPIRED_HTML
    o2 = offer()
    ablauf.check([o2], state, http, CFG, NOW + dt.timedelta(hours=4))     # nach 3 Std. neu geprüft
    assert len(http.calls) == 2 and o2.status == ABGELAUFEN
    # Budget gilt über alle Produkte eines Laufs
    many = [offer(url=f"https://www.mydealz.de/deals/x-{i}") for i in range(5)]
    http2 = FakeHttp({o.url: ACTIVE_HTML for o in many})
    budget = {"rest": 2}
    ablauf.check(many[:3], {}, http2, CFG, NOW, budget)
    ablauf.check(many[3:], {}, http2, CFG, NOW, budget)
    assert len(http2.calls) == 2


def test_fetch_error_keeps_offer_visible():
    state = {}
    o = offer()
    notes = ablauf.check([o], state, FakeHttp({DEAL: FetchError("HTTP 503")}), CFG, NOW)
    assert o.status == OK and "HTTP 503" in notes[0] and state["ablauf"] == {}


def test_ignored_offer_hidden_and_hide_link():
    o = offer()
    ignored = {offer_hash(o.key): {"quelle": "startseite"}}
    state = {}
    logic.evaluate(P, [o], state, CFG["regeln"], after_classify=lambda offs: ablauf.apply_ignored(offs, ignored))
    assert o.status == IGNORIERT
    # Link auf der Startseite nutzt denselben Schlüssel wie der Button „Ignorieren“
    ok = offer(url="https://www.mydealz.de/deals/anderer-deal-1")
    st = {"bot_name": "MeinDealRadarBot"}
    logic.remember(P, [ok], st, NOW, CFG["regeln"])
    html = page.product_card(P, st, {}, NOW, CFG["regeln"], page.ZoneInfo("Europe/Berlin"), CFG)
    assert f"https://t.me/MeinDealRadarBot?start=x_{offer_hash(ok.key)}" in html
    data = botdata.build([P], st, {}, CFG, NOW)["produkte"]["makita"]["angebote"]
    assert data[0]["h"] == offer_hash(ok.key) and data[0]["shop"] == "BAUR"
    # ohne bekannten Bot-Namen kein Link
    assert "t.me/" not in page.product_card(P, {**st, "bot_name": None}, {}, NOW, CFG["regeln"],
                                            page.ZoneInfo("Europe/Berlin"), CFG)

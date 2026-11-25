"""Tests für Suchbegriffe, Ausschlusswörter und die "guter Deal"-Logik."""

import datetime as dt
from zoneinfo import ZoneInfo

from dealradar.config import Product, end_datetime, is_over, parse_products
from dealradar.logic import evaluate, mark_reported, remember
from dealradar.matching import check_minimums, excluded_word, matches, missing_required
from dealradar.models import AUSGESCHLOSSEN, NICHT_PASSEND, OK, VERDAECHTIG, Offer

RULES = {"rabatt_vs_tiefstpreis": 0.10, "verdacht_unter_median": 0.40, "aktuell_stunden": 48,
         "vergessen_nach_tagen": 7}
NOW = dt.datetime(2026, 11, 25, 12, 0, tzinfo=ZoneInfo("Europe/Berlin"))


def makita():
    return Product(id="makita", name="Makita DHP490RFX3", suchbegriffe=["DHP490RFX3"], zielpreis=215,
                   ausschluss=["DHP490Z", "solo", "ohne Akku"])


def offer(price, shop="Amazon", url=None, shipping=0.0, title="Makita DHP490RFX3 Set", pid="makita", **kw):
    return Offer(product_id=pid, source="test", shop=shop, title=title,
                 url=url or f"https://x.test/{shop}/{price}", price=price, shipping=shipping, **kw)


# --- Matching ---------------------------------------------------------------

def test_model_number_with_spaces():
    p = makita()
    assert matches(p, "Makita DHP 490 RFX3 Akku-Schlagbohrschrauber")
    assert matches(p, "makita dhp490rfx3")
    assert not matches(p, "Makita DHP489 Set")


def test_phrase_needs_all_words():
    p = Product(id="m", name="m", suchbegriffe=["24 Zoll Monitor"], zielpreis=75)
    assert matches(p, 'Acer 24" Monitor Full HD')
    assert matches(p, "Monitor mit 24 Zoll")
    assert not matches(p, "24 Zoll Fernseher")


def test_exclusions():
    p = makita()
    assert excluded_word(p, "Makita DHP490Z solo ohne Akku") == "DHP490Z"
    assert excluded_word(p, "Makita DHP490RFX3 Solo-Gerät") == "solo"
    assert excluded_word(p, "Makita DHP490RFX3 Set mit 2 Akkus") is None


def test_minimums_and_required_hints():
    p = Product(id="m", name="m", suchbegriffe=["Monitor"], zielpreis=75, mindestwerte={"Hz": 75},
                pflicht_hinweise=["VESA"])
    assert check_minimums(p, "Monitor 60Hz")[0] == "nur 60 Hz (mind. 75)"
    assert check_minimums(p, "Monitor 100 Hz") == (None, [])
    assert check_minimums(p, "Monitor")[1] == ["bitte prüfen: Hz ≥ 75"]
    assert missing_required(p, "Monitor 100 Hz") == ["bitte prüfen: VESA"]
    assert missing_required(p, "Monitor VESA 100x100") == []


# --- Deal-Logik ---------------------------------------------------------------

def test_target_price_alert_and_no_duplicate():
    p, state = makita(), {}
    alerts = evaluate(p, [offer(209.0)], state, RULES)
    assert len(alerts) == 1 and "Zielpreis erreicht" in alerts[0].reasons
    mark_reported(state, alerts[0])
    # gleiches Angebot im nächsten Lauf -> keine Meldung
    assert evaluate(p, [offer(209.0)], state, RULES) == []
    # gleiches Angebot wird billiger -> neue Meldung
    assert len(evaluate(p, [offer(199.0, url="https://x.test/Amazon/209.0")], state, RULES)) == 1


def test_same_shop_same_price_other_link_not_reported_twice():
    p, state = makita(), {}
    alerts = evaluate(p, [offer(200.0, url="https://a.test/1"), offer(200.0, url="https://a.test/2")], state, RULES)
    assert len(alerts) == 1


def test_ten_percent_below_lowest():
    p, state = makita(), {}
    remember(p, [offer(300.0)], state, NOW, RULES)        # Tiefstpreis 300
    assert evaluate(p, [offer(280.0, shop="Otto")], state, RULES) == []   # nur 6,7 % billiger
    alerts = evaluate(p, [offer(269.0, shop="Otto")], state, RULES)        # 10,3 % billiger
    assert len(alerts) == 1 and alerts[0].previous_low == 300.0


def test_shipping_is_included_in_comparison():
    p, state = makita(), {}
    assert evaluate(p, [offer(210.0, shipping=9.90)], state, RULES) == []  # 219,90 > 215


def test_exclusion_and_suspicious_are_not_reported():
    p, state = makita(), {}
    excl = offer(99.0, title="Makita DHP490RFX3 solo")
    cheap = offer(50.0, shop="Fake")
    alerts = evaluate(p, [excl, cheap, offer(250.0, shop="Otto")], state, RULES)
    assert alerts == []
    assert excl.status == AUSGESCHLOSSEN
    assert cheap.status == VERDAECHTIG


def test_leasing_rules():
    p = Product(id="frontera", name="Frontera", suchbegriffe=["Frontera"], zielpreis=250, typ="leasing",
                leasing={"laufzeit_monate": 36, "min_km_jahr": 15000, "max_sonderzahlung": 1000})
    good = Offer("frontera", "t", "Händler A", "Frontera", "https://a.test/1", 239.0,
                 leasing={"rate": 239.0, "monate": 36, "km": 15000, "sonderzahlung": 0.0, "bereitstellung": 900.0})
    few_km = Offer("frontera", "t", "Händler B", "Frontera", "https://a.test/2", 199.0,
                   leasing={"rate": 199.0, "monate": 36, "km": 10000, "sonderzahlung": 0.0, "bereitstellung": 0.0})
    alerts = evaluate(p, [good, few_km], {}, RULES)
    assert [a.offer for a in alerts] == [good]
    assert few_km.status == NICHT_PASSEND
    assert good.effective_rate == 264.0      # (239*36 + 0 + 900) / 36
    assert good.status == OK


def test_end_date_inclusive():
    cfg = {"enddatum": "2026-11-27T23:59", "zeitzone": "Europe/Berlin", "nach_ende": "aus"}
    tz = ZoneInfo("Europe/Berlin")
    assert not is_over(cfg, dt.datetime(2026, 11, 27, 23, 59, 30, tzinfo=tz))
    assert is_over(cfg, dt.datetime(2026, 11, 28, 0, 0, 1, tzinfo=tz))
    # Standard nach dem Ende: Wunschlisten-Modus – nicht abschalten
    assert not is_over({**cfg, "nach_ende": "wunschliste"}, dt.datetime(2026, 11, 28, 0, 0, 1, tzinfo=tz))
    assert end_datetime(cfg).utcoffset() == dt.timedelta(hours=1)


def test_products_yaml_is_valid():
    import pathlib

    import yaml
    raw = yaml.safe_load((pathlib.Path(__file__).parent.parent / "products.yaml").read_text(encoding="utf-8"))
    products = parse_products(raw)
    assert len(products) >= 1  # Liste ändert sich per Telegram
    assert any(p.is_leasing for p in products)

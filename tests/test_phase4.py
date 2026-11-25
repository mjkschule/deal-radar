"""Tests für Phase 4: Effektivpreis, Bedingungen, Vertrauen, B-Ware, EAN, Alternativen,
Deal-Score, Kaufen-oder-Warten und Preise ohne UVP/Streichpreis."""

import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from dealradar import bewertung, logic
from dealradar.config import ConfigError, expand_alternatives, load_config, parse_products
from dealradar.models import AUSGESCHLOSSEN, OK, Offer
from dealradar.prices import parse_price
from dealradar.score import deal_score, explain
from dealradar.telegram import format_alert

TZ = ZoneInfo("Europe/Berlin")
NOW = dt.datetime(2026, 11, 25, 12, 0, tzinfo=TZ)
CFG = load_config()


def offer(price=100.0, shipping=0.0, shop="Otto", title="Philips HD9255", text="", **kw):
    return Offer(product_id="p", source="mydealz", shop=shop, title=title, url="https://x/1", price=price,
                 shipping=shipping, text=text or title, **kw)


PRODUCT = parse_products([{"id": "p", "name": "Philips HD9255", "suchbegriffe": ["HD9255"], "zielpreis": 80,
                           "ean": "8710103999999"}])[0]

# ---------- Preise: UVP / Streichpreise zählen nie ----------


@pytest.mark.parametrize("text,price", [
    ("UVP 119€ jetzt 79€", 79.0),
    ("statt 119,99 € nur 79 €", 79.0),
    ("Philips HD9255 für 79,99€ (statt 119€)", 79.99),
    ("Streichpreis 149 € – Aktionspreis 99 €", 99.0),
    ("Makita für 184€ (PVG 229€)", 184.0),
    ("119 € UVP, jetzt 79 €", 79.0),
    ("idealo ab 99€ – hier 89€", 89.0),
    ("nur 49,99€", 49.99),
    ("UVP 119 €", None),
])
def test_price_ignores_reference_prices(text, price):
    assert parse_price(text) == price


# ---------- Effektivpreis ----------

COUPON = {"shop": "Otto Newsletter", "domain": "otto.de", "rabatt_prozent": 20, "rabatt_euro": None,
          "mindestbestellwert": 50.0, "gueltig_bis": "2026-11-30", "mail_vom": "2026-11-24"}


def test_effective_price_with_coupon_and_calculation():
    o = offer(79.99, 4.95)
    bewertung.apply_effective([o], CFG, [COUPON], NOW)
    assert o.abzuege == [{"art": "gutschein", "betrag": 16.0, "text": "Gutschein 20 % (Code in deiner Mail vom 24.11.)"}]
    assert o.compare_price == 68.94
    assert bewertung.rechenweg(o) == ("79,99 € + 4,95 € Versand − 16,00 € Gutschein 20 % (Code in deiner Mail vom "
                                      "24.11.) = 68,94 €")


@pytest.mark.parametrize("change", [
    {"mindestbestellwert": 100.0},     # Mindestbestellwert nicht erreicht
    {"gueltig_bis": "2026-11-24"},     # abgelaufen
    {"domain": "mediamarkt.de"},       # anderer Shop
])
def test_coupon_only_when_conditions_match(change):
    o = offer(79.99, 0)
    bewertung.apply_effective([o], CFG, [{**COUPON, **change}], NOW)
    assert o.abzuege == [] and o.compare_price == 79.99 and bewertung.rechenweg(o) == ""


def test_cashback_and_payment_discount_from_config():
    cfg = {**CFG, "effektivpreis": {"gutscheine_aus_postfach": False, "cashback": {"otto.de": 3},
                                    "zahlungsrabatt_prozent": 1, "zahlungsrabatt_nur_shops": ["Otto"]}}
    o, other = offer(100.0, 5.0), offer(100.0, 5.0, shop="Amazon")
    bewertung.apply_effective([o, other], cfg, [COUPON], NOW)
    assert [a["betrag"] for a in o.abzuege] == [3.0, 1.02]   # 3 % von 100; 1 % von (105 − 3)
    assert o.compare_price == 100.98
    assert other.abzuege == []
    # Standard (deine Wahl): kein Cashback, kein Zahlungsrabatt
    assert CFG["effektivpreis"]["cashback"] == {} and CFG["effektivpreis"]["zahlungsrabatt_prozent"] == 0


def test_leasing_has_no_deductions():
    o = offer(300.0, None, leasing={"monate": 36, "sonderzahlung": 0, "bereitstellung": 900})
    bewertung.apply_effective([o], CFG, [COUPON], NOW)
    assert o.abzuege == [] and o.compare_price == 325.0


# ---------- Bedingungen, Vertrauen, B-Ware, EAN ----------

def classified(o, product=PRODUCT):
    from dealradar import prices
    o.hints = prices.detect_hints(o.text)
    logic.classify(product, o)
    return o


def test_conditions_are_marked():
    o = classified(offer(text="Philips HD9255 nur für Neukunden, Mindestbestellwert 50 €, nur für Plus-Mitglieder"))
    assert o.status == OK
    for h in ("nur für Neukunden", "Mindestbestellwert", "Mitgliedschaft nötig"):
        assert h in o.hints


def test_trust_flags():
    o = classified(offer(text="Philips HD9255 Versand aus China, Lieferzeit 3 Wochen, Rückgabe ausgeschlossen, "
                              "Verkauf durch Drittanbieter"))
    assert o.status == OK
    assert o.vertrauen == ["Marketplace-Händler – Verkäufer prüfen", "Versand aus dem Ausland",
                           "lange Lieferzeit (3 wochen)", "keine Rückgabe möglich"]
    weak = offer(title="Philips HD9255", hints=["eBay-Händler: abc (91.5 % positiv)"])
    assert "Händlerbewertung nur 91.5 % positiv" in bewertung.trust_flags(weak)
    assert bewertung.trust_flags(offer(text="Philips HD9255 Lieferzeit 2-3 Tage")) == []


def test_b_ware_only_when_allowed():
    o = classified(offer(text="Philips HD9255 B-Ware wie neu"))
    assert o.status == AUSGESCHLOSSEN and "b_ware: true" in o.status_reason
    ok_product = parse_products([{"id": "p", "name": "X", "suchbegriffe": ["HD9255"], "zielpreis": 80, "b_ware": True}])[0]
    o2 = classified(offer(text="Philips HD9255 refurbished"), ok_product)
    assert o2.status == OK and "gebraucht/B-Ware" in o2.hints
    text = format_alert(logic.Alert(ok_product, o2, None, ["Zielpreis erreicht"]))
    assert "♻️ <b>B-Ware / gebraucht / refurbished</b>" in text


def test_ean_mismatch_excludes_offer():
    assert classified(offer(ean="8710103000000")).status == AUSGESCHLOSSEN
    assert classified(offer(ean="08710103999999")).status == OK   # führende Null egal
    assert classified(offer(ean="")).status == OK


# ---------- Alternativen und Aliase ----------

def test_alternatives_become_search_rows():
    ps = parse_products([{"id": "phil", "name": "Philips HD9255", "suchbegriffe": ["HD9255"], "zielpreis": 80,
                          "aliase": ["Airfryer 5000 XL"],
                          "alternativen": [{"name": "Cosori Turbo Blaze", "suchbegriffe": ["Turbo Blaze"], "zielpreis": 90},
                                           {"name": "Tefal EY401D"}]}])
    rows = expand_alternatives(ps)
    assert [(r.id, r.zielpreis, r.main_id) for r in rows] == [
        ("phil", 80, "phil"), ("phil~alt1", 90, "phil"), ("phil~alt2", 80, "phil")]
    assert rows[2].suchbegriffe == ["Tefal EY401D"]
    from dealradar.matching import matches
    assert matches(ps[0], "Philips Airfryer 5000 XL im Angebot")  # Alias zählt wie ein Suchbegriff
    o = offer(85.0, 0, title="Cosori Turbo Blaze")
    text = format_alert(logic.Alert(rows[1], o, None, ["Zielpreis erreicht"]), main_name="Philips HD9255")
    assert "🔁 <i>Alternative zu Philips HD9255</i>" in text
    with pytest.raises(ConfigError):
        parse_products([{"id": "x", "name": "X", "suchbegriffe": ["a"], "zielpreis": 1, "alternativen": ["nur Text"]}])


# ---------- Deal-Score ----------

def pts(*prices):
    return [{"t": (NOW - dt.timedelta(hours=2 * i)).isoformat(), "bester": p} for i, p in enumerate(prices)]


def test_score_near_low_bonus_and_explanation():
    h = pts(*[100] * 9)
    assert deal_score(100, h, 98.5, NOW) == 55   # bis 2 % über Tiefstpreis: +5
    assert deal_score(100, h, 97, NOW) == 50
    assert explain(100, h, 89, NOW) == "Median 90 Tage: 100,00 € (9 Messungen) · Tiefstpreis: 89,00 €"
    assert explain(100, h[:3], None, NOW) == "noch zu wenig Preisverlauf (3 von 5 Messungen)"


# ---------- Kaufen oder warten ----------

@pytest.mark.parametrize("day,score,reached,start", [
    (25, 60, True, "✅ Kaufen: Zielpreis erreicht"),
    (25, 90, False, "✅ Kaufen: sehr guter Preis (Score 90)"),
    (25, 60, False, "⏳ Eher warten: Black Friday ist in 2 Tagen (27.11.)"),
    (26, None, False, "⏳ Eher warten: Black Friday ist in 1 Tag (27.11.)"),
    (28, 60, False, "⏳ Eher warten: Cyber Monday (30.11.)"),
    (30, 60, False, "🤔 Heute ist Cyber Monday"),
])
def test_buy_or_wait(day, score, reached, start):
    now = dt.datetime(2026, 11, day, 12, tzinfo=TZ)
    assert bewertung.buy_or_wait(CFG, now, score, reached).startswith(start)


def test_buy_or_wait_december():
    assert "spätestens um den 20.12." in bewertung.buy_or_wait(CFG, dt.datetime(2026, 12, 5, tzinfo=TZ), 50, False)
    assert bewertung.buy_or_wait(CFG, dt.datetime(2026, 12, 23, tzinfo=TZ), 50, False) == ""

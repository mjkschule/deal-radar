"""Die drei Kernrechnungen des Radars an einem Ort: Preise lesen, Effektivpreis, Deal-Score.

Jede Zeile ist ein Fall, wie er in echten Deal-Titeln vorkommt. Schlägt hier etwas fehl, stimmen
Meldungen oder Startseite nicht mehr.
"""

import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from dealradar import bewertung
from dealradar.config import load_config
from dealradar.models import Offer
from dealradar.prices import parse_price, parse_shipping
from dealradar.score import deal_score

TZ = ZoneInfo("Europe/Berlin")
NOW = dt.datetime(2026, 11, 25, 12, 0, tzinfo=TZ)
CFG = load_config()

# ---------------------------------------------------------------- 1. Preise lesen


@pytest.mark.parametrize("text,price", [
    ("1.299,00 €", 1299.0),                       # Tausenderpunkt + Komma
    ("1.299€", 1299.0),
    ("EUR 49,90", 49.9),                          # Währung davor
    ("49,90 EUR", 49.9),
    ("€ 59,99", 59.99),
    ("Preis: 19.99€", 19.99),                     # Punkt als Dezimaltrenner
    ("nur 7,- €", 7.0),                           # ",-"
    ("für 1299 Euro", 1299.0),
    ("ab 9€", 9.0),
    ("49 € statt 99 € (UVP)", 49.0),              # Streichpreis dahinter
    ("UVP 119€ jetzt 79€", 79.0),                 # Streichpreis davor
    ("Makita für 184€ (PVG 229€)", 184.0),        # Preisvergleich
    ("-20% auf alles", None),                     # kein Betrag
])
def test_price_formats(text, price):
    assert parse_price(text) == price


@pytest.mark.parametrize("text,price,shipping", [
    ("zzgl. 4,95 € Versand", 10, 4.95),
    ("+ 5,99€ VSK", 10, 5.99),
    ("Versand: 3,99€", 10, 3.99),
    ("versandkostenfrei", None, 0.0),
    ("inkl. Versand", None, 0.0),
    ("kostenloser Versand ab 29 €", 49, 0.0),     # Grenze erreicht
    ("kostenloser Versand ab 29 €", 19, None),    # Grenze nicht erreicht -> unbekannt, NICHT 29 €
    ("versandkostenfrei ab 50€, sonst 4,95 € Versand", 30, 4.95),
    ("versandkostenfrei ab 50€, sonst 4,95 € Versand", 60, 0.0),
    ("Super Angebot", 10, None),                  # nichts gesagt -> unbekannt
])
def test_shipping_formats(text, price, shipping):
    assert parse_shipping(text, price) == shipping


# ---------------------------------------------------------------- 2. Effektivpreis


def test_effective_price_full_formula():
    """Preis + Versand − Gutschein − Cashback − Zahlungsrabatt, mit Rechenweg."""
    cfg = {**CFG, "effektivpreis": {"gutscheine_aus_postfach": True, "cashback": {"Otto": 2},
                                    "zahlungsrabatt_prozent": 1, "zahlungsrabatt_nur_shops": []}}
    coupon = {"shop": "Otto", "domain": "otto.de", "rabatt_prozent": None, "rabatt_euro": 10.0,
              "mindestbestellwert": 50.0, "gueltig_bis": None, "mail_vom": "2026-11-24"}
    o = Offer(product_id="p", source="mydealz", shop="Otto", title="t", url="https://x", price=100.0, shipping=5.0)
    bewertung.apply_effective([o], cfg, [coupon], NOW)
    # 100 + 5 − 10 Gutschein − 1,80 Cashback (2 % von 90) − 0,93 Zahlart (1 % von 93,20) = 92,27
    assert [a["betrag"] for a in o.abzuege] == [10.0, 1.8, 0.93]
    assert o.compare_price == 92.27
    assert bewertung.rechenweg(o).endswith("= 92,27 €")
    assert o.target_value == 92.27  # mit dem Zielpreis verglichen wird der Effektivpreis


def test_effective_price_defaults_and_leasing():
    o = Offer(product_id="p", source="mydealz", shop="Otto", title="t", url="https://x", price=79.99, shipping=None)
    bewertung.apply_effective([o], CFG, [], NOW)
    assert o.compare_price == 79.99 and bewertung.rechenweg(o) == ""  # Versand unbekannt zählt als 0, kein Rechenweg
    lease = Offer(product_id="p", source="leasingmarkt", shop="L", title="t", url="https://x", price=299.0,
                  leasing={"monate": 36, "sonderzahlung": 1000, "bereitstellung": 980})
    # Effektive Rate = (299 × 36 + 1000 + 980) / 36 = 354,00
    assert lease.compare_price == 354.0 and lease.target_value == 299.0  # Alarm nach Monatsrate


# ---------------------------------------------------------------- 3. Deal-Score


def _history(*prices):
    return [{"t": (NOW - dt.timedelta(hours=2 * i)).isoformat(), "bester": p} for i, p in enumerate(prices)]


@pytest.mark.parametrize("price,low,score", [
    (100, 90, 50),     # üblicher Preis = Median
    (90, 80, 75),      # 10 % unter Median
    (80, 70, 100),     # 20 % unter Median
    (110, 90, 25),     # 10 % über Median
    (200, 90, 0),      # gedeckelt auf 0
    (100, 100, 60),    # = Allzeit-Tiefstpreis: +10
    (100, 98.5, 55),   # bis 2 % über Tiefstpreis: +5
    (70, 70, 100),     # gedeckelt auf 100
])
def test_deal_score_scale(price, low, score):
    assert deal_score(price, _history(*[100] * 10), low, NOW) == score


def test_deal_score_uses_only_own_history():
    h = _history(100, 100, 100, 100)                               # nur 4 Messungen
    assert deal_score(90, h, 90, NOW) is None                      # zu wenig Verlauf -> kein Score
    old = [{"t": (NOW - dt.timedelta(days=120)).isoformat(), "bester": 10}] * 20
    assert deal_score(100, _history(*[100] * 5) + old, None, NOW) == 50  # älter als 90 Tage zählt nicht

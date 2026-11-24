"""Tests für die Preis-Parser (dealradar/prices.py)."""

import pytest

from dealradar.prices import detect_hints, parse_leasing, parse_price, parse_shipping, to_number


@pytest.mark.parametrize("raw,expected", [
    ("1.234,56", 1234.56),
    ("1234,56", 1234.56),
    ("26.930", 26930.0),
    ("19,99", 19.99),
    ("19,-", 19.0),
    ("49", 49.0),
    ("1,234.56", 1234.56),
    ("2.199.000", 2199000.0),
    ("1 299,00", 1299.0),
    ("", None),
    ("abc", None),
])
def test_to_number_german(raw, expected):
    assert to_number(raw) == expected


def test_to_number_machine_format():
    # JSON-LD nutzt den Punkt als Dezimaltrenner
    assert to_number("199.9", german=False) == 199.9
    assert to_number("73.78", german=False) == 73.78
    assert to_number("1299.000", german=False) == 1299.0


@pytest.mark.parametrize("text,expected", [
    ("Epson EcoTank ET-2922 für 184,90 € bei Amazon", 184.90),
    ("nur 184,90 € statt 249 €", 184.90),
    ("ab 26930€ [Automobile Stauner]", 26930.0),
    ("€ 49,99 inkl. MwSt.", 49.99),
    ("Preis: 65,99 EUR", 65.99),
    ("Monitor für 1.099 Euro", 1099.0),
    ("Halterung 19,- €", 19.0),
    ("Gratis Probe", 0.0),
    ("Kein Preis hier", None),
    ("23,8 Zoll Monitor 144 Hz", None),
])
def test_parse_price(text, expected):
    assert parse_price(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("65,99€ (inkl. Versand)", 0.0),
    ("versandkostenfrei", 0.0),
    ("Kostenloser Versand", 0.0),
    ("zzgl. 4,95 € Versand", 4.95),
    ("+ 5,99€ VSK", 5.99),
    ("Versandkosten: 3,90 €", 3.90),
    ("Versand 6,99 €", 6.99),
    ("ab 29 € versandkostenfrei", 0.0),
    ("Toller Monitor", None),
])
def test_parse_shipping(text, expected):
    assert parse_shipping(text) == expected


def test_detect_hints():
    hints = detect_hints("Mit Gutscheincode SAVE10, nur für Neukunden, Verkauf durch Drittanbieter")
    assert "Gutschein/Code nötig" in hints
    assert "nur für Neukunden" in hints
    assert "Marketplace-Händler" in hints
    assert detect_hints("Ganz normaler Deal") == []


def test_parse_leasing_mydealz_title():
    t = "(Privatleasing) Opel Corsa Edition 1.2 Turbo 101 PS 99 €/mtl., eff. 140,39 €, 36 Mon., 10.000 km/Jahr, Schaltgetriebe"
    l = parse_leasing(t)
    assert l["rate"] == 99.0
    assert l["effektiv_angegeben"] == 140.39
    assert l["monate"] == 36
    assert l["km"] == 10000
    assert l["gewerbe"] is False


def test_parse_leasing_sparneuwagen_text():
    t = ("Opel Corsa Leasing für 135 Euro im Monat brutto [Vorführwagen] Mister Leasing bietet den Opel Corsa "
         "für 135 Euro brutto monatlich bei 24 Monaten Laufzeit und 10.000 Kilometern jährlich")
    l = parse_leasing(t)
    assert l["rate"] == 135.0
    assert l["monate"] == 24
    assert l["km"] == 10000


def test_parse_leasing_costs_and_tkm():
    t = ("Opel Frontera Electric 189 € mtl., 36 Monate, 15Tkm, Sonderzahlung 0 €, "
         "Überführung 990 €, Zulassung 150 €")
    l = parse_leasing(t)
    assert l["rate"] == 189.0
    assert l["km"] == 15000
    assert l["sonderzahlung"] == 0.0
    assert l["bereitstellung"] == 1140.0


def test_parse_leasing_no_downpayment_and_included_transfer():
    l = parse_leasing("Frontera Electric ohne Anzahlung 229 € im Monat inkl. Überführung, 48 Monate")
    assert l["sonderzahlung"] == 0.0
    assert l["bereitstellung"] == 0.0
    assert l["monate"] == 48


def test_parse_leasing_business():
    l = parse_leasing("Gewerbeleasing Opel Grandland GS 179 € netto/mtl., 24 Mon., 10.000 km/Jahr")
    assert l["gewerbe"] is True
    assert l["rate"] == 179.0


def test_parse_leasing_purchase_is_not_leasing():
    l = parse_leasing("Opel Frontera electric 43kWh 307km Reichweite förderfähig 21980€")
    assert l["rate"] is None

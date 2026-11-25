"""💥 Rabattknaller: Kategorien, Preisvergleich statt UVP, Hitze, Obergrenze, Meldeweg."""

import datetime as dt

import pytest

from dealradar import botdata, meldungen, page, rabattknaller
from dealradar.config import load_config
from dealradar.models import ABGELAUFEN, OK

CFG = load_config()
KATS = CFG["rabattknaller"]["kategorien"]
NOW = dt.datetime(2026, 11, 27, 12, 0, tzinfo=dt.timezone(dt.timedelta(hours=1)))


@pytest.mark.parametrize("title,kat", [
    ("Makita DHP482RTJ Akku-Schlagbohrschrauber Set 2x 5,0 Ah im Makpac", "schlagbohrset"),
    ("Bosch GSB 18V-55 Akku-Schlagbohrschrauber inkl. 2 Akkus", "schlagbohrset"),
    ("Makita DHP482Z Akku-Schlagbohrschrauber Solo", None),
    ("Bosch Akku-Schrauber IXO 7", None),
    ("LG UltraGear 27GR75Q 27 Zoll Gaming-Monitor QHD 165 Hz", "monitor"),
    ("Ergotron LX Monitorarm für Monitor bis 34 Zoll", None),
    ("Babyphone mit Monitor und Kamera", None),
    ("Ninja Foodi MAX Dual Zone Heißluftfritteuse AF400EU", "airfryer"),
    ("Cosori Airfryer Zubehör-Set 6-teilig", None),
    ("Klassische Fritteuse 3 Liter", None),
    ("Epson EcoTank ET-2856 Multifunktionsdrucker", "farbdrucker"),
    ("HP Envy 6032e Tintenstrahldrucker inkl. 3 Monate Instant Ink", "farbdrucker"),
    ("Brother HL-L2350DW Laserdrucker monochrom", None),
    ("HP 305 Druckerpatronen Multipack", None),
    ("Bambu Lab A1 mini 3D-Drucker", None),
])
def test_categories(title, kat):
    assert rabattknaller.category_of(title, title, KATS) == kat


@pytest.mark.parametrize("text,price,ref", [
    ("Dealpreis: 169,99 € inkl. Versand PVG: ca. 230 €", 159.99, 230.0),
    ("Nächster Preis ist Amazon mit 86,20 € (was …)", 34.99, 86.2),
    ("Der aktuelle Preisvergleich liegt bei 81,99 € inkl. Versand", 35.88, 81.99),
    ("Der Vergleichspreis (idealo) liegt aktuell bei rund 213 € – 240 €", 199.0, 213.0),
    ("Nur 99 € statt UVP 249 €", 99.0, None),              # UVP zählt nicht
    ("Jetzt 99 € statt 199 € (Streichpreis)", 99.0, None),  # Streichpreis zählt nicht
    ("idealo: 89 €, hier 99 €", 99.0, None),                # Preisvergleich niedriger -> kein Rabatt
])
def test_reference_is_price_comparison_only(text, price, ref):
    assert rabattknaller.reference_price(text, price) == ref


def item(title, desc, price, link, feed="gruppe/fritteusen"):
    return {"title": title, "description": desc, "price_raw": f"{price}€".replace(".", ","), "merchant": "Amazon",
            "link": link, "feed": feed}


RAW = {"mydealz": [
    item("Ninja Dual Zone Heißluftfritteuse AF300EU", "PVG 199 €", 99.0, "https://www.mydealz.de/deals/a-1"),   # 50 %
    item("Cosori Heißluftfritteuse 5,5 L", "PVG 79 €", 59.0, "https://www.mydealz.de/deals/b-2"),             # 25 %
    item("Tefal Easy Fry Heißluftfritteuse", "kein Vergleich", 49.0, "https://www.mydealz.de/deals/c-3"),     # heiß
    item("620° - Tefal Easy Fry Heißluftfritteuse", "", 49.0, "https://www.mydealz.de/deals/c-3", "trending"),
    item("Profi Airfryer 20 L Gastro", "PVG 999 €", 449.0, "https://www.mydealz.de/deals/d-4"),              # zu teuer
    item("Philips Airfryer 3000", "PVG 129 €", 85.0, "https://www.mydealz.de/deals/e-5"),                    # 34 %
]}


def test_find_rules_and_route():
    found = {o.url[-3:]: o for o in rabattknaller.find(RAW, CFG)}
    assert set(found) == {"a-1", "c-3", "e-5"}
    assert (found["a-1"].knaller["rabatt"], found["e-5"].knaller["rabatt"]) == (50, 34)
    assert found["c-3"].knaller["hitze"] == 620 and found["c-3"].knaller["rabatt"] is None
    assert found["c-3"].title == "Tefal Easy Fry Heißluftfritteuse"          # Temperatur nicht im Titel
    # schon über die Produktliste gefunden -> kein doppelter Knaller
    assert "a-1" not in {o.url[-3:] for o in rabattknaller.find(RAW, CFG, {"https://www.mydealz.de/deals/a-1"})}
    quiet_off = {**CFG, "ruhezeiten": {**CFG["ruhezeiten"], "aktiv": False}}
    assert rabattknaller.route(found["a-1"], quiet_off, NOW) == meldungen.SOFORT      # ab 40 % sofort
    assert rabattknaller.route(found["e-5"], quiet_off, NOW) == meldungen.UEBERSICHT  # 30–39 % -> 19 Uhr
    assert rabattknaller.route(found["c-3"], quiet_off, NOW) == meldungen.UEBERSICHT  # nur heiß -> 19 Uhr
    quiet_on = {**CFG, "ruhezeiten": {**CFG["ruhezeiten"], "aktiv": True}}
    night = dt.datetime(2026, 11, 27, 23, 30, tzinfo=NOW.tzinfo)
    assert rabattknaller.route(found["a-1"], quiet_on, night) == meldungen.RUHE
    text = rabattknaller.format_alert(found["a-1"])
    assert "Rabattknaller: Airfryer" in text and "−50 % ggü. Preisvergleich 199,00 €" in text


class NoHttp:
    def get(self, url):
        return '<div id="thread_details_1" class="thread thread--deal"></div>'


def test_update_reports_once_hides_expired_and_ignored():
    state = {"bot_name": "Bot"}
    found = rabattknaller.find(RAW, CFG)
    new = rabattknaller.update(state, found, NoHttp(), CFG, NOW, {})
    assert len(new) == 3
    for o in new:
        state["rabattknaller"]["gemeldet"][o.key] = o.compare_price
    again = rabattknaller.update(state, rabattknaller.find(RAW, CFG), NoHttp(), CFG, NOW, {})
    assert again == []                                                       # nicht doppelt
    # ausgeblendet + abgelaufen
    ninja = next(o for o in found if o.url.endswith("a-1"))
    state["ablauf"] = {"https://www.mydealz.de/deals/e-5": {"abgelaufen": True, "geprueft": NOW.isoformat()}}
    again = rabattknaller.find(RAW, CFG)
    rabattknaller.update(state, again, NoHttp(), CFG, NOW, {meldungen.offer_hash(ninja.key): {}})
    st = {o.url[-3:]: o.status for o in again}
    assert st["a-1"] == "ignoriert" and st["e-5"] == ABGELAUFEN and st["c-3"] == OK
    assert [d["url"][-3:] for d in rabattknaller.current(state)] == ["c-3"]
    html = page._knaller_html(state, CFG, page.ZoneInfo("Europe/Berlin"))
    assert "💥 Rabattknaller (1)" in html and "🔥 620°" in html and "t.me/Bot?start=x_" in html
    bot = botdata.build([], state, {}, CFG, NOW)["rabattknaller"]
    tefal = next(o for o in again if o.url.endswith("c-3"))
    assert bot[0]["hitze"] == 620 and bot[0]["h"] == meldungen.offer_hash(tefal.key)

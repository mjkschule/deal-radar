"""Tests für Phase 5: Zeitplan (gleiche Fälle wie worker/test/zeitplan.test.js), Enddatum/Wunschliste,
Quellen-Ausfall-Alarm, neue Startseite und PWA-Dateien."""

import datetime as dt
import json
import struct
import zlib

import pytest

from dealradar import meldungen, page, pwa, zeitplan
from dealradar.config import end_datetime, is_over, load_config, parse_products

CFG = load_config()
UTC = dt.timezone.utc


def utc(s):
    return dt.datetime.fromisoformat(s).replace(tzinfo=UTC)


@pytest.mark.parametrize("tick,mode,due", [
    ("2026-11-25T12:17", "normal", True),
    ("2026-11-25T12:47", "normal", False),
    ("2026-11-25T13:17", "normal", False),
    ("2026-11-26T23:47", "aktion", True),        # 00:47 Berlin am 27.11. = schon Aktionszeit
    ("2026-11-27T10:47", "aktion", True),
    ("2026-11-30T22:47", "aktion", True),        # 23:47 Berlin am Cyber Monday
    ("2026-11-30T23:17", "wunschliste", False),  # 00:17 Berlin am 1.12.
    ("2026-12-01T07:17", "wunschliste", True),   # 08:17 Berlin
    ("2026-12-01T07:47", "wunschliste", False),
])
def test_schedule_like_worker(tick, mode, due):
    assert zeitplan.mode(CFG, utc(tick)) == mode
    assert zeitplan.due(CFG, utc(tick)) is due


def test_next_run_and_gaps():
    assert zeitplan.next_run(CFG, utc("2026-11-30T23:05")).astimezone(UTC) == utc("2026-12-01T07:17")
    assert zeitplan.next_run(CFG, utc("2026-11-25T13:05")).astimezone(UTC) == utc("2026-11-25T14:17")
    assert zeitplan.min_gap(CFG, utc("2026-11-25T12:00")) == 60     # 2 Std.
    assert zeitplan.min_gap(CFG, utc("2026-11-28T12:00")) == 15     # 30 Min.
    assert zeitplan.min_gap(CFG, utc("2026-12-02T12:00")) == 720    # täglich
    # Lauf nach Bot-Befehl um 17:41 darf den planmäßigen Lauf um 19:17 nicht verhindern
    assert 96 >= zeitplan.min_gap(CFG, utc("2026-11-25T18:17"))
    assert zeitplan.describe(CFG, utc("2026-11-28T12:00")) == "Aktionszeit: alle 30 Minuten"


def test_end_never_and_off():
    never = {**CFG, "enddatum": "nie"}
    assert end_datetime(never) is None and zeitplan.mode(never, utc("2027-03-01T10:00")) == "normal"
    off = {**CFG, "nach_ende": "aus"}
    assert zeitplan.mode(off, utc("2026-12-02T10:00")) == "aus" and is_over(off, utc("2026-12-02T10:00"))
    assert zeitplan.next_run(off, utc("2026-12-02T10:00")) is None
    assert not is_over(CFG, utc("2026-12-02T10:00"))  # Standard: Wunschlisten-Modus, nicht aus
    assert CFG["enddatum"] == "2026-11-30T23:59"


def test_source_failure_alert_once_and_recovery():
    state = {}
    fail = {"mydealz": {"status": "fehler", "meldung": "HTTP 500"}, "ebay": {"status": "deaktiviert"}}
    assert meldungen.source_alerts(state, fail) == []
    assert meldungen.source_alerts(state, fail) == []
    third = meldungen.source_alerts(state, fail)
    assert len(third) == 1 and "„mydealz“ fällt aus" in third[0] and "HTTP 500" in third[0]
    assert meldungen.source_alerts(state, fail) == []           # nicht jedes Mal wiederholen
    ok = meldungen.source_alerts(state, {"mydealz": {"status": "ok"}})
    assert ok == ["✅ Quelle „mydealz“ funktioniert wieder."]
    assert state["quellen_fehler"] == {}
    # kurzer Aussetzer (1x) -> keine Entwarnung nötig
    meldungen.source_alerts(state, fail)
    assert meldungen.source_alerts(state, {"mydealz": {"status": "ok"}}) == []


# ---------- Startseite ----------

PRODUCTS = parse_products([
    {"id": "makita", "name": "Makita DHP490", "suchbegriffe": ["DHP490"], "zielpreis": 215, "kategorie": "werkzeug"},
    {"id": "epson", "name": "Epson ET-2922", "suchbegriffe": ["ET-2922"], "zielpreis": 155, "kategorie": "drucker"},
    {"id": "alt", "name": "Alter Drucker", "suchbegriffe": ["X"], "zielpreis": 10, "kategorie": "drucker",
     "aktiv": False},
])
NOW = dt.datetime(2026, 11, 25, 12, 0, tzinfo=dt.timezone(dt.timedelta(hours=1)))


def _offer(price, url):
    seen = NOW.isoformat(timespec="seconds")
    return {"price": price, "shipping": 0, "vergleichspreis": price, "shop": "BAUR", "url": url, "title": "T",
            "source": "mydealz", "status": "ok", "hints": [], "first_seen": seen, "last_seen": seen}


STATE = {
    "letzter_lauf": NOW.isoformat(),
    "angebote": {"makita": {"k1": _offer(184.0, "https://x/makita")}, "epson": {"k2": _offer(174.99, "https://x/epson")}},
    "quellen": {"mydealz": {"status": "ok", "anzahl": 3}, "leasingmarkt": {"status": "fehler", "meldung": "kaputt"}},
}


def test_page_has_reached_box_filters_status_and_pwa():
    html = page.render(PRODUCTS, STATE, {}, CFG, NOW)
    reached = html[html.index('class="box reached"'):html.index('<section class="top">')]
    assert "Ziel erreicht (1)" in reached and "Makita DHP490" in reached and "https://x/makita" in reached
    assert "Epson" not in reached
    assert '<button class="chip" data-cat="drucker">drucker <span class="muted">2</span>' in html
    assert '<option value="score">Sortieren: Deal-Score</option>' in html
    assert 'data-kategorie="werkzeug"' in html and 'data-score="-1"' in html
    assert "Nächster Lauf" in html and "25.11. 13:17 Uhr" in html  # 12:17 UTC = 13:17 Berlin
    assert "⚠️ 1 mit Fehler" in html and " open>" in html          # Fehler -> Quellenliste aufgeklappt
    assert '<link rel="manifest" href="manifest.webmanifest">' in html and 'register("sw.js")' in html
    assert "alle 2 Stunden" in html


def test_page_in_wishlist_mode():
    later = dt.datetime(2026, 12, 3, 9, 0, tzinfo=dt.timezone(dt.timedelta(hours=1)))
    html = page.render(PRODUCTS, STATE, {}, CFG, later)
    assert "Wunschlisten-Modus" in html and "seit 30.11.2026" in html
    assert "04.12. 08:17 Uhr" in html


def test_pwa_assets(tmp_path):
    pwa.write_assets(tmp_path)
    m = json.loads((tmp_path / "manifest.webmanifest").read_text())
    assert m["display"] == "standalone" and m["start_url"] == "./"
    assert {i["sizes"] for i in m["icons"]} == {"192x192", "512x512"}
    assert "maskable" in {i["purpose"] for i in m["icons"]}
    png = (tmp_path / "icon-192.png").read_bytes()
    assert png[:8] == b"\x89PNG\r\n\x1a\n" and struct.unpack(">II", png[16:24]) == (192, 192)
    # Pixel prüfen: Mitte weiß (Radar-Zentrum), Ecke transparent (abgerundet)
    idat = png[png.index(b"IDAT") + 4:png.index(b"IEND") - 8]
    raw = zlib.decompress(idat)
    row = 192 * 4 + 1
    px = lambda x, y: raw[y * row + 1 + x * 4: y * row + 1 + x * 4 + 4]
    assert px(96, 96) == b"\xff\xff\xff\xff" and px(0, 0)[3] == 0
    assert "deal-radar-v1" in (tmp_path / "sw.js").read_text()


def test_leasing_sources_keep_two_hour_pace(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from dealradar import main
    calls = []

    class Src:
        NAME = "leasingmarkt"

        def fetch(self, products, ctx):
            calls.append(1)
            return []

    data = tmp_path / "data"
    data.mkdir()
    now = main.now_local(load_config())
    recent = (now - dt.timedelta(minutes=40)).isoformat(timespec="seconds")
    (data / "state.json").write_text(json.dumps({"quellen": {"leasingmarkt": {"status": "ok", "zeit": recent,
                                                                              "anzahl": 7}}}))
    monkeypatch.setattr(main, "all_sources", lambda: [Src()])
    monkeypatch.setenv("RADAR_GRUND", "befehl")
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "o"))
    for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
        monkeypatch.delenv(k, raising=False)
    args = SimpleNamespace(dry_run=True, test_telegram=False, out=str(tmp_path), only=None, test_meldung=None)
    assert main.run(args) == 0
    st = json.loads((data / "state.json").read_text())["quellen"]["leasingmarkt"]
    assert calls == [] and st["zeit"] == recent and "nur alle 110 Min." in st["meldung"]

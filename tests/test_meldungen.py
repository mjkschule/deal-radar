"""Tests für Phase 2: Ruhezeiten, Sofort-/Übersichts-Regeln, Buttons unter Meldungen."""

import datetime as dt
import json
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from dealradar import main, meldungen, telegram
from dealradar.config import load_config
from dealradar.models import Offer

FIXTURE = Path(__file__).parent / "fixtures" / "products_test.yaml"

TZ = ZoneInfo("Europe/Berlin")
_REAL = load_config()
# Tests unabhängig von deiner echten Einstellung (/ruhe an|aus ändert config.yaml)
CFG = {**_REAL, "ruhezeiten": {**_REAL["ruhezeiten"], "aktiv": True}}


def at(day, hhmm):
    """day: 23 = Montag 23.11.2026 … 29 = Sonntag."""
    h, m = map(int, hhmm.split(":"))
    return dt.datetime(2026, 11, day, h, m, tzinfo=TZ)


@pytest.mark.parametrize("day,hhmm,quiet", [
    (23, "07:29", False),   # Mo kurz vor der Vormittags-Ruhe
    (23, "07:30", True),
    (23, "13:59", True),
    (23, "14:00", False),
    (23, "21:59", False),
    (23, "22:00", True),
    (24, "03:00", True),    # Nacht Mo -> Di
    (24, "06:59", True),
    (24, "07:00", False),   # Lücke 7:00–7:30 an Werktagen
    (28, "10:00", False),   # Samstag vormittags keine Ruhe
    (28, "23:30", True),
    (30, "02:00", True),    # So -> Mo über Mitternacht
])
def test_quiet_hours(day, hhmm, quiet):
    assert meldungen.quiet_now(CFG, at(day, hhmm)) is quiet


def test_quiet_hours_switch_off_and_utc_input():
    off = {**CFG, "ruhezeiten": {**CFG["ruhezeiten"], "aktiv": False}}
    assert not meldungen.quiet_now(off, at(23, "23:00"))
    # 22:30 UTC = 23:30 Berlin (Winterzeit) -> Ruhe
    assert meldungen.quiet_now(CFG, dt.datetime(2026, 11, 24, 22, 30, tzinfo=dt.timezone.utc))


def test_day_specs():
    assert meldungen._days("Mo-Fr") == {0, 1, 2, 3, 4}
    assert meldungen._days("Sa,So") == {5, 6}
    assert meldungen._days("Fr-Mo") == {4, 5, 6, 0}
    assert meldungen._days("täglich") == set(range(7))


@pytest.mark.parametrize("reached,score,value,when,expected", [
    (True, None, 200, (23, "16:00"), "sofort"),       # Ziel erreicht, keine Ruhe
    (False, 85, 300, (23, "16:00"), "sofort"),        # sehr hoher Score
    (False, 84, 300, (23, "16:00"), "uebersicht"),    # guter Deal, aber nur Übersicht
    (False, None, 300, (23, "16:00"), "uebersicht"),
    (True, 60, 200, (23, "10:00"), "ruhe"),           # Ruhezeit -> zurückhalten
    (True, 90, 200, (23, "10:00"), "sofort"),         # Ausnahme Score >= 90
    (True, None, 180, (23, "10:00"), "sofort"),       # Ausnahme: > 15 % unter Ziel (215 * 0.85 = 182,75)
    (True, None, 183, (23, "10:00"), "ruhe"),
    (False, 70, 300, (23, "23:00"), "uebersicht"),    # Übersicht bleibt Übersicht
])
def test_route(reached, score, value, when, expected):
    assert meldungen.route(reached, score, value, 215, CFG, at(*when)) == expected


def test_buttons_fit_telegram_limit():
    pid = "a" * 40
    rows = meldungen.buttons(pid, "shop|https://example.org/x", 1234567.89, "https://example.org/x")
    datas = [b["callback_data"] for r in rows for b in r if "callback_data" in b]
    assert {d.split(":")[0] for d in datas} == {"k", "i", "m", "q"}
    assert all(len(d.encode()) <= 64 for d in datas)
    assert rows[-1][0]["url"] == "https://example.org/x"
    assert "k:" + pid + ":123456789" in datas


def test_queue_prunes_old_items():
    state = {}
    now = at(25, "12:00")
    meldungen.queue_add(state, {"id": "a", "zeit": (now - dt.timedelta(hours=40)).isoformat()}, now - dt.timedelta(hours=40))
    meldungen.queue_add(state, {"id": "b", "zeit": now.isoformat()}, now)
    meldungen.queue_add(state, {"id": "b", "zeit": now.isoformat()}, now)
    assert [x["id"] for x in state["warteschlange"]] == ["b"]


# ---------- ganzer Lauf: Meldung geht sofort raus oder in die Warteschlange ----------

class FakeSource:
    NAME = "mydealz"

    def __init__(self, price):
        self.price = price

    def fetch(self, products, ctx):
        return [Offer(product_id="makita-dhp490rfx3", source="mydealz", shop="TestShop",
                      title="Makita DHP490RFX3 Akku-Schlagbohrschrauber", url="https://example.org/deal",
                      price=self.price, shipping=0)]


def _run(tmp_path, monkeypatch, now, price, ignored=None):
    sent = []

    def fake_call(self, method, params):
        if method == "getMe":  # Bot-Name für den Link „🚫 Abgelaufen?“
            return {"username": "TestBot"}
        sent.append((method, params))
        return {}

    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    # eingefrorene Produktliste statt der echten products.yaml (Makita: Ziel 215 €)
    (tmp_path / "products.yaml").write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(main, "ROOT", tmp_path)
    monkeypatch.setattr(main, "load_config", lambda: CFG)
    monkeypatch.setattr(main, "all_sources", lambda: [FakeSource(price)])
    if ignored:
        (data / "ignoriert.json").write_text(json.dumps(ignored))
    monkeypatch.setattr(telegram.Telegram, "_call", fake_call)
    monkeypatch.setattr(main, "now_local", lambda cfg: now)
    monkeypatch.setattr(main, "all_sources", lambda: [FakeSource(price)])
    monkeypatch.setattr(main, "handle_telegram_commands", lambda *a, **k: [])
    for k, v in {"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "1", "RADAR_GRUND": "befehl"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "out.txt"))
    args = SimpleNamespace(dry_run=False, test_telegram=False, out=str(tmp_path), only="makita-dhp490rfx3")
    assert main.run(args) == 0
    bot = json.loads((tmp_path / "docs" / "bot.json").read_text())
    return sent, bot


def test_run_sends_target_deal_with_buttons(tmp_path, monkeypatch):
    sent, bot = _run(tmp_path, monkeypatch, at(25, "16:00"), 200)
    assert len(sent) == 1
    method, params = sent[0]
    assert method == "sendMessage" and "Makita" in params["text"]
    kb = json.loads(params["reply_markup"])["inline_keyboard"]
    assert kb[0][0]["callback_data"] == "k:makita-dhp490rfx3:20000"
    assert bot["warteschlange"] == []


def test_run_holds_deal_during_quiet_hours(tmp_path, monkeypatch):
    sent, bot = _run(tmp_path, monkeypatch, at(25, "10:00"), 200)
    assert sent == []
    q = bot["warteschlange"]
    assert len(q) == 1 and q[0]["art"] == "ruhe" and q[0]["produkt"] == "makita-dhp490rfx3"
    assert q[0]["buttons"][0][0]["callback_data"].startswith("k:")
    assert bot["ruhezeit_beim_lauf"] is True


def test_run_exception_beats_quiet_hours(tmp_path, monkeypatch):
    sent, bot = _run(tmp_path, monkeypatch, at(25, "10:00"), 150)  # > 15 % unter Ziel 215
    assert len(sent) == 1 and bot["warteschlange"] == []


def test_run_skips_ignored_offer(tmp_path, monkeypatch):
    h = meldungen.offer_hash("testshop|https://example.org/deal")
    sent, bot = _run(tmp_path, monkeypatch, at(25, "16:00"), 200, ignored={h: {"produkt": "makita-dhp490rfx3"}})
    assert sent == [] and bot["warteschlange"] == []


def test_test_alert_has_buttons_for_real_product(tmp_path, monkeypatch):
    sent = []
    monkeypatch.setattr(telegram.Telegram, "_call", lambda self, m, p: sent.append((m, p)) or {})
    (tmp_path / "products.yaml").write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    tg = telegram.Telegram(None, "t", "1")
    assert main.send_test_alert(tg, "1", tmp_path / "products.yaml") == 0
    text, kb = sent[0][1]["text"], json.loads(sent[0][1]["reply_markup"])["inline_keyboard"]
    assert "TESTMELDUNG" in text and "Makita" in text
    assert kb[0][0]["callback_data"] == "k:makita-dhp490rfx3:21500"
    assert main.send_test_alert(tg, "99", tmp_path / "products.yaml") == 1

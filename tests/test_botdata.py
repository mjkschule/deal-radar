"""Tests für den vorläufigen Deal-Score, docs/bot.json und das Überspringen doppelter Zeitplan-Läufe."""

import datetime as dt
import json
import shutil
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from dealradar import botdata, main
from dealradar.config import load_config, parse_products
from dealradar.score import deal_score, history_median

TZ = ZoneInfo("Europe/Berlin")
NOW = dt.datetime(2026, 11, 25, 12, 0, tzinfo=TZ)


def pts(*prices, days_ago=1):
    return [{"t": (NOW - dt.timedelta(days=days_ago, hours=i)).isoformat(), "bester": p} for i, p in enumerate(prices)]


def test_score_needs_enough_history():
    assert deal_score(100, pts(100, 100, 100, 100), None, NOW) is None
    assert deal_score(None, pts(*[100] * 10), None, NOW) is None


def test_score_scale():
    h = pts(*[100] * 9)
    assert deal_score(100, h, 90, NOW) == 50           # üblicher Preis
    assert deal_score(90, h, 80, NOW) == 75            # 10 % unter Median
    assert deal_score(80, h, 85, NOW) == 100           # 20 % unter Median + Tiefstpreis (gedeckelt)
    assert deal_score(110, h, 90, NOW) == 25           # 10 % über Median
    assert deal_score(200, h, 90, NOW) == 0
    assert deal_score(100, h, 100, NOW) == 60          # = Allzeit-Tiefstpreis: +10


def test_median_ignores_old_and_empty_points():
    h = pts(100, 100, 100, 100, 100) + pts(10, 10, 10, 10, 10, 10, days_ago=120) + [{"t": NOW.isoformat(), "bester": None}]
    assert history_median(h, NOW) == (100, 5)


def test_bot_json_content():
    products = parse_products([
        {"id": "a", "name": "A", "suchbegriffe": ["a"], "zielpreis": 50},
        {"id": "b", "name": "B", "suchbegriffe": ["b"], "zielpreis": 50, "aktiv": False},
    ])
    seen = NOW.isoformat()
    state = {"letzter_lauf": seen, "quellen": {"mydealz": {"status": "ok"}},
             "angebote": {"a": {"x": {"status": "ok", "vergleichspreis": 45.0, "price": 40.0, "shipping": 5.0,
                                      "shop": "S", "url": "https://s", "title": "A", "last_seen": seen, "source": "mydealz"}},
                          "b": {"y": {"status": "ok", "vergleichspreis": 10.0, "price": 10.0, "shop": "T", "url": "u",
                                      "title": "B", "last_seen": seen}}},
             "tiefstpreis": {"a": {"vergleichspreis": 45.0, "shop": "S"}}}
    data = botdata.build(products, state, {"a": pts(*[60] * 6)}, load_config(), NOW)
    a, b = data["produkte"]["a"], data["produkte"]["b"]
    assert a["bester"]["effektivpreis"] == 45.0 and a["bester"]["versand"] == 5.0 and a["ziel_erreicht"]
    assert a["score"] == 100 and a["tiefstpreis"] == 45.0
    assert b["aktiv"] is False and b["bester"] is None and b["score"] is None
    assert data["letzter_lauf"] == seen and data["quellen"]["mydealz"]["status"] == "ok"
    text = json.dumps(data)
    assert "TOKEN" not in text and "chat" not in text.lower()


def _run_in_copy(tmp_path, monkeypatch, env, last_run_minutes_ago):
    data = tmp_path / "data"
    data.mkdir()
    last = (dt.datetime.now(TZ) - dt.timedelta(minutes=last_run_minutes_ago)).isoformat(timespec="seconds")
    (data / "state.json").write_text(json.dumps({"letzter_lauf": last}))
    out = tmp_path / "out.txt"
    out.write_text("")
    for k in ("GITHUB_EVENT_NAME", "RADAR_GRUND", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.setattr(main, "all_sources", lambda: [])
    args = SimpleNamespace(dry_run=True, test_telegram=False, out=str(tmp_path), only=None)
    assert main.run(args) == 0
    return out.read_text(), json.loads((data / "state.json").read_text())["letzter_lauf"] != last


def test_schedule_run_skipped_when_last_run_recent(tmp_path, monkeypatch):
    output, ran = _run_in_copy(tmp_path, monkeypatch, {"RADAR_GRUND": "zeitplan"}, 5)
    assert "lauf=uebersprungen" in output and not ran


def test_schedule_run_happens_when_last_run_old(tmp_path, monkeypatch):
    output, ran = _run_in_copy(tmp_path, monkeypatch, {"GITHUB_EVENT_NAME": "schedule"}, 150)
    assert "uebersprungen" not in output and ran
    assert (tmp_path / "docs" / "bot.json").exists()


def test_command_run_never_skipped(tmp_path, monkeypatch):
    output, ran = _run_in_copy(tmp_path, monkeypatch, {"RADAR_GRUND": "befehl"}, 1)
    assert ran


class ConflictHttp:
    def request(self, url, data=None, headers=None, method=None):
        return 409, json.dumps({"ok": False, "description": "Conflict: can't use getUpdates method while webhook is active; use deleteWebhook to delete the webhook first"})


def test_webhook_conflict_is_reported_calmly(tmp_path):
    from dealradar.telegram import Telegram
    tg = Telegram(ConflictHttp(), "t", "1")
    log = main.handle_telegram_commands(tg, ConflictHttp(), {}, load_config(), NOW, tmp_path / "p.yaml", tmp_path, {})
    assert log == ["Telegram-Webhook aktiv – Befehle beantwortet der Cloudflare Worker."]

"""Tests für die Telegram-Befehle /liste, /loeschen, /pause, /fortsetzen und die YAML-Bearbeitung."""

import base64
import datetime as dt
import json
import shutil
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import yaml

from dealradar import github, page
from dealradar.commands import CommandProcessor, split_message
from dealradar.config import ROOT, ConfigError, load_config, load_products
from dealradar.products_edit import remove_product, set_active
from dealradar.telegram import Telegram

TZ = ZoneInfo("Europe/Berlin")
NOW = dt.datetime(2026, 11, 25, 12, 0, tzinfo=TZ)


@pytest.fixture
def ppath(tmp_path) -> Path:
    """Kopie der echten products.yaml (8 Produkte, mit Kommentaren)."""
    p = tmp_path / "products.yaml"
    shutil.copy(ROOT / "products.yaml", p)
    return p


def make(ppath, state=None):
    return CommandProcessor(ppath, state or {}, load_config(), NOW)


def ids(ppath):
    return [p.id for p in load_products(ppath)]


# ---------- YAML-Bearbeitung ----------

def test_remove_keeps_other_entries_and_comments(ppath):
    before = ppath.read_text()
    old = remove_product(ppath, "hp-deskjet-2922")
    after = ppath.read_text()
    assert old["name"].startswith("HP DeskJet")
    assert "hp-deskjet-2922" not in ids(ppath) and len(ids(ppath)) == 7
    assert "Deal-Radar – deine Produkte" in after and "BEISPIEL für ein neues Produkt" in after
    assert "\n\n\n" not in after
    assert len(after) < len(before)


def test_remove_first_and_last_entry(ppath):
    remove_product(ppath, "makita-dhp490rfx3")
    remove_product(ppath, "opel-frontera-electric-leasing")
    text = ppath.read_text()
    assert ids(ppath)[0] == "hp-deskjet-2922" and ids(ppath)[-1] == "wandhalterung-c27f396"
    assert "# ====" in text and "# BEISPIEL" in text


def test_remove_also_drops_attached_telegram_comment(ppath):
    p = make(ppath)
    p.handle("/neu Testprodukt Airfryer; 50; Testprodukt Airfryer")
    assert "# per Telegram hinzugefügt" in ppath.read_text()
    remove_product(ppath, "testprodukt-airfryer")
    assert "per Telegram hinzugefügt" not in ppath.read_text()
    assert ppath.read_text() == (ROOT / "products.yaml").read_text()  # exakt wie vorher


def test_remove_unknown_raises(ppath):
    with pytest.raises(ConfigError):
        remove_product(ppath, "gibt-es-nicht")


def test_set_active_pause_and_resume(ppath):
    set_active(ppath, "lenovo-l24-4e", False)
    assert next(p for p in load_products(ppath) if p.id == "lenovo-l24-4e").aktiv is False
    assert ppath.read_text().count("aktiv: false") == 1
    set_active(ppath, "lenovo-l24-4e", True)
    assert next(p for p in load_products(ppath) if p.id == "lenovo-l24-4e").aktiv is True
    assert "aktiv: false" not in ppath.read_text() and ppath.read_text().count("  aktiv: true") == 1


def test_aktiv_must_be_bool(ppath):
    ppath.write_text(ppath.read_text().replace("- id: lenovo-l24-4e\n", "- id: lenovo-l24-4e\n  aktiv: vielleicht\n"))
    with pytest.raises(ConfigError):
        load_products(ppath)


# ---------- Befehle ----------

def test_ambiguous_name_asks_back(ppath):
    p = make(ppath)
    p.handle("/neu Testprodukt Airfryer Philips; 50; Testprodukt Airfryer Philips")
    p.handle("/neu Testprodukt Airfryer Ninja; 60; Testprodukt Airfryer Ninja")
    reply = p.handle("/loeschen airfryer")
    assert "passt auf 2 Produkte" in reply and "9. Testprodukt Airfryer Philips" in reply
    assert "10. Testprodukt Airfryer Ninja" in reply and "/loeschen 9" in reply
    assert len(ids(ppath)) == 10  # nichts gelöscht
    reply = p.handle("/loeschen Airfryer Ninja")  # eindeutig
    assert "Gelöscht" in reply and "Ninja" in reply and len(ids(ppath)) == 9


def test_delete_by_number_and_numbers_stay_stable_within_run(ppath):
    p = make(ppath)
    r1 = p.handle("/loeschen 2")   # HP
    r2 = p.handle("/loeschen 3")   # Epson (war Nr. 3 in der Liste), nicht der allgemeine Drucker
    assert "HP DeskJet" in r1 and "Epson" in r2
    assert "hp-deskjet-2922" not in ids(ppath) and "epson-et-2922" not in ids(ppath)
    assert "drucker-allgemein" in ids(ppath)
    assert "schon gelöscht" in p.handle("/loeschen 2")
    assert "gibt es nicht" in p.handle("/loeschen 99")
    assert p.batch.changes == ["Produkt hp-deskjet-2922 gelöscht", "Produkt epson-et-2922 gelöscht"]
    assert [a["id"] for a in p.batch.archived] == ["hp-deskjet-2922", "epson-et-2922"]
    assert p.batch.archived[0]["eintrag"]["zielpreis"] == 45


def test_pause_resume_and_list(ppath):
    state = {"letzter_lauf": "2026-11-25T10:17:00+01:00", "angebote": {"makita-dhp490rfx3": {"x": {
        "status": "ok", "vergleichspreis": 184.0, "shop": "BAUR", "last_seen": "2026-11-25T10:17:00+01:00",
        "url": "https://example.org", "title": "Makita"}}}}
    p = make(ppath, state)
    assert "pausiert" in p.handle("/pause 5")
    assert "bereits pausiert" in p.handle("/pause Lenovo")
    lst = p.handle("/liste")
    assert "1. ✅ <b>Makita" in lst and "184 € (BAUR)" in lst and "25.11. 10:17" in lst
    assert "5. ⏸ <b>Lenovo L24-4e" in lst and "(pausiert)" in lst
    assert "8. ⚪ <b>Opel Frontera" in lst and "€/Monat" in lst
    assert "wieder überwacht" in p.handle("/fortsetzen 5")
    assert all(x.aktiv for x in load_products(ppath))


def test_other_messages_and_bot_suffix(ppath):
    p = make(ppath)
    assert p.handle("hallo") is None
    assert "Deine Produkte" in p.handle("/liste@MeinDealBot")
    assert "Unbekannter Befehl" in p.handle("/quatsch")
    assert "Nummer oder Name" in p.handle("/loeschen")
    assert "Kein Produkt passt" in p.handle("/pause Kaffeemaschine")
    assert "/liste" in p.handle("/hilfe")


def test_split_message():
    text = "\n".join(f"Zeile {i} " + "x" * 50 for i in range(200))
    parts = split_message(text, limit=1000)
    assert all(len(x) <= 1000 for x in parts) and "\n".join(parts) == text


# ---------- Nur deine Chat-ID ----------

class FakeHttp:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, url, data=None, headers=None, method=None):
        self.calls.append((method or "GET", url, data))
        return self.responses.pop(0)


def test_only_own_chat_id_is_accepted():
    updates = {"ok": True, "result": [
        {"update_id": 10, "message": {"chat": {"id": 111}, "text": "/loeschen 1"}},
        {"update_id": 11, "message": {"chat": {"id": 999}, "text": "/loeschen 2"}},   # fremder Chat
        {"update_id": 12, "message": {"chat": {"id": -111}, "text": "/pause 3"}},     # Gruppe
        {"update_id": 13, "edited_message": {"chat": {"id": 111}, "text": "/pause 4"}},
    ]}
    tg = Telegram(FakeHttp([(200, json.dumps(updates))]), "token", "111")
    texts, offset = tg.commands(None)
    assert texts == ["/loeschen 1"] and offset == 14


# ---------- GitHub-API-Commit ----------

def test_github_commit_file():
    old = base64.b64encode(b"alt\n").decode()
    http = FakeHttp([(200, json.dumps({"sha": "abc", "content": old})),
                     (200, json.dumps({"commit": {"sha": "def123"}}))])
    sha = github.commit_file(http, "t", "me/repo", "main", "products.yaml", "neu\n", "Telegram: x")
    assert sha == "def123"
    method, url, body = http.calls[1]
    sent = json.loads(body)
    assert method == "PUT" and url.endswith("/repos/me/repo/contents/products.yaml")
    assert sent["sha"] == "abc" and base64.b64decode(sent["content"]) == b"neu\n" and sent["branch"] == "main"


def test_github_commit_unchanged_and_error():
    same = base64.b64encode(b"gleich\n").decode()
    assert github.commit_file(FakeHttp([(200, json.dumps({"sha": "a", "content": same}))]),
                              "t", "me/repo", "main", "products.yaml", "gleich\n", "m") is None
    http = FakeHttp([(200, json.dumps({"sha": "a", "content": same})), (409, json.dumps({"message": "conflict"}))])
    with pytest.raises(github.GitHubError, match="409"):
        github.commit_file(http, "t", "me/repo", "main", "products.yaml", "anders\n", "m")


# ---------- Startseite ----------

def test_page_hides_deleted_and_greys_paused(ppath):
    history = {"hp-deskjet-2922": [{"zeit": "2026-11-24T10:00:00+01:00", "bester": 50, "tiefst": 50}]}
    remove_product(ppath, "hp-deskjet-2922")
    set_active(ppath, "lenovo-l24-4e", False)
    html = page.render(load_products(ppath), {}, history, load_config(), NOW)
    assert "HP DeskJet" not in html and 'id="hp-deskjet-2922"' not in html
    assert 'class="card paused" id="lenovo-l24-4e"' in html and "⏸ Pausiert" in html
    assert ">0 / 6<" in html  # pausierte zählen nicht mit
    assert html.index('id="lenovo-l24-4e"') > html.index('id="opel-frontera-electric-leasing"')
    assert "hp-deskjet-2922" in history  # Verlauf bleibt erhalten

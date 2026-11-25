"""Abgelaufene und ausgeblendete Angebote.

1. Automatisch: mydealz lässt abgelaufene Deals noch tagelang in den Gruppen-Feeds stehen. Der Feed
   selbst sagt nicht, ob ein Deal abgelaufen ist – die Deal-Seite schon ("isExpired":true bzw.
   „Leider ist dieser Deal mittlerweile abgelaufen“). Deal-Seiten sind laut robots.txt erlaubt.
   Geprüft wird sparsam: nur Angebote, die sonst angezeigt oder gemeldet würden, jedes höchstens
   alle `ablauf.pruefen_stunden` Stunden und höchstens `ablauf.max_abrufe` Seiten pro Lauf.
   Ein abgelaufener Deal bleibt abgelaufen (wird nicht erneut geprüft).

2. Von Hand: data/ignoriert.json (Button „🙈 Ignorieren“, Link „🚫 Abgelaufen?“ auf der Startseite,
   Befehl /weg). Solche Angebote werden weder gemeldet noch auf der Startseite als Preis gezeigt.
"""

from __future__ import annotations

import datetime as dt
import re
from urllib.parse import urlparse

from .http import FetchError, Http
from .meldungen import offer_hash
from .models import ABGELAUFEN, IGNORIERT, OK, Offer

DEFAULTS = {"aktiv": True, "pruefen_stunden": 3, "max_abrufe": 25, "merken_tage": 14}

# mydealz liefert zwei Seiten-Fassungen: mit JSON-Daten ("isExpired") oder als reines HTML
_FLAG = re.compile(r'"isExpired"\s*:\s*(true|false)')
_DETAILS = re.compile(r'id="thread_details_\d+"[^>]*\bclass="([^"]*)"|class="([^"]*)"[^>]*id="thread_details_\d+"')
_TEXT = re.compile(r"dieser deal (?:ist )?(?:mittlerweile|vor [^<]{1,30}|seit [^<]{1,30})?\s*abgelaufen", re.I)


def settings(cfg: dict) -> dict:
    return {**DEFAULTS, **(cfg.get("ablauf") or {})}


def checkable(url: str) -> bool:
    """Nur mydealz-Deal-Seiten (dort steht verlässlich, ob der Deal abgelaufen ist)."""
    p = urlparse(url or "")
    return p.netloc.endswith("mydealz.de") and p.path.startswith("/deals/")


def expired_from_html(html: str) -> bool | None:
    """True = abgelaufen, False = läuft noch, None = nicht erkennbar."""
    m = _FLAG.search(html)
    if m:
        return m.group(1) == "true"
    if _TEXT.search(html):
        return True
    d = _DETAILS.search(html)
    if d:
        return "thread--expired" in (d.group(1) or d.group(2) or "")
    return None


def check(offers: list[Offer], state: dict, http: Http, cfg: dict, now: dt.datetime,
          budget: dict | None = None) -> list[str]:
    """Prüft die übergebenen Angebote (schon nach Status 'ok' gefiltert, wichtigste zuerst) und
    setzt bei abgelaufenen den Status. budget = {"rest": n} gilt über alle Produkte eines Laufs.
    Gibt Hinweise für das Lauf-Protokoll zurück."""
    s = settings(cfg)
    budget = budget if budget is not None else {"rest": int(s["max_abrufe"])}
    cache = state.setdefault("ablauf", {})
    notes: list[str] = []
    if not s["aktiv"]:
        return notes
    fetched = 0
    for o in offers:
        if not checkable(o.url):
            continue
        url = o.url.split("#")[0]
        entry = cache.get(url)
        fresh = entry and (entry.get("abgelaufen") or
                           now - dt.datetime.fromisoformat(entry["geprueft"]) < dt.timedelta(hours=s["pruefen_stunden"]))
        if not fresh:
            if budget["rest"] <= 0:
                continue  # Rest beim nächsten Lauf
            budget["rest"] -= 1
            fetched += 1
            try:
                flag = expired_from_html(http.get(url))
            except FetchError as ex:
                notes.append(f"Ablauf-Prüfung: {ex}"[:120])
                continue
            if flag is None:
                continue
            entry = cache[url] = {"abgelaufen": flag, "geprueft": now.isoformat(timespec="seconds")}
        if entry and entry.get("abgelaufen"):
            o.status, o.status_reason = ABGELAUFEN, "Deal bei mydealz als abgelaufen markiert"
    # Alte Prüfungen vergessen
    cutoff = now - dt.timedelta(days=s["merken_tage"])
    for url in [u for u, e in cache.items() if dt.datetime.fromisoformat(e["geprueft"]) < cutoff]:
        cache.pop(url)
    if fetched:
        notes.append(f"{fetched} Deal-Seiten auf Ablauf geprüft")
    return notes


def apply_ignored(offers: list[Offer], ignored: dict) -> None:
    """Von dir ausgeblendete Angebote (data/ignoriert.json, Schlüssel = offer_hash)."""
    for o in offers:
        if offer_hash(o.key) in ignored:
            o.status, o.status_reason = IGNORIERT, "von dir ausgeblendet"


def candidates(offers: list[Offer]) -> list[Offer]:
    """Angebote, die sonst gezeigt/gemeldet würden – günstigste zuerst."""
    return sorted((o for o in offers if o.status == OK and o.compare_price is not None),
                  key=lambda o: o.compare_price)

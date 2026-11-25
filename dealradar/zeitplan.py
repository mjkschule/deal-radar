"""Zeitplan und Laufzeit (config.yaml -> enddatum, nach_ende, zeitplan).

Modus (gleiche Regeln im Worker: worker/src/zeitplan.js):
  "aktion"      zwischen zeitplan.aktion_von und aktion_bis (Black Friday bis Cyber Monday):
                alle aktion_minuten (Standard 30)
  "normal"      sonst alle normal_minuten (Standard 120)
  "wunschliste" nach dem Enddatum (nach_ende: wunschliste): 1 Lauf täglich um wunschliste_uhrzeit
  "aus"         nach dem Enddatum mit nach_ende: aus -> der Workflow schaltet sich ab

enddatum: "JJJJ-MM-TTTHH:MM" oder "nie". Per Telegram: /ende 24.12.2026  bzw.  /ende nie

Der Worker tickt alle 30 Minuten (Minute 17 und 47, UTC) und startet einen Lauf, wenn er "dran" ist.
Läufe vom Zeitplan werden übersprungen, wenn der letzte Lauf weniger als min_gap() Minuten her ist
(GitHub-Reserve-Zeitplan und Worker sollen nicht doppelt laufen). Läufe nach Bot-Befehlen laufen immer.
"""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from .config import end_datetime

DEFAULTS = {"normal_minuten": 120, "aktion_minuten": 30, "aktion_von": "2026-11-27T00:00",
            "aktion_bis": "2026-11-30T23:59", "wunschliste_uhrzeit": "08:00"}


def settings(cfg: dict) -> dict:
    return {**DEFAULTS, **(cfg.get("zeitplan") or {})}


def _local(cfg: dict, raw: str) -> dt.datetime:
    d = dt.datetime.fromisoformat(str(raw))
    return d if d.tzinfo else d.replace(tzinfo=ZoneInfo(cfg.get("zeitzone", "Europe/Berlin")))


def mode(cfg: dict, now: dt.datetime) -> str:
    end = end_datetime(cfg)
    if end is not None and now > end:
        return "aus" if str(cfg.get("nach_ende", "wunschliste")).lower() == "aus" else "wunschliste"
    z = settings(cfg)
    if _local(cfg, z["aktion_von"]) <= now <= _local(cfg, z["aktion_bis"]) + dt.timedelta(seconds=59):
        return "aktion"
    return "normal"


def interval_minutes(cfg: dict, now: dt.datetime) -> int | None:
    z = settings(cfg)
    return {"aktion": int(z["aktion_minuten"]), "normal": int(z["normal_minuten"]),
            "wunschliste": 24 * 60, "aus": None}[mode(cfg, now)]


def min_gap(cfg: dict, now: dt.datetime) -> int:
    """So viele Minuten muss der letzte Lauf her sein, damit ein Zeitplan-Lauf nicht übersprungen wird."""
    iv = interval_minutes(cfg, now) or 24 * 60
    return iv - max(10, iv // 10)


MODE_TEXT = {"aktion": "Aktionszeit: alle {n} Minuten", "normal": "alle {h} Stunden",
             "wunschliste": "Wunschlisten-Modus: 1× täglich um {t} Uhr", "aus": "beendet"}


def describe(cfg: dict, now: dt.datetime) -> str:
    m = mode(cfg, now)
    iv = interval_minutes(cfg, now) or 0
    h = iv / 60
    return MODE_TEXT[m].format(n=iv, h=f"{h:g}", t=settings(cfg)["wunschliste_uhrzeit"])


def next_run(cfg: dict, now: dt.datetime) -> dt.datetime | None:
    """Nächster planmäßiger Lauf (Worker-Takt: Minute 17/47 UTC)."""
    utc = now.astimezone(dt.timezone.utc)
    t = utc.replace(second=0, microsecond=0)
    t += dt.timedelta(minutes=(17 - t.minute) % 30 or 30)  # nächster :17 / :47
    for _ in range(24 * 2 * 3):
        if due(cfg, t):
            return t.astimezone(ZoneInfo(cfg.get("zeitzone", "Europe/Berlin")))
        t += dt.timedelta(minutes=30)
    return None


def due(cfg: dict, tick: dt.datetime) -> bool:
    """Ist zu diesem Worker-Takt (Minute 17 oder 47 UTC) ein Lauf fällig?"""
    m = mode(cfg, tick)
    utc = tick.astimezone(dt.timezone.utc)
    if m == "aus":
        return False
    if m == "wunschliste":
        local = tick.astimezone(ZoneInfo(cfg.get("zeitzone", "Europe/Berlin")))
        hh = int(str(settings(cfg)["wunschliste_uhrzeit"]).split(":")[0])
        return local.hour == hh and utc.minute == 17
    iv = interval_minutes(cfg, tick)
    minute_of_day = utc.hour * 60 + utc.minute - 17
    return minute_of_day % iv == 0

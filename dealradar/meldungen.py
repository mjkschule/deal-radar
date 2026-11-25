"""Wann wird ein Deal wie gemeldet? (Sofort, nach der Ruhezeit oder in der Tagesübersicht)

Regeln (config.yaml -> meldungen, ruhezeiten):
  * Sofort nur, wenn der Zielpreis erreicht ist ODER der Deal-Score >= sofort_ab_score (85).
    Alles andere landet in der täglichen Übersicht (19:00 Uhr, verschickt der Cloudflare Worker).
  * In einer Ruhezeit werden Sofort-Meldungen zurückgehalten und vom Worker gesendet,
    sobald die Ruhezeit endet – außer bei Score >= ausnahme_ab_score (90) oder wenn der
    Zielpreis um mehr als ausnahme_unter_ziel (15 %) unterboten wird.
  * Ruhezeiten: "tage" (Mo-Fr, Mo-So, Sa, ...) bezieht sich auf den START der Zeitspanne;
    "22:00–07:00" läuft also über Mitternacht in den nächsten Tag.

Der Worker (worker/src/ruhe.js) rechnet die Ruhezeiten genauso – Tests prüfen beide.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import html
from zoneinfo import ZoneInfo

SOFORT = "sofort"
RUHE = "ruhe"
UEBERSICHT = "uebersicht"

TAGE = ["mo", "di", "mi", "do", "fr", "sa", "so"]
WARTESCHLANGE_STUNDEN = 36


def _days(spec: str) -> set[int]:
    """'Mo-Fr' -> {0..4}, 'Sa,So' -> {5, 6}, 'täglich'/'Mo-So' -> alle."""
    spec = str(spec or "").strip().lower()
    if not spec or spec in ("taeglich", "täglich", "alle"):
        return set(range(7))
    out: set[int] = set()
    for part in spec.replace(" ", "").split(","):
        if "-" in part:
            a, b = part.split("-", 1)
            i, j = TAGE.index(a[:2]), TAGE.index(b[:2])
            k = i
            while True:
                out.add(k)
                if k == j:
                    break
                k = (k + 1) % 7
        elif part:
            out.add(TAGE.index(part[:2]))
    return out


def _minutes(hhmm: str) -> int:
    h, m = str(hhmm).split(":")
    return int(h) * 60 + int(m)


def quiet_now(cfg: dict, now: dt.datetime) -> bool:
    """Ist gerade Ruhezeit? (now wird in die Zeitzone aus config.yaml umgerechnet)"""
    rz = cfg.get("ruhezeiten") or {}
    if not rz.get("aktiv", True):
        return False
    local = now.astimezone(ZoneInfo(cfg.get("zeitzone", "Europe/Berlin")))
    minute = local.hour * 60 + local.minute
    today = local.weekday()
    for z in rz.get("zeiten") or []:
        start, end = _minutes(z["von"]), _minutes(z["bis"])
        days = _days(z.get("tage", "Mo-So"))
        if start < end:
            if today in days and start <= minute < end:
                return True
        else:  # über Mitternacht: Start-Tag zählt
            if today in days and minute >= start:
                return True
            if (today - 1) % 7 in days and minute < end:
                return True
    return False


def route(target_reached: bool, score: int | None, target_value: float | None, target: float,
          cfg: dict, now: dt.datetime) -> str:
    """sofort / ruhe (nach der Ruhezeit senden) / uebersicht (nur Tagesübersicht)."""
    m = cfg.get("meldungen") or {}
    rz = cfg.get("ruhezeiten") or {}
    instant = target_reached or (score is not None and score >= m.get("sofort_ab_score", 85))
    if not instant:
        return UEBERSICHT
    if not quiet_now(cfg, now):
        return SOFORT
    big_score = score is not None and score >= rz.get("ausnahme_ab_score", 90)
    far_below = (target_value is not None and target > 0
                 and target_value < target * (1 - rz.get("ausnahme_unter_ziel", 0.15)))
    return SOFORT if (big_score or far_below) else RUHE


def offer_hash(key: str) -> str:
    """Kurzer, stabiler Schlüssel eines Angebots (für den Button „Ignorieren“)."""
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]


def buttons(product_id: str, offer_key: str, price: float | None, url: str) -> list[list[dict]]:
    """Buttons unter einer Deal-Meldung. callback_data max. 64 Byte (id max. 40 Zeichen)."""
    cents = int(round((price or 0) * 100))
    rows = [
        [{"text": "✅ Gekauft", "callback_data": f"k:{product_id}:{cents}"},
         {"text": "🙈 Ignorieren", "callback_data": f"i:{product_id}:{offer_hash(offer_key)}"}],
        [{"text": "🎯 Ziel −10 €", "callback_data": f"m:{product_id}"},
         {"text": "⏸ Pausieren", "callback_data": f"q:{product_id}"}],
    ]
    if url.startswith("http"):
        rows.append([{"text": "🔗 Zum Angebot", "url": url}])
    return rows


def queue_add(state: dict, item: dict, now: dt.datetime) -> None:
    """Merkt eine Meldung für den Worker vor (Ruhezeit-Nachlieferung bzw. Tagesübersicht)."""
    q = state.setdefault("warteschlange", [])
    if not any(x.get("id") == item["id"] for x in q):
        q.append(item)
    prune_queue(state, now)


def prune_queue(state: dict, now: dt.datetime) -> None:
    cutoff = now - dt.timedelta(hours=WARTESCHLANGE_STUNDEN)
    state["warteschlange"] = [x for x in state.get("warteschlange") or []
                              if dt.datetime.fromisoformat(x["zeit"]) >= cutoff]


def source_alerts(state: dict, status: dict, after: int = 3) -> list[str]:
    """Zählt Fehler je Quelle über die Läufe. Meldet einmal, wenn eine Quelle `after`-mal in Folge
    ausfällt, und einmal, wenn sie danach wieder funktioniert. (Abgeschaltete Quellen zählen nicht.)"""
    counts = state.setdefault("quellen_fehler", {})
    out = []
    for name, s in status.items():
        st = s.get("status")
        if st == "fehler":
            counts[name] = counts.get(name, 0) + 1
            if counts[name] == after:
                out.append(f"⚠️ <b>Quelle „{name}“ fällt aus</b> – {after} Läufe in Folge.\n"
                           f"Letzte Meldung: {html.escape(str(s.get('meldung', ''))[:200])}\n"
                           "Die anderen Quellen laufen weiter. Ich melde mich, sobald sie wieder geht.")
        elif st == "ok":
            if counts.get(name, 0) >= after:
                out.append(f"✅ Quelle „{name}“ funktioniert wieder.")
            counts.pop(name, None)
        else:  # abgeschaltet / nicht eingerichtet
            counts.pop(name, None)
    return out

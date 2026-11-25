"""docs/bot.json: die aktuellen Preise für den Telegram-Bot (Cloudflare Worker).

Der Worker beantwortet /liste, /top und /status sofort aus dieser Datei, ohne auf
einen Suchlauf zu warten. Sie enthält nur, was ohnehin auf der Startseite steht –
keine Tokens, keine Chat-ID.
"""

from __future__ import annotations

import datetime as dt

from .config import Product, end_datetime
from .bewertung import buy_or_wait, rechenweg
from .config import expand_alternatives
from .logic import current_best, offers_by_status
from .meldungen import offer_hash, quiet_now
from .models import OK
from .score import deal_score


def _best_info(best: dict | None) -> dict | None:
    if not best:
        return None
    lease = best.get("leasing") or {}
    return {
        "preis": best.get("price"),
        "effektivpreis": best.get("vergleichspreis"),  # inkl. Versand bzw. effektive Leasingrate
        "versand": best.get("shipping"),
        "rate": lease.get("rate"),
        "shop": best.get("shop"),
        "url": best.get("url"),
        "titel": (best.get("title") or "")[:160],
        "quelle": best.get("source"),
        "hinweise": best.get("hints") or [],
        "vertrauen": best.get("vertrauen") or [],
        "rechenweg": rechenweg(best),
        "gesehen": best.get("last_seen"),
    }


def build(products: list[Product], state: dict, history: dict, cfg: dict, now: dt.datetime) -> dict:
    rules = cfg["regeln"]
    out = {}
    for p in products:
        best = current_best(p, state, now, rules) if p.aktiv else None
        low = (state.get("tiefstpreis") or {}).get(p.id)
        info = _best_info(best)
        target_value = None
        if info:
            target_value = info["rate"] if p.is_leasing and info["rate"] is not None else info["effektivpreis"]
        out[p.id] = {
            "name": p.name,
            "kategorie": p.kategorie,
            "typ": p.typ,
            "aktiv": p.aktiv,
            "zielpreis": p.zielpreis,
            "bester": info,
            "tiefstpreis": low.get("vergleichspreis") if low else None,
            "tiefstpreis_shop": low.get("shop") if low else None,
            "score": deal_score(info["effektivpreis"], history.get(p.id, []),
                                low.get("vergleichspreis") if low else None, now) if info else None,
            "ziel_erreicht": bool(target_value is not None and target_value <= p.zielpreis),
        }
        e = out[p.id]
        e["kaufen_oder_warten"] = buy_or_wait(cfg, now, e["score"], e["ziel_erreicht"]) if p.aktiv and info else ""
        alts = []
        for alt in expand_alternatives([p])[1:] if p.aktiv else []:
            ab = _best_info(current_best(alt, state, now, rules))
            alts.append({"name": alt.name, "zielpreis": alt.zielpreis, "bester": ab,
                         "ziel_erreicht": bool(ab and ab["effektivpreis"] is not None
                                               and ab["effektivpreis"] <= alt.zielpreis)})
        e["alternativen"] = alts
        # Aktuelle Angebote mit Kurzschlüssel – für /weg und den Link „🚫 Abgelaufen?“ der Startseite
        e["angebote"] = [
            {"h": offer_hash(f"{(d.get('shop') or '').lower()}|{(d.get('url') or '').split('#')[0]}"),
             "shop": d.get("shop"), "preis": d.get("vergleichspreis"), "url": d.get("url"),
             "titel": (d.get("title") or "")[:100]}
            for d in (offers_by_status(p, state, now, rules, (OK,)) if p.aktiv else [])[:8]]
    return {
        "version": 1,
        "stand": now.isoformat(timespec="seconds"),
        "letzter_lauf": state.get("letzter_lauf"),
        "enddatum": end_datetime(cfg).isoformat(timespec="minutes"),
        "quellen": state.get("quellen") or {},
        "ruhezeit_beim_lauf": quiet_now(cfg, now),
        # Meldungen, die der Worker nach der Ruhezeit bzw. in der Tagesübersicht verschickt
        "warteschlange": state.get("warteschlange") or [],
        # Gutscheine aus dem Deal-Postfach (ohne Codes)
        "gutscheine": (state.get("cache") or {}).get("gutscheine") or [],
        "produkte": out,
    }

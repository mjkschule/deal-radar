"""Ein Lauf des Deal-Radars.

Aufruf:
    python -m dealradar.main                 # normaler Lauf (wie in GitHub Actions)
    python -m dealradar.main --dry-run       # nichts an Telegram senden, Daten in --out schreiben
    python -m dealradar.main --test-telegram # nur eine Testnachricht schicken
"""

from __future__ import annotations

import argparse
import html
import os
import sys
import time
from pathlib import Path

from . import logic, page, storage
from .config import ROOT, ConfigError, end_datetime, is_over, load_config, load_products, now_local
from .http import Http
from .products_edit import append_product, parse_telegram_command
from .sources import Context, Skipped, all_sources
from .telegram import Telegram, TelegramError, format_alert


def handle_telegram_commands(tg: Telegram, state: dict, products_path: Path) -> list[str]:
    """Verarbeitet /neu-Befehle. Gibt Statusmeldungen zurück."""
    log = []
    try:
        texts, offset = tg.commands(state.get("telegram_offset"))
    except TelegramError as e:
        return [f"Telegram-Befehle nicht lesbar: {e}"]
    state["telegram_offset"] = offset
    for text in texts:
        cmd = text.strip().split()[0].lower() if text.strip() else ""
        if cmd.startswith("/neu"):
            try:
                entry = append_product(products_path, parse_telegram_command(text), comment="per Telegram hinzugefügt")
                tg.send(f"✅ Neues Produkt <b>{html.escape(entry['name'])}</b> (Ziel {entry['zielpreis']:g} €) "
                        f"wird ab jetzt beobachtet.\nSuchbegriffe: {html.escape(', '.join(entry['suchbegriffe']))}")
                log.append(f"Produkt {entry['id']} per Telegram hinzugefügt")
            except ConfigError as e:
                tg.send(f"❌ Konnte das Produkt nicht anlegen: {html.escape(str(e))}\nBeispiel: /neu Bosch PSR 18; 89; PSR 18 LI-2, PSR18")
        elif cmd in ("/start", "/hilfe", "/help"):
            tg.send("📡 Deal-Radar\nNeues Produkt: <code>/neu Name; Zielpreis; Suchbegriff1, Suchbegriff2</code>\n"
                    "Befehle werden beim nächsten Lauf (alle 2 Std.) verarbeitet.")
    return log


def run(args) -> int:
    cfg = load_config()
    now = now_local(cfg)
    if is_over(cfg, now):
        print(f"Enddatum {end_datetime(cfg):%d.%m.%Y %H:%M} erreicht – Deal-Radar ist beendet.")
        return 0

    env = dict(os.environ)
    http = Http(cfg["user_agent"], pause=float(cfg["pause_sekunden"]), timeout=float(cfg["timeout_sekunden"]))
    tg = Telegram(http, env.get("TELEGRAM_BOT_TOKEN"), env.get("TELEGRAM_CHAT_ID"), dry_run=args.dry_run)

    if args.test_telegram:
        if not tg.configured:
            print("TELEGRAM_BOT_TOKEN oder TELEGRAM_CHAT_ID fehlt.")
            return 1
        tg.dry_run = False
        tg.send(f"✅ <b>Deal-Radar ist eingerichtet!</b>\nTestnachricht vom {now:%d.%m.%Y, %H:%M} Uhr.\n"
                "Ab jetzt melde ich mich, sobald ein guter Deal auftaucht.")
        print("Testnachricht gesendet.")
        return 0

    out = Path(args.out) if args.out else ROOT
    data_dir, docs_dir = out / "data", out / "docs"
    products_path = ROOT / "products.yaml"
    state = storage.load_json(data_dir / "state.json", {})
    history = storage.load_json(data_dir / "verlauf.json", {})

    for line in handle_telegram_commands(tg, state, products_path):
        print(line)
    products = load_products(products_path)
    if args.only:
        products = [p for p in products if p.id in args.only.split(",")]

    # --- Datenquellen abfragen (jede einzeln abgesichert) ---
    all_offers = []
    status = {}
    cache = state.setdefault("cache", {})
    for mod in all_sources():
        name = mod.NAME
        if not cfg["quellen"].get(name, True):
            status[name] = {"status": "deaktiviert", "meldung": "in config.yaml ausgeschaltet"}
            continue
        ctx = Context(http=http, config=cfg, env=env, now=now, cache=cache)
        t0 = time.monotonic()
        try:
            found = mod.fetch(products, ctx)
            all_offers.extend(found)
            status[name] = {"status": "ok", "anzahl": len(found), "meldung": "; ".join(ctx.notes)[:300]}
        except Skipped as s:
            status[name] = {"status": "deaktiviert", "meldung": str(s)}
        except Exception as ex:  # Quelle kaputt -> andere laufen weiter
            status[name] = {"status": "fehler", "meldung": f"{type(ex).__name__}: {ex}"[:300]}
        status[name]["zeit"] = now.isoformat(timespec="seconds")
        status[name]["dauer_s"] = round(time.monotonic() - t0, 1)
        print(f"[{name}] {status[name]['status']}: {status[name].get('meldung', '')}")
    state["quellen"] = status

    # --- Bewerten, melden, speichern ---
    rules = cfg["regeln"]
    now_iso = now.isoformat(timespec="seconds")
    sent = 0
    for p in products:
        offers = [o for o in all_offers if o.product_id == p.id]
        alerts = logic.evaluate(p, offers, state, rules)
        for a in alerts:
            try:
                tg.send(format_alert(a))
                if not args.dry_run:
                    logic.mark_reported(state, a)
                sent += 1
            except TelegramError as ex:
                print(f"Telegram-Fehler: {ex}", file=sys.stderr)
        logic.remember(p, offers, state, now, rules)
        best = logic.current_best(p, state, now, rules)
        low = (state.get("tiefstpreis") or {}).get(p.id)
        storage.append_history(history, p.id, now_iso, best["vergleichspreis"] if best else None,
                               low["vergleichspreis"] if low else None)
        counts = {}
        for o in offers:
            counts[o.status] = counts.get(o.status, 0) + 1
        print(f"  {p.id}: {len(offers)} Angebote {counts} · bester: {best['vergleichspreis'] if best else '–'} "
              f"· gemeldet: {len(alerts)}")
    state["letzter_lauf"] = now_iso
    state["version"] = 1

    storage.append_csv(data_dir / "verlauf.csv", now_iso, all_offers)
    storage.save_json(data_dir / "state.json", state)
    storage.save_json(data_dir / "verlauf.json", history)
    docs_dir.mkdir(parents=True, exist_ok=True)
    (docs_dir / "index.html").write_text(page.render(load_products(products_path), state, history, cfg, now),
                                         encoding="utf-8")
    (docs_dir / ".nojekyll").write_text("", encoding="utf-8")
    print(f"Fertig: {len(all_offers)} Angebote, {sent} Meldungen, {http.request_count} Abrufe.")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Deal-Radar")
    ap.add_argument("--dry-run", action="store_true", help="nichts an Telegram senden")
    ap.add_argument("--test-telegram", action="store_true", help="nur eine Telegram-Testnachricht senden")
    ap.add_argument("--out", help="anderer Ausgabeordner für data/ und docs/ (zum Testen)")
    ap.add_argument("--only", help="nur diese Produkt-IDs (kommagetrennt)")
    args = ap.parse_args(argv)
    try:
        return run(args)
    except ConfigError as e:
        print(f"Konfigurationsfehler: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

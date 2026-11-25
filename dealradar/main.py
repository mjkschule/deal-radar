"""Ein Lauf des Deal-Radars.

Aufruf:
    python -m dealradar.main                 # normaler Lauf (wie in GitHub Actions)
    python -m dealradar.main --dry-run       # nichts an Telegram senden, Daten in --out schreiben
    python -m dealradar.main --test-telegram # nur eine Testnachricht schicken
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
import time
from pathlib import Path

from . import bewertung, botdata, github, logic, meldungen, page, storage
from .config import (ROOT, ConfigError, end_datetime, expand_alternatives, is_over, load_config, load_products,
                     now_local)
from .commands import CommandProcessor, split_message
from .http import FetchError, Http
from .models import Offer
from .score import deal_score
from .score import explain as score_explain
from .sources import Context, Skipped, all_sources
from .telegram import Telegram, TelegramError, format_alert


def handle_telegram_commands(tg: Telegram, http: Http, state: dict, cfg: dict, now, products_path: Path,
                             data_dir: Path, env: dict) -> list[str]:
    """Holt Befehle aus deinem Telegram-Chat, führt sie aus, committet products.yaml
    per GitHub-API und schickt die Antworten. Gibt Log-Zeilen zurück."""
    log = []
    try:
        texts, offset = tg.commands(state.get("telegram_offset"))
    except TelegramError as e:
        if "webhook" in str(e).lower():
            # Normalfall mit Cloudflare Worker: der beantwortet die Befehle sofort.
            return ["Telegram-Webhook aktiv – Befehle beantwortet der Cloudflare Worker."]
        return [f"Telegram-Befehle nicht lesbar: {e}"]
    state["telegram_offset"] = offset
    if not texts:
        return log
    batch = CommandProcessor(products_path, state, cfg, now).run(texts)
    log.append(f"{len(texts)} Telegram-Nachricht(en) verarbeitet: {'; '.join(batch.changes) or 'keine Änderung'}")

    if batch.archived:  # gelöschte Produkte aufheben (Preisverlauf bleibt in verlauf.json)
        archive = storage.load_json(data_dir / "geloescht.json", [])
        archive.extend(batch.archived)
        storage.save_json(data_dir / "geloescht.json", archive)

    if batch.changes:
        token, repo = env.get("GITHUB_TOKEN"), env.get("GITHUB_REPOSITORY")
        if token and repo:
            try:
                sha = github.commit_file(http, token, repo, env.get("GITHUB_REF_NAME") or "main", "products.yaml",
                                         products_path.read_text(encoding="utf-8"),
                                         "Telegram: " + "; ".join(batch.changes))
                log.append(f"products.yaml per GitHub-API committet ({(sha or 'unverändert')[:7]})")
            except (github.GitHubError, FetchError) as e:
                # Kein Drama: Der Commit-Schritt im Workflow nimmt products.yaml ebenfalls mit.
                log.append(f"GitHub-API-Commit fehlgeschlagen, Workflow committet später: {e}")
        else:
            log.append("Kein GITHUB_TOKEN (lokal) – products.yaml nur lokal geändert")

    for reply in batch.replies:
        for part in split_message(reply):
            try:
                tg.send(part)
            except TelegramError as e:
                log.append(f"Antwort nicht gesendet: {e}")
    return log


def _output(key: str, value: str) -> None:
    """Wert an GitHub Actions weitergeben (steps.<id>.outputs.<key>)."""
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{key}={value}\n")


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

    if getattr(args, "test_meldung", None):
        return send_test_alert(tg, args.test_meldung, ROOT / "products.yaml")

    out = Path(args.out) if args.out else ROOT
    data_dir, docs_dir = out / "data", out / "docs"
    products_path = ROOT / "products.yaml"
    state = storage.load_json(data_dir / "state.json", {})
    history = storage.load_json(data_dir / "verlauf.json", {})

    # Zeitplan-Läufe kommen vom Worker UND (als Reserve) von GitHub. Liegt der letzte
    # Lauf weniger als X Minuten zurück, wird dieser Lauf übersprungen.
    if env.get("GITHUB_EVENT_NAME") == "schedule" or env.get("RADAR_GRUND") == "zeitplan":
        last = state.get("letzter_lauf")
        gap = int(cfg.get("mindestabstand_minuten", 60))
        if last and (now - dt.datetime.fromisoformat(last)).total_seconds() < gap * 60:
            print(f"Letzter Lauf {last} ist weniger als {gap} Minuten her – Zeitplan-Lauf übersprungen.")
            _output("lauf", "uebersprungen")
            return 0

    for line in handle_telegram_commands(tg, http, state, cfg, now, products_path, data_dir, env):
        print(line)
    all_products = load_products(products_path)
    paused = [p.id for p in all_products if not p.aktiv]
    if paused:
        print(f"Pausiert (nicht überwacht): {', '.join(paused)}")
    products = [p for p in all_products if p.aktiv]
    if args.only:
        products = [p for p in products if p.id in args.only.split(",")]
    # Alternativen ("<id>~alt1") werden wie eigene Produkte gesucht, aber beim Hauptprodukt gemeldet
    products = expand_alternatives(products)
    names = {p.id: p.name for p in products}

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
    sent = queued = 0
    ignored = storage.load_json(data_dir / "ignoriert.json", {})
    quiet = meldungen.quiet_now(cfg, now)
    if quiet:
        print("Ruhezeit: normale Meldungen werden danach vom Worker nachgeliefert.")
    coupons = (state.get("cache") or {}).get("gutscheine") or []
    for p in products:
        offers = logic.merge_duplicates([o for o in all_offers if o.product_id == p.id])
        bewertung.apply_effective(offers, cfg, coupons, now)
        alerts = [a for a in logic.evaluate(p, offers, state, rules)
                  if meldungen.offer_hash(a.offer.key) not in ignored]
        for a in alerts:
            o = a.offer
            low = (state.get("tiefstpreis") or {}).get(p.id)
            score = deal_score(o.compare_price, history.get(p.id, []),
                               low.get("vergleichspreis") if low else None, now)
            reached = "Zielpreis erreicht" in a.reasons
            how = meldungen.route(reached, score, o.target_value, p.zielpreis, cfg, now)
            text = format_alert(a, score, hint=bewertung.buy_or_wait(cfg, now, score, reached),
                                main_name=names.get(p.alternative_zu),
                                score_why=score_explain(o.compare_price, history.get(p.id, []),
                                                        low.get("vergleichspreis") if low else None, now))
            # Buttons wirken immer auf das echte Produkt (bei Alternativen: das Hauptprodukt)
            keyboard = meldungen.buttons(p.main_id, o.key, o.target_value, o.url)
            try:
                if how == meldungen.SOFORT:
                    # Nur als "gemeldet" merken, wenn die Nachricht wirklich angekommen ist
                    # (sonst würden Deals vor dem Eintragen der Secrets verloren gehen).
                    if tg.send(text, keyboard):
                        logic.mark_reported(state, a)
                        sent += 1
                elif tg.live:
                    # Der Worker liefert nach der Ruhezeit bzw. in der 19-Uhr-Übersicht.
                    meldungen.queue_add(state, {
                        "id": meldungen.offer_hash(f"{o.key}|{o.compare_price}"), "art": how,
                        "produkt": p.main_id, "name": p.name, "preis": o.compare_price, "shop": o.shop,
                        "url": o.url, "score": score, "ziel_erreicht": "Zielpreis erreicht" in a.reasons,
                        "text": text, "buttons": keyboard, "zeit": now.isoformat(timespec="seconds"),
                    }, now)
                    logic.mark_reported(state, a)
                    queued += 1
                else:
                    print(f"---- ({how}, nicht gespeichert) ----\n{text}\n----")
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
    meldungen.prune_queue(state, now)
    state["letzter_lauf"] = now_iso
    state["version"] = 1

    storage.append_csv(data_dir / "verlauf.csv", now_iso, all_offers)
    storage.save_json(data_dir / "state.json", state)
    storage.save_json(data_dir / "verlauf.json", history)
    docs_dir.mkdir(parents=True, exist_ok=True)
    storage.save_json(docs_dir / "bot.json", botdata.build(load_products(products_path), state, history, cfg, now))
    docs_dir.mkdir(parents=True, exist_ok=True)
    (docs_dir / "index.html").write_text(page.render(load_products(products_path), state, history, cfg, now),
                                         encoding="utf-8")
    (docs_dir / ".nojekyll").write_text("", encoding="utf-8")
    print(f"Fertig: {len(all_offers)} Angebote, {sent} Meldungen, {queued} vorgemerkt, {http.request_count} Abrufe.")
    return 0


def send_test_alert(tg: Telegram, which: str, products_path: Path) -> int:
    """Schickt eine Beispiel-Meldung (mit allen Buttons) für ein Produkt – zum Ausprobieren.
    which: Nummer aus /liste oder die id. Die Buttons wirken auf das ECHTE Produkt."""
    products = load_products(products_path)
    which = str(which).strip()
    p = (products[int(which) - 1] if which.isdigit() and 0 < int(which) <= len(products)
         else next((x for x in products if x.id == which), None))
    if not p:
        print(f"Produkt '{which}' nicht gefunden (Nummer aus /liste oder id angeben).")
        return 1
    if not tg.configured:
        print("TELEGRAM_BOT_TOKEN oder TELEGRAM_CHAT_ID fehlt.")
        return 1
    tg.dry_run = False
    url = p.shop_urls[0] if p.shop_urls else "https://mjkschule.github.io/deal-radar/"
    offer = Offer(product_id=p.id, source="test", shop="Testmeldung", title=f"{p.name} (Beispiel)",
                  url=url, price=p.zielpreis, shipping=0)
    alert = logic.Alert(p, offer, None, ["Zielpreis erreicht"])
    text = ("🧪 <b>TESTMELDUNG</b> – kein echtes Angebot. Die Buttons wirken aber auf das echte Produkt!\n\n"
            + format_alert(alert, None))
    tg.send(text, meldungen.buttons(p.id, offer.key, offer.target_value, url))
    print(f"Testmeldung für {p.id} gesendet.")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Deal-Radar")
    ap.add_argument("--dry-run", action="store_true", help="nichts an Telegram senden")
    ap.add_argument("--test-telegram", action="store_true", help="nur eine Telegram-Testnachricht senden")
    ap.add_argument("--test-meldung", metavar="NR_ODER_ID",
                    help="nur eine Beispiel-Meldung mit Buttons für dieses Produkt senden")
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

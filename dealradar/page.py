"""Erzeugt die Startseite docs/index.html (statisch, mobil lesbar, Deutsch)."""

from __future__ import annotations

import datetime as dt
import html
from zoneinfo import ZoneInfo

from . import bewertung
from .bewertung import BEDINGUNGEN, rechenweg
from .config import Product, end_datetime, expand_alternatives
from .logic import _fmt, current_best, offers_by_status
from .models import AUSGESCHLOSSEN, NICHT_PASSEND, VERDAECHTIG
from .score import deal_score


def e(s) -> str:
    return html.escape(str(s if s is not None else ""))


def euro(v) -> str:
    return "–" if v is None else f"{_fmt(v)} €"


def when(iso: str | None, tz: ZoneInfo) -> str:
    if not iso:
        return "–"
    t = dt.datetime.fromisoformat(iso).astimezone(tz)
    return t.strftime("%d.%m. %H:%M Uhr")


def sparkline(points: list[dict], target: float, width: int = 260, height: int = 48) -> str:
    """Kleiner Preisverlauf als SVG (bester Preis je Lauf + gestrichelter Zielpreis)."""
    vals = [p.get("bester") for p in points]
    nums = [v for v in vals if v is not None]
    if len(nums) < 2:
        return '<div class="spark-empty">Noch zu wenig Daten für einen Verlauf</div>'
    lo, hi = min(nums + [target]), max(nums + [target])
    span = (hi - lo) or 1
    pad = 4

    def y(v):
        return round(pad + (hi - v) / span * (height - 2 * pad), 1)

    step = (width - 2 * pad) / max(1, len(vals) - 1)
    segs, cur = [], []
    for i, v in enumerate(vals):
        if v is None:
            if cur:
                segs.append(cur)
            cur = []
        else:
            cur.append(f"{round(pad + i * step, 1)},{y(v)}")
    if cur:
        segs.append(cur)
    lines = "".join(f'<polyline points="{" ".join(s)}" class="spark-line"/>' for s in segs if len(s) > 1)
    dots = "".join(f'<circle cx="{s[-1].split(",")[0]}" cy="{s[-1].split(",")[1]}" r="2.5" class="spark-dot"/>'
                   for s in segs[-1:])
    ty = y(target)
    return (f'<svg class="spark" viewBox="0 0 {width} {height}" preserveAspectRatio="none" role="img" '
            f'aria-label="Preisverlauf, Minimum {euro(min(nums))}, Maximum {euro(max(nums))}">'
            f'<line x1="0" x2="{width}" y1="{ty}" y2="{ty}" class="spark-target"/>{lines}{dots}</svg>'
            f'<div class="spark-legend"><span>min {euro(min(nums))}</span><span>– – Ziel {euro(target)}</span>'
            f'<span>max {euro(max(nums))}</span></div>')


def ampel(best: dict | None, product: Product) -> tuple[str, str]:
    if not best:
        return "grey", "kein aktuelles Angebot"
    value = best["leasing"]["rate"] if best.get("leasing") else best["vergleichspreis"]
    if value <= product.zielpreis:
        return "green", "Ziel erreicht"
    if value <= product.zielpreis * 1.10:
        return "yellow", "knapp darüber"
    return "red", "über Zielpreis"


def _leasing_details(d: dict) -> str:
    l = d.get("leasing") or {}
    km = f"{l['km']:,}".replace(",", ".") if l.get("km") else "?"
    rows = [
        ("Rate", euro(l.get("rate"))),
        ("Sonderzahlung", euro(l.get("sonderzahlung")) if l.get("sonderzahlung") is not None else "unbekannt"),
        ("Bereitstellung", euro(l.get("bereitstellung")) if l.get("bereitstellung") is not None else "unbekannt"),
        ("Laufzeit / km", f"{l.get('monate') or '?'} Mon. · {km} km/Jahr"),
        ("Effektive Rate", euro(l.get("effektiv"))),
    ]
    return '<dl class="lease">' + "".join(f"<dt>{a}</dt><dd>{b}</dd>" for a, b in rows) + "</dl>"


def _offer_row(d: dict, tz) -> str:
    price = euro(d.get("vergleichspreis"))
    reason = f' – {e(d.get("status_reason"))}' if d.get("status_reason") else ""
    return (f'<li><a href="{e(d["url"])}" rel="noopener" target="_blank">{e(d["title"][:90])}</a>'
            f'<span class="muted"> · {e(d["shop"])} · {price}{reason}</span></li>')


def _alternatives_html(p: Product, state: dict, now: dt.datetime, rules: dict) -> str:
    rows = []
    for alt in expand_alternatives([p])[1:]:
        b = current_best(alt, state, now, rules)
        price = (f'{euro(b["vergleichspreis"])} bei <a href="{e(b["url"])}" rel="noopener" target="_blank">'
                 f'{e(b["shop"])}</a>' if b else "kein aktuelles Angebot")
        rows.append(f"<li>{e(alt.name)}: {price} <span class=\"muted\">(Ziel {euro(alt.zielpreis)})</span></li>")
    return f'<details open><summary>🔁 Alternativen ({len(rows)})</summary><ul>{"".join(rows)}</ul></details>' if rows else ""


def product_card(p: Product, state: dict, history: dict, now: dt.datetime, rules: dict, tz,
                 cfg: dict | None = None) -> str:
    best = current_best(p, state, now, rules)
    low = (state.get("tiefstpreis") or {}).get(p.id)
    color, label = ampel(best, p)
    if not p.aktiv:
        color, label = "grey", "pausiert"
    unit = " €/Monat" if p.is_leasing else " €"
    target = f"{_fmt(p.zielpreis)}{unit}" + (" (Rate)" if p.is_leasing else "")
    score = None
    gap = 9.99  # Abstand zum Ziel (für die Sortierung); ohne Angebot ganz hinten
    if best:
        big = euro(best["vergleichspreis"]) + (" eff./Monat" if p.is_leasing else "")
        ship = ""
        if not p.is_leasing:
            if best.get("shipping") == 0:
                ship = "inkl. Versand"
            elif best.get("shipping") is not None:
                ship = f"inkl. {euro(best['shipping'])} Versand"
            else:
                ship = "Versand unbekannt"
        conds = [h for h in best.get("hints") or [] if h in BEDINGUNGEN]
        hints = " · ".join(h for h in best.get("hints") or [] if h not in BEDINGUNGEN)
        calc = rechenweg(best)
        low_v = low["vergleichspreis"] if low else None
        score = deal_score(best["vergleichspreis"], history.get(p.id, []), low_v, now)
        value = best["leasing"]["rate"] if best.get("leasing") else best["vergleichspreis"]
        gap = round((value - p.zielpreis) / p.zielpreis, 4) if p.zielpreis else 0
        reached = color == "green"
        advice = bewertung.buy_or_wait(cfg, now, score, reached) if cfg and p.aktiv else ""
        main = (f'<div class="price">{big}</div>'
                f'<div class="muted">{e(ship)}{" · Score " + str(score) if score is not None else ""}</div>'
                + (f'<div class="muted">🧮 {e(calc)}</div>' if calc else "")
                + ('<div class="hints">♻️ <b>B-Ware / gebraucht</b></div>' if "gebraucht/B-Ware" in (best.get("hints") or []) else "")
                + (f'<div class="hints">📋 Bedingungen: {e(" · ".join(conds))}</div>' if conds else "")
                + (f'<div class="hints trust">🟡 Bitte prüfen: {e(" · ".join(best.get("vertrauen") or []))}</div>'
                   if best.get("vertrauen") else "")
                + (f'<div class="advice">{e(advice)}</div>' if advice else "") +
                f'<div class="shop"><a href="{e(best["url"])}" rel="noopener" target="_blank">Zum Angebot ↗</a>'
                f' <b>{e(best["shop"])}</b>'
                f' <span class="muted">· gesehen {when(best.get("first_seen"), tz)} · {e(best["source"])}</span></div>'
                f'<div class="offer-title">{e(best["title"][:140])}</div>'
                + (f'<div class="hints">⚠️ {e(hints)}</div>' if hints else "")
                + (_leasing_details(best) if p.is_leasing else ""))
    else:
        main = '<div class="price none">Kein aktuelles Angebot</div><div class="muted">Das Radar sucht weiter …</div>'
    if not p.aktiv:
        main = ('<div class="price none">⏸ Pausiert</div><div class="muted">Wird gerade nicht überwacht. '
                'Wieder einschalten: <code>/fortsetzen</code> in Telegram oder <code>aktiv: true</code> '
                'in products.yaml.</div>')

    extra = ""
    bad = offers_by_status(p, state, now, rules, (VERDAECHTIG, AUSGESCHLOSSEN))
    unfit = offers_by_status(p, state, now, rules, (NICHT_PASSEND,))
    if unfit:
        extra += (f'<details><summary>Nicht passend ({len(unfit)})</summary><ul>'
                  + "".join(_offer_row(d, tz) for d in unfit[:15]) + "</ul></details>")
    if bad:
        extra += (f'<details><summary>Verdächtig / ausgeschlossen ({len(bad)})</summary><ul>'
                  + "".join(_offer_row(d, tz) for d in bad[:15]) + "</ul></details>")
    extra += _alternatives_html(p, state, now, rules)
    notes = f'<div class="notes">{e(p.notizen)}</div>' if p.notizen else ""
    return f"""
<article class="card{"" if p.aktiv else " paused"}" id="{e(p.id)}" data-kategorie="{e(p.kategorie)}"
 data-score="{score if score is not None and p.aktiv else -1}" data-gap="{gap if p.aktiv else 99}"
 data-name="{e(p.name.lower())}">
  <header><span class="dot {color}" title="{label}"></span><div><h2>{e(p.name)}</h2>
  <div class="muted">{e(p.kategorie)} · <span class="tag {color}">{label}</span></div></div></header>
  {main}
  <div class="facts"><div><span>Zielpreis</span><b>{target}</b></div>
  <div><span>Tiefstpreis seit Start</span><b>{euro(low["vergleichspreis"]) if low else "–"}</b>
  {f'<small>{e(low["shop"])}, {when(low.get("last_seen"), tz)}</small>' if low else ""}</div></div>
  {sparkline(history.get(p.id, [])[-80:], p.zielpreis)}
  {notes}{extra}
</article>"""


STATUS_LABEL = {"ok": ("green", "OK"), "fehler": ("red", "Fehler"), "deaktiviert": ("grey", "aus"),
                "uebersprungen": ("grey", "übersprungen")}


def gutscheine_html(state: dict, now: dt.datetime) -> str:
    """Gutscheine aus dem Deal-Postfach – ohne Code (der steht nur in deiner Mail)."""
    today = now.date().isoformat()
    items = [g for g in (state.get("cache") or {}).get("gutscheine") or []
             if not g.get("gueltig_bis") or g["gueltig_bis"] >= today]
    if not items:
        return ""
    rows = []
    for g in sorted(items, key=lambda g: g["shop"].lower()):
        value = f'{g["rabatt_prozent"]} %' if g.get("rabatt_prozent") else euro(g.get("rabatt_euro"))
        extra = []
        if g.get("mindestbestellwert"):
            extra.append(f'ab {euro(g["mindestbestellwert"])}')
        if g.get("gueltig_bis"):
            extra.append("bis " + dt.date.fromisoformat(g["gueltig_bis"]).strftime("%d.%m."))
        rows.append(f'<li><b>{e(g["shop"])}</b>: {value} Rabatt'
                    f'{" · " + " · ".join(extra) if extra else ""}'
                    f'<span class="muted"> (Mail vom {dt.date.fromisoformat(g["mail_vom"]).strftime("%d.%m.")})</span></li>')
    return ('<section class="box" style="margin-top:16px"><div class="muted">🎟️ Gutscheine aus deinem Deal-Postfach '
            '(Code steht in der Mail)</div><ul class="sources">' + "".join(rows) + "</ul></section>")


def _reached_html(products: list[Product], state: dict, now: dt.datetime, rules: dict) -> str:
    """Oben: alle aktiven Produkte mit erreichtem Zielpreis – mit Kauf-Button."""
    rows = []
    for p in products:
        if not p.aktiv:
            continue
        best = current_best(p, state, now, rules)
        if ampel(best, p)[0] != "green":
            continue
        unit = " €/Monat" if p.is_leasing else ""
        value = best["leasing"]["rate"] if best.get("leasing") else best["vergleichspreis"]
        rows.append(
            f'<li><div><a href="#{e(p.id)}"><b>{e(p.name)}</b></a>'
            f'<div class="muted">{euro(value)}{unit} bei {e(best["shop"])} · Ziel {euro(p.zielpreis)}{unit}</div></div>'
            f'<a class="buy" href="{e(best["url"])}" rel="noopener" target="_blank">Zum Angebot ↗</a></li>')
    if not rows:
        return ('<section class="box reached none"><h2>🎯 Ziel erreicht</h2>'
                '<div class="muted">Gerade hat kein Produkt seinen Zielpreis erreicht.</div></section>')
    return (f'<section class="box reached"><h2>🎯 Ziel erreicht ({len(rows)})</h2>'
            f'<ul>{"".join(rows)}</ul></section>')


def render(products: list[Product], state: dict, history: dict, cfg: dict, now: dt.datetime) -> str:
    from . import zeitplan  # (hier importiert, um Kreisbezüge zu vermeiden)
    tz = ZoneInfo(cfg["zeitzone"])
    rules = cfg["regeln"]
    end = end_datetime(cfg)
    mode = zeitplan.mode(cfg, now)
    nxt = zeitplan.next_run(cfg, now)
    sources = state.get("quellen") or {}
    src_html = "".join(
        f'<li><span class="dot {STATUS_LABEL.get(s.get("status"), ("grey", ""))[0]}"></span>'
        f'<b>{e(name)}</b> <span class="tag {STATUS_LABEL.get(s.get("status"), ("grey", ""))[0]}">'
        f'{STATUS_LABEL.get(s.get("status"), ("grey", s.get("status")))[1]}</span>'
        f'<span class="muted"> {e(s.get("meldung", ""))}'
        f'{" · " + str(s.get("anzahl")) + " Treffer" if s.get("status") == "ok" else ""}</span></li>'
        for name, s in sources.items())
    errors = sum(1 for s in sources.values() if s.get("status") == "fehler")
    # Gelöschte Produkte stehen nicht mehr in products.yaml und erscheinen daher hier nicht –
    # ihr Preisverlauf bleibt aber in data/verlauf.json archiviert.
    active = [p for p in products if p.aktiv]
    reached = sum(1 for p in active if ampel(current_best(p, state, now, rules), p)[0] == "green")
    ordered = active + [p for p in products if not p.aktiv]  # pausierte ans Ende
    cards = "".join(product_card(p, state, history, now, rules, tz, cfg) for p in ordered)
    cats: dict[str, int] = {}
    for p in products:
        cats[p.kategorie] = cats.get(p.kategorie, 0) + 1
    chips = ('<button class="chip on" data-cat="">Alle</button>' + "".join(
        f'<button class="chip" data-cat="{e(c)}">{e(c)} <span class="muted">{n}</span></button>'
        for c, n in sorted(cats.items())))
    coupons = gutscheine_html(state, now)
    if mode == "wunschliste":
        run_label, run_value = "Wunschlisten-Modus", "1× täglich"
        run_note = f"seit {end.astimezone(tz):%d.%m.%Y}" if end else ""
    elif mode == "aus":
        run_label, run_value, run_note = "Radar beendet", "aus", ""
    else:
        run_label = "Normaler Betrieb bis" if end else "Laufzeit"
        run_value = (f'<span id="countdown" data-end="{end.isoformat()}">{end.astimezone(tz):%d.%m. %H:%M}</span>'
                     if end else "ohne Enddatum")
        run_note = (f"{zeitplan.describe(cfg, now)}; danach "
                    + ("Ende" if str(cfg.get("nach_ende")) == "aus" else "1× täglich (Wunschliste)") if end
                    else zeitplan.describe(cfg, now))
    return f"""<!doctype html>
<html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Deal-Radar</title>
<meta name="robots" content="noindex">
<meta name="description" content="Persönliches Preis-Radar: Deals, Zielpreise und Preisverlauf">
<link rel="manifest" href="manifest.webmanifest">
<link rel="icon" href="icon-192.png" type="image/png">
<link rel="apple-touch-icon" href="icon-192.png">
<meta name="theme-color" content="#2f5bea">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="Deal-Radar">
<style>
:root{{--bg:#f6f7f9;--card:#fff;--text:#1d2430;--muted:#667085;--line:#e4e7ec;--accent:#2f5bea;
--green:#12a150;--yellow:#e6a700;--red:#d92d20;--grey:#98a2b3;--chip:#eef2f6}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{--bg:#0f1218;--card:#181c24;--text:#e6e9ef;
--muted:#98a2b3;--line:#2a303c;--accent:#7b9bff;--chip:#232937}}}}
:root[data-theme="dark"]{{--bg:#0f1218;--card:#181c24;--text:#e6e9ef;--muted:#98a2b3;--line:#2a303c;--accent:#7b9bff;--chip:#232937}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--text);font:16px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}}
a{{color:var(--accent)}}
.wrap{{max-width:1100px;margin:0 auto;padding:16px}}
.top{{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));margin-bottom:16px}}
.box{{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px}}
h1{{font-size:1.5rem;margin:4px 0 12px;display:flex;gap:10px;align-items:center;flex-wrap:wrap}}
h2{{font-size:1.05rem;margin:0}}
.big{{font-size:1.4rem;font-weight:700;font-variant-numeric:tabular-nums}}
.muted{{color:var(--muted);font-size:.9rem}}
.reached{{margin-bottom:16px;border-color:var(--green)}} .reached.none{{border-color:var(--line)}}
.reached ul{{list-style:none;padding:0;margin:10px 0 0;display:grid;gap:8px}}
.reached li{{display:flex;justify-content:space-between;gap:12px;align-items:center;flex-wrap:wrap;
border-top:1px solid var(--line);padding-top:8px}}
.buy{{background:var(--green);color:#fff;text-decoration:none;font-weight:600;padding:8px 14px;border-radius:10px;white-space:nowrap}}
.toolbar{{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:0 0 12px}}
.chip{{font:inherit;font-size:.88rem;border:1px solid var(--line);background:var(--card);color:var(--text);
border-radius:99px;padding:5px 12px;cursor:pointer}}
.chip.on{{background:var(--accent);border-color:var(--accent);color:#fff}} .chip.on .muted{{color:#e6ecff}}
.toolbar select{{font:inherit;font-size:.88rem;padding:5px 8px;border-radius:8px;border:1px solid var(--line);
background:var(--card);color:var(--text);margin-left:auto}}
.grid{{display:grid;gap:14px;grid-template-columns:repeat(auto-fill,minmax(300px,1fr))}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px;display:flex;flex-direction:column;gap:8px;min-width:0}}
.card.paused{{opacity:.6}} .card[hidden]{{display:none}}
.card header{{display:flex;gap:10px;align-items:flex-start}}
.dot{{width:12px;height:12px;border-radius:50%;flex:none;margin-top:5px;display:inline-block}}
.dot.green{{background:var(--green)}} .dot.yellow{{background:var(--yellow)}} .dot.red{{background:var(--red)}} .dot.grey{{background:var(--grey)}}
.tag{{font-size:.75rem;padding:1px 8px;border-radius:99px;background:var(--chip)}}
.tag.green{{color:var(--green)}} .tag.red{{color:var(--red)}} .tag.yellow{{color:var(--yellow)}}
.mode{{font-size:.8rem;font-weight:500}}
.price{{font-size:1.8rem;font-weight:700;font-variant-numeric:tabular-nums}} .price.none{{font-size:1.1rem;color:var(--muted)}}
.offer-title{{font-size:.85rem;color:var(--muted);overflow-wrap:anywhere}}
.hints{{font-size:.85rem;background:var(--chip);border-radius:8px;padding:6px 8px}}
.hints.trust{{background:color-mix(in srgb,var(--yellow) 18%,var(--card))}}
.advice{{font-size:.9rem;font-weight:600}}
.facts{{display:grid;grid-template-columns:1fr 1fr;gap:8px;border-top:1px solid var(--line);padding-top:8px}}
.facts span{{display:block;font-size:.78rem;color:var(--muted)}} .facts small{{color:var(--muted)}}
.spark{{width:100%;height:48px}} .spark-line{{fill:none;stroke:var(--accent);stroke-width:2;vector-effect:non-scaling-stroke}}
.spark-dot{{fill:var(--accent)}} .spark-target{{stroke:var(--green);stroke-dasharray:4 4;stroke-width:1;vector-effect:non-scaling-stroke}}
.spark-legend{{display:flex;justify-content:space-between;font-size:.72rem;color:var(--muted)}}
.spark-empty{{font-size:.8rem;color:var(--muted)}}
dl.lease{{display:grid;grid-template-columns:auto 1fr;gap:2px 12px;margin:4px 0;font-size:.9rem}}
dl.lease dt{{color:var(--muted)}} dl.lease dd{{margin:0;text-align:right;font-variant-numeric:tabular-nums}}
details{{font-size:.88rem}} details ul{{padding-left:18px;margin:6px 0}} details li{{margin-bottom:4px;overflow-wrap:anywhere}}
summary{{cursor:pointer;color:var(--muted)}}
.sources{{list-style:none;padding:0;margin:8px 0 0;display:grid;gap:4px;font-size:.9rem}}
.sources li{{display:flex;gap:6px;align-items:baseline;flex-wrap:wrap}} .sources .dot{{margin-top:0}}
.notes{{font-size:.85rem;color:var(--muted)}}
.empty{{display:none;padding:20px;text-align:center}}
footer{{margin:24px 0;font-size:.8rem;color:var(--muted)}}
</style></head><body><div class="wrap">
<h1>📡 Deal-Radar <span class="tag mode">{e(zeitplan.describe(cfg, now))}</span></h1>
{_reached_html(ordered, state, now, rules)}
<section class="top">
  <div class="box"><div class="muted">Letzter Lauf</div><div class="big">{when(state.get("letzter_lauf"), tz)}</div></div>
  <div class="box"><div class="muted">Nächster Lauf</div>
  <div class="big">{nxt.astimezone(tz).strftime("%d.%m. %H:%M Uhr") if nxt else "–"}</div>
  <div class="muted">ca., GitHub startet manchmal etwas später</div></div>
  <div class="box"><div class="muted">{run_label}</div><div class="big">{run_value}</div>
  <div class="muted">{e(run_note)}</div></div>
  <div class="box"><div class="muted">Ziel erreicht</div><div class="big">{reached} / {len(active)}</div>
  <div class="muted">{len(products) - len(active)} pausiert</div></div>
</section>
<details class="box" style="margin-bottom:16px"{" open" if errors else ""}>
<summary>Datenquellen: {len(sources) - errors} von {len(sources)} ohne Fehler{f" · ⚠️ {errors} mit Fehler" if errors else ""}</summary>
<ul class="sources">{src_html or "<li>noch kein Lauf</li>"}</ul></details>
<nav class="toolbar" aria-label="Filter">{chips}
<select id="sort" aria-label="Sortierung"><option value="score">Sortieren: Deal-Score</option>
<option value="gap">Nähe zum Zielpreis</option><option value="name">Name</option><option value="list">Reihenfolge der Liste</option></select></nav>
<section class="grid" id="cards">{cards}</section>
<div class="box empty" id="empty">Keine Produkte in dieser Kategorie.</div>
{coupons}
<footer>Preise ohne Gewähr. Effektivpreis = Preis + Versand − Gutschein − Cashback − Zahlungsrabatt (Rechenweg in der
Karte); UVP und Streichpreise zählen nie. Ampel: grün = Zielpreis erreicht, gelb = bis 10 % darüber, rot = darüber,
grau = kein aktuelles Angebot (letzte {rules.get("aktuell_stunden", 48)} Std.). Deal-Score: 50 = üblicher Preis,
100 = 20 % unter dem eigenen 90-Tage-Median. Leasing: verglichen wird die effektive Rate.
Diese Seite lässt sich als App installieren (Browser-Menü → „Zum Startbildschirm“ / „App installieren“).</footer>
</div>
<script>
(function(){{
  var grid=document.getElementById("cards"),sel=document.getElementById("sort"),empty=document.getElementById("empty");
  var cards=Array.prototype.slice.call(grid.children),order=cards.slice();
  var store={{get:function(k){{try{{return localStorage.getItem(k)}}catch(e){{return null}}}},
             set:function(k,v){{try{{localStorage.setItem(k,v)}}catch(e){{}}}}}};
  var cat=store.get("dr-cat")||"",sort=store.get("dr-sort")||"score";
  function apply(){{
    var shown=0;
    cards.forEach(function(c){{var ok=!cat||c.dataset.kategorie===cat;c.hidden=!ok;if(ok)shown++;}});
    var list=sort==="list"?order.slice():cards.slice().sort(function(a,b){{
      var pa=a.classList.contains("paused"),pb=b.classList.contains("paused");if(pa!==pb)return pa?1:-1;
      if(sort==="score")return (+b.dataset.score)-(+a.dataset.score)||(+a.dataset.gap)-(+b.dataset.gap);
      if(sort==="gap")return (+a.dataset.gap)-(+b.dataset.gap);
      return a.dataset.name.localeCompare(b.dataset.name,"de");}});
    list.forEach(function(c){{grid.appendChild(c);}});
    empty.style.display=shown?"none":"block";
    document.querySelectorAll(".chip").forEach(function(b){{b.classList.toggle("on",b.dataset.cat===cat);}});
    sel.value=sort;
  }}
  document.querySelectorAll(".chip").forEach(function(b){{b.addEventListener("click",function(){{
    cat=b.dataset.cat;store.set("dr-cat",cat);apply();}});}});
  sel.addEventListener("change",function(){{sort=sel.value;store.set("dr-sort",sort);apply();}});
  if(cat&&!document.querySelector('.chip[data-cat="'+cat.replace(/"/g,"")+'"]'))cat="";
  apply();
  var el=document.getElementById("countdown");
  if(el){{var end=new Date(el.dataset.end);(function tick(){{var s=Math.floor((end-new Date())/1000);
    if(s<=0){{el.textContent="vorbei";return;}}var d=Math.floor(s/86400),h=Math.floor(s%86400/3600),m=Math.floor(s%3600/60);
    el.textContent=(d?d+" T ":"")+h+" Std "+m+" Min";setTimeout(tick,30000);}})();}}
  if("serviceWorker" in navigator){{navigator.serviceWorker.register("sw.js").catch(function(){{}});}}
}})();
</script></body></html>"""

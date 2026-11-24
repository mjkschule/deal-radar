"""Erzeugt die Startseite docs/index.html (statisch, mobil lesbar, Deutsch)."""

from __future__ import annotations

import datetime as dt
import html
from zoneinfo import ZoneInfo

from .config import Product, end_datetime
from .logic import _fmt, current_best, offers_by_status
from .models import AUSGESCHLOSSEN, NICHT_PASSEND, VERDAECHTIG


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
    rows = [
        ("Rate", euro(l.get("rate"))),
        ("Sonderzahlung", euro(l.get("sonderzahlung")) if l.get("sonderzahlung") is not None else "unbekannt"),
        ("Bereitstellung", euro(l.get("bereitstellung")) if l.get("bereitstellung") is not None else "unbekannt"),
        ("Laufzeit / km", f"{l.get('monate') or '?'} Mon. · {(str(l.get('km')) if l.get('km') else '?')} km/Jahr"),
        ("Effektive Rate", euro(l.get("effektiv"))),
    ]
    return '<dl class="lease">' + "".join(f"<dt>{a}</dt><dd>{b}</dd>" for a, b in rows) + "</dl>"


def _offer_row(d: dict, tz) -> str:
    price = euro(d.get("vergleichspreis"))
    reason = f' – {e(d.get("status_reason"))}' if d.get("status_reason") else ""
    return (f'<li><a href="{e(d["url"])}" rel="noopener" target="_blank">{e(d["title"][:90])}</a>'
            f'<span class="muted"> · {e(d["shop"])} · {price}{reason}</span></li>')


def product_card(p: Product, state: dict, history: dict, now: dt.datetime, rules: dict, tz) -> str:
    best = current_best(p, state, now, rules)
    low = (state.get("tiefstpreis") or {}).get(p.id)
    color, label = ampel(best, p)
    unit = " €/Monat" if p.is_leasing else " €"
    target = f"{_fmt(p.zielpreis)}{unit}" + (" (Rate)" if p.is_leasing else "")
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
        hints = " · ".join(best.get("hints") or [])
        main = (f'<div class="price">{big}</div>'
                f'<div class="muted">{e(ship)}</div>'
                f'<div class="shop"><a href="{e(best["url"])}" rel="noopener" target="_blank">{e(best["shop"])} öffnen ↗</a>'
                f' <span class="muted">· gesehen {when(best.get("first_seen"), tz)} · {e(best["source"])}</span></div>'
                f'<div class="offer-title">{e(best["title"][:140])}</div>'
                + (f'<div class="hints">⚠️ {e(hints)}</div>' if hints else "")
                + (_leasing_details(best) if p.is_leasing else ""))
    else:
        main = '<div class="price none">Kein aktuelles Angebot</div><div class="muted">Das Radar sucht weiter …</div>'

    extra = ""
    bad = offers_by_status(p, state, now, rules, (VERDAECHTIG, AUSGESCHLOSSEN))
    unfit = offers_by_status(p, state, now, rules, (NICHT_PASSEND,))
    if unfit:
        extra += (f'<details><summary>Nicht passend ({len(unfit)})</summary><ul>'
                  + "".join(_offer_row(d, tz) for d in unfit[:15]) + "</ul></details>")
    if bad:
        extra += (f'<details><summary>Verdächtig / ausgeschlossen ({len(bad)})</summary><ul>'
                  + "".join(_offer_row(d, tz) for d in bad[:15]) + "</ul></details>")
    notes = f'<div class="notes">{e(p.notizen)}</div>' if p.notizen else ""
    return f"""
<article class="card" id="{e(p.id)}">
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


def render(products: list[Product], state: dict, history: dict, cfg: dict, now: dt.datetime) -> str:
    tz = ZoneInfo(cfg["zeitzone"])
    rules = cfg["regeln"]
    end = end_datetime(cfg)
    sources = state.get("quellen") or {}
    src_html = "".join(
        f'<li><span class="dot {STATUS_LABEL.get(s.get("status"), ("grey", ""))[0]}"></span>'
        f'<b>{e(name)}</b> <span class="tag {STATUS_LABEL.get(s.get("status"), ("grey", ""))[0]}">'
        f'{STATUS_LABEL.get(s.get("status"), ("grey", s.get("status")))[1]}</span>'
        f'<span class="muted"> {e(s.get("meldung", ""))}'
        f'{" · " + str(s.get("anzahl")) + " Treffer" if s.get("status") == "ok" else ""}</span></li>'
        for name, s in sources.items())
    reached = sum(1 for p in products if ampel(current_best(p, state, now, rules), p)[0] == "green")
    cards = "".join(product_card(p, state, history, now, rules, tz) for p in products)
    ended = now > end
    return f"""<!doctype html>
<html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Deal-Radar</title>
<meta name="robots" content="noindex">
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
.top{{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));margin-bottom:16px}}
.box{{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px}}
h1{{font-size:1.5rem;margin:4px 0 12px}} h2{{font-size:1.05rem;margin:0}}
.big{{font-size:1.6rem;font-weight:700;font-variant-numeric:tabular-nums}}
.muted{{color:var(--muted);font-size:.9rem}}
.grid{{display:grid;gap:14px;grid-template-columns:repeat(auto-fill,minmax(300px,1fr))}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px;display:flex;flex-direction:column;gap:8px;min-width:0}}
.card header{{display:flex;gap:10px;align-items:flex-start}}
.dot{{width:12px;height:12px;border-radius:50%;flex:none;margin-top:5px;display:inline-block}}
.dot.green{{background:var(--green)}} .dot.yellow{{background:var(--yellow)}} .dot.red{{background:var(--red)}} .dot.grey{{background:var(--grey)}}
.tag{{font-size:.75rem;padding:1px 8px;border-radius:99px;background:var(--chip)}}
.tag.green{{color:var(--green)}} .tag.red{{color:var(--red)}} .tag.yellow{{color:var(--yellow)}}
.price{{font-size:1.8rem;font-weight:700;font-variant-numeric:tabular-nums}} .price.none{{font-size:1.1rem;color:var(--muted)}}
.offer-title{{font-size:.85rem;color:var(--muted);overflow-wrap:anywhere}}
.hints{{font-size:.85rem;background:var(--chip);border-radius:8px;padding:6px 8px}}
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
.sources{{list-style:none;padding:0;margin:0;display:grid;gap:4px;font-size:.9rem}}
.sources li{{display:flex;gap:6px;align-items:baseline;flex-wrap:wrap}} .sources .dot{{margin-top:0}}
.notes{{font-size:.85rem;color:var(--muted)}}
footer{{margin:24px 0;font-size:.8rem;color:var(--muted)}}
</style></head><body><div class="wrap">
<h1>📡 Deal-Radar</h1>
<section class="top">
  <div class="box"><div class="muted">Letzter Lauf</div><div class="big">{when(state.get("letzter_lauf"), tz)}</div>
  <div class="muted">läuft automatisch etwa alle 2 Stunden</div></div>
  <div class="box"><div class="muted">{"Radar beendet" if ended else "Countdown bis Black Friday-Ende"}</div>
  <div class="big" id="countdown" data-end="{end.isoformat()}">{"vorbei" if ended else "…"}</div>
  <div class="muted">Ende: {end.astimezone(tz).strftime("%d.%m.%Y, %H:%M Uhr")}</div></div>
  <div class="box"><div class="muted">Ziel erreicht</div><div class="big">{reached} / {len(products)}</div>
  <div class="muted">Produkte mit grüner Ampel</div></div>
  <div class="box"><div class="muted">Datenquellen</div><ul class="sources">{src_html or "<li>noch kein Lauf</li>"}</ul></div>
</section>
<section class="grid">{cards}</section>
<footer>Preise ohne Gewähr; „Versand unbekannt“ = Versandkosten nicht ermittelbar. Ampel: grün = Zielpreis erreicht,
gelb = bis 10 % darüber, rot = darüber, grau = kein aktuelles Angebot (letzte {rules.get("aktuell_stunden", 48)} Std.).
Leasing: verglichen wird die effektive Rate = (Rate × Monate + Sonderzahlung + Bereitstellung) / Monate;
der Alarm richtet sich nach der Monatsrate.</footer>
</div>
<script>
(function(){{var el=document.getElementById("countdown");if(!el)return;var end=new Date(el.dataset.end);
function tick(){{var s=Math.floor((end-new Date())/1000);if(s<=0){{el.textContent="vorbei";return;}}
var d=Math.floor(s/86400),h=Math.floor(s%86400/3600),m=Math.floor(s%3600/60);
el.textContent=(d?d+" T ":"")+h+" Std "+m+" Min";}}tick();setInterval(tick,30000);}})();
</script></body></html>"""

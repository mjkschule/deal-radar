"""Deal-Postfach (Gmail per IMAP): Preisalarme von idealo/Geizhals und Gutscheine aus Newslettern.

Einrichtung (README Abschnitt 1.7): eigenes Gmail-Konto, 2-Schritt-Bestätigung, App-Passwort,
dann die GitHub-Secrets DEAL_MAIL_ADRESSE und DEAL_MAIL_APP_PASSWORT.

Datenschutz – das Repo ist öffentlich:
  * Das Postfach wird NUR GELESEN (readonly, BODY.PEEK) – nichts wird gelöscht oder als gelesen markiert.
  * Gespeichert/angezeigt werden nur: Shop, Rabatt, Mindestbestellwert, Gültigkeit, Datum.
    NICHT gespeichert: Gutschein-Codes (können persönlich sein), Betreff, Text, Adressen.
  * Links aus Preisalarm-Mails werden ohne Parameter (?…) übernommen (keine Tracking-IDs).
"""

from __future__ import annotations

import datetime as dt
import email
import imaplib
import re
from email.header import decode_header, make_header
from email.utils import parseaddr, parsedate_to_datetime
from urllib.parse import quote_plus, urlparse

from .. import prices
from ..config import Product
from ..matching import matches
from ..models import Offer
from . import Context, Skipped, strip_tags

NAME = "postfach"
HOST = "imap.gmail.com"
TAGE = 14          # so weit zurück werden Mails gelesen
MAX_MAILS = 150

ALARM_ABSENDER = {"idealo": "idealo", "geizhals": "Geizhals"}

_CODE_RE = re.compile(r"(?:gutschein-?code|rabatt-?code|aktionscode|promo-?code|code)\s*[:„\"']?\s*([A-Z0-9][A-Z0-9-]{3,19})\b", re.I)
_PCT_RE = re.compile(r"(\d{1,2})\s?%\s*(?:rabatt|sparen|auf|extra|off)", re.I)
_EUR_RE = re.compile(r"(\d{1,3}(?:,\d{2})?)\s?(?:€|euro)\s*(?:rabatt|sparen|geschenkt|gutschein|nachlass|off)", re.I)
_MBW_RE = re.compile(r"(?:ab|mindestbestellwert(?: von)?|mbw(?: von)?)\s*(\d{1,4}(?:,\d{2})?)\s?(?:€|euro)", re.I)
_BIS_RE = re.compile(r"(?:gültig )?bis(?: zum| einschließlich)?\s*(\d{1,2})\.(\d{1,2})\.(\d{2,4})?", re.I)


def _text(value) -> str:
    try:
        return str(make_header(decode_header(value or "")))
    except Exception:
        return str(value or "")


def mail_body(msg: email.message.Message) -> tuple[str, list[str]]:
    """(Text ohne HTML, Links)"""
    parts = []
    for part in (msg.walk() if msg.is_multipart() else [msg]):
        ctype = part.get_content_type()
        if ctype not in ("text/plain", "text/html"):
            continue
        try:
            raw = part.get_payload(decode=True) or b""
            parts.append((ctype, raw.decode(part.get_content_charset() or "utf-8", "replace")))
        except Exception:
            continue
    html_part = next((t for c, t in parts if c == "text/html"), "")
    plain = next((t for c, t in parts if c == "text/plain"), "")
    links = re.findall(r'href=["\'](https?://[^"\']+)', html_part) or re.findall(r"https?://\S+", plain)
    return (strip_tags(html_part) if html_part else plain), links


def sender_info(msg) -> tuple[str, str]:
    """(Anzeigename oder Domain, Domain)"""
    name, addr = parseaddr(_text(msg.get("From")))
    domain = addr.split("@")[-1].lower() if "@" in addr else ""
    shop_domain = ".".join(domain.split(".")[-2:]) if domain else ""
    return (name.strip() or shop_domain or "unbekannt"), shop_domain


def clean_link(url: str) -> str:
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}{p.path}"


# Nur Links auf die echte Portal-Seite – keine Klick-/Newsletter-Weiterleitungen: die enthalten einen
# persönlichen Schlüssel deines Postfachs und dürfen nicht ins öffentliche Repo.
PORTAL_HOSTS = {"idealo": ("www.idealo.de", "idealo.de"), "geizhals": ("geizhals.de", "www.geizhals.de")}
SEARCH = {"idealo": "https://www.idealo.de/preisvergleich/MainSearchProductCategory.html?q={q}",
          "geizhals": "https://geizhals.de/?fs={q}"}


def portal_link(links: list[str], portal: str, product_name: str) -> str:
    """Neutraler Link: Produktseite im Portal (ohne Parameter) oder sonst die Portal-Suche."""
    hosts = PORTAL_HOSTS.get(portal.lower(), ())
    for u in links:
        p = urlparse(u)
        if p.scheme == "https" and p.netloc.lower() in hosts and len(p.path) > 1:
            return clean_link(u)
    return SEARCH.get(portal.lower(), "https://www.idealo.de/preisvergleich/MainSearchProductCategory.html?q={q}") \
        .format(q=quote_plus(product_name))


def is_tracking_link(url: str) -> bool:
    """Klick-Link aus einer Mail (z. B. clicks.news.idealo.com) – nie speichern."""
    host = urlparse(url or "").netloc.lower()
    return bool(host) and any(host.endswith(d) for d in ("idealo.com", "idealo.de", "geizhals.de", "geizhals.at")) \
        and host not in {h for hs in PORTAL_HOSTS.values() for h in hs}


def parse_alarm(msg, products: list[Product], portal: str) -> list[Offer]:
    """Preisalarm-Mail (idealo/Geizhals): passendes Produkt + Preis aus Betreff/Text."""
    subject = _text(msg.get("Subject"))
    body, links = mail_body(msg)
    text = f"{subject} {body[:3000]}"
    price = prices.parse_price(subject) or prices.parse_price(body[:1500])
    if not price:
        return []
    offers = []
    for prod in products:
        if prod.is_leasing or not matches(prod, text):
            continue
        offers.append(Offer(product_id=prod.id, source=NAME, shop=f"{portal} (Preisalarm)",
                            title=f"{portal}-Preisalarm: {prod.name}", url=portal_link(links, portal, prod.name),
                            price=price, shipping=None,
                            hints=["Bestpreis laut Preisalarm – Shop und Versand im Portal prüfen"], text=text))
    return offers


def parse_coupon(msg, now: dt.datetime) -> dict | None:
    """Gutschein aus einem Newsletter – OHNE den Code selbst (öffentliches Repo)."""
    subject = _text(msg.get("Subject"))
    body, _ = mail_body(msg)
    text = f"{subject} {body[:4000]}"
    if not _CODE_RE.search(text):
        return None
    pct = _PCT_RE.search(text)
    eur = _EUR_RE.search(text)
    if not pct and not eur:
        return None
    shop, domain = sender_info(msg)
    mbw = _MBW_RE.search(text)
    until = None
    m = _BIS_RE.search(text)
    if m:
        year = int(m.group(3)) if m.group(3) else now.year
        year = year + 2000 if year < 100 else year
        try:
            until = dt.date(year, int(m.group(2)), int(m.group(1))).isoformat()
        except ValueError:
            until = None
    try:
        date = parsedate_to_datetime(msg.get("Date")).date().isoformat()
    except Exception:
        date = now.date().isoformat()
    return {
        "shop": shop[:60], "domain": domain,
        "rabatt_prozent": int(pct.group(1)) if pct else None,
        "rabatt_euro": prices.to_number(eur.group(1)) if eur and not pct else None,
        "mindestbestellwert": prices.to_number(mbw.group(1)) if mbw else None,
        "gueltig_bis": until, "mail_vom": date,
    }


def read_mails(env: dict, since: dt.date) -> list[email.message.Message]:
    """Liest die Mails seit `since` (nur lesend). Kann in Tests ersetzt werden."""
    imap = imaplib.IMAP4_SSL(HOST, 993, timeout=30)
    try:
        imap.login(env["DEAL_MAIL_ADRESSE"], env["DEAL_MAIL_APP_PASSWORT"])
        imap.select("INBOX", readonly=True)
        _, data = imap.search(None, "SINCE", since.strftime("%d-%b-%Y"))
        ids = (data[0] or b"").split()[-MAX_MAILS:]
        msgs = []
        for i in ids:
            _, parts = imap.fetch(i, "(BODY.PEEK[])")
            for p in parts:
                if isinstance(p, tuple):
                    msgs.append(email.message_from_bytes(p[1]))
        return msgs
    finally:
        try:
            imap.logout()
        except Exception:
            pass


def fetch(products: list[Product], ctx: Context) -> list[Offer]:
    if not (ctx.env.get("DEAL_MAIL_ADRESSE") and ctx.env.get("DEAL_MAIL_APP_PASSWORT")):
        raise Skipped("nicht eingerichtet (Gmail-Konto + App-Passwort, siehe README 1.7)")
    try:
        msgs = read_mails(ctx.env, (ctx.now - dt.timedelta(days=TAGE)).date())
    except imaplib.IMAP4.error as e:
        raise RuntimeError(f"Anmeldung fehlgeschlagen – App-Passwort prüfen ({e})") from None
    offers: list[Offer] = []
    coupons: list[dict] = []
    alarms = 0
    for msg in msgs:
        _, domain = sender_info(msg)
        portal = next((v for k, v in ALARM_ABSENDER.items() if k in domain), None)
        if portal:
            found = parse_alarm(msg, products, portal)
            alarms += 1 if found else 0
            offers.extend(found)
            continue
        c = parse_coupon(msg, ctx.now)
        if c and not (c["gueltig_bis"] and c["gueltig_bis"] < ctx.now.date().isoformat()):
            coupons.append(c)
    # pro Shop nur den besten Gutschein merken
    best: dict[str, dict] = {}
    for c in coupons:
        k = c["domain"] or c["shop"]
        score = (c["rabatt_prozent"] or 0) * 10 + (c["rabatt_euro"] or 0)
        if k not in best or score > best[k]["_s"]:
            best[k] = {**c, "_s": score}
    ctx.cache["gutscheine"] = [{k: v for k, v in c.items() if k != "_s"} for c in best.values()]
    ctx.notes.append(f"{len(msgs)} Mails, {alarms} Preisalarme mit Treffer, {len(best)} Gutscheine")
    return offers


def _neutral(url: str, shop: str, name: str) -> str:
    portal = "geizhals" if "geizhals" in (shop or "").lower() or "geizhals" in url else "idealo"
    return portal_link([], portal, name)


def scrub_state(state: dict, names: dict[str, str]) -> int:
    """Ersetzt gespeicherte Klick-Links aus Mails (Altbestand) durch neutrale Portal-Links.
    names: produkt_id -> Produktname. Gibt die Zahl der ersetzten Links zurück."""
    n = 0
    for pid, store in (state.get("angebote") or {}).items():
        for key in [k for k, d in store.items() if is_tracking_link(d.get("url"))]:
            d = store.pop(key)
            d["url"] = _neutral(d["url"], d.get("shop"), names.get(pid, pid))
            new_key = f"{(d.get('shop') or '').lower()}|{d['url']}"
            if new_key not in store or store[new_key].get("last_seen", "") < d.get("last_seen", ""):
                store[new_key] = d
            n += 1
    for pid, low in (state.get("tiefstpreis") or {}).items():
        if low and is_tracking_link(low.get("url")):
            low["url"] = _neutral(low["url"], low.get("shop"), names.get(pid, pid))
            n += 1
    reported = state.get("gemeldet") or {}
    for key in [k for k in reported if is_tracking_link(k.split("|", 1)[-1])]:
        reported.pop(key)  # doppelte Meldung verhindert weiterhin "gemeldet_shop_preis" (Shop + Preis)
        n += 1
    for item in state.get("warteschlange") or []:
        if is_tracking_link(item.get("url")):
            item["url"] = _neutral(item["url"], item.get("shop"), item.get("name", ""))
            item["text"] = re.sub(r'https://[^"\s<]*idealo\.com[^"\s<]*', item["url"], item.get("text", ""))
            for row in item.get("buttons") or []:
                for b in row:
                    if is_tracking_link(b.get("url")):
                        b["url"] = item["url"]
            n += 1
    return n


def scrub_csv(path, names: dict[str, str]) -> int:
    """Gleiches für data/verlauf.csv (Spalte url)."""
    import csv
    if not path.exists() or "idealo.com" not in (text := path.read_text(encoding="utf-8")) and "geizhals.at" not in text:
        return 0
    rows = list(csv.DictReader(text.splitlines(), delimiter=";"))
    n = 0
    for r in rows:
        if is_tracking_link(r.get("url")):
            r["url"] = _neutral(r["url"], r.get("shop"), names.get(r.get("produkt_id"), r.get("produkt_id") or ""))
            n += 1
    if n:
        with path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()), delimiter=";")
            w.writeheader()
            w.writerows(rows)
    return n

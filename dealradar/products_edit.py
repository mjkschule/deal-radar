"""Neue Produkte zu products.yaml hinzufügen (aus Telegram-/neu oder GitHub-Issue).

Die Datei wird NICHT neu geschrieben, sondern der neue Eintrag unten angehängt –
so bleiben deine Kommentare erhalten.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import yaml

from .config import ConfigError, parse_products


def slugify(name: str) -> str:
    t = name.lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
    return t[:40].strip("-") or "produkt"


def _split_list(text: str) -> list[str]:
    parts = re.split(r"[\n,]", text or "")
    return [p.strip().strip("-•").strip() for p in parts if p.strip().strip("-•").strip()]


def _price(text: str) -> float:
    m = re.search(r"\d+(?:[.,]\d{1,2})?", text or "")
    if not m:
        raise ConfigError(f"Zielpreis '{text}' ist keine Zahl.")
    return float(m.group(0).replace(",", "."))


def parse_telegram_command(text: str) -> dict:
    """'/neu Name; Zielpreis; Suchbegriff1, Suchbegriff2' -> Produkt-Dict."""
    body = re.sub(r"^/neu(@\w+)?\s*", "", text.strip(), flags=re.I)
    parts = [p.strip() for p in body.split(";")]
    if len(parts) < 2 or not parts[0]:
        raise ConfigError("Format: /neu Name; Zielpreis; Suchbegriff1, Suchbegriff2")
    name, target = parts[0], _price(parts[1])
    terms = _split_list(parts[2]) if len(parts) > 2 and parts[2] else [name]
    return {"name": name, "zielpreis": target, "suchbegriffe": terms}


def parse_issue_form(body: str) -> dict:
    """Liest den Text eines GitHub-Issue-Formulars ('### Feld' + Wert)."""
    fields: dict[str, str] = {}
    current = None
    for line in (body or "").splitlines():
        m = re.match(r"^###\s+(.+?)\s*$", line)
        if m:
            current = m.group(1).strip().lower()
            fields[current] = ""
        elif current is not None:
            fields[current] += line + "\n"
    get = lambda key: next((v.strip() for k, v in fields.items() if k.startswith(key)), "")  # noqa: E731
    clean = lambda v: "" if v in ("_No response_", "None") else v  # noqa: E731

    name = clean(get("name"))
    if not name:
        raise ConfigError("Feld 'Name' ist leer.")
    terms = _split_list(clean(get("suchbegriffe"))) or [name]
    product = {"name": name, "zielpreis": _price(clean(get("zielpreis"))), "suchbegriffe": terms}
    if clean(get("kategorie")):
        product["kategorie"] = clean(get("kategorie"))
    excl = _split_list(clean(get("ausschluss")))
    if excl:
        product["ausschluss"] = excl
    urls = [u for u in _split_list(clean(get("shop"))) if u.startswith("http")]
    if urls:
        product["shop_urls"] = urls
    groups = [g.lower() for g in _split_list(clean(get("mydealz")))]
    if groups:
        product["mydealz_gruppen"] = groups
    notes = clean(get("notizen"))
    if notes:
        product["notizen"] = notes
    return product


def append_product(path: Path, product: dict, comment: str = "") -> dict:
    """Hängt das Produkt an products.yaml an und gibt den fertigen Eintrag zurück."""
    text = path.read_text(encoding="utf-8")
    existing = parse_products(yaml.safe_load(text))
    ids = {p.id for p in existing}
    base = slugify(product["name"])
    pid, n = base, 2
    while pid in ids:
        pid, n = f"{base}-{n}", n + 1
    entry = {"id": pid, **product}
    entry.setdefault("kategorie", "sonstiges")
    # Prüfen, ob der Eintrag gültig ist, bevor die Datei geändert wird
    parse_products([entry])
    block = yaml.safe_dump([entry], allow_unicode=True, sort_keys=False, default_flow_style=None, width=120)
    addition = ("\n" if not text.endswith("\n") else "") + "\n"
    if comment:
        addition += f"# {comment}\n"
    addition += block
    new_text = text + addition
    parse_products(yaml.safe_load(new_text))  # Gesamtdatei noch gültig?
    path.write_text(new_text, encoding="utf-8")
    return entry

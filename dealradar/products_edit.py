"""products.yaml ändern: Produkte hinzufügen, löschen, pausieren/fortsetzen.

Die Datei wird NIE komplett neu geschrieben. Es werden nur die Zeilen des
betroffenen Eintrags angehängt, entfernt oder angepasst – so bleiben deine
Kommentare und die Formatierung erhalten. Nach jeder Änderung wird geprüft,
ob die Datei noch gültig ist; sonst bleibt sie unverändert.
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


_ITEM_START = re.compile(r"""^- id:\s*["']?([a-z0-9][a-z0-9-]*)["']?\s*(#.*)?$""")


def _find_block(lines: list[str], pid: str) -> tuple[int, int]:
    """Zeilenbereich [start, end) des Eintrags mit dieser id (ohne Leerzeilen am Ende)."""
    for i, line in enumerate(lines):
        m = _ITEM_START.match(line.rstrip("\n"))
        if m and m.group(1) == pid:
            j = i + 1
            # Der Eintrag geht weiter, solange Zeilen eingerückt oder leer sind
            while j < len(lines) and (not lines[j].strip() or lines[j][:1] in (" ", "\t")):
                j += 1
            while j > i + 1 and not lines[j - 1].strip():
                j -= 1
            return i, j
    raise ConfigError(f"Eintrag '{pid}' wurde in products.yaml nicht gefunden (bitte im Web-Editor ändern).")


def _check_and_write(path: Path, new_text: str) -> list:
    products = parse_products(yaml.safe_load(new_text))
    path.write_text(new_text, encoding="utf-8")
    return products


def remove_product(path: Path, pid: str) -> dict:
    """Entfernt den Eintrag (samt direkt darüberstehendem Kommentar). Gibt den alten Eintrag zurück."""
    text = path.read_text(encoding="utf-8")
    raw = yaml.safe_load(text) or []
    old = next((item for item in raw if isinstance(item, dict) and str(item.get("id")) == pid), None)
    if old is None:
        raise ConfigError(f"Produkt '{pid}' gibt es nicht (mehr).")
    lines = text.splitlines(keepends=True)
    start, end = _find_block(lines, pid)
    # Kommentarzeilen direkt darüber (z. B. "# per Telegram hinzugefügt") gehören dazu,
    # Trennlinien wie "# ====" oder "# ----" bleiben stehen.
    while start > 0 and lines[start - 1].startswith("#") and not re.match(r"^#\s*[=-]{3,}", lines[start - 1]):
        start -= 1
    # eine Leerzeile davor mit entfernen, damit keine doppelten Leerzeilen bleiben
    if start > 0 and not lines[start - 1].strip():
        start -= 1
    new_lines = lines[:start] + lines[end:]
    products = _check_and_write(path, "".join(new_lines))
    if any(p.id == pid for p in products):
        raise ConfigError("Löschen fehlgeschlagen (Eintrag noch vorhanden).")
    return old


def set_active(path: Path, pid: str, active: bool) -> None:
    """Setzt 'aktiv: true/false' im Eintrag (fügt die Zeile ggf. direkt unter 'id' ein)."""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    start, end = _find_block(lines, pid)
    value = "true" if active else "false"
    for k in range(start + 1, end):
        if re.match(r"^  aktiv\s*:", lines[k]):
            lines[k] = f"  aktiv: {value}\n"
            break
    else:
        lines.insert(start + 1, f"  aktiv: {value}\n")
    products = _check_and_write(path, "".join(lines))
    if next(p for p in products if p.id == pid).aktiv is not active:
        raise ConfigError("Ändern von 'aktiv' fehlgeschlagen.")

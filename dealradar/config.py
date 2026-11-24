"""Laden und Prüfen von config.yaml und products.yaml."""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

ROOT = Path(__file__).resolve().parent.parent

DEFAULT_CONFIG = {
    "enddatum": "2026-11-27T23:59",
    "zeitzone": "Europe/Berlin",
    "user_agent": "DealRadar/1.0 (private Preisbeobachtung)",
    "pause_sekunden": 3,
    "timeout_sekunden": 25,
    "quellen": {"mydealz": True, "ebay": True, "shop": True, "leasingmarkt": True, "sparneuwagen": True},
    "mydealz_immer": ["new", "hot"],
    "leasingmarkt_max_seiten": 6,
    "leasingmarkt_max_details": 4,
    "regeln": {
        "rabatt_vs_tiefstpreis": 0.10,
        "verdacht_unter_median": 0.40,
        "aktuell_stunden": 48,
        "vergessen_nach_tagen": 7,
    },
}


class ConfigError(Exception):
    """Fehler in config.yaml oder products.yaml (mit verständlicher Meldung)."""


@dataclass
class Product:
    id: str
    name: str
    suchbegriffe: list[str]
    zielpreis: float
    kategorie: str = "sonstiges"
    typ: str = "produkt"  # "produkt" oder "leasing"
    ausschluss: list[str] = field(default_factory=list)
    shop_urls: list[str] = field(default_factory=list)
    mydealz_gruppen: list[str] = field(default_factory=list)
    ebay_suche: str | None = None
    pflicht_hinweise: list[str] = field(default_factory=list)
    mindestwerte: dict[str, float] = field(default_factory=dict)
    notizen: str = ""
    leasing: dict = field(default_factory=dict)

    @property
    def is_leasing(self) -> bool:
        return self.typ == "leasing"


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: Path | None = None) -> dict:
    path = path or ROOT / "config.yaml"
    data = {}
    if path.exists():
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as e:
            raise ConfigError(f"config.yaml ist kein gültiges YAML: {e}") from e
    return _deep_merge(DEFAULT_CONFIG, data)


def end_datetime(cfg: dict) -> dt.datetime:
    """Enddatum als zeitzonenbewusstes datetime (inklusive der angegebenen Minute)."""
    tz = ZoneInfo(cfg["zeitzone"])
    raw = str(cfg["enddatum"]).strip()
    try:
        end = dt.datetime.fromisoformat(raw)
    except ValueError as e:
        raise ConfigError(f"enddatum '{raw}' hat nicht das Format JJJJ-MM-TTTHH:MM") from e
    if end.tzinfo is None:
        end = end.replace(tzinfo=tz)
    # "bis einschließlich 23:59" -> bis zum Ende dieser Minute
    return end + dt.timedelta(seconds=59)


def now_local(cfg: dict) -> dt.datetime:
    return dt.datetime.now(ZoneInfo(cfg["zeitzone"]))


def is_over(cfg: dict, now: dt.datetime | None = None) -> bool:
    now = now or now_local(cfg)
    return now > end_datetime(cfg)


_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def _as_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [str(v) for v in value]


def parse_products(raw) -> list[Product]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ConfigError("products.yaml muss eine Liste sein (jeder Eintrag beginnt mit '- id:').")
    products: list[Product] = []
    seen: set[str] = set()
    for i, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise ConfigError(f"Eintrag Nr. {i} in products.yaml ist ungültig.")
        pid = str(item.get("id", "")).strip()
        where = f"Produkt '{pid or i}'"
        if not _ID_RE.match(pid):
            raise ConfigError(f"{where}: 'id' fehlt oder enthält ungültige Zeichen (erlaubt: a-z, 0-9, -).")
        if pid in seen:
            raise ConfigError(f"{where}: die id ist doppelt vergeben.")
        seen.add(pid)
        if not item.get("name"):
            raise ConfigError(f"{where}: 'name' fehlt.")
        terms = _as_list(item.get("suchbegriffe"))
        if not terms:
            raise ConfigError(f"{where}: mindestens ein Suchbegriff nötig.")
        try:
            target = float(str(item.get("zielpreis")).replace(",", "."))
        except (TypeError, ValueError) as e:
            raise ConfigError(f"{where}: 'zielpreis' muss eine Zahl sein.") from e
        typ = str(item.get("typ", "produkt")).strip().lower()
        if typ not in ("produkt", "leasing"):
            raise ConfigError(f"{where}: 'typ' muss 'produkt' oder 'leasing' sein.")
        mins = item.get("mindestwerte") or {}
        if not isinstance(mins, dict):
            raise ConfigError(f"{where}: 'mindestwerte' muss so aussehen: {{Hz: 75}}")
        products.append(
            Product(
                id=pid,
                name=str(item["name"]),
                suchbegriffe=terms,
                zielpreis=target,
                kategorie=str(item.get("kategorie") or "sonstiges"),
                typ=typ,
                ausschluss=_as_list(item.get("ausschluss")),
                shop_urls=_as_list(item.get("shop_urls")),
                mydealz_gruppen=_as_list(item.get("mydealz_gruppen")),
                ebay_suche=item.get("ebay_suche") or None,
                pflicht_hinweise=_as_list(item.get("pflicht_hinweise")),
                mindestwerte={str(k): float(v) for k, v in mins.items()},
                notizen=str(item.get("notizen") or ""),
                leasing=dict(item.get("leasing") or {}),
            )
        )
    return products


def load_products(path: Path | None = None) -> list[Product]:
    path = path or ROOT / "products.yaml"
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise ConfigError(f"{path.name} wurde nicht gefunden.") from e
    except yaml.YAMLError as e:
        raise ConfigError(f"products.yaml ist kein gültiges YAML (Einrückung prüfen!): {e}") from e
    return parse_products(raw)

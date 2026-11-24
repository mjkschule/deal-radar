"""Telegram-Befehle: /neu, /liste, /loeschen, /pause, /fortsetzen, /hilfe.

Die Befehle werden bei jedem Lauf (alle 2 Stunden) abgeholt und der Reihe nach
abgearbeitet. Nur Nachrichten aus deinem eigenen Chat (TELEGRAM_CHAT_ID) kommen
hier überhaupt an – das prüft telegram.Telegram.commands().

Nummern: /liste nummeriert die Produkte in der Reihenfolge von products.yaml.
Innerhalb eines Laufs bleiben die Nummern stabil – löschst du z. B. erst Nr. 3
und dann Nr. 5, ist wirklich das Produkt gemeint, das in deiner Liste Nr. 5 war.
"""

from __future__ import annotations

import datetime as dt
import html
import re
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import ConfigError, Product, load_products
from .logic import _fmt, current_best
from .page import ampel
from .products_edit import append_product, parse_telegram_command, remove_product, set_active

HELP = (
    "📡 <b>Deal-Radar – Befehle</b>\n"
    "<code>/liste</code> – alle Produkte mit Nummer, Zielpreis und aktuellem Bestpreis\n"
    "<code>/neu Name; Zielpreis; Suchbegriff1, Suchbegriff2</code> – Produkt hinzufügen\n"
    "<code>/loeschen 3</code> oder <code>/loeschen Makita</code> – Produkt entfernen\n"
    "<code>/pause 3</code> – Produkt vorübergehend nicht überwachen\n"
    "<code>/fortsetzen 3</code> – wieder überwachen\n"
    "Befehle werden beim nächsten Lauf (alle 2 Std.) verarbeitet."
)

AMPEL_ICON = {"green": "✅", "yellow": "🟡", "red": "🔴", "grey": "⚪"}
MAX_MESSAGE = 3800  # Telegram erlaubt 4096 Zeichen pro Nachricht


def _e(s) -> str:
    return html.escape(str(s), quote=False)


def _eur(v) -> str:
    """215 -> '215', 39.99 -> '39,99'"""
    return f"{v:g}" if float(v).is_integer() else _fmt(v)


def _fold(text: str) -> str:
    t = text.lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    return " ".join(re.findall(r"[a-z0-9]+", t))


def split_message(text: str, limit: int = MAX_MESSAGE) -> list[str]:
    """Teilt lange Nachrichten an Zeilenumbrüchen."""
    parts, current = [], ""
    for line in text.split("\n"):
        if current and len(current) + len(line) + 1 > limit:
            parts.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    if current:
        parts.append(current)
    return parts


@dataclass
class Batch:
    """Ergebnis eines Durchgangs: Antworten, Änderungen für den Commit, Archiv-Einträge."""
    replies: list[str] = field(default_factory=list)
    changes: list[str] = field(default_factory=list)
    archived: list[dict] = field(default_factory=list)


class CommandProcessor:
    def __init__(self, products_path: Path, state: dict, cfg: dict, now: dt.datetime):
        self.path = products_path
        self.state = state
        self.cfg = cfg
        self.now = now
        # Nummerierung zu Beginn des Laufs festhalten (siehe Modul-Beschreibung)
        self.numbered: list[str] = [p.id for p in load_products(products_path)]
        self.batch = Batch()

    # ----- Hilfsfunktionen -----
    def _products(self) -> dict[str, Product]:
        return {p.id: p for p in load_products(self.path)}

    def _nr(self, pid: str) -> int:
        return self.numbered.index(pid) + 1

    def resolve(self, arg: str, cmd: str) -> tuple[Product | None, str | None]:
        """Findet das gemeinte Produkt. Gibt (Produkt, None) oder (None, Antworttext) zurück."""
        arg = arg.strip()
        current = self._products()
        if not arg:
            return None, f"Bitte Nummer oder Name angeben, z. B. <code>{cmd} 3</code>. /liste zeigt die Nummern."
        if arg.isdigit():
            n = int(arg)
            if not 1 <= n <= len(self.numbered):
                return None, f"Nr. {n} gibt es nicht. /liste zeigt alle Produkte mit Nummer."
            pid = self.numbered[n - 1]
            if pid not in current:
                return None, f"Nr. {n} wurde gerade schon gelöscht."
            return current[pid], None
        q = _fold(arg)
        exact = [p for p in current.values() if p.id == arg.lower() or _fold(p.name) == q]
        if len(exact) == 1:
            return exact[0], None
        words = q.split()
        # Alle Wörter müssen in Name oder id vorkommen ("airfryer" findet "Philips Airfryer XL")
        hits = [p for p in current.values()
                if words and all(w in f"{_fold(p.name)} {_fold(p.id)}" for w in words)]
        if len(hits) == 1:
            return hits[0], None
        if not hits:
            return None, f"Kein Produkt passt zu „{_e(arg)}“. /liste zeigt alle Produkte mit Nummer."
        lines = [f"🤔 „{_e(arg)}“ passt auf {len(hits)} Produkte:"]
        for p in sorted(hits, key=lambda p: self._nr(p.id)):
            lines.append(f"{self._nr(p.id)}. {_e(p.name)}")
        first = self._nr(sorted(hits, key=lambda p: self._nr(p.id))[0].id)
        lines.append(f"Welches meinst du? Antworte mit der Nummer, z. B. <code>{cmd} {first}</code>")
        return None, "\n".join(lines)

    # ----- Befehle -----
    def cmd_liste(self) -> str:
        tz = ZoneInfo(self.cfg["zeitzone"])
        rules = self.cfg["regeln"]
        current = self._products()
        last = self.state.get("letzter_lauf")
        stamp = dt.datetime.fromisoformat(last).astimezone(tz).strftime("%d.%m. %H:%M") if last else "–"
        lines = [f"📋 <b>Deine Produkte</b> (Preise vom letzten Lauf, {stamp} Uhr)"]
        shown = 0
        for i, pid in enumerate(self.numbered, start=1):
            p = current.get(pid)
            if p is None:
                continue
            shown += 1
            unit = " €/Monat" if p.is_leasing else " €"
            if not p.aktiv:
                lines.append(f"\n{i}. ⏸ <b>{_e(p.name)}</b> (pausiert)\n    Ziel {_eur(p.zielpreis)}{unit}")
                continue
            best = current_best(p, self.state, self.now, rules)
            color, _ = ampel(best, p)
            if best and p.is_leasing:
                rate = (best.get("leasing") or {}).get("rate") or best["vergleichspreis"]
                eff = "" if abs(rate - best["vergleichspreis"]) < 0.01 else f", effektiv {_eur(best['vergleichspreis'])} €"
                now_txt = f"{_eur(rate)} €/Monat{eff} ({_e(best['shop'])})"
            elif best:
                now_txt = f"{_eur(best['vergleichspreis'])} € ({_e(best['shop'])})"
            else:
                now_txt = "kein aktuelles Angebot"
            lines.append(f"\n{i}. {AMPEL_ICON[color]} <b>{_e(p.name)}</b>\n"
                         f"    Ziel {_eur(p.zielpreis)}{unit} · jetzt {now_txt}")
        if not shown:
            return "📋 Keine Produkte eingetragen. Neues Produkt: <code>/neu Name; Zielpreis; Suchbegriffe</code>"
        lines.append("\n✅ Ziel erreicht · 🟡 knapp darüber · 🔴 darüber · ⚪ kein Angebot · ⏸ pausiert")
        return "\n".join(lines)

    def cmd_neu(self, text: str) -> str:
        try:
            entry = append_product(self.path, parse_telegram_command(text), comment="per Telegram hinzugefügt")
        except ConfigError as e:
            return (f"❌ Konnte das Produkt nicht anlegen: {_e(e)}\n"
                    "Beispiel: <code>/neu Bosch PSR 18; 89; PSR 18 LI-2, PSR18</code>")
        self.numbered.append(entry["id"])
        self.batch.changes.append(f"Produkt {entry['id']} hinzugefügt")
        return (f"✅ Neues Produkt <b>{_e(entry['name'])}</b> (Nr. {self._nr(entry['id'])}, "
                f"Ziel {entry['zielpreis']:g} €) wird ab jetzt beobachtet.\n"
                f"Suchbegriffe: {_e(', '.join(entry['suchbegriffe']))}")

    def cmd_loeschen(self, arg: str) -> str:
        p, answer = self.resolve(arg, "/loeschen")
        if p is None:
            return answer
        nr = self._nr(p.id)
        try:
            old = remove_product(self.path, p.id)
        except ConfigError as e:
            return f"❌ Konnte „{_e(p.name)}“ nicht löschen: {_e(e)}"
        self.batch.changes.append(f"Produkt {p.id} gelöscht")
        self.batch.archived.append({"id": p.id, "name": p.name, "geloescht_am": self.now.isoformat(timespec="seconds"),
                                    "eintrag": old})
        return (f"🗑 Gelöscht: <b>{_e(p.name)}</b> (Nr. {nr}, Ziel {_eur(p.zielpreis)} €).\n"
                "Es wird nicht mehr überwacht und verschwindet in wenigen Minuten von der Startseite. "
                "Der Preisverlauf bleibt im Repo archiviert.\n"
                "Hinweis: Die Nummern dahinter rücken auf – /liste zeigt die neue Reihenfolge.")

    def cmd_aktiv(self, arg: str, active: bool) -> str:
        cmd = "/fortsetzen" if active else "/pause"
        p, answer = self.resolve(arg, cmd)
        if p is None:
            return answer
        nr = self._nr(p.id)
        if p.aktiv == active:
            return (f"▶️ <b>{_e(p.name)}</b> wird bereits überwacht." if active
                    else f"⏸ <b>{_e(p.name)}</b> ist bereits pausiert.")
        try:
            set_active(self.path, p.id, active)
        except ConfigError as e:
            return f"❌ Konnte „{_e(p.name)}“ nicht ändern: {_e(e)}"
        self.batch.changes.append(f"Produkt {p.id} {'fortgesetzt' if active else 'pausiert'}")
        if active:
            return f"▶️ <b>{_e(p.name)}</b> (Nr. {nr}) wird wieder überwacht."
        return (f"⏸ <b>{_e(p.name)}</b> (Nr. {nr}) ist pausiert und wird nicht mehr überwacht.\n"
                f"Wieder einschalten: <code>/fortsetzen {nr}</code>")

    def handle(self, text: str) -> str | None:
        """Bearbeitet eine Nachricht und gibt die Antwort zurück (None = keine Antwort)."""
        text = text.strip()
        m = re.match(r"^/([a-zäöüß]+)(?:@\w+)?\s*(.*)$", text, flags=re.I | re.S)
        if not m:
            return None  # normale Nachricht, kein Befehl
        cmd, arg = m.group(1).lower(), m.group(2).strip()
        if cmd == "neu":
            return self.cmd_neu(text)
        if cmd == "liste":
            return self.cmd_liste()
        if cmd in ("loeschen", "löschen", "loschen"):
            return self.cmd_loeschen(arg)
        if cmd == "pause":
            return self.cmd_aktiv(arg, False)
        if cmd == "fortsetzen":
            return self.cmd_aktiv(arg, True)
        if cmd in ("start", "hilfe", "help"):
            return HELP
        return f"Unbekannter Befehl /{_e(cmd)}.\n\n{HELP}"

    def run(self, texts: list[str]) -> Batch:
        for t in texts:
            reply = self.handle(t)
            if reply:
                self.batch.replies.append(reply)
        return self.batch

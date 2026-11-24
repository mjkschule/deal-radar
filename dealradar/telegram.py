"""Telegram: Nachrichten senden und Befehle (/neu, /liste, /loeschen …) abholen.

Benötigt TELEGRAM_BOT_TOKEN und TELEGRAM_CHAT_ID (GitHub Secrets).
Befehle werden NUR aus deinem eigenen Chat (TELEGRAM_CHAT_ID) angenommen.
"""

from __future__ import annotations

import html
import json
import urllib.parse

from .http import Http
from .logic import Alert, _fmt

API = "https://api.telegram.org/bot{token}/{method}"


class TelegramError(Exception):
    pass


class Telegram:
    def __init__(self, http: Http, token: str | None, chat_id: str | None, dry_run: bool = False):
        self.http = http
        self.token = token
        self.chat_id = str(chat_id) if chat_id else None
        self.dry_run = dry_run

    @property
    def configured(self) -> bool:
        return bool(self.token and self.chat_id)

    def _call(self, method: str, params: dict) -> dict:
        url = API.format(token=self.token, method=method)
        body = urllib.parse.urlencode(params).encode()
        try:
            status, text = self.http.request(url, data=body, method="POST",
                                             headers={"Content-Type": "application/x-www-form-urlencoded"})
        except Exception as e:
            raise TelegramError(f"Telegram nicht erreichbar: {e}") from e
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise TelegramError(f"Telegram-Antwort unlesbar (HTTP {status})") from e
        if not data.get("ok"):
            raise TelegramError(f"Telegram meldet Fehler: {data.get('description', status)}")
        return data["result"]

    def send(self, text: str) -> bool:
        """Sendet eine Nachricht. True = wirklich bei Telegram angekommen."""
        if self.dry_run or not self.configured:
            print("---- Telegram (nicht gesendet) ----\n" + text + "\n----")
            return False
        self._call("sendMessage", {"chat_id": self.chat_id, "text": text, "parse_mode": "HTML",
                                   "disable_web_page_preview": "true"})
        return True

    def commands(self, offset: int | None) -> tuple[list[str], int | None]:
        """Liest neue Nachrichten. Gibt (Texte aus deinem Chat, neuer Offset) zurück."""
        if not self.configured or self.dry_run:
            return [], offset
        params = {"timeout": "0", "allowed_updates": '["message"]'}
        if offset:
            params["offset"] = str(offset)
        updates = self._call("getUpdates", params)
        texts = []
        for u in updates:
            offset = max(offset or 0, u["update_id"] + 1)
            msg = u.get("message") or {}
            if str((msg.get("chat") or {}).get("id")) != self.chat_id:
                continue  # fremde Chats ignorieren
            if msg.get("text"):
                texts.append(msg["text"])
        return texts, offset


def _e(s) -> str:
    return html.escape(str(s), quote=False)


def format_alert(a: Alert) -> str:
    o, p = a.offer, a.product
    lines = [f"🔥 <b>{_e(p.name)}</b>"]
    if o.leasing:
        l = o.leasing
        lines.append(f"🚗 Rate: <b>{_fmt(o.price)} €/Monat</b>")
        lines.append("   Sonderzahlung: " + (f"{_fmt(l['sonderzahlung'])} €" if l.get("sonderzahlung") is not None else "unbekannt"))
        lines.append("   Bereitstellung: " + (f"{_fmt(l['bereitstellung'])} €" if l.get("bereitstellung") is not None else "unbekannt"))
        lines.append(f"   Laufzeit: {l.get('monate') or '?'} Monate · {l.get('km') or '?'} km/Jahr")
        if o.effective_rate is not None:
            lines.append(f"   Effektive Rate: <b>{_fmt(o.effective_rate)} €</b>")
    else:
        ship = ("inkl. Versand" if o.shipping == 0 else
                f"+ {_fmt(o.shipping)} € Versand = <b>{_fmt(o.compare_price)} €</b>" if o.shipping is not None else
                "Versand unbekannt")
        lines.append(f"💶 <b>{_fmt(o.price)} €</b> ({ship})")
    lines.append(f"🏪 {_e(o.shop)} · Quelle: {_e(o.source)}")
    lines.append(f"🎯 Zielpreis: {_fmt(p.zielpreis)} €" + (" ✅" if "Zielpreis erreicht" in a.reasons else ""))
    if a.previous_low:
        diff = a.previous_low - o.compare_price
        if diff > 0:
            lines.append(f"📉 {_fmt(diff)} € günstiger als bisheriger Tiefstpreis ({_fmt(a.previous_low)} €, "
                         f"−{diff / a.previous_low * 100:.0f} %)")
        else:
            lines.append(f"📊 Bisheriger Tiefstpreis: {_fmt(a.previous_low)} €")
    else:
        lines.append("📊 Erster vom Radar gesehener Preis")
    if o.hints:
        lines.append("⚠️ " + _e(" · ".join(o.hints)))
    lines.append(f"🔗 <a href=\"{html.escape(o.url)}\">Zum Angebot</a>")
    lines.append(f"<i>{_e(o.title[:180])}</i>")
    return "\n".join(lines)

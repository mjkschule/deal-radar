"""Höflicher HTTP-Abruf: eigener User-Agent, robots.txt-Prüfung, Pausen, Timeouts.

Es werden KEINE Bot-Schutz-Maßnahmen umgangen: Antwortet eine Seite mit 403/429
oder einer Captcha-Seite, wird das als Fehler gemeldet und nicht erneut versucht.
"""

from __future__ import annotations

import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

from .robots import Robots


class FetchError(Exception):
    """Abruf fehlgeschlagen (Netzwerk, HTTP-Fehler, ...)."""


class RobotsBlocked(FetchError):
    """robots.txt erlaubt den Abruf nicht."""


class Http:
    def __init__(self, user_agent: str, pause: float = 3.0, timeout: float = 25.0,
                 robots_exempt_hosts: tuple[str, ...] = ("api.ebay.com", "api.telegram.org")):
        self.user_agent = user_agent
        self.pause = pause
        self.timeout = timeout
        self.robots_exempt_hosts = robots_exempt_hosts
        self._robots: dict[str, Robots] = {}
        self._last: dict[str, float] = {}
        self.request_count = 0

    def _wait(self, host: str) -> None:
        last = self._last.get(host)
        if last is not None:
            delay = self.pause - (time.monotonic() - last)
            if delay > 0:
                time.sleep(delay)

    def request(self, url: str, data: bytes | None = None, headers: dict | None = None,
                method: str | None = None) -> tuple[int, str]:
        """Roher Abruf ohne robots-Prüfung. Gibt (Statuscode, Text) zurück."""
        host = urlparse(url).netloc
        self._wait(host)
        h = {"User-Agent": self.user_agent, "Accept-Language": "de-DE,de;q=0.9"}
        h.update(headers or {})
        req = urllib.request.Request(url, data=data, headers=h, method=method)
        self.request_count += 1
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                status, body = r.status, r.read()
                charset = r.headers.get_content_charset() or "utf-8"
        except urllib.error.HTTPError as e:
            status, body = e.code, e.read() or b""
            charset = e.headers.get_content_charset() if e.headers else None
            charset = charset or "utf-8"
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            reason = getattr(e, "reason", e)
            raise FetchError(f"{host} nicht erreichbar ({reason})") from e
        finally:
            self._last[host] = time.monotonic()
        return status, body.decode(charset, "replace")

    def robots_for(self, url: str) -> Robots:
        p = urlparse(url)
        host = p.netloc
        if host not in self._robots:
            try:
                status, text = self.request(f"{p.scheme}://{host}/robots.txt")
            except FetchError:
                status, text = 599, ""
            if status in (401, 403) or status >= 500:
                # RFC 9309: nicht lesbar -> nichts abrufen
                self._robots[host] = Robots(disallow_all=True)
            elif status >= 400:
                self._robots[host] = Robots(allow_all=True)  # keine robots.txt vorhanden
            else:
                self._robots[host] = Robots(text)
        return self._robots[host]

    def allowed(self, url: str) -> bool:
        if urlparse(url).netloc in self.robots_exempt_hosts:
            return True
        return self.robots_for(url).can_fetch(self.user_agent, url)

    def get(self, url: str, headers: dict | None = None) -> str:
        """GET mit robots.txt-Prüfung. Wirft FetchError/RobotsBlocked."""
        if not self.allowed(url):
            raise RobotsBlocked(f"robots.txt verbietet den Abruf von {url}")
        status, text = self.request(url, headers=headers)
        if status == 429:
            raise FetchError(f"{urlparse(url).netloc}: zu viele Anfragen (429) – nächster Versuch beim nächsten Lauf")
        if status >= 400:
            raise FetchError(f"HTTP {status} bei {url}")
        low = text[:5000].lower()
        if "captcha" in low and ("robot" in low or "verify" in low or "bestätigen" in low):
            raise FetchError(f"{urlparse(url).netloc}: Bot-Schutz/Captcha – Seite wird nicht abgerufen")
        return text

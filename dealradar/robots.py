"""Kleiner robots.txt-Prüfer mit Unterstützung für * und $ (wie Google, RFC 9309).

Pythons eingebauter urllib.robotparser versteht keine Platzhalter wie
"Disallow: /*?sort=" – deshalb diese eigene, kleine Umsetzung.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse


class Robots:
    def __init__(self, text: str = "", allow_all: bool = False, disallow_all: bool = False):
        self.allow_all = allow_all
        self.disallow_all = disallow_all
        self.groups: list[tuple[list[str], list[tuple[bool, str]]]] = []
        if text:
            self._parse(text)

    def _parse(self, text: str) -> None:
        agents: list[str] = []
        rules: list[tuple[bool, str]] = []
        last_was_agent = False
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            key, _, value = line.partition(":")
            key, value = key.strip().lower(), value.strip()
            if key == "user-agent":
                if not last_was_agent and (agents or rules):
                    self.groups.append((agents, rules))
                    agents, rules = [], []
                agents.append(value.lower())
                last_was_agent = True
            elif key in ("allow", "disallow"):
                last_was_agent = False
                if agents and value:
                    rules.append((key == "allow", value))
            else:
                last_was_agent = False
        if agents:
            self.groups.append((agents, rules))

    def _rules_for(self, user_agent: str) -> list[tuple[bool, str]]:
        token = re.split(r"[/\s]", user_agent.strip(), maxsplit=1)[0].lower()
        specific = [r for a, r in self.groups if any(x != "*" and x in token for x in a)]
        if specific:
            return [rule for rs in specific for rule in rs]
        return [rule for a, r in self.groups if "*" in a for rule in r]

    @staticmethod
    def _to_regex(pattern: str) -> re.Pattern:
        anchored = pattern.endswith("$")
        if anchored:
            pattern = pattern[:-1]
        rx = "".join(".*" if ch == "*" else re.escape(ch) for ch in pattern)
        return re.compile(rx + ("$" if anchored else ""))

    def can_fetch(self, user_agent: str, url: str) -> bool:
        if self.disallow_all:
            return False
        if self.allow_all:
            return True
        p = urlparse(url)
        path = (p.path or "/") + (f"?{p.query}" if p.query else "")
        best_len, best_allow = -1, True
        for allow, pattern in self._rules_for(user_agent):
            if self._to_regex(pattern).match(path):
                length = len(pattern)
                # Längste Regel gewinnt, bei Gleichstand "Allow"
                if length > best_len or (length == best_len and allow):
                    best_len, best_allow = length, allow
        return best_allow

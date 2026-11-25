"""Startseite als installierbare App (PWA): Manifest, Service Worker, App-Symbole.

Wird bei jedem Lauf nach docs/ geschrieben. Die Symbole (ein stilisiertes Radar) werden ohne
Zusatzpakete erzeugt – PNG ist nur ein zlib-komprimierter Pixelstrom mit etwas Kopf.
"""

from __future__ import annotations

import json
import math
import struct
import zlib
from pathlib import Path

MANIFEST = {
    "name": "Deal-Radar",
    "short_name": "Deal-Radar",
    "description": "Persönliches Preis-Radar: Deals, Zielpreise und Preisverlauf",
    "lang": "de",
    "start_url": "./",
    "scope": "./",
    "display": "standalone",
    "background_color": "#0f1218",
    "theme_color": "#2f5bea",
    "icons": [
        {"src": "icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
        {"src": "icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
        {"src": "icon-512-maskable.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
    ],
}

# Netz zuerst (immer aktuelle Preise), ohne Netz die zuletzt gesehene Fassung.
SERVICE_WORKER = """// Deal-Radar Service Worker: Netz zuerst, offline die zuletzt geladene Seite.
const CACHE = "deal-radar-v1";
const SHELL = ["./", "manifest.webmanifest", "icon-192.png"];
self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});
self.addEventListener("fetch", (e) => {
  if (e.request.method !== "GET" || new URL(e.request.url).origin !== location.origin) return;
  e.respondWith(fetch(e.request).then((res) => {
    if (res.ok) { const copy = res.clone(); caches.open(CACHE).then((c) => c.put(e.request, copy)); }
    return res;
  }).catch(() => caches.match(e.request).then((r) => r || caches.match("./"))));
});
"""

BLUE = (47, 91, 234)
WHITE = (255, 255, 255)
GREEN = (18, 161, 80)


def _png(width: int, height: int, rows: list[bytes]) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + r for r in rows)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def icon(size: int, maskable: bool = False) -> bytes:
    """Blaues Quadrat (abgerundet, außer maskable), weiße Radarringe, Zeiger und grüner Punkt."""
    c = (size - 1) / 2
    radius = size * (0.22 if not maskable else 0)
    scale = 0.78 if maskable else 1.0  # maskable: Motiv in der sicheren Zone halten
    ring_w = size * 0.035 * scale
    rings = [size * f * scale for f in (0.14, 0.26, 0.38)]
    sweep = math.radians(-45)
    blip = (c + math.cos(math.radians(-35)) * rings[1], c + math.sin(math.radians(-35)) * rings[1])
    rows = []
    for y in range(size):
        row = bytearray()
        for x in range(size):
            # abgerundete Ecken (außerhalb = transparent)
            qx, qy = min(x, size - 1 - x), min(y, size - 1 - y)
            if radius and qx < radius and qy < radius and math.hypot(radius - qx, radius - qy) > radius:
                row += b"\x00\x00\x00\x00"
                continue
            dx, dy = x - c, y - c
            d = math.hypot(dx, dy)
            col = BLUE
            if any(abs(d - r) < ring_w / 2 for r in rings) or d < ring_w:
                col = WHITE
            ang = math.atan2(dy, dx)
            if d < rings[2] and abs(math.sin(ang - sweep)) * d < ring_w / 2 and math.cos(ang - sweep) > 0:
                col = WHITE
            if math.hypot(x - blip[0], y - blip[1]) < size * 0.055 * scale:
                col = GREEN
            row += bytes(col) + b"\xff"
        rows.append(bytes(row))
    return _png(size, size, rows)


def write_assets(docs_dir: Path) -> None:
    docs_dir.mkdir(parents=True, exist_ok=True)
    (docs_dir / "manifest.webmanifest").write_text(json.dumps(MANIFEST, ensure_ascii=False, indent=1), encoding="utf-8")
    (docs_dir / "sw.js").write_text(SERVICE_WORKER, encoding="utf-8")
    for name, size, mask in (("icon-192.png", 192, False), ("icon-512.png", 512, False),
                             ("icon-512-maskable.png", 512, True)):
        path = docs_dir / name
        if not path.exists():  # Symbole ändern sich nicht – nur einmal erzeugen
            path.write_bytes(icon(size, mask))

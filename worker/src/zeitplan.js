// Zeitplan – gleiche Regeln wie dealradar/zeitplan.py (Tests prüfen beide).
//   aktion      zwischen zeitplan.aktion_von und aktion_bis: alle aktion_minuten (30)
//   normal      sonst alle normal_minuten (120)
//   wunschliste nach dem Enddatum (nach_ende: wunschliste): 1x täglich um wunschliste_uhrzeit
//   aus         nach dem Enddatum mit nach_ende: aus
// Der Worker tickt um Minute 17 und 47 (UTC) und startet einen Lauf, wenn due() true ist.

import { localParts } from "./ruhe.js";

export const DEFAULTS = {
  normal_minuten: 120, aktion_minuten: 30, aktion_von: "2026-11-27T00:00",
  aktion_bis: "2026-11-30T23:59", wunschliste_uhrzeit: "08:00",
};

export const settings = (cfg) => ({ ...DEFAULTS, ...(cfg.zeitplan || {}) });

/** Abstand Ortszeit − UTC in Minuten zum Zeitpunkt `date`. */
function offsetMinutes(date, tz) {
  const p = Object.fromEntries(new Intl.DateTimeFormat("en-US", {
    timeZone: tz, hourCycle: "h23", year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit",
  }).formatToParts(date).map((x) => [x.type, x.value]));
  const asUtc = Date.UTC(+p.year, +p.month - 1, +p.day, +p.hour, +p.minute, +p.second);
  return Math.round((asUtc - date.getTime()) / 60000);
}

/** "2026-11-27T00:00" (Ortszeit) -> Date */
export function localDate(raw, tz = "Europe/Berlin") {
  const s = String(raw).trim();
  if (/[zZ]|[+-]\d\d:\d\d$/.test(s)) return new Date(s);
  const [d, t = "00:00"] = s.split("T");
  const [y, m, day] = d.split("-").map(Number);
  const [hh, mm] = t.split(":").map(Number);
  const guess = new Date(Date.UTC(y, m - 1, day, hh, mm));
  return new Date(guess.getTime() - offsetMinutes(guess, tz) * 60000);
}

/** Enddatum (inkl. der angegebenen Minute) oder null bei "nie". */
export function endDate(cfg) {
  const raw = String(cfg.enddatum ?? "2026-11-30T23:59").trim();
  if (["nie", "never", "none", ""].includes(raw.toLowerCase())) return null;
  return new Date(localDate(raw, cfg.zeitzone).getTime() + 59000);
}

export function mode(cfg, now) {
  const end = endDate(cfg);
  if (end && now > end) return String(cfg.nach_ende ?? "wunschliste").toLowerCase() === "aus" ? "aus" : "wunschliste";
  const z = settings(cfg);
  const from = localDate(z.aktion_von, cfg.zeitzone);
  const to = new Date(localDate(z.aktion_bis, cfg.zeitzone).getTime() + 59000);
  return now >= from && now <= to ? "aktion" : "normal";
}

export function intervalMinutes(cfg, now) {
  const z = settings(cfg);
  return { aktion: Number(z.aktion_minuten), normal: Number(z.normal_minuten), wunschliste: 1440, aus: null }[mode(cfg, now)];
}

/** Ist zu diesem Takt (Minute 17 oder 47 UTC) ein Lauf fällig? */
export function due(cfg, tick) {
  const m = mode(cfg, tick);
  if (m === "aus") return false;
  if (m === "wunschliste") {
    const hh = Number(String(settings(cfg).wunschliste_uhrzeit).split(":")[0]);
    return localParts(tick, cfg.zeitzone || "Europe/Berlin").hour === hh && tick.getUTCMinutes() === 17;
  }
  const minuteOfDay = tick.getUTCHours() * 60 + tick.getUTCMinutes() - 17; // Takte: :17 und :47
  return minuteOfDay >= 0 && minuteOfDay % intervalMinutes(cfg, tick) === 0;
}

/** Nächster planmäßiger Lauf ab `now` (oder null). */
export function nextRun(cfg, now) {
  const t = new Date(now);
  t.setUTCSeconds(0, 0);
  const step = ((17 - t.getUTCMinutes()) % 30 + 30) % 30 || 30;
  t.setTime(t.getTime() + step * 60000);
  for (let i = 0; i < 144; i++) {
    if (due(cfg, t)) return new Date(t);
    t.setTime(t.getTime() + 30 * 60000);
  }
  return null;
}

export function describe(cfg, now) {
  const m = mode(cfg, now);
  const iv = intervalMinutes(cfg, now);
  if (m === "aktion") return `Aktionszeit: alle ${iv} Minuten`;
  if (m === "normal") return `alle ${iv / 60} Stunden`;
  if (m === "wunschliste") return `Wunschlisten-Modus: 1× täglich um ${settings(cfg).wunschliste_uhrzeit} Uhr`;
  return "beendet";
}

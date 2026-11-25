// Ruhezeiten und Einstellungen aus config.yaml – gleiche Regeln wie dealradar/meldungen.py.
// "tage" gilt für den BEGINN einer Zeitspanne; "22:00–07:00" reicht in den nächsten Morgen.

import { parse } from "yaml";

const TAGE = ["mo", "di", "mi", "do", "fr", "sa", "so"];

export const DEFAULTS = {
  zeitzone: "Europe/Berlin",
  meldungen: { sofort_ab_score: 85, uebersicht_uhrzeit: "19:00" },
  ruhezeiten: {
    aktiv: true,
    zeiten: [
      { tage: "Mo-Fr", von: "07:30", bis: "14:00" },
      { tage: "Mo-So", von: "22:00", bis: "07:00" },
    ],
    ausnahme_ab_score: 90,
    ausnahme_unter_ziel: 0.15,
  },
};

/** config.yaml lesen; fehlende Werte kommen aus DEFAULTS (wie _deep_merge in Python). */
export function readConfig(text) {
  let raw = {};
  try {
    raw = parse(text || "") || {};
  } catch {
    raw = {};
  }
  return {
    ...DEFAULTS,
    ...raw,
    meldungen: { ...DEFAULTS.meldungen, ...(raw.meldungen || {}) },
    ruhezeiten: { ...DEFAULTS.ruhezeiten, ...(raw.ruhezeiten || {}) },
    zeitplan: { ...(raw.zeitplan || {}) },
  };
}

export function days(spec) {
  const s = String(spec ?? "").trim().toLowerCase();
  if (!s || ["taeglich", "täglich", "alle"].includes(s)) return new Set([0, 1, 2, 3, 4, 5, 6]);
  const out = new Set();
  for (const part of s.replace(/\s/g, "").split(",")) {
    if (!part) continue;
    if (part.includes("-")) {
      const [a, b] = part.split("-");
      let k = TAGE.indexOf(a.slice(0, 2));
      const j = TAGE.indexOf(b.slice(0, 2));
      for (;;) {
        out.add(k);
        if (k === j) break;
        k = (k + 1) % 7;
      }
    } else {
      out.add(TAGE.indexOf(part.slice(0, 2)));
    }
  }
  return out;
}

const minutes = (hhmm) => {
  const [h, m] = String(hhmm).split(":").map(Number);
  return h * 60 + m;
};

/** Wochentag (0 = Montag), Minute des Tages und Datum in der Zeitzone. */
export function localParts(date, tz = "Europe/Berlin") {
  const parts = Object.fromEntries(new Intl.DateTimeFormat("en-GB", {
    timeZone: tz, weekday: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
    year: "numeric", month: "2-digit", day: "2-digit",
  }).formatToParts(date).map((p) => [p.type, p.value]));
  const weekday = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].indexOf(parts.weekday);
  return {
    weekday,
    minute: Number(parts.hour) * 60 + Number(parts.minute),
    hour: Number(parts.hour),
    date: `${parts.year}-${parts.month}-${parts.day}`,
  };
}

export function quietNow(cfg, date) {
  const rz = cfg.ruhezeiten || {};
  if (rz.aktiv === false) return false;
  const { weekday, minute } = localParts(date, cfg.zeitzone || "Europe/Berlin");
  for (const z of rz.zeiten || []) {
    const start = minutes(z.von);
    const end = minutes(z.bis);
    const d = days(z.tage ?? "Mo-So");
    if (start < end) {
      if (d.has(weekday) && minute >= start && minute < end) return true;
    } else {
      if (d.has(weekday) && minute >= start) return true;
      if (d.has((weekday + 6) % 7) && minute < end) return true;
    }
  }
  return false;
}

/** Kurztext der Ruhezeiten für /ruhe und /status. */
export function describe(cfg) {
  const rz = cfg.ruhezeiten || {};
  const spans = (rz.zeiten || []).map((z) => `${z.tage} ${z.von}–${z.bis}`).join(", ");
  return `${spans} (Ausnahmen: Score ≥ ${rz.ausnahme_ab_score}, Ziel um mehr als ` +
    `${Math.round((rz.ausnahme_unter_ziel ?? 0.15) * 100)} % unterboten)`;
}

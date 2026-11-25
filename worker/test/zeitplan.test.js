// Zeitplan und /ende – gleiche Fälle wie tests/test_phase5.py
import assert from "node:assert/strict";
import { test } from "node:test";

import { handleUpdate, parseEnd } from "../src/bot.js";
import { readConfig } from "../src/ruhe.js";
import { due, mode, nextRun } from "../src/zeitplan.js";
import { CONFIG, deps, msg } from "./helpers.js";

const CFG = readConfig(CONFIG);
const utc = (s) => new Date(s + "Z");

// [Takt UTC, Modus, fällig?]
const CASES = [
  ["2026-11-25T12:17", "normal", true],
  ["2026-11-25T12:47", "normal", false],
  ["2026-11-25T13:17", "normal", false],
  ["2026-11-26T23:47", "aktion", true],        // 00:47 Berlin am 27.11. = schon Aktionszeit
  ["2026-11-27T10:47", "aktion", true],
  ["2026-11-30T22:47", "aktion", true],        // 23:47 Berlin am Cyber Monday
  ["2026-11-30T23:17", "wunschliste", false],  // 00:17 Berlin am 1.12.
  ["2026-12-01T07:17", "wunschliste", true],   // 08:17 Berlin
  ["2026-12-01T07:47", "wunschliste", false],
];

test("Zeitplan-Modi und Takte wie in Python", () => {
  for (const [t, m, d] of CASES) {
    assert.equal(mode(CFG, utc(t)), m, t);
    assert.equal(due(CFG, utc(t)), d, t);
  }
  assert.equal(nextRun(CFG, utc("2026-11-30T23:05")).toISOString(), "2026-12-01T07:17:00.000Z");
  assert.equal(mode({ ...CFG, enddatum: "nie" }, utc("2027-01-10T10:00")), "normal");
  assert.equal(mode({ ...CFG, nach_ende: "aus" }, utc("2026-12-02T10:00")), "aus");
  assert.equal(nextRun({ ...CFG, nach_ende: "aus" }, utc("2026-12-02T10:00")), null);
});

test("/ende versteht Datumsformate", () => {
  const now = new Date("2026-11-25T12:00:00+01:00");
  assert.equal(parseEnd("24.12.2026", now), "2026-12-24T23:59");
  assert.equal(parseEnd("24.12.", now), "2026-12-24T23:59");
  assert.equal(parseEnd("1.12.26 18:00", now), "2026-12-01T18:00");
  assert.equal(parseEnd("2026-12-24", now), "2026-12-24T23:59");
  assert.equal(parseEnd("nie", now), "nie");
  assert.equal(parseEnd("31.02.2026", now), null);
  assert.equal(parseEnd("morgen", now), null);
});

test("/ende ändert nur die Zeile enddatum in config.yaml", async () => {
  const d = deps();
  await handleUpdate(msg("/ende 24.12.2026"), d);
  const t = d.gh.store.get("config.yaml").text;
  assert.match(t, /^enddatum: "2026-12-24T23:59"$/m);
  assert.equal(t.replace('enddatum: "2026-12-24T23:59"', `enddatum: "${readConfig(CONFIG).enddatum}"`), CONFIG);
  assert.match(d.tg.sent[0].text, /Enddatum gesetzt: <b>24\.12\., 23:59 Uhr/);
  await handleUpdate(msg("/ende nie"), d);
  assert.match(d.gh.store.get("config.yaml").text, /^enddatum: "nie"$/m);
  assert.match(d.tg.sent[1].text, /Kein Enddatum mehr/);
  await handleUpdate(msg("/ende 1.1.2020"), d);
  assert.match(d.tg.sent[2].text, /Vergangenheit/);
  await handleUpdate(msg("/ende"), d);
  assert.match(d.tg.sent[3].text, /läuft immer weiter/);
  await handleUpdate(msg("/status"), d);
  assert.match(d.tg.sent[4].text, /Takt: alle 2 Stunden/);
  assert.match(d.tg.sent[4].text, /Läuft ohne Enddatum/);
});

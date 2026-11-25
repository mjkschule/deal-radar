// Abgelaufene Angebote ausblenden: Link der Startseite (/start x_…), /weg, Rückgängig.
import assert from "node:assert/strict";
import test from "node:test";

import { handleUpdate } from "../src/bot.js";
import { BOTDATA, click, deps, msg } from "./helpers.js";

const bot = JSON.parse(BOTDATA);
bot.produkte["makita-dhp490rfx3"].name = "Makita DHP490RFX3";
bot.produkte["makita-dhp490rfx3"].angebote = [
  { h: "0123456789", shop: "BAUR", preis: 184, url: "https://www.mydealz.de/deals/makita-1", titel: "Makita Set" },
  { h: "abcdefabcd", shop: "OBI", preis: 199, url: "https://www.mydealz.de/deals/makita-2", titel: "Makita bei OBI" },
];
const files = { "docs/bot.json": JSON.stringify(bot) };

test("Link der Startseite blendet das Angebot aus und startet einen Lauf", async () => {
  const d = deps(files);
  await handleUpdate(msg("/start x_0123456789"), d);
  const ign = JSON.parse(d.gh.store.get("data/ignoriert.json").text);
  assert.deepEqual([ign["0123456789"].produkt, ign["0123456789"].quelle], ["makita-dhp490rfx3", "startseite"]);
  assert.equal(ign["0123456789"].url, "https://www.mydealz.de/deals/makita-1");
  assert.match(d.tg.sent[0].text, /🚫 <b>Makita DHP490RFX3<\/b>: BAUR · 184 € ist ausgeblendet/);
  assert.equal(d.tg.sent[0].buttons[0][0].callback_data, "u:0123456789");
  assert.deepEqual(d.gh.dispatches, ["befehl"]);
  // zweimal tippen: kein zweiter Commit, kein zweiter Lauf
  await handleUpdate(msg("/start x_0123456789"), d);
  assert.match(d.tg.sent[1].text, /schon ausgeblendet/);
  assert.equal(d.gh.dispatches.length, 1);
});

test("Rückgängig blendet wieder ein", async () => {
  const d = deps({ ...files, "data/ignoriert.json": JSON.stringify({ "0123456789": { produkt: "x" }, ffffffffff: {} }) });
  await handleUpdate(click("u:0123456789"), d);
  assert.deepEqual(Object.keys(JSON.parse(d.gh.store.get("data/ignoriert.json").text)), ["ffffffffff"]);
  assert.match(d.tg.edited[0].text, /wieder gezeigt/);
});

test("/weg zeigt die Angebote als Buttons, Antippen blendet aus", async () => {
  const d = deps(files);
  await handleUpdate(msg("/weg 1"), d);
  const { text, buttons } = d.tg.sent[0];
  assert.match(text, /Aktuelle Angebote für <b>Makita/);
  assert.deepEqual(buttons.map((r) => r[0].callback_data), ["w:0123456789", "w:abcdefabcd", "x"]);
  assert.equal(buttons[1][0].text, "🚫 OBI · 199 €");
  await handleUpdate(click("w:abcdefabcd"), d);
  assert.ok(JSON.parse(d.gh.store.get("data/ignoriert.json").text).abcdefabcd);
  assert.match(d.tg.edited[0].text, /OBI · 199 € ist ausgeblendet/);
});

test("/weg ohne Angebot, /start ohne Zusatz zeigt die Hilfe, fremder Chat wird ignoriert", async () => {
  const d = deps(files);
  await handleUpdate(msg("/weg 2"), d);
  assert.match(d.tg.sent[0].text, /kein angezeigtes Angebot/);
  await handleUpdate(msg("/start"), d);
  assert.match(d.tg.sent[1].text, /Deal-Radar – Befehle/);
  assert.equal(await handleUpdate(msg("/start x_0123456789", 999), d), "ignoriert");
  assert.equal(d.gh.store.get("data/ignoriert.json"), undefined);
});

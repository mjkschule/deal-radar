// 💥 Rabattknaller im Bot: /knaller, eigener Abschnitt in der 19-Uhr-Übersicht, Ausblenden per Link.
import assert from "node:assert/strict";
import test from "node:test";

import { handleUpdate } from "../src/bot.js";
import { buildOverview } from "../src/daily.js";
import { parseProducts } from "../src/yamledit.js";
import { BOTDATA, FIXTURE, deps, msg } from "./helpers.js";

const bot = JSON.parse(BOTDATA);
bot.rabattknaller = [
  { h: "1111111111", kategorie_name: "Airfryer", title: "Ninja Dual Zone AF300EU", vergleichspreis: 99, shop: "Amazon",
    url: "https://www.mydealz.de/deals/a-1", rabatt: 50, bezug: 199, hitze: null },
  { h: "2222222222", kategorie_name: "Computer-Monitor", title: "LG 27GR75Q", vergleichspreis: 199, shop: "OTTO",
    url: "https://www.mydealz.de/deals/b-2", rabatt: null, bezug: null, hitze: 620 },
];
bot.warteschlange = [
  { id: "k1", art: "uebersicht", typ: "knaller", name: "Monitor: LG 27GR75Q", preis: 199, shop: "OTTO", url: "https://x/k", rabatt: 33, hitze: 620 },
  { id: "d1", art: "uebersicht", name: "Epson ET-2922", preis: 150, shop: "Amazon", url: "https://x/d", score: 70 },
];
const files = { "docs/bot.json": JSON.stringify(bot) };

test("/knaller listet Rabatt und Hitze", async () => {
  const d = deps(files);
  await handleUpdate(msg("/knaller"), d);
  const t = d.tg.sent[0].text;
  assert.match(t, /💥 <b>Rabattknaller<\/b> \(2\)/);
  assert.match(t, /99 € bei Amazon · −50 % ggü\. Preisvergleich 199 €/);
  assert.match(t, /🔥 620°/);
});

test("Übersicht trennt Rabattknaller von den übrigen Deals", async () => {
  const d = deps(files);
  const { text, ids } = await buildOverview(d, bot, parseProducts(FIXTURE), { meldungen: {} }, d.now);
  assert.match(text, /💥 <b>Rabattknaller<\/b> \(nicht auf deiner Liste\)\n• Monitor: LG 27GR75Q – 199 € bei OTTO · −33 % · 🔥 620°/);
  assert.match(text, /🔥 <b>Weitere gute Deals[^\n]*\n• Epson ET-2922/);
  assert.deepEqual(ids.sort(), ["d1", "k1"]);
});

test("Link „🚫 Abgelaufen?“ funktioniert auch für Rabattknaller", async () => {
  const d = deps(files);
  await handleUpdate(msg("/start x_1111111111"), d);
  const ign = JSON.parse(d.gh.store.get("data/ignoriert.json").text);
  assert.equal(ign["1111111111"].produkt, "knaller");
  assert.match(d.tg.sent[0].text, /Rabattknaller Airfryer<\/b>: Amazon · 99 €/);
});

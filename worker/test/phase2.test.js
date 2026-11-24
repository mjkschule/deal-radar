// Phase 2: Ruhezeiten (gleiche Fälle wie tests/test_meldungen.py), Produkt per Link,
// Buttons unter Meldungen, /ruhe, Nachlieferung und Tagesübersicht.
import assert from "node:assert/strict";
import { test } from "node:test";

import { handleUpdate } from "../src/bot.js";
import { hourly } from "../src/daily.js";
import { days, quietNow, readConfig } from "../src/ruhe.js";
import {
  deriveTerms, extractProduct, LinkError, parseRobots, readShopPage, robotsAllows, suggestTarget, USER_AGENT,
} from "../src/shoplink.js";
import { parseProducts } from "../src/yamledit.js";
import { BOTDATA, click, CONFIG, deps, fakeFetch, msg } from "./helpers.js";

const CFG = readConfig(CONFIG);
const at = (day, hhmm) => new Date(`2026-11-${String(day).padStart(2, "0")}T${hhmm}:00+01:00`);

// ---------- Ruhezeiten ----------

const QUIET_CASES = [
  [23, "07:29", false], [23, "07:30", true], [23, "13:59", true], [23, "14:00", false],
  [23, "21:59", false], [23, "22:00", true], [24, "03:00", true], [24, "06:59", true],
  [24, "07:00", false], [28, "10:00", false], [28, "23:30", true], [30, "02:00", true],
];

test("Ruhezeiten wie in Python", () => {
  for (const [day, hhmm, quiet] of QUIET_CASES) assert.equal(quietNow(CFG, at(day, hhmm)), quiet, `${day}. ${hhmm}`);
  assert.equal(quietNow({ ...CFG, ruhezeiten: { ...CFG.ruhezeiten, aktiv: false } }, at(23, "23:00")), false);
  assert.deepEqual([...days("Fr-Mo")].sort(), [0, 4, 5, 6]);
});

// ---------- Shop-Link ----------

const PAGE = `<html><head><script type="application/ld+json">
{"@context":"https://schema.org","@graph":[{"@type":"WebPage"},{"@type":"Product","name":"Philips Airfryer 5000 Series HD9255/90 &amp; Rezept-App",
"gtin13":"8710103999999","brand":{"@type":"Brand","name":"Philips"},
"offers":{"@type":"AggregateOffer","lowPrice":"89.99","priceCurrency":"EUR","availability":"https://schema.org/InStock"}}]}
</script></head></html>`;

test("Produktdaten aus JSON-LD und Meta-Tags", () => {
  const p = extractProduct(PAGE);
  assert.equal(p.name, "Philips Airfryer 5000 Series HD9255/90 & Rezept-App");
  assert.equal(p.ean, "8710103999999");
  assert.equal(p.price, 89.99);
  const meta = extractProduct('<meta property="og:title" content="Ninja AF100EU"><meta property="product:price:amount" content="79,90">');
  assert.deepEqual([meta.name, meta.price, meta.ean], ["Ninja AF100EU", 79.9, null]);
  const micro = extractProduct('<meta itemprop="name" content="Lenovo L24-4e (23.8&quot;)"><meta itemprop="gtin" content="198156534620">' +
    '<meta itemprop="price" content="73.78"><meta itemprop="price" content="109.00">');
  assert.deepEqual([micro.name, micro.price, micro.ean], ['Lenovo L24-4e (23.8")', 73.78, "198156534620"]);
  assert.equal(extractProduct("<html>nix</html>"), null);
});

test("Zielpreis-Vorschlag und Suchbegriffe", () => {
  assert.equal(suggestTarget(89.99), 80);
  assert.equal(suggestTarget(15), 13.5);
  assert.deepEqual(deriveTerms("Philips Airfryer 5000 Series HD9255/90"), ["HD9255"]);
  assert.deepEqual(deriveTerms("Makita DHP490RFX3 Akku-Schlagbohrschrauber 18V"), ["DHP490RFX3"]);
  assert.deepEqual(deriveTerms("Tolle Kaffeemaschine aus Glas"), ["Tolle Kaffeemaschine aus Glas"]);
  assert.deepEqual(deriveTerms("Logitech B110 Silent Maus"), ["Logitech B110"]);
  assert.deepEqual(deriveTerms("Lenovo L24-4e Full HD LED-Monitor 60,5 cm"), ["L24-4e"]);
});

test("robots.txt wird beachtet", async () => {
  const g = parseRobots("User-agent: *\nDisallow: /p/\nAllow: /p/ok\n\nUser-agent: GPTBot\nDisallow: /");
  assert.equal(robotsAllows(g, USER_AGENT, "https://s.de/p/123"), false);
  assert.equal(robotsAllows(g, USER_AGENT, "https://s.de/p/ok"), true);
  assert.equal(robotsAllows(g, USER_AGENT, "https://s.de/x"), true);
  const f = fakeFetch({ "https://s.de/robots.txt": [200, "User-agent: *\nDisallow: /p/"] });
  await assert.rejects(readShopPage("https://s.de/p/1", f), /erlaubt laut robots.txt/);
  assert.deepEqual(f.calls, ["https://s.de/robots.txt"]); // Produktseite wurde NICHT abgerufen
  const g403 = fakeFetch({ "https://s.de/robots.txt": [200, ""], "https://s.de/x": [403, "Access denied"] });
  await assert.rejects(readShopPage("https://s.de/x", g403), (e) => e instanceof LinkError && /Bot-Schutz/.test(e.message));
});

const LINK = "https://shop.example/airfryer-hd9255";
const ROUTES = { "https://shop.example/robots.txt": [404, ""], [LINK]: [200, PAGE] };

test("Link schicken → Vorschau mit Buttons → Übernehmen", async () => {
  const d = deps({}, { routes: ROUTES });
  await handleUpdate(msg(`Schau mal ${LINK}`), d);
  const preview = d.tg.sent[0];
  assert.match(preview.text, /Philips Airfryer 5000/);
  assert.match(preview.text, /89,99 €/);
  assert.match(preview.text, /Vorschlag Zielpreis: <b>80 €/);
  assert.match(preview.text, /EAN 8710103999999/);
  const [take, change, cancel] = preview.buttons.map((r) => r[0].callback_data);
  assert.match(take, /^a:[0-9a-f]{10}$/);
  assert.equal(change, take.replace("a:", "c:"));
  assert.equal(cancel, "x");

  await handleUpdate(click(take), d);
  assert.match(d.tg.edited[0].text, /Neues Produkt <b>Philips Airfryer 5000 Series HD9255\/90 &amp; Rezept-App<\/b> \(Nr\. 9, Ziel 80 €\)/);
  const p = parseProducts(d.gh.store.get("products.yaml").text).at(-1);
  assert.deepEqual([p.zielpreis, p.ean, p.shop_urls, p.suchbegriffe], [80, "8710103999999", [LINK], ["HD9255"]]);
  assert.deepEqual(d.gh.dispatches, ["befehl"]);

  // gleicher Link noch einmal -> schon vorhanden
  await handleUpdate(msg(LINK), d);
  assert.match(d.tg.sent.at(-1).text, /Das überwache ich schon: Nr\. 9/);
});

test("Link → Zielpreis ändern → Zahl schicken", async () => {
  const d = deps({}, { routes: ROUTES });
  await handleUpdate(msg(`/neu ${LINK}`), d);
  const change = d.tg.sent[0].buttons[1][0].callback_data;
  await handleUpdate(click(change), d);
  assert.match(d.tg.edited[0].text, /Schick mir jetzt den Zielpreis/);
  await handleUpdate(msg("72,50"), d);
  assert.match(d.tg.sent.at(-1).text, /Ziel 72,50 €/);
  assert.deepEqual(d.tg.markups.at(-1), { id: 77, buttons: [] }); // Abbrechen unter der Vorschau ist weg
  assert.equal(parseProducts(d.gh.store.get("products.yaml").text).at(-1).zielpreis, 72.5);
  // danach ist eine Zahl wieder nur eine Zahl
  await handleUpdate(msg("50"), d);
  assert.match(d.tg.sent.at(-1).text, /Schick mir einen Befehl/);
});

test("Link von gesperrtem Shop → ehrliche Absage, nichts gespeichert", async () => {
  const d = deps({}, { routes: { "https://shop.example/robots.txt": [200, "User-agent: *\nDisallow: /"] } });
  await handleUpdate(msg(LINK), d);
  assert.match(d.tg.sent[0].text, /erlaubt laut robots.txt kein automatisches Auslesen/);
  assert.match(d.tg.sent[0].text, /\/neu Name; Zielpreis/);
  assert.equal(d.gh.commits.length, 0);
});

// ---------- Buttons unter einer Deal-Meldung ----------

const ALERT = {
  reply_markup: {
    inline_keyboard: [
      [{ text: "✅ Gekauft", callback_data: "k:makita-dhp490rfx3:18400" }, { text: "🙈 Ignorieren", callback_data: "i:makita-dhp490rfx3:abc123def0" }],
      [{ text: "🎯 Ziel −10 €", callback_data: "m:makita-dhp490rfx3" }, { text: "⏸ Pausieren", callback_data: "q:makita-dhp490rfx3" }],
      [{ text: "🔗 Zum Angebot", url: "https://x/1" }],
    ],
  },
};

test("Gekauft: Produkt entfernt, Archiv mit Kaufpreis, Meldung behält Link", async () => {
  const d = deps();
  await handleUpdate(click("k:makita-dhp490rfx3:18400", ALERT), d);
  assert.ok(!parseProducts(d.gh.store.get("products.yaml").text).some((p) => p.id === "makita-dhp490rfx3"));
  const arch = JSON.parse(d.gh.store.get("data/geloescht.json").text)[0];
  assert.deepEqual([arch.grund, arch.gekauft.preis, arch.gekauft.url], ["gekauft", 184, "https://x/1"]);
  assert.equal(arch.eintrag.zielpreis, 215);
  assert.deepEqual(d.tg.markups[0].buttons, [[{ text: "✅ Gekauft", callback_data: "n" }], [{ text: "🔗 Zum Angebot", url: "https://x/1" }]]);
  assert.match(d.tg.sent[0].text, /als gekauft markiert \(184 €\)/);
  assert.equal(d.tg.edited.length, 0); // Meldungstext bleibt stehen
});

test("Ignorieren, Ziel −10 €, Pausieren", async () => {
  const d = deps();
  await handleUpdate(click("i:makita-dhp490rfx3:abc123def0", ALERT), d);
  assert.equal(JSON.parse(d.gh.store.get("data/ignoriert.json").text).abc123def0.produkt, "makita-dhp490rfx3");
  assert.equal(d.tg.answered.at(-1).text, "Wird nicht mehr gemeldet");
  assert.equal(d.gh.dispatches.length, 0); // Ignorieren braucht keinen Suchlauf

  await handleUpdate(click("m:makita-dhp490rfx3", ALERT), d);
  assert.equal(parseProducts(d.gh.store.get("products.yaml").text)[0].zielpreis, 205);
  assert.match(d.tg.sent.at(-1).text, /215 € → <b>205 €/);

  await handleUpdate(click("q:makita-dhp490rfx3", ALERT), d);
  assert.equal(parseProducts(d.gh.store.get("products.yaml").text)[0].aktiv, false);
  const rows = d.tg.markups.at(-1).buttons;
  assert.equal(rows[1][1].text, "⏸ Pausiert"); // nur der gedrückte Button ändert sich
  assert.equal(rows[0][0].callback_data, "k:makita-dhp490rfx3:18400"); // „Gekauft“ bleibt möglich
});

test("Buttons aus fremden Chats werden ignoriert", async () => {
  const d = deps();
  const c = click("k:makita-dhp490rfx3:18400", ALERT);
  c.callback_query.message.chat.id = 999;
  assert.equal(await handleUpdate(c, d), "ignoriert");
  assert.equal(d.gh.commits.length, 0);
});

// ---------- /ruhe ----------

test("/ruhe aus und an ändert nur die eine Zeile in config.yaml", async () => {
  const d = deps();
  await handleUpdate(msg("/ruhe aus"), d);
  const off = d.gh.store.get("config.yaml").text;
  assert.match(off, /ruhezeiten:\n  aktiv: false/);
  assert.equal(off.replace("aktiv: false", "aktiv: true"), CONFIG);
  assert.match(d.tg.sent[0].text, /Ruhezeiten sind <b>aus<\/b>/);
  await handleUpdate(msg("/ruhe"), d);
  assert.match(d.tg.sent[1].text, /aus/);
  await handleUpdate(msg("/ruhe an"), d);
  assert.equal(d.gh.store.get("config.yaml").text, CONFIG);
  assert.match(d.tg.sent[2].text, /Mo-Fr 07:30–14:00/);
  await handleUpdate(msg("/status"), d);
  assert.match(d.tg.sent[3].text, /Ruhezeiten: an \(gerade Ruhezeit\) · Übersicht täglich 19:00 Uhr/);
});

// ---------- Nachlieferung und Tagesübersicht ----------

function withQueue(items) {
  const data = JSON.parse(BOTDATA);
  data.warteschlange = items;
  return { "docs/bot.json": JSON.stringify(data) };
}

const HELD = {
  id: "h1", art: "ruhe", produkt: "makita-dhp490rfx3", name: "Makita", preis: 184, shop: "BAUR", url: "https://x/1",
  score: 60, text: "🔥 <b>Makita DHP490RFX3</b>", buttons: ALERT.reply_markup.inline_keyboard,
  zeit: "2026-11-25T10:17:00+01:00",
};
const DAILY = {
  id: "u1", art: "uebersicht", produkt: "epson-et-2922", name: "Epson ET-2922", preis: 159.9, shop: "Otto",
  url: "https://x/2", score: 72, text: "…", buttons: [], zeit: "2026-11-25T12:17:00+01:00",
};

test("Zurückgehaltene Meldung kommt erst nach der Ruhezeit – und nur einmal", async () => {
  const files = withQueue([HELD, DAILY]);
  const d = deps(files, { now: "2026-11-25T13:00:00+01:00" }); // noch Ruhezeit
  assert.equal((await hourly(d)).nachgeliefert, 0);
  assert.equal(d.tg.sent.length, 0);
  d.now = new Date("2026-11-25T14:00:00+01:00");
  assert.equal((await hourly(d)).nachgeliefert, 1);
  assert.match(d.tg.sent[0].text, /Während der Ruhezeit gefunden \(25\.11\., 10:17 Uhr\)/);
  assert.deepEqual(d.tg.sent[0].buttons, HELD.buttons);
  d.now = new Date("2026-11-25T15:00:00+01:00");
  assert.equal((await hourly(d)).nachgeliefert, 0);
});

test("Tagesübersicht um 19 Uhr, genau einmal, mit den Übersichts-Deals", async () => {
  const d = deps(withQueue([HELD, DAILY]), { now: "2026-11-25T18:00:00+01:00" });
  assert.equal((await hourly(d)).uebersicht, false);
  d.tg.sent = [];
  d.now = new Date("2026-11-25T19:00:00+01:00");
  assert.equal((await hourly(d)).uebersicht, true);
  const text = d.tg.sent.at(-1).text;
  assert.match(text, /Tagesübersicht/);
  assert.match(text, /Zielpreis erreicht<\/b>\n1\. ✅ Makita/);
  assert.match(text, /• Epson ET-2922 – 159,90 € bei Otto · Score 72/);
  assert.match(text, /📋 <b>Alle Produkte<\/b>/);
  const n = d.tg.sent.length;
  await hourly(d);
  assert.equal(d.tg.sent.length, n); // nicht doppelt
  // am nächsten Tag ist der Deal schon "verbraucht"
  d.now = new Date("2026-11-26T19:00:00+01:00");
  await hourly(d);
  assert.match(d.tg.sent.at(-1).text, /Keine weiteren neuen Deals/);
});

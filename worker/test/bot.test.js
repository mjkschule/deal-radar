import assert from "node:assert/strict";
import { test } from "node:test";

import { eur, handleUpdate, nextRun, parseNew } from "../src/bot.js";
import { editFile } from "../src/github.js";
import { parseProducts } from "../src/yamledit.js";
import { deps, msg } from "./helpers.js";

const products = (d) => parseProducts(d.gh.store.get("products.yaml").text);
const last = (d) => d.tg.sent.at(-1);

test("Nur die eigene Chat-ID wird beantwortet", async () => {
  const d = deps();
  assert.equal(await handleUpdate(msg("/loeschen 1", 999), d), "ignoriert");
  assert.equal(await handleUpdate(msg("/liste", -111), d), "ignoriert");
  assert.equal(await handleUpdate({ callback_query: { id: "c", data: "d:makita-dhp490rfx3",
    message: { message_id: 5, chat: { id: 999 } } } }, d), "ignoriert");
  assert.equal(d.tg.sent.length + d.tg.edited.length, 0);
  assert.equal(products(d).length, 8);
});

test("/liste: Nummer, Ziel, Effektivpreis, Shop, Score", async () => {
  const d = deps();
  await handleUpdate(msg("/liste"), d);
  const t = last(d).text;
  assert.match(t, /Preise vom Lauf 25\.11\., 10:17 Uhr/);
  assert.match(t, /1\. ✅ <b>Makita DHP490RFX3.*<\/b>\n    Ziel 215 € · jetzt 184 € bei BAUR · Score 88/);
  assert.match(t, /3\. 🔴 <b>Epson.*\n    Ziel 155 € · jetzt 174,99 € bei Amazon · Score 41/);
  assert.match(t, /2\. ⚪ <b>HP DeskJet.*\n.*jetzt kein aktuelles Angebot · Score –/);
  assert.match(t, /8\. 🔴 <b>Opel.*\n.*Ziel 250 €\/Monat · jetzt 301 €\/Monat \(effektiv 342,45 €\) bei LeasingMarkt\.de/);
  assert.match(t, /4\. 🆕 .*\n.*neu – wird beim nächsten Lauf gesucht/); // nicht in bot.json
});

test("/top sortiert nach Deal-Score", async () => {
  const d = deps();
  await handleUpdate(msg("/top"), d);
  const t = last(d).text;
  assert.ok(t.indexOf("Makita") < t.indexOf("Opel") && t.indexOf("Opel") < t.indexOf("Epson"));
  assert.match(t, /Score <b>88<\/b>/);
});

test("/status zeigt Läufe und Quellen", async () => {
  const d = deps();
  await handleUpdate(msg("/status"), d);
  const t = last(d).text;
  assert.match(t, /Letzter Lauf: 25\.11\., 10:17 Uhr \(vor 103 Min\.\)/);
  assert.match(t, /Nächster Lauf: ca\. 25\.11\., 13:17 Uhr/);
  assert.match(t, /✅ mydealz – 26 Treffer/);
  assert.match(t, /⚪ ebay – keine Schlüssel/);
});

test("/neu legt an, committet und startet einen Suchlauf", async () => {
  const d = deps();
  await handleUpdate(msg("/neu Philips Airfryer 5000; 55,5; HD9255, Airfryer 5000"), d);
  const p = products(d).at(-1);
  assert.equal(p.name, "Philips Airfryer 5000");
  assert.equal(p.zielpreis, 55.5);
  assert.deepEqual(p.suchbegriffe, ["HD9255", "Airfryer 5000"]);
  assert.match(last(d).text, /Nr\. 9, Ziel 55,50 €/);
  assert.match(last(d).text, /Suchlauf gestartet/);
  assert.deepEqual(d.gh.dispatches, ["befehl"]);
  assert.match(d.gh.commits[0].message, /^Telegram: Produkt Philips Airfryer 5000 hinzugefügt/);
});

test("Mehrdeutiger Name -> Buttons, Klick führt die Aktion aus", async () => {
  const d = deps();
  await handleUpdate(msg("/neu Philips Airfryer; 55; Philips Airfryer"), d);
  await handleUpdate(msg("/neu Ninja Airfryer; 65; Ninja Airfryer"), d);
  await handleUpdate(msg("/loeschen airfryer"), d);
  const q = last(d);
  assert.match(q.text, /passt auf 2 Produkte. Welches soll ich löschen\?/);
  assert.deepEqual(q.buttons.map((r) => r[0].text), ["9. Philips Airfryer", "10. Ninja Airfryer", "Abbrechen"]);
  assert.equal(products(d).length, 10); // noch nichts gelöscht
  await handleUpdate({ callback_query: { id: "cb1", data: q.buttons[1][0].callback_data,
    message: { message_id: 42, chat: { id: 111 } } } }, d);
  assert.deepEqual(d.tg.answered.map((a) => a.id), ["cb1"]);
  assert.match(d.tg.edited[0].text, /Gelöscht: <b>Ninja Airfryer<\/b>/);
  assert.equal(d.tg.edited[0].id, 42);
  assert.ok(!products(d).some((p) => p.id === "ninja-airfryer"));
  const archive = JSON.parse(d.gh.store.get("data/geloescht.json").text);
  assert.equal(archive[0].id, "ninja-airfryer");
  assert.equal(archive[0].eintrag.zielpreis, 65);
});

test("Abbrechen-Button ändert nichts", async () => {
  const d = deps();
  await handleUpdate({ callback_query: { id: "c", data: "x", message: { message_id: 1, chat: { id: 111 } } } }, d);
  assert.equal(d.tg.edited[0].text, "Abgebrochen.");
  assert.equal(d.gh.commits.length, 0);
});

test("/pause, /fortsetzen, /ziel per Nummer und Name", async () => {
  const d = deps();
  await handleUpdate(msg("/pause 5"), d);
  assert.match(last(d).text, /Lenovo L24-4e.*\(Nr\. 5\) ist pausiert/);
  assert.equal(products(d)[4].aktiv, false);
  await handleUpdate(msg("/pause lenovo"), d);
  assert.match(last(d).text, /bereits pausiert/);
  await handleUpdate(msg("/liste"), d);
  assert.match(last(d).text, /5\. ⏸ <b>Lenovo.*\n.*pausiert/);
  await handleUpdate(msg("/fortsetzen 5"), d);
  assert.equal(products(d)[4].aktiv, true);
  await handleUpdate(msg("/ziel epson 149,99"), d);
  assert.match(last(d).text, /Zielpreis von <b>Epson.*155 € → <b>149,99 €<\/b>/);
  assert.equal(products(d)[2].zielpreis, 149.99);
  await handleUpdate(msg("/ziel 3"), d);
  assert.match(last(d).text, /Format: <code>\/ziel 3 49,99<\/code>/);
});

test("/ziel bei mehrdeutigem Namen trägt den Preis im Button mit", async () => {
  const d = deps();
  await handleUpdate(msg("/ziel farbe wlan 50"), d);
  const q = last(d);
  assert.match(q.text, /passt auf 3 Produkte. Für welches soll ich den Zielpreis auf 50 € setzen\?/);
  const btn = q.buttons.find((r) => r[0].text.includes("Multifunktionsdrucker"))[0];
  assert.equal(btn.callback_data, "z:drucker-allgemein:5000");
  assert.ok(btn.callback_data.length <= 64);
  await handleUpdate({ callback_query: { id: "c", data: btn.callback_data, message: { message_id: 7, chat: { id: 111 } } } }, d);
  assert.equal(products(d).find((p) => p.id === "drucker-allgemein").zielpreis, 50);
});

test("Fehlerfälle und unbekannte Befehle", async () => {
  const d = deps();
  await handleUpdate(msg("/loeschen 99"), d);
  assert.match(last(d).text, /Nr\. 99 gibt es nicht/);
  await handleUpdate(msg("/pause kaffeemaschine"), d);
  assert.match(last(d).text, /Kein Produkt passt/);
  await handleUpdate(msg("/quatsch"), d);
  assert.match(last(d).text, /Das kenne ich nicht.*\/liste/s);
  await handleUpdate(msg("hallo"), d);
  assert.match(last(d).text, /\/hilfe/);
  await handleUpdate(msg("/liste@MeinDealBot"), d);
  assert.match(last(d).text, /Deine Produkte/);
  await handleUpdate(msg("/neu ohne Preis"), d);
  assert.match(last(d).text, /Format: \/neu/);
  assert.equal(d.gh.commits.length, 0);
});

test("Konflikt beim Commit wird einmal neu versucht", async () => {
  const d = deps();
  d.gh.conflictOnce = true;
  await editFile(d.gh, "products.yaml", "m", (t) => ({ text: t + "\n" }));
  assert.equal(d.gh.commits.length, 1);
});

test("Hilfsfunktionen", () => {
  assert.equal(eur(215), "215");
  assert.equal(eur(39.9), "39,90");
  assert.equal(eur(1492.3), "1.492,30");
  assert.equal(nextRun(new Date("2026-11-25T12:17:00Z")).toISOString(), "2026-11-25T14:17:00.000Z");
  assert.equal(nextRun(new Date("2026-11-25T13:05:00Z")).toISOString(), "2026-11-25T14:17:00.000Z");
  assert.deepEqual(parseNew("/neu A; 10"), { name: "A", zielpreis: 10, suchbegriffe: ["A"] });
});

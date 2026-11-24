// Gleiche Fälle wie tests/test_commands.py – Worker und Python müssen products.yaml gleich behandeln.
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  appendProduct, parseProducts, ProductError, removeProduct, setActive, setTarget, slugify,
} from "../src/yamledit.js";
import { FIXTURE } from "./helpers.js";

const ids = (t) => parseProducts(t).map((p) => p.id);

test("Fixture hat 8 gültige Produkte", () => {
  assert.equal(parseProducts(FIXTURE).length, 8);
});

test("Löschen lässt andere Einträge und Kommentare stehen", () => {
  const { text, product, raw } = removeProduct(FIXTURE, "hp-deskjet-2922");
  assert.ok(product.name.startsWith("HP DeskJet"));
  assert.equal(raw.zielpreis, 45);
  assert.deepEqual(ids(text).length, 7);
  assert.ok(!ids(text).includes("hp-deskjet-2922"));
  assert.ok(text.includes("Deal-Radar – deine Produkte") && text.includes("BEISPIEL für ein neues Produkt"));
  assert.ok(!text.includes("\n\n\n"));
});

test("Erstes und letztes Produkt löschen", () => {
  let t = removeProduct(FIXTURE, "makita-dhp490rfx3").text;
  t = removeProduct(t, "opel-frontera-electric-leasing").text;
  assert.equal(ids(t)[0], "hp-deskjet-2922");
  assert.equal(ids(t).at(-1), "wandhalterung-c27f396");
  assert.ok(t.includes("# ====") && t.includes("# BEISPIEL"));
});

test("Anlegen und wieder löschen ergibt exakt die alte Datei", () => {
  const added = appendProduct(FIXTURE, { name: "Testprodukt Airfryer", zielpreis: 49.9, suchbegriffe: ["Test Airfryer"] },
    "per Telegram hinzugefügt");
  assert.equal(added.number, 9);
  assert.equal(added.product.id, "testprodukt-airfryer");
  assert.equal(added.product.zielpreis, 49.9);
  assert.equal(removeProduct(added.text, "testprodukt-airfryer").text, FIXTURE);
});

test("Doppelte Namen bekommen eine neue id", () => {
  const a = appendProduct(FIXTURE, { name: "Makita DHP490RFX3", zielpreis: 1, suchbegriffe: ["x"] });
  assert.equal(a.product.id, "makita-dhp490rfx3-2");
});

test("Sonderzeichen im Namen bleiben gültiges YAML", () => {
  const a = appendProduct(FIXTURE, { name: 'De\'Longhi "Magnifica" S: 24" #1', zielpreis: 249, suchbegriffe: ["a: b", "c#d"] });
  assert.equal(a.product.name, 'De\'Longhi "Magnifica" S: 24" #1');
  assert.deepEqual(a.product.suchbegriffe, ["a: b", "c#d"]);
});

test("Pausieren und Fortsetzen", () => {
  let t = setActive(FIXTURE, "lenovo-l24-4e", false).text;
  assert.equal(parseProducts(t).find((p) => p.id === "lenovo-l24-4e").aktiv, false);
  t = setActive(t, "lenovo-l24-4e", true).text;
  assert.equal(parseProducts(t).find((p) => p.id === "lenovo-l24-4e").aktiv, true);
  assert.equal((t.match(/aktiv:/g) || []).length, 1);
});

test("Zielpreis ändern ersetzt die vorhandene Zeile", () => {
  const t = setTarget(FIXTURE, "epson-et-2922", 149.99).text;
  assert.equal(parseProducts(t).find((p) => p.id === "epson-et-2922").zielpreis, 149.99);
  assert.equal(t.split("\n").length, FIXTURE.split("\n").length);
});

test("Ungültige Werte werden abgelehnt", () => {
  assert.throws(() => removeProduct(FIXTURE, "gibt-es-nicht"), ProductError);
  assert.throws(() => parseProducts(FIXTURE.replace("- id: lenovo-l24-4e\n", "- id: lenovo-l24-4e\n  aktiv: vielleicht\n")),
    ProductError);
});

test("slugify wie in Python", () => {
  assert.equal(slugify("Philips Airfryer 5000 HD9255 (4,1 l)"), "philips-airfryer-5000-hd9255-4-1-l");
  assert.equal(slugify("Größe Übung"), "groesse-uebung");
});

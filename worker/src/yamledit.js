// products.yaml lesen und gezielt ändern (gleiches Prinzip wie dealradar/products_edit.py):
// Es werden nur die Zeilen des betroffenen Eintrags geändert, angehängt oder entfernt –
// Kommentare und Formatierung bleiben erhalten. Nach jeder Änderung wird die ganze
// Datei geprüft; ist sie ungültig, wird nichts gespeichert.

import { parse } from "yaml";

const ID_RE = /^[a-z0-9][a-z0-9-]*$/;
const ITEM_START = /^- id:\s*["']?([a-z0-9][a-z0-9-]*)["']?\s*(#.*)?$/;

export class ProductError extends Error {}

/** Liest products.yaml und prüft die wichtigsten Regeln (wie config.parse_products in Python). */
export function parseProducts(text) {
  let raw;
  try {
    raw = parse(text);
  } catch (e) {
    throw new ProductError(`products.yaml ist kein gültiges YAML: ${e.message.split("\n")[0]}`);
  }
  if (raw == null) return [];
  if (!Array.isArray(raw)) throw new ProductError("products.yaml muss eine Liste sein.");
  const seen = new Set();
  return raw.map((item, i) => {
    if (!item || typeof item !== "object") throw new ProductError(`Eintrag Nr. ${i + 1} ist ungültig.`);
    const id = String(item.id ?? "").trim();
    const where = `Produkt '${id || i + 1}'`;
    if (!ID_RE.test(id)) throw new ProductError(`${where}: 'id' fehlt oder ist ungültig.`);
    if (seen.has(id)) throw new ProductError(`${where}: die id ist doppelt vergeben.`);
    seen.add(id);
    if (!item.name) throw new ProductError(`${where}: 'name' fehlt.`);
    const terms = item.suchbegriffe == null ? [] : [].concat(item.suchbegriffe);
    if (!terms.length) throw new ProductError(`${where}: mindestens ein Suchbegriff nötig.`);
    const target = Number(String(item.zielpreis).replace(",", "."));
    if (!Number.isFinite(target)) throw new ProductError(`${where}: 'zielpreis' muss eine Zahl sein.`);
    const aktiv = item.aktiv ?? true;
    if (typeof aktiv !== "boolean") throw new ProductError(`${where}: 'aktiv' muss true oder false sein.`);
    return {
      id,
      name: String(item.name),
      zielpreis: target,
      aktiv,
      typ: String(item.typ || "produkt").toLowerCase(),
      kategorie: String(item.kategorie || "sonstiges"),
      suchbegriffe: terms.map(String),
      ean: item.ean == null ? null : String(item.ean),
      shop_urls: item.shop_urls == null ? [] : [].concat(item.shop_urls).map(String),
    };
  });
}

function splitLines(text) {
  return text.match(/[^\n]*\n|[^\n]+$/g) || [];
}

/** Zeilenbereich [start, end) des Eintrags (ohne Leerzeilen am Ende). */
function findBlock(lines, id) {
  for (let i = 0; i < lines.length; i++) {
    const m = ITEM_START.exec(lines[i].replace(/\n$/, ""));
    if (m && m[1] === id) {
      let j = i + 1;
      while (j < lines.length && (!lines[j].trim() || lines[j][0] === " " || lines[j][0] === "\t")) j++;
      while (j > i + 1 && !lines[j - 1].trim()) j--;
      return [i, j];
    }
  }
  throw new ProductError(`Eintrag '${id}' wurde in products.yaml nicht gefunden (bitte im Web-Editor ändern).`);
}

export function slugify(name) {
  let t = name.toLowerCase().replace(/ä/g, "ae").replace(/ö/g, "oe").replace(/ü/g, "ue").replace(/ß/g, "ss");
  t = t.normalize("NFKD").replace(/[^\x00-\x7f]/g, "");
  t = t.replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
  return t.slice(0, 40).replace(/-+$/g, "") || "produkt";
}

function yamlNumber(v) {
  return Number.isInteger(v) ? String(v) : String(Math.round(v * 100) / 100);
}

/** Entfernt einen Eintrag samt direkt darüberstehendem Kommentar. */
export function removeProduct(text, id) {
  const before = parseProducts(text);
  const old = before.find((p) => p.id === id);
  if (!old) throw new ProductError(`Produkt '${id}' gibt es nicht (mehr).`);
  const lines = splitLines(text);
  let [start, end] = findBlock(lines, id);
  while (start > 0 && lines[start - 1].startsWith("#") && !/^#\s*[=-]{3,}/.test(lines[start - 1])) start--;
  if (start > 0 && !lines[start - 1].trim()) start--;
  const newText = lines.slice(0, start).join("") + lines.slice(end).join("");
  if (parseProducts(newText).some((p) => p.id === id)) throw new ProductError("Löschen fehlgeschlagen.");
  // Den kompletten alten Eintrag (alle Felder) für das Archiv zurückgeben
  const rawOld = (parse(text) || []).find((x) => x && String(x.id) === id);
  return { text: newText, product: old, raw: rawOld };
}

/** Setzt ein einfaches Feld (z. B. aktiv, zielpreis) im Eintrag; fügt die Zeile ggf. unter 'id' ein. */
export function setField(text, id, key, value) {
  const lines = splitLines(text);
  const [start, end] = findBlock(lines, id);
  const re = new RegExp(`^  ${key}\\s*:`);
  const line = `  ${key}: ${value}\n`;
  let done = false;
  for (let k = start + 1; k < end; k++) {
    if (re.test(lines[k])) {
      lines[k] = line;
      done = true;
      break;
    }
  }
  if (!done) lines.splice(start + 1, 0, line);
  const newText = lines.join("");
  const product = parseProducts(newText).find((p) => p.id === id);
  return { text: newText, product };
}

export function setActive(text, id, active) {
  const r = setField(text, id, "aktiv", active ? "true" : "false");
  if (r.product.aktiv !== active) throw new ProductError("Ändern von 'aktiv' fehlgeschlagen.");
  return r;
}

export function setTarget(text, id, price) {
  const r = setField(text, id, "zielpreis", yamlNumber(price));
  if (Math.abs(r.product.zielpreis - price) > 0.001) throw new ProductError("Ändern des Zielpreises fehlgeschlagen.");
  return r;
}

/** Hängt ein neues Produkt unten an (vor dem Beispiel-Kommentar ist egal – YAML ignoriert Kommentare). */
export function appendProduct(text, { name, zielpreis, suchbegriffe, kategorie = "sonstiges", ean = null, shop_urls = [] },
  comment = "") {
  const existing = parseProducts(text);
  const ids = new Set(existing.map((p) => p.id));
  const base = slugify(name);
  let id = base;
  for (let n = 2; ids.has(id); n++) id = `${base}-${n}`;
  const q = (s) => JSON.stringify(String(s)); // JSON-Strings sind gültiges YAML
  let block = (text.endsWith("\n") ? "" : "\n") + "\n";
  if (comment) block += `# ${comment}\n`;
  block += `- id: ${id}\n  name: ${q(name)}\n  kategorie: ${kategorie}\n` +
    `  suchbegriffe: [${suchbegriffe.map(q).join(", ")}]\n  zielpreis: ${yamlNumber(zielpreis)}\n`;
  if (ean) block += `  ean: ${q(ean)}\n`;
  if (shop_urls.length) block += `  shop_urls: [${shop_urls.map(q).join(", ")}]\n`;
  const newText = text + block;
  const product = parseProducts(newText).find((p) => p.id === id);
  if (!product) throw new ProductError("Anlegen fehlgeschlagen.");
  return { text: newText, product, number: existing.length + 1 };
}

/**
 * Setzt in config.yaml einen Wert in einem Abschnitt, z. B. ruhezeiten -> aktiv: false.
 * Nur die eine Zeile wird geändert; Kommentare bleiben stehen.
 */
export function setConfigValue(text, section, key, value) {
  const lines = splitLines(text);
  const start = lines.findIndex((l) => new RegExp(`^${section}:\\s*(#.*)?$`).test(l.replace(/\n$/, "")));
  if (start < 0) throw new ProductError(`Abschnitt '${section}' fehlt in config.yaml.`);
  let k = start + 1;
  for (; k < lines.length && (!lines[k].trim() || /^[ \t#]/.test(lines[k])); k++) {
    const m = new RegExp(`^(\\s+)${key}:\\s*[^#\\n]*?(\\s*#.*)?$`).exec(lines[k].replace(/\n$/, ""));
    if (m && m[1].length === 2) {
      lines[k] = `${m[1]}${key}: ${value}${m[2] || ""}\n`;
      const newText = lines.join("");
      const parsed = parse(newText);
      if (String(parsed?.[section]?.[key]) !== String(value)) throw new ProductError("config.yaml ließ sich nicht ändern.");
      return { text: newText };
    }
  }
  throw new ProductError(`'${key}' fehlt im Abschnitt '${section}' der config.yaml.`);
}

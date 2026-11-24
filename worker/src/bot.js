// Die Befehle des Deal-Radar-Bots.
//
// Lesebefehle (/liste, /top, /status, /hilfe) antworten sofort aus docs/bot.json
// (schreibt der Suchlauf nach jedem Durchgang) und products.yaml.
// Schreibbefehle (/neu, /loeschen, /pause, /fortsetzen, /ziel) ändern products.yaml
// per GitHub-API (Commit), bestätigen sofort und starten danach einen Suchlauf.
// Es werden NUR Nachrichten aus deinem Chat (TELEGRAM_CHAT_ID) beantwortet.

import { editFile } from "./github.js";
import { describe, quietNow, readConfig } from "./ruhe.js";
import { deriveTerms, LinkError, readShopPage, suggestTarget } from "./shoplink.js";
import {
  appendProduct, parseProducts, ProductError, removeProduct, setActive, setConfigValue, setTarget,
} from "./yamledit.js";

const TZ = "Europe/Berlin";
const PRODUCTS = "products.yaml";
const BOTDATA = "docs/bot.json";
const ARCHIVE = "data/geloescht.json";
const IGNORED = "data/ignoriert.json";
const CONFIG = "config.yaml";
const LINK_TTL = 24 * 3600; // Vorschau eines Shop-Links gilt 1 Tag
const WAIT_TTL = 3600; // auf einen Zielpreis warten: 1 Stunde

export const HELP =
  "📡 <b>Deal-Radar – Befehle</b>\n\n" +
  "<b>Anzeigen</b> (Antwort sofort)\n" +
  "/liste – alle Produkte mit Nummer, Zielpreis, Bestpreis, Shop und Deal-Score\n" +
  "/top – die 5 besten Deals nach Deal-Score\n" +
  "/status – letzter und nächster Suchlauf, Zustand der Quellen\n\n" +
  "<b>Neues Produkt</b>\n" +
  "Einfach den <b>Link zur Produktseite</b> eines Shops schicken – ich lese Name, EAN und Preis " +
  "und schlage einen Zielpreis vor.\n" +
  "Oder von Hand: <code>/neu Philips HD9255; 55; HD9255, Airfryer 5000</code> – Name; Zielpreis; Suchbegriffe\n\n" +
  "<b>Ändern</b> (sofort gespeichert, danach startet ein Suchlauf)\n" +
  "<code>/ziel 3 49,99</code> – Zielpreis von Nr. 3 ändern\n" +
  "<code>/pause 3</code> – Nr. 3 vorübergehend nicht überwachen\n" +
  "<code>/fortsetzen 3</code> – wieder überwachen\n" +
  "<code>/loeschen 3</code> – Nr. 3 entfernen (Preisverlauf bleibt archiviert)\n\n" +
  "<b>Meldungen</b>\n" +
  "Sofort kommt nur, was den Zielpreis erreicht oder einen sehr hohen Deal-Score hat; " +
  "alles andere steht in der Übersicht um 19 Uhr.\n" +
  "<code>/ruhe aus</code> / <code>/ruhe an</code> – Ruhezeiten aus- oder einschalten, <code>/ruhe</code> zeigt den Stand\n" +
  "Unter jeder Meldung: ✅ Gekauft · 🙈 Ignorieren · 🎯 Ziel −10 € · ⏸ Pausieren · 🔗 Zum Angebot\n\n" +
  "Statt der Nummer geht auch ein Name, z. B. <code>/pause airfryer</code>. " +
  "Passt er auf mehrere Produkte, frage ich mit Buttons nach.";

const SHORT_HELP =
  "Das kenne ich nicht. Befehle: /liste · /top · /status · /neu · /ziel · /pause · /fortsetzen · /loeschen · /ruhe\n" +
  "Beispiele: /hilfe";

// ---------- Formatierung ----------

export const esc = (s) => String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

export function eur(v) {
  if (v == null || Number.isNaN(Number(v))) return "–";
  const n = Number(v);
  return new Intl.NumberFormat("de-DE", {
    minimumFractionDigits: Number.isInteger(n) ? 0 : 2, maximumFractionDigits: 2,
  }).format(n);
}

export function when(iso) {
  if (!iso) return "–";
  return new Intl.DateTimeFormat("de-DE", {
    timeZone: TZ, day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit",
  }).format(new Date(iso)) + " Uhr";
}

/** Nächster Zeitplan-Lauf: Minute 17 jeder geraden UTC-Stunde (wie in wrangler.toml). */
export function nextRun(now) {
  const d = new Date(now);
  d.setUTCMinutes(17, 0, 0);
  while (d <= now || d.getUTCHours() % 2 !== 0) d.setTime(d.getTime() + 3600e3);
  return d;
}

function fold(s) {
  const t = String(s).toLowerCase().replace(/ä/g, "ae").replace(/ö/g, "oe").replace(/ü/g, "ue").replace(/ß/g, "ss");
  return (t.match(/[a-z0-9]+/g) || []).join(" ");
}

export function parsePrice(text) {
  const m = /\d+(?:[.,]\d{1,2})?/.exec(text || "");
  if (!m) return null;
  return Number(m[0].replace(",", "."));
}

function icon(p, info) {
  if (!p.aktiv) return "⏸";
  if (!info) return "🆕";
  const b = info.bester;
  if (!b) return "⚪";
  const value = p.typ === "leasing" && b.rate != null ? b.rate : b.effektivpreis;
  if (value <= p.zielpreis) return "✅";
  if (value <= p.zielpreis * 1.1) return "🟡";
  return "🔴";
}

function priceText(p, b) {
  if (!b) return "kein aktuelles Angebot";
  if (p.typ === "leasing") {
    const rate = b.rate ?? b.effektivpreis;
    const eff = Math.abs(rate - b.effektivpreis) >= 0.01 ? ` (effektiv ${eur(b.effektivpreis)} €)` : "";
    return `${eur(rate)} €/Monat${eff} bei ${esc(b.shop)}`;
  }
  return `${eur(b.effektivpreis)} € bei ${esc(b.shop)}`;
}

// ---------- Daten laden ----------

async function loadProducts(gh) {
  const f = await gh.getFile(PRODUCTS);
  if (!f) throw new ProductError("products.yaml nicht gefunden.");
  return parseProducts(f.text);
}

export async function loadConfig(gh) {
  try {
    const f = await gh.getFile(CONFIG);
    return readConfig(f?.text);
  } catch {
    return readConfig("");
  }
}

export async function loadBotData(gh) {
  try {
    const f = await gh.getFile(BOTDATA);
    return f ? JSON.parse(f.text) : { produkte: {} };
  } catch {
    return { produkte: {} };
  }
}

// ---------- Produkt finden (Nummer oder Name) ----------

/** Gibt { product, nr } oder { error } oder { candidates: [{product, nr}] } zurück. */
export function resolve(products, arg) {
  arg = (arg || "").trim();
  if (!arg) return { error: "Bitte Nummer oder Name angeben. /liste zeigt die Nummern." };
  if (/^\d+$/.test(arg)) {
    const n = Number(arg);
    if (n < 1 || n > products.length) return { error: `Nr. ${n} gibt es nicht. /liste zeigt alle Produkte.` };
    return { product: products[n - 1], nr: n };
  }
  const q = fold(arg);
  const withNr = products.map((p, i) => ({ product: p, nr: i + 1 }));
  const exact = withNr.filter(({ product: p }) => p.id === arg.toLowerCase() || fold(p.name) === q);
  if (exact.length === 1) return exact[0];
  const words = q.split(" ").filter(Boolean);
  const hits = withNr.filter(({ product: p }) => words.length && words.every((w) => `${fold(p.name)} ${fold(p.id)}`.includes(w)));
  if (hits.length === 1) return hits[0];
  if (!hits.length) return { error: `Kein Produkt passt zu „${esc(arg)}“. /liste zeigt alle Produkte.` };
  return { candidates: hits };
}

// ---------- Lesebefehle ----------

export async function cmdListe({ gh }) {
  const [products, data] = await Promise.all([loadProducts(gh), loadBotData(gh)]);
  if (!products.length) return "📋 Noch keine Produkte. Anlegen: <code>/neu Name; Zielpreis; Suchbegriffe</code>";
  const lines = [`📋 <b>Deine Produkte</b> · Preise vom Lauf ${when(data.letzter_lauf)}`];
  products.forEach((p, i) => {
    const info = data.produkte?.[p.id];
    const unit = p.typ === "leasing" ? " €/Monat" : " €";
    let detail;
    if (!p.aktiv) detail = "pausiert";
    else if (!info) detail = "neu – wird beim nächsten Lauf gesucht";
    else detail = `jetzt ${priceText(p, info.bester)} · Score ${info.score ?? "–"}`;
    lines.push(`\n${i + 1}. ${icon(p, info)} <b>${esc(p.name)}</b>\n    Ziel ${eur(p.zielpreis)}${unit} · ${detail}`);
  });
  lines.push("\n✅ Ziel erreicht · 🟡 bis 10 % darüber · 🔴 darüber · ⚪ kein Angebot · ⏸ pausiert · 🆕 neu");
  return lines.join("\n");
}

export async function cmdTop({ gh }) {
  const [products, data] = await Promise.all([loadProducts(gh), loadBotData(gh)]);
  const rows = products
    .map((p, i) => ({ p, nr: i + 1, info: data.produkte?.[p.id] }))
    .filter((r) => r.p.aktiv && r.info?.bester && r.info.score != null)
    .sort((a, b) => b.info.score - a.info.score)
    .slice(0, 5);
  if (!rows.length) {
    const reached = products
      .map((p, i) => ({ p, nr: i + 1, info: data.produkte?.[p.id] }))
      .filter((r) => r.p.aktiv && r.info?.ziel_erreicht);
    let text = "🏆 Für einen Deal-Score fehlt noch Preisverlauf (mind. 5 Messpunkte).";
    if (reached.length) {
      text += "\n\nZielpreis erreicht:" + reached.map((r) =>
        `\n${r.nr}. ✅ <b>${esc(r.p.name)}</b>\n    ${priceText(r.p, r.info.bester)}`).join("");
    }
    return text;
  }
  return "🏆 <b>Top-Deals nach Deal-Score</b>" + rows.map((r) => {
    const b = r.info.bester;
    return `\n\n${r.nr}. ${icon(r.p, r.info)} <b>${esc(r.p.name)}</b> · Score <b>${r.info.score}</b>\n` +
      `    ${priceText(r.p, b)} (Ziel ${eur(r.p.zielpreis)} €)` +
      (b.url ? `\n    <a href="${esc(b.url)}">Zum Angebot</a>` : "");
  }).join("") + "\n\nScore: 50 = üblicher Preis, 100 = 20 % unter dem eigenen Median.";
}

export async function cmdStatus({ gh, env, now }) {
  const [products, data, cfg] = await Promise.all([loadProducts(gh), loadBotData(gh), loadConfig(gh)]);
  const active = products.filter((p) => p.aktiv);
  const quiet = cfg.ruhezeiten.aktiv === false ? "aus" : quietNow(cfg, now) ? "an (gerade Ruhezeit)" : "an";
  const reached = active.filter((p) => data.produkte?.[p.id]?.ziel_erreicht).length;
  const src = Object.entries(data.quellen || {}).map(([name, s]) => {
    const i = s.status === "ok" ? "✅" : s.status === "fehler" ? "❌" : "⚪";
    const extra = s.status === "ok" ? `${s.anzahl ?? 0} Treffer` : esc((s.meldung || "").slice(0, 80));
    return `${i} ${esc(name)} – ${extra}`;
  });
  const ago = data.letzter_lauf ? Math.round((now - new Date(data.letzter_lauf)) / 60000) : null;
  return [
    "📊 <b>Status</b>",
    `Letzter Lauf: ${when(data.letzter_lauf)}${ago != null ? ` (vor ${ago < 120 ? ago + " Min." : Math.round(ago / 60) + " Std."})` : ""}`,
    `Nächster Lauf: ca. ${when(nextRun(now).toISOString())}`,
    `Produkte: ${active.length} aktiv, ${products.length - active.length} pausiert · Ziel erreicht: ${reached}`,
    data.enddatum ? `Läuft bis: ${when(data.enddatum)}` : "",
    `Ruhezeiten: ${quiet} · Übersicht täglich ${esc(cfg.meldungen.uebersicht_uhrzeit)} Uhr`,
    "",
    "<b>Quellen</b>",
    ...(src.length ? src : ["noch keine Daten"]),
    "",
    `Startseite: ${esc(env.PAGE_URL || "")}`,
  ].filter((l, i, a) => l !== "" || a[i - 1] !== "").join("\n");
}

// ---------- Schreibbefehle ----------

const ACTIONS = {
  d: { ask: () => "Welches soll ich löschen?" },
  p: { ask: () => "Welches soll ich pausieren?" },
  f: { ask: () => "Welches soll ich fortsetzen?" },
  z: { ask: (extra) => `Für welches soll ich den Zielpreis auf ${eur(Number(extra) / 100)} € setzen?` },
};

async function startRun(gh) {
  try {
    await gh.dispatch("befehl");
    return "\n🔎 Suchlauf gestartet – Ergebnisse in wenigen Minuten.";
  } catch (e) {
    return "\n⚠️ Suchlauf konnte nicht gestartet werden – er kommt mit dem nächsten Zeitplan-Lauf.";
  }
}

/** Ändert eine JSON-Datei im Repo (legt sie bei Bedarf an); bei Konflikt ein zweiter Versuch. */
async function editJson(gh, path, message, empty, change) {
  for (let attempt = 0; ; attempt++) {
    const f = await gh.getFile(path);
    const data = change(f ? JSON.parse(f.text) : empty);
    try {
      await gh.putFile(path, JSON.stringify(data, null, 2) + "\n", f?.sha, message);
      return data;
    } catch (e) {
      if ((e.status === 409 || e.status === 422) && attempt === 0) continue;
      throw e;
    }
  }
}

async function archive(gh, entry, what = "gelöscht") {
  try {
    await editJson(gh, ARCHIVE, `Archiv: ${entry.id} ${what}`, [], (list) => [...list, entry]);
  } catch {
    // Archiv ist nur eine Komfort-Kopie; der Preisverlauf bleibt ohnehin in data/verlauf.json.
  }
}

/** Führt eine Schreib-Aktion für ein bestimmtes Produkt aus und gibt die Antwort zurück. */
export async function perform(code, id, extra, { gh, now }) {
  let res;
  if (code === "d") {
    res = await editFile(gh, PRODUCTS, `Telegram: Produkt ${id} gelöscht`, (t) => removeProduct(t, id));
    await archive(gh, { id, name: res.product.name, geloescht_am: now.toISOString(), eintrag: res.raw });
    return `🗑 Gelöscht: <b>${esc(res.product.name)}</b> (Ziel ${eur(res.product.zielpreis)} €).\n` +
      "Wird nicht mehr überwacht und verschwindet nach dem nächsten Lauf von der Startseite. " +
      "Der Preisverlauf bleibt archiviert.\nDie Nummern dahinter rücken auf." + await startRun(gh);
  }
  const products = await loadProducts(gh);
  const p = products.find((x) => x.id === id);
  if (!p) return "Dieses Produkt gibt es nicht mehr. /liste zeigt den aktuellen Stand.";
  const nr = products.indexOf(p) + 1;
  if (code === "p" || code === "f") {
    const active = code === "f";
    if (p.aktiv === active) {
      return active ? `▶️ <b>${esc(p.name)}</b> wird bereits überwacht.` : `⏸ <b>${esc(p.name)}</b> ist bereits pausiert.`;
    }
    await editFile(gh, PRODUCTS, `Telegram: Produkt ${id} ${active ? "fortgesetzt" : "pausiert"}`,
      (t) => setActive(t, id, active));
    if (active) return `▶️ <b>${esc(p.name)}</b> (Nr. ${nr}) wird wieder überwacht.` + await startRun(gh);
    return `⏸ <b>${esc(p.name)}</b> (Nr. ${nr}) ist pausiert.\nWieder einschalten: <code>/fortsetzen ${nr}</code>` +
      await startRun(gh);
  }
  if (code === "z") {
    const price = Number(extra) / 100;
    const old = p.zielpreis;
    await editFile(gh, PRODUCTS, `Telegram: Zielpreis ${id} ${old} -> ${price}`, (t) => setTarget(t, id, price));
    return `🎯 Zielpreis von <b>${esc(p.name)}</b> (Nr. ${nr}): ${eur(old)} € → <b>${eur(price)} €</b>` + await startRun(gh);
  }
  return "Unbekannte Aktion.";
}

async function writeCommand(code, arg, deps) {
  let extra = "";
  if (code === "z") {
    const m = /^(.*\S)\s+(\d+(?:[.,]\d{1,2})?)\s*€?$/.exec(arg.trim());
    if (!m) return { text: "Format: <code>/ziel 3 49,99</code> (Nummer oder Name, dann der neue Zielpreis)" };
    arg = m[1];
    const price = parsePrice(m[2]);
    if (!(price > 0)) return { text: "Der Zielpreis muss größer als 0 sein." };
    extra = String(Math.round(price * 100));
  }
  const products = await loadProducts(deps.gh);
  const r = resolve(products, arg);
  if (r.error) return { text: r.error };
  if (r.candidates) {
    const a = ACTIONS[code];
    const buttons = r.candidates.slice(0, 8).map(({ product: p, nr }) => [{
      text: `${nr}. ${p.name}`.slice(0, 60),
      callback_data: `${code}:${p.id}${extra ? ":" + extra : ""}`,
    }]);
    buttons.push([{ text: "Abbrechen", callback_data: "x" }]);
    return { text: `🤔 „${esc(arg)}“ passt auf ${r.candidates.length} Produkte. ${a.ask(extra)}`, buttons };
  }
  return { text: await perform(code, r.product.id, extra, deps) };
}

export function parseNew(text) {
  const body = text.trim().replace(/^\/neu(@\w+)?\s*/i, "");
  const parts = body.split(";").map((s) => s.trim());
  if (parts.length < 2 || !parts[0]) throw new ProductError("Format: /neu Name; Zielpreis; Suchbegriff1, Suchbegriff2");
  const price = parsePrice(parts[1]);
  if (price == null) throw new ProductError(`Zielpreis '${parts[1]}' ist keine Zahl.`);
  const terms = (parts[2] || "").split(/[\n,]/).map((s) => s.trim().replace(/^[-•]\s*/, "")).filter(Boolean);
  return { name: parts[0], zielpreis: price, suchbegriffe: terms.length ? terms : [parts[0]] };
}

async function cmdNeu(text, { gh }) {
  let product;
  try {
    product = parseNew(text);
  } catch (e) {
    return `❌ ${esc(e.message)}\nBeispiel: <code>/neu Bosch PSR 18; 89; PSR 18 LI-2, PSR18</code>`;
  }
  const res = await editFile(gh, PRODUCTS, `Telegram: Produkt ${product.name} hinzugefügt`,
    (t) => appendProduct(t, product, "per Telegram hinzugefügt"));
  return `✅ Neues Produkt <b>${esc(res.product.name)}</b> (Nr. ${res.number}, Ziel ${eur(res.product.zielpreis)} €)\n` +
    `Suchbegriffe: ${esc(res.product.suchbegriffe.join(", "))}` + await startRun(gh);
}

// ---------- Produkt per Shop-Link ----------

const URL_RE = /https?:\/\/[^\s<>"]+/i;
const randomKey = () => Array.from(crypto.getRandomValues(new Uint8Array(5)), (b) => b.toString(16).padStart(2, "0")).join("");

function linkPreview(info, target, extra = "") {
  const ship = info.shipping == null ? "" : info.shipping === 0 ? " inkl. Versand" : ` + ${eur(info.shipping)} € Versand`;
  return [
    `🛒 <b>${esc(info.name)}</b>`,
    `🏪 ${esc(info.shop)} · ${info.price != null ? `jetzt <b>${eur(info.price)} €</b>${ship}` : "Preis nicht lesbar"}` +
      (info.available === false ? " · ⚠️ laut Shop nicht lieferbar" : ""),
    info.ean ? `🔢 EAN ${esc(info.ean)}` : "🔢 keine EAN angegeben",
    `🔎 Suchbegriffe: ${esc(info.terms.join(", "))}`,
    target != null
      ? `🎯 Vorschlag Zielpreis: <b>${eur(target)} €</b> (10 % unter dem bisher bekannten Tiefstpreis von ${eur(info.low)} €)`
      : "🎯 Bitte Zielpreis selbst festlegen.",
    extra,
  ].filter(Boolean).join("\n");
}

async function cmdLink(url, deps) {
  const { gh, kv } = deps;
  let info;
  try {
    info = await readShopPage(url, deps.fetch);
  } catch (e) {
    if (!(e instanceof LinkError)) throw e;
    return {
      text: `❌ ${esc(e.message)}\nLeg das Produkt stattdessen von Hand an:\n` +
        "<code>/neu Name; Zielpreis; Suchbegriffe</code>",
    };
  }
  const products = await loadProducts(gh);
  const path = (u) => { try { const x = new URL(u); return x.host.replace(/^www\./, "") + x.pathname; } catch { return u; } };
  const dup = products.findIndex((p) => (info.ean && p.ean === info.ean) ||
    p.shop_urls.some((u) => path(u) === path(info.url)));
  if (dup >= 0) {
    return { text: `ℹ️ Das überwache ich schon: Nr. ${dup + 1} <b>${esc(products[dup].name)}</b> ` +
      `(Ziel ${eur(products[dup].zielpreis)} €). Zielpreis ändern: <code>/ziel ${dup + 1} 49,99</code>` };
  }
  const name = info.name.length > 80 ? info.name.slice(0, 80).replace(/\s+\S*$/, "") : info.name;
  const pending = { ...info, name, terms: deriveTerms(name), low: info.price };
  pending.target = info.price != null ? suggestTarget(info.price) : null;
  const key = randomKey();
  await kv.put(`link:${key}`, JSON.stringify(pending), { expirationTtl: LINK_TTL });
  const buttons = [];
  if (pending.target != null) buttons.push([{ text: `✅ Übernehmen (Ziel ${eur(pending.target)} €)`, callback_data: `a:${key}` }]);
  buttons.push([{ text: "✏️ Zielpreis ändern", callback_data: `c:${key}` }]);
  buttons.push([{ text: "Abbrechen", callback_data: "x" }]);
  return { text: linkPreview(pending, pending.target), buttons };
}

async function createFromLink(key, target, deps) {
  const { gh, kv } = deps;
  const raw = await kv.get(`link:${key}`);
  if (!raw) return "⌛ Die Vorschau ist abgelaufen – schick den Link bitte noch einmal.";
  const p = JSON.parse(raw);
  const res = await editFile(gh, PRODUCTS, `Telegram: Produkt ${p.name} per Link hinzugefügt`,
    (t) => appendProduct(t, {
      name: p.name, zielpreis: target, suchbegriffe: p.terms, ean: p.ean, shop_urls: [p.url],
    }, `per Telegram-Link hinzugefügt (${p.shop})`));
  await kv.delete(`link:${key}`);
  await kv.delete("warte_ziel");
  return `✅ Neues Produkt <b>${esc(res.product.name)}</b> (Nr. ${res.number}, Ziel ${eur(target)} €)\n` +
    `Überwacht: Shop-Seite ${esc(p.shop)} + Suche nach ${esc(p.terms.join(", "))}` + await startRun(gh);
}

async function linkCallback(code, key, cq, deps) {
  const { kv, tg } = deps;
  if (code === "a") {
    const raw = await kv.get(`link:${key}`);
    const text = raw ? await createFromLink(key, JSON.parse(raw).target, deps)
      : "⌛ Die Vorschau ist abgelaufen – schick den Link bitte noch einmal.";
    await tg.edit(cq.message.message_id, text);
    return;
  }
  // "Zielpreis ändern": auf die nächste Zahl warten
  const raw = await kv.get(`link:${key}`);
  if (!raw) {
    await tg.edit(cq.message.message_id, "⌛ Die Vorschau ist abgelaufen – schick den Link bitte noch einmal.");
    return;
  }
  await kv.put("warte_ziel", key, { expirationTtl: WAIT_TTL });
  const p = JSON.parse(raw);
  await tg.edit(cq.message.message_id,
    linkPreview(p, p.target, "\n✏️ <b>Schick mir jetzt den Zielpreis als Zahl</b>, z. B. <code>49,99</code>"),
    [[{ text: "Abbrechen", callback_data: "x" }]]);
}

// ---------- Buttons unter Deal-Meldungen ----------

function urlRow(cq) {
  const rows = cq.message?.reply_markup?.inline_keyboard || [];
  const b = rows.flat().find((x) => x.url);
  return b ? [[{ text: b.text, url: b.url }]] : [];
}

async function alertAction(code, id, extra, cq, deps) {
  const { gh, now } = deps;
  const offerUrl = urlRow(cq)[0]?.[0]?.url || null;
  if (code === "k") {
    const products = await loadProducts(gh);
    const p = products.find((x) => x.id === id);
    if (!p) return { toast: "Schon erledigt", text: null, label: "✅ Gekauft" };
    const price = extra ? Number(extra) / 100 : null;
    const res = await editFile(gh, PRODUCTS, `Telegram: ${id} gekauft`, (t) => removeProduct(t, id));
    await archive(gh, {
      id, name: res.product.name, geloescht_am: now.toISOString(), grund: "gekauft",
      gekauft: { preis: price, url: offerUrl, am: now.toISOString() }, eintrag: res.raw,
    }, "gekauft");
    return {
      toast: "Glückwunsch! 🎉", label: "✅ Gekauft",
      text: `🎉 <b>${esc(res.product.name)}</b> als gekauft markiert${price ? ` (${eur(price)} €)` : ""}.\n` +
        "Wird nicht mehr überwacht; Eintrag und Preisverlauf bleiben im Archiv." + await startRun(gh),
    };
  }
  if (code === "i") {
    await editJson(gh, IGNORED, `Telegram: Angebot ${extra} ignoriert`, {}, (d) => ({
      ...d, [extra]: { produkt: id, url: offerUrl, am: now.toISOString() },
    }));
    return { toast: "Wird nicht mehr gemeldet", label: "🙈 Ignoriert", text: null };
  }
  if (code === "m") {
    const products = await loadProducts(gh);
    const p = products.find((x) => x.id === id);
    if (!p) return { toast: "Produkt gibt es nicht mehr", text: null, label: null };
    const price = Math.round((p.zielpreis - 10) * 100) / 100;
    if (price < 1) return { toast: "Zielpreis ist schon sehr niedrig", text: null, label: null };
    return { toast: `Ziel jetzt ${eur(price)} €`, label: null, text: await perform("z", id, String(Math.round(price * 100)), deps) };
  }
  if (code === "q") return { toast: "Pausiert", label: "⏸ Pausiert", text: await perform("p", id, "", deps) };
  return { toast: "Schon erledigt", text: null, label: null };
}

// ---------- Ruhezeiten ----------

async function cmdRuhe(arg, { gh, now }) {
  const a = arg.trim().toLowerCase();
  if (a === "an" || a === "aus") {
    const on = a === "an";
    await editFile(gh, CONFIG, `Telegram: Ruhezeiten ${a}`, (t) => setConfigValue(t, "ruhezeiten", "aktiv", on ? "true" : "false"));
    const cfg = await loadConfig(gh);
    return on
      ? `🔕 Ruhezeiten sind <b>an</b>: ${esc(describe(cfg))}.\nZurückgehaltene Meldungen kommen danach gesammelt.`
      : "🔔 Ruhezeiten sind <b>aus</b> – Sofort-Meldungen kommen jetzt rund um die Uhr. Wieder einschalten: /ruhe an";
  }
  if (a) return "Format: <code>/ruhe an</code> oder <code>/ruhe aus</code> (ohne Zusatz: aktueller Stand)";
  const cfg = await loadConfig(gh);
  if (cfg.ruhezeiten.aktiv === false) return "🔔 Ruhezeiten sind <b>aus</b>. Einschalten: /ruhe an";
  return `🔕 Ruhezeiten sind <b>an</b>${quietNow(cfg, now) ? " – gerade ist Ruhezeit" : ""}.\n${esc(describe(cfg))}\n` +
    "Ausschalten: /ruhe aus";
}

// ---------- Einstieg ----------

/** Antwort auf eine Textnachricht: { text, buttons? }. */
export async function handleText(text, deps) {
  const t = text.trim();
  // Shop-Link (auch als "/neu <Link>")
  const url = URL_RE.exec(t);
  if (url && (!t.startsWith("/") || /^\/neu(@\w+)?\s+https?:/i.test(t))) return cmdLink(url[0], deps);
  // Zielpreis nach "Zielpreis ändern"
  if (/^\d+(?:[.,]\d{1,2})?\s*€?$/.test(t)) {
    const key = await deps.kv.get("warte_ziel");
    if (key) {
      const price = parsePrice(t);
      if (!(price > 0)) return { text: "Der Zielpreis muss größer als 0 sein." };
      return { text: await createFromLink(key, price, deps) };
    }
  }
  const m = /^\/([a-zäöüß]+)(?:@\w+)?\s*([\s\S]*)$/i.exec(t);
  if (!m) return { text: "Schick mir einen Befehl, z. B. /liste. Alle Befehle: /hilfe" };
  const cmd = m[1].toLowerCase();
  const arg = m[2].trim();
  switch (cmd) {
    case "liste": return { text: await cmdListe(deps) };
    case "top": return { text: await cmdTop(deps) };
    case "status": return { text: await cmdStatus(deps) };
    case "hilfe": case "help": case "start": return { text: HELP };
    case "neu": return { text: await cmdNeu(text, deps) };
    case "loeschen": case "löschen": case "loschen": return writeCommand("d", arg, deps);
    case "pause": return writeCommand("p", arg, deps);
    case "fortsetzen": return writeCommand("f", arg, deps);
    case "ziel": return writeCommand("z", arg, deps);
    case "ruhe": return { text: await cmdRuhe(arg, deps) };
    default: return { text: SHORT_HELP };
  }
}

const isOwnChat = (chat, env) => chat && String(chat.id) === String(env.TELEGRAM_CHAT_ID);

/** Verarbeitet ein Telegram-Update (Nachricht oder Button-Klick). */
export async function handleUpdate(update, deps) {
  const { tg, env } = deps;
  const cq = update.callback_query;
  if (cq) {
    if (!isOwnChat(cq.message?.chat, env)) return "ignoriert";
    const [code, id, extra] = String(cq.data || "").split(":");
    // Buttons unter einer Deal-Meldung: Meldung bleibt stehen, Ergebnis kommt als neue Nachricht
    if (["k", "i", "m", "q", "n"].includes(code)) {
      let r;
      try {
        r = await alertAction(code, id, extra, cq, deps);
      } catch (e) {
        r = { toast: "Hat nicht geklappt", text: `❌ Hat nicht geklappt: ${esc(e.message)}`, label: null };
      }
      await tg.answer(cq.id, r.toast);
      if (r.label) await tg.editMarkup(cq.message.message_id, [[{ text: r.label, callback_data: "n" }], ...urlRow(cq)]);
      if (r.text) await tg.send(r.text);
      return "meldung";
    }
    let text;
    let answered = false;
    try {
      if (code === "a" || code === "c") {
        await tg.answer(cq.id);
        answered = true;
        await linkCallback(code, id, cq, deps);
        return "link";
      }
      if (code === "x") await deps.kv?.delete("warte_ziel");
      text = code === "x" ? "Abgebrochen." : ACTIONS[code] ? await perform(code, id, extra, deps) : "Unbekannte Aktion.";
    } catch (e) {
      text = `❌ Hat nicht geklappt: ${esc(e.message)}`;
    }
    if (!answered) await tg.answer(cq.id);
    await tg.edit(cq.message.message_id, text);
    return "button";
  }
  const msg = update.message;
  if (!msg || !isOwnChat(msg.chat, env) || !msg.text) return "ignoriert";
  let out;
  try {
    out = await handleText(msg.text, deps);
  } catch (e) {
    out = { text: `❌ Hat nicht geklappt: ${esc(e.message)}` };
  }
  await tg.send(out.text, out.buttons);
  return "nachricht";
}

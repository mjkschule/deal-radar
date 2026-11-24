// Die Befehle des Deal-Radar-Bots.
//
// Lesebefehle (/liste, /top, /status, /hilfe) antworten sofort aus docs/bot.json
// (schreibt der Suchlauf nach jedem Durchgang) und products.yaml.
// Schreibbefehle (/neu, /loeschen, /pause, /fortsetzen, /ziel) ändern products.yaml
// per GitHub-API (Commit), bestätigen sofort und starten danach einen Suchlauf.
// Es werden NUR Nachrichten aus deinem Chat (TELEGRAM_CHAT_ID) beantwortet.

import { editFile } from "./github.js";
import {
  appendProduct, parseProducts, ProductError, removeProduct, setActive, setTarget,
} from "./yamledit.js";

const TZ = "Europe/Berlin";
const PRODUCTS = "products.yaml";
const BOTDATA = "docs/bot.json";
const ARCHIVE = "data/geloescht.json";

export const HELP =
  "📡 <b>Deal-Radar – Befehle</b>\n\n" +
  "<b>Anzeigen</b> (Antwort sofort)\n" +
  "/liste – alle Produkte mit Nummer, Zielpreis, Bestpreis, Shop und Deal-Score\n" +
  "/top – die 5 besten Deals nach Deal-Score\n" +
  "/status – letzter und nächster Suchlauf, Zustand der Quellen\n\n" +
  "<b>Ändern</b> (sofort gespeichert, danach startet ein Suchlauf)\n" +
  "<code>/neu Philips HD9255; 55; HD9255, Airfryer 5000</code> – Name; Zielpreis; Suchbegriffe\n" +
  "<code>/ziel 3 49,99</code> – Zielpreis von Nr. 3 ändern\n" +
  "<code>/pause 3</code> – Nr. 3 vorübergehend nicht überwachen\n" +
  "<code>/fortsetzen 3</code> – wieder überwachen\n" +
  "<code>/loeschen 3</code> – Nr. 3 entfernen (Preisverlauf bleibt archiviert)\n\n" +
  "Statt der Nummer geht auch ein Name, z. B. <code>/pause airfryer</code>. " +
  "Passt er auf mehrere Produkte, frage ich mit Buttons nach.";

const SHORT_HELP =
  "Das kenne ich nicht. Befehle: /liste · /top · /status · /neu · /ziel · /pause · /fortsetzen · /loeschen\n" +
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

async function loadBotData(gh) {
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
  const [products, data] = await Promise.all([loadProducts(gh), loadBotData(gh)]);
  const active = products.filter((p) => p.aktiv);
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

async function archive(gh, entry) {
  try {
    const f = await gh.getFile(ARCHIVE);
    const list = f ? JSON.parse(f.text) : [];
    list.push(entry);
    await gh.putFile(ARCHIVE, JSON.stringify(list, null, 2) + "\n", f?.sha, `Archiv: ${entry.id} gelöscht`);
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

// ---------- Einstieg ----------

/** Antwort auf eine Textnachricht: { text, buttons? }. */
export async function handleText(text, deps) {
  const m = /^\/([a-zäöüß]+)(?:@\w+)?\s*([\s\S]*)$/i.exec(text.trim());
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
    let text;
    try {
      text = code === "x" ? "Abgebrochen." : ACTIONS[code] ? await perform(code, id, extra, deps) : "Unbekannte Aktion.";
    } catch (e) {
      text = `❌ Hat nicht geklappt: ${esc(e.message)}`;
    }
    await tg.answer(cq.id);
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

// Stündlicher Zeitplan des Workers (zur vollen Stunde):
//  1. Nach einer Ruhezeit die zurückgehaltenen Meldungen nachliefern (mit Buttons).
//  2. Zur Übersichts-Uhrzeit (Standard 19:00) die Tagesübersicht schicken.
// Die Meldungen stehen in docs/bot.json -> warteschlange (schreibt der Suchlauf).
// Was schon verschickt wurde, merkt sich der Worker im KV-Speicher.

import { esc, eur, loadBotData, loadConfig, when } from "./bot.js";
import { localParts, quietNow } from "./ruhe.js";
import { parseProducts } from "./yamledit.js";

const SENT_TTL = 3 * 24 * 3600;

async function isSent(kv, id) {
  return Boolean(await kv.get(`gesendet:${id}`));
}

async function markSent(kv, id) {
  await kv.put(`gesendet:${id}`, "1", { expirationTtl: SENT_TTL });
}

/** Ruhezeit vorbei? Dann zurückgehaltene Meldungen einzeln (mit Buttons) senden. */
export async function releaseHeld({ tg, kv }, data, cfg, now) {
  if (quietNow(cfg, now)) return 0;
  let n = 0;
  for (const item of data.warteschlange || []) {
    if (item.art !== "ruhe" || await isSent(kv, item.id)) continue;
    await tg.send(`🔕 <i>Während der Ruhezeit gefunden (${when(item.zeit)}):</i>\n\n${item.text}`, item.buttons);
    await markSent(kv, item.id);
    n++;
  }
  return n;
}

function line(nr, p, info) {
  const b = info?.bester;
  const unit = p.typ === "leasing" ? " €/Monat" : " €";
  const value = b ? (p.typ === "leasing" && b.rate != null ? b.rate : b.effektivpreis) : null;
  const mark = !b ? "⚪" : value <= p.zielpreis ? "✅" : value <= p.zielpreis * 1.1 ? "🟡" : "🔴";
  const price = b ? `${eur(value)}${unit} bei ${esc(b.shop)}` : "kein Angebot";
  return `${nr}. ${mark} ${esc(p.name)} – ${price} (Ziel ${eur(p.zielpreis)}${unit})` +
    (info?.score != null ? ` · Score ${info.score}` : "");
}

/** Text der Tagesübersicht; markiert die enthaltenen Übersichts-Deals als verschickt. */
export async function buildOverview({ kv, env }, data, products, cfg, now) {
  const active = products.map((p, i) => ({ p, nr: i + 1 })).filter((x) => x.p.aktiv);
  const reached = active.filter(({ p }) => data.produkte?.[p.id]?.ziel_erreicht);
  const fresh = [];
  for (const item of data.warteschlange || []) {
    if (item.art === "uebersicht" && !(await isSent(kv, item.id))) fresh.push(item);
  }
  fresh.sort((a, b) => (b.score ?? -1) - (a.score ?? -1));
  const knaller = fresh.filter((x) => x.typ === "knaller").sort((a, b) => (b.rabatt ?? 0) - (a.rabatt ?? 0));
  const deals = fresh.filter((x) => x.typ !== "knaller");

  const day = new Intl.DateTimeFormat("de-DE", { timeZone: "Europe/Berlin", weekday: "long", day: "2-digit", month: "2-digit" })
    .format(now);
  const out = [`🗓 <b>Deal-Radar – Tagesübersicht</b>\n${day} · Preise vom Lauf ${when(data.letzter_lauf)}`];
  if (reached.length) {
    out.push("\n🎯 <b>Zielpreis erreicht</b>");
    for (const { p, nr } of reached) {
      const b = data.produkte[p.id].bester;
      out.push(line(nr, p, data.produkte[p.id]) + (b?.url ? ` · <a href="${esc(b.url)}">Angebot</a>` : ""));
    }
  }
  if (knaller.length) {
    out.push("\n💥 <b>Rabattknaller</b> (nicht auf deiner Liste)");
    for (const it of knaller.slice(0, 10)) {
      out.push(`• ${esc(it.name)} – ${eur(it.preis)} € bei ${esc(it.shop)}` +
        (it.rabatt != null ? ` · −${it.rabatt} %` : "") + (it.hitze != null ? ` · 🔥 ${it.hitze}°` : "") +
        (it.url ? ` · <a href="${esc(it.url)}">Angebot</a>` : ""));
    }
    if (knaller.length > 10) out.push(`… und ${knaller.length - 10} weitere auf der Startseite`);
  }
  if (deals.length) {
    out.push("\n🔥 <b>Weitere gute Deals seit der letzten Übersicht</b>");
    for (const it of deals.slice(0, 10)) {
      out.push(`• ${esc(it.name)} – ${eur(it.preis)} € bei ${esc(it.shop)}` +
        (it.score != null ? ` · Score ${it.score}` : "") + (it.url ? ` · <a href="${esc(it.url)}">Angebot</a>` : ""));
    }
    if (deals.length > 10) out.push(`… und ${deals.length - 10} weitere auf der Startseite`);
  } else {
    out.push("\n🔥 Keine weiteren neuen Deals seit der letzten Übersicht.");
  }
  out.push("\n📋 <b>Alle Produkte</b>");
  for (const { p, nr } of active) out.push(line(nr, p, data.produkte?.[p.id]));
  const paused = products.length - active.length;
  if (paused) out.push(`⏸ ${paused} pausiert`);
  out.push(`\nDetails: /liste · <a href="${esc(env.PAGE_URL || "")}">Startseite</a>`);
  return { text: out.join("\n"), ids: fresh.map((x) => x.id) };
}

/** Wird jede volle Stunde vom Cron-Trigger aufgerufen. */
export async function hourly(deps) {
  const { gh, tg, kv, now } = deps;
  const [data, cfg, pf] = await Promise.all([loadBotData(gh), loadConfig(gh), gh.getFile("products.yaml")]);
  const result = { nachgeliefert: await releaseHeld(deps, data, cfg, now), uebersicht: false };
  const { hour, date } = localParts(now, cfg.zeitzone || "Europe/Berlin");
  const wanted = Number(String(cfg.meldungen.uebersicht_uhrzeit || "19:00").split(":")[0]);
  if (hour === wanted && !(await kv.get(`uebersicht:${date}`))) {
    const products = pf ? parseProducts(pf.text) : [];
    const { text, ids } = await buildOverview(deps, data, products, cfg, now);
    await tg.send(text);
    await kv.put(`uebersicht:${date}`, "1", { expirationTtl: 2 * 24 * 3600 });
    for (const id of ids) await markSent(kv, id);
    result.uebersicht = true;
  }
  return result;
}

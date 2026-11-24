// Deal-Radar-Bot als Cloudflare Worker (kostenloser Plan).
//
//   POST /telegram  – Webhook: Telegram schickt jede Nachricht sofort hierher
//                     (geschützt durch das Secret WEBHOOK_SECRET)
//   GET  /setup     – setzt den Webhook und registriert die Befehle (setMyCommands);
//                     kann gefahrlos mehrfach aufgerufen werden
//   Zeitplan        – alle 2 Stunden (Minute 17) einen Suchlauf auf GitHub starten;
//                     jede volle Stunde: Meldungen nach der Ruhezeit nachliefern und
//                     um 19 Uhr die Tagesübersicht schicken (src/daily.js)
//
// Secrets (per `npx wrangler secret put NAME`): TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
// GITHUB_TOKEN, WEBHOOK_SECRET. Variablen und der KV-Speicher (Binding KV) stehen in wrangler.toml.

import { handleUpdate } from "./bot.js";
import { hourly } from "./daily.js";
import { makeGitHub } from "./github.js";
import { makeTelegram, setup } from "./telegram.js";

export const HOURLY_CRON = "0 * * * *";

function deps(env) {
  return { env, gh: makeGitHub(env), tg: makeTelegram(env), kv: env.KV, fetch: (...a) => fetch(...a), now: new Date() };
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/telegram" && request.method === "POST") {
      if (request.headers.get("X-Telegram-Bot-Api-Secret-Token") !== env.WEBHOOK_SECRET) {
        return new Response("forbidden", { status: 403 });
      }
      const update = await request.json().catch(() => null);
      if (update) {
        try {
          await handleUpdate(update, deps(env));
        } catch (e) {
          console.error("Update fehlgeschlagen:", e);
        }
      }
      return new Response("ok"); // immer 200, sonst schickt Telegram das Update erneut
    }
    if (url.pathname === "/setup") {
      try {
        const info = await setup(makeTelegram(env), `${url.origin}/telegram`, env.WEBHOOK_SECRET);
        return Response.json({ ok: true, ...info });
      } catch (e) {
        return Response.json({ ok: false, fehler: String(e.message) }, { status: 500 });
      }
    }
    return new Response("Deal-Radar-Bot läuft.");
  },

  async scheduled(event, env, ctx) {
    if (event.cron === HOURLY_CRON) {
      ctx.waitUntil(hourly(deps(env)).then((r) => console.log("stündlich:", JSON.stringify(r)))
        .catch((e) => console.error("stündlich fehlgeschlagen:", e)));
      return;
    }
    ctx.waitUntil(makeGitHub(env).dispatch("zeitplan"));
  },
};

// Telegram-Bot-API: Nachrichten senden, Buttons beantworten, Befehle registrieren.

export const COMMANDS = [
  { command: "liste", description: "Alle Produkte mit Preis und Deal-Score" },
  { command: "top", description: "Die 5 besten Deals nach Deal-Score" },
  { command: "knaller", description: "💥 Rabattknaller: große Rabatte in deinen Kategorien" },
  { command: "status", description: "Letzter/nächster Lauf und Quellen" },
  { command: "neu", description: "Produkt anlegen: Shop-Link schicken oder /neu Name; Zielpreis" },
  { command: "ziel", description: "Zielpreis ändern: /ziel 3 49,99" },
  { command: "pause", description: "Produkt pausieren: /pause 3" },
  { command: "fortsetzen", description: "Pausiertes Produkt fortsetzen: /fortsetzen 3" },
  { command: "loeschen", description: "Produkt löschen: /loeschen 3" },
  { command: "weg", description: "Abgelaufenes Angebot ausblenden: /weg 3" },
  { command: "ruhe", description: "Ruhezeiten: /ruhe an, /ruhe aus oder /ruhe (Stand)" },
  { command: "ende", description: "Enddatum: /ende 24.12.2026, /ende nie oder /ende (Stand)" },
  { command: "hilfe", description: "Alle Befehle mit Beispielen" },
];

export function makeTelegram(env, fetchImpl = fetch) {
  async function call(method, params) {
    const res = await fetchImpl(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/${method}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(params),
    });
    const data = await res.json().catch(() => ({}));
    if (!data.ok) throw new Error(`Telegram ${method}: ${data.description || res.status}`);
    return data.result;
  }

  return {
    call,
    send(text, buttons) {
      const params = { chat_id: env.TELEGRAM_CHAT_ID, text, parse_mode: "HTML", disable_web_page_preview: true };
      if (buttons) params.reply_markup = { inline_keyboard: buttons };
      return call("sendMessage", params);
    },
    /** Nur die Buttons einer Nachricht ändern (z. B. nach „Gekauft“ unter einer Deal-Meldung). */
    editMarkup(messageId, buttons) {
      return call("editMessageReplyMarkup", {
        chat_id: env.TELEGRAM_CHAT_ID, message_id: messageId, reply_markup: { inline_keyboard: buttons || [] },
      });
    },
    edit(messageId, text, buttons) {
      const params = {
        chat_id: env.TELEGRAM_CHAT_ID, message_id: messageId, text, parse_mode: "HTML",
        disable_web_page_preview: true,
      };
      if (buttons) params.reply_markup = { inline_keyboard: buttons };
      return call("editMessageText", params);
    },
    answer(callbackId, text = "") {
      return call("answerCallbackQuery", { callback_query_id: callbackId, text });
    },
  };
}

/** Webhook auf diesen Worker setzen und die Befehle bei Telegram registrieren (setMyCommands). */
export async function setup(tg, webhookUrl, secret) {
  await tg.call("setWebhook", {
    url: webhookUrl,
    secret_token: secret,
    allowed_updates: ["message", "callback_query"],
  });
  await tg.call("setMyCommands", { commands: COMMANDS });
  const info = await tg.call("getWebhookInfo", {});
  return { webhook: info.url, wartend: info.pending_update_count, letzter_fehler: info.last_error_message || null };
}

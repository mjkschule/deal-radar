import { readFileSync } from "node:fs";

export const FIXTURE = readFileSync(new URL("../../tests/fixtures/products_test.yaml", import.meta.url), "utf8");

export const ENV = { TELEGRAM_CHAT_ID: "111", GITHUB_REPO: "me/repo", PAGE_URL: "https://example.org/" };

/** GitHub im Speicher: Dateien, Commits und Dispatches werden mitgeschrieben. */
export function fakeGitHub(files) {
  const store = new Map(Object.entries(files).map(([k, v]) => [k, { text: v, sha: "sha0" }]));
  let n = 0;
  return {
    store,
    commits: [],
    dispatches: [],
    conflictOnce: false,
    async getFile(path) {
      const f = store.get(path);
      return f ? { ...f } : null;
    },
    async putFile(path, text, sha, message) {
      const cur = store.get(path);
      if (this.conflictOnce || (cur && cur.sha !== sha)) {
        this.conflictOnce = false;
        const e = new Error("conflict");
        e.status = 409;
        throw e;
      }
      store.set(path, { text, sha: `sha${++n}` });
      this.commits.push({ path, message });
      return `commit${n}`;
    },
    async dispatch(grund) {
      this.dispatches.push(grund);
    },
  };
}

export function fakeTelegram() {
  return {
    sent: [],
    edited: [],
    answered: [],
    async send(text, buttons) { this.sent.push({ text, buttons }); },
    async edit(id, text) { this.edited.push({ id, text }); },
    async answer(id) { this.answered.push(id); },
  };
}

export const BOTDATA = JSON.stringify({
  letzter_lauf: "2026-11-25T10:17:00+01:00",
  enddatum: "2026-11-27T23:59+01:00",
  quellen: { mydealz: { status: "ok", anzahl: 26 }, ebay: { status: "deaktiviert", meldung: "keine Schlüssel" } },
  produkte: {
    "makita-dhp490rfx3": { bester: { effektivpreis: 184, shop: "BAUR", url: "https://x/1" }, score: 88, ziel_erreicht: true },
    "epson-et-2922": { bester: { effektivpreis: 174.99, shop: "Amazon", url: "https://x/2" }, score: 41, ziel_erreicht: false },
    "hp-deskjet-2922": { bester: null, score: null, ziel_erreicht: false },
    "opel-frontera-electric-leasing": {
      bester: { effektivpreis: 342.45, rate: 301, shop: "LeasingMarkt.de", url: "https://x/3" }, score: 60, ziel_erreicht: false,
    },
  },
});

export function deps(extraFiles = {}) {
  const gh = fakeGitHub({ "products.yaml": FIXTURE, "docs/bot.json": BOTDATA, ...extraFiles });
  const tg = fakeTelegram();
  return { gh, tg, env: ENV, now: new Date("2026-11-25T12:00:00+01:00") };
}

export const msg = (text, chatId = 111) => ({ update_id: 1, message: { chat: { id: chatId }, text } });

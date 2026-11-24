// Produkt per Shop-Link anlegen: robots.txt prüfen, Seite einmal abrufen und die
// maschinenlesbaren Produktdaten (schema.org JSON-LD) lesen: Name, EAN/GTIN, Preis.
// Kein Umgehen von Bot-Schutz: Verweigert der Shop den Abruf, sagen wir das ehrlich.

export const USER_AGENT = "DealRadar/1.0 (private Preisbeobachtung; Open-Source-Bot, max. 1 Abruf/2 Std.)";

// ---------- robots.txt (gleiche Regeln wie dealradar/robots.py) ----------

export function parseRobots(text) {
  const groups = [];
  let agents = [];
  let rules = [];
  let lastWasAgent = false;
  for (const raw of String(text).split(/\r?\n/)) {
    const line = raw.split("#")[0].trim();
    const i = line.indexOf(":");
    if (i < 0) continue;
    const key = line.slice(0, i).trim().toLowerCase();
    const value = line.slice(i + 1).trim();
    if (key === "user-agent") {
      if (!lastWasAgent && (agents.length || rules.length)) {
        groups.push([agents, rules]);
        agents = [];
        rules = [];
      }
      agents.push(value.toLowerCase());
      lastWasAgent = true;
    } else if (key === "allow" || key === "disallow") {
      lastWasAgent = false;
      if (agents.length && value) rules.push([key === "allow", value]);
    } else {
      lastWasAgent = false;
    }
  }
  if (agents.length) groups.push([agents, rules]);
  return groups;
}

function patternRegex(pattern) {
  const anchored = pattern.endsWith("$");
  const p = anchored ? pattern.slice(0, -1) : pattern;
  const rx = p.split("*").map((s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join(".*");
  return new RegExp("^" + rx + (anchored ? "$" : ""));
}

export function robotsAllows(groups, userAgent, url) {
  const token = userAgent.trim().split(/[/\s]/)[0].toLowerCase();
  const specific = groups.filter(([a]) => a.some((x) => x !== "*" && token.includes(x)));
  const rules = (specific.length ? specific : groups.filter(([a]) => a.includes("*"))).flatMap(([, r]) => r);
  const u = new URL(url);
  const path = (u.pathname || "/") + u.search;
  let bestLen = -1;
  let bestAllow = true;
  for (const [allow, pattern] of rules) {
    if (patternRegex(pattern).test(path)) {
      if (pattern.length > bestLen || (pattern.length === bestLen && allow)) {
        bestLen = pattern.length;
        bestAllow = allow;
      }
    }
  }
  return bestAllow;
}

// ---------- Produktdaten aus der Seite ----------

const decode = (s) => String(s ?? "")
  .replace(/&amp;/g, "&").replace(/&quot;/g, '"').replace(/&#0?39;|&apos;/g, "'")
  .replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&nbsp;/g, " ")
  .replace(/&#(\d+);/g, (_, n) => String.fromCharCode(Number(n)))
  .replace(/\s+/g, " ").trim();

function toNumber(raw) {
  if (raw == null) return null;
  let s = String(raw).trim().replace(/[^\d.,-]/g, "");
  if (/,\d{1,2}$/.test(s)) s = s.replace(/\./g, "").replace(",", ".");
  else s = s.replace(/,/g, "");
  const n = Number(s);
  return Number.isFinite(n) && n > 0 ? n : null;
}

function* walk(obj) {
  if (Array.isArray(obj)) {
    for (const x of obj) yield* walk(x);
  } else if (obj && typeof obj === "object") {
    yield obj;
    for (const [k, v] of Object.entries(obj)) if (k !== "@context") yield* walk(v);
  }
}

const hasType = (o, t) => [].concat(o["@type"] ?? []).some((x) => String(x).toLowerCase() === t);

function offerPrices(product) {
  const out = [];
  for (const o of walk(product.offers ?? [])) {
    if (!(hasType(o, "offer") || hasType(o, "aggregateoffer") || "price" in o || "lowPrice" in o)) continue;
    const cur = String(o.priceCurrency ?? "EUR").toUpperCase();
    if (cur && cur !== "EUR") continue;
    const price = toNumber(o.price ?? o.lowPrice ?? o.priceSpecification?.price);
    if (price == null) continue;
    let shipping = null;
    const sd = [].concat(o.shippingDetails ?? [])[0];
    const rate = sd && [].concat(sd.shippingRate ?? [])[0];
    if (rate && rate.value != null) shipping = Number(rate.value);
    out.push({ price, shipping, available: !/OutOfStock|SoldOut|Discontinued/i.test(String(o.availability ?? "")) });
  }
  return out;
}

/** { name, ean, price, shipping, available, brand } oder null. */
export function extractProduct(html) {
  for (const m of html.matchAll(/<script[^>]*application\/ld\+json[^>]*>([\s\S]*?)<\/script>/gi)) {
    let data;
    try {
      data = JSON.parse(m[1].trim());
    } catch {
      continue;
    }
    for (const node of walk(data)) {
      if (!hasType(node, "product") || !node.name) continue;
      const offers = offerPrices(node).sort((a, b) => (b.available - a.available) || a.price - b.price);
      const gtin = node.gtin13 ?? node.gtin ?? node.gtin14 ?? node.gtin12 ?? node.ean ?? node.gtin8 ?? null;
      const brand = typeof node.brand === "string" ? node.brand : node.brand?.name;
      return {
        name: decode(node.name),
        ean: gtin != null && /^\d{8,14}$/.test(String(gtin).trim()) ? String(gtin).trim() : null,
        price: offers[0]?.price ?? null,
        shipping: offers[0]?.shipping ?? null,
        available: offers[0]?.available ?? true,
        brand: brand ? decode(brand) : null,
      };
    }
  }
  // Ohne JSON-LD: Meta-Tags (og:/product:) und Microdata (itemprop) – wie dealradar/sources/shop.py
  const attrs = (attr, names) => {
    const out = [];
    for (const tag of html.matchAll(/<(?:meta|span|div|link|data)\b[^>]*>/gi)) {
      const t = tag[0];
      const n = new RegExp(`\\b${attr}=["'](${names})["']`, "i").exec(t);
      const c = /\bcontent=["']([^"']+)["']/i.exec(t);
      if (n && c) out.push(c[1]);
    }
    return out;
  };
  const name = attrs("property", "og:title")[0] ?? attrs("itemprop", "name")[0] ?? null;
  const metaPrice = toNumber(attrs("property", "product:price:amount|og:price:amount")[0]);
  // Mehrere itemprop-Preise (z. B. UVP + Angebot): der niedrigste ist der Verkaufspreis
  const micro = attrs("itemprop", "price").map(toNumber).filter((x) => x != null);
  const price = metaPrice ?? (micro.length ? Math.min(...micro) : null);
  const gtin = attrs("itemprop", "gtin13|gtin|gtin14|gtin12|gtin8|ean").find((x) => /^\d{8,14}$/.test(x.trim()));
  if (name && price) return { name: decode(name), ean: gtin?.trim() ?? null, price, shipping: null, available: true, brand: null };
  return null;
}

// ---------- Vorschläge ----------

/** Zielpreis-Vorschlag: 10 % unter dem bekannten Tiefstpreis (ganze Euro ab 20 €). */
export function suggestTarget(knownLow) {
  const v = knownLow * 0.9;
  return v >= 20 ? Math.floor(v) : Math.floor(v * 100) / 100;
}

/** Suchbegriffe aus dem Namen: Modellnummern (Buchstaben + Ziffern), sonst ein Kurzname. */
export function deriveTerms(name) {
  const words = name.replace(/[(),|–—]/g, " ").split(/\s+/).filter(Boolean);
  const models = [];
  for (const w of words) {
    const t = w.replace(/^[^\w]+|[^\w/.-]+$/g, "");
    const unit = /^\d+([.,]\d+)?(l|w|v|ah|mm|cm|kg|g|gb|tb|zoll|hz|er)$/i.test(t);
    if (t.length >= 4 && /\d/.test(t) && /[a-z]/i.test(t) && !unit) {
      const base = t.split("/")[0];
      models.push(base.length >= 4 ? base : t);
    }
  }
  // Kurze Modellnummern (z. B. "B110") passen auf zu vieles -> Marke (erstes Wort) davor
  const brand = words[0];
  const terms = [...new Set(models.map((m) => (m.length < 6 && brand && brand !== m ? `${brand} ${m}` : m)))].slice(0, 3);
  return terms.length ? terms : [words.slice(0, 4).join(" ")];
}

export const shopName = (url) => new URL(url).hostname.replace(/^www\./, "");

// ---------- Abruf ----------

export class LinkError extends Error {}

async function get(fetchImpl, url) {
  return fetchImpl(url, {
    headers: { "User-Agent": USER_AGENT, "Accept-Language": "de-DE,de;q=0.9", Accept: "text/html,*/*" },
    redirect: "follow",
    signal: AbortSignal.timeout(15000),
  });
}

/** Prüft robots.txt und liest die Produktseite. Wirft LinkError mit verständlicher Meldung. */
export async function readShopPage(url, fetchImpl = fetch) {
  let u;
  try {
    u = new URL(url);
    if (!/^https?:$/.test(u.protocol)) throw new Error();
  } catch {
    throw new LinkError("Das ist kein gültiger Link.");
  }
  const shop = shopName(u.href);
  let groups = [];
  try {
    const r = await get(fetchImpl, `${u.protocol}//${u.host}/robots.txt`);
    if (r.status === 401 || r.status === 403 || r.status >= 500) {
      throw new LinkError(`${shop} lässt seine robots.txt nicht lesen (HTTP ${r.status}) – ` +
        "dann rufe ich dort sicherheitshalber nichts ab.");
    }
    if (r.ok) groups = parseRobots(await r.text());
  } catch (e) {
    if (e instanceof LinkError) throw e;
    throw new LinkError(`${shop} ist gerade nicht erreichbar.`);
  }
  if (!robotsAllows(groups, USER_AGENT, u.href)) {
    throw new LinkError(`${shop} erlaubt laut robots.txt kein automatisches Auslesen dieser Seite.`);
  }
  let res;
  try {
    res = await get(fetchImpl, u.href);
  } catch {
    throw new LinkError(`${shop} hat nicht rechtzeitig geantwortet.`);
  }
  if (res.status === 404 || res.status === 410) {
    throw new LinkError(`Diese Seite gibt es bei ${shop} nicht (mehr) (HTTP ${res.status}). Stimmt der Link?`);
  }
  if (!res.ok) {
    throw new LinkError(`${shop} gibt die Seite nicht an Programme heraus (HTTP ${res.status}, Bot-Schutz – ` +
      "den umgehe ich nicht).");
  }
  const info = extractProduct(await res.text());
  if (!info) throw new LinkError(`Auf der Seite von ${shop} stehen keine maschinenlesbaren Produktdaten.`);
  return { ...info, url: u.href, shop };
}

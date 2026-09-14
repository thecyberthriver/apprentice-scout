/**
 * Apprentice Scout — Cloudflare Worker (instant Telegram webhook).
 *
 * /search <keyword> <state>  → returns REAL jobs with DIRECT links (straight to
 * the posting), filtered by keyword + US state, answered instantly. It searches a
 * pre-built role index (roles_index.json, refreshed by the index.yml GitHub
 * Action from jobspy + employer/ATS scrapes) — a Worker can't scrape at request
 * time, so it reads the index and filters. No third-party click-through.
 *
 * Examples:
 *   /search soc analyst NY        /search help desk texas
 *   /search security engineer     /search NY            NY
 *
 * Bindings (secrets): TELEGRAM_BOT_TOKEN, WEBHOOK_SECRET, OWNER_CHAT_ID (optional).
 */

const INDEX_URL = "https://raw.githubusercontent.com/thecyberthriver/apprentice-scout/main/roles_index.json";
const MAX_RESULTS = 12;

// abbr -> full state name
const STATES = {
  AL:"Alabama", AK:"Alaska", AZ:"Arizona", AR:"Arkansas", CA:"California",
  CO:"Colorado", CT:"Connecticut", DE:"Delaware", DC:"District of Columbia",
  FL:"Florida", GA:"Georgia", HI:"Hawaii", ID:"Idaho", IL:"Illinois",
  IN:"Indiana", IA:"Iowa", KS:"Kansas", KY:"Kentucky", LA:"Louisiana",
  ME:"Maine", MD:"Maryland", MA:"Massachusetts", MI:"Michigan", MN:"Minnesota",
  MS:"Mississippi", MO:"Missouri", MT:"Montana", NE:"Nebraska", NV:"Nevada",
  NH:"New Hampshire", NJ:"New Jersey", NM:"New Mexico", NY:"New York",
  NC:"North Carolina", ND:"North Dakota", OH:"Ohio", OK:"Oklahoma", OR:"Oregon",
  PA:"Pennsylvania", RI:"Rhode Island", SC:"South Carolina", SD:"South Dakota",
  TN:"Tennessee", TX:"Texas", UT:"Utah", VT:"Vermont", VA:"Virginia",
  WA:"Washington", WV:"West Virginia", WI:"Wisconsin", WY:"Wyoming",
};
const FULL_TO_CODE = Object.fromEntries(
  Object.entries(STATES).map(([ab, full]) => [full.toLowerCase(), ab]));

const KW = "cybersecurity apprentice OR entry level OR rotational OR help desk";
const esc = (s) => String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
const q = (s) => encodeURIComponent(s);

// In-isolate cache so most requests skip the fetch + parse.
let CACHE = { t: 0, roles: [], generated: "" };
async function getIndex() {
  const now = Date.now();
  if (now - CACHE.t < 30 * 60 * 1000 && CACHE.roles.length) return CACHE;
  try {
    const r = await fetch(INDEX_URL, { cf: { cacheTtl: 1800, cacheEverything: true } });
    const j = await r.json();
    if (Array.isArray(j.roles)) CACHE = { t: now, roles: j.roles, generated: j.generated || "" };
  } catch (e) { /* keep stale index on failure */ }
  return CACHE;
}

// Split "<keyword...> <state>" — trailing 2-letter code or full state name is the
// state; the rest is the keyword. Either part may be empty.
function parseQuery(arg) {
  arg = (arg || "").trim();
  if (!arg) return { kw: "", state: "" };
  const toks = arg.split(/\s+/);
  const last = toks[toks.length - 1].toUpperCase();
  if (/^[A-Z]{2}$/.test(last) && STATES[last]) {
    return { kw: toks.slice(0, -1).join(" ").toLowerCase(), state: last };
  }
  for (let n = Math.min(3, toks.length); n >= 1; n--) {
    const code = FULL_TO_CODE[toks.slice(-n).join(" ").toLowerCase()];
    if (code) return { kw: toks.slice(0, toks.length - n).join(" ").toLowerCase(), state: code };
  }
  return { kw: arg.toLowerCase(), state: "" };
}

function placeLinks(place) {
  const loc = STATES[place.trim().toUpperCase()] || place.trim() || "United States";
  return [
    ["Indeed", `https://www.indeed.com/jobs?q=${q(KW)}&l=${q(loc)}&fromage=7`],
    ["LinkedIn", `https://www.linkedin.com/jobs/search/?keywords=${q(KW)}&location=${q(loc)}&f_TPR=r604800`],
    ["Google Jobs", `https://www.google.com/search?ibp=htl;jobs&q=${q(KW + " jobs in " + loc + " posted this week")}`],
    ["hiring.cafe — company career pages & ATS", `https://hiring.cafe/?q=${q(KW + " " + loc)}`],
  ];
}

function roleLines(hits) {
  const out = [];
  hits.forEach((r, i) => {
    const sal = r.sal ? ` · 💰 ${esc(r.sal)}` : "";
    const loc = r.loc ? ` · ${esc(r.loc)}` : "";
    const posted = r.posted ? ` · ${esc(r.posted)}` : "";
    const src = r.src ? ` <i>(${esc(r.src)})</i>` : "";
    out.push(`${i + 1}. <a href="${esc(r.u)}"><b>${esc(r.t)}</b></a> — ${esc(r.c)}${src}`);
    out.push(`     ${esc(r.tag || "role")}${loc}${sal}${posted}`);
  });
  return out;
}

function chunk(lines, limit = 3800) {
  const out = []; let buf = [], size = 0;
  for (const ln of lines) {
    const add = ln.length + 1;
    if (buf.length && size + add > limit) { out.push(buf.join("\n")); buf = []; size = 0; }
    buf.push(ln); size += add;
  }
  if (buf.length) out.push(buf.join("\n"));
  return out;
}

async function searchBlocks(arg) {
  const { kw, state } = parseQuery(arg);
  const idx = await getIndex();
  // Whole-word matching so "soc" doesn't match "asSOCiates".
  const res = kw.split(/\s+/).filter(Boolean)
    .map((t) => new RegExp("\\b" + t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "\\b", "i"));
  const label = [kw.trim(), state ? STATES[state] : ""].filter(Boolean).join(" · ") || "everything";

  if (!idx.roles.length) {
    return [`🔎 <b>${esc(label)}</b> — the role index isn't available right now. ` +
      "Try again shortly, or tap a live search:\n" +
      placeLinks(state).map(([l, u]) => `   • <a href="${esc(u)}">${esc(l)}</a>`).join("\n")];
  }

  let hits = idx.roles.filter((r) =>
    (!state || r.st === state) && res.every((re) => re.test(r.kw || "")));
  hits = hits.slice(0, MAX_RESULTS);

  if (!hits.length) {
    return [`🔎 <b>${esc(label)}</b> — no matching roles in the current index ` +
      `(${idx.roles.length} roles, updated ${esc((idx.generated || "").slice(0, 16))}). ` +
      "Try a broader keyword or a different state, or tap a live search:\n" +
      placeLinks(state).map(([l, u]) => `   • <a href="${esc(u)}">${esc(l)}</a>`).join("\n")];
  }

  const lines = [
    `🔎 <b>${esc(label)}</b> — ${hits.length} role(s), tap the title to open the posting:`,
    `<i>Direct from job boards &amp; employer career pages · index updated ${esc((idx.generated || "").slice(0, 16))} UTC.</i>`,
    "",
  ];
  lines.push(...roleLines(hits));
  return chunk(lines);
}

const HELP =
  "🎬 <b>Apprentice Scout — search</b>\n" +
  "Type a keyword and/or a state; I return real roles with links straight to the posting.\n\n" +
  "• <code>/search soc analyst NY</code> — keyword + state\n" +
  "• <code>/search help desk texas</code>\n" +
  "• <code>/search security engineer</code> — keyword, any state\n" +
  "• <code>/search NY</code> or just <code>NY</code> — a whole state\n" +
  "• <code>/states</code> — list state codes · <code>/help</code> — this message\n\n" +
  "<i>Roles come from job boards + employer/ATS career pages, refreshed a few times a day.</i>";

async function tgSend(env, chatId, text) {
  await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendMessage`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ chat_id: chatId, text, parse_mode: "HTML",
      disable_web_page_preview: true }),
  });
}

async function handleUpdate(env, update) {
  const msg = update.message || update.edited_message;
  if (!msg || !msg.text || !msg.chat) return;
  const chatId = msg.chat.id;
  if (env.OWNER_CHAT_ID && String(chatId) !== String(env.OWNER_CHAT_ID)) return;

  const t = msg.text.trim();
  const low = t.toLowerCase();

  if (["/start", "/help", "help", "start"].includes(low)) {
    await tgSend(env, chatId, HELP);
    return;
  }
  if (["/states", "states"].includes(low)) {
    await tgSend(env, chatId, `🗺️ <b>State codes</b>\n${esc(Object.keys(STATES).sort().join(" "))}\n\n` +
      "e.g. <code>/search soc analyst TX</code>, or just <code>TX</code>.");
    return;
  }

  const isBareState = /^[a-zA-Z]{2}$/.test(t) && STATES[t.toUpperCase()];
  if (low.startsWith("/search") || isBareState) {
    const arg = isBareState ? t : t.replace(/^\/search\b/i, "").trim();
    for (const block of await searchBlocks(arg)) await tgSend(env, chatId, block);
    return;
  }

  // Bare text with no command: treat as a keyword(+state) search.
  for (const block of await searchBlocks(t)) await tgSend(env, chatId, block);
}

export default {
  async fetch(request, env, ctx) {
    if (request.method === "GET") return new Response("Apprentice Scout webhook is up.", { status: 200 });
    if (request.method !== "POST") return new Response("method not allowed", { status: 405 });
    if (env.WEBHOOK_SECRET &&
        request.headers.get("X-Telegram-Bot-Api-Secret-Token") !== env.WEBHOOK_SECRET) {
      return new Response("forbidden", { status: 401 });
    }
    let update;
    try { update = await request.json(); }
    catch { return new Response("bad request", { status: 400 }); }
    ctx.waitUntil(handleUpdate(env, update).catch((e) => console.log("handle error", e)));
    return new Response("ok", { status: 200 });
  },
};

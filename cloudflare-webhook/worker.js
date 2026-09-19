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

// Level words anywhere in the query select which index levels to show.
// Default (no level word) = entry + mid, the bot's home turf; "senior" opts in.
const LEVEL_WORDS = [
  [/\b(entry[- ]?level|entry|junior|jr)\b/gi, ["entry"]],
  [/\b(mid[- ]?level|mid|intermediate)\b/gi, ["mid"]],
  [/\b(senior|sr|lead|staff|principal)\b/gi, ["senior"]],
  [/\b(all levels|any level|all)\b/gi, ["entry", "mid", "senior"]],
];
const DEFAULT_LEVELS = ["entry", "mid"];
const MAX_AGE_MS = 30 * 24 * 60 * 60 * 1000;   // never show a role older than 30 days

// Split "<level> <keyword...> <state>" — trailing 2-letter code or full state
// name is the state; level words are pulled out; the rest is the keyword.
function parseQuery(arg) {
  arg = (arg || "").trim();
  let levels = null;
  for (const [re, lv] of LEVEL_WORDS) {
    if (re.test(arg)) { levels = [...new Set([...(levels || []), ...lv])]; arg = arg.replace(re, " "); }
    re.lastIndex = 0;
  }
  arg = arg.replace(/\s+/g, " ").trim();
  const out = { kw: "", state: "", levels: levels || DEFAULT_LEVELS, explicit: !!levels };
  if (!arg) return out;
  const toks = arg.split(/\s+/);
  const last = toks[toks.length - 1].toUpperCase();
  if (/^[A-Z]{2}$/.test(last) && STATES[last]) {
    return { ...out, kw: toks.slice(0, -1).join(" ").toLowerCase(), state: last };
  }
  for (let n = Math.min(3, toks.length); n >= 1; n--) {
    const code = FULL_TO_CODE[toks.slice(-n).join(" ").toLowerCase()];
    if (code) return { ...out, kw: toks.slice(0, toks.length - n).join(" ").toLowerCase(), state: code };
  }
  return { ...out, kw: arg.toLowerCase() };
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
    const lvl = r.lvl ? ` · ${esc(r.lvl)}` : "";
    out.push(`     ${esc(r.tag || "role")}${lvl}${loc}${sal}${posted}`);
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
  const { kw, state, levels, explicit } = parseQuery(arg);
  const idx = await getIndex();
  // Whole-word matching so "soc" doesn't match "asSOCiates".
  const res = kw.split(/\s+/).filter(Boolean)
    .map((t) => new RegExp("\\b" + t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "\\b", "i"));
  const lvlLabel = levels.length === 3 ? "all levels" : levels.join("+");
  const label = [kw.trim(), state ? STATES[state] : "", explicit ? lvlLabel : ""]
    .filter(Boolean).join(" · ") || "everything";

  if (!idx.roles.length) {
    return [`🔎 <b>${esc(label)}</b> — the role index isn't available right now. ` +
      "Try again shortly, or tap a live search:\n" +
      placeLinks(state).map(([l, u]) => `   • <a href="${esc(u)}">${esc(l)}</a>`).join("\n")];
  }

  // Hard drop for anything over 30 days (guards against a stale index if the
  // rebuild stops running). Undated rows age from the index build date.
  const cutoff = Date.now() - MAX_AGE_MS;
  const built = Date.parse(idx.generated || "") || Date.now();
  let hits = idx.roles.filter((r) =>
    (r.posted ? Date.parse(r.posted) : built) >= cutoff &&
    (!state || r.st === state) && levels.includes(r.lvl || "mid") &&
    res.every((re) => re.test(r.kw || "")));
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


// ---------------------------------------------------------------------------
// /bool — recruiter BOOLEAN search over EMPLOYER ATS rows only (Greenhouse,
// Lever, Ashby, SmartRecruiters, Workday). No LinkedIn/Indeed rows, no
// aggregators. Workers can't eval, so the string is parsed, not compiled.
// ---------------------------------------------------------------------------
const ATS_SRC = new Set(["greenhouse", "lever", "ashby", "smartrecruiters", "workday"]);

export function parseBool(query) {
  const toks = String(query).match(/"[^"]*"|\(|\)|[^\s()]+/g) || [];
  let i = 0;
  const peek = () => toks[i];
  const stop = (t) => !t || t === ")" || /^OR$/i.test(t);

  function unary() {
    if (peek() && /^NOT$/i.test(peek())) { i++; const r = unary(); return (s) => !r(s); }
    if (peek() === "(") { i++; const r = or(); if (peek() === ")") i++; return r; }
    const term = (toks[i++] || "").replace(/^"|"$/g, "").trim().toLowerCase();
    return term ? (s) => s.includes(term) : () => true;
  }
  function and() {
    let l = unary();
    for (;;) {
      let t = peek();
      if (stop(t)) break;
      if (/^AND$/i.test(t)) { i++; if (stop(peek())) break; }
      const r = unary(), a = l;
      l = (s) => a(s) && r(s);
    }
    return l;
  }
  function or() {
    let l = and();
    while (peek() && /^OR$/i.test(peek())) { i++; const r = and(), a = l; l = (s) => a(s) || r(s); }
    return l;
  }
  const f = or();
  return (s) => f(String(s).toLowerCase());
}

// The eight CISSP domains, as searchspec.CYBER_DOMAINS tags them on every role
// ("🔐 D7 SecOps · …"). /d1…/d8 filter the ATS pool on that badge.
const DOMAINS = {
  1: "Risk & GRC", 2: "Asset/Data", 3: "Sec Eng/Arch", 4: "Network Sec",
  5: "IAM", 6: "Assess/Pentest", 7: "SecOps", 8: "AppSec",
};
const LEVELS = ["entry", "mid", "senior"];

// Pull leading level words off a command argument: "/d7 entry mid soc" →
// levels {entry,mid}, rest "soc". No level word = every level (entry→senior).
export function splitLevels(arg) {
  const words = (arg || "").trim().split(/\s+/).filter(Boolean);
  const levels = new Set();
  while (words.length) {
    const w = words[0].toLowerCase().replace(/[-_]?level$/, "");
    if (w === "all") { words.shift(); levels.clear(); break; }
    const hit = { entry: "entry", junior: "entry", jr: "entry", mid: "mid",
                  intermediate: "mid", senior: "senior", sr: "senior" }[w];
    if (!hit) break;
    levels.add(hit);
    words.shift();
  }
  return { levels: levels.size ? levels : null, rest: words.join(" ") };
}

// opts: { levels: Set|null, domain: 1-8|null, cmd: label for the usage text }
export async function boolBlocks(query, { levels = null, domain = null, cmd = "/bool" } = {}) {
  const scope = levels ? [...LEVELS].filter((l) => levels.has(l)).join("+") : "entry→senior";
  const dom = domain ? `D${domain} ${DOMAINS[domain]}` : "";
  if (!query && !domain) {
    return [`🔠 <b>${cmd}</b> — boolean search across employer ATS boards only (${esc(scope)}).\n\n` +
      `<code>${cmd} (soc OR siem OR "incident response") AND (analyst OR engineer)</code>\n\n` +
      "Supports <code>AND</code> <code>OR</code> <code>NOT</code>, parentheses and " +
      "<code>\"quoted phrases\"</code>; terms match title, company, location and level " +
      "(so <code>NY</code> works as a term, and on <code>/bool</code> so do " +
      "<code>entry</code>, <code>mid</code>, <code>senior</code>).\n\n" +
      "<code>/domains</code> — the same search by CISSP domain."];
  }
  const idx = await getIndex();
  if (!idx.roles.length) return ["🔠 The role index isn't available right now — try again shortly."];
  const match = query ? parseBool(query) : () => true;
  const cutoff = Date.now() - MAX_AGE_MS;
  const built = Date.parse(idx.generated || "") || Date.now();
  const pool = idx.roles.filter((r) =>
    ATS_SRC.has((r.src || "").toLowerCase()) &&
    (!levels || levels.has(r.lvl || "mid")) &&
    (!domain || new RegExp(`\\bD${domain}\\b`).test(r.tag || "")));
  const hits = pool.filter((r) =>
    (r.posted ? Date.parse(r.posted) : built) >= cutoff &&
    // Title + company + location + level ONLY. Deliberately not r.kw: its tag
    // text says "Entry-level" on every ATS row, so `entry` there matched mids.
    match(`${r.t || ""} ${r.c || ""} ${r.loc || ""} ${r.st || ""} ${r.lvl || ""}`)
  ).slice(0, MAX_RESULTS);

  const atsTotal = pool.length;
  const what = [dom, scope].filter(Boolean).join(" · ");
  if (!hits.length) {
    return [`🔠 <b>ATS boolean search — ${esc(what)}</b> — no match in ${atsTotal} employer-ATS ` +
      `roles (index ${esc((idx.generated || "").slice(0, 16))} UTC).\n` +
      (query ? `<code>${esc(query)}</code>\n\n` : "\n") +
      "Widen the string (more <code>OR</code>s), drop a <code>NOT</code>, or open the level " +
      "up (<code>all</code>)."];
  }
  const lines = [
    `🔠 <b>ATS boolean search — ${esc(what)}</b> — ${hits.length} of ${atsTotal} employer-ATS roles:`,
    ...(query ? [`<code>${esc(query)}</code>`] : []),
    `<i>Greenhouse · Lever · Ashby · SmartRecruiters · Workday only — the employer's own ` +
    `posting, no aggregators. Index ${esc((idx.generated || "").slice(0, 16))} UTC.</i>`,
    "",
  ];
  lines.push(...roleLines(hits));
  return chunk(lines);
}

// /domains — what's actually on the employer ATS boards right now, by CISSP
// domain and level, with the command to open each one.
export async function domainsBlocks() {
  const idx = await getIndex();
  const pool = idx.roles.filter((r) => ATS_SRC.has((r.src || "").toLowerCase()));
  const lines = [
    "🔐 <b>The eight CISSP domains — employer ATS roles</b>",
    `<i>entry / mid / senior · ${pool.length} roles · index ${esc((idx.generated || "").slice(0, 16))} UTC.</i>`,
    "",
  ];
  for (const n of Object.keys(DOMAINS)) {
    const rx = new RegExp(`\\bD${n}\\b`);
    const rows = pool.filter((r) => rx.test(r.tag || ""));
    const counts = LEVELS.map((l) => rows.filter((r) => (r.lvl || "mid") === l).length);
    lines.push(`<code>/d${n}</code> <b>D${n} ${esc(DOMAINS[n])}</b> — ${counts.join(" / ")}`);
  }
  lines.push("");
  lines.push("<code>/d7</code> every level · <code>/d7 entry</code> · <code>/d3 senior</code> · " +
    "<code>/d5 mid senior</code>");
  lines.push("Add a boolean string to narrow: <code>/d7 entry (remote OR ny) NOT clearance</code>");
  return chunk(lines);
}

const HELP =
  "🎬 <b>Apprentice Scout — search</b>\n" +
  "Type a keyword and/or a state; I return real roles with links straight to the posting.\n\n" +
  "• <code>/search soc analyst NY</code> — keyword + state\n" +
  "• <code>/search help desk texas</code>\n" +
  "• <code>/search security engineer</code> — keyword, any state\n" +
  "• <code>/search NY</code> or just <code>NY</code> — a whole state\n" +
  "• <code>/bool (soc OR siem) AND analyst</code> — boolean, employer ATS only, every level\n" +
  "• <code>/boolsr …</code> — same string, mid + senior only\n" +
  "• <code>/domains</code> — the eight CISSP domains, then <code>/d7</code>, " +
  "<code>/d7 entry</code>, <code>/d3 senior</code>\n" +
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

// /tailor <url> -> kick the private resume-tailor GitHub Action; it sends the
// report back to this chat itself. Needs secret GITHUB_DISPATCH_TOKEN (actions:write
// on thecyberthriver/resume-tailor).
async function tailor(env, chatId, arg) {
  const url = (arg || "").split(/\s+/)[0];
  if (!/^https?:\/\/\S+$/i.test(url)) {
    await tgSend(env, chatId, "Usage: <code>/tailor https://…posting url…</code>");
    return;
  }
  if (!env.GITHUB_DISPATCH_TOKEN) {
    await tgSend(env, chatId, "⚠️ /tailor isn't wired up: GITHUB_DISPATCH_TOKEN secret missing on the worker.");
    return;
  }
  const r = await fetch("https://api.github.com/repos/thecyberthriver/resume-tailor/actions/workflows/tailor.yml/dispatches", {
    method: "POST",
    headers: { authorization: `Bearer ${env.GITHUB_DISPATCH_TOKEN}`, accept: "application/vnd.github+json",
      "content-type": "application/json", "user-agent": "apprentice-scout-bot" },
    body: JSON.stringify({ ref: "main", inputs: { url } }),
  });
  await tgSend(env, chatId, r.status === 204
    ? `🧵 Tailoring against <a href="${esc(url)}">this posting</a> — report lands here in about a minute.`
    : `⚠️ GitHub refused the dispatch (HTTP ${r.status}). Check the GITHUB_DISPATCH_TOKEN secret.`);
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

  if (["/domains", "domains"].includes(low)) {
    for (const block of await domainsBlocks()) await tgSend(env, chatId, block);
    return;
  }

  // /boolsr first — /bool is a prefix of it.
  if (low.startsWith("/boolsr")) {
    const blocks = await boolBlocks(t.replace(/^\/boolsr\b/i, "").trim(),
      { levels: new Set(["mid", "senior"]), cmd: "/boolsr" });
    for (const block of blocks) await tgSend(env, chatId, block);
    return;
  }

  if (low.startsWith("/bool")) {
    for (const block of await boolBlocks(t.replace(/^\/bool\b/i, "").trim())) await tgSend(env, chatId, block);
    return;
  }

  // /d1 … /d8 — one CISSP domain, optional leading level words, optional string.
  const dm = /^\/d([1-8])\b/i.exec(t);
  if (dm) {
    const { levels, rest } = splitLevels(t.slice(dm[0].length));
    const blocks = await boolBlocks(rest, { levels, domain: Number(dm[1]), cmd: dm[0].toLowerCase() });
    for (const block of blocks) await tgSend(env, chatId, block);
    return;
  }

  if (low.startsWith("/tailor")) {
    await tailor(env, chatId, t.replace(/^\/tailor\b/i, "").trim());
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

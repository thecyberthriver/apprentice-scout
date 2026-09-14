/**
 * Apprentice Scout — Cloudflare Worker (instant Telegram webhook).
 *
 * Answers /search, /states and /help the moment you send them (no 5-min poll).
 * Telegram POSTs each update here; we reply immediately with tap-through links
 * that open STRAIGHT to the filtered roles — same GoWild-style deep-link pattern.
 *
 * A Worker can't run python-jobspy, so the interactive reply is links-only (like
 * GoWild): tapping opens Indeed / LinkedIn / Google Jobs pre-filtered to the
 * place, early-career cyber/tech, last 7 days. The full scraped role list still
 * arrives in the twice-weekly digest (schedule.yml). Mirrors place_links() in
 * searchspec.py.
 *
 * Bindings (set via wrangler / dashboard):
 *   - TELEGRAM_BOT_TOKEN  (secret)  bot token
 *   - WEBHOOK_SECRET      (secret)  matches Telegram's setWebhook secret_token
 *   - OWNER_CHAT_ID       (var)     optional; if set, only this chat is answered
 */

// abbr -> full state name (mirrors US_STATES in searchspec.py)
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

// Broad enough to catch apprenticeships, early-career AND career-changer roles.
const KW = "cybersecurity apprentice OR entry level OR rotational OR help desk";

const esc = (s) => String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
const q = (s) => encodeURIComponent(s);

// Free text: a state code/name OR a city ("Austin", "New York, NY"). A 2-letter
// code or state name is expanded to the full state name for the URLs.
function placeLinks(place) {
  const loc = STATES[place.trim().toUpperCase()] || place.trim();
  return [
    ["Indeed — opens the filtered results",
      `https://www.indeed.com/jobs?q=${q(KW)}&l=${q(loc)}&fromage=7`],
    ["LinkedIn — last 7 days",
      `https://www.linkedin.com/jobs/search/?keywords=${q(KW)}&location=${q(loc)}&f_TPR=r604800`],
    ["Google Jobs",
      `https://www.google.com/search?ibp=htl;jobs&q=${q(KW + " jobs in " + loc + " posted this week")}`],
    ["hiring.cafe — company career pages & ATS",
      `https://hiring.cafe/?q=${q(KW + " " + loc)}`],
  ];
}

function searchReply(label, place) {
  const lines = [
    `🔎 <b>${esc(label)}</b> — tap to jump straight to the roles ` +
      "(paid apprentice / entry-level / rotational / help-desk, last 7 days):",
    "",
  ];
  for (const [lbl, url] of placeLinks(place)) {
    lines.push(`   • <a href="${esc(url)}">${esc(lbl)}</a>`);
  }
  lines.push("");
  lines.push("<i>The full scraped list (with pay) lands in the twice-weekly digest.</i>");
  return lines.join("\n");
}

const HELP =
  "🎬 <b>Apprentice Scout — search commands</b>\n" +
  "• <code>/search NY</code> — a <b>state</b>. Instant tap-through links to the filtered results.\n" +
  "• <code>/search Austin</code> or <code>/search Austin, TX</code> — a <b>city</b>.\n" +
  "• <code>/search</code> — nationwide.\n" +
  "• Shortcut: just send a 2-letter state code, e.g. <code>TX</code>.\n" +
  "• <code>/states</code> — list valid state codes.\n" +
  "• <code>/help</code> — this message.\n\n" +
  "<i>Tap a link to open the boards pre-filtered to your place — instant, no waiting.</i>";

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

  if (["/start","/help","help","start"].includes(low)) {
    await tgSend(env, chatId, HELP);
    return;
  }
  if (["/states","states"].includes(low)) {
    const codes = Object.keys(STATES).sort().join(" ");
    await tgSend(env, chatId, `🗺️ <b>State codes</b>\n${esc(codes)}\n\n` +
      "Search one with <code>/search TX</code>, a city with <code>/search Austin</code>, or just <code>TX</code>.");
    return;
  }

  // /search [place]  OR  a bare 2-letter state code as a shortcut.
  const isBareState = /^[a-zA-Z]{2}$/.test(t) && STATES[t.toUpperCase()];
  if (low.startsWith("/search") || isBareState) {
    let arg;
    if (isBareState) {
      arg = t;
    } else {
      const i = t.indexOf(" ");
      arg = i === -1 ? "" : t.slice(i + 1).trim();
    }
    let label, place;
    if (!arg) {
      label = "United States"; place = "United States";
    } else {
      const full = STATES[arg.toUpperCase()];
      label = full || arg;     // else use the city as typed
      place = full || arg;
    }
    await tgSend(env, chatId, searchReply(label, place));
    return;
  }

  await tgSend(env, chatId,
    "Send <code>/search NY</code> (a state), <code>/search Austin</code> (a city), " +
    "or just <code>NY</code>. <code>/help</code> for more.");
}

export default {
  async fetch(request, env, ctx) {
    if (request.method === "GET") {
      return new Response("Apprentice Scout webhook is up.", { status: 200 });
    }
    if (request.method !== "POST") {
      return new Response("method not allowed", { status: 405 });
    }
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

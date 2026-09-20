// node worker.test.mjs — webhook command handling, offline.
//
// Nothing here touches Telegram or GitHub: global fetch is stubbed, so the
// index comes from a fixture and every "reply" is captured instead of sent.
import assert from "node:assert";
import { handleUpdate, _resetSeenUpdates, seenUpdate } from "./worker.js";

const INDEX = {
  generated: new Date().toISOString(),
  roles: [
    { t: "SOC Analyst I", c: "Motorola", u: "https://ats.example/1", lvl: "entry",
      loc: "Schaumburg, IL", st: "IL", sal: "", posted: today(), src: "workday",
      tag: "🔐 D7 SecOps · Entry-level", kw: "soc analyst i motorola 🔐 d7 secops cyber entry" },
    { t: "Security Engineer", c: "Acme", u: "https://ats.example/2", lvl: "mid",
      loc: "New York, NY", st: "NY", sal: "", posted: today(), src: "greenhouse",
      tag: "🔐 D3 Sec Eng/Arch · Mid-level", kw: "security engineer acme 🔐 d3 sec eng arch cyber mid" },
    { t: "Staff Security Engineer", c: "Bcme", u: "https://ats.example/3", lvl: "senior",
      loc: "Remote", st: "", sal: "", posted: today(), src: "lever",
      tag: "🔐 D3 Sec Eng/Arch · Senior", kw: "staff security engineer bcme 🔐 d3 sec eng arch cyber senior" },
    { t: "Help Desk Technician", c: "Ccme", u: "https://ats.example/4", lvl: "entry",
      loc: "Austin, TX", st: "TX", sal: "", posted: today(), src: "linkedin",
      tag: "💻 Tech · Entry-level", kw: "help desk technician ccme 💻 tech entry" },
  ],
};

function today() { return new Date().toISOString().slice(0, 10); }

// --- stub the network -------------------------------------------------------
let sent = [];      // every sendMessage the worker attempted
let tgStatus = 200; // what Telegram "returns"

globalThis.fetch = async (url, opts = {}) => {
  const u = String(url);
  if (u.includes("raw.githubusercontent.com")) {
    return { ok: true, json: async () => INDEX };
  }
  if (u.includes("api.telegram.org")) {
    sent.push(JSON.parse(opts.body || "{}"));
    return { ok: tgStatus === 200, status: tgStatus,
             json: async () => ({ ok: tgStatus === 200, description: "Forbidden: bot was blocked" }) };
  }
  throw new Error("unexpected fetch to " + u);
};

const ENV = { TELEGRAM_BOT_TOKEN: "test-token-never-logged" };

function msg(text, { id = 1, chat = 4242 } = {}) {
  return { update_id: id, message: { message_id: id, chat: { id: chat, type: "private" }, text } };
}

async function run(text, opts) {
  sent = [];
  await handleUpdate(ENV, msg(text, opts));
  return sent.map((s) => s.text).join("\n\n");
}

function reset() { _resetSeenUpdates(); tgStatus = 200; sent = []; }

// --- the four commands that must keep working -------------------------------
async function test_help() {
  reset();
  const out = await run("/help");
  assert(out.includes("Apprentice Scout"), out);
  assert(out.includes("/search"), "help must still document /search");
  assert(out.includes("/bool"), "help must still document /bool");
  assert(out.includes("/domains"), "help must still document /domains");
}

async function test_states() {
  reset();
  const out = await run("/states");
  assert(out.includes("NY") && out.includes("TX") && out.includes("CA"), out);
  assert(out.includes("State codes"), out);
}

async function test_search_by_state() {
  reset();
  const out = await run("/search security engineer NY");
  assert(out.includes("Security Engineer"), out);
  assert(out.includes("https://ats.example/2"), "must link the employer posting");
  assert(!out.includes("Help Desk Technician"), "TX role must not answer a NY search");
}

async function test_bare_state_shortcut() {
  reset();
  const out = await run("NY");
  assert(out.includes("Security Engineer"), out);
}

async function test_bool_is_ats_only() {
  reset();
  const out = await run("/bool security AND engineer");
  assert(out.includes("Security Engineer"), out);
  assert(!out.includes("Help Desk Technician"), "/bool must exclude the linkedin-sourced row");
}

async function test_boolsr_levels() {
  reset();
  const out = await run("/boolsr security");
  assert(out.includes("Staff Security Engineer"), out);
  assert(!out.includes("SOC Analyst I"), "/boolsr must exclude entry level");
}

async function test_domains_overview() {
  reset();
  const out = await run("/domains");
  assert(out.includes("D7 SecOps") && out.includes("D3 Sec Eng/Arch"), out);
  assert(out.includes("/d7"), "each domain must show its command");
}

async function test_domain_command() {
  reset();
  const out = await run("/d7");
  assert(out.includes("SOC Analyst I"), out);
  assert(!out.includes("Staff Security Engineer"), "D3 role must not answer /d7");
}

async function test_unknown_text_falls_back_to_search() {
  reset();
  const out = await run("security engineer");
  assert(out.length > 0, "bare keywords must still answer");
}

// --- duplicate updates ------------------------------------------------------
async function test_duplicate_update_is_answered_once() {
  reset();
  await handleUpdate(ENV, msg("/help", { id: 77 }));
  const first = sent.length;
  assert(first > 0, "first delivery must answer");
  await handleUpdate(ENV, msg("/help", { id: 77 }));   // Telegram re-delivery
  assert.equal(sent.length, first, "a repeated update_id must not answer twice");
}

async function test_distinct_updates_both_answered() {
  reset();
  await handleUpdate(ENV, msg("/help", { id: 1 }));
  const first = sent.length;
  await handleUpdate(ENV, msg("/help", { id: 2 }));
  assert(sent.length > first, "different update_ids are different commands");
}

// --- delivery + safety ------------------------------------------------------
async function test_failed_delivery_does_not_throw() {
  reset();
  tgStatus = 403;                       // recipient blocked the bot
  await handleUpdate(ENV, msg("/help", { id: 5 }));
  assert(sent.length > 0, "it must still attempt delivery");   // and not crash the isolate
}

async function test_owner_lock_ignores_strangers() {
  reset();
  sent = [];
  await handleUpdate({ ...ENV, OWNER_CHAT_ID: "4242" }, msg("/help", { id: 9, chat: 9999 }));
  assert.equal(sent.length, 0, "a locked bot must ignore other chats");
}

async function test_non_text_update_ignored() {
  reset();
  await handleUpdate(ENV, { update_id: 11, message: { chat: { id: 1 }, photo: [{}] } });
  assert.equal(sent.length, 0);
}

async function test_seen_update_set_is_bounded() {
  reset();
  for (let i = 0; i < 700; i++) seenUpdate(i);
  assert.equal(seenUpdate(699), true, "recent ids stay remembered");
  assert.equal(seenUpdate(0), false, "oldest ids are evicted, not leaked forever");
}

async function test_no_token_in_replies() {
  reset();
  const out = await run("/help");
  assert(!out.includes(ENV.TELEGRAM_BOT_TOKEN), "TOKEN LEAKED INTO A REPLY");
}

const TESTS = [test_help, test_states, test_search_by_state, test_bare_state_shortcut,
  test_bool_is_ats_only, test_boolsr_levels, test_domains_overview, test_domain_command,
  test_unknown_text_falls_back_to_search, test_duplicate_update_is_answered_once,
  test_distinct_updates_both_answered, test_failed_delivery_does_not_throw,
  test_owner_lock_ignores_strangers, test_non_text_update_ignored,
  test_seen_update_set_is_bounded, test_no_token_in_replies];

let failed = 0;
for (const t of TESTS) {
  try {
    await t();
    console.log(`  ok   ${t.name}`);
  } catch (e) {
    failed++;
    console.log(`  FAIL ${t.name}: ${e.message}`);
  }
}
console.log(`\n${TESTS.length - failed}/${TESTS.length} passed`);
process.exit(failed ? 1 : 0);

// node bool.test.mjs — check the /bool string parser (Workers can't eval, so it's hand-rolled).
import assert from "node:assert";
import { parseBool } from "./worker.js";

const m = parseBool('(soc OR siem OR "incident response") AND (analyst OR engineer) NOT senior');
assert(m("SOC Analyst I · entry · Motorola"));
assert(m("Incident Response Engineer"));
assert(!m("Senior SOC Analyst"));          // NOT senior
assert(!m("SOC Manager"));                 // needs analyst|engineer
assert(!m("Data Analyst"));                // needs soc|siem|phrase

assert(parseBool("security analyst")("Security Analyst"));            // implicit AND
assert(!parseBool("security analyst")("Security Engineer"));
assert(parseBool('"help desk"')("IT Help Desk Technician"));
assert(!parseBool('"help desk"')("Help Support Desk"));               // phrase, not two words
assert(parseBool("NOT senior")("SOC Analyst"));
assert(parseBool("entry AND (ny OR nj)")("SOC Analyst entry New York, NY"));
assert(!parseBool("entry AND (ny OR nj)")("SOC Analyst entry Austin, TX"));
assert(parseBool("")("anything"));                                     // empty = match all
assert(parseBool("a OR b AND c")("a"));                                // AND binds tighter
assert(!parseBool("a OR b AND c")("b"));
console.log("bool parser ok");

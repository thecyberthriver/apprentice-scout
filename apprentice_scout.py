#!/usr/bin/env python3
"""
apprentice_scout.py — LIVE paid-apprenticeship / early-career cyber & tech job
scout that feeds your TikTok content calendar.

Sibling to fare_watcher.py, gowild_scout.py, and tech_networking_scout.py, but
this one does real scraping: each run it queries the job boards DIRECTLY
(LinkedIn, Google Jobs, ZipRecruiter — no aggregator / referral third party)
for PAID apprenticeships, ROTATIONAL / leadership-development programs, and
early-career cybersecurity & tech roles POSTED IN THE LAST 7 DAYS, then:

  1. Filters to paid + early-career + cyber/tech (see searchspec.py scoring).
  2. Drops anything senior/unpaid and de-dupes against seen.json so you don't
     film the same role two weeks running.
  3. Ranks the best N and sends a Telegram digest built as a FILM-READY brief:
       • a headline count ("N paid roles posted this week")
       • a numbered, screen-recordable list (title · company · tag · posted)
       • a rotating TikTok video HOOK + caption tip (job videos do well for you)
       • one educational APPLY tip so the video teaches, not just lists
  4. Optional: Claude Haiku drafts a ready-to-read TikTok script + caption.
     Degrades gracefully if no ANTHROPIC_API_KEY is set.

HONESTY: this reads public job-board listings only; it does not apply for you
and does not invent postings. Confirm each role on its link before filming.

Run --preview to print to console (no Telegram, no de-dupe write).
Runs WEEKLY (Task Scheduler) via pythonw (silent). See register_task.ps1.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from datetime import date, datetime
from pathlib import Path

import requests

import searchspec as SPEC

# Windows consoles default to cp1252 and choke on emoji / em-dashes. Force
# UTF-8 so --preview and logging never crash. Telegram gets clean UTF-8 via JSON.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

# ---------------------------------------------------------------------------
# CONFIG — edit these
# ---------------------------------------------------------------------------

import os

# Telegram — real values live in secrets_local.py (untracked); placeholders here.
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "CHANGE-ME:paste-token-from-BotFather")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "CHANGE-ME-chat-id")

# Search scope.
LOCATION = "United States"          # default jobspy location (nationwide)
STATE = ""                          # set to a full state name to scope the scrape;
                                    # usually set at runtime via `--state XX`. Empty = nationwide.
HOURS_OLD = 168                     # 168h = last 7 days ("within the last week")
RESULTS_PER_QUERY = 25              # per board, per query pass (scheduled digest)
SEARCH_RESULTS_PER_QUERY = 12       # lighter pass for on-demand /search replies
MAX_PICKS = 8                       # main early-career roles in the digest
MAX_TRANSITION = 5                  # career-changer roles in the digest
SEARCH_MAX_PICKS = 10               # main roles in an on-demand /search reply
SEARCH_MAX_TRANSITION = 6           # career-changer roles in a /search reply

# Minimum combined score to keep a role in each section.
MIN_SCORE = 6                       # main: early-career + tech/cyber + paid
MIN_TRANS_SCORE = 5                 # career-changer: transition + tech/cyber + paid

# Anti-repeat: remember this many recently-featured role keys.
RECENT_MEMORY = 120

# --- Claude script/caption writer (optional) -------------------------------
USE_LLM = True
CLAUDE_MODEL = "claude-haiku-4-5"
CLAUDE_TIMEOUT = 30
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
LLM_SYSTEM = ("You help a cybersecurity creator make short-form TikTok videos about "
              "breaking into tech/cyber. Reply with ONLY compact JSON, no prose.")

# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
SEEN_FILE = BASE_DIR / "seen.json"
LOG_FILE = BASE_DIR / "apprentice_scout.log"

# Load secrets (untracked) — overrides the CHANGE-ME placeholders above.
try:
    import secrets_local as _secrets
    if "CHANGE-ME" in TELEGRAM_BOT_TOKEN:
        TELEGRAM_BOT_TOKEN = getattr(_secrets, "TELEGRAM_BOT_TOKEN", TELEGRAM_BOT_TOKEN)
    if "CHANGE-ME" in TELEGRAM_CHAT_ID:
        TELEGRAM_CHAT_ID = getattr(_secrets, "TELEGRAM_CHAT_ID", TELEGRAM_CHAT_ID)
    if not ANTHROPIC_API_KEY:
        ANTHROPIC_API_KEY = getattr(_secrets, "ANTHROPIC_API_KEY", "")
except ImportError:
    pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def log(msg: str) -> None:
    line = f"{datetime.now().isoformat(timespec='seconds')}  {msg}"
    print(line)
    try:
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def load_seen() -> dict:
    if SEEN_FILE.exists():
        try:
            return json.loads(SEEN_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"role_keys": [], "hook_recent": [], "tip_recent": []}


def save_seen(seen: dict) -> None:
    seen["role_keys"] = seen.get("role_keys", [])[-RECENT_MEMORY:]
    try:
        SEEN_FILE.write_text(json.dumps(seen, indent=2), encoding="utf-8")
    except OSError as e:
        log(f"WARN could not write seen cache: {e}")


def _day_seed(salt: str) -> int:
    h = hashlib.md5(f"{date.today().isoformat()}-{salt}".encode()).hexdigest()
    return int(h[:8], 16)


def rotate_pick(items: list[str], recent: list[str], salt: str) -> str:
    """Deterministic-per-day pick that avoids recently-used items."""
    fresh = [x for x in items if x not in recent] or list(items)
    return fresh[_day_seed(salt) % len(fresh)]


def role_key(title: str, company: str) -> str:
    norm = re.sub(r"[^a-z0-9]+", " ", f"{company} {title}".lower()).strip()
    return hashlib.md5(norm.encode()).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Scraping (jobspy) + filtering / scoring
# ---------------------------------------------------------------------------

def scrape_all(location: str | None = None, results_per_query: int | None = None) -> list[dict]:
    """Run every query in searchspec across the configured boards. Each pass is
    isolated so one board/query failing (rate limit, network) never kills the
    run. Returns a de-duplicated list of raw role dicts.

    location / results_per_query override the module defaults — used by the
    on-demand /search command to scope a live search to a single state."""
    try:
        from jobspy import scrape_jobs
    except ImportError:
        log("ERROR python-jobspy not installed. Run: pip install python-jobspy")
        return []

    seen_urls: set[str] = set()
    roles: list[dict] = []
    location = location or STATE or LOCATION
    rpq = results_per_query or RESULTS_PER_QUERY

    for q in SPEC.QUERIES:
        try:
            df = scrape_jobs(
                site_name=SPEC.SITES,
                search_term=q["search_term"],
                google_search_term=q["google_search_term"],
                location=location,
                results_wanted=rpq,
                hours_old=HOURS_OLD,
                linkedin_fetch_description=False,
                country_indeed="USA",
                verbose=0,
            )
        except Exception as e:  # noqa: BLE001
            log(f"WARN query '{q['tag']}' failed: {e}")
            continue

        if df is None or len(df) == 0:
            continue

        for _, row in df.iterrows():
            url = str(row.get("job_url") or "").strip()
            title = str(row.get("title") or "").strip()
            company = str(row.get("company") or "").strip()
            if not title or not company:
                continue
            dedupe = url or role_key(title, company)
            if dedupe in seen_urls:
                continue
            seen_urls.add(dedupe)

            desc = row.get("description")
            posted = row.get("date_posted")
            roles.append({
                "title": title,
                "company": company,
                "url": url,
                "site": str(row.get("site") or "").strip(),
                "location": str(row.get("location") or "").strip(),
                "posted": None if posted is None or str(posted).lower() in ("nat", "nan", "none", "") else str(posted)[:10],
                "desc": "" if desc is None else str(desc),
                "query_tag": q["tag"],
            })

    log(f"scraped {len(roles)} unique roles across {len(SPEC.QUERIES)} queries / "
        f"{SPEC.SITES} / location={location}")
    return roles


def _kw_score(text: str, table: dict) -> tuple[int, list[str]]:
    score, hits = 0, []
    for kw, w in table.items():
        if kw in text:
            score += w
            hits.append(kw.strip())
    return score, hits


def classify_role(role: dict) -> dict | None:
    """Score a role for tech/cyber fit and decide which section(s) it belongs to:
    the main early-career list and/or the career-changer list. Enriches the role
    in place and returns it, or None if it doesn't qualify for either."""
    hay = f" {role['title'].lower()} {role['desc'].lower()} "

    # Hard blocks first.
    if any(b in hay for b in SPEC.UNPAID_BLOCK):
        return None
    # Drop third-party reposters/aggregators — we want the real employer.
    company_l = role["company"].lower()
    if any(x in company_l for x in SPEC.EXCLUDE_COMPANIES):
        return None

    tech, _ = _kw_score(hay, SPEC.TECH_CYBER)
    if tech == 0:
        return None  # must be tech/cyber to matter at all

    early, early_hits = _kw_score(hay, SPEC.EARLY_CAREER)
    trans, trans_hits = _kw_score(hay, SPEC.TRANSITION_SIGNALS)
    if early == 0 and trans == 0:
        return None

    # Senior titles are out unless a strong entry signal is present.
    title_l = role["title"].lower()
    strong_entry = any(k in title_l for k in
                       ("apprentice", "rotational", "new grad", "new graduate",
                        "early career", "early talent", "graduate program",
                        "development program", "entry level", "entry-level", "trainee",
                        "help desk", "service desk", "it support", "skillbridge"))
    if any(b in f" {title_l} " for b in SPEC.SENIOR_BLOCK) and not strong_entry:
        return None

    paid, _ = _kw_score(hay, SPEC.PAID_BOOST)

    role["tag"] = _display_tag(early_hits, tech)
    role["trans_tag"] = _transition_tag(trans_hits, tech)
    role["main_score"] = early + tech + paid
    role["trans_score"] = trans + tech + paid
    role["is_main"] = early > 0 and role["main_score"] >= MIN_SCORE
    role["is_trans"] = trans > 0 and role["trans_score"] >= MIN_TRANS_SCORE
    if not (role["is_main"] or role["is_trans"]):
        return None
    return role


def _display_tag(early_hits: list[str], tech_score: int) -> str:
    domain = "🔐 Cyber" if tech_score >= 4 else "💻 Tech"
    if any("apprentice" in h for h in early_hits):
        kind = "Apprenticeship"
    elif any(h in ("rotational", "rotation", "development program",
                   "leadership development program", "ldp") for h in early_hits):
        kind = "Rotational / LDP"
    elif any(h in ("new grad", "new graduate", "graduate program",
                   "early career", "early talent", "recent graduate") for h in early_hits):
        kind = "New-grad program"
    else:
        kind = "Entry-level"
    return f"{domain} · {kind}"


def _transition_tag(trans_hits: list[str], tech_score: int) -> str:
    domain = "🔐 Cyber" if tech_score >= 4 else "💻 Tech"
    h = set(trans_hits)
    if h & {"skillbridge", "veteran", "transitioning military", "military"}:
        kind = "Veteran / SkillBridge"
    elif h & {"returnship", "return to work", "relaunch", "career reentry"}:
        kind = "Returnship / re-entry"
    elif h & {"help desk", "service desk", "it support", "technical support"}:
        kind = "Help-desk on-ramp"
    elif h & {"no experience", "no prior experience", "willing to train",
              "we will train", "we'll train", "train you", "on-the-job training",
              "no degree", "without a degree", "degree not required"}:
        kind = "No-degree / will-train"
    else:
        kind = "Career-changer friendly"
    return f"{domain} · {kind}"


def rank_and_dedupe(roles: list[dict], recent_keys: list[str],
                    max_main: int = MAX_PICKS,
                    max_trans: int = MAX_TRANSITION) -> tuple[list[dict], list[dict]]:
    """Return (main_picks, transition_picks). A role appears in at most one list;
    the main early-career list takes precedence over the career-changer list."""
    classified = [r for r in (classify_role(x) for x in roles) if r]
    fresh = [r for r in classified if role_key(r["title"], r["company"]) not in recent_keys]

    main = [r for r in fresh if r.get("is_main")]
    main.sort(key=lambda r: r["main_score"], reverse=True)
    main = main[:max_main]
    main_keys = {role_key(r["title"], r["company"]) for r in main}

    trans = [r for r in fresh if r.get("is_trans")
             and role_key(r["title"], r["company"]) not in main_keys]
    trans.sort(key=lambda r: r["trans_score"], reverse=True)
    trans = trans[:max_trans]
    return main, trans


# ---------------------------------------------------------------------------
# Claude TikTok script (optional, degrades gracefully)
# ---------------------------------------------------------------------------

def draft_script(picks: list[dict], count: int) -> dict | None:
    if not USE_LLM or not ANTHROPIC_API_KEY or not picks:
        return None
    listing = "; ".join(f"{p['title']} at {p['company']}" for p in picks[:5])
    prompt = (
        f"I found {count} paid early-career cyber/tech roles posted this week, "
        f"including: {listing}. Write a punchy TikTok for a cybersecurity "
        "creator. Reply ONLY compact JSON: {\"hook\": \"<2-sec opening line, "
        "<=90 chars>\", \"script\": [\"<line 1>\", \"<line 2>\", \"<line 3>\"], "
        "\"caption\": \"<caption <=150 chars, 2-3 hashtags>\"}. Keep it energetic "
        "and beginner-friendly."
    )
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY, timeout=CLAUDE_TIMEOUT)
        resp = client.messages.create(
            model=CLAUDE_MODEL, max_tokens=320, system=LLM_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        txt = "".join(b.text for b in resp.content if b.type == "text").strip()
        data = json.loads(txt[txt.find("{"):txt.rfind("}") + 1])
        return {
            "hook": str(data.get("hook", "")).strip(),
            "script": [str(s).strip() for s in data.get("script", []) if str(s).strip()][:3],
            "caption": str(data.get("caption", "")).strip(),
        }
    except Exception as e:  # noqa: BLE001
        log(f"WARN claude script failed: {e}")
        return None


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------

def esc(s: str) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _tg_api(method: str) -> str:
    return f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}"


def send_message(text: str) -> bool:
    if "CHANGE-ME" in TELEGRAM_BOT_TOKEN or "CHANGE-ME" in TELEGRAM_CHAT_ID:
        log("ERROR TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID still placeholder — edit secrets_local.py.")
        return False
    try:
        resp = requests.post(
            _tg_api("sendMessage"),
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML",
                  "disable_web_page_preview": True},
            timeout=25,
        )
        resp.raise_for_status()
        return True
    except Exception as e:  # noqa: BLE001
        log(f"WARN telegram send failed: {e}")
        return False


def _role_lines(picks: list[dict], tag_key: str) -> list[str]:
    out: list[str] = []
    for i, p in enumerate(picks, 1):
        posted = f" · posted {esc(p['posted'])}" if p.get("posted") else ""
        loc = f" · {esc(p['location'])}" if p.get("location") else ""
        out.append(
            f"{i}. <a href=\"{esc(p['url'])}\"><b>{esc(p['title'])}</b></a> — {esc(p['company'])}"
        )
        out.append(f"     {p[tag_key]}{loc}{posted}")
    return out


def build_digest(picks: list[dict], transition: list[dict], hook: str,
                 cap_tip: str, apply_tip: str, script: dict | None) -> str:
    today = date.today().strftime("%a %b %d")
    n = len(picks) + len(transition)
    top = picks[0]["company"] if picks else (transition[0]["company"] if transition else "A top company")
    scope = f" · 📍 {esc(STATE)}" if STATE else ""
    lines = [
        "🎬 <b>Paid Apprenticeships &amp; Early-Career Cyber/Tech — TikTok brief</b>",
        f"📅 {esc(today)} · <b>{n}</b> role(s) posted in the last 7 days · straight from the job boards{scope}",
        "",
        "🎥 <b>Video hook</b>",
        f"   <i>{esc(hook.format(n=n, top=top))}</i>",
    ]
    if picks:
        lines.append("")
        lines.append("🗂️ <b>Apprenticeships · rotational · new-grad (screen-record this)</b>")
        lines.extend(_role_lines(picks, "tag"))

    if transition:
        lines.append("")
        lines.append("🔁 <b>For career changers — switching into tech/cyber</b>")
        lines.append("   <i>No CS degree / coming from another field — lead a video with these.</i>")
        lines.extend(_role_lines(transition, "trans_tag"))

    if script and (script.get("hook") or script.get("script") or script.get("caption")):
        lines.append("")
        lines.append("✍️ <b>Draft TikTok script (AI)</b>")
        if script.get("hook"):
            lines.append(f"   🎯 Hook: {esc(script['hook'])}")
        for s in script.get("script", []):
            lines.append(f"     • {esc(s)}")
        if script.get("caption"):
            lines.append(f"   💬 Caption: {esc(script['caption'])}")

    lines += [
        "",
        "📈 <b>Posting tip</b>",
        f"   {esc(cap_tip)}",
        "",
        "💡 <b>Teach-your-audience tip</b>",
        f"   {esc(apply_tip)}",
        "",
        "💬 <b>Search live in the bot</b> — text me <code>/search NY</code> (or just "
        "<code>NY</code>) any time for current roles in a state. <code>/help</code> for more.",
        "",
        "🗺️ <b>Search by state (tap — LinkedIn, last 7 days)</b>",
    ]
    for label, url in SPEC.state_search_links():
        lines.append(f"   • <a href=\"{esc(url)}\">{esc(label)}</a>")
    lines.append("")
    lines.append("🔎 <b>Browse more (tap — always current)</b>")
    for label, url in SPEC.LINK_SOURCES:
        lines.append(f"   • <a href=\"{esc(url)}\">{esc(label)}</a>")
    lines += [
        "",
        "<i>Reads public job-board listings only — confirm each role on its link before you film or apply.</i>",
    ]
    return "\n".join(lines)


def build_empty_message() -> str:
    return (
        "🎬 <b>Paid Apprenticeships &amp; Early-Career Cyber/Tech — TikTok brief</b>\n"
        f"📅 {esc(date.today().strftime('%a %b %d'))}\n\n"
        "No fresh qualifying roles cleared the filter this run (boards may be "
        "rate-limiting, or nothing new in the last 7 days). Try re-running later, "
        "or loosen MIN_SCORE / add a board in the config."
    )


# ---------------------------------------------------------------------------
# Main / preview / chatid
# ---------------------------------------------------------------------------

def _gather() -> tuple[list[dict], list[dict], dict]:
    seen = load_seen()
    roles = scrape_all()
    picks, transition = rank_and_dedupe(roles, seen.get("role_keys", []))
    return picks, transition, seen


def main() -> int:
    picks, transition, seen = _gather()
    if not picks and not transition:
        log("No qualifying roles this run.")
        send_message(build_empty_message())
        return 0

    hook = rotate_pick(SPEC.VIDEO_HOOKS, seen.get("hook_recent", []), "hook")
    cap_tip = rotate_pick(SPEC.CAPTION_TIPS, [], "captip")
    apply_tip = rotate_pick(SPEC.APPLY_TIPS, seen.get("tip_recent", []), "applytip")
    combined = picks + transition
    script = draft_script(combined, len(combined))

    msg = build_digest(picks, transition, hook, cap_tip, apply_tip, script)
    if send_message(msg):
        log(f"SENT {len(picks)} main + {len(transition)} transition: "
            f"{[p['company'] for p in combined]}")
        keys = seen.get("role_keys", [])
        keys.extend(role_key(p["title"], p["company"]) for p in combined)
        seen["role_keys"] = keys
        seen.setdefault("hook_recent", []).append(hook)
        seen["hook_recent"] = seen["hook_recent"][-4:]
        seen.setdefault("tip_recent", []).append(apply_tip)
        seen["tip_recent"] = seen["tip_recent"][-4:]
        save_seen(seen)
        return 0
    log("Digest not sent (see errors above).")
    return 1


def preview() -> int:
    """Scrape + rank and print to console — no Telegram, no de-dupe write."""
    seen = load_seen()
    roles = scrape_all()
    picks, transition = rank_and_dedupe(roles, [])  # ignore de-dupe in preview
    if not picks and not transition:
        print("No qualifying roles found this run.")
        return 0
    hook = rotate_pick(SPEC.VIDEO_HOOKS, [], "hook")
    cap_tip = rotate_pick(SPEC.CAPTION_TIPS, [], "captip")
    apply_tip = rotate_pick(SPEC.APPLY_TIPS, [], "applytip")
    text = build_digest(picks, transition, hook, cap_tip, apply_tip, None)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    print(text)
    return 0


def print_chat_id() -> int:
    if "CHANGE-ME" in TELEGRAM_BOT_TOKEN:
        print("Set TELEGRAM_BOT_TOKEN in secrets_local.py first.")
        return 1
    try:
        r = requests.get(_tg_api("getUpdates"), timeout=20)
        r.raise_for_status()
        results = r.json().get("result", [])
        if not results:
            print("No messages found. Message your bot first (press Start), then re-run --chatid.")
            return 1
        ids = {u["message"]["chat"]["id"]: u["message"]["chat"].get("username", "")
               for u in results if "message" in u}
        print("Chat id(s) that have messaged your bot:")
        for cid, uname in ids.items():
            print(f"  {cid}   (@{uname})" if uname else f"  {cid}")
        return 0
    except Exception as e:  # noqa: BLE001
        print(f"Error calling getUpdates: {e}")
        return 1


# ---------------------------------------------------------------------------
# On-demand /search command — a cloud poller (responder.yml, every ~5 min) lets
# you text the bot "/search NY" and get live roles for that state back any time,
# not just in the scheduled digest. Same pattern as the GoWild Matcher bot.
# ---------------------------------------------------------------------------

POLL_OFFSET_FILE = BASE_DIR / "poll_offset.json"

HELP_TEXT = (
    "🎬 <b>Apprentice Scout — search commands</b>\n"
    "• <code>/search NY</code> — LIVE search of paid apprenticeships, rotational "
    "&amp; early-career cyber/tech roles in a state (posted last 7 days), plus a "
    "career-changer set.\n"
    "• <code>/search</code> — nationwide.\n"
    "• Shortcut: just send a 2-letter state code, e.g. <code>TX</code>.\n"
    "• <code>/states</code> — list valid state codes.\n"
    "• <code>/help</code> — this message.\n\n"
    "<i>A live search scrapes the job boards, so a reply takes ~a minute.</i>"
)


def _chunk_lines(lines: list[str], limit: int = 3800) -> list[str]:
    """Pack lines into messages under Telegram's 4096-char cap."""
    out: list[str] = []
    buf: list[str] = []
    size = 0
    for ln in lines:
        add = len(ln) + 1
        if buf and size + add > limit:
            out.append("\n".join(buf))
            buf, size = [], 0
        buf.append(ln)
        size += add
    if buf:
        out.append("\n".join(buf))
    return out


def _reply(chat_id: str, text: str) -> None:
    try:
        requests.post(_tg_api("sendMessage"),
                      json={"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                            "disable_web_page_preview": True}, timeout=25).raise_for_status()
    except Exception as e:  # noqa: BLE001
        log(f"WARN reply failed: {e}")


def build_search_reply(location_label: str, location: str) -> list[str]:
    """Live-scrape roles scoped to `location` and format a chunked reply. Ignores
    the de-dupe cache so a search always returns the current best matches."""
    roles = scrape_all(location=location, results_per_query=SEARCH_RESULTS_PER_QUERY)
    picks, transition = rank_and_dedupe(roles, [], SEARCH_MAX_PICKS, SEARCH_MAX_TRANSITION)
    if not picks and not transition:
        return [f"🔎 <b>{esc(location_label)}</b> — no fresh qualifying roles right "
                "now (boards may be rate-limiting, or nothing new in the last 7 days). "
                "Try again shortly, or a different state."]
    lines = [f"🔎 <b>Apprentice Scout — {esc(location_label)}</b>",
             "<i>Posted in the last 7 days · straight from the job boards.</i>"]
    if picks:
        lines.append("")
        lines.append("🗂️ <b>Apprenticeships · rotational · new-grad</b>")
        lines.extend(_role_lines(picks, "tag"))
    if transition:
        lines.append("")
        lines.append("🔁 <b>For career changers — switching into tech/cyber</b>")
        lines.extend(_role_lines(transition, "trans_tag"))
    lines.append("")
    lines.append("<i>Confirm each role on its link before you apply or film.</i>")
    return _chunk_lines(lines)


def _handle_command(chat_id: str, text: str) -> None:
    t = text.strip()
    low = t.lower()
    if low in ("/start", "/help", "help", "start"):
        _reply(chat_id, HELP_TEXT)
        return
    if low in ("/states", "states"):
        codes = " ".join(sorted(SPEC.US_STATES))
        _reply(chat_id, f"🗺️ <b>State codes</b>\n{esc(codes)}\n\n"
                        "Search one with <code>/search TX</code> or just <code>TX</code>.")
        return

    # /search [state]  OR  a bare 2-letter state code as a shortcut.
    is_bare_state = len(t) == 2 and t.isalpha() and t.upper() in SPEC.US_STATES
    if low.startswith("/search") or is_bare_state:
        if is_bare_state:
            arg = t
        else:
            parts = t.split(maxsplit=1)
            arg = parts[1] if len(parts) > 1 else ""
        if not arg:  # nationwide
            _reply(chat_id, "🔎 Searching <b>nationwide</b>, one moment…")
            for block in build_search_reply("United States", LOCATION):
                _reply(chat_id, block)
                time.sleep(0.4)
            return
        full = SPEC.resolve_state(arg)
        if not full:
            _reply(chat_id, f"🤔 I don't know state <b>{esc(arg)}</b>. Use a 2-letter "
                            "code (e.g. TX) or full name, or send <code>/states</code>.")
            return
        _reply(chat_id, f"🔎 Searching <b>{esc(full)}</b>, one moment… (live scrape, ~a minute)")
        for block in build_search_reply(full, full):
            _reply(chat_id, block)
            time.sleep(0.4)
        return

    _reply(chat_id, "Send <code>/search NY</code> (or just <code>NY</code>) for live "
                    "roles in a state, or <code>/help</code>.")


def _load_offset() -> int:
    if POLL_OFFSET_FILE.exists():
        try:
            return int(json.loads(POLL_OFFSET_FILE.read_text(encoding="utf-8")).get("offset", 0))
        except (json.JSONDecodeError, OSError, ValueError):
            pass
    return 0


def _save_offset(offset: int) -> None:
    try:
        POLL_OFFSET_FILE.write_text(json.dumps({"offset": offset}), encoding="utf-8")
    except OSError as e:
        log(f"WARN could not write poll offset: {e}")


def serve_once() -> int:
    """One poll cycle: fetch new updates since the stored offset, answer any
    commands, persist the new offset. Meant to run on a schedule (responder.yml,
    every few minutes) so the bot answers even when your PC is off."""
    if "CHANGE-ME" in TELEGRAM_BOT_TOKEN:
        log("ERROR token still placeholder.")
        return 1
    offset = _load_offset()
    try:
        r = requests.get(_tg_api("getUpdates"),
                         params={"offset": offset, "timeout": 0, "allowed_updates": '["message"]'},
                         timeout=30)
        r.raise_for_status()
        updates = r.json().get("result", [])
    except Exception as e:  # noqa: BLE001
        log(f"WARN getUpdates failed: {e}")
        return 1

    handled, last = 0, offset
    for u in updates:
        last = max(last, u["update_id"] + 1)
        msg = u.get("message") or {}
        text = msg.get("text")
        chat = msg.get("chat", {})
        if text and chat.get("id") is not None:
            _handle_command(str(chat["id"]), text)
            handled += 1
    if last != offset:
        _save_offset(last)
    log(f"serve_once: {len(updates)} update(s), {handled} handled, offset -> {last}")
    return 0


def _apply_state_arg() -> None:
    """Handle `--state XX` / `--state "New York"` — scope the live scrape to one
    state. Unknown values are rejected with the list of valid options."""
    global STATE
    if "--state" not in sys.argv:
        return
    i = sys.argv.index("--state")
    if i + 1 >= len(sys.argv):
        print("--state needs a value, e.g. --state TX  or  --state \"New York\"")
        sys.exit(2)
    resolved = SPEC.resolve_state(sys.argv[i + 1])
    if not resolved:
        print(f"Unknown state '{sys.argv[i + 1]}'. Use a 2-letter code (TX) or full name.")
        sys.exit(2)
    STATE = resolved
    log(f"Scope: scraping only {STATE}")


if __name__ == "__main__":
    if "--chatid" in sys.argv:
        sys.exit(print_chat_id())
    if "--serve-once" in sys.argv:
        sys.exit(serve_once())
    _apply_state_arg()
    if "--preview" in sys.argv or "--dry-run" in sys.argv:
        sys.exit(preview())
    sys.exit(main())

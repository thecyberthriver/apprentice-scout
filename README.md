# Apprentice Scout 🎬🔐

> 📖 **Workshop / architecture guide with diagrams + screenshots:**
> [`docs/how-it-works.md`](docs/how-it-works.md) — how the scraper, role index,
> Cloudflare webhook, and `/search` (keyword + state → direct job links) fit
> together, plus full setup.

A local Windows Python + Telegram agent that scouts **paid apprenticeships,
rotational / leadership-development programs, and early-career cybersecurity &
tech roles posted in the last 7 days** — and hands you a **film-ready TikTok
brief** for each batch (job videos perform best on your account).

Sibling to `fare_watcher`, `gowild_scout`, and `tech_networking_scout`, but this
one does **live scraping**: every run it queries the job boards **directly**
(LinkedIn + Google Jobs) — no aggregator / referral third party — filters to
paid + early-career + cyber/tech, de-dupes against past runs, ranks the best,
and posts a Telegram digest you can screen-record and narrate.

## What each digest contains

- **Headline count** — "N paid roles posted this week."
- **A rotating TikTok video hook** — the opening line to say/overlay.
- **The roles** — numbered, screen-recordable: title · company · tag
  (🔐 Cyber / 💻 Tech · Apprenticeship / Rotational / New-grad / Entry-level) ·
  location · date posted. Each links straight to the employer's posting.
- **A "For career changers" section** — roles friendly to people switching INTO
  tech/cyber from another field (no-degree / will-train, help-desk on-ramps,
  veterans / SkillBridge, returnships), scored separately from the new-grad list.
- **Search by state** — GoWild-style tappable per-state links (LinkedIn, last 7
  days) for the states in `TARGET_STATES`. Run `--state XX` to scope the actual
  scrape to one state (e.g. `--state TX` or `--state "New York"`).
- **Interactive in-bot search** — text the bot `/search NY` (or just `NY`) any
  time and it live-scrapes that state and replies with ranked roles. Also
  `/states` and `/help`. Answered in the cloud by `responder.yml` (polls every
  ~5 min via `--serve-once`), so it works even when your PC is off.
- **Boolean search over employer ATS boards only** — recruiter strings
  (`AND` / `OR` / `NOT`, parentheses, `"quoted phrases"`) against Greenhouse,
  Lever, Ashby, SmartRecruiters and Workday postings; LinkedIn/Indeed rows are
  excluded, so every hit is the employer's own posting. In the bot:
  `/bool (soc OR siem) AND analyst` (every level), `/boolsr …` (mid + senior),
  `/domains` (the eight CISSP domains with entry/mid/senior counts), then
  `/d7`, `/d7 entry`, `/d3 senior`, `/d5 mid senior` — each takes an optional
  string, e.g. `/d7 entry (remote OR ny) NOT clearance`. Answered instantly from
  the role index by the Worker. On the CLI, `boolsearch.py` does the same against
  a live ATS scrape (`--level mid,senior`, `--domain 7`, `--send`).
- **A draft TikTok script + caption** (optional, via Claude Haiku).
- **A posting tip** and a **teach-your-audience tip** so the video educates.
- **Browse-more links** — pre-filtered live searches on hiring.cafe,
  apprenticeship.gov (official paid registered apprenticeships), and LinkedIn.

## Why these sources (the "no third parties" rule)

`python-jobspy` scrapes the boards themselves, so a hit is the employer's own
posting — not a reposter. Companies that are themselves aggregators / staffing
reposters (Jobright, Lensa, ZipRecruiter, Dice, "jobs via …", staffing firms,
etc.) are filtered out by name — see `EXCLUDE_COMPANIES` in `searchspec.py`.

hiring.cafe's search API is auth-gated (can't be scraped cleanly), and
apprenticeship.gov is the official registry — both are included as **tappable
pre-filtered links** at the bottom of the digest rather than scraped.

## Setup

```powershell
pip install -r requirements.txt          # python-jobspy, requests, anthropic
```

1. **Create / choose a Telegram bot** (BotFather → `/newbot`) and copy the token.
2. Put secrets in `secrets_local.py` (untracked):
   - `TELEGRAM_BOT_TOKEN`
   - Message the bot once, then run `python apprentice_scout.py --chatid` to get
     your `TELEGRAM_CHAT_ID`; paste it in.
   - Optional: `ANTHROPIC_API_KEY` to enable the AI-drafted TikTok script.
3. Test:
   ```powershell
   python apprentice_scout.py --preview            # scrape + rank, print, no send
   python apprentice_scout.py                       # real Telegram send
   python apprentice_scout.py --preview --state TX  # scope the scrape to one state
   ```
4. Schedule it — **the cloud is production**: GitHub Actions runs the digest Mon +
   Thu at 12:00 UTC (8 AM ET), `.github/workflows/schedule.yml`. Set repo Secrets
   `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` (and optionally `ANTHROPIC_API_KEY`).
   Trigger a test run from the Actions tab or `gh workflow run schedule.yml`.
   `register_task.ps1` (Windows Task Scheduler) exists for **local development
   only** — nothing in production needs your PC, and running both would
   double-post, since the two de-dupe against separate caches.

## Architecture — nothing here needs your computer

| Piece | Where it runs | What it does | State it keeps |
|---|---|---|---|
| `schedule.yml` | GitHub Actions, Mon + Thu 12:00 UTC | scrapes and sends the digest | commits `seen.json` back to the repo |
| `index.yml` | GitHub Actions, every 2h | rebuilds `roles_index.json` | commits the index back to the repo |
| `cloudflare-webhook/worker.js` | Cloudflare Worker (webhook) | answers `/search`, `/states`, `/help`, `/bool`, `/boolsr`, `/domains`, `/d1`–`/d8` instantly | none — reads `roles_index.json` from the repo, caches it 30 min in-isolate |
| `responder.yml` | GitHub Actions, **disabled** | `getUpdates` fallback poller | `poll_offset.json` via `actions/cache` |
| `register_task.ps1` | your PC, optional | local dev runs | local files |

**One receiver per bot.** The Cloudflare webhook owns this bot's updates, so
`responder.yml`'s cron is commented out — a bot cannot use a webhook and
`getUpdates` at once (`getUpdates` returns HTTP 409 while a webhook is set). To
switch to polling instead: run `python cloudflare-webhook/set_webhook.py --delete`
**first**, then un-comment the `schedule:` block in `responder.yml`.

**State.** A Actions runner is wiped between runs, so nothing durable lives on
it: `seen.json` (de-dupe) and `roles_index.json` (what the Worker serves) are
committed back to the repo by the workflow that writes them, and the poll offset
uses `actions/cache` (evictable — losing it can only re-answer one command).

**Secrets** live in GitHub Actions repo secrets and Cloudflare Worker secrets.
None are committed, and every log line goes through `redact()` before it is
written, because the Bot API puts the token in the URL that `requests` embeds in
exception messages — and this repo's Actions logs are public.

### Tests (no network, no Telegram, no scrape)

```powershell
python test_delivery.py                    # delivery failures, seen-cache, polling, state
python searchspec.py                       # query/title classifier self-check
python boolsearch.py --selfcheck           # boolean CLI
node cloudflare-webhook/worker.test.mjs    # webhook command handling + duplicate updates
node cloudflare-webhook/bool.test.mjs      # boolean parser (Workers can't eval)
```

## Tuning (all in `searchspec.py` / the CONFIG block of `apprentice_scout.py`)

- `QUERIES` — the board queries (cyber/tech × apprentice/rotational/early-career, plus one pass per CISSP domain D1–D8).
- `CYBER_DOMAINS` — CISSP 8-domain title keywords; labels every cyber role line (e.g. `🔐 D7 SecOps`) and extends `CYBER_ROLE_TITLES`.
- `level_of()` — entry / mid / senior from the title. The digest stays entry-to-mid; the `/search` index keeps every level and the bot shows entry+mid unless you type a level: `/search entry level cyber`, `/search senior soc analyst NY`, `/search all grc`.
- `SITES` — boards to scrape (`google`, `linkedin`; add `indeed`/`zip_recruiter`
  to try, though both block scrapers).
- `EARLY_CAREER` / `TECH_CYBER` / `PAID_BOOST` — scoring keyword weights.
- `EXCLUDE_COMPANIES` — aggregator/reposter blocklist.
- `TRANSITION_SIGNALS` — keywords that flag career-changer-friendly roles.
- `GREENHOUSE_BOARDS` / `LEVER_BOARDS` / `ASHBY_BOARDS` / `WORKDAY_BOARDS` — employer career pages read directly (roles appear here the moment they are posted). Probe a slug before adding it.
- `TARGET_STATES` — which states get tappable "Search by state" links.
- `MIN_SCORE`, `MIN_TRANS_SCORE`, `MAX_PICKS`, `MAX_TRANSITION`, `HOURS_OLD`, `MAX_AGE_DAYS` (3-week cap on the /search index; the Worker also drops anything over 30 days),
  `LOCATION` — filter/scope knobs.
- `VIDEO_HOOKS`, `CAPTION_TIPS`, `APPLY_TIPS`, `LINK_SOURCES` — content angles.

## Honesty

Reads public job-board listings only. It does **not** apply on your behalf and
does **not** invent postings. Confirm each role on its link before you film or
apply. Boards rate-limit scrapers; if a run comes back empty, re-run later.

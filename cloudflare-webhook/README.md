# Apprentice Scout — instant webhook (Cloudflare Worker)

Answers `/search`, `/states` and `/help` **the instant you send them** — no 5-min
poll. Telegram POSTs each update straight to this Worker, which replies
immediately. Same instant-search feel as the GoWild Matcher bot.

This replaces the `responder.yml` poller (a Telegram bot can't use a webhook and
`getUpdates` polling at the same time — leave the poller disabled while the
webhook is active).

## What it does
Mirrors `place_links()` in `searchspec.py`: given a **state** (`/search NY`) or a
**city** (`/search Austin`), it returns tap-through links that open straight to
the filtered roles on Indeed, LinkedIn, and Google Jobs — early-career cyber/tech,
last 7 days. A Worker can't run `python-jobspy`, so the interactive reply is
links-only (like GoWild); the full **scraped** role list still arrives in the
twice-weekly digest (`schedule.yml`).

## One-time setup

**1. Cloudflare account** (free, no card): https://dash.cloudflare.com/sign-up
(use the same account as the GoWild bot).

**2. Log wrangler in** (opens a browser to authorize — no token pasting):
```
npx wrangler login
```

**3. Deploy + wire up** (run from this folder; secrets are piped from the
untracked `../secrets_local.py`, never printed):
```
npx wrangler deploy
python - <<'PY' | npx wrangler secret put TELEGRAM_BOT_TOKEN
import sys; sys.path.insert(0,".."); import secrets_local as s; print(s.TELEGRAM_BOT_TOKEN)
PY
python - <<'PY' | npx wrangler secret put WEBHOOK_SECRET
import sys; sys.path.insert(0,".."); import secrets_local as s; print(s.WEBHOOK_SECRET)
PY
python - <<'PY' | npx wrangler secret put OWNER_CHAT_ID
import sys; sys.path.insert(0,".."); import secrets_local as s; print(s.TELEGRAM_CHAT_ID)
PY
```

**4. Point Telegram at the Worker** (uses the deployed `*.workers.dev` URL):
```
python set_webhook.py https://apprentice-scout-bot.<your-subdomain>.workers.dev
python set_webhook.py --info      # confirm url + pending_update_count
```

## Bindings
| Name | Kind | Purpose |
|------|------|---------|
| `TELEGRAM_BOT_TOKEN` | secret | bot token |
| `WEBHOOK_SECRET` | secret | matches Telegram's `setWebhook` secret_token (rejects forged posts) |
| `OWNER_CHAT_ID` | secret | only this chat is answered (remove to answer anyone) |

## Reverting to the poller
```
python set_webhook.py --delete     # deleteWebhook re-enables getUpdates
```
Then re-enable the `schedule:` cron in `.github/workflows/responder.yml`.

#!/usr/bin/env python3
"""
set_webhook.py — point Telegram at the Cloudflare Worker (or remove it).

Usage:
  python set_webhook.py https://apprentice-scout-bot.<subdomain>.workers.dev
  python set_webhook.py --delete     # remove webhook, re-enable getUpdates polling
  python set_webhook.py --info       # show current webhook status

Reads TELEGRAM_BOT_TOKEN + WEBHOOK_SECRET from ../secrets_local.py (untracked);
the secret value is never printed.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import requests
import secrets_local as s  # noqa: E402

BASE = f"https://api.telegram.org/bot{s.TELEGRAM_BOT_TOKEN}"


def main() -> int:
    if "--delete" in sys.argv:
        r = requests.post(f"{BASE}/deleteWebhook", json={"drop_pending_updates": False}, timeout=20)
        print("deleteWebhook:", r.status_code, r.json())
        return 0
    if "--info" in sys.argv:
        r = requests.get(f"{BASE}/getWebhookInfo", timeout=20)
        print(r.json())
        return 0
    urls = [a for a in sys.argv[1:] if a.startswith("http")]
    if not urls:
        print(__doc__)
        return 1
    r = requests.post(
        f"{BASE}/setWebhook",
        json={
            "url": urls[0],
            "secret_token": getattr(s, "WEBHOOK_SECRET", ""),
            "allowed_updates": ["message"],
            "drop_pending_updates": True,
            "max_connections": 20,
        },
        timeout=20,
    )
    data = r.json()
    print("setWebhook:", r.status_code, {k: data.get(k) for k in ("ok", "result", "description")})
    return 0 if data.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())

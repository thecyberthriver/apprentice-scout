#!/usr/bin/env python3
"""
ats.py — scrape entry-to-mid cyber & IT roles DIRECTLY from employer ATS boards.

Greenhouse and Lever publish public JSON job-board APIs for exactly this (job
distribution) — no key, no login, allowed. This is the "employer websites / ATS
that allow job scraping" source, complementing the jobspy board scrape.

Which companies + which titles are content-tuning knobs in searchspec.py
(GREENHOUSE_BOARDS, LEVER_BOARDS, ENTRY_MID_TITLES / entry_mid_title). Roles come
back PRE-CLASSIFIED (tag + scores set) so apprentice_scout's ranker keeps them
without re-scoring — they're already title-vetted to entry/mid cyber/IT.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import requests

import searchspec as SPEC

_TIMEOUT = 20
_UA = {"User-Agent": "Mozilla/5.0 (compatible; apprentice-scout/1.0)"}
_US_MARKERS = ("united states", "usa", "u.s", "remote", "hybrid", "anywhere",
               "in-office", "in office", "flexible")
# Checked FIRST — a "Remote, Australia" posting must not count as US just because
# it says "remote". Common non-US signals on global ATS boards.
_NON_US = ("australia", "canada", "united kingdom", " uk", "uk)", "ireland",
           "india", "germany", "france", "spain", "netherlands", "poland",
           "portugal", "romania", "singapore", "japan", "china", "israel",
           "brazil", "mexico", "argentina", "colombia", "emea", "apac", "latam",
           "london", "dublin", "bangalore", "hyderabad", "toronto", "vancouver",
           "berlin", "munich", "amsterdam", "sydney", "melbourne", "tel aviv",
           "são paulo", "sao paulo", "manila", "kraków", "krakow", "lisbon")


def _us_location(loc: str) -> bool:
    """Keep US (or US-remote/unspecified) roles; drop clearly non-US ones."""
    if not loc:
        return True
    low = loc.lower()
    if any(n in low for n in _NON_US):
        return False
    if any(m in low for m in _US_MARKERS):
        return True
    up = loc.upper()
    if any(re.search(rf"(?:^|,)\s*{ab}\b", up) for ab in SPEC.US_STATES):
        return True
    return any(full.lower() in low for full in SPEC.US_STATES.values())


def _tag(title: str) -> str:
    domain = "🔐 Cyber" if SPEC.is_cyber_title(title) else "💻 Tech"
    low = title.lower()
    if "apprentice" in low:
        kind = "Apprenticeship"
    elif any(w in low for w in ("intern", "new grad", "graduate", "early career", "junior", "associate", "i ", " i", "entry")):
        kind = "Entry-level"
    elif any(w in low for w in ("help desk", "service desk", "support", "desktop")):
        kind = "Help-desk on-ramp"
    else:
        kind = "Mid-level"
    return f"{domain} · {kind} · direct-from-employer"


def _score(title: str) -> int:
    """Above MIN_SCORE so ATS roles survive ranking; entry signals sort higher."""
    low = title.lower()
    bonus = 3 if any(w in low for w in
                     ("apprentice", "intern", "junior", "associate", "new grad",
                      "graduate", "early career", "entry", " i ", "trainee")) else 0
    return 8 + bonus


def _role(title, company, url, location, posted, site):
    return {
        "title": title, "company": company, "url": url, "salary": "",
        "site": site, "location": location, "posted": posted,
        "desc": title, "query_tag": "ats",
        "preclassified": True, "tag": _tag(title), "trans_tag": "",
        "main_score": _score(title), "trans_score": 0,
        "is_main": True, "is_trans": False,
    }


def _fresh(dt: datetime | None, cutoff: datetime) -> bool:
    return dt is None or dt >= cutoff  # keep undated roles


def _greenhouse(slug, name, cutoff, log):
    url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
    r = requests.get(url, headers=_UA, timeout=_TIMEOUT)
    r.raise_for_status()
    out = []
    for j in r.json().get("jobs", []):
        title = (j.get("title") or "").strip()
        loc = ((j.get("location") or {}).get("name") or "").strip()
        if not title or not SPEC.entry_mid_title(title) or not _us_location(loc):
            continue
        raw = j.get("first_published") or j.get("updated_at") or ""
        dt = None
        try:
            dt = datetime.fromisoformat(raw) if raw else None
        except ValueError:
            dt = None
        if not _fresh(dt, cutoff):
            continue
        out.append(_role(title, j.get("company_name") or name,
                         j.get("absolute_url") or url,
                         loc, dt.date().isoformat() if dt else None, "greenhouse"))
    return out


def _lever(slug, name, cutoff, log):
    url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
    r = requests.get(url, headers=_UA, timeout=_TIMEOUT)
    r.raise_for_status()
    data = r.json()
    out = []
    for j in data if isinstance(data, list) else []:
        title = (j.get("text") or "").strip()
        loc = ((j.get("categories") or {}).get("location") or "").strip()
        if not title or not SPEC.entry_mid_title(title) or not _us_location(loc):
            continue
        ms = j.get("createdAt")
        dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc) if isinstance(ms, (int, float)) else None
        if not _fresh(dt, cutoff):
            continue
        link = j.get("hostedUrl") or f"https://jobs.lever.co/{slug}/{j.get('id','')}"
        out.append(_role(title, name, link, loc,
                         dt.date().isoformat() if dt else None, "lever"))
    return out


def scrape_ats(days: int, log=print) -> list[dict]:
    """Scrape all configured Greenhouse + Lever boards for fresh (<= `days`)
    entry-to-mid cyber/IT roles. Each board is isolated: one failing (rate limit,
    moved off the ATS) never kills the run."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    roles: list[dict] = []
    for fetch, boards in ((_greenhouse, SPEC.GREENHOUSE_BOARDS),
                          (_lever, SPEC.LEVER_BOARDS)):
        for slug, name in boards:
            try:
                roles.extend(fetch(slug, name, cutoff, log))
            except Exception as e:  # noqa: BLE001
                log(f"WARN ATS {fetch.__name__[1:]} '{slug}' failed: {e}")
    log(f"ATS: {len(roles)} entry/mid cyber-IT roles from "
        f"{len(SPEC.GREENHOUSE_BOARDS) + len(SPEC.LEVER_BOARDS)} employer boards "
        f"(<= {days}d)")
    return roles


if __name__ == "__main__":  # quick manual check: python ats.py
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # Windows console is cp1252
    except Exception:  # noqa: BLE001
        pass
    for r in scrape_ats(days=30)[:25]:
        print(f"{r['posted']}  {r['tag']}\n   {r['title']} - {r['company']} | {r['location']}")

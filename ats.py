#!/usr/bin/env python3
"""
ats.py — scrape cyber & IT roles DIRECTLY from employer ATS boards (Greenhouse,
Lever, Ashby, SmartRecruiters, Workday).

Greenhouse, Lever and Ashby publish public JSON job-board APIs for exactly this
(job distribution) — no key, no login, allowed. Workday exposes the same JSON
search its own careers pages use. This is the "employer websites / ATS" source:
a role shows up here the moment the employer posts it, days before it trickles
onto LinkedIn/Indeed.

Which companies + which titles are content-tuning knobs in searchspec.py
(GREENHOUSE_BOARDS, LEVER_BOARDS, ASHBY_BOARDS, WORKDAY_BOARDS, tech_title /
level_of). Roles come back PRE-CLASSIFIED (tag + scores set) so
apprentice_scout's ranker keeps them without re-scoring.
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


def _keep(title: str, levels) -> bool:
    """Cyber/IT title at one of `levels` (None = every level)."""
    return SPEC.tech_title(title) and (levels is None or SPEC.level_of(title) in levels)


def _tag(title: str) -> str:
    domain = SPEC.domain_label(title, cyber=SPEC.is_cyber_title(title))
    low = title.lower()
    if SPEC.is_senior_title(title):
        kind = "Senior"
    elif "apprentice" in low:
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


def _greenhouse(slug, name, cutoff, log, levels):
    url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
    r = requests.get(url, headers=_UA, timeout=_TIMEOUT)
    r.raise_for_status()
    out = []
    for j in r.json().get("jobs", []):
        title = (j.get("title") or "").strip()
        loc = ((j.get("location") or {}).get("name") or "").strip()
        if not title or not _keep(title, levels) or not _us_location(loc):
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


def _lever(slug, name, cutoff, log, levels):
    url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
    r = requests.get(url, headers=_UA, timeout=_TIMEOUT)
    r.raise_for_status()
    data = r.json()
    out = []
    for j in data if isinstance(data, list) else []:
        title = (j.get("text") or "").strip()
        loc = ((j.get("categories") or {}).get("location") or "").strip()
        if not title or not _keep(title, levels) or not _us_location(loc):
            continue
        ms = j.get("createdAt")
        dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc) if isinstance(ms, (int, float)) else None
        if not _fresh(dt, cutoff):
            continue
        link = j.get("hostedUrl") or f"https://jobs.lever.co/{slug}/{j.get('id','')}"
        out.append(_role(title, name, link, loc,
                         dt.date().isoformat() if dt else None, "lever"))
    return out


def _ashby(slug, name, cutoff, log, levels):
    url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
    r = requests.get(url, headers=_UA, timeout=_TIMEOUT)
    r.raise_for_status()
    out = []
    for j in r.json().get("jobs", []):
        title = (j.get("title") or "").strip()
        loc = (j.get("location") or "").strip()
        if j.get("isRemote") and "remote" not in loc.lower():
            loc = f"Remote, {loc}" if loc else "Remote"
        if not title or not _keep(title, levels) or not _us_location(loc):
            continue
        raw = j.get("publishedAt") or ""
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00")) if raw else None
        except ValueError:
            dt = None
        if not _fresh(dt, cutoff):
            continue
        out.append(_role(title, name, j.get("jobUrl") or f"https://jobs.ashbyhq.com/{slug}",
                         loc, dt.date().isoformat() if dt else None, "ashby"))
    return out


_WD_AGE = re.compile(r"(\d+)\+?\s+days?\s+ago", re.I)


def _workday_age(posted_on: str) -> int | None:
    """Workday gives 'Posted Today' / 'Posted Yesterday' / 'Posted 3 Days Ago' /
    'Posted 30+ Days Ago' — return the age in days (None = unknown)."""
    low = (posted_on or "").lower()
    if "today" in low:
        return 0
    if "yesterday" in low:
        return 1
    m = _WD_AGE.search(low)
    return int(m.group(1)) if m else None


_WD_PAGES = 15   # ponytail: 15 x 20 = 300 'security' hits per tenant; raise if big tenants truncate


def _workday(slug, name, cutoff, log, levels):
    """slug = 'tenant/wdN/site'. Workday's search endpoint is a public POST used
    by every tenant's own careers page. We ask it for 'security' roles. Results
    are relevance-sorted (not newest-first), so we page to _WD_PAGES and filter
    each posting by its 'Posted N Days Ago' age."""
    tenant, wdn, site = slug.split("/")
    base = f"https://{tenant}.{wdn}.myworkdayjobs.com"
    url = f"{base}/wday/cxs/{tenant}/{site}/jobs"
    hdr = {**_UA, "Content-Type": "application/json", "Accept": "application/json"}
    max_age = (datetime.now(timezone.utc) - cutoff).days
    out = []
    for page in range(_WD_PAGES):
        r = requests.post(url, json={"appliedFacets": {}, "limit": 20, "offset": page * 20,
                                     "searchText": "security"}, headers=hdr, timeout=_TIMEOUT)
        r.raise_for_status()
        posts = r.json().get("jobPostings", [])
        for j in posts:
            title = (j.get("title") or "").strip()
            path = j.get("externalPath") or ""
            loc = (j.get("locationsText") or "").strip()
            if loc.lower().endswith("locations") and path.count("/") >= 2:
                # "3 Locations" — the primary site is in the path: /job/USA---Austin-TX/...
                loc = path.split("/")[2].replace("---", ", ").replace("-", " ")
            age = _workday_age(j.get("postedOn", ""))
            if age is not None and age > max_age:
                continue
            if not title or not _keep(title, levels) or not _us_location(loc):
                continue
            posted = (datetime.now(timezone.utc) - timedelta(days=age)).date().isoformat() if age is not None else None
            out.append(_role(title, name, f"{base}/{site}{path}", loc, posted, "workday"))
        if len(posts) < 20:
            break
    return out


_FETCHERS = (
    (_greenhouse, "GREENHOUSE_BOARDS"), (_lever, "LEVER_BOARDS"),
    (_ashby, "ASHBY_BOARDS"), (_workday, "WORKDAY_BOARDS"),
)


def scrape_ats(days: int, log=print, levels=("entry", "mid")) -> list[dict]:
    """Scrape every configured employer board (Greenhouse, Lever, Ashby,
    SmartRecruiters, Workday) for fresh (<= `days`) cyber/IT roles at `levels`
    (default entry+mid for the digest; None = all, used by the /search index).
    Boards are fetched in parallel and isolated: one failing (rate limit, moved
    off the ATS) never kills the run."""
    from concurrent.futures import ThreadPoolExecutor
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    jobs = [(fetch, slug, name)
            for fetch, attr in _FETCHERS
            for slug, name in getattr(SPEC, attr, [])]

    def one(job):
        fetch, slug, name = job
        try:
            return fetch(slug, name, cutoff, log, levels)
        except Exception as e:  # noqa: BLE001
            log(f"WARN ATS {fetch.__name__[1:]} '{slug}' failed: {e}")
            return []

    roles: list[dict] = []
    with ThreadPoolExecutor(max_workers=8) as ex:   # ponytail: 8 is polite; raise if slow
        for got in ex.map(one, jobs):
            roles.extend(got)
    log(f"ATS: {len(roles)} cyber-IT roles from {len(jobs)} employer boards (<= {days}d)")
    return roles


if __name__ == "__main__":  # quick manual check: python ats.py
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # Windows console is cp1252
    except Exception:  # noqa: BLE001
        pass
    for r in scrape_ats(days=30)[:25]:
        print(f"{r['posted']}  {r['tag']}\n   {r['title']} - {r['company']} | {r['location']}")

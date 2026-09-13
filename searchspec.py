#!/usr/bin/env python3
"""
searchspec.py — what apprentice_scout.py looks for, how it scores, and the
TikTok content angles it hands you.

This is the "catalog" file (sibling to events.py in tech-networking-scout), but
instead of curated events it defines the LIVE job-board queries and the keyword
scoring used to keep only PAID apprenticeships, rotational programs, and
early-career cyber/tech roles posted in the last week.

Everything here is content-tuning — edit freely. The scraping/filtering engine
lives in apprentice_scout.py and imports these names.
"""

from __future__ import annotations

from urllib.parse import quote

# ---------------------------------------------------------------------------
# QUERIES — each dict is one scrape pass. We hit the job boards DIRECTLY
# (LinkedIn, Google Jobs, ZipRecruiter) — no aggregator / referral third party.
#
#   search_term         : board-native keyword query (LinkedIn/ZipRecruiter)
#   google_search_term  : natural-language query Google Jobs parses best
#   tag                 : which content bucket a hit from this pass leans toward
#
# Google + LinkedIn are the reliable engines; ZipRecruiter is best-effort and
# is allowed to fail without killing the run.
# ---------------------------------------------------------------------------

QUERIES = [
    {
        "tag": "cyber-apprentice",
        "search_term": "cybersecurity apprentice OR apprenticeship",
        "google_search_term": "paid cybersecurity apprenticeship entry level jobs posted this week",
    },
    {
        "tag": "cyber-rotational",
        "search_term": "cyber security rotational program OR leadership development program",
        "google_search_term": "cybersecurity rotational program new grad jobs posted this week",
    },
    {
        "tag": "cyber-early",
        "search_term": "associate cybersecurity analyst OR SOC analyst new grad OR entry level",
        "google_search_term": "entry level cybersecurity analyst new graduate jobs posted this week",
    },
    {
        "tag": "tech-apprentice",
        "search_term": "tech apprenticeship OR software apprentice OR IT apprentice",
        "google_search_term": "paid tech software apprenticeship program jobs posted this week",
    },
    {
        "tag": "tech-rotational",
        "search_term": "technology rotational program OR technology development program OR TDP",
        "google_search_term": "technology rotational leadership development program new grad jobs posted this week",
    },
    {
        "tag": "tech-early",
        "search_term": "new grad software engineer OR early career technology analyst",
        "google_search_term": "new graduate early career software engineer jobs posted this week",
    },
    # --- Career transitioners (switching INTO tech/cyber from another field) ---
    {
        "tag": "transition-cyber",
        "search_term": "cybersecurity career change OR no experience OR entry level SOC analyst",
        "google_search_term": "cybersecurity jobs for career changers no experience posted this week",
    },
    {
        "tag": "transition-tech",
        "search_term": "IT support career change OR help desk entry level OR service desk",
        "google_search_term": "entry level IT help desk career change no degree jobs posted this week",
    },
    {
        "tag": "transition-vets",
        "search_term": "SkillBridge cybersecurity OR veterans cyber OR returnship technology",
        "google_search_term": "veteran SkillBridge returnship cybersecurity technology jobs posted this week",
    },
]

# Boards to scrape. Order doesn't matter; each is tried independently.
#   indeed  — most reliable, incl. from datacenter/Actions IPs; scopes by state
#             (LinkedIn/Google don't reliably), and returns descriptions + salary
#             + a job_url_direct that points at the EMPLOYER/ATS (Workday,
#             SmartRecruiters, Greenhouse, ADP, Oracle HCM…), not a third party.
#   google  — good when it answers, but frequently returns 0 from cloud IPs.
#   linkedin — often blocked from datacenter IPs; title-only (no descriptions).
# ZipRecruiter is omitted (403s every request). Failures are swallowed per-query
# so a blocked board can't break a run. Indeed is a job board, not a reposter —
# and we link through to its job_url_direct (the real employer/ATS posting).
SITES = ["indeed", "google", "linkedin"]

# ---------------------------------------------------------------------------
# SCORING KEYWORDS (all matched case-insensitively against the title, and the
# description when available).
# ---------------------------------------------------------------------------

# Early-career signals — a role must hit at least one of these to qualify.
# Weighted: apprenticeship/rotational (the user's explicit focus) score highest.
EARLY_CAREER = {
    "apprenticeship": 6, "apprentice": 6,
    "rotational": 6, "rotation program": 6, "rotation": 3,
    "leadership development program": 5, " ldp": 4, "development program": 4,
    "new grad": 5, "new graduate": 5, "recent graduate": 4,
    "early career": 5, "early talent": 5, "early-career": 5,
    "entry level": 4, "entry-level": 4,
    "graduate program": 5, "graduate engineer": 4, "graduate analyst": 4,
    "class of 202": 4,  # "Class of 2026/2027" cohort postings
    "trainee": 4, "junior": 3, "associate": 2, "intern": 2, "internship": 2,
    "2026": 1, "2027": 1,
}

# Cyber/tech relevance — a role must hit at least one of these too.
TECH_CYBER = {
    "cybersecurity": 5, "cyber security": 5, "cyber": 4, "infosec": 4,
    "information security": 5, "security": 3, "soc": 3, "grc": 3,
    "penetration": 4, "incident response": 4, "threat": 3, "vulnerability": 3,
    "software engineer": 3, "developer": 2, "cloud": 2, "network": 2,
    "data engineer": 2, "data analyst": 2, "it ": 2, "technology": 2,
    "devops": 3, "systems engineer": 2, "help desk": 1,
}

# "Paid" signals boost a role; unpaid signals disqualify it. Registered
# apprenticeships and rotational/new-grad programs are paid by definition, so
# absence of the word "paid" is NOT disqualifying — only explicit unpaid is.
PAID_BOOST = {"paid": 3, "salary": 2, "$": 2, "compensation": 1, "stipend": 1}
UNPAID_BLOCK = ["unpaid", "volunteer", "no pay", "non-paid", "for college credit only"]

# Career-transitioner signals — roles friendly to people switching INTO tech/cyber
# from another field (not fresh college grads). A role lands in the "career
# changers" section when it hits at least one of these AND a tech/cyber keyword.
TRANSITION_SIGNALS = {
    "career change": 6, "career changer": 6, "career transition": 6,
    "career pivot": 6, "career switch": 6, "changing careers": 6, "second career": 5,
    "no experience": 5, "no prior experience": 5, "willing to train": 5,
    "we will train": 5, "we'll train": 5, "train you": 4, "on-the-job training": 4,
    "no degree": 4, "without a degree": 4, "degree not required": 5,
    "transferable skills": 4, "non-traditional": 3, "bootcamp": 4, "self-taught": 3,
    "returnship": 6, "return to work": 5, "relaunch": 3, "career reentry": 5,
    "skillbridge": 6, "veteran": 4, "transitioning military": 6, "military": 3,
    "help desk": 3, "service desk": 3, "it support": 3, "technical support": 2,
}

# Third-party reposters / aggregators to EXCLUDE — the user wants roles posted
# by the actual employer, not scraped-and-relisted by a middleman. Matched as a
# substring against the company name (lowercased).
EXCLUDE_COMPANIES = [
    "jobright", "lensa", "ziprecruiter", "get.it", "getit", "jobot",
    "energy jobline", "talentify", "dice", "recruiting.com", "careerbuilder",
    "adzuna", "jooble", "snagajob", "myworkdayjobs.com", "jobs via", "hiring.cafe",
    "staffing", "recruiters", "recruitment", "talent acquisition partner",
]

# Seniority that disqualifies (unless an early-career signal is also present,
# e.g. "New Grad — reports to Senior Manager").
SENIOR_BLOCK = ["senior ", "sr.", "sr ", "staff ", "principal ", "lead ",
                "manager", "director", "vp ", "head of", "architect",
                "ii ", "iii ", " 3 ", "experienced"]

# ---------------------------------------------------------------------------
# TIKTOK CONTENT ANGLES — surfaced in the digest so each batch is film-ready.
# {n} = number of roles, {top} = headline company/title.
# ---------------------------------------------------------------------------

VIDEO_HOOKS = [
    "\"{n} PAID cybersecurity apprenticeships hiring RIGHT NOW (no experience needed)\" — screen-record the list.",
    "\"POV: you didn't go to college but these {n} companies will PAY you to learn cyber\" — talk over the roll.",
    "\"Stop paying for bootcamps. These {n} rotational programs pay YOU to train.\" — react to each one.",
    "\"{top} is hiring early-career cyber — and nobody's talking about it.\" — deep-dive one role.",
    "\"Save this: {n} entry-level tech + cyber roles posted THIS WEEK.\" — fast-cut carousel style.",
    "\"How to break into cybersecurity in 2026 without a degree\" — use these {n} apprenticeships as proof.",
]

CAPTION_TIPS = [
    "Pin a comment with the direct application links — TikTok buries links in captions.",
    "Add on-screen text with each company name; viewers screenshot to apply later.",
    "End with 'Follow for weekly paid cyber roles' — job videos convert best on consistency.",
    "Hook in the first 2 seconds with the salary or 'no degree required' — then list.",
    "Reply to a 'how do I get into cyber' comment with this video for reach.",
    "Post between 6–9pm ET; career content peaks in the evening scroll.",
]

# ---------------------------------------------------------------------------
# BROWSE-MORE SOURCES — tappable, always-current, pre-filtered searches shown at
# the bottom of every digest. These are boards whose live search we DON'T scrape
# (hiring.cafe is auth-gated; apprenticeship.gov is the official registry) — so
# we point you straight at their filtered results instead. (label, url)
# ---------------------------------------------------------------------------

LINK_SOURCES = [
    ("hiring.cafe — cybersecurity (indexes company career pages directly)",
     "https://hiring.cafe/?q=cybersecurity"),
    ("hiring.cafe — tech apprentice / new grad",
     "https://hiring.cafe/?q=apprentice"),
    ("apprenticeship.gov — official PAID registered cyber apprenticeships",
     "https://www.apprenticeship.gov/apprenticeship-job-finder?searchType=JOB&keyword=cybersecurity"),
    ("LinkedIn — 'cybersecurity apprentice', last 24h",
     "https://www.linkedin.com/jobs/search/?keywords=cybersecurity%20apprentice&f_TPR=r86400"),
]

# ---------------------------------------------------------------------------
# SEARCH BY STATE — like the GoWild bot's one-tap per-hub links, each state gets
# a tappable link that opens LinkedIn Jobs filtered to that state, cyber/tech
# early-career keywords, POSTED IN THE LAST 7 DAYS (f_TPR=r604800). Also drives
# the `--state XX` scrape override, which scopes the live scrape to one state.
# ---------------------------------------------------------------------------

US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii",
    "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
    "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming",
}

# Which states show as tappable links in every digest (edit freely). Ordered by
# the user's base (NY/NJ) then major cyber/tech + government-security hubs.
TARGET_STATES = ["NY", "NJ", "TX", "VA", "MD", "CA", "GA", "FL", "NC", "WA"]

# Keywords used for the per-state LinkedIn links (broad enough to catch
# apprenticeships, early-career, AND career-changer roles).
_STATE_LINK_KEYWORDS = "cybersecurity apprentice OR entry level OR rotational OR help desk"


def state_link(abbr: str) -> tuple[str, str] | None:
    """(label, url) for a single state's last-7-days LinkedIn search, or None if
    the abbreviation is unknown."""
    full = US_STATES.get(abbr.upper())
    if not full:
        return None
    url = ("https://www.linkedin.com/jobs/search/?keywords="
           + quote(_STATE_LINK_KEYWORDS)
           + "&location=" + quote(full)
           + "&f_TPR=r604800")  # past 7 days
    return (f"{full} ({abbr.upper()})", url)


def state_search_links(states: list[str] | None = None) -> list[tuple[str, str]]:
    states = states or TARGET_STATES
    return [lk for a in states if (lk := state_link(a))]


def place_links(place: str) -> list[tuple[str, str]]:
    """(label, url) tappable searches that open STRAIGHT to filtered roles for a
    place — a state OR a city ('Austin', 'New York, NY') — on each real board,
    early-career cyber/tech, last 7 days. Like the GoWild bot's one-tap deep
    links: instant, no scraping, never rate-limited. `place` is free text; a
    2-letter code or state name is expanded to the full state name."""
    loc = US_STATES.get(place.strip().upper(), place.strip())
    kw = _STATE_LINK_KEYWORDS
    return [
        ("Indeed — opens the filtered results",
         "https://www.indeed.com/jobs?q=" + quote(kw) + "&l=" + quote(loc) + "&fromage=7"),
        ("LinkedIn — last 7 days",
         "https://www.linkedin.com/jobs/search/?keywords=" + quote(kw)
         + "&location=" + quote(loc) + "&f_TPR=r604800"),
        ("Google Jobs",
         "https://www.google.com/search?ibp=htl;jobs&q="
         + quote(f"{kw} jobs in {loc} posted this week")),
    ]


def resolve_state(arg: str) -> str | None:
    """Map a CLI --state value (abbreviation or full name) to a full state name
    usable as a jobspy location, or None if unrecognized."""
    if not arg:
        return None
    a = arg.strip()
    if a.upper() in US_STATES:
        return US_STATES[a.upper()]
    for full in US_STATES.values():
        if full.lower() == a.lower():
            return full
    return None


# Educational pillar so the video teaches, not just lists.
APPLY_TIPS = [
    "Apprenticeship ≠ internship: registered apprenticeships (apprenticeship.gov) are W-2 jobs with a wage schedule.",
    "Rotational / LDP programs move you across teams in 6–24 months — great for figuring out your niche.",
    "Apply within 48 hrs of posting; early-career reqs fill from the top of the pile.",
    "No degree? Lead with certs (Security+, Google Cyber) and a home lab in your resume summary.",
    "Tailor the resume title to the exact posting ('Associate SOC Analyst') to beat keyword filters.",
    "Set a LinkedIn alert for 'apprentice cybersecurity' + 'past 24 hours' to catch these first.",
]

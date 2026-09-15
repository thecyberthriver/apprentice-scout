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

import re
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
    # --- Cyber by CISSP domain (D1–D8) — entry/associate-level per specialty ---
    {
        "tag": "cyber-d1-grc",
        "search_term": "GRC analyst OR cyber risk analyst OR security compliance analyst entry level",
        "google_search_term": "entry level GRC risk compliance analyst cybersecurity jobs posted this week",
    },
    {
        "tag": "cyber-d2-data",
        "search_term": "data protection analyst OR privacy analyst OR DLP analyst entry level",
        "google_search_term": "entry level data protection privacy DLP analyst jobs posted this week",
    },
    {
        "tag": "cyber-d3-eng",
        "search_term": "associate security engineer OR junior security engineer OR cloud security analyst",
        "google_search_term": "junior associate security engineer cloud security jobs posted this week",
    },
    {
        "tag": "cyber-d4-network",
        "search_term": "network security analyst OR firewall administrator OR network security engineer entry level",
        "google_search_term": "entry level network security firewall analyst jobs posted this week",
    },
    {
        "tag": "cyber-d5-iam",
        "search_term": "IAM analyst OR identity and access management associate OR access management analyst",
        "google_search_term": "entry level identity and access management IAM analyst jobs posted this week",
    },
    {
        "tag": "cyber-d6-assess",
        "search_term": "junior penetration tester OR vulnerability analyst OR IT security auditor",
        "google_search_term": "junior penetration tester vulnerability analyst security auditor jobs posted this week",
    },
    {
        "tag": "cyber-d7-secops",
        "search_term": "SOC analyst OR incident response analyst OR threat intelligence analyst OR digital forensics analyst",
        "google_search_term": "entry level SOC incident response threat intelligence digital forensics analyst jobs posted this week",
    },
    {
        "tag": "cyber-d8-appsec",
        "search_term": "application security analyst OR DevSecOps engineer OR product security associate junior",
        "google_search_term": "junior application security DevSecOps product security jobs posted this week",
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
    "information security": 5, "security": 3, " soc ": 3, "grc": 3,
    "penetration": 4, "incident response": 4, "threat": 3, "vulnerability": 3,
    # CISSP-domain specialties
    "risk management": 3, "compliance": 2, "privacy": 3, "data protection": 4,
    "data loss prevention": 4, " dlp ": 4, "cryptograph": 4, " pki ": 4, "zero trust": 3,
    "network security": 4, "firewall": 3, " iam ": 4, "identity and access": 4,
    "access management": 3, "privileged access": 4, "pentest": 4, "red team": 4,
    "security audit": 3, "forensic": 4, " dfir ": 5, " siem ": 4, "malware": 4,
    "threat hunt": 4, "blue team": 4, "application security": 4, "appsec": 4,
    "devsecops": 4, "product security": 4, "secure code": 3,
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
        # hiring.cafe indexes company career pages / ATS directly. Its search API
        # is auth-gated (can't scrape), so we hand you its filtered results page.
        ("hiring.cafe — company career pages & ATS",
         "https://hiring.cafe/?q=" + quote(f"{kw} {loc}")),
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


# ---------------------------------------------------------------------------
# ENTRY-to-MID role titles (cyber + IT) — the "what to search for" catalog.
# Used to filter ATS / company-board postings (ats.py) down to roles a career
# starter or switcher can actually land. Matched as a lowercased substring
# against the job title. Add your own freely.
# ---------------------------------------------------------------------------

CYBER_ROLE_TITLES = [
    "soc analyst", "security operations", "security analyst", "cybersecurity analyst",
    "cyber security analyst", "information security analyst", "infosec analyst",
    "security engineer", "cybersecurity engineer", "detection engineer",
    "detection and response", "incident response", "threat analyst", "threat intelligence",
    "threat detection", "vulnerability analyst", "vulnerability management",
    "grc analyst", "grc engineer", "governance risk", "security compliance",
    "compliance analyst", "risk analyst", "identity and access", "iam analyst",
    "iam engineer", "penetration tester", "pen tester", "application security",
    "appsec", "product security", "cloud security", "security specialist",
    "security operations center", "security administrator", "security consultant",
    "soc support", "security awareness", "ot/ics", "ics security",
    "associate security", "junior security", "security analyst i", "security analyst ii",
]

# CISSP 8 domains → title keywords (regex, word-bounded so "soc" can't match
# "associate"). Order = tie-break priority when a title spans domains.
# Drives (a) the domain label on every cyber role line in the digest and
# (b) the domain-specific rows in CYBER_ROLE_TITLES below.
CYBER_DOMAINS = {
    "D7 SecOps": [r"\bsoc\b", "security operations", "incident response", "detection",
                  "threat hunt", "threat intel", "threat analyst", "forensic", r"\bdfir\b",
                  "malware", r"\bsiem\b", "blue team", "cyber defense", "security monitoring",
                  r"\bedr\b", r"\bcsirt\b"],
    "D6 Assess/Pentest": ["penetration", "pen tester", "pentest", "red team", "vulnerability",
                          "security assessment", "security audit", "it audit", "security testing",
                          "ethical hack", "offensive security", "bug bounty"],
    "D8 AppSec": ["application security", "appsec", "product security", "devsecops",
                  "secure code", "software security", r"\bsast\b", r"\bdast\b",
                  "security champion"],
    "D5 IAM": [r"\biam\b", "identity", "access management", "privileged access", r"\bpam\b",
               "active directory", r"\bsso\b", "access control", "authentication"],
    "D4 Network Sec": ["network security", "firewall", "network defense", "perimeter",
                       r"\bvpn\b", "wireless security", r"\bsase\b", r"\bcnd\b"],
    "D2 Asset/Data": ["data protection", "privacy", "data loss prevention", r"\bdlp\b",
                      "data classification", "data security", "records management"],
    "D1 Risk & GRC": [r"\bgrc\b", "governance", "risk analyst", "risk management", "cyber risk",
                      "compliance", "policy analyst", "security awareness", "third party risk",
                      "third-party risk", "vendor risk", r"\btprm\b", "information security officer"],
    "D3 Sec Eng/Arch": ["security engineer", "security architect", "cryptograph", r"\bpki\b",
                        "hardware security", "embedded security", "cloud security", "zero trust",
                        "platform security", "infrastructure security", "secure design",
                        "ot/ics", "ics security", "ot security", r"\bics\b", r"\bscada\b"],
}
_DOMAIN_RX = {d: re.compile("|".join(kws)) for d, kws in CYBER_DOMAINS.items()}

# Domain-specific entry/mid titles, derived from the plain-word keywords above
# (regex entries are for labelling only; a bare "\bsoc\b" isn't a title).
CYBER_ROLE_TITLES += sorted({k for kws in CYBER_DOMAINS.values() for k in kws
                             if "\\" not in k} - set(CYBER_ROLE_TITLES))


def cyber_domain(title: str) -> str | None:
    """CISSP domain label for a job title, e.g. 'D7 SecOps', or None."""
    low = title.lower()
    for d, rx in _DOMAIN_RX.items():
        if rx.search(low):
            return d
    return None


def domain_label(title: str, cyber: bool = True) -> str:
    """Digest domain badge: '🔐 D5 IAM' / '🔐 Cyber' / '💻 Tech'."""
    d = cyber_domain(title)
    if d:
        return f"🔐 {d}"
    return "🔐 Cyber" if cyber else "💻 Tech"

IT_ROLE_TITLES = [
    "help desk", "helpdesk", "service desk", "desktop support", "it support",
    "technical support", "support specialist", "support engineer", "support analyst",
    "system administrator", "systems administrator", "sysadmin", "it administrator",
    "network administrator", "network engineer", "network technician",
    "it technician", "it analyst", "it specialist", "it associate",
    "systems engineer", "systems analyst", "site reliability", " sre ",
    "devops engineer", "cloud engineer", "cloud administrator", "data analyst",
    "data engineer", "junior developer", "associate engineer", "software engineer i",
    "software engineer ii", "junior software", "noc technician", "noc analyst",
    "field technician", "technical analyst",
]

ENTRY_MID_TITLES = CYBER_ROLE_TITLES + IT_ROLE_TITLES

# Senior/lead titles to exclude from ATS results. Matched against a
# punctuation-normalized title (so "Principal, X" is caught). Allows "II" (mid)
# but blocks "III"+; separate from SENIOR_BLOCK (which also blocks "ii ").
ATS_SENIOR = [
    " senior ", " sr ", " staff ", " principal ", " lead ", " team lead ",
    " manager ", " director ", " vp ", " vice president ", " head of ",
    " architect ", " chief ", " iii ", " 3 ", " experienced ", " expert ",
    " distinguished ",
]

# Generic cyber hints for titles that name no domain ("Cybersecurity Analyst").
# "soc" lives in CYBER_DOMAINS as \bsoc\b — as a bare substring it matched "associate".
_CYBER_HINTS = ("secur", "cyber", "infosec")  # ICS/OT lives in CYBER_DOMAINS (word-bounded)


def entry_mid_title(title: str) -> bool:
    """True if a job title is an entry-to-mid cyber OR IT role (and not senior)."""
    low = f" {title.lower()} "
    norm = " " + re.sub(r"[^a-z0-9]+", " ", title.lower()).strip() + " "
    if any(s in norm for s in ATS_SENIOR):
        return False
    return any(k in low for k in ENTRY_MID_TITLES)


def is_cyber_title(title: str) -> bool:
    low = title.lower()
    return cyber_domain(title) is not None or any(h in low for h in _CYBER_HINTS)


def is_senior_title(title: str) -> bool:
    """True for senior/lead/exec titles (entry-to-mid bot excludes these)."""
    norm = " " + re.sub(r"[^a-z0-9]+", " ", title.lower()).strip() + " "
    return any(s in norm for s in ATS_SENIOR)


_ENTRY_WORDS = (" apprentice", " intern", " junior ", " jr ", " associate ", " entry ",
                " new grad", " graduate ", " early career ", " early talent ", " trainee ",
                " i ", " 1 ", " help desk ", " service desk ", " desktop support ")


def level_of(title: str) -> str:
    """'entry' | 'mid' | 'senior' from the title alone (ATS gives us no more).
    /search filters on this; default view is entry+mid, 'senior' opts in."""
    if is_senior_title(title):
        return "senior"
    norm = " " + re.sub(r"[^a-z0-9]+", " ", title.lower()).strip() + " "
    return "entry" if any(w in norm for w in _ENTRY_WORDS) else "mid"


def tech_title(title: str) -> bool:
    """Any-level cyber OR IT title (the index keeps seniors; ATS boards list
    sales/marketing too, so this is the 'is it our field at all' gate)."""
    low = f" {title.lower()} "
    return cyber_domain(title) is not None or any(k in low for k in ENTRY_MID_TITLES)


# ---------------------------------------------------------------------------
# ATS / COMPANY BOARDS — scraped DIRECTLY from each employer's public job-board
# API (Greenhouse / Lever expose these for job distribution — allowed, no key).
# This is the "employer websites / ATS that allow scraping" source. (slug, name)
# Add any company that hosts on these ATSes; verify the slug returns jobs first:
#   Greenhouse: https://boards-api.greenhouse.io/v1/boards/<slug>/jobs
#   Lever:      https://api.lever.co/v0/postings/<slug>?mode=json
# ---------------------------------------------------------------------------

GREENHOUSE_BOARDS = [
    # Security / cyber-focused employers
    ("cloudflare", "Cloudflare"), ("datadog", "Datadog"), ("okta", "Okta"),
    ("huntress", "Huntress"), ("elastic", "Elastic"), ("zscaler", "Zscaler"),
    ("recordedfuture", "Recorded Future"), ("abnormalsecurity", "Abnormal Security"),
    ("expel", "Expel"), ("dragos", "Dragos"), ("cybereason", "Cybereason"),
    ("netskope", "Netskope"), ("tanium", "Tanium"), ("bugcrowd", "Bugcrowd"),
    ("knowbe4", "KnowBe4"), ("nozominetworks", "Nozomi Networks"),
    ("censys", "Censys"), ("tailscale", "Tailscale"),
    # Tech / IT employers (IT, cloud, SRE, support, data roles)
    ("gitlab", "GitLab"), ("fastly", "Fastly"), ("twilio", "Twilio"),
    ("databricks", "Databricks"), ("mongodb", "MongoDB"), ("vercel", "Vercel"),
    ("stripe", "Stripe"), ("coinbase", "Coinbase"), ("robinhood", "Robinhood"),
    ("affirm", "Affirm"), ("brex", "Brex"), ("sofi", "SoFi"),
    ("reddit", "Reddit"), ("airbnb", "Airbnb"), ("lyft", "Lyft"),
    ("roblox", "Roblox"), ("discord", "Discord"), ("figma", "Figma"),
    ("asana", "Asana"), ("gusto", "Gusto"), ("instacart", "Instacart"),
    ("pinterest", "Pinterest"),
]

LEVER_BOARDS = [
    ("spotify", "Spotify"),
    # Add cyber/tech employers that host on Lever, e.g. ("company", "Company").
]


# Educational pillar so the video teaches, not just lists.
APPLY_TIPS = [
    "Apprenticeship ≠ internship: registered apprenticeships (apprenticeship.gov) are W-2 jobs with a wage schedule.",
    "Rotational / LDP programs move you across teams in 6–24 months — great for figuring out your niche.",
    "Apply within 48 hrs of posting; early-career reqs fill from the top of the pile.",
    "No degree? Lead with certs (Security+, Google Cyber) and a home lab in your resume summary.",
    "Tailor the resume title to the exact posting ('Associate SOC Analyst') to beat keyword filters.",
    "Set a LinkedIn alert for 'apprentice cybersecurity' + 'past 24 hours' to catch these first.",
]


if __name__ == "__main__":  # self-check: python searchspec.py
    assert cyber_domain("Associate SOC Analyst") == "D7 SecOps"
    assert cyber_domain("IAM Analyst I") == "D5 IAM"
    assert cyber_domain("Junior Penetration Tester") == "D6 Assess/Pentest"
    assert cyber_domain("GRC Analyst") == "D1 Risk & GRC"
    assert cyber_domain("Associate Software Developer") is None   # "soc" in "associate"
    assert cyber_domain("Help Desk Technician") is None
    assert is_cyber_title("Cybersecurity Analyst") and not is_cyber_title("Associate Developer")
    assert entry_mid_title("Privacy Analyst") and entry_mid_title("DevSecOps Engineer")
    assert domain_label("Network Security Engineer") == "🔐 D4 Network Sec"
    assert domain_label("Data Analyst", cyber=False) == "💻 Tech"
    assert level_of("Associate SOC Analyst") == "entry" and level_of("SOC Analyst I") == "entry"
    assert level_of("SOC Analyst II") == "mid" and level_of("Security Engineer") == "mid"
    assert level_of("Senior Security Engineer") == "senior" and level_of("Director, GRC") == "senior"
    assert tech_title("Senior Security Engineer") and not tech_title("Account Executive")
    assert not is_cyber_title("Senior Financial Analyst - Analytics")   # "ics " used to match
    assert cyber_domain("ICS Security Analyst") == "D3 Sec Eng/Arch"
    print("searchspec self-check OK —", len(QUERIES), "queries,", len(CYBER_ROLE_TITLES), "cyber titles")

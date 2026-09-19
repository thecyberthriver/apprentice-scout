#!/usr/bin/env python3
"""
boolsearch.py — recruiter-style BOOLEAN search over employer ATS boards only.

Sources: ats.py (Greenhouse / Lever / Ashby / SmartRecruiters / Workday public
job-board APIs). No LinkedIn, Indeed, Google Jobs, or any aggregator — every hit
is the employer's own posting on its own ATS.

  python boolsearch.py                                   # default entry-level cyber string, print
  python boolsearch.py --send                            # ...and post it to Telegram
  python boolsearch.py "(soc OR siem) AND analyst NOT senior" --days 21 --send
  python boolsearch.py --level entry,mid --selfcheck
"""

from __future__ import annotations

import re
import sys

import ats
import searchspec as SPEC

# Entry-level cyber, recruiter boolean. Terms match title + company + location.
DEFAULT_QUERY = (
    '("security" OR "cyber" OR "soc" OR "infosec" OR "grc" OR "iam" OR '
    '"vulnerability" OR "threat" OR "incident" OR "risk" OR "compliance") '
    'AND ("analyst" OR "engineer" OR "specialist" OR "associate" OR "apprentice" '
    'OR "intern" OR "trainee" OR "technician" OR "administrator" OR "consultant") '
    'NOT ("sales" OR "account executive" OR "recruiter" OR "counsel" OR '
    '"attorney" OR "paralegal" OR "clearance required")'
)

_TOKEN = re.compile(r'"([^"]*)"|\(|\)|\b(?:AND|OR|NOT)\b|[^\s()]+')


def compile_query(query: str):
    """Boolean string -> predicate. AND/OR/NOT, parens, "quoted phrases".
    Implicit AND between adjacent terms; NOT x means AND NOT x."""
    terms, parts, prev_operand = [], [], False
    for m in _TOKEN.finditer(query):
        tok = m.group(0)
        up = tok.upper()
        if tok in "()" or up in ("AND", "OR", "NOT"):
            if up == "NOT" and prev_operand:
                parts.append("and")
            elif tok == "(" and prev_operand:
                parts.append("and")
            parts.append({"AND": "and", "OR": "or", "NOT": "not"}.get(up, tok))
            prev_operand = tok == ")"
        else:
            if prev_operand:
                parts.append("and")
            terms.append((m.group(1) if m.group(1) is not None else tok).lower())
            parts.append(f"(T[{len(terms) - 1}] in s)")
            prev_operand = True
    expr = compile(" ".join(parts) or "True", "<query>", "eval")
    return lambda s: eval(expr, {"__builtins__": {}}, {"T": terms, "s": s.lower()})  # noqa: S307


def search(query: str, days: int, levels: tuple[str, ...], cyber_only: bool) -> list[dict]:
    match = compile_query(query)
    roles = ats.scrape_ats(days=days, log=lambda m: print(m, file=sys.stderr), levels=levels)
    hits, seen = [], set()
    for r in roles:
        if cyber_only and not SPEC.is_cyber_title(r["title"]):
            continue
        if not match(f"{r['title']} {r['company']} {r.get('location', '')}"):
            continue
        key = r.get("url") or f"{r['title']}|{r['company']}"
        if key in seen:
            continue
        seen.add(key)
        hits.append(r)
    hits.sort(key=lambda r: (r.get("posted") or "", r["company"]), reverse=True)
    return hits


def format_hits(hits: list[dict], query: str, days: int, levels) -> str:
    from apprentice_scout import esc
    lines = [f"🔐 <b>ATS boolean search — {len(hits)} role(s)</b>",
             f"<i>Employer ATS only (Greenhouse · Lever · Ashby · SmartRecruiters · "
             f"Workday) · last {days}d · level: {'+'.join(levels)}</i>",
             "", f"<code>{esc(query)}</code>", ""]
    for i, r in enumerate(hits, 1):
        bits = [b for b in (r.get("location"), r.get("posted"), r.get("salary")) if b]
        lines.append(f"{i}. <a href=\"{esc(r['url'])}\">{esc(r['title'])}</a> — "
                     f"<b>{esc(r['company'])}</b>")
        lines.append(f"    {esc(' · '.join(bits))}")
    if not hits:
        lines.append("No ATS postings matched. Widen the string or raise --days.")
    else:
        lines.append("")
        lines.append("<i>Each link is the employer's own ATS posting — verify before applying.</i>")
    return "\n".join(lines)


def _selfcheck() -> None:
    m = compile_query('("soc" OR siem) AND analyst NOT senior')
    assert m("SOC Analyst I")
    assert m("SIEM Analyst, Detection")
    assert not m("Senior SOC Analyst")
    assert not m("SOC Engineer")          # 'analyst' required
    assert not m("Data Analyst")          # soc/siem required
    assert compile_query('"incident response"')("Incident Response Intern")
    assert not compile_query('"incident response"')("Incident Intern Response")
    print("selfcheck ok")


def main() -> int:
    argv = sys.argv[1:]

    def opt(name, default):
        return argv[argv.index(name) + 1] if name in argv else default

    if "--selfcheck" in argv:
        _selfcheck()
        return 0
    days = int(opt("--days", 14))
    levels = tuple(opt("--level", "entry").split(","))
    positional = [a for i, a in enumerate(argv)
                  if not a.startswith("--") and (i == 0 or not argv[i - 1].startswith("--"))]
    query = positional[0] if positional else DEFAULT_QUERY
    hits = search(query, days, levels, cyber_only="--all-tech" not in argv)
    text = format_hits(hits, query, days, levels)
    print(re.sub(r"<[^>]+>", "", text))
    if "--send" in argv:
        from apprentice_scout import send_message
        return 0 if send_message(text) else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

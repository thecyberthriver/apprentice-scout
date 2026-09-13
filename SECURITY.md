# Security Policy

## Reporting a vulnerability

Please **do not open a public issue**. Report privately via GitHub's
[private vulnerability reporting](https://github.com/thecyberthriver/apprentice-scout/security/advisories/new)
(Security tab -> Report a vulnerability).

## Secrets

No secrets live in source control. Credentials are supplied at runtime via a
git-ignored `secrets_local.py` (Telegram bot token, chat id, optional
`ANTHROPIC_API_KEY`) — or environment variables. If a secret was ever committed,
treat it as compromised and rotate it (BotFather `/revoke` for a Telegram token;
the provider console for an API key).

## Data & sources

This tool reads **public** job-board listings only (via `python-jobspy`). It does
not authenticate to, scrape login-walled areas of, or submit applications to any
site. It does not collect personal data.

## Automated checks

- Secret scanning + push protection (public repos)
- Dependabot alerts and security updates

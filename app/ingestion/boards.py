"""The curated company-board list — the seed of your job index.

Each entry is one real company's public job board. The list below is a
STARTER list of well-known technology companies; growing it toward
hundreds of boards is Exercise 2 of this step (and a good first
Pull Request for a student: one line per company).

Important honesty note: companies change hiring systems, and board tokens
die. That is why scripts/check_boards.py exists — it tests every entry
against the live interface and reports which are alive, so the list is
VERIFIED, not assumed. Run it before relying on the list, and prune what
it reports dead. A curated list you have not checked is a guess.
"""

# Greenhouse board tokens: the <token> in
# https://boards-api.greenhouse.io/v1/boards/<token>/jobs
GREENHOUSE_BOARDS: list[str] = [
    "anthropic",
    "stripe",
    "airbnb",
    "pinterest",
    "reddit",
    "robinhood",
    "coinbase",
    "databricks",
    "dropbox",
    "duolingo",
    "figma",
    "gitlab",
    "instacart",
    "lyft",
    "doordash",
    "cloudflare",
    "mongodb",
    "datadog",
    "twilio",
    "asana",
]

# Lever company names: the <company> in
# https://api.lever.co/v0/postings/<company>
LEVER_COMPANIES: list[str] = [
    "plaid",
    "netflix",
    "palantir",
    "attentive",
    "ramp",
]

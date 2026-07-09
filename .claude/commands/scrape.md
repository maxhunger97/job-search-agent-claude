---
description: Search for new job postings across your configured search profiles, locations, and company watchlist, score them, and update data/job_leads.json.
---

# /scrape

Read `config.yaml` first (`search_profiles`, `search_locations`, `company_watchlist`, `linkedin_follows`). If it still looks like the fictional Alex Berger example, or is missing, tell the person to run `/setup` first and stop.

## Why this command doesn't hardcode a scraper per job portal

An earlier version of this agent used site-specific scrapers (fixed CSS selectors per portal). They broke every time a portal changed its markup, and they don't generalize across countries/portals different users will need. This command instead uses your own web search / browsing tools directly, driven by the configured search profiles — same "broad recall, then filter" methodology, implemented with tools that adapt instead of a brittle per-site scraper.

## What to do

1. For each `search_profiles.<name>`, run a web search for each of its `terms`, combined with each `search_locations` entry (e.g. "ESG Consultant Berlin", "Sustainability Consultant Berlin jobs"). Prefer general job-search queries over portal-specific URL hacking — let your search tool surface results from whatever aggregators/boards are actually indexed for that market (LinkedIn, Indeed, company career pages, national job boards, etc.).
2. For each `company_watchlist` entry, check its `careers_url` (or search "<company name> careers <role>") for open roles matching any configured search profile.
3. Cast a wide net deliberately — include postings that are only loosely on-target. The scoring engine's disqualification rules are what filters noise, not the search step. Do not pre-filter by eye before scoring; let `config.yaml` do that job so the person's tuning actually gets exercised.
4. For every posting found, collect: `id` (stable — hash of URL is fine), `title`, `company`, `location`, `description` (as much of the actual posting text as you can get — the scorer and CV/CL generator both need real text, not just a title), `url`, `source` (which portal/search this came from — keep this, it's what the checkup below reports on).
5. Deduplicate by URL/id before writing.
6. Write the full list to `data/job_leads_raw.json` as a JSON array of flat objects (see `engine/cli.py` docstring for the exact schema).
7. Run:
   ```
   python3 engine/cli.py score
   ```
   This merges into `data/job_leads.json`, preserving `applied`/`rejected` flags on postings you've already seen, and prints the top-ranked results.

## Scrape Checkup (always show this, every run)

Don't just report the top results — show the mechanism so the person can tell the difference between "no good jobs exist right now" and "the search or scoring missed something":

- Every query actually run (search-profile term × location, and each watchlist company's careers check), with a raw result count per query.
- Total raw postings found, how many were removed as duplicates, and how many remained in `data/job_leads_raw.json`.
- How many of those passed `min_score` into `data/job_leads.json`, and how many were filtered out by a disqualification rule (name which rule, when it's a large chunk — e.g. "12 rejected for seniority, 4 for wrong domain").
- The top 5-10 by score with their `profile_match`.
- If very few or zero postings passed: say so plainly and suggest a concrete next step (loosen a specific disqualifier, add adjacent search terms, lower `min_score`) rather than treating a quiet run as a success to move past.

Do not generate CVs or cover letters in this command — that's `/apply`.

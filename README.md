# Generic Job Search Agent

A Claude Code job-search coach: parses your CV, learns your job-search
preferences, scores scraped job postings against your own rules, and
generates a tailored CV + cover letter for the ones worth applying to.

This is a genericized, config-driven version of an agent that was originally
built and validated for one specific person's job search. Nothing in
`engine/` knows about any particular field, city, or degree — every rule
lives in `config.yaml` and `cv_system/cv_data.yaml`, which `/setup` builds
for you through a short interview. The engine has been regression-tested to
behave identically to the original hand-tuned version on real data, and
separately smoke-tested end to end against a fictional persona in a
completely different field (ESG/climate policy, Berlin) to confirm it
generalizes and never leaks anyone else's information into your CV or
cover letter.

## Quick start

1. Clone this repo and open it in Claude Code.
2. Run `/setup`. You'll be asked to paste or upload your CV, answer a few
   questions about the roles/locations/companies you're targeting, and give
   Claude 2-4 real stories to draw from for cover letters. This produces:
   - `cv_system/cv_data.yaml` — your CV content, ATS keyword allow-list, and
     cover-letter building blocks
   - `cv_system/config_<variant>.yaml` — one file per CV "flavor" you want
     (e.g. a consulting-facing version and a technical version of the same CV)
   - `config.yaml` — your job search terms, locations, watchlist companies,
     and every scoring/disqualification rule
   - `CUSTOMIZATION_REPORT.md` — a plain-language summary of everything that
     got configured and why, so you can hand-edit any rule later with full
     context
3. Run `/scrape` whenever you want fresh postings. It searches your
   configured terms/locations/watchlist, scores everything against your
   rules, and reports the top results.
4. Run `/apply` to generate a CV + cover letter for your top-ranked,
   not-yet-applied postings, and build an HTML report
   (`output/job_report.html`) linking to all of them.

You can also just describe changes in plain language at any time —
"stop showing me anything with 'Manager' in the title" or "add a fourth cover
letter story about X" — and Claude will edit the underlying config directly.

## Folder layout

```
config.yaml               # YOUR search + scoring config (created by /setup, gitignored)
cv_system/
  cv_data.yaml             # YOUR CV content + cover-letter data (created by /setup, gitignored)
  config_*.yaml            # YOUR CV variant configs (created by /setup, gitignored)
  template.html            # shared CV HTML template — generic, not user-specific
engine/
  scorer.py                # generic scoring engine — reads config.yaml, no hardcoded field/city rules
  cv_generator.py           # generic CV + cover-letter generator — reads cv_data.yaml + config.yaml
  cli.py                   # `python3 engine/cli.py score|generate|report` — used by /scrape and /apply
templates/
  config.example.yaml       # documented reference config, fictional "Alex Berger" persona
  cv_data.example.yaml      # documented reference CV data, same fictional persona
  smoke_test_jobs.json      # synthetic postings used to validate a fresh setup
.claude/commands/
  setup.md / scrape.md / apply.md   # the three slash commands
```

Two files ship pre-filled rather than gitignored, as worked examples of the
variant-config schema: `cv_system/config_consulting.yaml` and
`cv_system/config_policy.yaml`. They belong to the same fictional persona as
`templates/*.example.yaml` — `/setup` will create your own
`cv_system/config_<variant>.yaml` files alongside (or instead of) them.

## Design notes

- **CV tailoring is mechanical.** The engine swaps in the right variant,
  reorders/highlights skills, and fills a summary template — it never invents
  a skill you didn't list in `cv_data.yaml`'s `skill_signals`.
- **Cover letters need your actual voice**, so they're assembled from
  `experience_catalog` stories you provide during `/setup`, not generated
  from scratch. The HTML shell and structure are fixed; only the
  hook/evidence/company-reasoning/personal-note content varies per job.
- **Search casts a wide net; scoring rules do the filtering.** `/scrape`
  deliberately over-collects loosely-relevant postings — your
  disqualification and domain-gate rules in `config.yaml` are what should be
  doing the precision work, not the search terms.

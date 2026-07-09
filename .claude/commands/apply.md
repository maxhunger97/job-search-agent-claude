---
description: Generate a tailored CV and cover letter for your top-ranked, not-yet-applied job leads, and produce an HTML report.
---

# /apply

Read `data/job_leads.json`. If it doesn't exist or is empty, tell the person to run `/scrape` first and stop.

## What to do

1. Ask the person how many new applications they want prepared this run (default to 15 if they don't say, matching the pattern this agent was validated with).
2. Run:
   ```
   python3 engine/cli.py generate --top <N>
   ```
   This picks the top-ranked jobs that aren't already flagged `applied` or `rejected`, generates a CV and cover letter for each via `engine/cv_generator.py`, and writes the output paths back into `data/job_leads.json`.
3. Run:
   ```
   python3 engine/cli.py report
   ```
   This builds `output/job_report.html` — a static, shareable/printable table of every scored job with links to its CV/CL and the original posting. Good for a quick read or sending to someone else; not interactive.
4. Mention `python3 engine/server.py` (open `http://localhost:5555`) as the interactive alternative: filter/search/sort the same data live, regenerate a single CV/CL on demand (with a spot to paste a manually-copied job description if the scraped one was thin), and use **Mark Applied** / **Mark seen** buttons instead of hand-editing `data/job_leads.json`. Marking a job Applied there also adds it to `data/applications_archive.json` — see the README's "Reviewing & archiving jobs" section for why that's a local file by default rather than a Notion/Sheets sync.
5. Spot-check at least one generated cover letter yourself before telling the person it's ready: confirm it reads like a real paragraph (not a template with unfilled placeholders), doesn't repeat the same experience story twice, and doesn't trip the banned-phrase/dash warnings that `cv_generator.py` logs to the console during generation. If warnings were printed, mention them and offer to hand-fix that specific letter.

## Generation Checkup (always show this, every run)

- List every job a CV/CL pair was generated for: title, company, score, and which experience-catalog story ended up leading the cover letter for it — this ties the output back to the Phase 3 checkup from `/setup` so the person can see their own stories actually being used, and notice if one story is being overused while others never fire.
- Flag any banned-phrase or dash warnings printed during generation, per job, rather than only mentioning them if asked.
- State where the report is (`output/job_report.html`) and how many CV/CL pairs were generated this run vs. total in the system.

Remind the person that once they actually apply to one, they (or you, if they tell you) should mark it applied — either by running the server and clicking **Mark Applied**, or by setting `"applied": true` directly in `data/job_leads.json`. Do not mark anything as applied yourself unless the person explicitly tells you they applied — this command only prepares materials, it never claims an application was sent.

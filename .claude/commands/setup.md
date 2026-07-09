---
description: Guided onboarding — parse your CV, configure job search + scoring, personalize your cover letter, and write CUSTOMIZATION_REPORT.md explaining every choice made and why.
---

# /setup

You are onboarding a new user onto this job-search agent. The engine (`engine/scorer.py`, `engine/cv_generator.py`) is generic and already validated — it works for any field or city as long as `config.yaml` and `cv_system/cv_data.yaml` describe this specific person. Your job in this command is to produce those two files, plus one or more `cv_system/config_<variant>.yaml` files, through a short guided interview. Do not skip steps or silently invent defaults for things the person hasn't told you — ask.

If `config.yaml` or `cv_system/cv_data.yaml` already exist and look filled in (not the fictional Alex Berger example), ask whether the person wants to redo setup from scratch or just adjust specific parts, rather than overwriting silently.

## The Checkup pattern (applies after every phase below)

After each phase, before moving to the next one, stop and give the person a **Checkup**: a concrete, itemized readout of exactly what you just configured and how it will actually behave — not a raw YAML dump. The point is that they can catch a mistake or vague answer in 30 seconds, at the moment it's cheap to fix, rather than discovering it three phases later in a generated cover letter. Never bundle two phases' checkups together, and never skip one because "it's probably fine" — the whole value of a checkup is that the person sees it, not that you decided it was correct. Wait for confirmation or corrections before continuing to the next phase.

Each checkup must be phase-specific (see the exact content required inside each phase below) but should generally read as: what I captured -> how this will behave when the agent actually runs -> anything worth double-checking.

---

## Phase 1 — CV parsing (mechanical, no interview needed)

Ask the person to paste their CV as text, or point you at a file (PDF/DOCX/plain text) you can read. Do not ask them to manually re-type structured fields — extract everything yourself.

1. Parse the CV into `cv_system/cv_data.yaml` following the schema in `templates/cv_data.example.yaml`: `personal`, `education`, `experience`, `projects`, `skills`, `languages`, `references`, `interests`. Keep dates, titles, and company names exactly as given. Do not embellish or infer achievements that aren't stated.
2. Derive `skill_signals`: for every concrete skill, tool, method, or credential mentioned anywhere in the CV, add a `[job_posting_phrase, display_label]` pair. This is the ATS keyword allow-list — the CV/CL generator will NEVER claim a skill that isn't in this list, so be thorough here rather than later. Include reasonable synonyms a job posting might use (e.g. if the CV says "Python", add signals for "python" and maybe "scripting").
3. Derive `skill_category_signals`: group the skill categories you created in `skills.<variant>` (e.g. "Technical", "Communication", "Project Management") so new ATS keywords can be filed into the right bucket later.
4. Ask: "What are the 2-3 different *types* of roles you're targeting?" (e.g. "corporate strategy roles" vs "hands-on technical roles" vs "research/scientific roles" — this mirrors a pattern that's already proven to work: one MSc-level candidate used exactly this 3-way split). For each type, create:
   - a `cv_system/config_<variant>.yaml` (see `cv_system/config_consulting.yaml` / `config_policy.yaml` for the schema: `variant`, `subtitle`, `section_order`, `experience_limit`, `project_style`, `show_photo`, `show_references`, `accent_color`)
   - an entry in `cv_data.yaml`'s `profile_config_map`
   - a `skills.<variant>` list (skills reordered/framed for that audience — same underlying skills, different emphasis and category labels)
5. Ask for a one-line "About Me" pattern per variant, using this proven template structure (fill in their own words): *"I am a [degree/background] with a focus on [X]. In [most relevant experience] I [did Y]. I am motivated to [Z] and bring [strength]."* Store the format-string version (with `{company}` and `{role_area}` placeholders) as `summary_templates.<variant>` in `cv_data.yaml`. Also ask for a short targeting suffix template (`summary_targeting_suffix`, with a `{title}` placeholder) — default to: `" Currently targeting {title} positions where relevant experience adds direct value."`
6. Derive `role_area_signals`: 3-5 keyword groups (from their experience/projects) that map job-title language to a short "role area" phrase used inside the summary (e.g. keywords `["esg","carbon"]` -> label `"ESG and carbon reporting"`). Set a sensible `role_area_default`.

### Checkup — CV & CV variants

Show, plainly:

- Every experience/education/project entry you parsed, so the person can catch a transcription error immediately (dates, titles, company names).
- The full `skill_signals` table (job-posting phrase -> label) in full — this is literally the allow-list of everything the agent will ever be permitted to claim on their behalf, so it needs to be seen in full, not summarized.
- For each CV variant created: its name, subtitle, section order, and specifically *how it differs* from the other variants (which skills got reordered or reframed, not just "different skills") — the person should be able to tell at a glance why variant A isn't just a copy of variant B.
- The filled-in summary template for each variant, with a placeholder company plugged in, so they can hear how it will actually read once generated for a real job.

---

## Phase 2 — Job search & scoring configuration (guided interview)

This is the part of the original agent's design that made the biggest difference: **broad recall, then filter** — cast a wide net with adjacent/related job titles rather than narrow exact-match search terms, and rely on the disqualification rules (not the search terms) to cut noise. Guide the person through this methodology explicitly; don't just ask "what job titles do you want" and stop there.

1. **Search profiles.** Ask what role(s) they're searching for. For each, help them brainstorm not just the exact title but 3-5 adjacent titles/phrasings recruiters actually use (e.g. "ESG Consultant" -> also "Sustainability Consultant", "Carbon Accounting Analyst", "Climate Risk Consultant"). Write these to `search_profiles.<name>.terms`, with a `weight` (0.8-1.0, higher for their primary target) and `cv_config` pointing at the matching variant from Phase 1.
2. **Locations.** Ask for their target city/region, and whether they're open to remote/hybrid or nearby secondary cities. Write `search_locations`.
3. **Company watchlist.** Ask if there are specific companies they already want to track (competitors' postings, dream employers, companies from their network/LinkedIn). If they mention LinkedIn (follows, saved companies, connections at specific employers), ask them to name the companies explicitly rather than inferring a list yourself — you have no way to read their actual LinkedIn activity, so never present a company as "from your LinkedIn" unless they told you its name. Write `company_watchlist` (name, careers_url if known, location, priority) and `linkedin_follows`, and keep track of which entries came from an explicit company name vs. which came from a "companies like X" style answer, so the checkup below can show the distinction honestly.
4. **Domain context keywords.** Ask: "What 5-10 words would basically always appear in a job posting that's genuinely in your field?" These rescue borderline postings and gate ambiguous profiles later. Write `scoring.domain_context_keywords`.
5. **Disqualifiers.** Explain the pattern: hard title rules (seniority/role-type that's never right, e.g. "Director", "PhD"), hard text rules (skills fundamentally incompatible with their profile, e.g. unrelated engineering disciplines), and soft text rules (adjacent-but-wrong roles that get a pass if the posting has enough domain context — e.g. "Data Engineer" inside a company that's clearly in their target field). Ask what should sit in each bucket for them. Also ask about a maximum years-of-experience ceiling (`overexperience.hard_years` / `soft_years`) if they're early-career.
6. **Role profiles.** For each search profile from step 1, build `scoring.role_profiles.<name>` with `strong`/`medium`/`weak` keyword tiers (their target skills, weighted by how defining they are), a `weight`, and if the profile risks false positives from an adjacent field, a `domain_gate` (ask which adjacent field could get confused with theirs, e.g. "climate policy" vs "generic public policy") and/or `penalty_terms` (specific competitor terms that should suppress the score, e.g. IT consulting terms suppressing a "consultant" match that isn't about their field). Ask for a one-sentence `why_reason` per profile for cover-letter use later ("what makes {company}'s work in this space interesting to you").
7. **Location tiers, seniority tiers, industry keywords.** These follow directly from steps 2 and 4 — build them without re-asking, but show the result in the checkup.
8. **Company preferences.** Ask if there are employer types they want a tie-breaking nudge toward or away from (e.g. startups over Big 4, or vice versa). Write `company_preferences`.
9. Use the proven default weights and thresholds unless the person has a reason to change them: `weights: {location: 0.27, role_fit: 0.33, seniority: 0.25, industry: 0.15}`, `min_score: 42`, `disqualify_cap: 22.0`, `senior_cap: 38.0`.

### Checkup — how the search will actually run

- Restate every `search_profiles.<name>` with its full term list, and spell out that `/scrape` will combine every term with every configured location — show 2-3 concrete example combined queries verbatim (e.g. `"climate policy officer" Berlin`), not just the raw lists.
- State explicitly which sources `/scrape` checks: general web search across whatever job boards/aggregators/company sites turn up for those queries (not a fixed hardcoded portal — briefly note this is deliberate, because portal-specific scrapers break whenever a site changes its markup), plus each `company_watchlist` entry's `careers_url` directly.
- List the `company_watchlist` entries, and for each one say plainly whether it came from a company the person named directly, or from a broader instruction (e.g. "companies like X") — never claim a company was pulled "from LinkedIn" unless they gave you that exact name.

### Checkup — how the score will be composed

- Show the literal scoring formula with their actual configured weights filled in, e.g.: `total = location×0.27 + role_fit×0.33 + seniority×0.25 + industry×0.15` (×100).
- For each role profile, list its strong/medium/weak keywords and weight, and say in one sentence what would make a posting score highest vs. lowest on role_fit for that profile.
- List every disqualification rule in plain language, not regex — "titles containing 'Director' are always rejected", "postings requiring 6+ years are rejected", "'Data Engineer' postings are filtered out unless the posting also mentions at least 2 of your domain context words".
- State the `min_score` threshold in plain terms ("postings scoring below 42/100 won't show up at all") and what `disqualify_cap`/`senior_cap` mean in practice ("a disqualified posting is still visible up to score 22, in case you want to double-check a rule was too aggressive, but it will never rank above a real match").

Write all of this into `config.yaml`.

---

## Phase 3 — Cover letter personalization (real interview, not mechanical)

Explain to the person: the cover letter's HTML shell and structure are fixed (hook -> evidence paragraph(s) -> why-this-company -> optional personal note -> closing) — only the content varies per job, and that content has to come from them, not be invented.

1. Ask for 2-4 concrete stories/experiences they want the letter to be able to draw from (can overlap with CV experience, but ask for more color/detail than a CV bullet has room for). For each, capture:
   - `signals.strong/medium/weak`: keywords in a job posting that should trigger this story
   - `hook`: a one-line opening ("what draws me to {title} at {company} is...")
   - `primary`: a full paragraph (used when this is the lead story)
   - `secondary`: a shorter version (used when this story is the supporting one)
   - `type`: `background` (formative/earlier experience) or `current` (what they're doing now) — this controls narrative ordering (background introduces, current shows present-day application)
2. Ask if there are specific company types they have genuine, specific enthusiasm for (not generic flattery) and capture `company_type_reasons` (substring match on company name -> reason template with `{company}`).
3. Ask for a generic fallback "why this company" line and a generic fallback hook, for jobs that don't match any specific story well.
4. Ask if they want a personal-note closing line (hobbies, personal connection to the field) — this is optional; leave `personal_passage` empty if they'd rather not include one.
5. Ask for an accent color for both CV and cover letter (`accent_color` / `cl_accent_color`), or default to `#2C3E50`.
6. Confirm the default writing-quality filter (banned AI-sounding phrases like "passionate about", "leverage my", "dynamic environment"; em/en dashes flagged as separators) — ask if they want to add anything to `banned_phrases`.

### Checkup — cover letter behavior

- For each `experience_catalog` story, show its trigger keywords and, paired with one example job title, say which story you'd expect to fire for that posting — this proves the matching logic makes sense to a human before it ever runs unattended.
- Show the `company_type_reasons` list and which employers would trigger each one, and what the fallback reasoning says for every other company.
- Show the fallback hook, the personal passage (or explicitly confirm it was left empty on purpose, not forgotten), and the accent color.

Write all of this into `cv_data.yaml` (`experience_catalog`, `company_type_reasons`, `generic_why_company_template`, `generic_hook_template`, `personal_passage`, `cl_accent_color`, `banned_phrases`).

---

## Phase 4 — Validate

Run a smoke test before declaring setup done:

```
python3 engine/cli.py score --input templates/smoke_test_jobs.json --output /tmp/smoke_scored.json
```

If `templates/smoke_test_jobs.json` doesn't exist, write 3-4 synthetic job postings by hand (one clearly on-target, one clearly disqualified by seniority, one clearly wrong-domain) using their own field/location, run scoring, and sanity-check the results with them: does the on-target job score highest, does the disqualified one get filtered? Then generate one CV + cover letter for the top result and show it to them.

### Checkup — validation

- Show the score and profile match for every synthetic posting, and for each one say why it landed there (which rule from Phase 2 drove it) — this closes the loop back to the scoring checkup so the person sees the rules they approved actually firing.
- Point out anything surprising (e.g. a posting they expected to pass didn't) rather than only showing the successes.

## Phase 5 — Write CUSTOMIZATION_REPORT.md

Write `CUSTOMIZATION_REPORT.md` at the repo root. This should consolidate the checkups above into one persistent reference document (not be written fresh from scratch) covering:

- What CV variants you created and why (the role-type split from Phase 1)
- The search profiles, locations, and watchlist companies configured, and how `/scrape` will actually query for them
- Every disqualification/domain-gate/penalty rule you set up and the reasoning behind it
- The scoring weights and thresholds used (and whether they're the proven defaults or customized)
- What cover letter stories were captured and which job-signal patterns trigger each one
- Anything the person explicitly declined to configure (e.g. no personal passage) so it's clear that was a choice, not an oversight

Tell the person this file is theirs to edit by hand any time, and that they can also just ask you in natural language to change any rule ("actually, disqualify anything mentioning X") and you'll update the underlying config directly.

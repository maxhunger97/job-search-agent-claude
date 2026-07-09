"""
Generic CV + Cover Letter Generator — config/data-driven, field-agnostic.

Nothing about a specific person's degree, employer, or life story is hardcoded
here. Two data sources drive everything:

  cv_data.yaml   — the person's real CV content (education, experience, skills,
                    projects) PLUS a few generated-content sections that /setup
                    fills in: summary_templates, skill_signals, experience_catalog,
                    company_type_reasons, personal_passage.
  config.yaml    — role_profiles (shared with the scorer) used to pick a CV
                    variant and to generalize "why this company" reasoning.

Design principles carried over from the original, validated system (see
CUSTOMIZATION_REPORT.md for what your own /setup run configured):

  1. CV tailoring is MECHANICAL: swap in the matching variant, reorder/highlight
     skills, rewrite the summary from a template, done. No fabrication risk,
     because ATS keyword injection only ever surfaces skills the person's own
     cv_data.yaml already lists — never a skill they didn't tell us they have.
  2. Cover letters need a human voice, so they draw from `experience_catalog`
     (the person's own stories, gathered by the CL-specific interview in /setup),
     assembled by a generic scoring+composition engine: highest-signal-match
     experience leads, a secondary one supports, ordered so background
     experience introduces a current role rather than the other way around.
  3. The letter's HTML shell, edit toolbar, and structure are FIXED. Only the
     hook / evidence paragraphs / company reasoning / personal note vary per job.
  4. A banned-phrase and banned-character filter runs on every generated
     cover letter, flagging AI-sounding phrasing and em/en-dash-as-separator
     use. This is a generically good writing rule, not specific to anyone,
     and ships on by default; extend it per-user via cv_data.yaml if you want.
"""

import re
import copy
import hashlib
import yaml
from pathlib import Path
from datetime import datetime
from functools import lru_cache
from jinja2 import Environment, FileSystemLoader

ENGINE_DIR = Path(__file__).parent
AGENT_DIR = ENGINE_DIR.parent
CV_SYSTEM_DIR = AGENT_DIR / "cv_system"
OUTPUT_DIR = AGENT_DIR / "output" / "cv"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ─────────────────────────────────────────────
# DATA LOADING
# ─────────────────────────────────────────────

@lru_cache(maxsize=4)
def load_cv_data(cv_data_path: str = None) -> dict:
    path = Path(cv_data_path) if cv_data_path else CV_SYSTEM_DIR / "cv_data.yaml"
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


@lru_cache(maxsize=4)
def load_role_profiles(config_path: str = None) -> dict:
    path = Path(config_path) if config_path else AGENT_DIR / "config.yaml"
    try:
        with open(path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    except FileNotFoundError:
        cfg = {}
    return cfg.get("scoring", {}).get("role_profiles", {})


def _person_name(cv_data: dict) -> str:
    return cv_data.get("personal", {}).get("name", "Applicant")


# ─────────────────────────────────────────────
# ATS KEYWORD EXTRACTION — only from skills the person actually claims
# ─────────────────────────────────────────────

def extract_keywords(title: str, description: str, cv_data: dict, max_kw: int = 8) -> list[str]:
    """
    Match job-posting language against `cv_data['skill_signals']`, a list of
    (job_signal, label) pairs the person defined (or /setup derived from their
    uploaded CV) for skills they genuinely have. This function will NEVER
    surface a skill label that isn't in the person's own skill_signals list —
    that's what keeps this safe to run unattended.
    """
    text = f"{title} {description}".lower()
    signal_map = cv_data.get("skill_signals", [])

    seen_labels = set()
    found = []
    for entry in signal_map:
        signal, label = entry[0], entry[1]
        if signal.lower() in text and label not in seen_labels:
            seen_labels.add(label)
            found.append(label)
        if len(found) >= max_kw:
            break
    return found


# ─────────────────────────────────────────────
# SUMMARY GENERATION
# ─────────────────────────────────────────────

def _detect_role_area(title: str, cv_data: dict) -> str:
    """cv_data['role_area_signals'] is a list of {keywords: [...], label: "..."}
    checked in order — first match wins. Falls back to a generic label."""
    title_lower = title.lower()
    for entry in cv_data.get("role_area_signals", []):
        if any(kw in title_lower for kw in entry["keywords"]):
            return entry["label"]
    return cv_data.get("role_area_default", "this field")


def generate_summary(job, profile: str, cv_data: dict) -> str:
    """Fill the person's own summary template for this CV variant.

    cv_data['summary_templates'][profile] is a Python format-string with
    {company} and {role_area} placeholders — this mirrors the exact "About Me"
    template pattern already validated by hand for the original user:
    "I am a [degree] from [institution] with a focus on [X]. In [project] I
    [did Y]. I am motivated to [Z] and bring [strength]."
    """
    templates = cv_data.get("summary_templates", {})
    template = templates.get(profile) or next(iter(templates.values()), "")
    role_area = _detect_role_area(job.title, cv_data)
    clean_title = _sanitize_job_title(job.title)

    summary = template.format(company=job.company, role_area=role_area)
    targeting_suffix = cv_data.get(
        "summary_targeting_suffix",
        " Currently targeting {title} positions where relevant experience adds direct value.",
    )
    summary = summary.rstrip() + " " + targeting_suffix.format(title=clean_title)
    return summary


# ─────────────────────────────────────────────
# CV GENERATION
# ─────────────────────────────────────────────

def safe_filename(s: str) -> str:
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"\s+", "_", s.strip())
    return s[:40]


def _encode_photo(photo_path: Path):
    import base64
    if not photo_path or not photo_path.exists():
        return None
    ext = photo_path.suffix.lower().lstrip(".")
    mime = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png"}.get(ext, "jpeg")
    with open(photo_path, "rb") as f:
        data = base64.b64encode(f.read()).decode()
    return f"data:image/{mime};base64,{data}"


def generate_cv_for_job(job, cv_data_path: str = None, config_path: str = None) -> str:
    """Generate a tailored CV as HTML. Returns the relative output path."""
    job.title = _sanitize_job_title(job.title)
    cv_data = copy.deepcopy(load_cv_data(cv_data_path))
    profile = job.profile_match or next(iter(cv_data.get("profile_config_map", {})), "default")

    profile_config_map = cv_data.get("profile_config_map", {})
    config_file = profile_config_map.get(profile, next(iter(profile_config_map.values()), None))
    if not config_file:
        raise ValueError(
            "No CV variant configs found. Run /setup to define at least one "
            "CV variant (cv_data.yaml -> profile_config_map)."
        )
    variant = Path(config_file).stem.replace("config_", "")

    with open(CV_SYSTEM_DIR / config_file, encoding="utf-8") as f:
        variant_config = yaml.safe_load(f)

    cv_data.setdefault("summary", {})[variant] = generate_summary(job, profile, cv_data)

    keywords = extract_keywords(job.title, job.description, cv_data, max_kw=20)
    if keywords and variant in cv_data.get("skills", {}):
        skills = cv_data["skills"][variant]
        existing_all = " ".join(s.get("keywords", "") for s in skills).lower()
        new_kws = [kw for kw in keywords if kw.lower() not in existing_all][:7]

        category_signals = cv_data.get("skill_category_signals", {})

        def _best_category(kw: str) -> int:
            kw_l = kw.lower()
            for domain, signals in category_signals.items():
                if any(s.lower() in kw_l or kw_l in s.lower() for s in signals):
                    for i, skill in enumerate(skills):
                        if any(sig in skill.get("category", "") for sig in signals):
                            return i
            return 0

        for kw in new_kws:
            idx = _best_category(kw)
            existing = skills[idx].get("keywords", "")
            if kw.lower() not in existing.lower():
                skills[idx]["keywords"] = existing + ", " + kw if existing else kw

    personal = cv_data["personal"]
    ctx = {
        "name": personal["name"],
        "subtitle": variant_config.get("subtitle", personal.get("title", "")),
        "email": personal.get("email", ""),
        "phone": personal.get("phone", ""),
        "linkedin": personal.get("linkedin", ""),
        "nationality": personal.get("nationality", ""),
        "summary": cv_data["summary"][variant],
        "skills": cv_data["skills"][variant],
        "experience": cv_data["experience"][: variant_config.get("experience_limit", 7)],
        "projects": cv_data.get("projects", []),
        "education": cv_data.get("education", []),
        "languages": cv_data.get("languages", []),
        "references": cv_data.get("references", []) if variant_config.get("show_references") else [],
        "interests": cv_data.get("interests", []),
        "accent_color": variant_config.get("accent_color", "#2C3E50"),
        "show_photo": variant_config.get("show_photo", False),
        "photo_data": None,
        "project_style": variant_config.get("project_style", "outcome"),
        "section_order": variant_config.get(
            "section_order", ["summary", "experience", "projects", "education", "skills", "languages"]
        ),
    }
    if ctx["show_photo"] and personal.get("photo"):
        ctx["photo_data"] = _encode_photo(CV_SYSTEM_DIR / personal["photo"])

    env = Environment(loader=FileSystemLoader(str(CV_SYSTEM_DIR)))
    html_content = env.get_template("template.html").render(**ctx)

    job_id_hash = hashlib.md5(str(getattr(job, "id", job.title)).encode()).hexdigest()[:6]
    date_str = datetime.now().strftime("%Y%m%d")
    company_name = job.company if (job.company and job.company != job.title) else getattr(job, "source", "Unknown")
    job_slug = safe_filename(_sanitize_title_for_cl(job.title))[:20]
    company_slug = safe_filename(company_name)[:30]
    name_slug = safe_filename(_person_name(cv_data)).replace("_", "")
    output_filename = f"CV_{company_slug}_{job_slug}_{job_id_hash}_{date_str}_{name_slug}.html"
    output_path = OUTPUT_DIR / output_filename
    output_path.write_text(html_content, encoding="utf-8")

    print(f"  CV generated: {output_path}")
    return f"output/cv/{output_filename}"


# ─────────────────────────────────────────────
# COVER LETTER — experience scoring + composition
# ─────────────────────────────────────────────

def score_experiences(job, cv_data: dict) -> list:
    """Score every catalog entry against the job text. Returns [(key, score), ...] sorted desc."""
    text = f"{job.title} {getattr(job, 'description', '') or ''}".lower()
    catalog = cv_data.get("experience_catalog", {})
    scores = {}
    for key, exp in catalog.items():
        score = 0.0
        signals = exp.get("signals", {})
        for kw in signals.get("strong", []):
            if kw in text:
                score += 0.4
        for kw in signals.get("medium", []):
            if kw in text:
                score += 0.2
        for kw in signals.get("weak", []):
            if kw in text:
                score += 0.05
        scores[key] = min(score, 1.0)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)


def _make_hook(job, cv_data: dict) -> str:
    """Use the top-matched experience's own hook template if the job has a
    description; otherwise fall back to a generic, safe default."""
    catalog = cv_data.get("experience_catalog", {})
    if getattr(job, "description", ""):
        ranked = score_experiences(job, cv_data)
        if ranked and ranked[0][1] > 0:
            top_exp = catalog.get(ranked[0][0], {})
            hook_template = top_exp.get("hook")
            if hook_template:
                return f"<p>{hook_template.format(title=job.title, company=job.company)}</p>"

    fallback = cv_data.get(
        "generic_hook_template",
        "What draws me to the {title} role at {company} is the chance to apply my background directly, in a setting that matters to me.",
    )
    return f"<p>{fallback.format(title=job.title, company=job.company)}</p>"


def _make_body_evidence(job, cv_data: dict) -> str:
    """Pick a primary + (optional) secondary experience and compose two paragraphs.

    Ordering rule (generic, carried over from the validated original): if the
    top-scoring experience is tagged type: "background" and the secondary one
    is tagged type: "current", the background experience introduces the
    narrative and the current role follows as where that background gets
    applied today — not the other way around. Tag your experiences with
    `type: background` or `type: current` in cv_data.yaml to get this ordering;
    untagged experiences are just ordered by match score.
    """
    catalog = cv_data.get("experience_catalog", {})
    ranked = score_experiences(job, cv_data)
    if not ranked or ranked[0][1] == 0:
        # No signal match at all — use the two experiences marked as most
        # generally representative (or just the first two in the catalog).
        keys = list(catalog.keys())[:2]
        if not keys:
            return ""
        if len(keys) == 1:
            return f"<p>{catalog[keys[0]].get('primary', '')}</p>"
        return f"<p>{catalog[keys[0]].get('primary','')}</p>\n\n<p>{catalog[keys[1]].get('secondary', catalog[keys[1]].get('primary',''))}</p>"

    primary_key, _ = ranked[0]
    secondary_key = None
    SECONDARY_THRESHOLD = 0.15
    for key, score in ranked[1:]:
        if score >= SECONDARY_THRESHOLD:
            secondary_key = key
            break

    primary_exp = catalog[primary_key]
    if secondary_key is None:
        return f"<p>{primary_exp.get('primary', '')}</p>"

    secondary_exp = catalog[secondary_key]
    primary_type = primary_exp.get("type", "")
    secondary_type = secondary_exp.get("type", "")

    if primary_type == "background" and secondary_type == "current":
        return f"<p>{primary_exp.get('primary','')}</p>\n\n<p>{secondary_exp.get('secondary', secondary_exp.get('primary',''))}</p>"
    elif primary_type == "current" and secondary_type == "background":
        # Let the background experience lead instead, current role cross-positions —
        # matches the validated ordering preference (background intro -> current application).
        return f"<p>{secondary_exp.get('primary','')}</p>\n\n<p>{primary_exp.get('secondary', primary_exp.get('primary',''))}</p>"
    else:
        return f"<p>{primary_exp.get('primary','')}</p>\n\n<p>{secondary_exp.get('secondary', secondary_exp.get('primary',''))}</p>"


def _make_body_why_company(job, cv_data: dict, role_profiles: dict) -> str:
    """Company-specific reasoning. cv_data['company_type_reasons'] maps a list
    of company-name substrings to a reason template (e.g. academic institutions,
    Big 4 consulting, big pharma, hospitals — whatever types the person told
    /setup they have specific enthusiasm for). Falls back to matching the job
    description against the same role_profiles used for scoring, so the
    fallback reasoning stays in sync with however the person defined their
    fields of interest."""
    company = job.company
    company_lower = company.lower()
    desc_lower = (getattr(job, "description", "") or "").lower()

    for group in cv_data.get("company_type_reasons", []):
        if any(sub in company_lower for sub in group["matches"]):
            return f"<p>{group['reason'].format(company=company)}</p>"

    # Generic fallback: match against role_profiles' own "strong" keywords,
    # using each profile's optional `why_reason` text.
    for profile_name, profile_cfg in role_profiles.items():
        reason = profile_cfg.get("why_reason")
        if not reason:
            continue
        if any(kw in desc_lower for kw in profile_cfg.get("strong", [])):
            return f"<p>{reason.format(company=company)}</p>"

    default_reason = cv_data.get(
        "generic_why_company_template",
        "What drew me to {company} is the work itself and the domain it sits in. "
        "I am at a point where I want to commit to a specific direction, and this role fits it well.",
    )
    return f"<p>{default_reason.format(company=company)}</p>"


def _make_personal_passage(cv_data: dict) -> str:
    """Entirely optional. Set cv_data['personal_passage'] to include a closing
    personal note, or leave it unset / empty to skip this section."""
    passage = cv_data.get("personal_passage", "").strip()
    if not passage:
        return ""
    return f"<p>{passage}</p>"


COVER_LETTER_HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
  @page {{ size: A4; margin: 0; }}
  @media print {{
    body {{ padding: 18mm 20mm !important; margin: 0 !important; }}
    .edit-toolbar {{ display: none !important; }}
    [contenteditable]:focus {{ outline: none; }}
    [contenteditable]:hover {{ background: transparent !important; }}
  }}
  body {{
    font-family: 'Helvetica Neue', Arial, sans-serif;
    font-size: 10.5pt;
    line-height: 1.6;
    color: #333;
    max-width: 680px;
    margin: 40px auto;
    padding: 0 40px;
  }}
  .edit-toolbar {{ position: fixed; top: 12px; right: 16px; display: flex; gap: 8px; z-index: 999; }}
  .edit-toolbar button {{ padding: 7px 16px; border: none; border-radius: 5px; font-size: 13px; cursor: pointer; font-family: inherit; }}
  .btn-print {{ background: {accent_color}; color: #fff; }}
  .btn-reset {{ background: #eee; color: #555; font-size: 12px; }}
  .header {{ display: flex; justify-content: space-between; margin-bottom: 40px; }}
  .sender {{ font-size: 10pt; color: #555; }}
  .sender .name {{ font-weight: bold; font-size: 12pt; color: {accent_color}; }}
  .date-company {{ text-align: right; font-size: 10pt; color: #555; }}
  .subject {{ font-weight: bold; font-size: 11pt; margin: 30px 0 20px 0; color: {accent_color}; }}
  p {{ margin: 0 0 14px 0; }}
  .accent-line {{ height: 3px; background: {accent_color}; margin-bottom: 30px; }}
  [contenteditable]:hover {{ background: #f0f4f8; border-radius: 3px; outline: 1px dashed #aac; }}
  [contenteditable]:focus {{ background: #f8fbff; outline: 1px solid {accent_color}; border-radius: 3px; }}
</style>
</head>
<body>

<div class="edit-toolbar">
  <button class="btn-reset" onclick="location.reload()" title="Discard changes and reload original">&#8634; Reset</button>
  <button class="btn-print" onclick="window.print()">Print / Save PDF</button>
</div>

<div class="accent-line"></div>
<div class="header">
  <div class="sender">
    <div class="name">{name}</div>
    <div>{subtitle}</div>
    <div>{phone} &middot; {email}</div>
    <div>{linkedin}</div>
  </div>
  <div class="date-company" contenteditable="true">
    <div>{date}</div>
    <br>
    <div><strong>{company}</strong></div>
    <div>{location}</div>
  </div>
</div>

<div class="subject" contenteditable="true">Application: {title}</div>

<p contenteditable="true">Dear Hiring Team,</p>

<div contenteditable="true">
{hook}
</div>

<div contenteditable="true">
{body_evidence}
</div>

<div contenteditable="true">
{body_why_company}
</div>

<div contenteditable="true">
{personal_passage}
</div>

<p contenteditable="true">I would love the chance to meet and learn more about what the role looks like in practice. My CV is attached, and I look forward to hearing from you.</p>

<div class="signature-block">
<p contenteditable="true">Kind regards,<br><strong>{name}</strong></p>
</div>
</body>
</html>"""


# Sensible generic writing-quality defaults — extend via cv_data['banned_phrases'].
_DEFAULT_BANNED_PHRASES = [
    "motivated to contribute", "i am passionate about", "passionate about",
    "leverage my skills", "leverage my", "i would welcome the opportunity",
    "i would welcome the chance", "dynamic environment", "solution-oriented approach",
    "i am excited to", "i am thrilled", "i strongly believe", "dedicated professional",
    "proven track record", "with great interest", "deeply passionate", "synergy",
    "going forward", "at the end of the day",
]
_BANNED_CHARS = ["—", "–"]  # em/en dash as a clause separator


def _sanitize_cl_text(text: str, cv_data: dict) -> str:
    import logging
    log = logging.getLogger(__name__)
    text_l = text.lower()
    for phrase in cv_data.get("banned_phrases", _DEFAULT_BANNED_PHRASES):
        if phrase in text_l:
            log.warning(f"  CL contains banned phrase: '{phrase}' — consider rephrasing.")
    for char in _BANNED_CHARS:
        if char in text:
            log.warning("  CL contains an em/en dash used as a separator — replace with a comma or new sentence.")
    return text


def _sanitize_title_for_cl(title: str) -> str:
    title = title.replace("—", ",").replace("–", ",").replace("−", ",")
    title = re.sub(r",\s*,", ",", title)
    title = re.sub(r"\s+", " ", title).strip().strip(",")
    return title


def _sanitize_job_title(raw: str) -> str:
    """Strip metadata garbage ('3 days ago', 'Place of work: ...') from a scraped title."""
    t = raw.strip()
    for stop in ("Place of work", "Arbeitsort", "Workload", "Pensum",
                 "Contract type", "Anstellungsart", "Easy apply",
                 "Is this job relevant", "Jetzt bewerben"):
        idx = t.lower().find(stop.lower())
        if idx > 0:
            t = t[:idx].strip()
    t = re.sub(
        r'^(\d+\s+(tag[e]?|day[s]?|week[s]?|month[s]?|stunde[n]?|hour[s]?)\s*(ago|her|zuvor)?'
        r'|(last|letzt[eern]*)\s*(week|woche|month|monat)s?'
        r'|gestern|yesterday|heute|today)\s*',
        '', t, flags=re.I
    ).strip()
    return t if len(t) < 100 else raw[:80]


def generate_cover_letter(job, cv_data_path: str = None, config_path: str = None) -> str:
    """Generate a cover letter as HTML. Returns the relative output path."""
    cv_data = load_cv_data(cv_data_path)
    role_profiles = load_role_profiles(config_path)
    clean_title = _sanitize_title_for_cl(_sanitize_job_title(job.title))

    company_display = job.company
    if not company_display or company_display == job.title:
        company_display = getattr(job, "source", "Unknown").replace(".", " ").title()

    personal = cv_data["personal"]
    accent_color = cv_data.get("cl_accent_color", "#2C3E50")

    hook = _make_hook(job, cv_data)
    body_evidence = _make_body_evidence(job, cv_data)
    body_company = _make_body_why_company(job, cv_data, role_profiles)
    personal_passage = _make_personal_passage(cv_data)

    html_content = COVER_LETTER_HTML.format(
        name=personal["name"],
        subtitle=personal.get("title", ""),
        phone=personal.get("phone", ""),
        email=personal.get("email", ""),
        linkedin=personal.get("linkedin", ""),
        accent_color=accent_color,
        date=datetime.now().strftime("%d. %B %Y"),
        company=company_display,
        location=job.location,
        title=clean_title,
        hook=hook,
        body_evidence=body_evidence,
        body_why_company=body_company,
        personal_passage=personal_passage,
    )
    _sanitize_cl_text(html_content, cv_data)

    job_id_hash = hashlib.md5(str(getattr(job, "id", job.title)).encode()).hexdigest()[:6]
    date_str = datetime.now().strftime("%Y%m%d")
    job_slug = safe_filename(clean_title)[:20] if clean_title else ""
    company_slug = safe_filename(company_display)[:30] if company_display else "Unknown"
    name_slug = safe_filename(_person_name(cv_data)).replace("_", "")
    output_filename = f"CL_{company_slug}_{job_slug}_{job_id_hash}_{date_str}_{name_slug}.html"
    output_path = OUTPUT_DIR / output_filename
    output_path.write_text(html_content, encoding="utf-8")

    print(f"  Cover letter generated: {output_path}")
    return f"output/cv/{output_filename}"

"""
Generic Job Scorer Engine — config-driven, field-agnostic.

This is a genericized version of a job-scoring engine originally built for one
person's specific field (health/MedTech). ALL domain-specific rules (which
keywords mean "in my field", which titles/skills disqualify a job, which
locations are preferred, seniority preferences, industry keywords, preferred
company types) live in config.yaml under the `scoring:` key — nothing about a
specific field, city, or seniority level is hardcoded here.

If you're reading this file to understand what the ENGINE does (as opposed to
what YOUR config says): it computes four sub-scores (location, role_fit,
seniority, industry), combines them with configurable weights, and applies a
disqualification pass that hard-caps jobs matching your disqualify rules. That
algorithm is generic. Everything it's told to look for comes from config.

See templates/config.example.yaml for a fully worked example, and run /setup
to generate your own config.yaml through a guided interview instead of editing
this by hand.
"""

import re
import yaml
from pathlib import Path
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional


@dataclass
class ScoreResult:
    total: float
    location: float
    role_fit: float
    seniority: float
    industry: float
    profile_match: str
    match_reason: str


# ─────────────────────────────────────────────
# CONFIG LOADING
# ─────────────────────────────────────────────

DEFAULT_CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"

# Fallback defaults used only if a key is missing from the user's config —
# these are intentionally neutral/permissive, NOT tuned to any specific field.
_DEFAULTS = {
    "domain_context_keywords": [],
    "disqualify": {
        "title_hard": [],
        "title_out_of_scope": [],
        "text_hard": [],
        "text_soft": [],
    },
    "overexperience": {
        "hard_years": None,   # e.g. 5 -> disqualify jobs demanding 5+ years
        "soft_years": None,   # e.g. 3 -> soft-penalize jobs demanding 3-4 years
    },
    "location_tiers": {},
    "location_default_score": 0.55,
    "location_default_label": "Unknown",
    "role_profiles": {},
    "seniority_tiers": {},
    "seniority_default_score": 0.65,
    "seniority_default_label": "unknown",
    "industry_keywords": [],
    "industry_default_score": 0.4,
    "industry_default_label": "other",
    "target_companies": [],
    "academic_companies": [],
    "academic_company_score_cap": 0.75,
    "company_preferences": {
        "prefer": [],
        "prefer_bonus": 0.0,
        "avoid": [],
        "avoid_penalty": 0.0,
    },
    "weights": {"location": 0.30, "role_fit": 0.35, "seniority": 0.20, "industry": 0.15},
    "min_score": 40,
    "disqualify_cap": 25.0,
    "senior_title_patterns": [],
    "senior_cap": 45.0,
}


def _deep_merge_defaults(user_cfg: dict, defaults: dict) -> dict:
    out = dict(defaults)
    for k, v in (user_cfg or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge_defaults(v, out[k])
        else:
            out[k] = v
    return out


@lru_cache(maxsize=4)
def load_scoring_config(config_path: str = None) -> dict:
    """Load the `scoring:` section of config.yaml, merged over neutral defaults.

    Cached per path — call load_scoring_config.cache_clear() if you edit
    config.yaml and want changes picked up without restarting the process.
    """
    path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    try:
        with open(path, encoding="utf-8") as f:
            full_cfg = yaml.safe_load(f) or {}
    except FileNotFoundError:
        full_cfg = {}
    return _deep_merge_defaults(full_cfg.get("scoring", {}), _DEFAULTS)


def _compile_all(patterns: list[str]) -> list[re.Pattern]:
    return [re.compile(p, re.IGNORECASE) for p in patterns]


def _build_experience_regex(min_years: Optional[int]) -> Optional[re.Pattern]:
    """Build a regex catching '<min_years>+ years', 'minimum N years', etc.
    for N >= min_years. Returns None if min_years is not configured."""
    if not min_years:
        return None
    n = min_years
    return re.compile(
        rf"\b([{n}-9]|\d{{2}})\+\s*years?\b"
        rf"|minimum\s+([{n}-9]|\d{{2}})\s+years?\b"
        rf"|at\s+least\s+([{n}-9]|\d{{2}})\s+years?\b"
        rf"|([{n}-9]|\d{{2}})\s+years?\s+of\s+(experience|exp|work|consulting)\b"
        rf"|([{n}-9]|\d{{2}})\s*[\-–]\s*\d+\s*years?\s*(of\s*)?(experience|exp)\b"
    )


# ─────────────────────────────────────────────
# DOMAIN CONTEXT
# ─────────────────────────────────────────────

def has_domain_context(text: str, cfg: dict) -> bool:
    """True if the text contains at least one of your domain_context_keywords
    (config-defined signals that a posting is genuinely 'in your field')."""
    return any(kw in text for kw in cfg["domain_context_keywords"])


def _domain_context_count(text: str, cfg: dict) -> int:
    return sum(1 for kw in cfg["domain_context_keywords"] if kw in text)


# ─────────────────────────────────────────────
# DISQUALIFICATION
# ─────────────────────────────────────────────

def is_disqualified(title: str, description: str, cfg: dict) -> tuple[bool, str]:
    """
    Returns (disqualified, reason).
    - disqualify.title_hard / title_out_of_scope: checked against TITLE only, no override.
    - disqualify.text_hard: checked against full text, no override (fundamentally wrong skillset).
    - overexperience.hard_years: hard disqualify if posting demands more years than you have + margin.
    - disqualify.text_soft: checked against full text, but overridden if enough domain_context_keywords match.
    """
    title_lower = title.lower()
    text = f"{title} {description}".lower()

    for pattern in _compile_all(cfg["disqualify"]["title_hard"]):
        if pattern.search(title_lower):
            return True, "Title disqualified (hard rule)"
    for pattern in _compile_all(cfg["disqualify"]["title_out_of_scope"]):
        if pattern.search(title_lower):
            return True, "Out of scope (title)"
    for pattern in _compile_all(cfg["disqualify"]["text_hard"]):
        if pattern.search(text):
            return True, "Skill/domain mismatch"

    hard_exp_re = _build_experience_regex(cfg["overexperience"]["hard_years"])
    if hard_exp_re and hard_exp_re.search(text):
        return True, f"Requires {cfg['overexperience']['hard_years']}+ years experience"

    for pattern in _compile_all(cfg["disqualify"]["text_soft"]):
        if pattern.search(text):
            # Soft disqualifiers can be rescued by strong domain context —
            # e.g. a "data engineer" posting inside a hospital's digital-health team.
            if _domain_context_count(text, cfg) < 2:
                return True, "Wrong domain"

    return False, ""


# ─────────────────────────────────────────────
# LOCATION SCORING
# ─────────────────────────────────────────────

def score_location(location: str, cfg: dict) -> tuple[float, str]:
    loc_lower = location.lower()
    for tier in cfg["location_tiers"].values():
        for kw in tier.get("keywords", []):
            if kw in loc_lower:
                return tier["score"], tier.get("label", kw)
    return cfg["location_default_score"], cfg["location_default_label"]


# ─────────────────────────────────────────────
# ROLE FIT SCORING
# ─────────────────────────────────────────────

def score_role_fit(title: str, description: str, company: str, cfg: dict) -> tuple[float, str, str]:
    """Returns (score 0-1, best_profile_name, reason). Profiles, their keyword
    tiers, weights, and optional domain gates all come from cfg['role_profiles'].

    Each profile in config may define a `domain_gate` with:
      min_context: int          # domain_context_keyword hits required for full credit
      zero_context_score: float # score if 0 hits
      partial_context_score_multiplier: float  # multiplier if 1 hit (below min_context)
    and/or a `penalty_terms` list of {terms: [...], multiplier: float} applied
    in order (first match wins) when the profile's raw score exceeds a threshold —
    this replicates things like "heavy penalty if this is really IT consulting,
    not health consulting" from the original Max-specific scorer, generalized.
    """
    text = f"{title} {description} {company}".lower()

    best_profile, best_score, best_reason = "none", 0.0, ""

    for profile_name, profile_cfg in cfg["role_profiles"].items():
        profile_score = 0.0
        matches = []

        for kw in profile_cfg.get("strong", []):
            if kw in text:
                profile_score += 0.25
                matches.append(kw)
        for kw in profile_cfg.get("medium", []):
            if kw in text:
                profile_score += 0.12
                matches.append(kw)
        for kw in profile_cfg.get("weak", []):
            if kw in text:
                profile_score += 0.05

        profile_score = min(profile_score, 1.0) * profile_cfg.get("weight", 1.0)

        gate = profile_cfg.get("domain_gate")
        if gate and profile_score > gate.get("activate_above", 0.15):
            hits = _domain_context_count(text, cfg)
            min_context = gate.get("min_context", 1)
            if hits == 0:
                profile_score = gate.get("zero_context_score", profile_score * 0.3)
            elif hits < min_context:
                profile_score *= gate.get("partial_context_score_multiplier", 0.5)

        for rule in profile_cfg.get("penalty_terms", []):
            if profile_score > rule.get("activate_above", 0.20) and any(t in text for t in rule["terms"]):
                profile_score *= rule["multiplier"]
                break

        if profile_score > best_score:
            best_score = profile_score
            best_profile = profile_name
            best_reason = ", ".join(matches[:4]) if matches else "general match"

    return min(best_score, 1.0), best_profile, best_reason


# ─────────────────────────────────────────────
# SENIORITY SCORING
# ─────────────────────────────────────────────

def score_seniority(title: str, description: str, cfg: dict) -> tuple[float, str]:
    text = f"{title} {description}".lower()

    hard_exp_re = _build_experience_regex(cfg["overexperience"]["hard_years"])
    if hard_exp_re and hard_exp_re.search(text):
        return 0.10, "overqualified_exp"

    soft_exp_re = _build_experience_regex(cfg["overexperience"]["soft_years"])
    if soft_exp_re and soft_exp_re.search(text):
        return 0.30, "experienced_req"

    for tier_name, tier_cfg in cfg["seniority_tiers"].items():
        for pattern in _compile_all(tier_cfg.get("patterns", [])):
            if pattern.search(text):
                return tier_cfg["score"], tier_name

    return cfg["seniority_default_score"], cfg["seniority_default_label"]


# ─────────────────────────────────────────────
# INDUSTRY SCORING
# ─────────────────────────────────────────────

def score_industry(company: str, description: str, title: str, cfg: dict) -> tuple[float, str]:
    text = f"{company} {description} {title}".lower()
    company_lower = company.lower()

    for ac in cfg["academic_companies"]:
        if ac in company_lower:
            best_score, best_label = 0.0, "general"
            for kw, score in cfg["industry_keywords"]:
                if kw in text and score > best_score:
                    best_score, best_label = score, kw
            floor = cfg["academic_company_score_cap"] * 0.85
            return min(max(best_score, floor), cfg["academic_company_score_cap"]), f"Academic: {company}"

    for tc in cfg["target_companies"]:
        if tc in company_lower:
            return 0.95, f"Target company: {company}"

    best_score, best_label = 0.0, "general"
    for kw, score in cfg["industry_keywords"]:
        if kw in text and score > best_score:
            best_score, best_label = score, kw

    if best_score == 0:
        return cfg["industry_default_score"], cfg["industry_default_label"]
    return best_score, best_label


# ─────────────────────────────────────────────
# MAIN SCORING FUNCTION
# ─────────────────────────────────────────────

_TITLE_GARBAGE_RE = re.compile(
    r'(\d+\s+)?(days?\s+ago|weeks?\s+ago|months?\s+ago|stunden?\s+her|tage[n]?\s+her|'
    r'place\s+of\s+work|arbeitsort:|workload:|pensum:|contract\s+type:|anstellungsart:|'
    r'easy\s+apply|is\s+this\s+job|jetzt\s+bewerben)',
    re.I,
)


def score_job(job, config_path: str = None) -> ScoreResult:
    """Score a single job. `job` needs .title, .description, .company, .location,
    and optionally .profile_match (set by whichever search query found it)."""
    cfg = load_scoring_config(config_path)

    disq, disq_reason = is_disqualified(job.title, job.description, cfg)
    loc_score, loc_label = score_location(job.location, cfg)
    role_score, profile, reason = score_role_fit(job.title, job.description, job.company, cfg)
    sen_score, sen_label = score_seniority(job.title, job.description, cfg)
    ind_score, ind_label = score_industry(job.company, job.description, job.title, cfg)

    weights = cfg["weights"]
    total = (
        loc_score * weights["location"]
        + role_score * weights["role_fit"]
        + sen_score * weights["seniority"]
        + ind_score * weights["industry"]
    ) * 100

    if getattr(job, "profile_match", None) and job.profile_match == profile:
        total = min(100.0, total + 5.0)

    senior_title_re = re.compile("|".join(cfg["senior_title_patterns"]), re.I) if cfg["senior_title_patterns"] else None

    if disq:
        total = min(total, cfg["disqualify_cap"])
        profile = f"[FILTERED: {disq_reason}]"
    elif senior_title_re and senior_title_re.search(job.title):
        total = min(total, cfg["senior_cap"])
        profile = f"[SENIOR: {profile}]"

    if not disq and not (senior_title_re and senior_title_re.search(job.title)):
        company_lower = job.company.lower()
        prefs = cfg["company_preferences"]
        if any(c in company_lower for c in prefs.get("avoid", [])):
            total = max(0.0, total - prefs.get("avoid_penalty", 0.0))
        elif any(c in company_lower for c in prefs.get("prefer", [])):
            total = min(100.0, total + prefs.get("prefer_bonus", 0.0))

    return ScoreResult(
        total=round(total, 1),
        location=round(loc_score * 100, 1),
        role_fit=round(role_score * 100, 1),
        seniority=round(sen_score * 100, 1),
        industry=round(ind_score * 100, 1),
        profile_match=profile,
        match_reason=reason,
    )


def score_and_rank(jobs: list, top_n: int = 50, config_path: str = None, min_role_fit: float = 0.0) -> list:
    """Score all jobs, drop anything below your configured min_score, return sorted list."""
    cfg = load_scoring_config(config_path)
    results = []
    for job in jobs:
        title = job.title if hasattr(job, "title") else job.get("title", "")
        if _TITLE_GARBAGE_RE.search(title):
            continue
        result = score_job(job, config_path)
        job.score = result.total
        job.score_breakdown = {
            "location": result.location,
            "role_fit": result.role_fit,
            "seniority": result.seniority,
            "industry": result.industry,
            "profile": result.profile_match,
        }
        job.profile_match = result.profile_match
        job.match_reason = result.match_reason
        if job.score >= cfg["min_score"]:
            results.append(job)

    results.sort(key=lambda j: j.score, reverse=True)
    if min_role_fit:
        results = [j for j in results if j.score_breakdown.get("role_fit", 0) >= min_role_fit]
    return results[: top_n if top_n else 30]

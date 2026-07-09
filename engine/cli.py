"""
Generic Job Agent CLI — thin wrapper around engine/scorer.py and
engine/cv_generator.py so the /scrape and /apply commands (and you, by hand)
can score and generate without writing Python each time.

Usage:
  python3 engine/cli.py score    [--input data/job_leads_raw.json] [--output data/job_leads.json]
  python3 engine/cli.py generate [--input data/job_leads.json] [--top 15] [--only-new]
  python3 engine/cli.py report   [--input data/job_leads.json] [--output output/job_report.html]

Job schema (JSON list of objects) needs at least: id, title, company, location,
description, url, source. After `score`: + score, score_breakdown,
profile_match, match_reason. After `generate`: + cv_path, cl_path.
Set `applied: true` or `rejected: true` on a job by hand (or have Claude do it
when you say "I applied to X" / "skip Y") to keep it out of future `generate`
runs — `score` preserves these flags across re-scrapes by matching on `id`.
"""
import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent))
import scorer
import cv_generator

AGENT_DIR = Path(__file__).parent.parent
CONFIG_PATH = AGENT_DIR / "config.yaml"
CV_DATA_PATH = AGENT_DIR / "cv_system" / "cv_data.yaml"
DEFAULT_RAW = AGENT_DIR / "data" / "job_leads_raw.json"
DEFAULT_SCORED = AGENT_DIR / "data" / "job_leads.json"
DEFAULT_REPORT = AGENT_DIR / "output" / "job_report.html"


def _load_jobs(path: Path) -> list:
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    return [SimpleNamespace(**j) for j in raw]


def _dump_jobs(jobs: list, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump([vars(j) for j in jobs], f, indent=2, ensure_ascii=False, default=str)


def cmd_score(args):
    jobs = _load_jobs(Path(args.input))
    if not jobs:
        print(f"No jobs found in {args.input}. Nothing to score.")
        return

    # Preserve applied/rejected/cv_path/cl_path flags across re-scrapes by
    # matching on id, so re-running /scrape never re-surfaces a job you
    # already dealt with.
    out_path = Path(args.output)
    existing = {j.id: j for j in _load_jobs(out_path)} if out_path.exists() else {}
    for j in jobs:
        old = existing.get(getattr(j, "id", None))
        if old:
            for field in ("applied", "rejected", "cv_path", "cl_path"):
                if hasattr(old, field):
                    setattr(j, field, getattr(old, field))

    ranked = scorer.score_and_rank(jobs, top_n=len(jobs), config_path=str(CONFIG_PATH))
    _dump_jobs(ranked, out_path)
    print(f"Scored {len(jobs)} jobs — {len(ranked)} passed your min_score threshold.")
    for j in ranked[:15]:
        print(f"  {j.score:5.1f}  {j.profile_match:30}  {j.title} @ {j.company}")


def cmd_generate(args):
    in_path = Path(args.input)
    jobs = _load_jobs(in_path)
    candidates = [j for j in jobs if not getattr(j, "applied", False) and not getattr(j, "rejected", False)]
    candidates.sort(key=lambda j: getattr(j, "score", 0), reverse=True)
    targets = candidates[: args.top]

    generated = 0
    for j in targets:
        if args.only_new and getattr(j, "cv_path", None):
            continue
        j.cv_path = cv_generator.generate_cv_for_job(j, cv_data_path=str(CV_DATA_PATH), config_path=str(CONFIG_PATH))
        j.cl_path = cv_generator.generate_cover_letter(j, cv_data_path=str(CV_DATA_PATH), config_path=str(CONFIG_PATH))
        generated += 1

    _dump_jobs(jobs, in_path)
    print(f"Generated CV + cover letter for {generated} jobs. Updated {in_path}.")


def cmd_report(args):
    jobs = _load_jobs(Path(args.input))
    jobs.sort(key=lambda j: getattr(j, "score", 0), reverse=True)

    rows = []
    for j in jobs:
        cv_link = f'<a href="{j.cv_path}">CV</a>' if getattr(j, "cv_path", None) else "-"
        cl_link = f'<a href="{j.cl_path}">CL</a>' if getattr(j, "cl_path", None) else "-"
        status = "applied" if getattr(j, "applied", False) else ("rejected" if getattr(j, "rejected", False) else "")
        rows.append(
            f"<tr><td>{j.score:.1f}</td><td>{j.title}</td><td>{j.company}</td>"
            f"<td>{j.location}</td><td>{j.profile_match}</td><td>{cv_link}</td><td>{cl_link}</td>"
            f'<td><a href="{getattr(j, "url", "")}">link</a></td><td>{status}</td></tr>'
        )

    html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
<style>body{{font-family:Arial,sans-serif;margin:30px}}table{{border-collapse:collapse;width:100%}}
td,th{{border:1px solid #ddd;padding:6px 10px;font-size:13px}}th{{background:#2C3E50;color:#fff}}
tr:nth-child(even){{background:#f7f7f7}}</style>
</head><body><h2>Job Report ({len(jobs)} jobs)</h2><table>
<tr><th>Score</th><th>Title</th><th>Company</th><th>Location</th><th>Profile</th><th>CV</th><th>CL</th><th>Posting</th><th>Status</th></tr>
{''.join(rows)}
</table></body></html>"""

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"Report written to {out}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)

    sc = sub.add_parser("score", help="Score raw scraped jobs and merge into data/job_leads.json")
    sc.add_argument("--input", default=str(DEFAULT_RAW))
    sc.add_argument("--output", default=str(DEFAULT_SCORED))
    sc.set_defaults(func=cmd_score)

    gn = sub.add_parser("generate", help="Generate CV + cover letter for top-ranked jobs")
    gn.add_argument("--input", default=str(DEFAULT_SCORED))
    gn.add_argument("--top", type=int, default=15)
    gn.add_argument("--only-new", action="store_true", help="Skip jobs that already have a cv_path")
    gn.set_defaults(func=cmd_generate)

    rp = sub.add_parser("report", help="Build an HTML report from data/job_leads.json")
    rp.add_argument("--input", default=str(DEFAULT_SCORED))
    rp.add_argument("--output", default=str(DEFAULT_REPORT))
    rp.set_defaults(func=cmd_report)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

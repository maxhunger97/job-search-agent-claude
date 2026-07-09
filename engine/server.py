#!/usr/bin/env python3
"""
Generic Job Agent — local review server.

Run: python3 engine/server.py
Open: http://localhost:5555

This is an interactive alternative front-end for the exact same data
`/scrape` and `/apply` produce (`data/job_leads.json`, `output/cv/*.html`) —
not a separate system. Everything you do here (mark applied, dismiss,
regenerate) writes straight back to those files, so `/scrape` and `/apply`
see the same state next time you run them.

Endpoints:
  GET  /                       — interactive job dashboard
  GET  /archive                — applications archive (jobs marked Applied)
  POST /api/reject/<id>        — dismiss a job (hidden on next load)
  POST /api/undo-reject/<id>   — undo a dismissal
  POST /api/apply/<id>         — mark Applied (adds a record to the archive)
  POST /api/description/<id>   — save a manually pasted job description
  POST /api/generate/<id>      — (re)generate CV + cover letter on demand
  GET  /cv/<filename>          — serve a generated CV/CL file

Why a local archive instead of a Notion/Sheets sync: the original personal
version of this agent synced applications to the person's own Notion
database, which only makes sense once you already use Notion for this and
have a database + API token set up. This generic version defaults to a
plain local file (`data/applications_archive.json`) that works for everyone
with zero setup. If you use Notion, Airtable, or a spreadsheet, just ask
Claude to add a sync step here — the archive record already has every field
a sync target would need (title, company, score, applied_date, notes, links).
"""

import json
import logging
import sys
from datetime import datetime
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_file

sys.path.insert(0, str(Path(__file__).parent))
import cv_generator
import yaml

AGENT_DIR = Path(__file__).parent.parent
DATA_DIR = AGENT_DIR / "data"
LEADS_PATH = DATA_DIR / "job_leads.json"
ARCHIVE_PATH = DATA_DIR / "applications_archive.json"
WARNINGS_PATH = DATA_DIR / "scrape_warnings.json"
CV_DIR = AGENT_DIR / "output" / "cv"
CONFIG_PATH = AGENT_DIR / "config.yaml"
CV_DATA_PATH = AGENT_DIR / "cv_system" / "cv_data.yaml"

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")

app = Flask(__name__)


# ── Data helpers ──────────────────────────────────────────────────────────

def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_jobs() -> list:
    return load_json(LEADS_PATH, [])


def save_jobs(jobs: list):
    save_json(LEADS_PATH, jobs)


def load_archive() -> list:
    return load_json(ARCHIVE_PATH, [])


def person_name() -> str:
    try:
        cv_data = yaml.safe_load(CV_DATA_PATH.read_text(encoding="utf-8")) or {}
        return cv_data.get("personal", {}).get("name", "you")
    except Exception:
        return "you"


def min_score_default() -> int:
    try:
        cfg = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
        return int(cfg.get("scoring", {}).get("min_score", 40))
    except Exception:
        return 40


class _Job:
    """Lightweight stand-in so cv_generator (which expects attributes, not
    dict keys) can be handed a plain dict loaded from job_leads.json."""
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


# ── HTML dashboard ────────────────────────────────────────────────────────

def render_dashboard(jobs: list, applied_ids: set, warnings: list) -> str:
    name = person_name()
    run_date = datetime.now().strftime("%d %B %Y, %H:%M")
    default_min_score = min_score_default()

    # Distinct clean profile names present in the data, for the filter chips —
    # never hardcoded, since this template doesn't know what fields exist.
    profiles = sorted({j.get("profile_match", "") for j in jobs if j.get("profile_match")})

    warnings_html = ""
    if warnings:
        items = "".join(f"<div class='run-summary-warning'>&#9888; {w}</div>" for w in warnings)
        warnings_html = f'<div class="run-summary"><div class="run-summary-inner">{items}</div></div>'

    jobs_json = json.dumps(jobs, ensure_ascii=False)
    applied_json = json.dumps(list(applied_ids), ensure_ascii=False)
    profiles_json = json.dumps(profiles, ensure_ascii=False)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Job Leads — {name}</title>
<style>
:root {{
  --bg:#f8f9fa; --card:#fff; --accent:#2C3E50; --accent2:#3498db; --text:#333;
  --muted:#888; --border:#e8e8e8; --green:#27ae60; --orange:#e67e22; --red:#e74c3c;
}}
* {{ box-sizing:border-box; margin:0; padding:0; }}
body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; background:var(--bg); color:var(--text); min-height:100vh; }}
header {{ background:var(--accent); color:#fff; padding:20px 32px; display:flex; justify-content:space-between; align-items:center; position:sticky; top:0; z-index:100; box-shadow:0 2px 8px rgba(0,0,0,.15); }}
header h1 {{ font-size:18px; font-weight:600; }}
header .meta {{ font-size:12px; opacity:.75; margin-top:3px; }}
header .stats {{ display:flex; align-items:center; gap:20px; }}
header .stats .count {{ font-size:28px; font-weight:700; text-align:center; }}
header .stats .label {{ font-size:11px; opacity:.7; text-align:center; }}
header a.archive-link {{ color:#fff; font-size:13px; opacity:.85; text-decoration:none; border:1px solid rgba(255,255,255,.4); padding:5px 12px; border-radius:6px; }}
.run-summary {{ background:#fff3cd; border-bottom:1px solid #ffc107; padding:10px 32px; font-size:13px; }}
.run-summary-inner {{ display:flex; flex-direction:column; gap:4px; }}
.run-summary-warning {{ color:#856404; }}
.run-summary-warning a {{ color:#856404; font-weight:600; }}
.controls {{ padding:16px 32px; background:#fff; border-bottom:1px solid var(--border); display:flex; gap:10px; flex-wrap:wrap; align-items:center; }}
.controls input[type=text] {{ padding:7px 12px; border:1px solid var(--border); border-radius:6px; font-size:13px; width:220px; }}
.filter-btn {{ padding:6px 14px; border:1px solid var(--border); border-radius:20px; background:#fff; font-size:12px; cursor:pointer; }}
.filter-btn:hover, .filter-btn.active {{ background:var(--accent); color:#fff; border-color:var(--accent); }}
.sort-select {{ padding:6px 10px; border:1px solid var(--border); border-radius:6px; font-size:12px; background:#fff; cursor:pointer; margin-left:auto; }}
.score-slider-wrap {{ display:flex; align-items:center; gap:6px; font-size:13px; }}
.jobs-grid {{ padding:24px 32px; display:grid; grid-template-columns:repeat(auto-fill,minmax(380px,1fr)); gap:16px; }}
.job-card {{ background:var(--card); border:1px solid var(--border); border-radius:10px; overflow:hidden; position:relative; transition:box-shadow .2s, transform .1s; }}
.job-card:hover {{ box-shadow:0 4px 16px rgba(0,0,0,.1); transform:translateY(-2px); }}
.job-card.applied-card {{ border-left:3px solid var(--green); }}
.job-card-inner {{ padding:18px; }}
.card-top {{ display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:10px; }}
.company-title h3 {{ font-size:14px; font-weight:600; line-height:1.3; }}
.company-title .company {{ font-size:12px; color:var(--muted); margin-top:3px; }}
.score-badge {{ min-width:48px; height:48px; border-radius:50%; display:flex; align-items:center; justify-content:center; font-weight:700; font-size:14px; color:#fff; flex-shrink:0; margin-left:10px; }}
.score-high {{ background:var(--green); }} .score-mid {{ background:var(--orange); }} .score-low {{ background:var(--red); }}
.card-tags {{ display:flex; gap:6px; flex-wrap:wrap; margin:8px 0; }}
.tag {{ padding:2px 9px; border-radius:20px; font-size:10px; font-weight:500; }}
.tag-location {{ background:#f0f4ff; color:#3456d1; }}
.tag-profile {{ background:#6c5ce7; color:#fff; }}
.tag-source {{ background:#f5f5f5; color:#666; }}
.match-reason {{ font-size:11px; color:var(--muted); margin:6px 0 10px; font-style:italic; }}
.score-bar-row {{ display:flex; align-items:center; gap:8px; margin-bottom:5px; }}
.score-bar-label {{ font-size:10px; color:var(--muted); width:60px; flex-shrink:0; }}
.score-bar-track {{ flex:1; height:5px; background:var(--border); border-radius:3px; overflow:hidden; }}
.score-bar-fill {{ height:100%; border-radius:3px; background:var(--accent2); }}
.score-bar-val {{ font-size:10px; color:var(--muted); width:24px; text-align:right; flex-shrink:0; }}
.card-actions {{ display:flex; flex-wrap:wrap; gap:8px; padding:12px 18px; background:#fafafa; border-top:1px solid var(--border); }}
.btn {{ padding:7px 14px; border-radius:6px; font-size:12px; font-weight:500; cursor:pointer; border:none; text-decoration:none; display:inline-flex; align-items:center; gap:5px; }}
.btn:hover {{ opacity:.85; }}
.btn-view {{ background:var(--accent); color:#fff; }}
.btn-view.disabled {{ opacity:.4; cursor:not-allowed; }}
.btn-cv, .btn-cl {{ background:#e8f4fd; color:var(--accent2); }}
.btn-seen {{ background:#f0f0f0; color:#888; margin-left:auto; }}
.btn-mark-applied {{ background:#eafaf1; color:var(--green); border:1px solid var(--green); }}
.btn-mark-applied.applied, .btn-mark-applied:disabled {{ background:var(--green); color:#fff; opacity:1; cursor:default; }}
.btn-dismiss {{ position:absolute; top:10px; right:10px; background:transparent; color:#ccc; border:none; border-radius:50%; width:24px; height:24px; font-size:14px; cursor:pointer; z-index:2; }}
.btn-dismiss:hover {{ background:#fde8e8; color:var(--red); }}
.applied-badge {{ display:inline-block; background:var(--green); color:#fff; font-size:11px; font-weight:600; padding:2px 8px; border-radius:10px; margin-left:8px; vertical-align:middle; }}
.empty-state {{ text-align:center; padding:60px; color:var(--muted); grid-column:1/-1; }}
footer {{ text-align:center; padding:24px; font-size:11px; color:var(--muted); border-top:1px solid var(--border); margin-top:20px; }}
.modal-overlay {{ display:none; position:fixed; inset:0; background:rgba(0,0,0,.45); z-index:1000; align-items:center; justify-content:center; }}
.modal-overlay.open {{ display:flex; }}
.modal-box {{ background:#fff; border-radius:12px; padding:24px; width:min(640px,92vw); max-height:88vh; overflow-y:auto; }}
.modal-box textarea {{ width:100%; height:180px; padding:10px; border:1px solid var(--border); border-radius:6px; font-family:inherit; font-size:12px; }}
.modal-actions {{ display:flex; gap:10px; justify-content:flex-end; margin-top:14px; }}
.modal-btn-cancel {{ padding:8px 18px; border:1px solid var(--border); border-radius:6px; background:#fff; cursor:pointer; }}
.modal-btn-generate {{ padding:8px 22px; border:none; border-radius:6px; background:var(--accent); color:#fff; cursor:pointer; font-weight:600; }}
</style>
</head>
<body>

<header>
  <div>
    <h1>Job Leads — {name}</h1>
    <div class="meta">Last updated: {run_date}</div>
  </div>
  <div class="stats">
    <a class="archive-link" href="/archive">Applications Archive &rarr;</a>
    <div><div class="count" id="visibleCount">—</div><div class="label">jobs shown</div></div>
  </div>
</header>

{warnings_html}

<div class="controls">
  <input type="text" id="searchInput" placeholder="Search title, company, location..." oninput="filterJobs()">
  <button class="filter-btn active" data-filter="all" onclick="setFilter('all', this)">All</button>
  <span id="profileChips"></span>
  <div class="score-slider-wrap">
    <span>Min score:</span>
    <input type="range" id="scoreSlider" min="0" max="100" value="{default_min_score}" step="1"
      oninput="document.getElementById('scoreSliderVal').textContent=this.value; filterJobs()">
    <strong id="scoreSliderVal">{default_min_score}</strong>
  </div>
  <select class="sort-select" id="sortSelect" onchange="sortJobs()">
    <option value="score">Sort: Score</option>
    <option value="company">Sort: Company</option>
  </select>
</div>

<div class="jobs-grid" id="jobsGrid"></div>

<footer>Generic Job Search Agent &middot; {name} &middot; {run_date}</footer>

<div class="modal-overlay" id="genModal" onclick="if(event.target===this)closeGenModal()">
  <div class="modal-box">
    <h3 id="genModalTitle" style="margin-bottom:4px">Generate CV + Cover Letter</h3>
    <p id="genModalSubtitle" style="color:var(--muted);font-size:12px;margin-bottom:12px"></p>
    <p style="font-size:12px;font-weight:600;color:var(--muted);margin-bottom:6px">Job description (optional — improves the cover letter)</p>
    <textarea id="genModalDesc" placeholder="Paste the full job posting here if the scraped description was thin or missing."></textarea>
    <div class="modal-actions">
      <button class="modal-btn-cancel" onclick="closeGenModal()">Cancel</button>
      <button class="modal-btn-generate" id="genModalBtn" onclick="submitGenerate()">Generate</button>
    </div>
  </div>
</div>

<script id="jobs-data" type="application/json">{jobs_json}</script>
<script id="applied-data" type="application/json">{applied_json}</script>
<script id="profiles-data" type="application/json">{profiles_json}</script>
<script>
const RAW_JOBS = JSON.parse(document.getElementById('jobs-data').textContent);
const APPLIED_IDS = JSON.parse(document.getElementById('applied-data').textContent);
const PROFILES = JSON.parse(document.getElementById('profiles-data').textContent);
let currentFilter = 'all';

document.getElementById('profileChips').innerHTML = PROFILES.map(p =>
  `<button class="filter-btn" data-filter="${{p}}" onclick="setFilter('${{p}}', this)">${{p}}</button>`
).join('');

function getScoreClass(score) {{ return score >= 70 ? 'score-high' : score >= 50 ? 'score-mid' : 'score-low'; }}

function renderCard(job) {{
  const breakdown = job.score_breakdown || {{}};
  const score = Math.round(job.score || 0);
  const profile = job.profile_match || '';
  const isApplied = APPLIED_IDS.includes(job.id);

  const viewBtn = job.url
    ? `<a class="btn btn-view" href="${{job.url}}" target="_blank">View Job &#8599;</a>`
    : `<span class="btn btn-view disabled">No link</span>`;
  const genBtn = `<button class="btn btn-cv" onclick="event.stopPropagation();openGenModal('${{job.id}}')">${{job.cv_path ? '&#8635; Regenerate' : 'Generate CV/CL'}}</button>`;
  const clLink = job.cl_path ? `<a class="btn btn-cl" href="/cv/${{job.cl_path.split('/').pop()}}" target="_blank">Cover Letter &#8599;</a>` : '';
  const cvLink = job.cv_path ? `<a class="btn btn-cv" href="/cv/${{job.cv_path.split('/').pop()}}" target="_blank">CV &#8599;</a>` : '';
  const markAppliedBtn = `<button class="btn btn-mark-applied ${{isApplied ? 'applied' : ''}}" onclick="event.stopPropagation();markApplied('${{job.id}}')" ${{isApplied ? 'disabled' : ''}}>${{isApplied ? '&#10003; Applied' : 'Mark Applied'}}</button>`;
  const reasonHtml = job.match_reason ? `<div class="match-reason">Keywords: ${{job.match_reason}}</div>` : '';
  const appliedBadge = isApplied ? `<span class="applied-badge">Applied &#10003;</span>` : '';

  const bars = ['location','role_fit','seniority','industry'].map(dim => {{
    const val = Math.round(breakdown[dim] || 0);
    const label = dim === 'role_fit' ? 'Role Fit' : dim.charAt(0).toUpperCase() + dim.slice(1);
    return `<div class="score-bar-row"><div class="score-bar-label">${{label}}</div><div class="score-bar-track"><div class="score-bar-fill" style="width:${{val}}%"></div></div><div class="score-bar-val">${{val}}</div></div>`;
  }}).join('');

  return `
    <div class="job-card ${{isApplied ? 'applied-card' : ''}}" id="card-${{job.id}}" data-id="${{job.id}}" data-profile="${{profile}}" data-score="${{score}}">
      <button class="btn-dismiss" onclick="event.stopPropagation();dismissJob('${{job.id}}')" title="Hide this job">&#10005;</button>
      <div class="job-card-inner">
        <div class="card-top">
          <div class="company-title">
            <h3>${{job.title || 'Untitled'}} ${{appliedBadge}}</h3>
            <div class="company">${{job.company || ''}} ${{job.location ? '&middot; ' + job.location : ''}}</div>
          </div>
          <div class="score-badge ${{getScoreClass(score)}}">${{score}}</div>
        </div>
        <div class="card-tags">
          ${{job.location ? `<span class="tag tag-location">${{job.location}}</span>` : ''}}
          ${{profile ? `<span class="tag tag-profile">${{profile}}</span>` : ''}}
          ${{job.source ? `<span class="tag tag-source">${{job.source}}</span>` : ''}}
        </div>
        ${{reasonHtml}}
        <div class="score-bars">${{bars}}</div>
      </div>
      <div class="card-actions">
        ${{viewBtn}}${{genBtn}}${{clLink}}${{cvLink}}${{markAppliedBtn}}
        <button class="btn btn-seen" onclick="event.stopPropagation();dismissJob('${{job.id}}')">Mark seen</button>
      </div>
    </div>`;
}}

function filterJobs() {{
  const query = document.getElementById('searchInput').value.toLowerCase();
  const minScore = parseInt(document.getElementById('scoreSlider').value) || 0;
  const grid = document.getElementById('jobsGrid');
  const cards = grid.querySelectorAll('.job-card[data-id]');
  let visible = 0;
  cards.forEach(card => {{
    const profile = card.dataset.profile || '';
    const score = parseInt(card.dataset.score) || 0;
    const text = card.innerText.toLowerCase();
    let show = score >= minScore;
    if (show && currentFilter !== 'all') show = profile === currentFilter;
    if (show && query) show = text.includes(query);
    card.style.display = show ? '' : 'none';
    if (show) visible++;
  }});
  document.getElementById('visibleCount').textContent = visible;
  let empty = grid.querySelector('.empty-state');
  if (visible === 0) {{
    if (!empty) {{ empty = document.createElement('div'); empty.className = 'empty-state'; empty.textContent = 'No jobs match this filter.'; grid.appendChild(empty); }}
  }} else if (empty) empty.remove();
}}

function setFilter(filter, btn) {{
  currentFilter = filter;
  document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  filterJobs();
}}

function sortJobs() {{
  const sortBy = document.getElementById('sortSelect').value;
  const grid = document.getElementById('jobsGrid');
  const cards = Array.from(grid.querySelectorAll('.job-card'));
  cards.sort((a, b) => sortBy === 'score'
    ? parseInt(b.dataset.score) - parseInt(a.dataset.score)
    : (a.querySelector('.company').textContent || '').localeCompare(b.querySelector('.company').textContent || ''));
  cards.forEach(c => grid.appendChild(c));
  filterJobs();
}}

function showToast(msg, color) {{
  let t = document.getElementById('toast');
  if (!t) {{ t = document.createElement('div'); t.id = 'toast'; t.style.cssText = 'position:fixed;bottom:24px;right:24px;padding:12px 20px;border-radius:8px;color:#fff;font-size:14px;z-index:9999;transition:opacity .3s'; document.body.appendChild(t); }}
  t.style.background = color || '#27ae60'; t.textContent = msg; t.style.opacity = '1';
  clearTimeout(t._timer); t._timer = setTimeout(() => t.style.opacity = '0', 3000);
}}

function dismissJob(jobId) {{
  fetch('/api/reject/' + jobId, {{method:'POST'}}).then(r => r.json()).then(d => {{
    if (d.ok) {{
      const card = document.getElementById('card-' + jobId);
      card.style.transition = 'opacity .3s'; card.style.opacity = '0';
      setTimeout(() => {{ card.remove(); filterJobs(); }}, 300);
      showToast('Hidden — won\\'t reappear until you undo it in data/job_leads.json', '#e74c3c');
    }}
  }});
}}

function markApplied(jobId) {{
  const notes = prompt('Any notes for the archive? (optional)') || '';
  fetch('/api/apply/' + jobId, {{method:'POST', headers:{{'Content-Type':'application/json'}}, body: JSON.stringify({{notes}})}})
    .then(r => r.json()).then(d => {{
      if (d.ok) {{
        const btn = document.querySelector('#card-' + jobId + ' .btn-mark-applied');
        if (btn) {{ btn.textContent = '\\u2713 Applied'; btn.classList.add('applied'); btn.disabled = true; }}
        document.getElementById('card-' + jobId).classList.add('applied-card');
        showToast('Moved to archive — view at /archive', '#27ae60');
      }}
    }});
}}

let _genJobId = null;
function openGenModal(jobId) {{
  _genJobId = jobId;
  const job = RAW_JOBS.find(j => j.id === jobId);
  document.getElementById('genModalSubtitle').textContent = job ? `${{job.title}} \\u00b7 ${{job.company}}` : jobId;
  document.getElementById('genModalDesc').value = job ? (job.description || '') : '';
  document.getElementById('genModal').classList.add('open');
}}
function closeGenModal() {{ document.getElementById('genModal').classList.remove('open'); _genJobId = null; }}

function submitGenerate() {{
  const jobId = _genJobId;
  if (!jobId) return;
  const description = document.getElementById('genModalDesc').value.trim();
  const btn = document.getElementById('genModalBtn');
  btn.textContent = 'Generating...'; btn.disabled = true;
  fetch('/api/generate/' + jobId, {{method:'POST', headers:{{'Content-Type':'application/json'}}, body: JSON.stringify({{description}})}})
    .then(r => r.json()).then(d => {{
      closeGenModal();
      btn.textContent = 'Generate'; btn.disabled = false;
      if (d.ok) {{
        if (d.cl_url) window.open(d.cl_url, '_blank');
        showToast('Generated — reload the page to see the links on this card', '#27ae60');
      }} else {{
        showToast('Error: ' + (d.error || 'generation failed'), '#e74c3c');
      }}
    }})
    .catch(() => {{ closeGenModal(); btn.textContent = 'Generate'; btn.disabled = false; showToast('Server error', '#e74c3c'); }});
}}

function renderAll() {{
  const grid = document.getElementById('jobsGrid');
  const jobs = [...RAW_JOBS].sort((a, b) => (b.score || 0) - (a.score || 0));
  grid.innerHTML = jobs.map(renderCard).join('');
  filterJobs();
}}
renderAll();
</script>
</body>
</html>"""


def render_archive(entries: list) -> str:
    entries = sorted(entries, key=lambda a: a.get("applied_date", ""), reverse=True)
    rows = ""
    for a in entries:
        cv_link = f'<a href="/cv/{Path(a.get("cv_path","")).name}" target="_blank">CV</a>' if a.get("cv_path") else "-"
        cl_link = f'<a href="/cv/{Path(a.get("cl_path","")).name}" target="_blank">CL</a>' if a.get("cl_path") else "-"
        rows += (
            f"<tr><td>{a.get('applied_date','')}</td><td><strong>{a.get('title','')}</strong></td>"
            f"<td>{a.get('company','')}</td><td>{a.get('score',0):.0f}</td>"
            f'<td>{cv_link} &nbsp; {cl_link}</td><td><a href="{a.get("url","")}" target="_blank">&#8599;</a></td>'
            f"<td style='color:#888;font-size:12px'>{a.get('notes','')}</td></tr>"
        )
    body = (
        f"<table><thead><tr><th>Date</th><th>Role</th><th>Company</th><th>Score</th><th>Docs</th><th>Link</th><th>Notes</th></tr></thead><tbody>{rows}</tbody></table>"
        if entries else "<div class='empty'>No applications tracked yet. Click \"Mark Applied\" on a job to add it here.</div>"
    )
    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Applications Archive</title>
<style>
body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; background:#f8f9fa; color:#333; padding:32px; }}
h1 {{ color:#2C3E50; margin-bottom:8px; }} p.sub {{ color:#888; margin-bottom:24px; }}
a {{ color:#3498db; }} table {{ border-collapse:collapse; width:100%; background:#fff; border-radius:10px; overflow:hidden; }}
th {{ background:#2C3E50; color:#fff; padding:10px 14px; text-align:left; font-size:13px; }}
td {{ padding:10px 14px; border-bottom:1px solid #eee; font-size:14px; }}
.back {{ display:inline-block; margin-bottom:20px; color:#3498db; text-decoration:none; }}
.empty {{ text-align:center; padding:60px; color:#888; }}
</style></head><body>
<a href="/" class="back">&larr; Back to jobs</a>
<h1>Applications Archive</h1>
<p class="sub">{len(entries)} job{'s' if len(entries) != 1 else ''} applied to</p>
{body}
</body></html>"""


# ── Routes ────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    jobs = [j for j in load_jobs() if not j.get("rejected")]
    applied_ids = {j["id"] for j in jobs if j.get("applied")}
    warnings = load_json(WARNINGS_PATH, [])
    return Response(render_dashboard(jobs, applied_ids, warnings), mimetype="text/html")


@app.route("/archive")
def archive():
    return Response(render_archive(load_archive()), mimetype="text/html")


@app.route("/cv/<filename>")
def serve_cv(filename):
    path = CV_DIR / filename
    if path.exists():
        return send_file(str(path))
    return "File not found", 404


@app.route("/api/reject/<job_id>", methods=["POST"])
def reject_job(job_id):
    jobs = load_jobs()
    for j in jobs:
        if j["id"] == job_id:
            j["rejected"] = True
    save_jobs(jobs)
    log.info(f"Dismissed: {job_id}")
    return jsonify({"ok": True})


@app.route("/api/undo-reject/<job_id>", methods=["POST"])
def undo_reject(job_id):
    jobs = load_jobs()
    for j in jobs:
        if j["id"] == job_id:
            j["rejected"] = False
    save_jobs(jobs)
    return jsonify({"ok": True})


@app.route("/api/description/<job_id>", methods=["POST"])
def save_description(job_id):
    body = request.get_json(silent=True) or {}
    desc = (body.get("description") or "").strip()
    if not desc:
        return jsonify({"ok": False, "error": "No description provided"}), 400
    jobs = load_jobs()
    updated = False
    for j in jobs:
        if j["id"] == job_id:
            j["description"] = desc
            updated = True
    if not updated:
        return jsonify({"ok": False, "error": "Job not found"}), 404
    save_jobs(jobs)
    return jsonify({"ok": True, "chars": len(desc)})


@app.route("/api/apply/<job_id>", methods=["POST"])
def mark_applied(job_id):
    body = request.get_json(silent=True) or {}
    jobs = load_jobs()
    job = next((j for j in jobs if j["id"] == job_id), None)
    if not job:
        return jsonify({"ok": False, "error": "Job not found"}), 404

    job["applied"] = True
    save_jobs(jobs)

    archive_entries = load_archive()
    if not any(a["id"] == job_id for a in archive_entries):
        archive_entries.append({
            "id": job_id,
            "title": job.get("title", ""),
            "company": job.get("company", ""),
            "url": job.get("url", ""),
            "location": job.get("location", ""),
            "score": job.get("score", 0),
            "profile_match": job.get("profile_match", ""),
            "applied_date": datetime.now().strftime("%Y-%m-%d"),
            "notes": body.get("notes", ""),
            "cv_path": job.get("cv_path", ""),
            "cl_path": job.get("cl_path", ""),
        })
        save_json(ARCHIVE_PATH, archive_entries)
    log.info(f"Applied: {job.get('title')} @ {job.get('company')}")
    return jsonify({"ok": True})


@app.route("/api/generate/<job_id>", methods=["POST"])
def generate_cv(job_id):
    jobs = load_jobs()
    job_data = next((j for j in jobs if j["id"] == job_id), None)
    if not job_data:
        return jsonify({"ok": False, "error": "Job not found"}), 404

    try:
        body = request.get_json(silent=True) or {}
        manual_desc = (body.get("description") or "").strip()
        job = _Job(**job_data)
        if manual_desc:
            job.description = manual_desc

        cv_path = cv_generator.generate_cv_for_job(job, cv_data_path=str(CV_DATA_PATH), config_path=str(CONFIG_PATH))
        cl_path = cv_generator.generate_cover_letter(job, cv_data_path=str(CV_DATA_PATH), config_path=str(CONFIG_PATH))

        for j in jobs:
            if j["id"] == job_id:
                j["cv_path"] = cv_path
                j["cl_path"] = cl_path
                if manual_desc:
                    j["description"] = manual_desc
        save_jobs(jobs)

        cv_name = Path(cv_path).name if cv_path else ""
        cl_name = Path(cl_path).name if cl_path else ""
        return jsonify({"ok": True, "cv_url": f"/cv/{cv_name}", "cl_url": f"/cv/{cl_name}"})
    except Exception as e:
        log.error(f"Generation failed: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


if __name__ == "__main__":
    DATA_DIR.mkdir(exist_ok=True)
    print("\n" + "=" * 50)
    print("  Job Agent Server")
    print("  Open:    http://localhost:5555")
    print("  Archive: http://localhost:5555/archive")
    print("=" * 50 + "\n")
    app.run(host="127.0.0.1", port=5555, debug=False)

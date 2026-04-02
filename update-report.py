#!/usr/bin/env python3
"""
update-report.py — Inject agent recommendations into a visual-qa HTML report.

Adds a collapsible recommendations section to report.html, embeds an
"Export as Markdown" button, and updates library.html with a recommendations
indicator on the relevant card.

Usage:
    python3 update-report.py --recommendations PATH [--run-dir PATH] [--report-dir PATH]

    If --run-dir is omitted, the most recent run in --report-dir is used.

Recommendations JSON format (write to /tmp/qa-recommendations.json):
[
  {
    "element": "Avatar",
    "status": "FAIL",
    "observation": "48pt diameter in app, 72pt in Figma",
    "recommendation": "Increase the avatar circle diameter to 72pt."
  },
  {
    "element": "Action row gap",
    "status": "REVIEW",
    "observation": "12pt gap between buttons in app, 16pt in Figma",
    "recommendation": "Increase gap between action buttons to 16pt."
  }
]

Status values: FAIL | REVIEW
"""
import json, sys, argparse
from pathlib import Path

REPORT_DIR_DEFAULT = Path.home() / ".visual-qa-reports"
VERDICT_COLOR = {
    "PASS":    "#22c55e",
    "REVIEW":  "#f59e0b",
    "FAIL":    "#ef4444",
    "INSPECT": "#3b82f6",
}
STATUS_COLOR = {"FAIL": "#ef4444", "REVIEW": "#f59e0b"}


# ── Helpers ───────────────────────────────────────────────────────────────────

def find_latest_run(report_dir):
    runs = sorted(
        [d for d in Path(report_dir).iterdir() if d.is_dir() and (d / "meta.json").exists()],
        reverse=True
    )
    if not runs:
        print(f"ERROR: No runs found in {report_dir}")
        sys.exit(1)
    return runs[0]


def _format_timestamp(ts):
    """Convert '2026-04-02T14-30-00' to '2026-04-02 14:30:00'."""
    parts = ts.replace("T", " ").split(" ", 1)
    if len(parts) == 2:
        return parts[0] + " " + parts[1].replace("-", ":")
    return ts


def escape_html(s):
    return (str(s)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))


def escape_js(s):
    return (str(s)
            .replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\n", "\\n")
            .replace("\r", ""))


# ── Recommendations HTML block ────────────────────────────────────────────────

def build_recommendations_html(recs, meta):
    fail_count   = sum(1 for r in recs if r.get("status") == "FAIL")
    review_count = sum(1 for r in recs if r.get("status") == "REVIEW")

    summary_parts = []
    if fail_count:
        summary_parts.append(f'<span style="color:#ef4444;font-weight:700">{fail_count} FAIL</span>')
    if review_count:
        summary_parts.append(f'<span style="color:#f59e0b;font-weight:700">{review_count} REVIEW</span>')
    summary_str = " &nbsp;&middot;&nbsp; ".join(summary_parts) if summary_parts else "No issues"

    items_html = ""
    for rec in recs:
        status = rec.get("status", "REVIEW").upper()
        color  = STATUS_COLOR.get(status, "#f59e0b")
        elem   = escape_html(rec.get("element", ""))
        obs    = escape_html(rec.get("observation", ""))
        recom  = escape_html(rec.get("recommendation", ""))

        items_html += f"""
  <details class="rec-item">
    <summary>
      <span class="rec-pill" style="background:{color}22;color:{color}">{status}</span>
      <span class="rec-elem">{elem}</span>
      <span class="rec-chevron">&#9654;</span>
    </summary>
    <div class="rec-body">
      <div class="rec-row">
        <span class="rec-label">Observation</span>
        <span class="rec-value">{obs}</span>
      </div>
      <div class="rec-row" style="margin-top:10px">
        <span class="rec-label">Recommendation</span>
        <span class="rec-value">{recom}</span>
      </div>
    </div>
  </details>"""

    # Embed recs + meta as JSON for the export function
    recs_json   = json.dumps(recs,   ensure_ascii=False)
    meta_subset = {
        "screen_name": meta.get("screen_name", ""),
        "node_id":     meta.get("node_id", ""),
        "timestamp":   meta.get("timestamp", ""),
        "verdict":     meta.get("verdict", ""),
    }
    meta_json = json.dumps(meta_subset, ensure_ascii=False)

    return f"""
<!-- RECOMMENDATIONS_START -->
<style>
.rec-section{{margin-top:36px;padding:24px;background:#141414;border:1px solid #27272a;border-radius:12px}}
.rec-header{{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px;margin-bottom:20px}}
.rec-title{{font-size:16px;font-weight:700;letter-spacing:-0.3px}}
.rec-summary{{font-size:13px;color:#71717a;margin-top:4px}}
.rec-btns{{display:flex;gap:8px;flex-wrap:wrap}}
.rec-btn{{background:#27272a;border:none;color:#e4e4e7;font-size:12px;font-weight:500;
  padding:6px 14px;border-radius:8px;cursor:pointer;transition:background .15s}}
.rec-btn:hover{{background:#3f3f46}}
.rec-btn.export{{background:#1d4ed822;color:#60a5fa;border:1px solid #1d4ed844}}
.rec-btn.export:hover{{background:#1d4ed833}}
.rec-item{{border:1px solid #27272a;border-radius:8px;overflow:hidden;margin-top:8px}}
.rec-item summary{{display:flex;align-items:center;gap:10px;padding:12px 16px;
  cursor:pointer;list-style:none;user-select:none}}
.rec-item summary::-webkit-details-marker{{display:none}}
.rec-item summary:hover{{background:#1a1a1a}}
.rec-pill{{font-size:11px;font-weight:700;padding:2px 8px;border-radius:999px;
  letter-spacing:.04em;flex-shrink:0}}
.rec-elem{{font-size:14px;font-weight:500;flex:1}}
.rec-chevron{{color:#52525b;font-size:10px;transition:transform .15s;flex-shrink:0}}
.rec-item[open] .rec-chevron{{transform:rotate(90deg)}}
.rec-body{{padding:16px;border-top:1px solid #27272a;background:#0f0f0f}}
.rec-row{{display:grid;grid-template-columns:110px 1fr;gap:12px;align-items:baseline}}
.rec-label{{font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.05em;color:#71717a}}
.rec-value{{font-size:13px;color:#d4d4d8;line-height:1.5}}
</style>

<div class="rec-section" id="recommendations">
  <div class="rec-header">
    <div>
      <div class="rec-title">Recommendations</div>
      <div class="rec-summary">{summary_str}</div>
    </div>
    <div class="rec-btns">
      <button class="rec-btn" onclick="recToggleAll(true)">Show all</button>
      <button class="rec-btn" onclick="recToggleAll(false)">Hide all</button>
      <button class="rec-btn export" onclick="recExportMarkdown()">Export as Markdown &#8595;</button>
    </div>
  </div>
{items_html}
</div>

<script id="rec-data" type="application/json">{recs_json}</script>
<script id="rec-meta" type="application/json">{meta_json}</script>
<script>
function recToggleAll(open) {{
  document.querySelectorAll('#recommendations .rec-item').forEach(function(d) {{ d.open = open; }});
}}

function recExportMarkdown() {{
  var recs  = JSON.parse(document.getElementById('rec-data').textContent);
  var meta  = JSON.parse(document.getElementById('rec-meta').textContent);
  var ts    = (meta.timestamp || '').replace('T', ' ');
  var parts = ts.split(' ');
  if (parts.length === 2) {{ ts = parts[0] + ' ' + parts[1].replace(/-/g, ':'); }}
  var lines = [];

  lines.push('# Visual QA Recommendations: ' + (meta.screen_name || meta.node_id));
  lines.push('');
  lines.push('**Node:** ' + meta.node_id + ' | **Date:** ' + ts + ' | **Verdict:** ' + meta.verdict);
  lines.push('');

  var fails   = recs.filter(function(r) {{ return r.status === 'FAIL'; }});
  var reviews = recs.filter(function(r) {{ return r.status === 'REVIEW'; }});

  if (fails.length) {{
    lines.push('## FAIL — Must fix');
    lines.push('');
    fails.forEach(function(r) {{
      lines.push('### ' + r.element);
      lines.push('**Observation:** ' + r.observation);
      lines.push('');
      lines.push('**Recommendation:** ' + r.recommendation);
      lines.push('');
    }});
  }}

  if (reviews.length) {{
    lines.push('## REVIEW — Consider fixing');
    lines.push('');
    reviews.forEach(function(r) {{
      lines.push('### ' + r.element);
      lines.push('**Observation:** ' + r.observation);
      lines.push('');
      lines.push('**Recommendation:** ' + r.recommendation);
      lines.push('');
    }});
  }}

  var md   = lines.join('\\n');
  var slug = (meta.node_id || 'report').replace(':', '-');
  var blob = new Blob([md], {{type: 'text/markdown'}});
  var a    = document.createElement('a');
  a.href     = URL.createObjectURL(blob);
  a.download = 'qa-recommendations-' + slug + '.md';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}}
</script>
<!-- RECOMMENDATIONS_END -->
"""


# ── Library regeneration ──────────────────────────────────────────────────────

def _import_generate_library():
    """Import generate_library from compare-screenshots.py (single source of truth)."""
    import importlib.util
    cs_path = Path(__file__).parent / "compare-screenshots.py"
    spec = importlib.util.spec_from_file_location("compare_screenshots", cs_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.generate_library


def regenerate_library(report_dir):
    """Rebuild library.html using the canonical function in compare-screenshots.py."""
    generate_library = _import_generate_library()
    generate_library(report_dir)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Inject agent recommendations into a visual-qa HTML report."
    )
    parser.add_argument(
        "--recommendations",
        metavar="PATH",
        required=True,
        help="Path to a JSON file containing the recommendations array"
    )
    parser.add_argument(
        "--run-dir",
        metavar="PATH",
        help=(
            "Path to the run folder to update. "
            "If omitted, the most recent run in --report-dir is used."
        )
    )
    parser.add_argument(
        "--report-dir",
        metavar="PATH",
        default=str(REPORT_DIR_DEFAULT),
        help=f"Parent library directory (default: {REPORT_DIR_DEFAULT})"
    )
    args = parser.parse_args()

    # Resolve run dir
    run_dir = Path(args.run_dir) if args.run_dir else find_latest_run(args.report_dir)
    if not run_dir.exists():
        print(f"ERROR: Run directory not found: {run_dir}")
        sys.exit(1)

    # Load recommendations
    recs_path = Path(args.recommendations)
    if not recs_path.exists():
        print(f"ERROR: Recommendations file not found: {recs_path}")
        sys.exit(1)
    try:
        recs = json.loads(recs_path.read_text())
        if not isinstance(recs, list):
            raise ValueError("Expected a JSON array")
    except Exception as e:
        print(f"ERROR: Could not parse recommendations JSON: {e}")
        sys.exit(1)

    # Load meta
    meta_path = run_dir / "meta.json"
    if not meta_path.exists():
        print(f"ERROR: meta.json not found in {run_dir}")
        sys.exit(1)
    meta = json.loads(meta_path.read_text())

    # Save recommendations.json into run dir
    (run_dir / "recommendations.json").write_text(
        json.dumps(recs, indent=2, ensure_ascii=False)
    )

    # Update meta with recommendation count
    meta["recommendation_count"] = len(recs)
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False))

    # Build the HTML block to inject
    rec_html = build_recommendations_html(recs, meta)

    # Inject into report.html (before </body>)
    report_path = run_dir / "report.html"
    if not report_path.exists():
        print(f"ERROR: report.html not found in {run_dir}")
        sys.exit(1)

    existing = report_path.read_text(encoding="utf-8")

    # Remove any previously injected recommendations block before re-injecting
    start_marker = "<!-- RECOMMENDATIONS_START -->"
    end_marker   = "<!-- RECOMMENDATIONS_END -->"
    if start_marker in existing:
        start = existing.find(start_marker)
        end   = existing.find(end_marker)
        if start != -1 and end != -1:
            existing = existing[:start] + existing[end + len(end_marker):]

    updated = existing.replace("</body>", rec_html + "\n</body>")
    report_path.write_text(updated, encoding="utf-8")
    print(f"  Report updated    → {report_path}")

    # Regenerate library
    regenerate_library(Path(args.report_dir))

    fail_count   = sum(1 for r in recs if r.get("status", "").upper() == "FAIL")
    review_count = sum(1 for r in recs if r.get("status", "").upper() == "REVIEW")
    print(f"\n  {len(recs)} recommendation(s) added  "
          f"({fail_count} FAIL, {review_count} REVIEW)")
    print(f"  Open the report to view and export:\n  {report_path}\n")


if __name__ == "__main__":
    main()

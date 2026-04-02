#!/usr/bin/env python3
"""
compare-screenshots.py — Figma vs app visual diff tool
Supports: iOS Simulator, Android Emulator, web (pre-captured screenshot)

Usage:
    python3 compare-screenshots.py <fileKey> <nodeId> [options]

Options:
    --platform ios|android|web   Screenshot source (default: ios)
    --design-width N             Frame width in logical points (default: 390 for iPhone).
                                 Use the Figma frame width for web, or 360 for most Android phones.
    --web-screenshot PATH        Web/iOS MCP: path to a pre-captured PNG to use instead of capturing
    --skip-capture               Skip the capture step entirely; diff whatever is already at SIM_PATH.
                                 Use when the screenshot was already taken by an MCP tool (e.g. XcodeBuildMCP).
    --screen-name NAME           Human-readable label shown in the report (e.g. "Contact Detail - Default")
    --report-dir PATH            Directory for the run report and library (default: ~/.visual-qa-reports)
    --inspect-only               Skip pixel diff entirely. Downloads the Figma reference for visual
                                 comparison, saves a side-by-side report, and logs the run to the library
                                 as "INSPECT". Use when screen widths differ (responsive QA).
    --sections PATH [PATH ...]   Paths to multiple viewport screenshots captured top-to-bottom by
                                 scrolling through a long screen. The Figma reference (full frame height)
                                 is sliced into matching viewport chunks and each pair is diffed
                                 independently. Results are combined into one library card and report.
                                 Requires --skip-capture to be set (screenshots pre-captured via MCP).

Requires:
    - ~/.figma_token or FIGMA_TOKEN env var (Figma personal access token)
    - pip3 install Pillow
    - iOS:     xcrun (built into macOS) — or XcodeBuildMCP with --skip-capture
    - Android: adb (Android SDK / Android Studio)
    - Web:     pass --web-screenshot with a file captured by the browser MCP tool
"""
import sys, os, io, json, shutil, base64, datetime, urllib.request, subprocess, argparse
from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError:
    print("ERROR: Pillow not installed. Run: pip3 install Pillow")
    sys.exit(1)

FIGMA_REF_PATH    = "/tmp/figma-ref.png"
SIM_PATH          = "/tmp/sim-current.png"
DIFF_PATH         = "/tmp/diff-highlighted.png"
DIFF_OVERLAY_PATH = "/tmp/diff-overlay.png"
TOKEN_FILE        = Path.home() / ".figma_token"
REPORT_DIR_DEFAULT = Path.home() / ".visual-qa-reports"

DIFF_THRESHOLD = 15  # 0–255; tolerates font anti-aliasing and minor shadow blending

# Mobile: skip the OS-rendered status bar (top) and home indicator (bottom).
# Web: browser_take_screenshot captures page content only — no chrome — so skip nothing.
SKIP_FRACTIONS = {
    "ios":     (0.07, 0.04),
    "android": (0.07, 0.04),
    "web":     (0.0,  0.0),
}


# ── Auth ──────────────────────────────────────────────────────────────────────

def read_token():
    if TOKEN_FILE.exists():
        token = TOKEN_FILE.read_text().strip()
        if token:
            return token
    env_token = os.environ.get("FIGMA_TOKEN", "")
    if env_token:
        return env_token
    print("ERROR: No Figma token found.")
    print("  Create ~/.figma_token with your token, or set FIGMA_TOKEN env var.")
    print("  Get a token at: figma.com → Settings → Security → Personal access tokens")
    sys.exit(1)


# ── Figma download ────────────────────────────────────────────────────────────

def download_figma_screenshot(file_key, node_id, token):
    node_id_encoded = node_id.replace(":", "%3A")
    api_url = (
        f"https://api.figma.com/v1/images/{file_key}"
        f"?ids={node_id_encoded}&format=png&scale=2"
    )
    req = urllib.request.Request(api_url, headers={"X-Figma-Token": token})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print(f"ERROR: Figma API request failed ({e.code}). Check your token and file key.")
        sys.exit(1)

    if data.get("err"):
        print(f"ERROR from Figma API: {data['err']}")
        sys.exit(1)

    images = data.get("images", {})
    img_url = images.get(node_id) or images.get(node_id.replace(":", "-"))
    if not img_url:
        print(f"ERROR: No image URL returned for node {node_id!r}.")
        print(f"  Available node IDs in response: {list(images.keys())}")
        sys.exit(1)

    urllib.request.urlretrieve(img_url, FIGMA_REF_PATH)
    print(f"  Figma reference saved → {FIGMA_REF_PATH}")


# ── Screenshot capture ────────────────────────────────────────────────────────

def capture_ios():
    result = subprocess.run(
        ["xcrun", "simctl", "io", "booted", "screenshot", SIM_PATH],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"ERROR: iOS capture failed.\n  {result.stderr.strip()}")
        print("  Make sure the iOS Simulator is running and a device is booted.")
        sys.exit(1)
    print(f"  iOS Simulator screenshot saved → {SIM_PATH}")


def capture_android():
    result = subprocess.run(
        ["adb", "exec-out", "screencap", "-p"],
        capture_output=True
    )
    if result.returncode != 0:
        print("ERROR: Android capture failed.")
        print("  Make sure the Android Emulator is running and adb is in your PATH.")
        print("  Try: adb devices  (to confirm the emulator is connected)")
        sys.exit(1)
    if not result.stdout:
        print("ERROR: adb returned empty output. Is the emulator fully booted?")
        sys.exit(1)
    with open(SIM_PATH, "wb") as f:
        f.write(result.stdout)
    print(f"  Android Emulator screenshot saved → {SIM_PATH}")


def capture_web(web_screenshot_path):
    if not web_screenshot_path:
        print("ERROR: --web-screenshot <path> is required for --platform web.")
        print("  Capture the browser screenshot using the cursor-ide-browser MCP tool,")
        print("  save it to a path, then re-run with --web-screenshot <path>.")
        sys.exit(1)
    src = Path(web_screenshot_path).resolve()
    dst = Path(SIM_PATH).resolve()
    if not src.exists():
        print(f"ERROR: Screenshot file not found: {web_screenshot_path}")
        sys.exit(1)
    if src == dst:
        print(f"  Web screenshot already at {SIM_PATH} — skipping copy")
    else:
        shutil.copy(src, SIM_PATH)
        print(f"  Web screenshot copied from {web_screenshot_path} → {SIM_PATH}")


# ── Normalization ─────────────────────────────────────────────────────────────

def normalize_images(img_a, img_b, design_width_pt):
    """
    The Figma API exports the full scrollable frame height, while screenshots
    only capture the visible viewport. This function:
      1. Derives each image's pixel scale from its width vs the logical design width
      2. Crops both to the shorter logical height (the visible viewport)
      3. Resizes both to the same pixel dimensions before diffing

    design_width_pt: the Figma frame width in logical points (e.g. 390 for iPhone,
    360 for most Android phones, or the actual Figma frame width for web).
    """
    img_a = img_a.convert("RGB")
    img_b = img_b.convert("RGB")

    scale_a = img_a.width / design_width_pt
    scale_b = img_b.width / design_width_pt

    vp_height_pt = min(img_a.height / scale_a, img_b.height / scale_b)

    crop_a = img_a.crop((0, 0, img_a.width, int(vp_height_pt * scale_a)))
    crop_b = img_b.crop((0, 0, img_b.width, int(vp_height_pt * scale_b)))

    target = (crop_a.width, crop_a.height)
    if crop_b.size != target:
        crop_b = crop_b.resize(target, Image.LANCZOS)

    return crop_a, crop_b


def slice_figma_to_sections(figma_full, section_imgs, design_width_pt):
    """
    Slice the full-height Figma reference into viewport-sized chunks that
    correspond to each scrolled section screenshot.

    The Figma reference is exported at scale=2 (retina). Each section screenshot
    was captured from a fixed-width device viewport. This function:
      1. Computes the logical viewport height from each section screenshot's dimensions
      2. Walks down the Figma frame one viewport at a time
      3. Crops and resizes each Figma slice to match the paired section screenshot exactly

    Returns a list of (figma_slice, section_img_rgb) pairs ready for build_diff().
    """
    figma_scale = figma_full.width / design_width_pt
    pairs = []
    y_pt_offset = 0.0

    for section_img in section_imgs:
        section_rgb   = section_img.convert("RGB")
        section_scale = section_rgb.width / design_width_pt
        vp_height_pt  = section_rgb.height / section_scale

        y0_px = int(y_pt_offset * figma_scale)
        y1_px = int((y_pt_offset + vp_height_pt) * figma_scale)
        y1_px = min(y1_px, figma_full.height)   # cap at bottom of Figma frame

        slice_img = figma_full.crop((0, y0_px, figma_full.width, y1_px)).convert("RGB")

        target = (section_rgb.width, section_rgb.height)
        if slice_img.size != target:
            slice_img = slice_img.resize(target, Image.LANCZOS)

        pairs.append((slice_img, section_rgb))
        y_pt_offset += vp_height_pt

    return pairs


# ── Diff ──────────────────────────────────────────────────────────────────────

def build_diff(figma, sim, threshold, skip_top_frac=0.07, skip_bottom_frac=0.04):
    width, height = figma.size
    skip_top    = int(height * skip_top_frac)
    skip_bottom = int(height * (1 - skip_bottom_frac))

    figma_pixels = list(figma.getdata())
    sim_pixels   = list(sim.getdata())
    diff_pixels  = []

    total_content = diff_count = 0
    content_height = skip_bottom - skip_top
    third = content_height // 3
    region_counts = {"top": [0, 0], "middle": [0, 0], "bottom": [0, 0]}

    for i, (fp, sp) in enumerate(zip(figma_pixels, sim_pixels)):
        y = i // width
        if y < skip_top or y >= skip_bottom:
            diff_pixels.append(fp)
            continue

        total_content += 1
        max_delta = max(abs(int(fp[c]) - int(sp[c])) for c in range(3))
        is_diff = max_delta > threshold

        if is_diff:
            diff_count += 1
            diff_pixels.append((220, 30, 30))
        else:
            diff_pixels.append(tuple(int(c * 0.35) for c in fp))

        rel_y = y - skip_top
        region = "top" if rel_y < third else ("middle" if rel_y < 2 * third else "bottom")
        region_counts[region][1] += 1
        if is_diff:
            region_counts[region][0] += 1

    diff_img = Image.new("RGB", figma.size)
    diff_img.putdata(diff_pixels)

    pct_diff   = (diff_count / total_content * 100) if total_content else 0
    region_map = {n: (c[0] / c[1] * 100 if c[1] else 0) for n, c in region_counts.items()}
    return diff_img, pct_diff, region_map


# ── Side-by-side composite ────────────────────────────────────────────────────

def build_side_by_side(figma, sim, diff):
    w, h         = figma.size
    padding      = 20
    label_height = 30
    total_w      = w * 3 + padding * 4
    total_h      = h + padding * 2 + label_height

    canvas = Image.new("RGB", (total_w, total_h), (20, 20, 20))
    draw   = ImageDraw.Draw(canvas)

    panels = [("Figma", figma), ("App", sim), ("Diff  (red = different)", diff)]
    for idx, (label, img) in enumerate(panels):
        x = padding + idx * (w + padding)
        y = padding + label_height
        canvas.paste(img, (x, y))
        draw.text((x, padding // 2), label, fill=(200, 200, 200))

    return canvas


# ── Verdict helpers ───────────────────────────────────────────────────────────

def get_verdict(pct_diff):
    if pct_diff < 2:
        return "PASS"
    elif pct_diff < 8:
        return "REVIEW"
    else:
        return "FAIL"

VERDICT_COLOR = {
    "PASS":    "#22c55e",
    "REVIEW":  "#f59e0b",
    "FAIL":    "#ef4444",
    "INSPECT": "#3b82f6",
}


# ── HTML report generation ────────────────────────────────────────────────────

def _format_timestamp(ts):
    """Convert '2026-04-02T14-30-00' to '2026-04-02 14:30:00'."""
    parts = ts.replace("T", " ").split(" ", 1)
    if len(parts) == 2:
        return parts[0] + " " + parts[1].replace("-", ":")
    return ts


def img_to_b64(img):
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _bar(pct, color):
    w = min(pct, 100)
    return (
        f'<div style="background:#1e1e1e;border-radius:4px;overflow:hidden;'
        f'height:8px;width:100%">'
        f'<div style="background:{color};width:{w:.1f}%;height:100%"></div></div>'
    )


_REPORT_BASE_STYLE = """
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'SF Pro Display',sans-serif;
  background:#0a0a0a;color:#e4e4e7;min-height:100vh;padding:40px 32px}
a.back{display:inline-flex;align-items:center;gap:6px;color:#71717a;font-size:13px;
  text-decoration:none;margin-bottom:24px}
a.back:hover{color:#e4e4e7}
h1{font-size:24px;font-weight:700;letter-spacing:-0.5px}
.meta{color:#71717a;font-size:13px;margin-top:6px}
.pill{display:inline-flex;align-items:center;padding:4px 12px;border-radius:999px;
  font-size:13px;font-weight:600;margin-top:12px}
.panels{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));
  gap:16px;margin-top:28px}
.panel{background:#141414;border:1px solid #27272a;border-radius:12px;overflow:hidden}
.panel-label{padding:12px 16px;font-size:12px;font-weight:600;text-transform:uppercase;
  letter-spacing:.05em;color:#71717a;border-bottom:1px solid #27272a}
.panel img{width:100%;display:block}
"""


def generate_run_report(run_dir, meta, figma_img, sim_img, diff_img, overlay_img):
    verdict = meta["verdict"]
    color   = VERDICT_COLOR[verdict]
    regions = meta["region_map"]

    figma_b64   = img_to_b64(figma_img)
    sim_b64     = img_to_b64(sim_img)
    diff_b64    = img_to_b64(diff_img)
    overlay_b64 = img_to_b64(overlay_img)

    ts_display = _format_timestamp(meta["timestamp"])

    score_box = f"""
<div style="margin-top:24px;padding:20px;background:#141414;border-radius:12px;border:1px solid #27272a">
  <div style="font-size:12px;color:#71717a;text-transform:uppercase;letter-spacing:.05em;margin-bottom:8px">Overall diff (content area)</div>
  <div style="font-size:28px;font-weight:700;margin-bottom:10px;color:{color}">{meta['pct_diff']:.1f}%</div>
  {_bar(meta['pct_diff'], color)}
  <div style="display:grid;grid-template-columns:80px 1fr 44px;gap:8px;align-items:center;margin-top:16px;font-size:12px;color:#a1a1aa">
    <span>Top third</span>{_bar(regions.get('top',0),color)}<span>{regions.get('top',0):.1f}%</span>
  </div>
  <div style="display:grid;grid-template-columns:80px 1fr 44px;gap:8px;align-items:center;margin-top:10px;font-size:12px;color:#a1a1aa">
    <span>Middle</span>{_bar(regions.get('middle',0),color)}<span>{regions.get('middle',0):.1f}%</span>
  </div>
  <div style="display:grid;grid-template-columns:80px 1fr 44px;gap:8px;align-items:center;margin-top:10px;font-size:12px;color:#a1a1aa">
    <span>Bottom</span>{_bar(regions.get('bottom',0),color)}<span>{regions.get('bottom',0):.1f}%</span>
  </div>
</div>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Visual QA — {meta['screen_name']}</title>
<style>{_REPORT_BASE_STYLE}</style>
</head>
<body>
<a class="back" href="../library.html">&#8592; Library</a>
<h1>{meta['screen_name']}</h1>
<p class="meta">Node {meta['node_id']} &nbsp;&middot;&nbsp; {ts_display}</p>
<div class="pill" style="background:{color}22;color:{color}">{verdict}</div>
{score_box}
<div class="panels">
  <div class="panel"><div class="panel-label">Figma reference</div><img src="{figma_b64}" alt="Figma reference"></div>
  <div class="panel"><div class="panel-label">App screenshot</div><img src="{sim_b64}" alt="App screenshot"></div>
  <div class="panel"><div class="panel-label">Diff (red = different)</div><img src="{diff_b64}" alt="Diff"></div>
  <div class="panel"><div class="panel-label">Side-by-side</div><img src="{overlay_b64}" alt="Side-by-side overlay"></div>
</div>
</body>
</html>"""

    (run_dir / "report.html").write_text(html, encoding="utf-8")
    print(f"  Run report saved → {run_dir / 'report.html'}")


def generate_inspect_report(run_dir, meta, figma_img, sim_img):
    """Inspect-mode report: Figma reference + app screenshot side by side, no diff panels."""
    color = VERDICT_COLOR["INSPECT"]

    figma_b64 = img_to_b64(figma_img)
    sim_b64   = img_to_b64(sim_img)

    ts_display     = _format_timestamp(meta["timestamp"])
    design_width   = meta.get("design_width", "?")
    captured_width = meta.get("captured_width", "?")

    note = (
        f"Figma design: {design_width}px wide &nbsp;&middot;&nbsp; "
        f"Captured: {captured_width}px wide"
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Responsive Inspection — {meta['screen_name']}</title>
<style>{_REPORT_BASE_STYLE}</style>
</head>
<body>
<a class="back" href="../library.html">&#8592; Library</a>
<h1>{meta['screen_name']}</h1>
<p class="meta">Node {meta['node_id']} &nbsp;&middot;&nbsp; {ts_display}</p>
<div class="pill" style="background:{color}22;color:{color}">INSPECT — Responsive</div>
<p style="margin-top:16px;font-size:13px;color:#71717a">{note}</p>
<p style="margin-top:8px;font-size:13px;color:#52525b">
  Pixel diff is not run when widths differ. Use the images below for visual inspection
  and evaluate using the responsive checklist.
</p>
<div class="panels">
  <div class="panel">
    <div class="panel-label">Figma reference ({design_width}px)</div>
    <img src="{figma_b64}" alt="Figma reference">
  </div>
  <div class="panel">
    <div class="panel-label">App screenshot ({captured_width}px)</div>
    <img src="{sim_b64}" alt="App screenshot">
  </div>
</div>
</body>
</html>"""

    (run_dir / "report.html").write_text(html, encoding="utf-8")
    print(f"  Inspect report saved → {run_dir / 'report.html'}")


def generate_multipass_report(run_dir, meta, section_results):
    """
    Render a single consolidated HTML report for a multi-pass scrollable-screen run.

    section_results: list of dicts, each containing:
        figma_img, sim_img, diff_img, overlay_img, pct_diff, region_map
    """
    overall_pct     = meta["pct_diff"]
    overall_verdict = meta["verdict"]
    color           = VERDICT_COLOR[overall_verdict]
    ts_display      = _format_timestamp(meta["timestamp"])
    n_sections      = len(section_results)

    # ── Per-section panels ────────────────────────────────────────────────────
    sections_html = ""
    for i, s in enumerate(section_results, 1):
        s_verdict = get_verdict(s["pct_diff"])
        s_color   = VERDICT_COLOR[s_verdict]
        r         = s["region_map"]
        sections_html += f"""
<div style="margin-top:32px;padding:20px;background:#141414;border-radius:12px;
            border:1px solid #27272a">
  <div style="display:flex;align-items:center;justify-content:space-between;
              margin-bottom:16px">
    <div style="font-size:14px;font-weight:600;color:#e4e4e7">
      Section {i} of {n_sections}
    </div>
    <div class="pill" style="background:{s_color}22;color:{s_color}">
      {s_verdict} &nbsp; {s['pct_diff']:.1f}%
    </div>
  </div>
  <div class="panels">
    <div class="panel">
      <div class="panel-label">Figma slice</div>
      <img src="{img_to_b64(s['figma_img'])}" alt="Figma slice {i}">
    </div>
    <div class="panel">
      <div class="panel-label">App screenshot</div>
      <img src="{img_to_b64(s['sim_img'])}" alt="App section {i}">
    </div>
    <div class="panel">
      <div class="panel-label">Diff (red = different)</div>
      <img src="{img_to_b64(s['diff_img'])}" alt="Diff {i}">
    </div>
    <div class="panel">
      <div class="panel-label">Side-by-side</div>
      <img src="{img_to_b64(s['overlay_img'])}" alt="Overlay {i}">
    </div>
  </div>
  <div style="display:grid;grid-template-columns:80px 1fr 44px;gap:8px;
              align-items:center;margin-top:12px;font-size:12px;color:#a1a1aa">
    <span>Top third</span>{_bar(r.get('top',0),s_color)}
    <span>{r.get('top',0):.1f}%</span>
  </div>
  <div style="display:grid;grid-template-columns:80px 1fr 44px;gap:8px;
              align-items:center;margin-top:10px;font-size:12px;color:#a1a1aa">
    <span>Middle</span>{_bar(r.get('middle',0),s_color)}
    <span>{r.get('middle',0):.1f}%</span>
  </div>
  <div style="display:grid;grid-template-columns:80px 1fr 44px;gap:8px;
              align-items:center;margin-top:10px;font-size:12px;color:#a1a1aa">
    <span>Bottom</span>{_bar(r.get('bottom',0),s_color)}
    <span>{r.get('bottom',0):.1f}%</span>
  </div>
</div>"""

    # ── Overall score box ─────────────────────────────────────────────────────
    section_rows = ""
    for i, s in enumerate(section_results, 1):
        s_color   = VERDICT_COLOR[get_verdict(s["pct_diff"])]
        section_rows += f"""
  <div style="display:grid;grid-template-columns:80px 1fr 44px;gap:8px;
              align-items:center;margin-top:10px;font-size:12px;color:#a1a1aa">
    <span>Section {i}</span>{_bar(s['pct_diff'],s_color)}
    <span>{s['pct_diff']:.1f}%</span>
  </div>"""

    score_box = f"""
<div style="margin-top:24px;padding:20px;background:#141414;border-radius:12px;
            border:1px solid #27272a">
  <div style="font-size:12px;color:#71717a;text-transform:uppercase;
              letter-spacing:.05em;margin-bottom:8px">
    Overall diff — {n_sections} section{"s" if n_sections != 1 else ""} (pixel-weighted average)
  </div>
  <div style="font-size:28px;font-weight:700;margin-bottom:10px;color:{color}">
    {overall_pct:.1f}%
  </div>
  {_bar(overall_pct, color)}
  {section_rows}
</div>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Visual QA — {meta['screen_name']}</title>
<style>{_REPORT_BASE_STYLE}</style>
</head>
<body>
<a class="back" href="../library.html">&#8592; Library</a>
<h1>{meta['screen_name']}</h1>
<p class="meta">
  Node {meta['node_id']} &nbsp;&middot;&nbsp; {ts_display}
  &nbsp;&middot;&nbsp; {n_sections}-section multi-pass
</p>
<div class="pill" style="background:{color}22;color:{color}">{overall_verdict}</div>
{score_box}
{sections_html}
</body>
</html>"""

    (run_dir / "report.html").write_text(html, encoding="utf-8")
    print(f"  Multi-pass report saved → {run_dir / 'report.html'}")


def generate_library(report_dir):
    runs = []
    for d in sorted(report_dir.iterdir(), reverse=True):
        meta_file = d / "meta.json"
        if d.is_dir() and meta_file.exists():
            try:
                meta = json.loads(meta_file.read_text())
                meta["folder"] = d.name
                runs.append(meta)
            except Exception:
                continue

    cards_html = ""
    for run in runs:
        v     = run.get("verdict", "FAIL")
        color = VERDICT_COLOR.get(v, "#ef4444")
        # Inspect runs have no diff-overlay; use the app screenshot as thumbnail
        thumb = (
            f"{run['folder']}/sim-current.png"
            if v == "INSPECT"
            else f"{run['folder']}/diff-overlay.png"
        )
        ts   = _format_timestamp(run.get("timestamp", ""))
        name = run.get("screen_name") or run.get("node_id", "")
        if v == "INSPECT":
            sub = (f"{run.get('captured_width','?')}px captured "
                   f"vs {run.get('design_width','?')}px design")
        elif run.get("mode") == "multipass":
            n = run.get("section_count", "?")
            sub = f"{n} section{'s' if n != 1 else ''} · {run.get('pct_diff', 0):.1f}% avg diff"
        else:
            sub = f"{run.get('pct_diff', 0):.1f}% diff"

        rec_count = run.get("recommendation_count", 0)
        rec_badge = (
            f'<span class="rec-badge">{rec_count} rec{"s" if rec_count != 1 else ""}</span>'
            if rec_count else ""
        )

        cards_html += f"""
  <a class="card" href="{run['folder']}/report.html">
    <div class="thumb"><img src="{thumb}" alt="" loading="lazy"></div>
    <div class="card-body">
      <div class="card-name">{name}</div>
      <div class="card-meta">{ts}</div>
      <div class="card-footer">
        <span class="pill" style="background:{color}22;color:{color}">{v}</span>
        <div style="display:flex;align-items:center;gap:8px">
          {rec_badge}
          <span class="diff">{sub}</span>
        </div>
      </div>
    </div>
  </a>"""

    empty = "" if runs else '<p class="empty">No runs yet.</p>'
    count = f"{len(runs)} run{'s' if len(runs) != 1 else ''}"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Visual QA Library</title>
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'SF Pro Display',sans-serif;
  background:#0a0a0a;color:#e4e4e7;min-height:100vh;padding:40px 32px}}
header{{display:flex;align-items:baseline;justify-content:space-between;margin-bottom:32px}}
h1{{font-size:28px;font-weight:700;letter-spacing:-0.5px}}
.count{{color:#52525b;font-size:14px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:16px}}
.card{{background:#141414;border:1px solid #27272a;border-radius:14px;overflow:hidden;
  text-decoration:none;color:inherit;display:block;
  transition:border-color .15s,transform .15s}}
.card:hover{{border-color:#52525b;transform:translateY(-2px)}}
.thumb{{background:#1e1e1e;aspect-ratio:3/1;overflow:hidden}}
.thumb img{{width:100%;height:100%;object-fit:cover;display:block}}
.card-body{{padding:14px 16px}}
.card-name{{font-size:14px;font-weight:600;white-space:nowrap;
  overflow:hidden;text-overflow:ellipsis}}
.card-meta{{font-size:12px;color:#71717a;margin-top:4px}}
.card-footer{{display:flex;align-items:center;justify-content:space-between;margin-top:10px}}
.pill{{font-size:11px;font-weight:700;padding:2px 8px;
  border-radius:999px;letter-spacing:.04em}}
.rec-badge{{font-size:11px;font-weight:600;padding:2px 8px;border-radius:999px;
  background:#1d4ed822;color:#60a5fa;border:1px solid #1d4ed844}}
.diff{{font-size:12px;color:#52525b}}
.empty{{color:#52525b;grid-column:1/-1;text-align:center;padding:80px 0;font-size:14px}}
</style>
</head>
<body>
<header>
  <h1>Visual QA Library</h1>
  <span class="count">{count}</span>
</header>
<div class="grid">
{cards_html}
{empty}
</div>
</body>
</html>"""

    (report_dir / "library.html").write_text(html, encoding="utf-8")
    print(f"  Library updated   → {report_dir / 'library.html'}")


def _make_run_dir(report_dir, node_id):
    report_dir = Path(report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    node_slug = node_id.replace(":", "-")
    run_dir = report_dir / f"{timestamp}_{node_slug}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return report_dir, run_dir, timestamp


def save_run(report_dir, file_key, node_id, screen_name,
             figma_img, sim_img, diff_img, overlay_img, pct_diff, region_map):
    report_dir, run_dir, timestamp = _make_run_dir(report_dir, node_id)

    figma_img.save(run_dir / "figma-ref.png")
    sim_img.save(run_dir / "sim-current.png")
    diff_img.save(run_dir / "diff-highlighted.png")
    overlay_img.save(run_dir / "diff-overlay.png")

    verdict = get_verdict(pct_diff)
    meta = {
        "timestamp":   timestamp,
        "file_key":    file_key,
        "node_id":     node_id,
        "screen_name": screen_name or node_id,
        "pct_diff":    round(pct_diff, 2),
        "region_map":  {k: round(v, 2) for k, v in region_map.items()},
        "verdict":     verdict,
    }
    (run_dir / "meta.json").write_text(json.dumps(meta, indent=2))

    generate_run_report(run_dir, meta, figma_img, sim_img, diff_img, overlay_img)
    generate_library(report_dir)
    return run_dir


def save_inspect_run(report_dir, file_key, node_id, screen_name,
                     figma_img, sim_img, design_width):
    report_dir, run_dir, timestamp = _make_run_dir(report_dir, node_id)

    figma_img.save(run_dir / "figma-ref.png")
    sim_img.save(run_dir / "sim-current.png")

    meta = {
        "timestamp":     timestamp,
        "file_key":      file_key,
        "node_id":       node_id,
        "screen_name":   screen_name or node_id,
        "verdict":       "INSPECT",
        "design_width":  design_width,
        "captured_width": sim_img.width,
    }
    (run_dir / "meta.json").write_text(json.dumps(meta, indent=2))

    generate_inspect_report(run_dir, meta, figma_img, sim_img)
    generate_library(report_dir)
    return run_dir


def save_multipass_run(report_dir, file_key, node_id, screen_name,
                       figma_full_img, section_results, platform):
    """
    Persist all images and metadata for a multi-pass (scrollable screen) QA run,
    then generate a consolidated report and update the library index.
    """
    report_dir, run_dir, timestamp = _make_run_dir(report_dir, node_id)

    # Full Figma reference (unsliced, for reference)
    figma_full_img.save(run_dir / "figma-ref-full.png")

    # Per-section images with numbered filenames
    for i, s in enumerate(section_results, 1):
        suffix = f"s{i:02d}"
        s["figma_img"].save(run_dir / f"figma-ref-{suffix}.png")
        s["sim_img"].save(run_dir   / f"sim-{suffix}.png")
        s["diff_img"].save(run_dir  / f"diff-{suffix}.png")
        s["overlay_img"].save(run_dir / f"overlay-{suffix}.png")

    # First section's overlay becomes the library thumbnail
    section_results[0]["overlay_img"].save(run_dir / "diff-overlay.png")

    # Pixel-count-weighted average across all sections
    total_px = sum(
        s["sim_img"].width * s["sim_img"].height for s in section_results
    )
    overall_pct = (
        sum(s["pct_diff"] * s["sim_img"].width * s["sim_img"].height
            for s in section_results) / total_px
        if total_px else 0.0
    )
    overall_verdict = get_verdict(overall_pct)

    meta = {
        "timestamp":     timestamp,
        "file_key":      file_key,
        "node_id":       node_id,
        "screen_name":   screen_name or node_id,
        "pct_diff":      round(overall_pct, 2),
        "verdict":       overall_verdict,
        "mode":          "multipass",
        "section_count": len(section_results),
        "sections": [
            {
                "index":      i + 1,
                "pct_diff":   round(s["pct_diff"], 2),
                "verdict":    get_verdict(s["pct_diff"]),
                "region_map": {k: round(v, 2) for k, v in s["region_map"].items()},
            }
            for i, s in enumerate(section_results)
        ],
    }
    (run_dir / "meta.json").write_text(json.dumps(meta, indent=2))

    generate_multipass_report(run_dir, meta, section_results)
    generate_library(report_dir)
    return run_dir, overall_pct


# ── Terminal report ───────────────────────────────────────────────────────────

def print_report(pct_diff, region_map, report_dir=None, run_dir=None):
    def bar(pct):
        filled = int(pct / 100 * 30)
        return "[" + "█" * filled + "░" * (30 - filled) + f"] {pct:5.1f}%"

    print("\n" + "=" * 60)
    print("  SCREENSHOT DIFF REPORT")
    print("=" * 60)
    print(f"  Overall (content area): {bar(pct_diff)}\n")
    for region, pct in region_map.items():
        print(f"  {region.capitalize()} third:         {bar(pct)}")
    print("=" * 60)

    verdict_text = {
        "PASS":   "PASS  — very close match",
        "REVIEW": "REVIEW  — minor differences (font AA, shadows, sub-pixel)",
        "FAIL":   "FAIL  — notable differences, review the diff image",
    }[get_verdict(pct_diff)]

    print(f"  Verdict:       {verdict_text}")
    print(f"  Diff image →   {DIFF_PATH}")
    print(f"  Side-by-side → {DIFF_OVERLAY_PATH}")
    if run_dir:
        print(f"  Run report →   {run_dir}/report.html")
    if report_dir:
        print(f"  Library →      {report_dir}/library.html")
    print("=" * 60 + "\n")


def print_inspect_report(design_width, captured_width, report_dir=None, run_dir=None):
    print("\n" + "=" * 60)
    print("  RESPONSIVE INSPECTION REPORT")
    print("=" * 60)
    print(f"  Figma design:  {design_width}px wide")
    print(f"  Captured:      {captured_width}px wide")
    print(f"  Pixel diff:    not run (widths differ)")
    print("=" * 60)
    print("  Use the Figma reference and app screenshot for visual")
    print("  inspection against the responsive checklist.")
    if run_dir:
        print(f"  Report →       {run_dir}/report.html")
    if report_dir:
        print(f"  Library →      {report_dir}/library.html")
    print("=" * 60 + "\n")


def print_multipass_report(section_results, overall_pct, report_dir=None, run_dir=None):
    def bar(pct):
        filled = int(pct / 100 * 30)
        return "[" + "█" * filled + "░" * (30 - filled) + f"] {pct:5.1f}%"

    print("\n" + "=" * 60)
    print("  MULTI-PASS SCREENSHOT DIFF REPORT")
    print("=" * 60)
    for i, s in enumerate(section_results, 1):
        print(f"  Section {i}:              {bar(s['pct_diff'])}")
    print(f"\n  Overall (weighted avg): {bar(overall_pct)}\n")
    print("=" * 60)

    verdict_text = {
        "PASS":   "PASS  — very close match across all sections",
        "REVIEW": "REVIEW  — minor differences in one or more sections",
        "FAIL":   "FAIL  — notable differences, review the diff images",
    }[get_verdict(overall_pct)]

    print(f"  Verdict:     {verdict_text}")
    if run_dir:
        print(f"  Run report → {run_dir}/report.html")
    if report_dir:
        print(f"  Library →    {report_dir}/library.html")
    print("=" * 60 + "\n")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Compare a Figma design against a live app or browser screenshot."
    )
    parser.add_argument("file_key", help="Figma file key (from the URL)")
    parser.add_argument("node_id",  help="Figma node ID, colon-separated (e.g. 123:456)")
    parser.add_argument(
        "--platform",
        choices=["ios", "android", "web"],
        default="ios",
        help="Screenshot source platform (default: ios)"
    )
    parser.add_argument(
        "--design-width",
        type=int,
        default=390,
        metavar="N",
        help=(
            "Figma frame width in logical points (default: 390 for iPhone). "
            "Use 360 for most Android phones, or the actual Figma frame width for web."
        )
    )
    parser.add_argument(
        "--web-screenshot",
        metavar="PATH",
        help="Path to a pre-captured PNG to use as the app screenshot (web or MCP-captured iOS)"
    )
    parser.add_argument(
        "--skip-capture",
        action="store_true",
        help=(
            "Skip the screenshot capture step entirely. "
            "Use when the screenshot was already saved to /tmp/sim-current.png "
            "by an external tool such as XcodeBuildMCP."
        )
    )
    parser.add_argument(
        "--screen-name",
        metavar="NAME",
        default="",
        help='Human-readable label for the report (e.g. "Contact Detail - Default")'
    )
    parser.add_argument(
        "--report-dir",
        metavar="PATH",
        default=str(REPORT_DIR_DEFAULT),
        help=f"Directory for the run report and library (default: {REPORT_DIR_DEFAULT})"
    )
    parser.add_argument(
        "--inspect-only",
        action="store_true",
        help=(
            "Skip pixel diff. Downloads Figma reference for visual comparison, "
            "saves a side-by-side report, logs as INSPECT in the library. "
            "Use when the screen width differs from the Figma design width."
        )
    )
    parser.add_argument(
        "--sections",
        nargs="+",
        metavar="PATH",
        help=(
            "Paths to pre-captured section screenshots, ordered top-to-bottom. "
            "Triggers multi-pass mode: the Figma full-height frame is sliced into "
            "viewport-height chunks and each pair is diffed independently. "
            "Results are combined into one library card and report."
        )
    )
    args = parser.parse_args()

    token = read_token()

    print(f"1/4  Downloading Figma screenshot  (node {args.node_id})...")
    download_figma_screenshot(args.file_key, args.node_id, token)

    # ── Multi-pass scrollable screen mode ─────────────────────────────────────
    if args.sections:
        figma_full = Image.open(FIGMA_REF_PATH)
        n = len(args.sections)
        print(f"2/4  Loading {n} section screenshot{'s' if n != 1 else ''}...")
        section_imgs = []
        for p in args.sections:
            path = Path(p)
            if not path.exists():
                print(f"ERROR: Section screenshot not found: {p}")
                sys.exit(1)
            section_imgs.append(Image.open(path))

        platform_key = "web" if args.platform == "web" else args.platform
        skip_top_frac, skip_bottom_frac = SKIP_FRACTIONS.get(platform_key, (0.07, 0.04))

        print(f"3/4  Slicing Figma reference into {n} section{'s' if n != 1 else ''} "
              f"and diffing  (design width: {args.design_width}pt)...")
        pairs = slice_figma_to_sections(figma_full, section_imgs, args.design_width)

        section_results = []
        for figma_slice, sim_section in pairs:
            diff_img, pct_diff, region_map = build_diff(
                figma_slice, sim_section, DIFF_THRESHOLD,
                skip_top_frac, skip_bottom_frac
            )
            overlay_img = build_side_by_side(figma_slice, sim_section, diff_img)
            section_results.append({
                "figma_img":   figma_slice,
                "sim_img":     sim_section,
                "diff_img":    diff_img,
                "overlay_img": overlay_img,
                "pct_diff":    pct_diff,
                "region_map":  region_map,
            })

        print("4/4  Saving multi-pass report...")
        run_dir, overall_pct = save_multipass_run(
            report_dir      = args.report_dir,
            file_key        = args.file_key,
            node_id         = args.node_id,
            screen_name     = args.screen_name,
            figma_full_img  = figma_full,
            section_results = section_results,
            platform        = platform_key,
        )
        print_multipass_report(
            section_results = section_results,
            overall_pct     = overall_pct,
            report_dir      = args.report_dir,
            run_dir         = run_dir,
        )
        return

    # ── Single-screenshot modes ────────────────────────────────────────────────
    if args.skip_capture:
        if not Path(SIM_PATH).exists():
            print(f"ERROR: --skip-capture was set but no screenshot found at {SIM_PATH}.")
            print("  Capture the screenshot first (e.g. via XcodeBuildMCP 'screenshot' tool),")
            print(f"  save it to {SIM_PATH}, then re-run.")
            sys.exit(1)
        if args.web_screenshot:
            print("  Note: --web-screenshot is ignored when --skip-capture is set.")
        print(f"2/4  Using pre-captured screenshot at {SIM_PATH}  (--skip-capture)")
    elif args.web_screenshot:
        print(f"2/4  Using pre-captured screenshot from {args.web_screenshot}...")
        capture_web(args.web_screenshot)
    else:
        print(f"2/4  Capturing {args.platform} screenshot...")
        if args.platform == "ios":
            capture_ios()
        elif args.platform == "android":
            capture_android()
        else:
            capture_web(args.web_screenshot)

    figma_img = Image.open(FIGMA_REF_PATH)
    sim_img   = Image.open(SIM_PATH)

    if args.inspect_only:
        print("3/4  Inspect mode — skipping pixel diff...")
        print("4/4  Saving report...")
        run_dir = save_inspect_run(
            report_dir   = args.report_dir,
            file_key     = args.file_key,
            node_id      = args.node_id,
            screen_name  = args.screen_name,
            figma_img    = figma_img,
            sim_img      = sim_img,
            design_width = args.design_width,
        )
        print_inspect_report(
            design_width   = args.design_width,
            captured_width = sim_img.width,
            report_dir     = args.report_dir,
            run_dir        = run_dir,
        )
    else:
        print(f"3/4  Generating diff  (design width: {args.design_width}pt)...")
        figma_img, sim_img = normalize_images(figma_img, sim_img, args.design_width)

        platform_key = "web" if (args.platform == "web" or args.web_screenshot) else args.platform
        skip_top_frac, skip_bottom_frac = SKIP_FRACTIONS.get(platform_key, (0.07, 0.04))
        diff_img, pct_diff, region_map = build_diff(
            figma_img, sim_img, DIFF_THRESHOLD, skip_top_frac, skip_bottom_frac
        )
        overlay_img = build_side_by_side(figma_img, sim_img, diff_img)

        diff_img.save(DIFF_PATH)
        overlay_img.save(DIFF_OVERLAY_PATH)

        print("4/4  Saving report...")
        run_dir = save_run(
            report_dir  = args.report_dir,
            file_key    = args.file_key,
            node_id     = args.node_id,
            screen_name = args.screen_name,
            figma_img   = figma_img,
            sim_img     = sim_img,
            diff_img    = diff_img,
            overlay_img = overlay_img,
            pct_diff    = pct_diff,
            region_map  = region_map,
        )
        print_report(pct_diff, region_map, report_dir=args.report_dir, run_dir=run_dir)


if __name__ == "__main__":
    main()

---
name: visual-qa
description: Compares a live app screen against its Figma design using pixel-level diffing, and inspects layouts at different screen widths. Use when asked to "compare this screen to Figma", "run visual QA", "screenshot comparison", "design review", "check if this matches the design", "does this look right", "how does this look on a different device", "test responsive layout", or "check a different breakpoint". Supports iOS Simulator, Android Emulator, and web browsers.
---

# Visual QA — Figma vs Live App

Pixel-level diff between a Figma design and the running app, followed by a detailed UI element checklist.

## Prerequisites

Check these before starting. Tell the user what's missing rather than failing silently.

| Requirement | How to check | Fix |
|-------------|--------------|-----|
| Figma token | `cat ~/.figma_token` | Create `~/.figma_token` with a Figma personal access token (Figma Settings → Security → Personal access tokens), or `export FIGMA_TOKEN=...` |
| Pillow | `python3 -c "import PIL"` | `pip3 install Pillow` |
| iOS capture | `which xcrun` | Built into macOS — if missing, install Xcode |
| Android capture | `which adb` | Install Android SDK / Android Studio |

### Optional: XcodeBuildMCP (iOS only — recommended)

If **XcodeBuildMCP** is active as an MCP server in this session, use it for iOS screenshots instead of `xcrun`. It gives the agent direct screenshot and UI automation access without a shell command.

To install (one-time):
```bash
brew tap getsentry/xcodebuildmcp
brew install xcodebuildmcp
```

Then add to `~/.cursor/mcp.json` under `mcpServers` — use the **full path** (Cursor doesn't inherit terminal PATH):
```json
"XcodeBuildMCP": {
  "command": "/opt/homebrew/bin/xcodebuildmcp",
  "args": ["mcp"]
}
```

The user must also grant **Accessibility** and **Screen Recording** permissions to Cursor in System Settings → Privacy & Security. Without these, XcodeBuildMCP cannot tap or capture screenshots.

Restart Cursor after adding it. Check availability in a session with the `doctor` tool.

---

## Step 1 — Detect platform

Check the project root:

| Files present | Platform |
|---------------|----------|
| `*.xcodeproj` or `*.xcworkspace` (no `android/`) | iOS |
| `build.gradle` or `gradlew` (no `ios/`) | Android |
| `android/` **and** `ios/` both present | React Native → ask user which is running |
| `package.json` + `next.config.*` / `vite.config.*` / `index.html` | Web |

If still ambiguous, ask the user.

---

## Step 2 — Get Figma node info

You need two values from the Figma URL:

```
figma.com/design/<fileKey>/...?node-id=<nodeId>
```

- **fileKey** — the long alphanumeric string after `/design/`
- **nodeId** — the `node-id` query param; convert dashes to colons (`123-456` → `123:456`)

If not already in context, ask the user to paste the Figma URL for the exact frame to compare.

---

## Step 3 — Verify the script exists

```bash
ls ~/.cursor/skills/visual-qa/compare-screenshots.py
```

If missing, tell the user to reinstall the `visual-qa` skill.

---

## Step 4 — Capture and diff

Always pass `--screen-name` with a short human-readable label — it appears in the report and library (e.g. `"Contact Detail - Default"`).

### iOS Simulator

**If XcodeBuildMCP is active**, use it to capture — this is preferred over the shell fallback:

1. Call the `screenshot` MCP tool with output path `/tmp/sim-current.png`
2. Then run the diff script with `--skip-capture`:

```bash
python3 ~/.cursor/skills/visual-qa/compare-screenshots.py <fileKey> <nodeId> \
  --skip-capture \
  --screen-name "Screen Name"
```

**If XcodeBuildMCP is not available**, fall back to xcrun:

```bash
python3 ~/.cursor/skills/visual-qa/compare-screenshots.py <fileKey> <nodeId> \
  --platform ios \
  --screen-name "Screen Name"
```

The Simulator must be running and showing the correct screen.

### Android Emulator

```bash
python3 ~/.cursor/skills/visual-qa/compare-screenshots.py <fileKey> <nodeId> \
  --platform android \
  --screen-name "Screen Name"
```

The Emulator must be running and showing the correct screen.

### Web (browser)

#### 1. Get the Figma frame width

Check the Figma design panel (W field on the selected frame), or call `get_metadata` on the node. This determines both the viewport width to set and the `--design-width` value to pass the script.

Common breakpoints:

| Figma frame width | Breakpoint |
|-------------------|------------|
| 1440px | Desktop |
| 1280px | Laptop |
| 768px | Tablet |
| 375px or 390px | Mobile web |

#### 2. Resize the browser to match

Use `browser_resize` to set the viewport width to the Figma frame width before capturing. Use a tall height (e.g. 900px) — it doesn't affect the full-page capture.

```
browser_resize: { width: <figmaFrameWidth>, height: 900 }
```

#### 3. Navigate and capture

Navigate to the correct page/state, then capture using `browser_take_screenshot` with `fullPage: true` — this captures the entire scrollable page height in one shot, matching how Figma exports a full frame.

```
browser_take_screenshot: { fullPage: true, filename: "/tmp/sim-current.png" }
```

#### 4. Run the diff

```bash
python3 ~/.cursor/skills/visual-qa/compare-screenshots.py <fileKey> <nodeId> \
  --platform web \
  --web-screenshot /tmp/sim-current.png \
  --design-width <figmaFrameWidth> \
  --screen-name "Page Name — Desktop"
```

#### Section-specific captures (optional)

If you only want to compare one section of a page (e.g. the hero, or a card component), use the Figma node ID for that specific frame/component rather than the whole page, and capture the viewport without `fullPage`:

1. Use `browser_scroll` to scroll the target section into view
2. Capture with `browser_take_screenshot` (no `fullPage`)
3. Run the diff against the section's Figma node ID

This is useful when a page is too long to diff meaningfully in one pass, or when comparing an individual component.

### React Native

Use whichever platform the user confirmed is running (iOS or Android command above).

---

## Step 5 — Display images and open library

Read and display all four output files inline in the chat:

- `/tmp/figma-ref.png` — Figma reference
- `/tmp/sim-current.png` — live app
- `/tmp/diff-highlighted.png` — red pixels = differences
- `/tmp/diff-overlay.png` — 3-panel side-by-side

Then open the library in the browser so the user can view the full report. Use the `cursor-ide-browser` MCP tool to navigate to:

```
~/.visual-qa-reports/library.html
```

The library shows a card grid of all past runs — each card links to a self-contained report with the 4 images, diff score, and region breakdown. Every new run automatically appends a new card and updates the library.

---

## Step 6 — Checklist

For every item below, state **PASS**, **FAIL**, or **N/A** with a specific observation. Never write "looks good" — state the actual value (color hex, px size, etc.) vs. what Figma shows.

### Header
- [ ] Background color matches Figma (state the hex)
- [ ] Title: text content, font size, font weight
- [ ] Back/close button: icon present, correct size
- [ ] Padding top (status bar / Dynamic Island to first content)
- [ ] Padding bottom

### Avatar (if present)
- [ ] Circle diameter
- [ ] Background color (exact hex)
- [ ] Icon asset: correct image (initials / person / other)
- [ ] Icon size and color within circle
- [ ] Indicator badge: size, fill vs outline style, color, icon

### Text block
- [ ] Each line: content, font size, font weight, color, alignment
- [ ] Line spacing

### Badges / tags
- [ ] Present/absent matches Figma
- [ ] Background color, text, font size
- [ ] Padding and corner radius

### Action row (if present)
- [ ] Number of buttons, width, height, gap between them
- [ ] Button background color
- [ ] Icon: correct asset, size, color, orientation (flag horizontal flips)
- [ ] Label: text, font size, font weight, color
- [ ] Top padding above the row

### Cards (evaluate each card)
- [ ] Present/absent matches Figma
- [ ] Title and body: font size, weight, color
- [ ] Internal padding (all 4 sides)
- [ ] Background color, corner radius
- [ ] Gap to next card

### Dividers
- [ ] Present between correct rows (not after the last row)
- [ ] Thickness, color

### Global
- [ ] Elements visible in Figma but missing from app
- [ ] Elements in app absent from Figma
- [ ] Outer horizontal padding (left and right)
- [ ] Vertical gap between major sections

---

## Step 7 — Results table

```
| Element                | Status | Notes                              |
|------------------------|--------|------------------------------------|
| Header background      | PASS   | #1A1A2E matches                    |
| Avatar size            | FAIL   | 48pt in app, 72pt in Figma         |
| Action row gap         | REVIEW | 12pt app vs 16pt Figma             |
```

---

## Step 8 — Add recommendations to report

For every **FAIL** and **REVIEW** item in the results table, write a recommendation. Since engineers may be working from specs rather than the codebase, be specific about the component, property, and the exact value from the Figma design.

Write the recommendations to `/tmp/qa-recommendations.json` in this format:

```json
[
  {
    "element": "Avatar",
    "status": "FAIL",
    "observation": "48pt diameter in app, 72pt in Figma",
    "recommendation": "Increase the avatar circle diameter to 72pt. Figma specifies W=72 H=72 with a circular clip."
  },
  {
    "element": "Action row gap",
    "status": "REVIEW",
    "observation": "12pt gap between buttons in app, 16pt in Figma",
    "recommendation": "Increase the spacing between action buttons to 16pt."
  }
]
```

Then run:

```bash
python3 ~/.cursor/skills/visual-qa/update-report.py \
  --recommendations /tmp/qa-recommendations.json
```

This injects a collapsible recommendations section into the report (hidden by default, with show/hide toggles and an "Export as Markdown" button), and adds a recommendations indicator to the library card. If no `--run-dir` is given, it updates the most recent run automatically.

---

## Step 9 — Fix and re-verify loop

If any items **FAIL**:

1. Fix the code
2. Re-run Step 4
3. Re-display images (Step 5)
4. Re-evaluate only the previously failed items
5. Update the results table
6. Re-run Step 8 with updated recommendations
7. Repeat until all non-N/A items are **PASS** or **REVIEW**

Do not declare a screen done while any item is **FAIL**.

---

## Interaction flow QA (iOS only, requires XcodeBuildMCP)

Use this when verifying screens reachable only after a tap, or multiple states of the same screen (e.g. empty vs filled). **Read `~/.cursor/skills/visual-qa/reference.md` → "Interaction flow QA" for the full workflow, tool list, and animation review instructions before proceeding.**

---

## Responsive Inspection mode

Use this when the screen width you're testing **differs from the Figma design width** (e.g. a 390pt design on a 375pt device, or a 1440px design tested at 1024px). Pixel diff is skipped — the agent evaluates against a responsive checklist instead. **Read `~/.cursor/skills/visual-qa/reference.md` → "Responsive Inspection mode" for the full web/iOS workflows, checklist, and results table format before proceeding.**

---

## Scoring reference

| Diff % | Script verdict |
|--------|----------------|
| < 2% | PASS — very close match |
| 2–8% | REVIEW — minor differences (font AA, shadows, sub-pixel) |
| 8–20% | FAIL — notable differences |
| > 20% | FAIL — significant differences |

On mobile (iOS / Android), the script skips the top 7% (status bar) and bottom 4% (home indicator) from scoring, since those contain OS-rendered UI that will always differ. On web, no regions are skipped (0% / 0%).

---

## Important notes

### Always use the skill's script

Always run `~/.cursor/skills/visual-qa/compare-screenshots.py` — never a local `scripts/compare-screenshots.py` or similar file within the project. If a project has an older local copy, ignore it and use the skill's version.

### Project-level rule files

If a project has a `.cursor/rules/` file that references this skill (e.g. a `screenshot-comparison.mdc`), that file must have `alwaysApply: true` in its frontmatter to take effect automatically. If set to `false` with no globs, the agent will not see the rule.

### Restart and new chat required for config changes

MCP servers, permissions, and rule files are loaded when Cursor starts. If any of these change, the user must **restart Cursor**. Additionally, the agent caches context within a conversation — always **start a new chat** after config changes to ensure they take effect.

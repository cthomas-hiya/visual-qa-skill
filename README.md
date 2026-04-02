# Visual QA Skill for Cursor

This is an AI agent skill that compares your live app against a Figma design — automatically. Point the agent at a Figma frame and it captures a screenshot of your running app, runs a pixel-level comparison, and generates a browsable HTML report with the diff images, a scored verdict, and a checklist of what to fix.

**What you get:** screenshot → Figma comparison → browser report with recommendations you can share with your engineering team.

---

## What you'll need

| What | Why you need it |
|------|-----------------|
| [Cursor IDE](https://cursor.com) | Runs the AI agent |
| Figma account + personal access token | Downloads your design frames for comparison |
| Python 3 | Runs the comparison script (comes pre-installed on macOS) |
| Pillow (Python library) | Does the pixel-level math |
| **iOS:** Xcode | Runs the iOS Simulator |
| **Android:** Android Studio | Runs the Android Emulator |
| **Web:** nothing extra | Cursor has a built-in browser |

---

## Installation

**Step 1 — Copy the skill files**

Clone this repo or manually copy all 4 files into `~/.cursor/skills/visual-qa/`:

```bash
git clone https://github.com/cthomas-hiya/visual-qa-skill.git ~/.cursor/skills/visual-qa
```

The 4 files are:
- `SKILL.md` — the AI agent's instruction file
- `reference.md` — extended checklists the agent reads when needed
- `compare-screenshots.py` — the main diff script
- `update-report.py` — injects recommendations into your reports

**Step 2 — Get a Figma personal access token**

1. Open Figma and go to **Settings → Security → Personal access tokens**
2. Create a new token and copy it
3. Save it to a file: `echo "your-token-here" > ~/.figma_token`

**Step 3 — Install Pillow**

```bash
pip3 install Pillow
```

**Step 4 — iOS only (recommended): Install XcodeBuildMCP**

XcodeBuildMCP lets the agent take its own screenshots from the iOS Simulator without you doing anything. It also enables interaction testing (tapping through flows) and animation recording.

```bash
brew tap getsentry/xcodebuildmcp
brew install xcodebuildmcp
```

Then open `~/.cursor/mcp.json` and add this under `mcpServers`:

```json
"XcodeBuildMCP": {
  "command": "xcodebuildmcp",
  "args": ["mcp"]
}
```

Restart Cursor after saving.

---

## How to find your Figma URL details

Every QA command needs a Figma URL. Here's how to read it:

```
https://www.figma.com/design/AbCdEfGhIjKl/My-App?node-id=123-456
                              ^^^^^^^^^^^^                  ^^^^^^^
                              fileKey                       nodeId
```

- **fileKey** — the string after `/design/` (before the next `/`)
- **nodeId** — the `node-id` query parameter; **convert dashes to colons** when passing it to commands (`123-456` → `123:456`)

To get the URL for a specific frame: select it in Figma, then right-click → **Copy link to selection**.

---

## Cheat sheet

Make sure you're in **Agent mode** in Cursor (not Ask mode) before running any of these.

### Standard QA — pixel diff

Use these when your app is running and you want a scored comparison against a Figma frame.

| Say this | What happens |
|----------|--------------|
| `"Compare this screen to Figma — [Figma URL]"` | Full QA run: screenshot, diff, checklist, report |
| `"Run visual QA on the profile screen — [Figma URL]"` | Same, with a descriptive label in the report |
| `"Does this match the design? [Figma URL]"` | Same |

> **Tip:** Name the screen in your prompt and the agent uses it as the label in the report library — e.g. `"Compare the Contact Detail screen to Figma — [URL]"` → report is labeled "Contact Detail".

*Example use case: You've just built the onboarding screen and want to confirm spacing, colors, and typography match before handing off to QA.*

---

### Responsive inspection — different screen widths

Use these when you want to check a design at a width different from the Figma frame — for example, a 390pt iPhone 14 design on a 375pt iPhone SE, or a 1440px desktop design at 1200px. No pixel score is calculated; the agent evaluates a layout checklist instead.

| Say this | What happens |
|----------|--------------|
| `"How does this look on an iPhone SE? [Figma URL]"` | Captures at iPhone SE width, side-by-side report |
| `"Check this at 1200px wide — [Figma URL]"` | Resizes browser to 1200px, compares to Figma frame |
| `"Test the tablet breakpoint — [Figma URL]"` | 768px viewport capture, responsive checklist |

*Example use case: Your Figma design is for iPhone 14 but you want to verify nothing overflows or breaks on an older, smaller device.*

---

### Interaction and state QA — screens reached by tapping (iOS only)

Use these when the screen you want to test is only visible after a user interaction, or when you have multiple states to compare (empty, filled, error, etc.). Requires XcodeBuildMCP.

| Say this | What happens |
|----------|--------------|
| `"QA the state after tapping Send — [Figma URL for that state]"` | Agent taps, captures, diffs |
| `"Compare the empty state to Figma — [Figma URL]"` | Navigates to empty state, runs QA |
| `"Check the error state against the design — [Figma URL]"` | Triggers error, captures, diffs |

*Example use case: A bottom sheet appears after the user taps a card. Compare it to the Figma frame for that sheet, without you having to manually navigate there.*

---

### Animation review (iOS only)

Use these when you want to verify a transition or animation matches the Figma prototype. The agent records a video and gives you a qualitative assessment — it can't score animations, but it can describe what it sees vs. what the prototype specifies.

| Say this | What happens |
|----------|--------------|
| `"Record the transition and check it against the prototype"` | Records the interaction as video, describes it |
| `"Does this loading animation match the Figma prototype?"` | Records, compares to prototype description |

*Example use case: You want to confirm that a screen-to-screen transition is a 300ms slide rather than a fade.*

---

### Recommendations and sharing

After every QA checklist, the agent automatically writes recommendations for every failing item. These appear in the report as a hidden section — click "Show all" to expand them.

| Say this / do this | What happens |
|--------------------|--------------|
| Recommendations are added automatically | Agent writes them after every checklist |
| Click **"Export as Markdown ↓"** in the report | Downloads a `.md` file with all recommendations |

The exported markdown file is ready to paste into a Jira ticket, GitHub issue, or Slack message. It lists every failing item with the observation and a specific fix recommendation.

---

## Your report library

Every QA run is saved as a self-contained HTML report and added to a browsable library.

- **Where it lives:** `~/.visual-qa-reports/library.html`
- **What's in it:** A card for each run showing the screen name, timestamp, verdict badge, and (if recommendations were written) a count badge
- **How to open it:** Cursor opens it automatically after each run. You can also open it manually in any browser — it's a plain HTML file

Each card links to a full report with all 4 comparison images (Figma reference, app screenshot, diff highlights, and side-by-side), the diff score, and the recommendations section.

---

## Understanding the results

### Pixel-diff runs (standard QA)

| Verdict | Diff % | What it means |
|---------|--------|---------------|
| **PASS** | < 2% | Very close match — likely just font rendering differences |
| **REVIEW** | 2–8% | Minor differences — shadows, anti-aliasing, sub-pixel rendering; worth a look |
| **FAIL** | > 8% | Notable differences — the agent will identify what's off |

On **mobile** (iOS and Android), the top ~7% of the screenshot (status bar) and bottom ~4% (home indicator) are excluded from scoring — these are OS-rendered and will always look different. On **web**, no regions are excluded.

### Responsive inspection runs

| Verdict | What it means |
|---------|---------------|
| **INSPECT** | No score calculated — the report shows a side-by-side view for manual review against the responsive checklist |

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| "No Figma token found" | Check that `~/.figma_token` exists and contains your token (`cat ~/.figma_token`) |
| "Pillow not installed" | Run `pip3 install Pillow` |
| "iOS capture failed" | Make sure the iOS Simulator is open and a device is booted |
| "No image URL returned" | The node ID may still have dashes — convert to colons (`123-456` → `123:456`) |
| Agent doesn't run commands | This skill requires **Agent mode** in Cursor. Look for the mode selector in the chat panel and switch from Ask to Agent |
| XcodeBuildMCP not found | Run `brew install xcodebuildmcp`, add it to `~/.cursor/mcp.json`, and restart Cursor |

---

## Appendix — Using this skill in other IDEs

The two Python scripts and the HTML report library work in any environment. Only the `SKILL.md` agent instructions are Cursor-specific.

### What's portable

| File / thing | Portable? | Notes |
|--------------|-----------|-------|
| `compare-screenshots.py` | Yes | Plain Python — run from any terminal |
| `update-report.py` | Yes | Plain Python — run from any terminal |
| `reference.md` | Yes | Extended checklists and workflows — content is IDE-agnostic |
| `~/.visual-qa-reports/` library | Yes | Standard HTML — open in any browser |
| `SKILL.md` | Cursor-specific | See adaptations below for other IDEs |
| `cursor-ide-browser` MCP (web screenshots) | Cursor-specific | Other IDEs need their own browser tool |
| XcodeBuildMCP | Any MCP-compatible IDE | Works in Claude Code, Windsurf, and others |

### Claude Code

Claude Code reads custom instructions from a `CLAUDE.md` file in your project root, or globally from `~/.claude/CLAUDE.md`.

1. Copy the body of `SKILL.md` (everything after the `---` frontmatter block) into your `CLAUDE.md`
2. Keep `reference.md` in the same folder as the Python scripts — the instructions tell the agent to read it for interaction flow and responsive inspection workflows
3. The Python scripts and report library work identically

### Windsurf

Windsurf reads custom instructions from its Memories panel or a `.windsurfrules` file.

1. Paste the body of `SKILL.md` into your Windsurf instructions
2. Keep `reference.md` alongside the Python scripts so the agent can find it when the instructions reference it
3. The Python scripts run unchanged via Windsurf's terminal access

### Any other AI IDE

If your IDE lets the agent run shell commands:

1. Paste the workflow steps from `SKILL.md` into your IDE's custom instructions or system prompt
2. Keep all 4 files together (`SKILL.md`, `reference.md`, `compare-screenshots.py`, `update-report.py`) — `SKILL.md` references `reference.md` for extended workflows
3. For web screenshots: use whatever browser tool your IDE supports, or capture manually and pass the path via `--web-screenshot`
4. The report library opens in any browser regardless of which IDE generated it

The diff algorithm, scoring, HTML reports, and recommendations system all live in the two Python scripts and are completely IDE-agnostic.

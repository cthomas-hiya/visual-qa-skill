# Visual QA — Reference

Extended workflows referenced by the main `SKILL.md`. The agent should read this file when it encounters the relevant trigger.

---

## Interaction flow QA (iOS only, requires XcodeBuildMCP)

Use this when you need to verify a screen that's only reachable after a tap, or to QA multiple states of the same screen (e.g. empty vs filled, default vs error).

### Tools available (XcodeBuildMCP)

| Tool | Use for |
|------|---------|
| `snapshot_ui` | Dump the accessibility tree to find element labels and coordinates before tapping |
| `tap` | Tap by accessibility label (preferred) or x/y coordinates |
| `swipe` | Scroll a list or swipe between screens |
| `long_press` | Long press at coordinates |
| `screenshot` | Capture the current simulator state |
| `record_sim_video` | Record a transition or animation as video for manual review |

### Workflow

1. **Identify the target element** — call `snapshot_ui` to get a list of visible accessibility elements and their coordinates
2. **Perform the interaction** — call `tap` (by label if possible, coordinates as fallback) or `swipe`
3. **Wait for the transition to settle** — wait 0.5–1 second after the tap before capturing
4. **Capture the result** — call `screenshot` with output path `/tmp/sim-current.png`
5. **Run the diff** against the Figma "after" state frame (get the node ID for that specific state):

```bash
python3 ~/.cursor/skills/visual-qa/compare-screenshots.py <fileKey> <afterStateNodeId> \
  --skip-capture \
  --screen-name "Screen Name — After Tap"
```

6. **Display and evaluate** as normal (Steps 5–7 in SKILL.md)
7. Repeat for each state or interaction you need to verify

### Animation review

Animations cannot be automatically scored. For transitions or loading states:

1. Call `record_sim_video` to start recording
2. Trigger the interaction with `tap` or `swipe`
3. Call `record_sim_video` again to stop (or wait for it to auto-stop)
4. Display the video and make a qualitative call — describe what you see vs. what the Figma prototype specifies (timing, easing, direction)

Flag animation issues as **REVIEW** in the results table with a specific observation (e.g. "transition appears instant; Figma prototype shows 300ms slide-in from right").

---

## Responsive Inspection mode

Use this when the screen width you're testing **differs from the Figma design width** — for example:
- iPhone 14 design (390pt) tested on an iPhone 14 Pro (393pt) or iPhone SE (375pt)
- Desktop design (1440px) tested at 1200px or 1024px
- Any breakpoint you don't have a specific Figma frame for

Pixel diff is **not run** in this mode — layout reflow makes it meaningless. Instead, the agent captures both images, places them side-by-side in the report, and evaluates the screen against the responsive checklist below.

### Web workflow

1. **Resize the browser** to the target width you want to test:
   ```
   browser_resize: { width: <targetWidth>, height: 900 }
   ```
2. **Capture** the full page:
   ```
   browser_take_screenshot: { fullPage: true, filename: "/tmp/sim-current.png" }
   ```
3. **Run in inspect mode**, passing the *Figma* design width as `--design-width` (for the reference image) and a label that includes both widths:
   ```bash
   python3 ~/.cursor/skills/visual-qa/compare-screenshots.py <fileKey> <nodeId> \
     --platform web \
     --web-screenshot /tmp/sim-current.png \
     --design-width <figmaFrameWidth> \
     --inspect-only \
     --screen-name "Home Page — 1200px"
   ```

### iOS workflow

1. **Boot the target simulator** — ask the user to select the device in Xcode or via `list_sims` + `boot_sim` in XcodeBuildMCP
2. **Capture** using XcodeBuildMCP `screenshot` tool (output `/tmp/sim-current.png`) or xcrun fallback
3. **Run in inspect mode**:
   ```bash
   python3 ~/.cursor/skills/visual-qa/compare-screenshots.py <fileKey> <nodeId> \
     --skip-capture \
     --design-width 390 \
     --inspect-only \
     --screen-name "Contact Detail — iPhone SE"
   ```

### Responsive checklist

Evaluate each item as **PASS**, **FAIL**, or **N/A**. No pixel scores — describe what you observe.

#### Layout
- [ ] No horizontal overflow or unexpected scrollbar at this width
- [ ] Grid/columns adapt correctly (e.g. 3-col → 2-col → 1-col)
- [ ] Navigation adapts (hamburger menu, collapsed tabs, etc.)
- [ ] Hero / banner scales without cropping key content
- [ ] No elements collide or overlap

#### Typography
- [ ] No text truncation or unintended clipping
- [ ] Text wraps at natural break points (not mid-word or mid-phrase)
- [ ] Line lengths remain readable (not too wide or too narrow)
- [ ] Heading hierarchy still visually clear at this width

#### Spacing
- [ ] Padding and margins scale proportionally
- [ ] Section spacing still visually separates content
- [ ] No section feels cramped or excessively sparse

#### Interactive elements
- [ ] Tap/click targets still adequately sized (min 44pt iOS / 48px web)
- [ ] Buttons and CTAs still prominent and not squeezed
- [ ] Form inputs usable at this width

#### Images and media
- [ ] Images scale without distortion or unintended cropping
- [ ] Aspect ratios preserved

#### Mobile-specific (if applicable)
- [ ] Safe area / notch / Dynamic Island handled correctly on target device
- [ ] Bottom tab bar or navigation fits correctly on screen

### Results table for inspect mode

```
| Element              | Status | Observation                               |
|----------------------|--------|-------------------------------------------|
| Navigation           | PASS   | Collapses to hamburger at 1200px          |
| Hero image           | FAIL   | Crops faces at 1200px — needs art-direction |
| Body text line length | REVIEW | Lines reach ~100 chars — slightly wide    |
```

# Design

Visual system for the Waypoint portal. Direction: **Modernist / International
Typographic Style**, applied to data reporting. Reference lane: Observable,
Datawrapper, Müller-Brockmann grids. Structure comes from typography, rules and
whitespace; never from boxes, shadows or decorative color.

## Theme

**Light portal, dark media canvas.** Not a preference, a functional split.

The scene: a store manager reading checkout numbers on a back-office desktop
under bright fluorescent light, standing, between floor walks. That forces a
light, high-contrast, paper-like reading surface. The portal does not follow
`prefers-color-scheme`; it is light on purpose.

The exception is any surface whose subject is video or heat imagery. Live
camera views, the grid wall, and heatmap canvases sit on near-black, because
video and heat gradients need a dark surround to read correctly. Scoped with
`.canvas`, never applied to reading surfaces.

## Color

Strategy: **Restrained.** Tinted warm neutrals, one ultramarine accent used only
for primary actions, current selection, focus and links. Never for decoration.

All values OKLCH. No pure `#000` or `#fff`; every neutral is warmed toward hue 70–85.

| Token | Value | Role |
|---|---|---|
| `--paper` | `oklch(0.981 0.004 85)` | Page ground |
| `--surface` | `oklch(0.998 0.002 85)` | Raised areas, table headers, inputs |
| `--ink` | `oklch(0.21 0.012 70)` | Body text, headings, heavy rules |
| `--ink-muted` | `oklch(0.50 0.010 75)` | Secondary text, axis labels |
| `--ink-faint` | `oklch(0.545 0.010 78)` | Eyebrows, column heads, legends (AA 4.5:1) |
| `--ink-disabled` | `oklch(0.68 0.008 78)` | Disabled controls, placeholders (WCAG-exempt) |
| `--rule` | `oklch(0.885 0.005 80)` | Hairline separators |
| `--rule-ink` | `var(--ink)` | The heavy structural rule under page titles |
| `--accent` | `oklch(0.47 0.19 264)` | Ultramarine: primary action, selection, focus, links |
| `--accent-hover` | `oklch(0.39 0.19 264)` | Accent hover/active |
| `--accent-wash` | `oklch(0.955 0.028 264)` | Selected-row tint, accent backgrounds |
| `--canvas` | `oklch(0.16 0.008 70)` | Dark media surround only |

**Why ultramarine and not the category reflex.** Camera/CV tooling reflexively
goes dark-navy with cyan glow. On a warm paper ground with black ink and Swiss
rules, ultramarine reads as a printing ink, not a control room. The surface
treatment, not just the hue, is what keeps this out of the surveillance lane.

### Status colors are never load-bearing

Status appears on every camera in the product, so color alone is not permitted
(see PRODUCT.md accessibility). Every status renders as **color + geometric mark
+ text label**, all three:

| State | Color | Mark | Label |
|---|---|---|---|
| Live | `--ok` `oklch(0.52 0.14 150)` | filled circle | "Live" |
| Degraded | `--warn` `oklch(0.62 0.15 70)` | filled diamond | "Degraded" |
| Offline | `--danger` `oklch(0.52 0.19 27)` | filled square | "Offline" |
| Not set up | `--ink-faint` | hollow circle | "Not set up" |

The marks are distinguishable in grayscale and to any form of color blindness.

### Charts

Charts are the subject, so they get the accent, not the chrome. Single-hue
sequential ultramarine for magnitude; `--chart-grid` is nearly invisible so data
carries the contrast. Heat ramp runs warm-white to deep ultramarine in 5 steps.
Every chart ships a `<details>` "View as table" equivalent.

## Typography

One family. A neutral grotesque, in the Swiss tradition:

```
"Helvetica Neue", Helvetica, Inter, -apple-system, BlinkMacSystemFont,
"Segoe UI", Arial, sans-serif
```

Monospace (logs, raw config): `ui-monospace, "SF Mono", SFMono-Regular, Menlo, monospace`

Fixed rem scale, ratio ~1.2. No fluid clamps: users are at consistent desktop DPI.

| Token | Size | Use |
|---|---|---|
| `--t-micro` | 0.6875rem | Eyebrow labels, uppercase, `0.09em` tracking |
| `--t-small` | 0.8125rem | Table cells, captions, metadata |
| `--t-body` | 0.9375rem | Body, controls |
| `--t-lead` | 1.0625rem | Section intros |
| `--t-h3` | 1.125rem | Sub-headings |
| `--t-h2` | 1.375rem | Section headings |
| `--t-h1` | 1.9375rem | Page title |
| `--t-display` | 2.5rem | KPI figures |

Rules:
- Headings: weight 600, `letter-spacing: -0.021em`. Never 700+ display weights.
- **Every number uses `font-variant-numeric: tabular-nums`.** Columns of figures
  must align; this is a data product.
- Eyebrows: uppercase, `--t-micro`, weight 600, `--ink-faint`, wide tracking.
- Prose capped at 68ch. Tables and dense UI may exceed it.
- Flush left, ragged right. Nothing centered except table numerics.

## Layout

Grid: content column `max-width: 1140px`, `padding: 0 2rem`. Asymmetric balance,
not centered composition.

- **The heavy rule.** Every page title sits above a 2px ink rule spanning the
  content column. It is the single strongest structural mark in the system and
  the page's anchor.
- **No cards.** Sections are separated by hairline rules and whitespace, not
  borders + radius + shadow. Nested boxes are forbidden.
- **No shadows.** No elevation. Planes are separated by rules alone.
- **`border-radius: 0` everywhere.** Buttons, inputs, tiles, images. Geometric
  honesty; the hard edge is the signature.
- Spacing varies deliberately for rhythm (`0.5 / 0.75 / 1.25 / 2 / 3.5rem`), it
  is not one uniform gutter.
- KPI figures sit in a rule-divided horizontal band, newspaper-style, not in
  a row of boxes.

## Components

Every interactive element ships default / hover / focus-visible / active /
disabled. Focus is a 2px `--accent` outline with 2px offset, never removed.

- **Buttons.** Square. Secondary: 1px `--ink` border, transparent ground.
  Primary: filled `--accent`, paper text. Danger: `--danger` border and text,
  fills on hover. Small variant for table rows.
- **Inputs.** Square, 1px `--rule`, `--surface` ground, accent border on focus.
- **Tables.** Hairline row rules, no zebra striping, uppercase micro column
  headers, tabular numerics, numeric columns right-aligned.
- **Flash messages.** A 2px left-aligned accent-colored top rule and tinted
  ground. (Not a side stripe: the rule sits on the top edge, full width.)
- **Empty states.** Teach the next action in plain retail language, always
  naming the specific thing to click.

## Motion

Functional only, with exactly one named exception (below). Nothing
choreographed anywhere else.

- Duration `140ms` for hover/color, `200ms` for reveals.
- Easing `cubic-bezier(0.22, 1, 0.36, 1)` (ease-out-quart). No bounce, no elastic.
- Only `color`, `background-color`, `border-color`, `opacity`, `transform`.
  Never layout properties.
- All motion wrapped by `@media (prefers-reduced-motion: reduce)` removal.

### The one exception: the cold-boot splash

`src/splash/` plays a ~2.9s branded sequence on the portal's entry page —
six balls scatter, converge into the mark's dot, the frame draws itself
around them, the wordmark tracks in. This is deliberately the opposite of
every rule above, and it is allowed *once*, in *one place*, under these
conditions:

- **Portal entry only** (`/`). Never on `/app/*`, never on navigation, never
  on refetch or HMR. Gated by `sessionStorage` so it plays once per session.
- **Never gates the app.** Bootstrap runs in parallel from frame zero; the
  splash only controls when it stops covering an already-rendered page.
- **Always skippable** — any key or click after 600ms jumps to the settled
  lockup.
- **`prefers-reduced-motion` skips the physics entirely**, fading the
  finished lockup in over 300ms instead.
- **Hard ceiling 3.2s.** Past that it holds the completed lockup with a
  quiet pulse rather than extending the animation.

Everything else in the product stays functional-only. If a second
choreographed sequence is ever proposed, it does not inherit this exemption:
this one is justified by being the single moment where the product
introduces itself, not by being enjoyable.

Timings and physics constants live in `src/splash/splashConstants.ts`.

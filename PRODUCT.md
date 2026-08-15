# Product

## Register

product

## Users

Retail operations people: store managers and area/ops leadership. They use this
on a back-office desktop under bright store lighting, in short bursts between
floor walks, not in long focused sessions. They are not analysts and not
engineers. They arrive with a specific operational question already in mind:
"how long are customers waiting at checkout?", "when was I busiest?", "how many
people came in today?"

A secondary user appears exactly once per store: whoever does setup (often the
same manager, sometimes an IT contact). They discover cameras, calibrate, and
place service points, then never touch that part again.

The job to be done: answer an operational question in under a minute, with
enough confidence to act on it.

## Product Purpose

Turns the security cameras a store already owns into a live operations
dashboard. No new hardware, no cloud dependency, no floor-plan survey.

It measures store entries and exits, how long visitors stay, where they stand
(per-camera heatmaps), and how long customers spend being served at a register
or counter.

Success looks like: a manager changes a staffing decision because of something
they saw here. Failure looks like a beautiful dashboard nobody opens twice.

## Brand Personality

Precise, plain-spoken, unshowy. It reports rather than persuades. Numbers are
stated with authority and their limits are stated just as plainly, because a
metric a manager can't trust is worse than no metric.

Closest in craft and personality to Observable and Datawrapper: editorial data
publishing, where the chart is the subject and the interface gets out of its
way. Not a monitoring console, not a security product.

## Anti-references

- **Floor plans and homography.** Rejected twice. Spatial features live in each
  camera's own image space. Never reintroduce a store map, blueprint upload, or
  perspective-transform calibration step.
- **Computer-vision jargon.** No "footfall", "dwell", "global ID", "queue zone",
  "Re-ID". Plain retail language throughout: store entries, time spent, visitor
  ID, camera handoff point.
- **Surveillance aesthetics.** No dark neon control-room look, no scan lines, no
  glowing status walls, no crosshairs. This is a business measurement tool that
  happens to use cameras, not a security product.
- **The generic dark SaaS dashboard.** Gradient hero metrics, identical card
  grids, glassmorphism, decorative accent stripes.

## Design Principles

1. **The chart is the subject.** Chrome recedes. If a visual element isn't data,
   a label for data, or a control that changes data, question whether it should
   exist.
2. **Say what a number can't tell you.** Every metric that has a real limit
   states it inline, in plain words. Honest limits are the product's credibility.
3. **Setup is a visitor, operation is a resident.** Discovery and calibration
   are one-time paths and should stay out of the daily surface. Watching and
   reading are the daily surface.
4. **Plain retail words, always.** If a store manager wouldn't say it out loud
   to a colleague, it doesn't belong in the interface.
5. **Structure over decoration.** Hierarchy comes from typography, rules, and
   whitespace. Not from boxes, shadows, or color.

## Accessibility & Inclusion

WCAG 2.1 AA, with colorblind safety treated as a hard requirement rather than a
nicety: camera status (live / offline / degraded / not set up) appears
throughout the product and must never be carried by color alone. Every status
carries a distinct geometric mark and a text label alongside its color.

- Body text at 4.5:1 minimum against its background; large text and non-text UI
  at 3:1.
- Visible, high-contrast focus rings on every interactive element. Never
  `outline: none` without a replacement.
- Charts must remain readable in grayscale and always offer a "View as table"
  equivalent for screen-reader and keyboard users.
- Respect `prefers-reduced-motion`; all motion in this product is functional and
  safe to remove entirely.

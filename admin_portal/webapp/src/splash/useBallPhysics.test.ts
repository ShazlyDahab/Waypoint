import { describe, expect, it } from "vitest";
import {
  advance,
  attractionAt,
  createBalls,
  createRng,
  hasConverged,
  stepOnce,
} from "./useBallPhysics";
import { PHASE, PHYSICS } from "./splashConstants";

const VIEW = { width: 1280, height: 800 };
const CENTRE = { x: 640, y: 400 };

describe("seeded determinism", () => {
  it("produces identical trajectories for the same seed", () => {
    const a = createBalls({ ...VIEW, seed: 42 });
    const b = createBalls({ ...VIEW, seed: 42 });
    const ctx = { ...VIEW, attraction: 0, target: CENTRE };
    for (let i = 0; i < 300; i++) {
      stepOnce(a, ctx, PHYSICS.TIMESTEP_MS / 1000);
      stepOnce(b, ctx, PHYSICS.TIMESTEP_MS / 1000);
    }
    expect(a.map((x) => [x.x, x.y])).toEqual(b.map((x) => [x.x, x.y]));
  });

  it("produces a different run for a different seed", () => {
    const a = createBalls({ ...VIEW, seed: 1 });
    const b = createBalls({ ...VIEW, seed: 2 });
    expect(a.map((x) => [x.x, x.y])).not.toEqual(b.map((x) => [x.x, x.y]));
  });

  it("createRng is stable and stays in [0,1)", () => {
    const r1 = createRng(7);
    const r2 = createRng(7);
    for (let i = 0; i < 50; i++) {
      const v = r1();
      expect(v).toBe(r2());
      expect(v).toBeGreaterThanOrEqual(0);
      expect(v).toBeLessThan(1);
    }
  });
});

describe("fixed timestep", () => {
  it("advances identically at 60Hz and 144Hz for the same wall-clock time", () => {
    // The whole point of the accumulator: frame rate must not change motion.
    //
    // Both runs must be fed the SAME total wall-clock, so drive them by an
    // exact frame count rather than a `t < total` loop — accumulating a
    // float step lands on 1016.7ms at 60Hz vs 1000ms at 144Hz, and the
    // resulting 3-step difference is real motion, not a bug.
    const slow = createBalls({ ...VIEW, seed: 9 });
    const fast = createBalls({ ...VIEW, seed: 9 });
    const ctx = { ...VIEW, attraction: 0, target: CENTRE };

    let accSlow = 0;
    let accFast = 0;
    for (let i = 0; i < 60; i++) accSlow = advance(slow, ctx, 1000 / 60, accSlow);
    for (let i = 0; i < 144; i++) accFast = advance(fast, ctx, 1000 / 144, accFast);

    // Equal time in => equal fixed steps consumed => bit-identical positions.
    slow.forEach((s, i) => {
      expect(s.x).toBeCloseTo(fast[i].x, 6);
      expect(s.y).toBeCloseTo(fast[i].y, 6);
    });
  });

  it("clamps a huge frame delta so a backgrounded tab cannot fling balls away", () => {
    const balls = createBalls({ ...VIEW, seed: 3 });
    const ctx = { ...VIEW, attraction: 0, target: CENTRE };
    // 30 seconds in one frame — the clamp must cap the catch-up work.
    advance(balls, ctx, 30_000, 0);
    for (const b of balls) {
      expect(b.x).toBeGreaterThanOrEqual(0);
      expect(b.x).toBeLessThanOrEqual(VIEW.width);
      expect(b.y).toBeGreaterThanOrEqual(0);
      expect(b.y).toBeLessThanOrEqual(VIEW.height);
    }
  });
});

describe("bounds", () => {
  it("no ball ever escapes the viewport during free scatter", () => {
    const balls = createBalls({ ...VIEW, seed: 11 });
    const ctx = { ...VIEW, attraction: 0, target: CENTRE };
    let acc = 0;
    for (let frame = 0; frame < 600; frame++) {
      acc = advance(balls, ctx, 1000 / 60, acc);
      for (const b of balls) {
        expect(b.x).toBeGreaterThanOrEqual(b.radius - 0.001);
        expect(b.x).toBeLessThanOrEqual(VIEW.width - b.radius + 0.001);
        expect(b.y).toBeGreaterThanOrEqual(b.radius - 0.001);
        expect(b.y).toBeLessThanOrEqual(VIEW.height - b.radius + 0.001);
      }
    }
  });

  it("stays in bounds in a narrow viewport too", () => {
    const narrow = { width: 320, height: 200 };
    const balls = createBalls({ ...narrow, seed: 5 });
    const ctx = { ...narrow, attraction: 0, target: { x: 160, y: 100 } };
    let acc = 0;
    for (let f = 0; f < 400; f++) acc = advance(balls, ctx, 1000 / 60, acc);
    for (const b of balls) {
      expect(b.x).toBeGreaterThanOrEqual(b.radius - 0.001);
      expect(b.x).toBeLessThanOrEqual(narrow.width - b.radius + 0.001);
    }
  });
});

describe("convergence", () => {
  it("completes inside the phase budget", () => {
    const balls = createBalls({ ...VIEW, seed: 21 });
    let acc = 0;
    let elapsed = 0;
    const frameMs = 1000 / 60;
    // Run the real timeline: free scatter, then the ramped attractor.
    while (elapsed < PHASE.CONVERGE_UNTIL_MS) {
      const attraction = attractionAt(elapsed, PHASE.SCATTER_UNTIL_MS, PHASE.ATTRACTOR_RAMP_MS);
      acc = advance(balls, { ...VIEW, attraction, target: CENTRE }, frameMs, acc);
      elapsed += frameMs;
    }
    expect(hasConverged(balls, CENTRE)).toBe(true);
  });

  it("ramps attraction rather than switching it on", () => {
    // A step change here is exactly the visible discontinuity the brief
    // warns about, so assert it genuinely eases.
    expect(attractionAt(PHASE.SCATTER_UNTIL_MS, PHASE.SCATTER_UNTIL_MS, 150)).toBe(0);
    expect(attractionAt(PHASE.SCATTER_UNTIL_MS + 75, PHASE.SCATTER_UNTIL_MS, 150)).toBeCloseTo(0.5, 2);
    expect(attractionAt(PHASE.SCATTER_UNTIL_MS + 150, PHASE.SCATTER_UNTIL_MS, 150)).toBe(1);
    expect(attractionAt(PHASE.SCATTER_UNTIL_MS + 900, PHASE.SCATTER_UNTIL_MS, 150)).toBe(1);
  });

  it("balls end effectively on top of each other, ready to read as one dot", () => {
    const balls = createBalls({ ...VIEW, seed: 33 });
    let acc = 0;
    let elapsed = 0;
    while (elapsed < PHASE.CONVERGE_UNTIL_MS) {
      const attraction = attractionAt(elapsed, PHASE.SCATTER_UNTIL_MS, PHASE.ATTRACTOR_RAMP_MS);
      acc = advance(balls, { ...VIEW, attraction, target: CENTRE }, 1000 / 60, acc);
      elapsed += 1000 / 60;
    }
    const spread = Math.max(...balls.map((b) => Math.hypot(b.x - CENTRE.x, b.y - CENTRE.y)));
    expect(spread).toBeLessThanOrEqual(PHYSICS.ARRIVAL_RADIUS);
  });
});

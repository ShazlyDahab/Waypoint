// Framework-free ball simulation for the Waypoint splash.
//
// No React, no DOM, no rAF in here — the caller drives it. That keeps the
// whole thing unit-testable: feed it a seed and a fixed number of steps and
// it produces the same trajectory every run.
//
// Integration is a fixed-timestep accumulator, NOT raw frame delta, so a
// 144Hz monitor and a 60Hz monitor see identical motion. Frame time is
// clamped (PHYSICS.MAX_FRAME_MS) so a backgrounded tab resuming after 30s
// doesn't advance 30 seconds of physics in one go and fling every ball into
// the void.

import { PHYSICS } from "./splashConstants";

export interface Ball {
  x: number;
  y: number;
  vx: number;
  vy: number;
  radius: number;
  /** Rendered alpha — some balls are dimmed so the cluster has depth. */
  alpha: number;
  /** Recent positions, newest last. Empty when trails are disabled. */
  trail: Array<{ x: number; y: number }>;
}

export interface SimulationOptions {
  width: number;
  height: number;
  seed?: number;
  ballCount?: number;
}

/**
 * Mulberry32 — small, fast, and crucially *seedable*, which Math.random is
 * not. Determinism is what makes the physics testable.
 */
export function createRng(seed: number): () => number {
  let a = seed >>> 0;
  return function next() {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const lerp = (a: number, b: number, t: number) => a + (b - a) * t;

export function createBalls(opts: SimulationOptions): Ball[] {
  const { width, height, seed = 1, ballCount = PHYSICS.BALL_COUNT } = opts;
  const rng = createRng(seed);
  const balls: Ball[] = [];

  for (let i = 0; i < ballCount; i++) {
    const radius = lerp(PHYSICS.RADIUS_MIN, PHYSICS.RADIUS_MAX, rng());
    const speed = lerp(PHYSICS.SPEED_MIN, PHYSICS.SPEED_MAX, rng());
    // Full 360° heading: the brief asks for movement on both axes with
    // randomised direction, not a choreographed sweep.
    const angle = rng() * Math.PI * 2;
    balls.push({
      // Inset by radius so nothing starts already overlapping a wall.
      x: lerp(radius, width - radius, rng()),
      y: lerp(radius, height - radius, rng()),
      vx: Math.cos(angle) * speed,
      vy: Math.sin(angle) * speed,
      radius,
      alpha: rng() < PHYSICS.DIM_RATIO ? PHYSICS.DIM_ALPHA : 1,
      trail: [],
    });
  }
  return balls;
}

export interface StepContext {
  width: number;
  height: number;
  /** 0 = free scatter, 1 = full attraction. Ramped, never switched. */
  attraction: number;
  target: { x: number; y: number };
}

/** Advances exactly one fixed timestep. `dt` is in seconds. */
export function stepOnce(balls: Ball[], ctx: StepContext, dt: number): void {
  const { width, height, attraction, target } = ctx;

  for (const b of balls) {
    if (attraction > 0) {
      const dx = target.x - b.x;
      const dy = target.y - b.y;
      // Linear spring rather than inverse-square: inverse-square explodes as
      // distance approaches zero and the balls would slingshot past the
      // target instead of settling on it.
      // Linear spring: acceleration proportional to displacement.
      const k = PHYSICS.ATTRACTOR_STIFFNESS * attraction;
      b.vx += dx * k * dt;
      b.vy += dy * k * dt;

      // Damping ramps with attraction, so they still bounce a little on the
      // way in and lose that energy rather than stopping dead.
      const damping = Math.exp(-PHYSICS.DAMPING_PER_SEC * attraction * dt);
      b.vx *= damping;
      b.vy *= damping;
    } else {
      b.vy += PHYSICS.GRAVITY * dt;
    }

    b.x += b.vx * dt;
    b.y += b.vy * dt;

    // Elastic walls. Position is clamped as well as reflected, otherwise a
    // ball that overshoots badly in one step can stick outside the bounds.
    if (b.x - b.radius < 0) {
      b.x = b.radius;
      b.vx = Math.abs(b.vx) * PHYSICS.RESTITUTION;
    } else if (b.x + b.radius > width) {
      b.x = width - b.radius;
      b.vx = -Math.abs(b.vx) * PHYSICS.RESTITUTION;
    }
    if (b.y - b.radius < 0) {
      b.y = b.radius;
      b.vy = Math.abs(b.vy) * PHYSICS.RESTITUTION;
    } else if (b.y + b.radius > height) {
      b.y = height - b.radius;
      b.vy = -Math.abs(b.vy) * PHYSICS.RESTITUTION;
    }
  }
}

/**
 * Advances the simulation by a wall-clock frame using a fixed-timestep
 * accumulator. Returns the leftover accumulator for the next call.
 */
export function advance(
  balls: Ball[],
  ctx: StepContext,
  frameMs: number,
  accumulatorMs: number
): number {
  let acc = accumulatorMs + Math.min(frameMs, PHYSICS.MAX_FRAME_MS);
  const stepSec = PHYSICS.TIMESTEP_MS / 1000;

  // EPSILON, not a bare >=. Accumulating 1000/144 a hundred and forty-four
  // times lands on 8.333333333333332 against a timestep of
  // 8.333333333333334, so the last step is silently dropped to a two-ulp
  // rounding error. That made a 144Hz display run ~1 step/second behind a
  // 60Hz one — precisely the frame-rate dependence the fixed timestep is
  // here to eliminate.
  const EPSILON = 1e-9;
  while (acc + EPSILON >= PHYSICS.TIMESTEP_MS) {
    stepOnce(balls, ctx, stepSec);
    acc -= PHYSICS.TIMESTEP_MS;
  }
  if (acc < 0) acc = 0;

  if (PHYSICS.TRAIL_LENGTH > 0) {
    for (const b of balls) {
      b.trail.push({ x: b.x, y: b.y });
      if (b.trail.length > PHYSICS.TRAIL_LENGTH) b.trail.shift();
    }
  }
  return acc;
}

/** True once every ball has effectively arrived at the target. */
export function hasConverged(balls: Ball[], target: { x: number; y: number }): boolean {
  return balls.every((b) => Math.hypot(target.x - b.x, target.y - b.y) <= PHYSICS.ARRIVAL_RADIUS);
}

/**
 * Attraction ramp for a given elapsed time. Eased in over
 * PHASE.ATTRACTOR_RAMP_MS so the handover from free scatter to attraction
 * has no visible discontinuity.
 */
export function attractionAt(elapsedMs: number, scatterUntilMs: number, rampMs: number): number {
  if (elapsedMs <= scatterUntilMs) return 0;
  return Math.min(1, (elapsedMs - scatterUntilMs) / rampMs);
}

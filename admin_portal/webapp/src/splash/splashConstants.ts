// Every tunable for the Waypoint splash lives here. Change these without
// reading the simulation loop.
//
// Phase budget is expressed as absolute milliseconds from splash start, so
// the phases are read as a timeline rather than a chain of durations.

export const PHASE = {
  /** Balls scatter freely. */
  SCATTER_UNTIL_MS: 1300,
  /** Attractor eases in over this window so physics->easing has no visible seam. */
  ATTRACTOR_RAMP_MS: 150,
  /** Convergence + settle complete; the dot is the dot. */
  CONVERGE_UNTIL_MS: 2000,
  /** Wordmark finished fading in. */
  WORDMARK_UNTIL_MS: 2600,
  /** Hold the finished lockup, then hand off. */
  HANDOFF_AT_MS: 2900,
  /** Never hold the user longer than this, whatever bootstrap is doing. */
  HARD_CEILING_MS: 3200,
  /** Don't flash-and-abort if bootstrap resolves instantly. */
  MIN_VISIBLE_MS: 1800,
  /** Ignore skip input before this, so an early stray keypress doesn't kill it. */
  SKIP_ENABLED_AFTER_MS: 600,
} as const;

export const PHYSICS = {
  BALL_COUNT: 6,
  /** px radius range; varied so the cluster reads as depth, not six clones. */
  RADIUS_MIN: 4,
  RADIUS_MAX: 7,
  /** px/sec initial speed range. */
  SPEED_MIN: 260,
  SPEED_MAX: 520,
  /** Elastic-ish walls. 1.0 would never lose energy. */
  RESTITUTION: 0.95,
  /** px/sec^2. Near-zero: buoyant, not falling. */
  GRAVITY: 40,
  /** Fixed timestep — identical behaviour at 60/120/144Hz. */
  TIMESTEP_MS: 1000 / 120,
  /** Cap catch-up work after a backgrounded tab, so balls never fling away. */
  MAX_FRAME_MS: 100,
  /* Convergence is a spring-damper, tuned to settle inside the phase budget.
     omega = sqrt(ATTRACTOR_STIFFNESS) ~= 20 rad/s, and
     zeta = DAMPING_PER_SEC / (2*omega) ~= 0.7 — slightly underdamped, so the
     cluster overshoots a touch and settles rather than stopping dead.
     Raising stiffness without raising damping makes it ring; keep the ratio. */
  /** Spring stiffness toward the logo centre, 1/sec^2. */
  ATTRACTOR_STIFFNESS: 385,
  /** Damping coefficient, 1/sec. Velocity scales by exp(-this * dt). */
  DAMPING_PER_SEC: 27,
  /** Below this distance (px) a ball counts as arrived. */
  ARRIVAL_RADIUS: 4,
  /** Trail samples per ball. 0 disables trails. */
  TRAIL_LENGTH: 6,
  TRAIL_ALPHA: 0.16,
  /** Fraction of balls drawn at reduced opacity, for depth. */
  DIM_RATIO: 0.4,
  DIM_ALPHA: 0.55,
} as const;

export const LOCKUP = {
  /** Wordmark tracking eases from this to its resting value as it fades in. */
  TRACKING_FROM_EM: 0.22,
  TRACKING_TO_EM: 0.06,
  /** translateX start for the wordmark, px. */
  SLIDE_FROM_PX: 12,
  /** Per-letter stagger. Set to 0 to fade the word as one unit. */
  LETTER_STAGGER_MS: 18,
  /** Splash renders the mark this many times larger than the header's 22px. */
  MARK_SCALE: 3.2,
} as const;

/** Matches --ease in index.css. Tuple shape is what motion expects. */
export const EASE_OUT_QUART: [number, number, number, number] = [0.22, 1, 0.36, 1];

export const SESSION_KEY = "waypoint.splash.seen";
/** Set by the logo click, consumed on the next load of the home page. */
export const REPLAY_KEY = "waypoint.splash.replay";

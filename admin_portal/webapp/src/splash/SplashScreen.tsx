import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { motion } from "motion/react";
import LogoLockup, { MARK, wordmarkLetters } from "../components/LogoLockup";
import { EASE_OUT_QUART, LOCKUP, PHASE, PHYSICS } from "./splashConstants";
import { advance, attractionAt, Ball, createBalls } from "./useBallPhysics";
import { usePrefersReducedMotion } from "./usePrefersReducedMotion";

// Cold-boot splash. Phase timings and physics constants are in
// splashConstants.ts — tune there, not here.
//
// The app is NEVER gated on this: `bootstrap` runs from frame zero in
// parallel, and the splash only controls when it stops covering the page.

type Phase = "scatter" | "converge" | "wordmark" | "hold" | "done" | "error";

export interface SplashScreenProps {
  /** Runs in parallel from frame zero. Rejection surfaces an error state. */
  bootstrap?: () => Promise<unknown>;
  onFinish?: () => void;
  /** Fixed seed makes a run reproducible; omit for a different run each time. */
  seed?: number;
}

export default function SplashScreen({ bootstrap, onFinish, seed }: SplashScreenProps) {
  const prefersReducedMotion = usePrefersReducedMotion();
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const dotRef = useRef<SVGCircleElement>(null);
  const rafRef = useRef<number | null>(null);
  const finishedRef = useRef(false);

  const [phase, setPhase] = useState<Phase>(prefersReducedMotion ? "hold" : "scatter");
  const [borderProgress, setBorderProgress] = useState(prefersReducedMotion ? 1 : 0);
  const [clusterVisible, setClusterVisible] = useState(!prefersReducedMotion);
  const [bootstrapError, setBootstrapError] = useState<string | null>(null);
  const [overCeiling, setOverCeiling] = useState(false);

  const runSeed = useMemo(() => seed ?? Math.floor(Math.random() * 0xffffffff), [seed]);

  const finish = useCallback(() => {
    if (finishedRef.current) return;
    finishedRef.current = true;
    setPhase("done");
    onFinish?.();
  }, [onFinish]);

  // ---------------------------------------------------------- bootstrap ---
  // Kicked off immediately, independent of the animation.
  const bootstrapDoneRef = useRef(false);
  useEffect(() => {
    let cancelled = false;
    const started = performance.now();
    if (!bootstrap) {
      bootstrapDoneRef.current = true;
      return;
    }
    bootstrap()
      .then(() => {
        if (!cancelled) bootstrapDoneRef.current = true;
      })
      .catch((e) => {
        if (cancelled) return;
        // Surface it. Never spin forever on a failure.
        setBootstrapError(e instanceof Error ? e.message : String(e));
        setPhase("error");
      })
      .finally(() => {
        if (!cancelled && import.meta.env.DEV) {
          // eslint-disable-next-line no-console
          console.debug(`[splash] bootstrap settled in ${Math.round(performance.now() - started)}ms`);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [bootstrap]);

  // ------------------------------------------------------ reduced motion ---
  // No physics at all: render the finished lockup and fade it in.
  useEffect(() => {
    if (!prefersReducedMotion) return;
    const t = window.setTimeout(() => {
      if (bootstrapDoneRef.current || !bootstrap) finish();
      else window.setTimeout(finish, PHASE.HARD_CEILING_MS - 300);
    }, 300);
    return () => window.clearTimeout(t);
  }, [prefersReducedMotion, bootstrap, finish]);

  // ------------------------------------------------------------- physics ---
  useEffect(() => {
    if (prefersReducedMotion) return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let width = window.innerWidth;
    let height = window.innerHeight;
    let dpr = Math.min(window.devicePixelRatio || 1, 3);

    function resize() {
      width = window.innerWidth;
      height = window.innerHeight;
      dpr = Math.min(window.devicePixelRatio || 1, 3);
      canvas!.width = Math.round(width * dpr);
      canvas!.height = Math.round(height * dpr);
      canvas!.style.width = `${width}px`;
      canvas!.style.height = `${height}px`;
      // Draw in CSS pixels; the backing store stays retina-sharp.
      ctx!.setTransform(dpr, 0, 0, dpr, 0, 0);
    }
    resize();

    const balls: Ball[] = createBalls({ width, height, seed: runSeed });
    const accent =
      getComputedStyle(document.documentElement).getPropertyValue("--accent").trim() ||
      "oklch(0.47 0.19 264)";

    // The balls converge on the REAL dot's centre, measured from the DOM, so
    // the cluster lands exactly where the mark's dot lives at any viewport.
    function targetPoint() {
      const el = dotRef.current;
      if (!el) return { x: width / 2, y: height / 2 };
      const r = el.getBoundingClientRect();
      return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
    }

    let accumulator = 0;
    let last = performance.now();
    const startedAt = last;
    let paused = false;
    // Time spent hidden, excluded from `elapsed`. Without this the physics
    // pauses but the PHASE CLOCK keeps running, so a tab backgrounded for a
    // few seconds resumes already past handoff — the balls would still be
    // scattered while the timeline thinks it's done. "Resume without a time
    // jump" has to mean the phases too, not just the integrator.
    let pausedTotal = 0;
    let pausedAt = 0;

    function onVisibility() {
      if (document.hidden) {
        if (!paused) {
          paused = true;
          pausedAt = performance.now();
        }
      } else if (paused) {
        paused = false;
        pausedTotal += performance.now() - pausedAt;
        last = performance.now();
      }
    }
    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("resize", resize);

    function frame(now: number) {
      rafRef.current = requestAnimationFrame(frame);
      if (paused) {
        last = now;
        return;
      }

      const frameMs = now - last;
      last = now;
      const elapsed = now - startedAt - pausedTotal;

      const attraction = attractionAt(elapsed, PHASE.SCATTER_UNTIL_MS, PHASE.ATTRACTOR_RAMP_MS);
      const target = targetPoint();
      accumulator = advance(balls, { width, height, attraction, target }, frameMs, accumulator);

      // ---- phase transitions -------------------------------------------
      if (elapsed >= PHASE.SCATTER_UNTIL_MS && elapsed < PHASE.CONVERGE_UNTIL_MS) {
        setPhase((p) => (p === "scatter" ? "converge" : p));
        // Frame draws itself around the cluster as it arrives.
        const t = (elapsed - PHASE.SCATTER_UNTIL_MS) /
          (PHASE.CONVERGE_UNTIL_MS - PHASE.SCATTER_UNTIL_MS);
        setBorderProgress(Math.min(1, t));
      } else if (elapsed >= PHASE.CONVERGE_UNTIL_MS) {
        setBorderProgress(1);
        // Cheap merge: at maximum overlap the cluster hands off to the real
        // dot. Cross-fade reads the same as a metaball blur at a fraction of
        // the cost, and it guarantees we end on the actual mark.
        setClusterVisible(false);
        setPhase((p) => (p === "converge" || p === "scatter" ? "wordmark" : p));
      }

      // ---- draw ---------------------------------------------------------
      ctx!.clearRect(0, 0, width, height);

      // Shrink the cluster as it settles, so it reads as coalescing rather
      // than six balls stacking up.
      const shrink =
        elapsed <= PHASE.SCATTER_UNTIL_MS
          ? 1
          : Math.max(
              0.25,
              1 -
                (elapsed - PHASE.SCATTER_UNTIL_MS) /
                  (PHASE.CONVERGE_UNTIL_MS - PHASE.SCATTER_UNTIL_MS)
            );
      const clusterAlpha =
        elapsed < PHASE.CONVERGE_UNTIL_MS - 160
          ? 1
          : Math.max(0, (PHASE.CONVERGE_UNTIL_MS - elapsed) / 160);

      if (clusterAlpha > 0) {
        for (const b of balls) {
          if (PHYSICS.TRAIL_LENGTH > 0 && b.trail.length > 1) {
            for (let i = 0; i < b.trail.length - 1; i++) {
              const p = b.trail[i];
              const fade = (i / b.trail.length) * PHYSICS.TRAIL_ALPHA;
              ctx!.globalAlpha = fade * b.alpha * clusterAlpha;
              ctx!.beginPath();
              ctx!.arc(p.x, p.y, b.radius * shrink, 0, Math.PI * 2);
              ctx!.fillStyle = accent;
              ctx!.fill();
            }
          }
          ctx!.globalAlpha = b.alpha * clusterAlpha;
          ctx!.beginPath();
          ctx!.arc(b.x, b.y, b.radius * shrink, 0, Math.PI * 2);
          ctx!.fillStyle = accent;
          ctx!.fill();
        }
        ctx!.globalAlpha = 1;
      }

      // ---- handoff -------------------------------------------------------
      const bootstrapReady = bootstrapDoneRef.current || !bootstrap;
      if (elapsed >= PHASE.HARD_CEILING_MS) {
        setOverCeiling(!bootstrapReady);
        if (bootstrapReady) finish();
      } else if (elapsed >= PHASE.HANDOFF_AT_MS && elapsed >= PHASE.MIN_VISIBLE_MS) {
        if (bootstrapReady) finish();
      }
    }

    rafRef.current = requestAnimationFrame(frame);

    return () => {
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("resize", resize);
    };
  }, [prefersReducedMotion, runSeed, bootstrap, finish]);

  // Past the ceiling with bootstrap still running: hold the finished lockup
  // and pulse the dot. Nothing new enters the frame.
  useEffect(() => {
    if (!overCeiling) return;
    const id = window.setInterval(() => {
      if (bootstrapDoneRef.current) finish();
    }, 120);
    return () => window.clearInterval(id);
  }, [overCeiling, finish]);

  // --------------------------------------------------------------- skip ---
  useEffect(() => {
    if (phase === "error") return;
    const enabledAt = performance.now() + PHASE.SKIP_ENABLED_AFTER_MS;
    function onInput() {
      if (performance.now() < enabledAt) return;
      setBorderProgress(1);
      setClusterVisible(false);
      setPhase("hold");
      // Straight to the settled lockup, then out — but still never before
      // bootstrap, or we'd hand off to a half-built page.
      if (bootstrapDoneRef.current || !bootstrap) finish();
      else setOverCeiling(true);
    }
    window.addEventListener("keydown", onInput);
    window.addEventListener("pointerdown", onInput);
    return () => {
      window.removeEventListener("keydown", onInput);
      window.removeEventListener("pointerdown", onInput);
    };
  }, [phase, bootstrap, finish]);

  if (phase === "done") return null;

  const markSize = MARK.baseWidth * LOCKUP.MARK_SCALE;
  const showWordmark = phase === "wordmark" || phase === "hold" || phase === "error";
  const letters = wordmarkLetters();

  return (
    <div className="splash" role="presentation">
      {!prefersReducedMotion && (
        <canvas ref={canvasRef} className="splash-canvas" aria-hidden="true" />
      )}

      <div className="splash-lockup">
        <motion.div
          initial={prefersReducedMotion ? { opacity: 0 } : false}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.3, ease: EASE_OUT_QUART }}
          style={{ display: "flex", alignItems: "center", gap: markSize * 0.35 }}
        >
          <LogoLockup
            size={markSize}
            borderProgress={borderProgress}
            dotOpacity={clusterVisible ? 0 : 1}
            showWordmark={false}
            dotRef={dotRef}
            className={overCeiling ? "is-waiting" : ""}
          />

          {/* Wordmark: opacity + translateX + tracking tightening. The
              tightening is what sells "appearing" over "sliding in". */}
          <motion.span
            className="splash-wordmark"
            aria-hidden="true"
            initial={{
              opacity: 0,
              x: LOCKUP.SLIDE_FROM_PX,
              letterSpacing: `${LOCKUP.TRACKING_FROM_EM}em`,
            }}
            animate={
              showWordmark
                ? { opacity: 1, x: 0, letterSpacing: `${LOCKUP.TRACKING_TO_EM}em` }
                : {}
            }
            transition={{ duration: 0.6, ease: EASE_OUT_QUART }}
            style={{ fontSize: markSize * 0.62 }}
          >
            {LOCKUP.LETTER_STAGGER_MS > 0
              ? letters.map((ch, i) => (
                  <motion.span
                    key={i}
                    initial={{ opacity: 0 }}
                    animate={showWordmark ? { opacity: 1 } : {}}
                    transition={{
                      duration: 0.45,
                      delay: (i * LOCKUP.LETTER_STAGGER_MS) / 1000,
                      ease: EASE_OUT_QUART,
                    }}
                  >
                    {ch}
                  </motion.span>
                ))
              : letters.join("")}
          </motion.span>
        </motion.div>

        {phase === "error" && (
          <p className="splash-error" role="alert">
            Waypoint couldn’t start: {bootstrapError}
          </p>
        )}
      </div>

      <span role="status" className="visually-hidden">
        {phase === "error" ? `Waypoint failed to load: ${bootstrapError}` : "Loading Waypoint"}
      </span>
    </div>
  );
}

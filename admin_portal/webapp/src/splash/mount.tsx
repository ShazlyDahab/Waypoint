// Standalone entry that mounts ONLY the splash onto the server-rendered
// Jinja pages. The portal is mostly Jinja; the splash is the one React thing
// those pages need, so it ships as its own small bundle rather than pulling
// in the whole /app router.
//
// Firing rules:
//   - cold boot only, gated by sessionStorage (no replay on nav/refetch/HMR)
//   - ?splash=1 forces a replay for development
//   - ?splash=0 suppresses it

import { createRoot } from "react-dom/client";
import SplashScreen from "./SplashScreen";
import { REPLAY_KEY, SESSION_KEY } from "./splashConstants";
import "../index.css";

/** Diagnostics that survive teardown — `waypointSplash` in the console.
 *  Cheap, and the alternative is guessing whether the handoff ran. */
const debug: Record<string, unknown> = {};

function shouldPlay(): boolean {
  const params = new URLSearchParams(window.location.search);
  const forced = params.get("splash");
  if (forced === "1") return true;
  if (forced === "0") return false;
  try {
    // Clicking the Waypoint logo arms REPLAY_KEY and navigates here; consume
    // it so a later back/forward doesn't replay unexpectedly.
    if (sessionStorage.getItem(REPLAY_KEY) === "1") {
      sessionStorage.removeItem(REPLAY_KEY);
      return true;
    }
    return sessionStorage.getItem(SESSION_KEY) === null;
  } catch {
    // Private mode / storage disabled: don't trap the user in a splash we
    // can't remember showing.
    return false;
  }
}

/** Drop the pre-paint curtain (see index.html's head script). */
function liftCurtain() {
  document.documentElement.classList.remove("splash-pending");
}

/**
 * Real work to wait on. The Jinja page is already rendered by the time this
 * runs, so "bootstrap" here means: fonts settled (otherwise the wordmark
 * reflows mid-animation) and the backend reachable. The latter gives the
 * failure state something genuine to report — if the API is down, the splash
 * says so instead of handing off to a portal that can't load anything.
 */
function bootstrap(): Promise<unknown> {
  const fonts = document.fonts?.ready ?? Promise.resolve();
  const api = fetch("/api/cameras", { cache: "no-store" }).then((r) => {
    if (!r.ok) throw new Error(`the server answered ${r.status}`);
    return r.json();
  });
  return Promise.all([fonts, api]);
}

export function mountSplash(force = false) {
  if (!force && !shouldPlay()) {
    liftCurtain();
    return;
  }

  const host = document.createElement("div");
  host.id = "waypoint-splash-root";
  document.body.appendChild(host);
  const root = createRoot(host);
  debug.mountedAt = performance.now();

  // Keep the page underneath from scrolling while the splash covers it.
  const previousOverflow = document.body.style.overflow;
  document.body.style.overflow = "hidden";

  function finish() {
    debug.finishedAt = performance.now();
    try {
      sessionStorage.setItem(SESSION_KEY, "1");
    } catch {
      /* storage unavailable — the splash simply plays again next load */
    }
    document.body.style.overflow = previousOverflow;
    liftCurtain();

    // Focus BEFORE teardown. Ordering matters: unmounting first meant a
    // teardown failure silently cost the accessibility handoff, leaving
    // focus stranded on <body>.
    const target =
      document.querySelector<HTMLElement>("main h1") ??
      document.querySelector<HTMLElement>("main") ??
      document.body;
    target.setAttribute("tabindex", "-1");
    target.focus({ preventScroll: true });
    debug.focusTarget = target.tagName + ':' + (target.textContent || '').trim().slice(0, 24);

    // Defer the unmount out of React's commit phase. finish() is invoked
    // from the rAF callback that just queued setPhase("done"), and calling
    // root.unmount() synchronously there can throw "Attempted to
    // synchronously unmount a root while React was already rendering".
    setTimeout(() => {
      try {
        root.unmount();
      } finally {
        host.remove();
      }
    }, 0);
  }

  root.render(<SplashScreen bootstrap={bootstrap} onFinish={finish} />);
  // The splash now covers the page itself, so the curtain has done its job.
  requestAnimationFrame(liftCurtain);
}

mountSplash();

// Dev toggle: replay without a reload. `?splash=1` forces it on load;
// this is the in-page equivalent while tuning splashConstants.ts.
declare global {
  interface Window {
    replaySplash?: () => void;
  }
}
window.replaySplash = () => mountSplash(true);
(window as never as Record<string, unknown>).waypointSplash = debug;

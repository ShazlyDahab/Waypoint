import { useEffect, useState } from "react";

const QUERY = "(prefers-reduced-motion: reduce)";

/**
 * Reads the reduced-motion preference directly rather than going through
 * motion/react's useReducedMotion.
 *
 * This gates an accessibility branch — whether the physics runs at all — so
 * it must be correct on the very first render, not one effect later. The
 * library hook initialises from state captured at module load, which is both
 * harder to test and a subtle dependency to rest an a11y guarantee on.
 */
export function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState<boolean>(() => {
    if (typeof window === "undefined" || !window.matchMedia) return false;
    return window.matchMedia(QUERY).matches;
  });

  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const mq = window.matchMedia(QUERY);
    const onChange = () => setReduced(mq.matches);
    setReduced(mq.matches);
    // Safari < 14 only has the deprecated addListener.
    if (mq.addEventListener) mq.addEventListener("change", onChange);
    else mq.addListener(onChange);
    return () => {
      if (mq.removeEventListener) mq.removeEventListener("change", onChange);
      else mq.removeListener(onChange);
    };
  }, []);

  return reduced;
}

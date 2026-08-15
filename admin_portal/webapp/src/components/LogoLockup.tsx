import { CSSProperties, forwardRef } from "react";
import { LOCKUP } from "../splash/splashConstants";

// THE single source for the Waypoint lockup in React. Header and splash both
// render this, so the splash cannot drift from the real mark — it ends on
// literally the same element, same geometry, same tokens.
//
// (admin_portal/templates/_brand.html is the server-rendered twin for the
// Jinja pages. Same geometry, different template language. If you change the
// SVG here, change it there.)
//
// The mark: a camera frame containing one filled position. Two Bauhaus
// primitives, and semantically the product itself — a person's position
// within a camera's own view. Sharp corners, no radius: DESIGN.md commits to
// radius 0 throughout.

/** Intrinsic geometry of the mark, in viewBox units. */
export const MARK = {
  viewBoxW: 24,
  viewBoxH: 20,
  rect: { x: 1, y: 1, w: 22, h: 18, strokeWidth: 2 },
  dot: { cx: 15.5, cy: 12.5, r: 3.4 },
  /** Header render width in px. */
  baseWidth: 22,
} as const;

export interface LogoLockupProps {
  /** Mark width in px. Defaults to the header size. */
  size?: number;
  /** 0..1 — how much of the frame's stroke is drawn. 1 = complete. */
  borderProgress?: number;
  /** 0..1 — lets the splash cross-fade the ball cluster into the real dot. */
  dotOpacity?: number;
  /** Render the wordmark alongside the mark. */
  showWordmark?: boolean;
  /** Extra style for the wordmark (the splash animates tracking/opacity here). */
  wordmarkStyle?: CSSProperties;
  /** Renders as a link when provided, a plain span otherwise. */
  href?: string;
  className?: string;
  style?: CSSProperties;
  /** Splash measures the real dot to know where the balls must converge. */
  dotRef?: React.Ref<SVGCircleElement>;
}

const WORDMARK = "Waypoint";

const LogoLockup = forwardRef<HTMLElement, LogoLockupProps>(function LogoLockup(
  {
    size = MARK.baseWidth,
    borderProgress = 1,
    dotOpacity = 1,
    showWordmark = true,
    wordmarkStyle,
    href,
    className = "",
    style,
    dotRef,
  },
  ref
) {
  const height = (size / MARK.viewBoxW) * MARK.viewBoxH;
  const Tag = (href ? "a" : "span") as "a";

  const content = (
    <>
      <svg
        className="mark"
        viewBox={`0 0 ${MARK.viewBoxW} ${MARK.viewBoxH}`}
        width={size}
        height={height}
        aria-hidden="true"
        focusable="false"
      >
        <rect
          x={MARK.rect.x}
          y={MARK.rect.y}
          width={MARK.rect.w}
          height={MARK.rect.h}
          fill="none"
          stroke="currentColor"
          strokeWidth={MARK.rect.strokeWidth}
          // pathLength normalises the perimeter to 1, so the draw-on is a
          // plain 0..1 progress regardless of the mark's rendered size.
          pathLength={1}
          strokeDasharray={1}
          strokeDashoffset={1 - borderProgress}
        />
        <circle
          ref={dotRef}
          cx={MARK.dot.cx}
          cy={MARK.dot.cy}
          r={MARK.dot.r}
          fill="var(--accent)"
          opacity={dotOpacity}
        />
      </svg>
      {showWordmark && (
        <span className="wordmark" style={wordmarkStyle}>
          {WORDMARK}
        </span>
      )}
    </>
  );

  // Clicking the logo replays the splash on arrival at home — same contract
  // as the Jinja lockup in templates/_brand.html.
  function armSplashReplay() {
    if (!href) return;
    try {
      sessionStorage.setItem("waypoint.splash.replay", "1");
    } catch {
      /* storage blocked — the link still navigates, just without the splash */
    }
  }

  return (
    <Tag
      ref={ref as never}
      className={`brand ${className}`.trim()}
      href={href}
      style={style}
      onClick={href ? armSplashReplay : undefined}
    >
      {content}
    </Tag>
  );
});

export default LogoLockup;

/** Per-letter spans, for the splash's optional stagger. */
export function wordmarkLetters(): string[] {
  return WORDMARK.split("");
}

export const WORDMARK_TEXT = WORDMARK;
export { LOCKUP };

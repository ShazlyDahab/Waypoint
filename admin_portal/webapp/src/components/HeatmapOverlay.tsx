import { useEffect, useRef } from "react";
import { CameraHeatmap } from "../lib/api";

// Draws recorded standing positions as heat directly over the camera's own
// view. The data is a grid of counts in normalized image space, so it
// scales to whatever size the video/still is actually rendered at without
// any coordinate transform — this is the whole reason the heatmap moved
// from a floor plan to the camera view: no homography, nothing to
// calibrate, and what you see lines up with what the camera sees.

const PALETTE = [
  // low -> high. Alpha ramps up with intensity so cold areas stay readable.
  { r: 0, g: 90, b: 255, a: 0.0 },
  { r: 0, g: 160, b: 255, a: 0.35 },
  { r: 0, g: 220, b: 180, a: 0.45 },
  { r: 250, g: 220, b: 60, a: 0.55 },
  { r: 255, g: 130, b: 40, a: 0.65 },
  { r: 240, g: 40, b: 40, a: 0.75 },
];

function colorFor(t: number) {
  // t in 0..1 -> interpolate between palette stops
  const scaled = t * (PALETTE.length - 1);
  const i = Math.min(PALETTE.length - 2, Math.floor(scaled));
  const f = scaled - i;
  const a = PALETTE[i];
  const b = PALETTE[i + 1];
  return {
    r: Math.round(a.r + (b.r - a.r) * f),
    g: Math.round(a.g + (b.g - a.g) * f),
    b: Math.round(a.b + (b.b - a.b) * f),
    alpha: a.a + (b.a - a.a) * f,
  };
}

export default function HeatmapOverlay({
  heatmap,
  opacity = 1,
}: {
  heatmap: CameraHeatmap | null;
  opacity?: number;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !heatmap) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const { grid, matrix, peak } = heatmap;
    // Render at grid resolution, then let CSS scale it up with smoothing —
    // far cheaper than drawing thousands of gradient circles, and the
    // blur is what makes it read as heat rather than as a mosaic.
    canvas.width = grid;
    canvas.height = grid;
    ctx.clearRect(0, 0, grid, grid);
    if (!peak) return;

    const image = ctx.createImageData(grid, grid);
    for (let y = 0; y < grid; y++) {
      for (let x = 0; x < grid; x++) {
        const count = matrix[y][x];
        const idx = (y * grid + x) * 4;
        if (!count) {
          image.data[idx + 3] = 0;
          continue;
        }
        // sqrt curve: without it a single very busy cell flattens
        // everything else to invisible.
        const t = Math.sqrt(count / peak);
        const { r, g, b, alpha } = colorFor(t);
        image.data[idx] = r;
        image.data[idx + 1] = g;
        image.data[idx + 2] = b;
        image.data[idx + 3] = Math.round(alpha * 255);
      }
    }
    ctx.putImageData(image, 0, 0);
  }, [heatmap]);

  if (!heatmap) return null;

  return (
    <canvas
      ref={canvasRef}
      style={{
        position: "absolute",
        inset: 0,
        width: "100%",
        height: "100%",
        pointerEvents: "none",
        opacity,
        filter: "blur(6px)",
        // Deliberately NOT mixBlendMode:"screen" — it looks great over a
        // dark frame and disappears completely over a brightly-lit shop
        // photo. The caller dims the backdrop instead, which reads
        // consistently whatever the camera is pointed at.
      }}
    />
  );
}

export function HeatmapLegend({ peak }: { peak: number }) {
  const stops = [0, 0.25, 0.5, 0.75, 1];
  return (
    <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", fontSize: "0.75rem" }}>
      <span className="muted">Quiet</span>
      <div style={{ display: "flex", height: 10, borderRadius: 3, overflow: "hidden", width: 120 }}>
        {stops.map((t) => {
          const { r, g, b } = colorFor(t);
          return <div key={t} style={{ flex: 1, background: `rgb(${r},${g},${b})` }} />;
        })}
      </div>
      <span className="muted">Busy</span>
      {peak > 0 && <span className="muted">· peak {peak} sighting(s) in one spot</span>}
    </div>
  );
}

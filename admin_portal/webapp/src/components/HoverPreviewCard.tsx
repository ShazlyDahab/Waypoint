import { useEffect, useState } from "react";
import { acquirePreviewSlot, releasePreviewSlot } from "../lib/previewPool";
import type { ConnectionState } from "../lib/api";

// The floating card a hovered/long-pressed marker shows. Pulls the LOW-RES
// SUBSTREAM snapshot (sub=true — see api/streams.py), not the main stream —
// this is a glance, not a monitor. Implemented as periodic still-image
// polling rather than a second live WebRTC connection per hovered marker:
// simpler, and it naturally satisfies the spec's "beyond the concurrency
// cap, fall back to a periodically refreshed still snapshot" by just
// polling slower once the cap (previewPool.ts) is hit, instead of running
// two entirely different code paths for "under cap" vs "over cap".
export default function HoverPreviewCard({
  cameraId,
  cameraName,
  status,
  x,
  y,
}: {
  cameraId: string;
  cameraName: string;
  status: ConnectionState;
  x: number;
  y: number;
}) {
  const [imgUrl, setImgUrl] = useState<string | null>(null);
  const [hasSlot, setHasSlot] = useState(false);

  useEffect(() => {
    const slotId = `preview-${cameraId}`;
    const got = acquirePreviewSlot(slotId);
    setHasSlot(got);
    const intervalMs = got ? 400 : 5000; // ~2.5 FPS under the cap, slow fallback over it

    let cancelled = false;
    let currentUrl: string | null = null;

    async function tick() {
      try {
        const resp = await fetch(`/api/streams/${encodeURIComponent(cameraId)}/snapshot?sub=true`);
        if (!resp.ok || cancelled) return;
        const blob = await resp.blob();
        const url = URL.createObjectURL(blob);
        if (currentUrl) URL.revokeObjectURL(currentUrl);
        currentUrl = url;
        if (!cancelled) setImgUrl(url);
      } catch {
        // Restreamer not running / camera offline — the card's status
        // line already conveys this; no need to also spam a broken-image icon.
      }
    }

    tick();
    const interval = setInterval(tick, intervalMs);
    return () => {
      cancelled = true;
      clearInterval(interval);
      if (currentUrl) URL.revokeObjectURL(currentUrl);
      if (got) releasePreviewSlot(slotId);
    };
  }, [cameraId]);

  return (
    <div
      style={{
        position: "fixed", left: x + 16, top: y - 8, zIndex: 50,
        width: 220, background: "var(--canvas)", border: "1px solid var(--canvas-rule)",
        borderRadius: 8, boxShadow: "0 4px 16px rgba(0,0,0,0.3)", overflow: "hidden",
        pointerEvents: "none",
      }}
    >
      <div style={{ width: "100%", height: 124, background: "#000", display: "flex", alignItems: "center", justifyContent: "center" }}>
        {imgUrl ? (
          <img src={imgUrl} alt={cameraName} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
        ) : (
          <span className="muted" style={{ color: "#999", fontSize: "0.75rem" }}>No preview</span>
        )}
      </div>
      <div style={{ padding: "0.5rem 0.6rem" }}>
        <div style={{ fontWeight: 600, fontSize: "0.85rem" }}>{cameraName}</div>
        <div className="muted" style={{ fontSize: "0.72rem", textTransform: "capitalize" }}>
          {status.replace("_", " ")}{!hasSlot && " · reduced rate (preview cap reached)"}
        </div>
      </div>
    </div>
  );
}

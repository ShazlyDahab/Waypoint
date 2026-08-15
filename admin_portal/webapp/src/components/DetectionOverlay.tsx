import { useEffect, useRef, useState } from "react";
import { DetectionBuffer, DetectionMessage } from "../lib/detectionSync";

export interface OverlayToggles {
  boxes: boolean;
  labels: boolean;
  confidence: boolean;
  trackIds: boolean;
  trails: boolean;
  timeInStore: boolean;
}

const DEFAULT_TOGGLES: OverlayToggles = {
  boxes: true, labels: true, confidence: false, trackIds: false, trails: false,
  timeInStore: true,
};
const TOGGLES_KEY = "detectionOverlayToggles";

export function loadToggles(): OverlayToggles {
  try {
    const raw = localStorage.getItem(TOGGLES_KEY);
    return raw ? { ...DEFAULT_TOGGLES, ...JSON.parse(raw) } : DEFAULT_TOGGLES;
  } catch {
    return DEFAULT_TOGGLES;
  }
}

export function saveToggles(t: OverlayToggles) {
  localStorage.setItem(TOGGLES_KEY, JSON.stringify(t));
}

const TRACK_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#4a3aa7"];
function colorForTrack(id: number) {
  return TRACK_COLORS[id % TRACK_COLORS.length];
}

// How long this person has been in the store, across every camera that has
// seen them — not how long they've been in this camera's frame.
function formatDuration(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const mins = Math.floor(seconds / 60);
  if (mins < 60) return `${mins}m ${Math.round(seconds % 60)}s`;
  return `${Math.floor(mins / 60)}h ${mins % 60}m`;
}

// Draws on a <canvas> positioned over the <video>'s VIDEO CONTENT box (not
// the element's own box — with objectFit:contain the rendered video is
// letterboxed inside the element at any window size), per spec. This is
// metadata overlay, not server-side burn-in — see ws.py's docstring for why.
export default function DetectionOverlay({
  cameraId,
  videoRef,
  toggles,
}: {
  cameraId: string;
  videoRef: React.RefObject<HTMLVideoElement>;
  toggles: OverlayToggles;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const bufferRef = useRef(new DetectionBuffer());
  const trailsRef = useRef<Map<number, [number, number][]>>(new Map());
  const [stale, setStale] = useState(true);

  useEffect(() => {
    const ws = new WebSocket(
      `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/detections/${encodeURIComponent(cameraId)}`
    );
    ws.onmessage = (ev) => {
      try {
        const msg: DetectionMessage = JSON.parse(ev.data);
        if (msg.type === "detections") bufferRef.current.push(msg);
      } catch {
        // ignore malformed frames
      }
    };
    return () => ws.close();
  }, [cameraId]);

  useEffect(() => {
    let raf = 0;

    function contentBox(video: HTMLVideoElement) {
      const rect = video.getBoundingClientRect();
      const videoAspect = video.videoWidth / video.videoHeight || 16 / 9;
      const boxAspect = rect.width / rect.height;
      let width = rect.width, height = rect.height, offsetX = 0, offsetY = 0;
      if (boxAspect > videoAspect) {
        width = rect.height * videoAspect;
        offsetX = (rect.width - width) / 2;
      } else {
        height = rect.width / videoAspect;
        offsetY = (rect.height - height) / 2;
      }
      return { left: rect.left + offsetX, top: rect.top + offsetY, width, height, parentRect: rect };
    }

    function draw() {
      raf = requestAnimationFrame(draw);
      const video = videoRef.current;
      const canvas = canvasRef.current;
      if (!video || !canvas || video.videoWidth === 0) return;

      const box = contentBox(video);
      canvas.style.left = `${box.left - box.parentRect.left}px`;
      canvas.style.top = `${box.top - box.parentRect.top}px`;
      canvas.style.width = `${box.width}px`;
      canvas.style.height = `${box.height}px`;
      if (canvas.width !== Math.round(box.width) || canvas.height !== Math.round(box.height)) {
        canvas.width = Math.round(box.width);
        canvas.height = Math.round(box.height);
      }
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      ctx.clearRect(0, 0, canvas.width, canvas.height);

      const now = Date.now() / 1000;
      const isStale = bufferRef.current.isStale(now);
      setStale((prev) => (prev !== isStale ? isStale : prev));
      if (isStale) return;

      const msg = bufferRef.current.nearest(now);
      if (!msg) return;

      for (const det of msg.detections) {
        const [x1, y1, x2, y2] = det.bbox;
        const px = x1 * canvas.width, py = y1 * canvas.height;
        const pw = (x2 - x1) * canvas.width, ph = (y2 - y1) * canvas.height;
        const color = colorForTrack(det.track_id);

        if (toggles.trails) {
          const pts = trailsRef.current.get(det.track_id) ?? [];
          const center: [number, number] = [px + pw / 2, py + ph];
          pts.push(center);
          if (pts.length > 20) pts.shift();
          trailsRef.current.set(det.track_id, pts);
          ctx.beginPath();
          pts.forEach(([tx, ty], i) => (i === 0 ? ctx.moveTo(tx, ty) : ctx.lineTo(tx, ty)));
          ctx.strokeStyle = color;
          ctx.lineWidth = 2;
          ctx.globalAlpha = 0.6;
          ctx.stroke();
          ctx.globalAlpha = 1;
        }

        if (toggles.boxes) {
          ctx.strokeStyle = color;
          ctx.lineWidth = 2;
          ctx.strokeRect(px, py, pw, ph);
        }

        if (toggles.labels || toggles.confidence || toggles.trackIds || toggles.timeInStore) {
          const parts: string[] = [];
          if (toggles.labels) parts.push(det.class);
          if (toggles.trackIds) {
            // visitor_id is the cross-camera identity; track_id only means
            // something within this one stream. Show the one that answers
            // "is this the same person I saw on the other camera?".
            parts.push(det.visitor_id != null ? `visitor #${det.visitor_id}` : `#${det.track_id}`);
          }
          if (toggles.confidence) parts.push(`${Math.round(det.confidence * 100)}%`);
          if (toggles.timeInStore && det.time_in_store_seconds != null) {
            parts.push(formatDuration(det.time_in_store_seconds));
          }
          const text = parts.join(" ");
          ctx.font = "12px sans-serif";
          const textWidth = ctx.measureText(text).width;
          ctx.fillStyle = color;
          ctx.fillRect(px, py - 16, textWidth + 8, 16);
          ctx.fillStyle = "#fff";
          ctx.fillText(text, px + 4, py - 4);
        }
      }
    }

    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [videoRef, toggles]);

  return (
    <>
      <canvas ref={canvasRef} style={{ position: "absolute", pointerEvents: "none" }} />
      {stale && (
        <div
          style={{
            position: "absolute", top: 8, left: 8, background: "rgba(220,38,38,0.85)", color: "#fff",
            padding: "0.25rem 0.6rem", borderRadius: 6, fontSize: "0.78rem", fontWeight: 600,
          }}
        >
          Detections unavailable
        </div>
      )}
    </>
  );
}

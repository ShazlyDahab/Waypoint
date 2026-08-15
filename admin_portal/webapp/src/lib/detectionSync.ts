// Detections arrive slightly ahead of or behind the displayed frame — this
// buffers recent messages and picks whichever is closest to "now" rather
// than always drawing the newest one. Both sides of the comparison are
// unix timestamps (frame_ts from the Python publisher's time.time(), "now"
// from the browser's Date.now()/1000): a real frame-accurate presentation
// timestamp isn't available for WebRTC in a cross-browser way (see the
// top-level plan's honest-gaps section) — wall-clock nearest-match is the
// achievable target here, not frame-exact sync.
//
// Kept dependency-free (no DOM, no WebSocket) so it's unit tested directly.

export interface Detection {
  class: string;
  confidence: number;
  track_id: number; // per-stream ByteTrack id — only meaningful on this camera
  visitor_id?: number | null; // cross-camera identity from reid_registry
  time_in_store_seconds?: number; // total across every camera, not this frame's camera
  bbox: [number, number, number, number]; // normalized x1,y1,x2,y2
}

export interface DetectionMessage {
  type: "detections";
  camera_id: string;
  frame_ts: number;
  frame_seq: number;
  source_width: number;
  source_height: number;
  detections: Detection[];
}

export const STALE_AFTER_SEC = 1.5;

export class DetectionBuffer {
  private messages: DetectionMessage[] = [];
  private maxSize: number;

  constructor(maxSize = 30) {
    this.maxSize = maxSize;
  }

  push(msg: DetectionMessage) {
    this.messages.push(msg);
    if (this.messages.length > this.maxSize) this.messages.shift();
  }

  size() {
    return this.messages.length;
  }

  /** The message whose frame_ts is closest to `atTime` — not just newest. */
  nearest(atTime: number): DetectionMessage | null {
    if (this.messages.length === 0) return null;
    let best = this.messages[0];
    let bestDiff = Math.abs(best.frame_ts - atTime);
    for (const m of this.messages) {
      const diff = Math.abs(m.frame_ts - atTime);
      if (diff < bestDiff) {
        best = m;
        bestDiff = diff;
      }
    }
    return best;
  }

  latest(): DetectionMessage | null {
    return this.messages.length ? this.messages[this.messages.length - 1] : null;
  }

  isStale(atTime: number, thresholdSec = STALE_AFTER_SEC): boolean {
    const latest = this.latest();
    if (!latest) return true;
    return atTime - latest.frame_ts > thresholdSec;
  }
}

import { describe, it, expect } from "vitest";
import { DetectionBuffer } from "./detectionSync";

function msg(frame_ts: number, frame_seq: number, count = 0) {
  return {
    type: "detections" as const,
    camera_id: "cam1",
    frame_ts,
    frame_seq,
    source_width: 1000,
    source_height: 800,
    detections: Array.from({ length: count }, (_, i) => ({
      class: "person", confidence: 0.9, track_id: i, bbox: [0, 0, 0.1, 0.1] as [number, number, number, number],
    })),
  };
}

describe("DetectionBuffer.nearest", () => {
  it("picks the message closest to the query time, not just the newest", () => {
    const buf = new DetectionBuffer();
    buf.push(msg(100.0, 1));
    buf.push(msg(100.5, 2));
    buf.push(msg(101.0, 3));
    // 100.6 is closer to 100.5 (seq 2) than to 101.0 (seq 3) or 100.0 (seq 1)
    expect(buf.nearest(100.6)?.frame_seq).toBe(2);
  });

  it("picks the newest when the query time is after all buffered messages", () => {
    const buf = new DetectionBuffer();
    buf.push(msg(100.0, 1));
    buf.push(msg(100.5, 2));
    expect(buf.nearest(200.0)?.frame_seq).toBe(2);
  });

  it("returns null when nothing has been pushed yet", () => {
    const buf = new DetectionBuffer();
    expect(buf.nearest(100.0)).toBeNull();
  });
});

describe("DetectionBuffer bounded size", () => {
  it("drops the oldest message once maxSize is exceeded", () => {
    const buf = new DetectionBuffer(3);
    buf.push(msg(1, 1));
    buf.push(msg(2, 2));
    buf.push(msg(3, 3));
    buf.push(msg(4, 4));
    expect(buf.size()).toBe(3);
    expect(buf.nearest(1)?.frame_seq).toBe(2); // seq 1 was evicted
  });
});

describe("DetectionBuffer.isStale", () => {
  it("is stale with no messages at all", () => {
    const buf = new DetectionBuffer();
    expect(buf.isStale(100.0)).toBe(true);
  });

  it("is not stale just under the 1.5s threshold", () => {
    const buf = new DetectionBuffer();
    buf.push(msg(100.0, 1));
    expect(buf.isStale(101.4)).toBe(false);
  });

  it("is stale just over the 1.5s threshold", () => {
    const buf = new DetectionBuffer();
    buf.push(msg(100.0, 1));
    expect(buf.isStale(101.6)).toBe(true);
  });

  it("respects a custom threshold", () => {
    const buf = new DetectionBuffer();
    buf.push(msg(100.0, 1));
    expect(buf.isStale(103.0, 5.0)).toBe(false);
  });
});

"""
Multi-Camera Store Dashboard — Re-ID v2 (gate-constrained + review queue)
------------------------------------------------------------------------------
Same one-process/one-thread-per-camera design as before, now wired to the
v2 registry: each track contributes several appearance samples over time,
gate exits narrow who a new arrival could possibly be, and ambiguous
matches go to review_queue.json instead of being silently merged.

Prerequisites:
  1. calibrate_zones.py run for every camera        -> zones_<id>.json (entrance line + handoffs)
  2. floor_map_builder.py run to get gate-link suggestions, then confirm
     them by hand in each zones_<id>.json "gates" -> "leads_to" field
  3. camera_topology.json filled in (fallback only, for cameras/gates
     without a confirmed link yet)

Install:
    pip install rfdetr supervision opencv-python numpy torch torchvision
"""

import math
import sqlite3
import sys
import cv2
import json
import time
import threading
from collections import deque
from pathlib import Path
import numpy as np
import supervision as sv
from rfdetr import RFDETRMedium
from rfdetr.assets.coco_classes import COCO_CLASSES

from reid_registry import ReIDEmbedder, GlobalIDRegistry, load_gates, load_topology, MAX_EMBEDDING_SAMPLES
import metrics_store
import ws_publisher

CAMERAS_FILE = "cameras.json"
OPS_CONSOLE_DB = Path(__file__).resolve().parent / "ops_console.db"
PROCESS_EVERY_N_FRAMES = 2
SUMMARY_PRINT_EVERY_SEC = 30
TRACK_LOST_AFTER_MISSED_FRAMES = 15
EMBEDDING_SAMPLE_INTERVAL_SEC = 2.0     # don't sample every frame — near-duplicates don't help
STATUS_PUBLISH_INTERVAL_SEC = 2.0        # how often a status (connection_state/person_count) message goes out
POSITION_SAMPLE_INTERVAL_SEC = 1.0       # heatmap resolution in time — per-frame would be ~90k rows/hr/person
VISIT_TOUCH_INTERVAL_SEC = 5.0           # how often a visitor's last_seen is pushed to visit_sessions
MIN_SERVICE_VISIT_SECONDS = 3.0          # below this, someone just walked past the counter
SERVICE_POINT_RELOAD_INTERVAL_SEC = 30   # pick up service points added in the portal without a restart

# Time-in-store per visitor, shared across camera threads: a visitor who
# walks entrance_cam -> checkout_cam is ONE visit, so first_seen has to live
# above any single camera worker.
visit_first_seen = {}
visit_last_touch = {}
visit_lock = threading.Lock()

# jobs.py already runs this headless (stdout redirected to a log file, no
# display attached) — cv2.imshow/waitKey error in that context regardless
# of the detection-streaming feature below; --no-display skips them, and
# admin_portal/jobs.py's start_dashboard() passes this flag.
NO_DISPLAY = "--no-display" in sys.argv

model = RFDETRMedium()
embedder = ReIDEmbedder()
registry = GlobalIDRegistry(gates_by_camera=load_gates(CAMERAS_FILE), topology=load_topology())
metrics_store.init_db()
ws_publisher.start()
print_lock = threading.Lock()

camera_stats = {}
stats_lock = threading.Lock()


def get_person_detections(frame):
    detections = model.predict(frame, threshold=0.5)
    idx = [i for i, cid in enumerate(detections.class_id) if COCO_CLASSES[cid] == "person"]
    return detections[idx]


def load_service_points(camera_id):
    """Service points (cashier/counter spots) are configured in the admin
    portal and live in ops_console.db, not in zones_<id>.json — they're
    portal-managed config, and this process only ever reads them. A missing
    database is normal (portal never started); return nothing rather than
    failing the camera worker over an optional feature."""
    if not OPS_CONSOLE_DB.exists():
        return []
    try:
        conn = sqlite3.connect(f"file:{OPS_CONSOLE_DB}?mode=ro", uri=True, timeout=5)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT name, x, y, radius FROM service_points WHERE camera_id = ?", (camera_id,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except sqlite3.Error as e:
        with print_lock:
            print(f"[{camera_id}] could not read service points: {e}")
        return []


def record_visit(visitor_id, now):
    """Returns how long this visitor has been in the store, in seconds.
    Writes to visit_sessions at most every VISIT_TOUCH_INTERVAL_SEC per
    visitor — the in-memory dict is what the live overlay reads, the table
    is for history."""
    with visit_lock:
        first = visit_first_seen.setdefault(visitor_id, now)
        should_touch = now - visit_last_touch.get(visitor_id, 0) >= VISIT_TOUCH_INTERVAL_SEC
        if should_touch:
            visit_last_touch[visitor_id] = now
    if should_touch:
        metrics_store.touch_visit(visitor_id, now)
    return now - first


def load_zone_config(camera_id):
    with open(f"zones_{camera_id}.json") as f:
        cfg = json.load(f)
    entrance_line = None
    if cfg["entrance_line"]:
        entrance_line = sv.LineZone(
            start=sv.Point(*cfg["entrance_line"]["start"]),
            end=sv.Point(*cfg["entrance_line"]["end"]),
        )
    return entrance_line


def camera_worker(camera_id, rtsp_url):
    try:
        entrance_line = load_zone_config(camera_id)
    except FileNotFoundError:
        print(f"[{camera_id}] No zones_{camera_id}.json yet — calibrate this camera "
              f"(Cameras -> Recalibrate) before starting the dashboard. Skipping.")
        return
    service_points = load_service_points(camera_id)
    last_service_reload_at = time.time()
    tracker = sv.ByteTrack()
    line_annotator = sv.LineZoneAnnotator() if entrance_line else None
    box_annotator = sv.BoxAnnotator()
    label_annotator = sv.LabelAnnotator()

    cap = cv2.VideoCapture(rtsp_url)
    if not cap.isOpened():
        print(f"[{camera_id}] Could not open stream.")
        return

    # local_id -> {"visitor_id", "samples": deque, "last_sample_at", "last_pos", "missed_frames",
    #              "last_service_check_at",
    #              "service_time": {point_name: accumulated_seconds}}
    local_state = {}
    frame_count = 0
    last_status_publish_at = 0
    last_position_sample_at = 0

    with stats_lock:
        camera_stats[camera_id] = {"entries": 0, "exits": 0}

    while True:
        ret, frame = cap.read()
        if not ret:
            ws_publisher.publish({
                "type": "status", "camera_id": camera_id,
                "connection_state": "offline", "person_count": 0,
            })
            time.sleep(2)
            cap.release()
            cap = cv2.VideoCapture(rtsp_url)
            continue

        frame_count += 1
        if frame_count % PROCESS_EVERY_N_FRAMES != 0:
            continue

        detections = get_person_detections(frame)
        detections = tracker.update_with_detections(detections)
        now = time.time()
        frame_h, frame_w = frame.shape[:2]
        seen_this_frame = set()
        time_in_store = {}  # local_id -> seconds, reused by the detection message below

        if now - last_service_reload_at >= SERVICE_POINT_RELOAD_INTERVAL_SEC:
            service_points = load_service_points(camera_id)
            last_service_reload_at = now

        for (x1, y1, x2, y2), local_id in zip(detections.xyxy, detections.tracker_id):
            seen_this_frame.add(local_id)
            foot_point = [(x1 + x2) / 2, y2]
            crop = frame[max(0, int(y1)):int(y2), max(0, int(x1)):int(x2)]

            if local_id not in local_state:
                emb = embedder.embed(crop)
                samples = deque(maxlen=MAX_EMBEDDING_SAMPLES)
                if emb is not None:
                    samples.append(emb)
                visitor_id, status = registry.report_new_track(camera_id, list(samples), crop, now)
                local_state[local_id] = {
                    "visitor_id": visitor_id, "samples": samples,
                    "last_sample_at": now, "last_pos": foot_point, "missed_frames": 0,
                    "last_service_check_at": now, "service_time": {},
                }
                metrics_store.log_visitor_event(visitor_id, camera_id, status, now)
                with print_lock:
                    print(f"[{camera_id}] track#{local_id} -> visitor#{visitor_id} ({status})")
            else:
                st = local_state[local_id]
                st["missed_frames"] = 0
                st["last_pos"] = foot_point
                if now - st["last_sample_at"] >= EMBEDDING_SAMPLE_INTERVAL_SEC:
                    emb = embedder.embed(crop)
                    if emb is not None:
                        st["samples"].append(emb)
                        st["last_sample_at"] = now

            time_in_store[local_id] = record_visit(local_state[local_id]["visitor_id"], now)

        for local_id in seen_this_frame:
            st = local_state[local_id]
            dt = now - st["last_service_check_at"]
            if dt > 0:
                # Service points are a plain radius test in normalized image
                # space — no polygon, no homography. "In front of the
                # cashier" is the catchment circle the user drew, nothing
                # more; that keeps this honest about what it measures.
                fx, fy = st["last_pos"][0] / frame_w, st["last_pos"][1] / frame_h
                for sp in service_points:
                    if math.hypot(fx - sp["x"], fy - sp["y"]) <= sp["radius"]:
                        st["service_time"][sp["name"]] = st["service_time"].get(sp["name"], 0.0) + dt
            st["last_service_check_at"] = now

        for local_id in list(local_state.keys()):
            if local_id not in seen_this_frame:
                local_state[local_id]["missed_frames"] += 1
                if local_state[local_id]["missed_frames"] >= TRACK_LOST_AFTER_MISSED_FRAMES:
                    st = local_state.pop(local_id)
                    registry.report_track_lost(
                        st["visitor_id"], camera_id, list(st["samples"]), st["last_pos"], now
                    )
                    for point_name, secs in st["service_time"].items():
                        if secs >= MIN_SERVICE_VISIT_SECONDS:
                            metrics_store.log_service_point_visit(
                                camera_id, point_name, st["visitor_id"], secs, now
                            )

        if entrance_line:
            crossed_in, crossed_out = entrance_line.trigger(detections)
            for did in range(len(crossed_in)):
                if crossed_in[did]:
                    metrics_store.log_entry_exit(camera_id, "in", now)
                if crossed_out[did]:
                    metrics_store.log_entry_exit(camera_id, "out", now)

        # Where people are standing, for the per-camera heatmap. Normalized
        # against the source frame so a camera resolution change doesn't
        # invalidate the history already recorded.
        if now - last_position_sample_at >= POSITION_SAMPLE_INTERVAL_SEC:
            metrics_store.log_positions(
                camera_id,
                [
                    (local_state[lid]["visitor_id"],
                     local_state[lid]["last_pos"][0] / frame_w,
                     local_state[lid]["last_pos"][1] / frame_h)
                    for lid in seen_this_frame
                ],
                now,
            )
            last_position_sample_at = now

        # Detection metadata over WebSocket — NOT burned into the frame.
        # track_id is the per-stream ByteTrack id (stable frame to frame for
        # THIS camera only); visitor_id is the cross-camera identity from
        # reid_registry, and is what time_in_store_seconds is measured
        # against — the same person walking entrance_cam -> checkout_cam
        # keeps one visitor_id and one running clock.
        ws_publisher.publish({
            "type": "detections", "camera_id": camera_id, "frame_ts": now, "frame_seq": frame_count,
            "source_width": frame_w, "source_height": frame_h,
            "detections": [
                {
                    "class": "person", "confidence": float(conf), "track_id": int(tid),
                    "visitor_id": local_state[tid]["visitor_id"] if tid in local_state else None,
                    "time_in_store_seconds": round(time_in_store.get(tid, 0.0), 1),
                    "bbox": [float(x1 / frame_w), float(y1 / frame_h), float(x2 / frame_w), float(y2 / frame_h)],
                }
                for (x1, y1, x2, y2), tid, conf in zip(
                    detections.xyxy, detections.tracker_id, detections.confidence
                )
            ],
        })
        if now - last_status_publish_at >= STATUS_PUBLISH_INTERVAL_SEC:
            ws_publisher.publish({
                "type": "status", "camera_id": camera_id,
                "connection_state": "online", "person_count": len(seen_this_frame),
            })
            last_status_publish_at = now

        with stats_lock:
            if entrance_line:
                camera_stats[camera_id]["entries"] = entrance_line.in_count
                camera_stats[camera_id]["exits"] = entrance_line.out_count

        if not NO_DISPLAY:
            labels = [f"T{lid}/V{local_state[lid]['visitor_id']}" for lid in detections.tracker_id]
            annotated = box_annotator.annotate(frame.copy(), detections)
            annotated = label_annotator.annotate(annotated, detections, labels)
            if entrance_line:
                annotated = line_annotator.annotate(annotated, entrance_line)
            for sp in service_points:
                cv2.circle(
                    annotated, (int(sp["x"] * frame_w), int(sp["y"] * frame_h)),
                    int(sp["radius"] * frame_w), (255, 0, 255), 2,
                )

            cv2.imshow(f"Store Ops - {camera_id}", annotated)
            cv2.waitKey(1)


def summary_loop():
    while True:
        time.sleep(SUMMARY_PRINT_EVERY_SEC)
        with print_lock, stats_lock:
            print(f"\n=== Store-wide summary {time.strftime('%H:%M:%S')} ===")
            for cam_id, stats in camera_stats.items():
                print(f"  {cam_id}: entries={stats.get('entries', 0)} exits={stats.get('exits', 0)}")
            with visit_lock:
                in_store = len(visit_first_seen)
            pending = len(registry.pending_reviews) - len(registry.confirmed_merges)
            print(f"  VISITORS SEEN: {registry.unique_visitor_count()} "
                  f"({pending} pending identity review — see review_queue.json)")
            print(f"  VISIT SESSIONS TRACKED: {in_store}")


def main():
    with open(CAMERAS_FILE) as f:
        cameras = json.load(f)

    threads = [threading.Thread(target=camera_worker, args=(c["id"], c["rtsp_url"]), daemon=True)
               for c in cameras]
    for t in threads:
        t.start()

    threading.Thread(target=summary_loop, daemon=True).start()

    print("Running. Press Ctrl+C to stop." if NO_DISPLAY else "Running. Press 'q' in a video window, or Ctrl+C, to stop.")
    try:
        while True:
            time.sleep(1)
            if not NO_DISPLAY and cv2.waitKey(1) & 0xFF == ord("q"):
                break
    except KeyboardInterrupt:
        pass
    if not NO_DISPLAY:
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()

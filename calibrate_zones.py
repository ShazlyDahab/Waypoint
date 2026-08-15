"""
Auto Zone Calibrator — RF-DETR + CCTV
----------------------------------------
Connects to each camera in cameras.json, watches real foot traffic for a
period of time, and PROPOSES zones based on observed behavior:

  - Queue zones    -> clusters of points where people stood still for a while
  - Entrance line  -> the frame edge where tracks most often appear/disappear
  - Dwell zone     -> convex hull of all observed foot positions

RF-DETR does not recognize "checkout counter" or "entrance" as concepts — it
only detects people. This script infers zones from HOW people move, then
saves a snapshot image with the proposed zones drawn on it so you can
visually confirm (or hand-edit the JSON) before running the live dashboard.

Run this during a real, reasonably busy period (not an empty store) — it
can't learn queue positions if nobody is queueing.

Install:
    pip install rfdetr supervision opencv-python numpy
"""

import cv2
import json
import time
import numpy as np
import supervision as sv
from rfdetr import RFDETRMedium
from rfdetr.assets.coco_classes import COCO_CLASSES

# ============ CONFIG ============
CAMERAS_FILE = "cameras.json"
OBSERVATION_SECONDS = 900        # 15 min. Longer = better zone quality.
PROCESS_EVERY_N_FRAMES = 3
EDGE_MARGIN_PX = 60              # distance from frame edge to count as an entry/exit point
CLUSTER_EPS_PX = 60              # max distance between points in the same handoff-point cluster
CLUSTER_MIN_POINTS = 4           # min points to form a handoff-point cluster
# =================================

model = RFDETRMedium()


def get_person_detections(frame):
    detections = model.predict(frame, threshold=0.5)
    idx = [i for i, cid in enumerate(detections.class_id) if COCO_CLASSES[cid] == "person"]
    return detections[idx]


def simple_cluster(points, eps, min_points):
    """Lightweight distance-based clustering (no sklearn/scipy dependency)."""
    n = len(points)
    if n == 0:
        return []
    visited = np.zeros(n, dtype=bool)
    labels = -np.ones(n, dtype=int)
    cluster_id = 0
    dist = np.linalg.norm(points[:, None, :] - points[None, :, :], axis=2)

    for i in range(n):
        if visited[i]:
            continue
        visited[i] = True
        neighbors = np.where(dist[i] <= eps)[0]
        if len(neighbors) < min_points:
            continue
        labels[i] = cluster_id
        queue = list(neighbors)
        while queue:
            j = queue.pop()
            if not visited[j]:
                visited[j] = True
                j_neighbors = np.where(dist[j] <= eps)[0]
                if len(j_neighbors) >= min_points:
                    queue.extend(list(j_neighbors))
            if labels[j] == -1:
                labels[j] = cluster_id
        cluster_id += 1
    return labels


def calibrate_camera(camera_id, rtsp_url):
    print(f"\n=== Calibrating '{camera_id}' ({rtsp_url}) ===")
    cap = cv2.VideoCapture(rtsp_url)
    if not cap.isOpened():
        print(f"  Could not open stream — skipping.")
        return

    tracker = sv.ByteTrack()
    track_history = {}       # tracker_id -> list of (t, x, y)
    edge_points = {"top": [], "bottom": [], "left": [], "right": []}
    last_frame = None

    frame_count = 0
    start = time.time()
    ret, frame = cap.read()
    if not ret:
        print("  Could not read first frame — skipping.")
        cap.release()
        return
    h, w = frame.shape[:2]

    while time.time() - start < OBSERVATION_SECONDS:
        ret, frame = cap.read()
        if not ret:
            time.sleep(1)
            continue
        last_frame = frame
        frame_count += 1
        if frame_count % PROCESS_EVERY_N_FRAMES != 0:
            continue

        detections = get_person_detections(frame)
        detections = tracker.update_with_detections(detections)
        now = time.time()

        for (x1, y1, x2, y2), tid in zip(detections.xyxy, detections.tracker_id):
            cx, cy = (x1 + x2) / 2, y2  # foot point
            track_history.setdefault(tid, []).append((now, cx, cy))

            # Edge proximity -> candidate entry/exit point
            if cy <= EDGE_MARGIN_PX:
                edge_points["top"].append((cx, cy))
            if cy >= h - EDGE_MARGIN_PX:
                edge_points["bottom"].append((cx, cy))
            if cx <= EDGE_MARGIN_PX:
                edge_points["left"].append((cx, cy))
            if cx >= w - EDGE_MARGIN_PX:
                edge_points["right"].append((cx, cy))

        elapsed = int(time.time() - start)
        if elapsed % 60 == 0:
            print(f"  ...observing ({elapsed}s / {OBSERVATION_SECONDS}s, "
                  f"{len(track_history)} people tracked so far)")

    cap.release()

    # ---- Derive entrance line from busiest edge (counts store entries/exits) ----
    edge_counts = {k: len(v) for k, v in edge_points.items()}
    entrance_line = None
    if any(edge_counts.values()):
        busiest = max(edge_counts, key=edge_counts.get)
        pts = np.array(edge_points[busiest])
        if busiest in ("top", "bottom"):
            y = 0 if busiest == "top" else h
            x_min, x_max = float(pts[:, 0].min()), float(pts[:, 0].max())
            entrance_line = {"edge": busiest, "start": [x_min, y], "end": [x_max, y]}
        else:
            x = 0 if busiest == "left" else w
            y_min, y_max = float(pts[:, 1].min()), float(pts[:, 1].max())
            entrance_line = {"edge": busiest, "start": [x, y_min], "end": [x, y_max]}

    # ---- Derive GATES: distinct exit/entry clusters, used for cross-camera Re-ID ----
    # A gate is a specific spot where people consistently enter/exit — e.g. a
    # doorway, or a walkway toward another camera. A camera can have several
    # gates (e.g. front door AND a path toward the checkout area). Unlike the
    # single entrance_line above, gates exist ONLY to narrow "who could this
    # new arrival possibly be" for Re-ID — each gate's "leads_to" field starts
    # empty and gets filled in either by hand or by floor_map_builder.py's
    # geometry-based suggestion (see that script).
    all_edge_points = []
    for pts_list in edge_points.values():
        all_edge_points.extend(pts_list)

    gates = []
    if all_edge_points:
        pts = np.array(all_edge_points)
        labels = simple_cluster(pts, CLUSTER_EPS_PX, CLUSTER_MIN_POINTS)
        for cid in sorted(set(labels)):
            if cid == -1:
                continue
            cluster_pts = pts[labels == cid].astype(np.float32)
            hull = cv2.convexHull(cluster_pts)
            gates.append({
                "gate_id": f"gate_{len(gates) + 1}",
                "centroid": cluster_pts.mean(axis=0).tolist(),
                "polygon": hull.reshape(-1, 2).tolist(),
                "point_count": int(len(cluster_pts)),
                "leads_to": None,   # fill in by hand, or via floor_map_builder.py suggestions
            })

    # ---- Dwell zone = convex hull of all observed positions ----
    all_points = [(p[1], p[2]) for hist in track_history.values() for p in hist]
    dwell_polygon = []
    if len(all_points) >= 3:
        hull = cv2.convexHull(np.array(all_points, dtype=np.float32))
        dwell_polygon = hull.reshape(-1, 2).tolist()

    config = {
        "camera_id": camera_id,
        "rtsp_url": rtsp_url,
        "frame_size": [w, h],
        "observation_seconds": OBSERVATION_SECONDS,
        "people_observed": len(track_history),
        "entrance_line": entrance_line,
        "gates": gates,
        "coverage_area": dwell_polygon,
        "calibrated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    # ---- Save config + a snapshot for visual confirmation ----
    config_path = f"zones_{camera_id}.json"
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)

    if last_frame is not None:
        snapshot = last_frame.copy()
        if entrance_line:
            p1 = tuple(map(int, entrance_line["start"]))
            p2 = tuple(map(int, entrance_line["end"]))
            cv2.line(snapshot, p1, p2, (255, 0, 0), 3)
            cv2.putText(snapshot, "Entrance", p1, cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 0), 2)
        if dwell_polygon:
            poly = np.array(dwell_polygon, dtype=np.int32)
            cv2.polylines(snapshot, [poly], True, (0, 255, 0), 1)
        for gate in gates:
            poly = np.array(gate["polygon"], dtype=np.int32)
            cv2.polylines(snapshot, [poly], True, (255, 0, 255), 2)
            cv2.putText(snapshot, gate["gate_id"], tuple(poly[0]),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 255), 1)
        snapshot_path = f"calibration_snapshot_{camera_id}.png"
        cv2.imwrite(snapshot_path, snapshot)
        print(f"  Snapshot saved: {snapshot_path}  <-- open this and confirm zones look right")

    print(f"  Config saved: {config_path}")
    print(f"  {len(gates)} handoff point(s) proposed, "
          f"entrance placed on '{entrance_line['edge'] if entrance_line else 'NONE — not enough edge traffic'}' edge, "
          f"{len(track_history)} people observed.")
    print(f"  NOTE: gate 'leads_to' fields are empty — run floor_map_builder.py for link "
          f"suggestions, or fill zones_{camera_id}.json by hand before using Re-ID.")


def main():
    import sys

    with open(CAMERAS_FILE) as f:
        cameras = json.load(f)

    if len(sys.argv) > 1:
        wanted = set(sys.argv[1:])
        cameras = [c for c in cameras if c["id"] in wanted]
        missing = wanted - {c["id"] for c in cameras}
        if missing:
            print(f"Unknown camera id(s), skipping: {', '.join(sorted(missing))}")
        if not cameras:
            print("No matching cameras to calibrate.")
            return

    for cam in cameras:
        calibrate_camera(cam["id"], cam["rtsp_url"])

    print("\nDone. Review each calibration_snapshot_*.png before running the dashboard.")
    print("If a zone looks wrong, hand-edit the matching zones_<camera_id>.json directly.")


if __name__ == "__main__":
    main()

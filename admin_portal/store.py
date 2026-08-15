"""
Thin JSON read/write helpers over the same config files the pipeline
scripts (calibrate_zones.py, multi_camera_dashboard.py, reid_registry.py,
resolve_reviews.py) already use. The portal never invents
its own storage format — it edits the exact files those scripts read, so
nothing needs to change about how the pipeline runs outside the portal.
"""

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

CAMERAS_FILE = PROJECT_ROOT / "cameras.json"
TOPOLOGY_FILE = PROJECT_ROOT / "camera_topology.json"
REVIEW_QUEUE_FILE = PROJECT_ROOT / "review_queue.json"
MERGES_FILE = PROJECT_ROOT / "confirmed_merges.json"


def load_json(path: Path, default):
    if not path.exists():
        return default
    with open(path) as f:
        return json.load(f)


def save_json(path: Path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def load_cameras():
    return load_json(CAMERAS_FILE, [])


def save_cameras(cameras):
    save_json(CAMERAS_FILE, cameras)


def get_camera(camera_id):
    for c in load_cameras():
        if c["id"] == camera_id:
            return c
    return None


def zones_path(camera_id):
    return PROJECT_ROOT / f"zones_{camera_id}.json"


def load_zones(camera_id):
    return load_json(zones_path(camera_id), None)


def save_zones(camera_id, data):
    save_json(zones_path(camera_id), data)


def calibration_snapshot_path(camera_id):
    return PROJECT_ROOT / f"calibration_snapshot_{camera_id}.png"


def load_topology():
    return load_json(TOPOLOGY_FILE, {})


def save_topology(data):
    save_json(TOPOLOGY_FILE, data)


def load_review_queue():
    return load_json(REVIEW_QUEUE_FILE, [])


def save_review_queue(data):
    save_json(REVIEW_QUEUE_FILE, data)


def load_merges():
    return load_json(MERGES_FILE, {})


def save_merges(data):
    save_json(MERGES_FILE, data)

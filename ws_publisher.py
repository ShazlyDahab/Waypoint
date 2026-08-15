"""
Runs INSIDE multi_camera_dashboard.py's process. One background thread
(not one per camera) owns a single WebSocket client connection to the
admin portal's ingestion endpoint, draining a queue that each camera_worker
thread pushes small dicts into per processed frame. Reconnects with
exponential backoff so start order between the dashboard and the portal
doesn't matter — this can come up before or after admin_portal.main.

Detection message schema (one per processed frame per camera):
    {"type": "detections", "camera_id": str, "frame_ts": float (unix time),
     "frame_seq": int, "source_width": int, "source_height": int,
     "detections": [{"class": str, "confidence": float, "track_id": int,
                      "bbox": [x1, y1, x2, y2]}]}   # bbox normalized 0..1,
                                                      # top-left/bottom-right

Status message (periodic, also drives the floor-plan occupancy badge):
    {"type": "status", "camera_id": str, "connection_state":
     "online"|"offline", "person_count": int}
"""

import json
import queue
import threading
import time

try:
    from websockets.sync.client import connect as ws_connect
except ImportError:
    ws_connect = None

INGEST_URL = "ws://127.0.0.1:8800/ws/ingest/detections"
_queue: "queue.Queue[dict]" = queue.Queue(maxsize=2000)
_started = False


def publish(message: dict):
    """Non-blocking — a camera worker thread must never stall on this.
    Drops the message if the queue is backed up rather than applying
    backpressure to detection/tracking work."""
    try:
        _queue.put_nowait(message)
    except queue.Full:
        pass


def _run():
    if ws_connect is None:
        print("[ws_publisher] the 'websockets' package isn't installed — detection streaming disabled "
              "(pip install websockets). Detection/tracking itself is unaffected.")
        return
    backoff = 1
    while True:
        try:
            with ws_connect(INGEST_URL, open_timeout=5) as ws:
                print(f"[ws_publisher] connected to {INGEST_URL}")
                backoff = 1
                while True:
                    message = _queue.get()
                    ws.send(json.dumps(message))
        except Exception as e:
            print(f"[ws_publisher] connection lost ({e}) — retrying in {backoff}s")
            time.sleep(backoff)
            backoff = min(backoff * 2, 30)


def start():
    """Idempotent — safe to call once at module import time even if
    multiple camera threads exist; only one publisher thread is ever
    started."""
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=_run, daemon=True, name="ws-publisher").start()

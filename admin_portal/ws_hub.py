"""
In-process asyncio pub/sub for detection + status messages.

multi_camera_dashboard.py (a separate OS process, launched via jobs.py)
pushes messages in over one WebSocket connection (/ws/ingest/detections).
This hub fans them out to:
  - per-camera subscribers (/ws/detections/{camera_id}) — opened only while
    a live view or an active hover-preview actually needs it.
  - ONE shared status channel (/ws/status) that the floor-plan page opens
    once for every camera's connection_state/person_count — this is what
    satisfies "30 markers, one shared channel, not one connection each."

Bounded per-subscriber queues drop the oldest message rather than block the
ingest handler if a slow/stalled subscriber isn't draining fast enough —
detections are inherently perishable (a stale one is worse than a dropped
one), so backpressure here should never propagate back to the publisher.
"""

import asyncio


def _put_latest(q: asyncio.Queue, message: dict):
    if q.full():
        try:
            q.get_nowait()
        except asyncio.QueueEmpty:
            pass
    try:
        q.put_nowait(message)
    except asyncio.QueueFull:
        pass


class DetectionHub:
    def __init__(self):
        self.latest_detections: dict[str, dict] = {}
        self.latest_status: dict[str, dict] = {}
        self._detection_subs: dict[str, set[asyncio.Queue]] = {}
        self._status_subs: set[asyncio.Queue] = set()
        self._scan_subs: dict[int, set[asyncio.Queue]] = {}

    def subscribe_detections(self, camera_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=30)
        self._detection_subs.setdefault(camera_id, set()).add(q)
        return q

    def unsubscribe_detections(self, camera_id: str, q: asyncio.Queue):
        self._detection_subs.get(camera_id, set()).discard(q)

    def subscribe_status(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._status_subs.add(q)
        return q

    def unsubscribe_status(self, q: asyncio.Queue):
        self._status_subs.discard(q)

    def subscribe_scan(self, scan_id: int) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._scan_subs.setdefault(scan_id, set()).add(q)
        return q

    def unsubscribe_scan(self, scan_id: int, q: asyncio.Queue):
        self._scan_subs.get(scan_id, set()).discard(q)

    async def publish(self, message: dict):
        msg_type = message.get("type")
        camera_id = message.get("camera_id")
        if msg_type == "detections" and camera_id:
            self.latest_detections[camera_id] = message
            for q in list(self._detection_subs.get(camera_id, ())):
                _put_latest(q, message)
        elif msg_type == "status" and camera_id:
            self.latest_status[camera_id] = message
            for q in list(self._status_subs):
                _put_latest(q, message)

    async def publish_scan_progress(self, scan_id: int, message: dict):
        for q in list(self._scan_subs.get(scan_id, ())):
            _put_latest(q, message)


hub = DetectionHub()

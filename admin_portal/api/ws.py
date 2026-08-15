"""
WebSocket routes for the detection bridge (see ws_hub.py for the fan-out
design and why: metadata overlay, not server-side burn-in — the browser
draws boxes on a canvas over the <video>, decoded once here and reused by
every viewer AND by the floor-plan occupancy badges, instead of a GPU
re-encode per viewer).

No auth on /ingest/detections, consistent with the rest of this app's
trusted-network-only posture — anyone on the LAN could inject fake
detection messages into it. Same posture as everything else today, called
out explicitly rather than silently inherited (see the top-level plan's
"honest gaps" section).
"""

import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..ws_hub import hub

router = APIRouter()


@router.websocket("/ingest/detections")
async def ingest_detections(ws: WebSocket):
    """multi_camera_dashboard.py connects here as a client (see
    ws_publisher.py) — one connection for the whole process, not one per
    camera thread."""
    await ws.accept()
    try:
        while True:
            raw = await ws.receive_text()
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                continue
            await hub.publish(message)
    except WebSocketDisconnect:
        pass


@router.websocket("/detections/{camera_id}")
async def subscribe_detections(ws: WebSocket, camera_id: str):
    await ws.accept()
    q = hub.subscribe_detections(camera_id)
    try:
        if camera_id in hub.latest_detections:
            await ws.send_text(json.dumps(hub.latest_detections[camera_id]))
        while True:
            message = await q.get()
            await ws.send_text(json.dumps(message))
    except WebSocketDisconnect:
        pass
    finally:
        hub.unsubscribe_detections(camera_id, q)


@router.websocket("/status")
async def subscribe_status(ws: WebSocket):
    """The ONE shared channel every floor-plan page opens, regardless of
    how many cameras are on it — see ws_hub.py's docstring."""
    await ws.accept()
    q = hub.subscribe_status()
    try:
        for message in hub.latest_status.values():
            await ws.send_text(json.dumps(message))
        while True:
            message = await q.get()
            await ws.send_text(json.dumps(message))
    except WebSocketDisconnect:
        pass
    finally:
        hub.unsubscribe_status(q)


@router.websocket("/discovery/{scan_id}")
async def subscribe_discovery_scan(ws: WebSocket, scan_id: int):
    await ws.accept()
    q = hub.subscribe_scan(scan_id)
    try:
        while True:
            message = await q.get()
            await ws.send_text(json.dumps(message))
    except WebSocketDisconnect:
        pass
    finally:
        hub.unsubscribe_scan(scan_id, q)

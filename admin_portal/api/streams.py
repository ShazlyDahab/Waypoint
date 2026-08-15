"""
Proxies the browser's WebRTC signaling, HLS, and snapshot requests through
to go2rtc's LOCALHOST-only API — the browser never talks to go2rtc
directly and never sees an RTSP URL or credential (see restreamer.py for
why go2rtc, and the localhost-binding rationale).

Every route here fails clearly and fast if the restreamer job isn't
running, rather than hanging or returning a confusing low-level connection
error — this is one of the "failure states are first-class" requirements
from the spec, and the one most likely to be hit by anyone running this
code without a real camera or the go2rtc binary installed yet.
"""

import httpx
from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from .. import restreamer, store

router = APIRouter()


def _require_restreamer():
    if not restreamer.is_running():
        raise HTTPException(
            503,
            "The restreamer (go2rtc) isn't running. Start it from the Jobs page, or run "
            "`python -c \"from admin_portal import restreamer; restreamer.start()\"` — "
            "it needs the go2rtc binary at bin/go2rtc (see admin_portal/restreamer.py).",
        )


def _require_camera(camera_id: str):
    if store.get_camera(camera_id) is None:
        raise HTTPException(404, "Unknown camera")


class WebRTCOfferIn(BaseModel):
    sdp: str
    type: str = "offer"


@router.post("/{camera_id}/webrtc-offer")
async def webrtc_offer(camera_id: str, body: WebRTCOfferIn):
    _require_camera(camera_id)
    _require_restreamer()
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{restreamer.GO2RTC_API_BASE}/api/webrtc",
                params={"src": camera_id},
                json={"type": body.type, "sdp": body.sdp},
            )
    except httpx.RequestError as e:
        raise HTTPException(502, f"Could not reach the restreamer: {e}")
    if resp.status_code != 200:
        raise HTTPException(502, f"Restreamer rejected the offer: {resp.text[:300]}")
    return resp.json()


@router.get("/{camera_id}/snapshot")
async def snapshot(camera_id: str, sub: bool = False):
    _require_camera(camera_id)
    _require_restreamer()
    src = f"{camera_id}_sub" if sub else camera_id
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{restreamer.GO2RTC_API_BASE}/api/frame.jpeg", params={"src": src})
    except httpx.RequestError as e:
        raise HTTPException(502, f"Could not reach the restreamer: {e}")
    if resp.status_code != 200:
        raise HTTPException(502, f"Restreamer could not produce a snapshot: {resp.text[:300]}")
    # go2rtc answers 200 with a ZERO-BYTE body when it can't pull a frame
    # (camera unreachable, wrong credentials, stream not yet connected).
    # Passing that through as image/jpeg hands the browser a "valid" empty
    # image that renders as a silent broken icon, so treat an empty or
    # absurdly small body as the failure it actually is.
    if len(resp.content) < 128:
        raise HTTPException(
            502,
            f"No frame available from '{camera_id}'. The restreamer is running but couldn't pull "
            "a picture — usually the camera is unreachable, the credentials are wrong, or the "
            "stream hasn't connected yet.",
        )
    return Response(content=resp.content, media_type="image/jpeg")


@router.get("/{camera_id}/hls/{filename}")
async def hls_passthrough(camera_id: str, filename: str, sub: bool = False):
    _require_camera(camera_id)
    _require_restreamer()
    src = f"{camera_id}_sub" if sub else camera_id
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{restreamer.GO2RTC_API_BASE}/api/stream.m3u8", params={"src": src})
    except httpx.RequestError as e:
        raise HTTPException(502, f"Could not reach the restreamer: {e}")
    # Same empty-200 trap as the snapshot route above — an empty playlist
    # makes the player fail with no explanation.
    if resp.status_code != 200 or not resp.content.strip():
        raise HTTPException(
            502,
            f"No HLS playlist available for '{camera_id}' — the camera is most likely "
            "unreachable or the stream hasn't connected yet.",
        )
    return Response(content=resp.content, media_type="application/vnd.apple.mpegurl")


@router.get("/{camera_id}/status")
def stream_status(camera_id: str):
    _require_camera(camera_id)
    return {"restreamer_running": restreamer.is_running()}

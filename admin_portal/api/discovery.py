"""
Discovery scan orchestration: ONVIF WS-Discovery and subnet-sweep scans run
as asyncio background tasks (pure I/O, no subprocess needed — unlike the
GPU-loading pipeline scripts in jobs.py). Progress is written incrementally
to the discovery_scans/discovered_devices tables (durable, survives a
dropped client) and also pushed live over ws://.../ws/discovery/{scan_id}.

Nothing is added as a real camera automatically — every discovered device
sits in a review list until a human picks credentials, names it, and adds
it. Re-scans dedup against existing cameras by MAC -> serial -> IP (see
discovery/dedup.py) so a camera that changed IP via DHCP updates in place
instead of creating a duplicate.
"""

import asyncio
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import db, security, store
from ..discovery.dedup import match_existing_camera
from ..discovery.subnet_sweep import RangeTooLarge, sweep_subnet
from ..discovery.onvif_discovery import discover_devices, get_device_info
from ..rtsp_paths import build_rtsp_url, guess_rtsp_paths
from ..ws_hub import hub

router = APIRouter()

_cancel_flags: dict = {}


def _existing_cameras_for_dedup():
    conn = db.get_conn()
    rows = conn.execute("SELECT camera_id, mac, serial, ip FROM camera_network").fetchall()
    return [dict(r) for r in rows]


async def _publish_progress(scan_id: int, payload: dict):
    await hub.publish_scan_progress(scan_id, {"type": "discovery_progress", "scan_id": scan_id, **payload})


class StartScanIn(BaseModel):
    method: str  # "onvif" | "subnet"
    cidr: Optional[str] = None
    force: bool = False


@router.post("/scans")
async def start_scan(body: StartScanIn):
    if body.method not in ("onvif", "subnet"):
        raise HTTPException(400, "method must be 'onvif' or 'subnet'")
    if body.method == "subnet" and not body.cidr:
        raise HTTPException(400, "cidr is required for a subnet sweep")

    conn = db.get_conn()
    ts = db.now()
    cur = conn.execute(
        "INSERT INTO discovery_scans (method, cidr, status, started_at) VALUES (?, ?, 'running', ?)",
        (body.method, body.cidr, ts),
    )
    conn.commit()
    scan_id = cur.lastrowid
    _cancel_flags[scan_id] = False

    asyncio.create_task(_run_scan(scan_id, body.method, body.cidr, body.force))
    return {"scan_id": scan_id}


async def _run_scan(scan_id: int, method: str, cidr: Optional[str], force: bool):
    conn = db.get_conn()
    try:
        if method == "onvif":
            devices = await asyncio.to_thread(discover_devices, 8.0)
            hosts_total = len(devices)
            conn.execute("UPDATE discovery_scans SET hosts_total = ? WHERE id = ?", (hosts_total, scan_id))
            conn.commit()
            for i, d in enumerate(devices):
                if _cancel_flags.get(scan_id):
                    break
                _record_device(scan_id, ip=d.get("ip"), onvif_xaddr=d.get("onvif_xaddr"))
                conn.execute("UPDATE discovery_scans SET hosts_scanned = ? WHERE id = ?", (i + 1, scan_id))
                conn.commit()
                await _publish_progress(scan_id, {"hosts_scanned": i + 1, "hosts_total": hosts_total})
        else:
            try:
                from ..discovery.subnet_sweep import parse_cidr
                hosts_total = len(parse_cidr(cidr, force=force))
            except RangeTooLarge as e:
                conn.execute(
                    "UPDATE discovery_scans SET status='error', error=?, ended_at=? WHERE id = ?",
                    (str(e), db.now(), scan_id),
                )
                conn.commit()
                return
            conn.execute("UPDATE discovery_scans SET hosts_total = ? WHERE id = ?", (hosts_total, scan_id))
            conn.commit()

            def on_progress(scanned, total):
                conn.execute("UPDATE discovery_scans SET hosts_scanned = ? WHERE id = ?", (scanned, scan_id))
                conn.commit()
                asyncio.create_task(_publish_progress(scan_id, {"hosts_scanned": scanned, "hosts_total": total}))

            results = await sweep_subnet(
                cidr, force=force, on_progress=on_progress,
                should_cancel=lambda: _cancel_flags.get(scan_id, False),
            )
            for r in results:
                _record_device(
                    scan_id, ip=r.ip, http_banner=r.http_banner,
                    guessed_manufacturer=r.guessed_manufacturer, probe_ports=r.open_ports,
                )

        conn.execute(
            "UPDATE discovery_scans SET status = ?, ended_at = ? WHERE id = ?",
            ("cancelled" if _cancel_flags.get(scan_id) else "done", db.now(), scan_id),
        )
        conn.commit()
        await _publish_progress(scan_id, {"status": "done"})
    except Exception as e:
        conn.execute(
            "UPDATE discovery_scans SET status='error', error=?, ended_at=? WHERE id = ?",
            (str(e), db.now(), scan_id),
        )
        conn.commit()
    finally:
        _cancel_flags.pop(scan_id, None)


def _record_device(scan_id, ip=None, mac=None, onvif_xaddr=None, probe_ports=None,
                    http_banner=None, guessed_manufacturer=None):
    conn = db.get_conn()
    existing = _existing_cameras_for_dedup()
    matched_id, reason, ip_changed = match_existing_camera(mac, None, ip, existing)
    conn.execute(
        "INSERT INTO discovered_devices (scan_id, ip, mac, onvif_xaddr, probe_ports, http_banner, "
        "guessed_manufacturer, matched_camera_id, match_reason, ip_changed, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (scan_id, ip, mac, onvif_xaddr, str(probe_ports) if probe_ports else None, http_banner,
         guessed_manufacturer, matched_id, reason, int(ip_changed), db.now()),
    )
    conn.commit()


@router.get("/scans/{scan_id}")
def get_scan(scan_id: int):
    conn = db.get_conn()
    row = conn.execute("SELECT * FROM discovery_scans WHERE id = ?", (scan_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Scan not found")
    return dict(row)


@router.get("/scans/{scan_id}/devices")
def list_scan_devices(scan_id: int):
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT * FROM discovered_devices WHERE scan_id = ? ORDER BY id", (scan_id,)
    ).fetchall()
    return [dict(r) for r in rows]


@router.post("/scans/{scan_id}/cancel")
def cancel_scan(scan_id: int):
    if scan_id not in _cancel_flags:
        raise HTTPException(404, "Scan not running")
    _cancel_flags[scan_id] = True
    return {"ok": True}


@router.post("/devices/{device_id}/dismiss")
def dismiss_device(device_id: int):
    conn = db.get_conn()
    conn.execute("UPDATE discovered_devices SET dismissed = 1 WHERE id = ?", (device_id,))
    conn.commit()
    return {"ok": True}


class AddDeviceIn(BaseModel):
    camera_id: str
    name: str
    username: str
    password: str
    rtsp_port: int = 554
    manufacturer: Optional[str] = None


@router.post("/devices/{device_id}/add")
def add_discovered_device(device_id: int, body: AddDeviceIn):
    conn = db.get_conn()
    device = conn.execute("SELECT * FROM discovered_devices WHERE id = ?", (device_id,)).fetchone()
    if device is None:
        raise HTTPException(404, "Discovered device not found")

    cameras = store.load_cameras()
    if any(c["id"] == body.camera_id for c in cameras):
        raise HTTPException(409, f"Camera id '{body.camera_id}' already exists")

    ts = db.now()
    cred_cur = conn.execute(
        "INSERT INTO credentials (label, username, encrypted_password, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        (f"{body.name} credentials", body.username, security.encrypt_password(body.password), ts, ts),
    )
    credential_id = cred_cur.lastrowid

    manufacturer = body.manufacturer or device["guessed_manufacturer"]
    paths = guess_rtsp_paths(manufacturer)
    rtsp_url = build_rtsp_url(device["ip"], body.rtsp_port, body.username, body.password, paths["main"])

    cameras.append({"id": body.camera_id, "name": body.name, "rtsp_url": rtsp_url})
    store.save_cameras(cameras)

    conn.execute(
        "INSERT INTO camera_network (camera_id, ip, mac, manufacturer, main_stream_uri, credential_id, "
        "connection_state, updated_at) VALUES (?, ?, ?, ?, ?, ?, 'not_configured', ?)",
        (body.camera_id, device["ip"], device["mac"], manufacturer, rtsp_url, credential_id, ts),
    )
    conn.execute("UPDATE discovered_devices SET added_as_camera_id = ? WHERE id = ?", (body.camera_id, device_id))
    conn.commit()
    return {"ok": True, "camera_id": body.camera_id}

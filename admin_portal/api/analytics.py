"""
Per-camera analytics: the standing-position heatmap and service points
(cashier/counter spots).

Everything here works in ONE camera's own image space, normalized 0-1.
There is deliberately no floor plan and no homography: the earlier
floor-plan/floor-heatmap approach needed a top-down blueprint plus a
perspective transform per camera to place a person on a store map, which
is a lot of calibration for a result the user can't easily sanity-check.
Drawing heat directly over the camera's own view is immediately legible —
you see the aisle, and you see the hot spot on that aisle — and it needs
no calibration at all beyond the camera already being pointed somewhere.

The tradeoff worth naming: heat is per-camera, so it can't be summed
across cameras into one store-wide map, and two cameras overlooking the
same aisle will each show their own view of it rather than one merged
picture.
"""

import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .. import db, store

PROJECT_ROOT = store.PROJECT_ROOT
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import metrics_store  # noqa: E402

router = APIRouter()

VALID_DAYS = (1, 7, 30, 90)


# ------------------------------------------------------------- heatmap ------

@router.get("/cameras/{camera_id}/heatmap")
def camera_heatmap(camera_id: str, days: int = 7, grid: int = 48):
    """Counts of recorded standing positions, bucketed into a grid x grid
    matrix over the camera's normalized image space. The client scales this
    to whatever size the video is actually rendered at."""
    if store.get_camera(camera_id) is None:
        raise HTTPException(404, "Unknown camera")
    if days not in VALID_DAYS:
        raise HTTPException(400, f"days must be one of {VALID_DAYS}")
    grid = max(8, min(96, grid))
    result = metrics_store.position_heatmap(camera_id, days=days, grid=grid)
    return {"camera_id": camera_id, "days": days, **result}


@router.get("/cameras/{camera_id}/reference-frame")
def camera_reference_frame(camera_id: str):
    """A still image of what this camera sees, used as the backdrop for the
    heatmap when there's no live video (go2rtc not running, or just viewing
    history). Reuses the snapshot calibrate_zones.py already saves — no new
    capture path, and it works with the pipeline stopped."""
    if store.get_camera(camera_id) is None:
        raise HTTPException(404, "Unknown camera")
    snapshot = store.calibration_snapshot_path(camera_id)
    if not snapshot.is_file():
        raise HTTPException(
            404,
            "No reference frame for this camera yet — run calibration for it "
            "(Cameras -> the camera -> Recalibrate) to capture one.",
        )
    return FileResponse(snapshot)


# ------------------------------------------------------- service points -----

class ServicePointIn(BaseModel):
    name: str
    kind: str = "cashier"
    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)
    radius: float = Field(default=0.12, gt=0.0, le=1.0)


@router.get("/cameras/{camera_id}/service-points")
def list_service_points(camera_id: str):
    if store.get_camera(camera_id) is None:
        raise HTTPException(404, "Unknown camera")
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT * FROM service_points WHERE camera_id = ? ORDER BY id", (camera_id,)
    ).fetchall()
    return [dict(r) for r in rows]


@router.post("/cameras/{camera_id}/service-points")
def create_service_point(camera_id: str, body: ServicePointIn):
    if store.get_camera(camera_id) is None:
        raise HTTPException(404, "Unknown camera")
    conn = db.get_conn()
    ts = db.now()
    cur = conn.execute(
        "INSERT INTO service_points (camera_id, name, kind, x, y, radius, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (camera_id, body.name.strip(), body.kind, body.x, body.y, body.radius, ts, ts),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM service_points WHERE id = ?", (cur.lastrowid,)).fetchone()
    return dict(row)


class ServicePointPatch(BaseModel):
    name: Optional[str] = None
    kind: Optional[str] = None
    x: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    y: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    radius: Optional[float] = Field(default=None, gt=0.0, le=1.0)


@router.patch("/service-points/{point_id}")
def update_service_point(point_id: int, body: ServicePointPatch):
    conn = db.get_conn()
    row = conn.execute("SELECT * FROM service_points WHERE id = ?", (point_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Service point not found")
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if fields:
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        conn.execute(
            f"UPDATE service_points SET {set_clause}, updated_at = ? WHERE id = ?",
            (*fields.values(), db.now(), point_id),
        )
        conn.commit()
    return dict(conn.execute("SELECT * FROM service_points WHERE id = ?", (point_id,)).fetchone())


@router.delete("/service-points/{point_id}")
def delete_service_point(point_id: int):
    conn = db.get_conn()
    conn.execute("DELETE FROM service_points WHERE id = ?", (point_id,))
    conn.commit()
    return {"ok": True}


@router.get("/service-points/stats")
def service_point_stats(days: int = 30):
    if days not in VALID_DAYS:
        raise HTTPException(400, f"days must be one of {VALID_DAYS}")
    return metrics_store.service_point_stats(days)


# ------------------------------------------------------------- year orb -----

@router.get("/orb")
def orb_year(year: int = 2026):
    """Per-day store metrics for one calendar year, shaped for the year orb
    (admin_portal/static/time-orb.html) — it fetches this once and
    aggregates client-side at whatever zoom level the visitor is on. Days
    with no logged activity are simply absent from `days`."""
    start = datetime(year, 1, 1).timestamp()
    end = datetime(year + 1, 1, 1).timestamp()
    return {"year": year, "days": metrics_store.daily_visitor_metrics(start, end)}

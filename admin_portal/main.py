"""
Waypoint — admin portal for the camera analytics pipeline.

Handles setup/config that previously meant hand-editing JSON files or
running CLI scripts: camera registry, camera-handoff review, live
monitoring, and visitor-identity review queue resolution. It reads and
writes the exact same files the pipeline scripts use (cameras.json,
zones_<id>.json, review_queue.json, confirmed_merges.json) and can also
launch calibrate_zones.py / multi_camera_dashboard.py as background jobs.

Run from the project root:
    uvicorn admin_portal.main:app --reload --port 8800
"""

import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import db, jobs, restreamer, store
from .api import camera_network as api_camera_network
from .api import cameras_ext as api_cameras
from .api import analytics as api_analytics
from .api import discovery as api_discovery
from .api import streams as api_streams
from .api import ws as api_ws

PROJECT_ROOT = store.PROJECT_ROOT
os.chdir(PROJECT_ROOT)  # pipeline scripts/modules use paths relative to the project root
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import metrics_store  # noqa: E402 — needs PROJECT_ROOT on sys.path first
from . import charts  # noqa: E402

ADMIN_DIR = Path(__file__).resolve().parent
WEBAPP_DIST = ADMIN_DIR / "webapp_dist"
templates = Jinja2Templates(directory=str(ADMIN_DIR / "templates"))


def splash_assets():
    """(js_url, css_urls) for the cold-boot splash bundle, or (None, []).

    Read from Vite's manifest rather than a pinned filename: the bundle is
    content-hashed, so a pinned name would either break on rebuild or need
    cache-busting hacks. Returns None when the webapp hasn't been built,
    so the portal degrades to no splash instead of a broken <script>.
    """
    manifest_path = WEBAPP_DIST / ".vite" / "manifest.json"
    if not manifest_path.is_file():
        return None, []
    try:
        with open(manifest_path) as f:
            manifest = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None, []
    entry = manifest.get("src/splash/mount.tsx")
    if not entry:
        return None, []
    css = []
    for key in entry.get("imports", []):
        css.extend(manifest.get(key, {}).get("css", []))
    css.extend(entry.get("css", []))
    return f"/app/{entry['file']}", [f"/app/{c}" for c in dict.fromkeys(css)]

db.init_db()

app = FastAPI(title="Waypoint")
app.mount("/static", StaticFiles(directory=str(ADMIN_DIR / "static")), name="static")
app.include_router(api_cameras.router, prefix="/api/cameras", tags=["cameras"])
app.include_router(api_camera_network.router, prefix="/api/cameras", tags=["camera-network"])
app.include_router(api_streams.router, prefix="/api/streams", tags=["streams"])
app.include_router(api_discovery.router, prefix="/api/discovery", tags=["discovery"])
app.include_router(api_analytics.router, prefix="/api/analytics", tags=["analytics"])
app.include_router(api_ws.router, prefix="/ws", tags=["websocket"])

ALLOWED_MEDIA_EXT = {".png", ".jpg", ".jpeg"}


def redirect(path, ok=None, error=None, status_code=303):
    qs = []
    if ok:
        qs.append(f"ok={quote(ok)}")
    if error:
        qs.append(f"error={quote(error)}")
    sep = "&" if "?" in path else "?"
    return RedirectResponse(path + (sep + "&".join(qs) if qs else ""), status_code=status_code)


def render(request, template_name, **context):
    return templates.TemplateResponse(request, template_name, context)


def _format_age(seconds):
    if seconds < 90:
        return f"{int(seconds)}s ago"
    if seconds < 5400:
        return f"{round(seconds / 60)} min ago"
    if seconds < 86400 * 2:
        return f"{round(seconds / 3600)} hr ago"
    return f"{round(seconds / 86400)} days ago"


# ---------------------------------------------------------------- media ----

@app.get("/media/{file_path:path}")
def media(file_path: str):
    target = (PROJECT_ROOT / file_path).resolve()
    try:
        target.relative_to(PROJECT_ROOT)
    except ValueError:
        raise HTTPException(404)
    if target.suffix.lower() not in ALLOWED_MEDIA_EXT or not target.is_file():
        raise HTTPException(404)
    return FileResponse(target)


# ---------------------------------------------------------------- home -----

@app.get("/")
def home(request: Request):
    cameras = store.load_cameras()
    calibrated_count = sum(1 for c in cameras if store.load_zones(c["id"]) is not None)
    dashboard_job = jobs.manager.get("dashboard")
    reviews = store.load_review_queue()
    pending_reviews = sum(1 for r in reviews if not r.get("resolved"))
    splash_js, splash_css = splash_assets()
    return render(
        request, "index.html", active="home",
        cameras=cameras,
        calibrated_count=calibrated_count,
        dashboard_running=bool(dashboard_job and dashboard_job.is_running()),
        pending_reviews=pending_reviews,
        splash_js=splash_js, splash_css=splash_css,
    )


# ------------------------------------------------------------- cameras -----

@app.get("/cameras")
def cameras_page(request: Request):
    cameras = store.load_cameras()
    calibrated_ids = {c["id"] for c in cameras if store.load_zones(c["id"]) is not None}
    return render(
        request, "cameras.html", active="cameras",
        cameras=cameras, calibrated_ids=calibrated_ids,
    )


@app.post("/cameras/add")
def cameras_add(id: str = Form(...), rtsp_url: str = Form(...), name: str = Form("")):
    id = id.strip()
    cameras = store.load_cameras()
    if any(c["id"] == id for c in cameras):
        return redirect("/cameras", error=f'Camera id "{id}" already exists.')
    cameras.append({"id": id, "rtsp_url": rtsp_url.strip(), "name": name.strip() or None})
    store.save_cameras(cameras)
    return redirect("/cameras", ok=f'Added camera "{id}".')


@app.post("/cameras/{camera_id}/edit")
def cameras_edit(camera_id: str, rtsp_url: str = Form(...), name: str = Form("")):
    cameras = store.load_cameras()
    for c in cameras:
        if c["id"] == camera_id:
            c["rtsp_url"] = rtsp_url.strip()
            c["name"] = name.strip() or None
            break
    else:
        raise HTTPException(404)
    store.save_cameras(cameras)
    return redirect("/cameras", ok=f'Updated "{camera_id}".')


@app.post("/cameras/{camera_id}/delete")
def cameras_delete(camera_id: str):
    cameras = [c for c in store.load_cameras() if c["id"] != camera_id]
    store.save_cameras(cameras)
    return redirect("/cameras", ok=f'Removed "{camera_id}" from the camera registry.')


# --------------------------------------------------------------- zones -----

@app.get("/cameras/{camera_id}/zones")
def zones_page(request: Request, camera_id: str):
    if store.get_camera(camera_id) is None:
        raise HTTPException(404, "Unknown camera")
    zones = store.load_zones(camera_id)
    cameras = store.load_cameras()
    other_camera_ids = [c["id"] for c in cameras if c["id"] != camera_id]
    return render(
        request, "zones.html", active="cameras",
        camera_id=camera_id, zones=zones, other_camera_ids=other_camera_ids,
        snapshot_exists=store.calibration_snapshot_path(camera_id).exists(),
        zones_raw=json.dumps(zones, indent=2) if zones else "",
    )


@app.post("/cameras/{camera_id}/zones/recalibrate")
def zones_recalibrate(camera_id: str):
    if store.get_camera(camera_id) is None:
        raise HTTPException(404, "Unknown camera")
    _, started = jobs.start_calibrate_camera(camera_id)
    msg = f"Calibration started for {camera_id} — see Jobs for progress." if started \
        else f"Calibration for {camera_id} is already running."
    return redirect(f"/cameras/{camera_id}/zones", ok=msg)


@app.post("/cameras/{camera_id}/zones/gates/save")
async def zones_save_gates(request: Request, camera_id: str):
    zones = store.load_zones(camera_id)
    if zones is None:
        raise HTTPException(404, "No zones config for this camera")
    form = await request.form()
    kept_gates = []
    for g in zones.get("gates", []):
        gid = g["gate_id"]
        if form.get(f"delete__{gid}") == "on":
            continue
        leads_to = form.get(f"leads_to__{gid}") or None
        g["leads_to"] = leads_to
        kept_gates.append(g)
    zones["gates"] = kept_gates
    store.save_zones(camera_id, zones)
    return redirect(f"/cameras/{camera_id}/zones", ok="Handoff links saved.")


@app.post("/cameras/{camera_id}/zones/raw/save")
async def zones_save_raw(request: Request, camera_id: str):
    form = await request.form()
    try:
        data = json.loads(form.get("raw", ""))
    except json.JSONDecodeError as e:
        return redirect(f"/cameras/{camera_id}/zones", error=f"Invalid JSON: {e}")
    store.save_zones(camera_id, data)
    return redirect(f"/cameras/{camera_id}/zones", ok="Raw config saved.")


# ------------------------------------------------------------- reviews -----

@app.get("/reviews")
def reviews_page(request: Request):
    reviews = store.load_review_queue()
    pending = [r for r in reviews if not r.get("resolved")]
    for r in pending:
        crop = r.get("new_crop")
        r["new_crop_url"] = f"/media/{crop}" if crop else None
    merges = store.load_merges()
    return render(
        request, "reviews.html", active="reviews",
        pending=pending, confirmed_count=len(merges),
    )


@app.post("/reviews/{review_id}/resolve")
def reviews_resolve(review_id: str, decision: str = Form(...)):
    reviews = store.load_review_queue()
    target = next((r for r in reviews if r["review_id"] == review_id), None)
    if target is None:
        raise HTTPException(404)
    merges = store.load_merges()
    if decision == "same":
        merges[str(target["provisional_global_id"])] = target["candidate_global_id"]
        target["resolved"] = True
        msg = "Merged — counted as one visitor."
    elif decision == "different":
        target["resolved"] = True
        msg = "Kept as two separate visitors."
    else:
        msg = "Skipped — will show again."
    store.save_review_queue(reviews)
    store.save_merges(merges)
    return redirect("/reviews", ok=msg)


# --------------------------------------------------------------- jobs ------

@app.get("/jobs")
def jobs_page(request: Request):
    job_list = []
    for status in jobs.manager.all_statuses():
        job = jobs.manager.get(status["name"])
        job_list.append({**status, "log": job.tail(300), "resource": job.resource_usage()})

    health = metrics_store.db_health()
    newest_ts = health["newest_event_ts"]
    dashboard_job = jobs.manager.get("dashboard")
    dashboard_running = bool(dashboard_job and dashboard_job.is_running())
    if newest_ts is None:
        newest_label, stale = "no data yet", False
    else:
        age = time.time() - newest_ts
        newest_label = _format_age(age)
        # Only flags as stale while the dashboard is supposedly running —
        # no data is expected and unremarkable when it's stopped.
        stale = dashboard_running and age > 60

    return render(
        request, "jobs.html", active="jobs", jobs=job_list,
        db_health=health, db_newest_label=newest_label, db_stale=stale,
    )


@app.post("/jobs/start/{job_type}")
def jobs_start(job_type: str):
    if job_type == "calibrate_all":
        if not store.load_cameras():
            return redirect("/jobs", error="Add at least one camera first.")
        _, started = jobs.start_calibrate_all()
        msg = "Calibration (all cameras) started." if started else "Calibration is already running."
    elif job_type == "dashboard":
        if not store.load_cameras():
            return redirect("/jobs", error="Add at least one camera first.")
        _, started = jobs.start_dashboard()
        msg = "Dashboard started." if started else "Dashboard is already running."
    elif job_type == "restreamer":
        if not restreamer.is_binary_installed():
            return redirect(
                "/jobs",
                error=f"go2rtc binary not found at {restreamer.GO2RTC_BIN} — download it from "
                "github.com/AlexxIT/go2rtc/releases and place it there first.",
            )
        _, started = restreamer.start()
        msg = "Restreamer (go2rtc) started." if started else "Restreamer is already running."
    else:
        raise HTTPException(404)
    return redirect("/jobs", ok=msg)


@app.post("/jobs/{job_name}/stop")
def jobs_stop(job_name: str):
    job = jobs.manager.get(job_name)
    if job is None:
        raise HTTPException(404)
    job.stop()
    return redirect("/jobs", ok=f"Stopped {job_name}.")


@app.post("/jobs/reset-data")
def jobs_reset_data():
    """Clears every recorded metric (entries/exits, visits, positions,
    service times) — the numbers behind Insights, On the Floor, and the
    orb all go back to zero. Cameras, zones and calibration are untouched."""
    metrics_store.reset_all()
    return redirect("/jobs", ok="All recorded data cleared — Insights, On the Floor, and the orb start from zero.")


# ------------------------------------------------------------- on floor ----

@app.get("/floor")
def floor_page(request: Request):
    """A glance, not a workspace: today's headline numbers plus which
    cameras are currently reporting. Deliberately narrow in scope — this is
    the page someone checks from a phone on the sales floor, not a second
    Insights page. Everything with real analytical depth stays on Insights.
    """
    from datetime import date, datetime, timedelta

    now = datetime.now()
    today_start = datetime.combine(now.date(), datetime.min.time()).timestamp()
    today_end = now.timestamp()

    # Compared against the SAME weekday last week, bounded to the same
    # elapsed portion of the day — a full day vs. a partial day would flatter
    # or bury today's number depending purely on what time you happen to load
    # this page.
    last_week_date = now.date() - timedelta(days=7)
    lw_start = datetime.combine(last_week_date, datetime.min.time()).timestamp()
    lw_end = lw_start + (today_end - today_start)
    compare_weekday = last_week_date.strftime("%A")

    totals_today = metrics_store.totals(start=today_start, end=today_end)
    entries_today = totals_today["entries"]
    in_store_now = max(0, entries_today - totals_today["exits"])

    entries_last_week = metrics_store.totals(start=lw_start, end=lw_end)["entries"]
    pct_change = None
    if entries_last_week > 0:
        pct_change = round((entries_today - entries_last_week) / entries_last_week * 100)

    reporting_ids = metrics_store.cameras_active(start=today_start, end=today_end)

    svc_today = metrics_store.service_point_stats(start=today_start, end=today_end)
    avg_wait_seconds = None
    slowest_point = None
    if svc_today:
        total_customers = sum(s["customers"] for s in svc_today)
        if total_customers:
            avg_wait_seconds = sum(s["avg_seconds"] * s["customers"] for s in svc_today) / total_customers
        slowest_point = max(svc_today, key=lambda s: s["avg_seconds"])

    peak_today = metrics_store.peak_hours(start=today_start, end=today_end)
    busiest_today = max(peak_today, key=lambda p: p[1]) if any(c for _, c in peak_today) else None

    cameras = store.load_cameras()

    return render(
        request, "floor.html", active="floor",
        cameras=cameras,
        in_store_now=in_store_now,
        reporting_count=len(reporting_ids),
        entries_today=entries_today,
        pct_change=pct_change,
        compare_weekday=compare_weekday,
        avg_wait_seconds=avg_wait_seconds,
        slowest_point=slowest_point,
        busiest_today=busiest_today,
    )


# ----------------------------------------------------------- insights ------

@app.get("/insights")
def insights_page(request: Request):
    days = int(request.query_params.get("days", 30) or 30)
    if days not in (7, 30, 90):
        days = 30

    # Explicit calendar window: ?from=YYYY-MM-DD&to=YYYY-MM-DD overrides the
    # trailing-days presets. `to` is inclusive (a manager asking for
    # "Aug 1 to Aug 7" means through the end of the 7th), hence +1 day.
    from datetime import date, datetime, timedelta

    def _parse_date(name):
        raw = request.query_params.get(name, "").strip()
        if not raw:
            return None
        try:
            return datetime.strptime(raw, "%Y-%m-%d").date()
        except ValueError:
            return None

    d_from, d_to = _parse_date("from"), _parse_date("to")
    start = end = None
    custom_range = False
    if d_from and d_to and d_from <= d_to and d_from <= date.today():
        start = datetime.combine(d_from, datetime.min.time()).timestamp()
        end = datetime.combine(d_to + timedelta(days=1), datetime.min.time()).timestamp()
        custom_range = True
        range_label = f"{d_from.strftime('%b %-d')} – {d_to.strftime('%b %-d, %Y')}"
    else:
        d_from = d_to = None
        range_label = f"last {days} days"

    t = metrics_store.totals(days, start=start, end=end)
    merges = store.load_merges()
    true_unique_visitors = max(0, t["raw_new_visitors"] - len(merges))

    peak = metrics_store.peak_hours(days, start=start, end=end)
    busiest_hour = max(peak, key=lambda p: p[1]) if any(c for _, c in peak) else None
    peak_chart = charts.bar_chart_svg(
        [(f"{h:02d}", c) for h, c in peak],
        aria_label="Store entries by hour of day", label_every=3, show_value_labels=False,
    )
    peak_table = charts.data_table_html(
        ["Hour", "Entries"], [(f"{h:02d}:00", c) for h, c in peak], "peak-hours-table"
    )

    dow_labels, hour_labels, heat_matrix = metrics_store.hourly_heatmap(days, start=start, end=end)
    heatmap_chart = charts.heatmap_svg(
        dow_labels, [f"{h:02d}" for h in hour_labels], heat_matrix,
        aria_label="Store entries by day of week and hour of day",
    )
    heatmap_legend = charts.heatmap_legend_html()
    heatmap_table = charts.heatmap_table_html(
        dow_labels, [f"{h:02d}:00" for h in hour_labels], heat_matrix, "heatmap-table"
    )
    has_heatmap_data = any(any(row) for row in heat_matrix)

    traffic = metrics_store.daily_entries_exits(days, start=start, end=end)
    traffic_chart = charts.line_chart_svg(
        [(f["day"][5:], f["entries"]) for f in traffic],
        aria_label="Store entries per day", label_every=max(1, len(traffic) // 8 or 1),
    )
    traffic_table = charts.data_table_html(
        ["Day", "Entries", "Exits"],
        [(f["day"], f["entries"], f["exits"]) for f in traffic], "traffic-table"
    )

    visitors = metrics_store.daily_new_visitors(days, start=start, end=end)
    visitors_chart = charts.line_chart_svg(
        [(v["day"][5:], v["new_visitors"]) for v in visitors],
        aria_label="New visitors per day, raw count before identity-review corrections",
        label_every=max(1, len(visitors) // 8 or 1),
    )
    visitors_table = charts.data_table_html(
        ["Day", "New visitors (raw)"], [(v["day"], v["new_visitors"]) for v in visitors], "visitors-table"
    )

    # --- how long people stay in the store overall (across all cameras) ---
    visit_stats = metrics_store.visit_length_stats(days, start=start, end=end)
    visit_buckets = metrics_store.visit_length_buckets(days, start=start, end=end)
    visit_chart = charts.bar_chart_svg(
        visit_buckets, aria_label="How long visitors stayed in the store", horizontal=True,
    )
    visit_table = charts.data_table_html(
        ["Visit length", "Visitors"], visit_buckets, "visit-length-table"
    )
    has_visit_data = any(c for _, c in visit_buckets)

    # --- cashier / service point operation ---
    service = metrics_store.service_point_stats(days, start=start, end=end)
    service_chart = charts.bar_chart_svg(
        [(f"{p['camera_id']} / {p['point_name']}", p["avg_seconds"]) for p in service],
        aria_label="Average time customers spend at each service point, in seconds", horizontal=True,
    )
    service_table = charts.data_table_html(
        ["Camera", "Service point", "Avg service time (s)", "Customers", "Longest (s)"],
        [(p["camera_id"], p["point_name"], p["avg_seconds"], p["customers"], p["longest_seconds"])
         for p in service],
        "service-point-table",
    )
    service_hourly = metrics_store.service_point_hourly(days, start=start, end=end)
    service_hourly_chart = charts.bar_chart_svg(
        [(f"{h:02d}", v) for h, v in service_hourly],
        aria_label="Average service time by hour of day, in seconds",
        label_every=3, show_value_labels=False,
    )

    return render(
        request, "insights.html", active="insights",
        days=days, custom_range=custom_range, range_label=range_label,
        date_from=d_from.isoformat() if d_from else "",
        date_to=d_to.isoformat() if d_to else "",
        totals=t, true_unique_visitors=true_unique_visitors, confirmed_merges=len(merges),
        busiest_hour=busiest_hour,
        peak_chart=peak_chart, peak_table=peak_table, has_peak_data=any(c for _, c in peak),
        heatmap_chart=heatmap_chart, heatmap_legend=heatmap_legend, heatmap_table=heatmap_table,
        has_heatmap_data=has_heatmap_data,
        traffic_chart=traffic_chart, traffic_table=traffic_table, has_traffic_data=bool(traffic),
        visitors_chart=visitors_chart, visitors_table=visitors_table, has_visitor_data=bool(visitors),
        visit_stats=visit_stats, visit_chart=visit_chart, visit_table=visit_table,
        has_visit_data=has_visit_data,
        service_chart=service_chart, service_table=service_table,
        service_hourly_chart=service_hourly_chart, has_service_data=bool(service),
    )


# ------------------------------------------------------ react app (/app) ---
# Registered LAST so it never shadows a Jinja page or /api/* route above.
# In dev, the React app is served by its own Vite dev server (see
# admin_portal/webapp/README.md) which proxies /api and /ws back to this
# process — this block only matters once `npm run build` has produced
# webapp_dist/. Until then it 404s with a clear message instead of a
# confusing missing-file error.

# check_dir=False: don't require webapp_dist/assets to exist at import time
# (Starlette's StaticFiles otherwise raises in __init__) — it can appear
# later from `npm run build` without a server restart, and 404s cleanly
# per-request until then.
app.mount(
    "/app/assets",
    StaticFiles(directory=str(WEBAPP_DIST / "assets"), check_dir=False),
    name="webapp-assets",
)


@app.get("/app")
def app_root():
    return redirect("/app/cameras")


@app.get("/app/{full_path:path}")
def spa_fallback(full_path: str):
    index_path = WEBAPP_DIST / "index.html"
    if not index_path.is_file():
        raise HTTPException(
            404,
            "The React app hasn't been built yet. Run `npm run build` in admin_portal/webapp "
            "(or `npm run dev` for local development at http://localhost:5173).",
        )
    return FileResponse(index_path)


if __name__ == "__main__":
    import uvicorn

    # timeout_graceful_shutdown: an open WebSocket (live view, status feed)
    # otherwise blocks every autoreload indefinitely at "Waiting for
    # background tasks to complete" — 3s turns that permanent wedge into a
    # brief pause.
    uvicorn.run(
        "admin_portal.main:app", host="127.0.0.1", port=8800,
        reload=True, timeout_graceful_shutdown=3,
    )

# Live Monitoring web app

A React + Vite single-page app, mounted by the FastAPI backend at `/app/*`.
The rest of the admin portal (Home, Insights, Cameras, Review Queue, Jobs)
is server-rendered Jinja2 and is untouched — this app is additive.

## Running it

**Dev** (hot reload, two processes):
```bash
uvicorn admin_portal.main:app --reload --port 8800
npm --prefix admin_portal/webapp run dev
```
Open `http://localhost:5173/app/cameras`. Vite proxies `/api/*` and `/ws/*`
back to the backend on :8800 — no CORS setup needed.

**Prod / single process**:
```bash
npm --prefix admin_portal/webapp run build
uvicorn admin_portal.main:app --port 8800
```
Open `http://localhost:8800/app/cameras`.

Run `python -m admin_portal.migrate_db` once before first use.
Tests: `pytest` (backend, 45 tests) and
`npm --prefix admin_portal/webapp test` (frontend).

**Operational quirk**: `uvicorn --reload` can hang on shutdown ("Waiting for
background tasks to complete") when a WebSocket is still open. If a reload
seems stuck, `pkill -f admin_portal.main` and restart.

---

## How live monitoring actually works

Four independent pieces. Knowing which is which matters, because they fail
separately and only one of them needs go2rtc.

```
                     ┌──────────────────────────────────────┐
   IP camera ──RTSP──┤ go2rtc (restreamer)                  │
        │            │ localhost:1984, never on the LAN     │
        │            └──────────────┬───────────────────────┘
        │                           │ WebRTC (SDP proxied by FastAPI)
        │                           ▼
        │                     browser <video>          ← 1. the picture
        │
        └──RTSP──▶ multi_camera_dashboard.py (RF-DETR + ByteTrack + Re-ID)
                          │
                          ├── ws_publisher ──▶ /ws/ingest/detections
                          │                          │
                          │                    DetectionHub (ws_hub.py)
                          │                       ├─▶ /ws/detections/{cam}  ← 2. the boxes
                          │                       └─▶ /ws/status (ONE shared) ← 3. the counts
                          │
                          └── metrics_store.py ──▶ store_metrics.db ← 4. the history
```

**1. The picture (needs go2rtc).** Browsers cannot play RTSP. go2rtc pulls
the camera's RTSP stream and republishes it as WebRTC, which a `<video>`
element can show with sub-second latency. Your browser never talks to
go2rtc and never sees an RTSP URL or password — it POSTs a WebRTC offer to
`/api/streams/{id}/webrtc-offer`, and FastAPI relays it to go2rtc on
localhost. **This is the only piece that needs the go2rtc binary.**

**2. The boxes (needs the pipeline).** Detection boxes are *not* burned
into the video. `multi_camera_dashboard.py` runs RF-DETR on its own RTSP
connection and publishes plain JSON — one message per processed frame per
camera — which the browser draws on a `<canvas>` layered over the video.
That's why boxes/labels/trails/visitor-ID are independently toggleable, why
they cost no GPU per viewer, and why the same data can drive the person
counts on the camera list without running detection twice. The canvas is
sized from the video's real letterboxed content box, so boxes stay aligned
at any window size. If detections stop arriving for 1.5s the overlay fades
and shows "Detections unavailable" rather than freezing stale boxes on screen.

**3. The counts.** Every camera's `connection_state` and live person count
arrive over **one** shared `/ws/status` socket, not one per camera — that's
what keeps the camera list cheap with many cameras.

**4. The history.** Independently of any browser, the pipeline writes
entries/exits, positions, visit sessions, and
service-point timings to `store_metrics.db`. Heatmaps and Insights read
from there, which is why they work with the pipeline stopped and go2rtc
never installed.

### What you see when things aren't running

| State | Live video | Boxes / counts | Heatmap | Insights |
|---|---|---|---|---|
| Everything running | ✅ | ✅ | ✅ | ✅ |
| go2rtc not installed | ❌ clear error | ✅ | ✅ | ✅ |
| Pipeline stopped | ✅ | ❌ "unavailable" | ✅ (history) | ✅ (history) |
| Neither running | ❌ | ❌ | ✅ (history) | ✅ (history) |

---

## Features

### Live Monitoring (`/app/cameras`)
Camera list with live status badges and person counts, links into each
camera, the grid wall, and discovery. This is the app's home — cameras are
the organizing unit, since there is no store map.

### Camera view (`/app/cameras/:id/view`)
Deep-linkable. Two modes, toggled in the header and reflected in the URL
(`?mode=heatmap`):

- **Live** — WebRTC video with the detection overlay. Toggles for boxes,
  labels, confidence, **Visitor ID**, **Time in store**, and trails; each
  persists to `localStorage`.
- **Heatmap** — where people actually stood, over a still frame from that
  camera, with Today / 7 / 30 / 90-day ranges.

Arrow keys move between cameras, Esc returns to the list.

### Per-camera heatmap
The pipeline records each tracked person's foot position once per second,
normalized 0–1 against the source frame. The API buckets those into a grid;
the browser draws it over the camera's reference frame.

**Why per-camera and not a store floor plan:** the old floor-plan approach
needed a top-down blueprint *plus* a perspective transform per camera to
place a person on a map — a lot of calibration for a result that's hard to
sanity-check. Heat drawn on the camera's own view needs zero calibration
and is immediately legible: you see the aisle and the hot spot on it.

**The tradeoff, stated plainly:** heat is per-camera and cannot be summed
into one store-wide map. Two cameras covering the same aisle each show
their own view of it rather than one merged picture.

The backdrop is the snapshot `calibrate_zones.py` saves, so it works with
everything stopped. A camera that's never been calibrated shows a clear
"run calibration to capture one" message rather than a broken image.

### Time in store (person metadata)
Each detection carries `visitor_id` (cross-camera identity from
`reid_registry.py`) and `time_in_store_seconds`. Because the clock is keyed
to `visitor_id`, someone walking entrance → checkout is **one** visit with
one running clock, not two. Visible live on the overlay; aggregated on
Insights as "Avg time in store" and a visit-length distribution.

Accuracy is bounded by cross-camera re-identification: if two sightings of
one person aren't matched, that's two short visits instead of one long one.
The Review Queue is how you correct that.

### Service points (cashier / counter)
Click **Place service point** on any camera view and click where customers
stand to be served. The circle is the catchment area; time inside it becomes
the service-time metrics on Insights (average, customer count, longest, and
average by hour of day).

It's a plain radius in normalized image space — no polygon, no floor
projection — and the pipeline measures exactly the circle that's drawn, so
what you see is what's counted. Points are picked up within 30 seconds
without restarting the pipeline.

Because it's image space, the catchment renders (and measures) as an
ellipse on a non-square frame: normalized distance treats a 1280×720 frame
as a unit square. Consistent and resolution-independent, but not a true
circle on the floor — that would need the homography this design avoids.

### Discovery (`/app/discovery`)
**ONVIF WS-Discovery** (no credentials, same L2 segment/VLAN only) or a
**subnet sweep** (any CIDR, concurrency-capped, refuses >1024 hosts without
`force`). Progress streams over `/ws/discovery/{scan_id}` with a polling
fallback. Nothing is added automatically — devices sit in a review list
until you supply credentials and click Add. Re-scans dedup by MAC → serial
→ IP and flag `ip_changed` rather than creating duplicates.

### Grid wall (`/app/grid`)
2×2 / 3×3 multi-camera view built from the same `LiveVideo` component.

---

## Naming

Renamed from CV jargon to plain retail language. Old table/column names are
migrated automatically and idempotently in `metrics_store._migrate()` —
verified data-preserving by `tests/test_metrics_analytics.py`.

| Was | Now |
|---|---|
| Footfall in / out | Store entries / exits |
| Global ID | Visitor ID |
| Local ID | Track ID |
| Gate | Camera handoff point |
| Re-ID review | Identity review |

Waiting areas (auto-detected "queue zones") were removed entirely: they
duplicated what the heatmap (where people stand) and service points (how
long per customer) already answer, and the auto-detected polygons reported
different numbers than the hand-placed service points for the same
register, which was worse than either alone. Legacy `queue_snapshots`
tables in an old database are left untouched, just no longer read.

---

## Known limitations

- **Heat is per-camera, not store-wide** — see the tradeoff above. This is
  the design, not a gap to fill later.
- **No live video without the go2rtc binary** (`bin/README.md` has the
  install command for this Mac). Everything else works without it.
- **go2rtc, real cameras, and a real ONVIF network were not available in
  this environment.** The streaming path is verified for request/response
  shapes, error handling, and "no RTSP URL or credential ever reaches the
  browser" — not for an actual moving picture. Discovery is verified
  against loopback/mock servers plus a live multicast probe that correctly
  finds zero devices.
- **Frame-accurate detection/video sync isn't achievable over WebRTC** —
  boxes are matched to the nearest detection by wall-clock timestamp.
- **Time in store is only as good as cross-camera matching** (above).
- **The heatmap backdrop is a calibration snapshot, not a live frame** — if
  the camera is moved or the shelves are rearranged, recapture it by
  re-running calibration, or old heat will sit over a scene that no longer
  matches.
- **Service-point catchment is an ellipse in world terms** (above).
- **Each camera can have up to 2 simultaneous RTSP clients** (go2rtc + the
  pipeline's own capture); some budget cameras cap concurrent sessions at
  2–4. Worth a real-hardware check.
- **Placing/dragging service points is mouse-only** — untested on touch.
- **No auth anywhere** (`/api/*`, `/ws/*`), consistent with this app's
  trusted-network-only posture — explicitly not solved. Credentials are
  encrypted at rest as disclosure protection, not access control.
- **No dedicated credentials/network-management UI** — implemented and
  tested at the API layer; the only UI touching it is discovery's add form.
- `npm audit` flags issues in `esbuild`'s dev server (dev only) and
  `react-router`'s SSR/redirect handling (no SSR here, no user-controlled
  redirects) — unpatched, both need major version bumps.

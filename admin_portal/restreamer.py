"""
go2rtc integration — the RTSP-to-browser bridge.

Why go2rtc over MediaMTX: both are single static Go binaries needing no
Docker (matches this repo's plain-subprocess style throughout). go2rtc wins
here specifically for a runtime HTTP API that lets streams be added/removed
without a restart, a WebRTC path tuned for sub-second latency on exactly
this "existing RTSP camera -> browser" shape, and a trivial single-YAML
config — the better fit than MediaMTX's WHIP/WHEP-leaning design at the
1-10 camera scale this app targets.

Browsers cannot play RTSP directly — go2rtc is what makes a `<video>`
element possible at all here. It pulls RTSP itself (independent of
multi_camera_dashboard.py's own cv2.VideoCapture — see the concurrent-
session-limit note in the top-level plan) and exposes WebRTC/HLS/snapshot.

The go2rtc binary is a documented manual-install prerequisite —
PROJECT_ROOT/bin/go2rtc — never auto-downloaded at runtime (downloading and
executing a fetched binary is exactly the kind of supply-chain shortcut
worth avoiding even in a small internal tool). Get it from
https://github.com/AlexxIT/go2rtc/releases and place the binary there.

go2rtc's own HTTP API binds to 127.0.0.1 only — it is NEVER exposed to the
LAN. The browser never talks to it directly and never sees an RTSP URL or
credential; admin_portal/api/streams.py proxies WebRTC signaling, HLS, and
snapshots through this backend instead.
"""

import os
from pathlib import Path

import yaml

from . import db, jobs, store

PROJECT_ROOT = store.PROJECT_ROOT
GO2RTC_BIN = PROJECT_ROOT / "bin" / "go2rtc"
GO2RTC_YAML = PROJECT_ROOT / "go2rtc.yaml"
GO2RTC_API_BASE = "http://127.0.0.1:1984"
GO2RTC_WEBRTC_LISTEN = ":8555/tcp"


def _stream_urls_for_camera(cam, conn):
    """(main_url, sub_url_or_None) — prefers camera_network's stored stream
    URIs (already have credentials embedded, built at manual-add/discovery
    time — see api/camera_network.py), falling back to cameras.json's
    embedded rtsp_url for cameras that predate that table (the two original
    demo cameras)."""
    row = conn.execute(
        "SELECT main_stream_uri, sub_stream_uri FROM camera_network WHERE camera_id = ?", (cam["id"],)
    ).fetchone()
    main_url = (row["main_stream_uri"] if row and row["main_stream_uri"] else None) or cam["rtsp_url"]
    sub_url = row["sub_stream_uri"] if row and row["sub_stream_uri"] else None
    return main_url, sub_url


def generate_config() -> dict:
    conn = db.get_conn()
    streams = {}
    for cam in store.load_cameras():
        main_url, sub_url = _stream_urls_for_camera(cam, conn)
        streams[cam["id"]] = main_url
        if sub_url:
            streams[f"{cam['id']}_sub"] = sub_url
    return {
        "streams": streams,
        "api": {"listen": "127.0.0.1:1984"},  # localhost only — never on the LAN
        "webrtc": {"listen": GO2RTC_WEBRTC_LISTEN},
    }


def write_config() -> Path:
    config = generate_config()
    yaml_text = yaml.safe_dump(config, sort_keys=False)
    fd = os.open(GO2RTC_YAML, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(yaml_text)
    return GO2RTC_YAML


def is_binary_installed() -> bool:
    return GO2RTC_BIN.is_file() and os.access(GO2RTC_BIN, os.X_OK)


def start():
    """Reuses jobs.JobManager verbatim, so the restreamer shows up on the
    existing Jobs page (log tailing, start/stop) for free — no new UI."""
    write_config()
    return jobs.manager.start("restreamer", [str(GO2RTC_BIN), "-config", str(GO2RTC_YAML)])


def is_running() -> bool:
    job = jobs.manager.get("restreamer")
    return bool(job and job.is_running())

"""
SQLite storage for the floor-plan/camera-placement/discovery feature set.

Clones metrics_store.py's pattern deliberately: plain sqlite3, WAL mode,
one connection per thread, no ORM. Kept in its own file (ops_console.db)
separate from store_metrics.db — business metrics and device/config
inventory are different lifecycles and shouldn't share a migration path.

cameras.json stays the source of truth for camera id/name/rtsp_url; nothing
here migrates that out. Tables below reference camera_id as a plain string,
validated against store.get_camera() at the application layer (no real FK
across a JSON file).
"""

import sqlite3
import threading
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "ops_console.db"

_local = threading.local()
_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS service_points (
    -- A named spot inside ONE camera's field of view that staff work at:
    -- a cash register, a service desk, a returns counter. Stored in the
    -- camera's own image space (normalized 0-1 so it survives a resolution
    -- change), NOT in any floor/world coordinate system — there is no
    -- homography here and this feature deliberately doesn't need one.
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    camera_id TEXT NOT NULL,
    name TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'cashier',
    x REAL NOT NULL,
    y REAL NOT NULL,
    radius REAL NOT NULL DEFAULT 0.12,  -- normalized: "in front of" catchment around the point
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_service_points_camera ON service_points(camera_id);

CREATE TABLE IF NOT EXISTS credentials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    label TEXT NOT NULL,
    username TEXT NOT NULL,
    encrypted_password BLOB NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS camera_network (
    camera_id TEXT PRIMARY KEY,
    ip TEXT, mac TEXT, hostname TEXT,
    rtsp_port INTEGER, http_port INTEGER, onvif_port INTEGER,
    manufacturer TEXT, model TEXT, firmware TEXT, serial TEXT,
    onvif_profile_support TEXT,
    main_stream_uri TEXT, main_stream_width INTEGER, main_stream_height INTEGER,
    main_stream_codec TEXT, main_stream_fps REAL,
    sub_stream_uri TEXT, sub_stream_width INTEGER, sub_stream_height INTEGER,
    sub_stream_codec TEXT, sub_stream_fps REAL,
    credential_id INTEGER REFERENCES credentials(id),
    last_seen REAL, last_error TEXT,
    connection_state TEXT NOT NULL DEFAULT 'not_configured',
    uptime_seconds REAL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS discovery_scans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    method TEXT NOT NULL,
    cidr TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    hosts_total INTEGER,
    hosts_scanned INTEGER NOT NULL DEFAULT 0,
    started_at REAL NOT NULL,
    ended_at REAL,
    error TEXT
);

CREATE TABLE IF NOT EXISTS discovered_devices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id INTEGER NOT NULL REFERENCES discovery_scans(id) ON DELETE CASCADE,
    ip TEXT NOT NULL, mac TEXT, onvif_xaddr TEXT,
    probe_ports TEXT, http_banner TEXT, guessed_manufacturer TEXT,
    matched_camera_id TEXT, match_reason TEXT,
    ip_changed INTEGER NOT NULL DEFAULT 0,
    dismissed INTEGER NOT NULL DEFAULT 0,
    added_as_camera_id TEXT,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_discovered_scan ON discovered_devices(scan_id);
"""


def _connect():
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(DB_PATH, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        _local.conn = conn
    return conn


def init_db():
    with _lock:
        conn = _connect()
        conn.executescript(SCHEMA)
        conn.commit()


def get_conn():
    """For callers that need to run their own statements (routers, migration script)."""
    return _connect()


def now():
    return time.time()

"""
SQLite persistence for business-insight events.

Nothing in multi_camera_dashboard.py used to be stored anywhere — counts
and visitor status all just went to stdout. This module gives it somewhere
durable to land so the admin portal's Insights page (and, later, any
external BI tool) has history to query instead of a snapshot of whatever's
on screen right now.

Naming: this module deliberately uses plain retail language rather than CV
jargon — "entries/exits" not "footfall", "time spent" not "dwell",
"visitor_id" not "global_id". Old table
and column names from the earlier schema are migrated automatically in
_migrate() (idempotent, preserves existing rows).

Single-store SQLite by design: zero setup, one file, safe for a handful of
camera threads writing concurrently via WAL mode. If this grows into a
multi-store rollup, swap this module for a Postgres-backed one — the
call sites (log_entry_exit, log_positions, etc.) are the seam.
"""

import sqlite3
import threading
import time
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "store_metrics.db"

_lock = threading.Lock()
_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS entry_exit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    camera_id TEXT NOT NULL,
    direction TEXT NOT NULL CHECK (direction IN ('in', 'out')),
    ts REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_entry_exit_ts ON entry_exit_events(ts);

CREATE TABLE IF NOT EXISTS visitor_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    visitor_id INTEGER NOT NULL,
    camera_id TEXT NOT NULL,
    status TEXT NOT NULL,
    ts REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_visitor_ts ON visitor_events(ts);

-- Where people actually stood, in each camera's own image space (x/y
-- normalized 0-1 against the source frame, so a resolution change doesn't
-- invalidate history). This is what the per-camera heatmap aggregates.
-- One row per visitor per sample interval, NOT per frame — see
-- POSITION_SAMPLE_INTERVAL_SEC in multi_camera_dashboard.py; at 25fps a
-- per-frame write would be ~90k rows/hour/person for no extra insight.
CREATE TABLE IF NOT EXISTS position_samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    camera_id TEXT NOT NULL,
    visitor_id INTEGER,
    x REAL NOT NULL,
    y REAL NOT NULL,
    ts REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_position_camera_ts ON position_samples(camera_id, ts);

-- One row per visitor per store visit. last_seen is updated as they're
-- re-seen on any camera, so (last_seen - first_seen) is total time in the
-- store across every camera, not time in one camera's view.
CREATE TABLE IF NOT EXISTS visit_sessions (
    visitor_id INTEGER PRIMARY KEY,
    first_seen REAL NOT NULL,
    last_seen REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_visit_sessions_first ON visit_sessions(first_seen);

-- Time a visitor spent within a service point's catchment radius (see
-- service_points in ops_console.db). This is what "how long did customers
-- stand in front of the cashier" is computed from.
CREATE TABLE IF NOT EXISTS service_point_visits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    camera_id TEXT NOT NULL,
    point_name TEXT NOT NULL,
    visitor_id INTEGER,
    seconds REAL NOT NULL,
    ts REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_service_visits_ts ON service_point_visits(ts);
"""

# old name -> new name. Applied only when the old table exists and the new
# one doesn't, so re-running is harmless and no data is ever dropped.
_TABLE_RENAMES = [
    ("footfall_events", "entry_exit_events"),
]
# table -> (old column, new column)
_COLUMN_RENAMES = [
    ("visitor_events", "global_id", "visitor_id"),
]


def _connect():
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(DB_PATH, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        _local.conn = conn
    return conn


def _table_exists(conn, name):
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?", (name,)
    ).fetchone() is not None


def _column_exists(conn, table, column):
    if not _table_exists(conn, table):
        return False
    return any(r[1] == column for r in conn.execute(f"PRAGMA table_info({table})"))


def _migrate(conn):
    """Rename the pre-existing jargon-named tables/columns in place rather
    than recreating them — the demo/history rows in store_metrics.db are
    worth keeping, and a rename is atomic where a copy-and-drop isn't."""
    for old, new in _TABLE_RENAMES:
        if _table_exists(conn, old) and not _table_exists(conn, new):
            conn.execute(f"ALTER TABLE {old} RENAME TO {new}")
    for table, old_col, new_col in _COLUMN_RENAMES:
        if _column_exists(conn, table, old_col) and not _column_exists(conn, table, new_col):
            conn.execute(f"ALTER TABLE {table} RENAME COLUMN {old_col} TO {new_col}")
    conn.commit()


def init_db():
    with _lock:
        conn = _connect()
        _migrate(conn)
        conn.executescript(SCHEMA)
        conn.commit()


# ------------------------------------------------------------ write side ----

def log_entry_exit(camera_id, direction, ts=None):
    """direction: 'in' (someone entered the store) or 'out' (they left)."""
    ts = ts if ts is not None else time.time()
    with _lock:
        conn = _connect()
        conn.execute(
            "INSERT INTO entry_exit_events (camera_id, direction, ts) VALUES (?, ?, ?)",
            (camera_id, direction, ts),
        )
        conn.commit()


def log_visitor_event(visitor_id, camera_id, status, ts=None):
    ts = ts if ts is not None else time.time()
    with _lock:
        conn = _connect()
        conn.execute(
            "INSERT INTO visitor_events (visitor_id, camera_id, status, ts) VALUES (?, ?, ?, ?)",
            (visitor_id, camera_id, status, ts),
        )
        conn.commit()


def log_positions(camera_id, samples, ts=None):
    """samples: [(visitor_id, x, y), ...] with x/y normalized 0-1.
    Batched in one transaction — this is the highest-frequency write in the
    system and one commit per person per interval would dominate it."""
    if not samples:
        return
    ts = ts if ts is not None else time.time()
    with _lock:
        conn = _connect()
        conn.executemany(
            "INSERT INTO position_samples (camera_id, visitor_id, x, y, ts) VALUES (?, ?, ?, ?, ?)",
            [(camera_id, vid, x, y, ts) for vid, x, y in samples],
        )
        conn.commit()


def touch_visit(visitor_id, ts=None):
    """Upsert a visit session: first_seen is set once, last_seen moves
    forward every time this visitor is seen on any camera."""
    ts = ts if ts is not None else time.time()
    with _lock:
        conn = _connect()
        conn.execute(
            "INSERT INTO visit_sessions (visitor_id, first_seen, last_seen) VALUES (?, ?, ?) "
            "ON CONFLICT(visitor_id) DO UPDATE SET last_seen = excluded.last_seen",
            (visitor_id, ts, ts),
        )
        conn.commit()


def log_service_point_visit(camera_id, point_name, visitor_id, seconds, ts=None):
    ts = ts if ts is not None else time.time()
    with _lock:
        conn = _connect()
        conn.execute(
            "INSERT INTO service_point_visits (camera_id, point_name, visitor_id, seconds, ts) "
            "VALUES (?, ?, ?, ?, ?)",
            (camera_id, point_name, visitor_id, seconds, ts),
        )
        conn.commit()


# ------------------------------------------------------- read-side queries --

def _bounds(days=30, start=None, end=None):
    """(since_ts, until_ts) for a read query. Pass start/end (unix
    timestamps) for an explicit calendar window; otherwise the window is
    the trailing `days` ending now. Every read below applies BOTH bounds,
    which is what makes "show me just last Tuesday" possible."""
    if start is not None:
        return start, (end if end is not None else time.time())
    now = time.time()
    return now - days * 86400, now


def peak_hours(days=30, start=None, end=None):
    """Total entries per hour-of-day (0-23), local time, zero-filled."""
    conn = _connect()
    rows = conn.execute(
        "SELECT CAST(strftime('%H', ts, 'unixepoch', 'localtime') AS INTEGER) AS hour, COUNT(*) "
        "FROM entry_exit_events WHERE direction='in' AND ts >= ? AND ts <= ? GROUP BY hour",
        _bounds(days, start, end),
    ).fetchall()
    by_hour = {int(h): c for h, c in rows}
    return [(h, by_hour.get(h, 0)) for h in range(24)]


def hourly_heatmap(days=30, start=None, end=None):
    """Entries matrix: rows = day of week (Mon..Sun), cols = hour of day."""
    conn = _connect()
    rows = conn.execute(
        "SELECT CAST(strftime('%w', ts, 'unixepoch', 'localtime') AS INTEGER) AS dow, "
        "CAST(strftime('%H', ts, 'unixepoch', 'localtime') AS INTEGER) AS hour, COUNT(*) "
        "FROM entry_exit_events WHERE direction='in' AND ts >= ? AND ts <= ? GROUP BY dow, hour",
        _bounds(days, start, end),
    ).fetchall()
    by_cell = {(int(d), int(h)): c for d, h, c in rows}
    dow_order = [1, 2, 3, 4, 5, 6, 0]  # SQLite %w: 0=Sunday — reorder to Monday-first
    dow_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    matrix = [[by_cell.get((d, h), 0) for h in range(24)] for d in dow_order]
    return dow_labels, list(range(24)), matrix


def daily_entries_exits(days=30, start=None, end=None):
    conn = _connect()
    rows = conn.execute(
        "SELECT date(ts, 'unixepoch', 'localtime') AS day, "
        "SUM(CASE WHEN direction='in' THEN 1 ELSE 0 END), "
        "SUM(CASE WHEN direction='out' THEN 1 ELSE 0 END) "
        "FROM entry_exit_events WHERE ts >= ? AND ts <= ? GROUP BY day ORDER BY day",
        _bounds(days, start, end),
    ).fetchall()
    return [{"day": d, "entries": i, "exits": o} for d, i, o in rows]


def daily_new_visitors(days=30, start=None, end=None):
    conn = _connect()
    rows = conn.execute(
        "SELECT date(ts, 'unixepoch', 'localtime') AS day, COUNT(DISTINCT visitor_id) "
        "FROM visitor_events WHERE status IN ('new', 'pending_review') AND ts >= ? AND ts <= ? "
        "GROUP BY day ORDER BY day",
        _bounds(days, start, end),
    ).fetchall()
    return [{"day": d, "new_visitors": c} for d, c in rows]


def visit_length_stats(days=30, min_seconds=5.0, start=None, end=None):
    """How long visitors stayed in the store overall (across all cameras).
    Sessions shorter than min_seconds are treated as pass-through noise —
    someone clipping the edge of frame isn't a store visit."""
    conn = _connect()
    row = conn.execute(
        "SELECT COUNT(*), AVG(last_seen - first_seen), MAX(last_seen - first_seen) "
        "FROM visit_sessions WHERE first_seen >= ? AND first_seen <= ? "
        "AND (last_seen - first_seen) >= ?",
        (*_bounds(days, start, end), min_seconds),
    ).fetchone()
    count, avg, longest = row if row else (0, None, None)
    return {
        "visits": count or 0,
        "avg_seconds": round(avg, 1) if avg else 0.0,
        "longest_seconds": round(longest, 1) if longest else 0.0,
    }


def visit_length_buckets(days=30, min_seconds=5.0, start=None, end=None):
    """Distribution of visit lengths, for a 'how long do people stay' chart."""
    conn = _connect()
    rows = conn.execute(
        "SELECT (last_seen - first_seen) FROM visit_sessions "
        "WHERE first_seen >= ? AND first_seen <= ? AND (last_seen - first_seen) >= ?",
        (*_bounds(days, start, end), min_seconds),
    ).fetchall()
    edges = [(0, 60, "< 1 min"), (60, 300, "1–5 min"), (300, 600, "5–10 min"),
             (600, 1800, "10–30 min"), (1800, float("inf"), "30+ min")]
    counts = {label: 0 for _, _, label in edges}
    for (secs,) in rows:
        for lo, hi, label in edges:
            if lo <= secs < hi:
                counts[label] += 1
                break
    return [(label, counts[label]) for _, _, label in edges]


def service_point_stats(days=30, start=None, end=None):
    """Per service point (cashier/counter): how long customers spend there
    and how many were served — the core cashier-operation metrics."""
    conn = _connect()
    rows = conn.execute(
        "SELECT camera_id, point_name, AVG(seconds), COUNT(*), MAX(seconds) "
        "FROM service_point_visits WHERE ts >= ? AND ts <= ? GROUP BY camera_id, point_name "
        "ORDER BY AVG(seconds) DESC",
        _bounds(days, start, end),
    ).fetchall()
    return [
        {"camera_id": c, "point_name": p, "avg_seconds": round(a, 1),
         "customers": n, "longest_seconds": round(m, 1)}
        for c, p, a, n, m in rows
    ]


def service_point_hourly(days=30, start=None, end=None):
    """Average service time per hour-of-day, across all service points —
    shows when checkout slows down."""
    conn = _connect()
    rows = conn.execute(
        "SELECT CAST(strftime('%H', ts, 'unixepoch', 'localtime') AS INTEGER) AS hour, "
        "AVG(seconds) FROM service_point_visits WHERE ts >= ? AND ts <= ? GROUP BY hour",
        _bounds(days, start, end),
    ).fetchall()
    by_hour = {int(h): round(a, 1) for h, a in rows}
    return [(h, by_hour.get(h, 0)) for h in range(24)]


def position_heatmap(camera_id, days=30, grid=48, start=None, end=None):
    """Aggregates position_samples for one camera into a grid x grid matrix
    of counts, in the camera's own normalized image space. The frontend
    draws this straight over the camera view — no floor plan, no homography,
    no coordinate transform beyond scaling to the rendered video size."""
    conn = _connect()
    rows = conn.execute(
        "SELECT x, y FROM position_samples WHERE camera_id = ? AND ts >= ? AND ts <= ?",
        (camera_id, *_bounds(days, start, end)),
    ).fetchall()
    matrix = [[0] * grid for _ in range(grid)]
    for x, y in rows:
        cx = min(grid - 1, max(0, int(x * grid)))
        cy = min(grid - 1, max(0, int(y * grid)))
        matrix[cy][cx] += 1
    peak = max((v for row in matrix for v in row), default=0)
    return {"grid": grid, "matrix": matrix, "samples": len(rows), "peak": peak}


def totals(days=30, start=None, end=None):
    conn = _connect()
    bounds = _bounds(days, start, end)
    entries = conn.execute(
        "SELECT COUNT(*) FROM entry_exit_events WHERE direction='in' AND ts >= ? AND ts <= ?", bounds
    ).fetchone()[0]
    exits = conn.execute(
        "SELECT COUNT(*) FROM entry_exit_events WHERE direction='out' AND ts >= ? AND ts <= ?", bounds
    ).fetchone()[0]
    raw_new_visitors = conn.execute(
        "SELECT COUNT(DISTINCT visitor_id) FROM visitor_events "
        "WHERE status IN ('new', 'pending_review') AND ts >= ? AND ts <= ?",
        bounds,
    ).fetchone()[0]
    return {"entries": entries, "exits": exits, "raw_new_visitors": raw_new_visitors}

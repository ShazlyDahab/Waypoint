"""Tests for the per-camera heatmap, visit-length, and service-point logic.

Uses a temp database rather than the real store_metrics.db so a test run
never touches recorded history.
"""

import importlib
import math

import pytest


@pytest.fixture
def metrics(tmp_path, monkeypatch):
    import metrics_store
    monkeypatch.setattr(metrics_store, "DB_PATH", tmp_path / "test_metrics.db")
    # thread-local connection is cached — clear it so the new path is used
    if hasattr(metrics_store._local, "conn"):
        del metrics_store._local.conn
    metrics_store.init_db()
    yield metrics_store
    if hasattr(metrics_store._local, "conn"):
        metrics_store._local.conn.close()
        del metrics_store._local.conn


# ------------------------------------------------------------- heatmap ------

def test_position_heatmap_buckets_into_correct_cells(metrics):
    # A point at (0.0, 0.0) belongs in the top-left cell, (0.99, 0.99) in
    # bottom-right. Getting this backwards would flip the heatmap vertically
    # against the camera image, which is the kind of bug that looks
    # plausible until you compare it to the actual scene.
    metrics.log_positions("cam1", [(1, 0.01, 0.01), (2, 0.99, 0.99)])
    result = metrics.position_heatmap("cam1", days=1, grid=10)
    assert result["matrix"][0][0] == 1
    assert result["matrix"][9][9] == 1
    assert result["samples"] == 2
    assert result["peak"] == 1


def test_position_heatmap_clamps_out_of_range_coordinates(metrics):
    # x=1.0 exactly would index grid[10] on a 10-cell grid without clamping.
    metrics.log_positions("cam1", [(1, 1.0, 1.0)])
    result = metrics.position_heatmap("cam1", days=1, grid=10)
    assert result["matrix"][9][9] == 1


def test_position_heatmap_is_per_camera(metrics):
    metrics.log_positions("cam1", [(1, 0.5, 0.5)])
    metrics.log_positions("cam2", [(2, 0.5, 0.5), (3, 0.1, 0.1)])
    assert metrics.position_heatmap("cam1", days=1)["samples"] == 1
    assert metrics.position_heatmap("cam2", days=1)["samples"] == 2


def test_position_heatmap_empty_camera_is_not_an_error(metrics):
    result = metrics.position_heatmap("never_seen", days=1, grid=8)
    assert result["samples"] == 0
    assert result["peak"] == 0
    assert len(result["matrix"]) == 8


# -------------------------------------------------------- visit sessions ----

def test_touch_visit_keeps_first_seen_and_advances_last_seen(metrics):
    # This is what makes "time in store" span cameras: the same visitor seen
    # again later must extend the visit, not start a new one.
    metrics.touch_visit(42, ts=1000.0)
    metrics.touch_visit(42, ts=1600.0)
    row = metrics._connect().execute(
        "SELECT first_seen, last_seen FROM visit_sessions WHERE visitor_id = 42"
    ).fetchone()
    assert row == (1000.0, 1600.0)


def test_visit_length_stats_ignores_pass_through_noise(metrics):
    import time
    now = time.time()
    metrics.touch_visit(1, ts=now - 600)
    metrics.touch_visit(1, ts=now)          # 600s visit — counted
    metrics.touch_visit(2, ts=now - 1)
    metrics.touch_visit(2, ts=now)          # 1s visit — below the 5s floor
    stats = metrics.visit_length_stats(days=1, min_seconds=5.0)
    assert stats["visits"] == 1
    assert stats["avg_seconds"] == pytest.approx(600, abs=1)


def test_visit_length_buckets_cover_every_visit_exactly_once(metrics):
    import time
    now = time.time()
    for i, length in enumerate([30, 120, 400, 900, 3600], start=1):
        metrics.touch_visit(i, ts=now - length)
        metrics.touch_visit(i, ts=now)
    buckets = metrics.visit_length_buckets(days=1)
    assert [c for _, c in buckets] == [1, 1, 1, 1, 1]
    assert sum(c for _, c in buckets) == 5


# --------------------------------------------------------- service points ---

def test_service_point_stats_groups_by_point(metrics):
    metrics.log_service_point_visit("checkout", "Register 1", 1, 40.0)
    metrics.log_service_point_visit("checkout", "Register 1", 2, 60.0)
    metrics.log_service_point_visit("checkout", "Register 2", 3, 20.0)
    stats = {s["point_name"]: s for s in metrics.service_point_stats(days=1)}
    assert stats["Register 1"]["avg_seconds"] == 50.0
    assert stats["Register 1"]["customers"] == 2
    assert stats["Register 1"]["longest_seconds"] == 60.0
    assert stats["Register 2"]["customers"] == 1


def test_service_point_stats_orders_slowest_first(metrics):
    metrics.log_service_point_visit("checkout", "Fast", 1, 10.0)
    metrics.log_service_point_visit("checkout", "Slow", 2, 90.0)
    names = [s["point_name"] for s in metrics.service_point_stats(days=1)]
    assert names[0] == "Slow"


# ------------------------------- the "in front of the cashier" radius test --

def in_catchment(px, py, point, frame_w, frame_h):
    """Mirrors multi_camera_dashboard.py's service-point test exactly: foot
    position normalized against the frame, plain euclidean distance in
    normalized space against the point's radius."""
    fx, fy = px / frame_w, py / frame_h
    return math.hypot(fx - point["x"], fy - point["y"]) <= point["radius"]


def test_person_at_the_point_is_inside_catchment():
    point = {"x": 0.5, "y": 0.5, "radius": 0.1}
    assert in_catchment(640, 360, point, 1280, 720) is True


def test_person_far_from_the_point_is_outside_catchment():
    point = {"x": 0.5, "y": 0.5, "radius": 0.1}
    assert in_catchment(100, 100, point, 1280, 720) is False


def test_catchment_boundary_is_inclusive():
    point = {"x": 0.5, "y": 0.5, "radius": 0.1}
    # exactly 0.1 to the right of the point in normalized space
    assert in_catchment(0.6 * 1280, 0.5 * 720, point, 1280, 720) is True


def test_catchment_is_resolution_independent():
    # The same physical spot in a 1280x720 and a 3840x2160 frame must give
    # the same answer — that's the whole point of storing normalized
    # coordinates rather than pixels.
    point = {"x": 0.5, "y": 0.5, "radius": 0.1}
    assert in_catchment(660, 370, point, 1280, 720) == in_catchment(1980, 1110, point, 3840, 2160)


# ------------------------------------------------------------- migration ----

def test_migration_renames_old_tables_and_preserves_rows(tmp_path, monkeypatch):
    """The rename from the old jargon schema (footfall_events etc.) runs
    against a database with real recorded history in it. Losing those rows
    would be silent and unrecoverable, so this asserts the data survives."""
    import sqlite3
    import metrics_store

    db_path = tmp_path / "legacy.db"
    legacy = sqlite3.connect(db_path)
    legacy.executescript("""
        CREATE TABLE footfall_events (id INTEGER PRIMARY KEY, camera_id TEXT, direction TEXT, ts REAL);
        CREATE TABLE queue_snapshots (id INTEGER PRIMARY KEY, camera_id TEXT, zone_name TEXT, count INTEGER, ts REAL);
        CREATE TABLE visitor_events (id INTEGER PRIMARY KEY, global_id INTEGER, camera_id TEXT,
                                     status TEXT, ts REAL);
    """)
    legacy.execute("INSERT INTO footfall_events (camera_id, direction, ts) VALUES ('cam1', 'in', 1000)")
    legacy.execute("INSERT INTO queue_snapshots (camera_id, zone_name, count, ts) VALUES ('cam1', 'Q', 3, 1000)")
    legacy.execute("INSERT INTO visitor_events (global_id, camera_id, status, ts) VALUES (7, 'cam1', 'new', 1000)")
    legacy.commit()
    legacy.close()

    monkeypatch.setattr(metrics_store, "DB_PATH", db_path)
    if hasattr(metrics_store._local, "conn"):
        del metrics_store._local.conn
    metrics_store.init_db()
    conn = metrics_store._connect()

    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "entry_exit_events" in tables and "footfall_events" not in tables
    # Waiting-area tables were removed as a feature: a legacy queue_snapshots
    # table must be LEFT ALONE (not renamed, not dropped — deleting user data
    # in a migration is never acceptable), just no longer read or written.
    assert "queue_snapshots" in tables

    assert conn.execute("SELECT COUNT(*) FROM entry_exit_events").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM queue_snapshots").fetchone()[0] == 1
    assert conn.execute("SELECT visitor_id FROM visitor_events").fetchone()[0] == 7

    # Idempotent: running it again must not fail or double-rename.
    metrics_store.init_db()
    assert conn.execute("SELECT COUNT(*) FROM entry_exit_events").fetchone()[0] == 1

    conn.close()
    del metrics_store._local.conn


# ------------------------------------------------------------ date ranges ---

def test_reads_accept_explicit_calendar_window(metrics):
    # Rows on three separate days; a window covering only the middle day
    # must return exactly that day's activity.
    day = 86400.0
    base = 1_700_000_000.0
    for i, ts in enumerate([base, base + day, base + 2 * day]):
        metrics.log_entry_exit("cam1", "in", ts=ts)
    full = metrics.totals(start=base - 1, end=base + 3 * day)
    middle = metrics.totals(start=base + day - 1, end=base + day + 1)
    assert full["entries"] == 3
    assert middle["entries"] == 1


def test_position_heatmap_respects_window(metrics):
    metrics.log_positions("cam1", [(1, 0.5, 0.5)], ts=1000.0)
    metrics.log_positions("cam1", [(2, 0.5, 0.5)], ts=5000.0)
    inside = metrics.position_heatmap("cam1", start=0.0, end=2000.0)
    assert inside["samples"] == 1


def test_trailing_days_window_unchanged(metrics):
    # The default trailing-days behaviour must survive the range refactor:
    # an old row outside the window stays excluded.
    import time
    now = time.time()
    metrics.log_entry_exit("cam1", "in", ts=now - 10)
    metrics.log_entry_exit("cam1", "in", ts=now - 5 * 86400)
    assert metrics.totals(days=1)["entries"] == 1
    assert metrics.totals(days=30)["entries"] == 2

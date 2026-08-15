"""
One-time (idempotent) setup for ops_console.db.

Run manually: python -m admin_portal.migrate_db

What it does:
  1. Creates ops_console.db and the full schema (safe to re-run — all
     CREATE statements are IF NOT EXISTS).
  2. Seeds a camera_network row (connection_state='not_configured') for
     every camera already in cameras.json, so existing cameras show up in
     the new UI immediately without you re-entering anything.

What it never does: touch cameras.json, zones_<id>.json, floor_zones.json,
review_queue.json, or confirmed_merges.json. Those stay exactly as they are.

Rollback: stop the app, delete ops_console.db (and the -wal/-shm files next
to it if present), restart. Nothing else was touched, so there's nothing
else to undo.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from admin_portal import db, store  # noqa: E402


def migrate():
    db.init_db()
    conn = db.get_conn()
    cameras = store.load_cameras()
    seeded = 0
    for cam in cameras:
        cur = conn.execute(
            "INSERT OR IGNORE INTO camera_network (camera_id, connection_state, updated_at) "
            "VALUES (?, 'not_configured', ?)",
            (cam["id"], db.now()),
        )
        if cur.rowcount:
            seeded += 1
    conn.commit()
    print(f"ops_console.db ready at {db.DB_PATH}")
    print(f"Seeded {seeded} new camera_network row(s) from cameras.json "
          f"({len(cameras)} camera(s) total).")


if __name__ == "__main__":
    migrate()

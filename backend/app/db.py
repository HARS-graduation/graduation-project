"""SQLite storage for the Sprint-1 demo.

The production schema is PostgreSQL + PostGIS (see db/schema.postgres.sql).
This module mirrors the same tables and constraints on SQLite so the endpoint can
be demoed and tested on any laptop without a database server. The SQL dialect is
the only thing that changes; column names and rules are identical.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS cameras (
    camera_id     TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    zone          TEXT NOT NULL,
    latitude      REAL NOT NULL CHECK (latitude BETWEEN -90 AND 90),
    longitude     REAL NOT NULL CHECK (longitude BETWEEN -180 AND 180),
    stream_path   TEXT NOT NULL,
    fps_target    REAL NOT NULL DEFAULT 25,
    status        TEXT NOT NULL DEFAULT 'unknown'
                  CHECK (status IN ('online', 'offline', 'frozen', 'unknown')),
    last_seen_at  TEXT,
    is_active     INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS camera_links (
    from_camera_id  TEXT NOT NULL REFERENCES cameras(camera_id) ON DELETE CASCADE,
    to_camera_id    TEXT NOT NULL REFERENCES cameras(camera_id) ON DELETE CASCADE,
    transit_seconds INTEGER NOT NULL CHECK (transit_seconds > 0),
    distance_m      REAL,
    is_bidirectional INTEGER NOT NULL DEFAULT 1 CHECK (is_bidirectional IN (0, 1)),
    PRIMARY KEY (from_camera_id, to_camera_id),
    CHECK (from_camera_id <> to_camera_id)
);

CREATE TABLE IF NOT EXISTS alerts (
    event_id     TEXT PRIMARY KEY,
    event_type   TEXT NOT NULL CHECK (event_type IN (
                     'fight', 'smoking', 'camera_disconnected',
                     'camera_frozen', 'person_handoff')),
    camera_id    TEXT NOT NULL REFERENCES cameras(camera_id),
    occurred_at  TEXT NOT NULL,
    confidence   REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    track_id     TEXT,
    global_id    TEXT,
    clip_uri     TEXT,
    snapshot_uri TEXT,
    reason       TEXT,
    status       TEXT NOT NULL DEFAULT 'new'
                 CHECK (status IN ('new', 'confirmed', 'dismissed')),
    status_by    TEXT,
    status_at    TEXT,
    received_at  TEXT NOT NULL,
    raw_payload  TEXT NOT NULL DEFAULT '{}',
    CHECK (status = 'new' OR status_by IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS alerts_camera_time_idx
    ON alerts (camera_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS alerts_status_time_idx
    ON alerts (status, occurred_at DESC);
CREATE INDEX IF NOT EXISTS alerts_type_time_idx
    ON alerts (event_type, occurred_at DESC);
CREATE INDEX IF NOT EXISTS alerts_global_id_idx
    ON alerts (global_id, occurred_at)
    WHERE global_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS alert_actions (
    action_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id      TEXT NOT NULL REFERENCES alerts(event_id) ON DELETE CASCADE,
    actor_user_id TEXT,
    action        TEXT NOT NULL CHECK (action IN (
                      'created', 'confirmed', 'dismissed', 'commented')),
    from_status   TEXT,
    to_status     TEXT,
    note          TEXT,
    created_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS alert_actions_event_idx
    ON alert_actions (event_id, created_at);

CREATE TABLE IF NOT EXISTS camera_health_events (
    health_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    camera_id       TEXT NOT NULL REFERENCES cameras(camera_id) ON DELETE CASCADE,
    previous_status TEXT,
    new_status      TEXT NOT NULL
                    CHECK (new_status IN ('online', 'offline', 'frozen', 'unknown')),
    reason          TEXT,
    detected_at     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS camera_health_camera_time_idx
    ON camera_health_events (camera_id, detected_at DESC);
"""

# Cameras and transit times taken from the project scope (main gate -> corridor
# ~10 s, corridor -> lab block ~30 s). Coordinates are on the BUC campus.
DEMO_CAMERAS = [
    ("CAM-001", "Main Gate", "Outdoor", 30.0557, 31.2786, "cam-001", 25.0),
    ("CAM-002", "Main Corridor", "Building A", 30.0561, 31.2790, "cam-002", 25.0),
    ("CAM-003", "Lab Block", "Building B", 30.0565, 31.2795, "cam-003", 15.0),
    ("CAM-004", "Parking", "Outdoor", 30.0552, 31.2792, "cam-004", 12.0),
]

DEMO_LINKS = [
    ("CAM-001", "CAM-002", 10, 120.0, 1),
    ("CAM-002", "CAM-003", 30, 260.0, 1),
    ("CAM-001", "CAM-004", 45, 310.0, 1),
]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def connect(db_path: Path | str) -> sqlite3.Connection:
    """Open a connection with sane defaults for a small single-node service."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db(db_path: Path | str, seed_demo_cameras: bool = True) -> None:
    conn = connect(db_path)
    try:
        conn.executescript(SCHEMA_SQL)
        if seed_demo_cameras:
            _seed_cameras(conn)
        conn.commit()
    finally:
        conn.close()


def _seed_cameras(conn: sqlite3.Connection) -> None:
    now = utc_now().isoformat()
    for camera_id, name, zone, lat, lon, stream, fps in DEMO_CAMERAS:
        conn.execute(
            """
            INSERT INTO cameras (camera_id, name, zone, latitude, longitude,
                                 stream_path, fps_target, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'unknown', ?)
            ON CONFLICT (camera_id) DO NOTHING
            """,
            (camera_id, name, zone, lat, lon, stream, fps, now),
        )
    for from_id, to_id, seconds, distance, bidirectional in DEMO_LINKS:
        conn.execute(
            """
            INSERT INTO camera_links (from_camera_id, to_camera_id,
                                      transit_seconds, distance_m, is_bidirectional)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (from_camera_id, to_camera_id) DO NOTHING
            """,
            (from_id, to_id, seconds, distance, bidirectional),
        )

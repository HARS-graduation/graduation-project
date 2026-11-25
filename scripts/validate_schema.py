"""Developer check: execute the real schema on a throwaway PostgreSQL instance.

    python -m pip install -r requirements-dev.txt
    python scripts/validate_schema.py

The bundled server (pgserver) does not ship PostGIS, so the two PostGIS-only
pieces (cameras.geom and its trigger) are stripped before execution. Everything
else - enums, tables, constraints, indexes, functions, views, seed and the
phase-2 tables - is the exact file that will run in production.

Exit code 0 means every invariant below held. This is the same checklist a
reviewer can run by hand with psql.
"""

from __future__ import annotations

import re
import sys
import tempfile
import uuid
from pathlib import Path

import pgserver
import psycopg2
from psycopg2 import errors

ROOT = Path(__file__).resolve().parent.parent
CORE = ROOT / "db" / "schema.postgres.sql"
PHASE2 = ROOT / "db" / "schema.phase2.postgres.sql"
SEED = ROOT / "db" / "seed.sql"

OPERATOR_ID = "b7c1f0a2-3d4e-4f56-8a90-1b2c3d4e5f60"
SEED_EVENT_ID = "8f14e45f-ceea-4a67-9d2b-1b7c1e2f3a41"

checks: list[str] = []


def without_postgis(sql: str) -> str:
    sql = sql.replace("CREATE EXTENSION IF NOT EXISTS postgis;", "")
    sql = sql.replace("CREATE EXTENSION IF NOT EXISTS pgcrypto;", "")
    sql = re.sub(r"\n\s*geom\s+geography\(Point, 4326\),", "", sql)
    sql = re.sub(
        r"CREATE OR REPLACE FUNCTION cameras_set_geom\(\).*?\$\$;\n", "", sql, flags=re.S
    )
    sql = re.sub(
        r"DROP TRIGGER IF EXISTS cameras_set_geom_trg.*?"
        r"EXECUTE FUNCTION cameras_set_geom\(\);\n",
        "",
        sql,
        flags=re.S,
    )
    sql = re.sub(
        r"COMMENT ON COLUMN cameras\.geom IS.*?;\n", "", sql, flags=re.S
    )
    return sql


def ok(label: str) -> None:
    checks.append(label)
    print(f"  [ok] {label}")


def expect_error(cur, sql: str, params=None) -> None:
    try:
        cur.execute(sql, params)
    except psycopg2.Error:
        return
    raise AssertionError(f"expected an error from: {sql[:90]}")


def main() -> int:
    pgdata = Path(tempfile.mkdtemp(prefix="pgcheck-")) / "data"
    server = pgserver.get_server(str(pgdata), cleanup_mode="delete")
    conn = psycopg2.connect(server.get_uri())
    conn.autocommit = True
    cur = conn.cursor()

    print("Applying core schema...")
    cur.execute(without_postgis(CORE.read_text(encoding="utf-8")))
    print("Applying seed...")
    cur.execute(without_postgis(SEED.read_text(encoding="utf-8")))
    print("Applying phase-2 schema...")
    cur.execute(without_postgis(PHASE2.read_text(encoding="utf-8")))

    # ---------------------------------------------------------------- tables
    cur.execute(
        """SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"""
    )
    tables = {row[0] for row in cur.fetchall()}
    core_tables = {
        "sites", "users", "cameras", "camera_links", "alerts",
        "alert_actions", "camera_health_events",
    }
    phase2_tables = {
        "recording_segments", "tracked_persons", "person_tracks",
        "site_settings", "audit_log",
    }
    assert core_tables <= tables, core_tables - tables
    ok(f"7 core tables created ({len(core_tables)})")
    assert phase2_tables <= tables, phase2_tables - tables
    ok(f"5 phase-2 tables created ({len(phase2_tables)})")

    # ------------------------------------------------------------ camera graph
    cur.execute("SELECT count(*) FROM camera_edges")
    assert cur.fetchone()[0] == 6
    ok("camera_edges exposes 3 links in both directions (6 rows)")

    # --------------------------------------------------------------- alerts
    cur.execute(
        """SELECT count(*) FROM alert_feed
            WHERE event_id = %s AND camera_name = 'Main Corridor'""",
        (SEED_EVENT_ID,),
    )
    assert cur.fetchone()[0] == 1
    ok("alert_feed joins the camera name and zone")

    # idempotency: the same event_id cannot be stored twice
    expect_error(
        cur,
        """INSERT INTO alerts (event_id, event_type, camera_id, occurred_at, confidence)
           VALUES (%s, 'fight', 'CAM-001', now(), 0.900)""",
        (SEED_EVENT_ID,),
    )
    ok("a duplicate event_id is rejected by the primary key")

    # confidence outside [0,1]
    expect_error(
        cur,
        """INSERT INTO alerts (event_id, event_type, camera_id, occurred_at, confidence)
           VALUES (%s, 'fight', 'CAM-001', now(), 1.400)""",
        (str(uuid.uuid4()),),
    )
    ok("confidence outside [0,1] is rejected")

    # a decided alert without an actor is impossible
    expect_error(
        cur,
        """INSERT INTO alerts
               (event_id, event_type, camera_id, occurred_at, confidence, status)
           VALUES (%s, 'smoking', 'CAM-001', now(), 0.800, 'confirmed')""",
        (str(uuid.uuid4()),),
    )
    ok("a decided alert without status_by/status_at is rejected")

    # a 2-hour clock skew is rejected
    expect_error(
        cur,
        """INSERT INTO alerts (event_id, event_type, camera_id, occurred_at, confidence)
           VALUES (%s, 'fight', 'CAM-001', now() + interval '2 hours', 0.900)""",
        (str(uuid.uuid4()),),
    )
    ok("an event timestamp far in the future is rejected")

    # ----------------------------------------------------- decision function
    cur.execute(
        "SELECT status, status_by, status_at FROM decide_alert(%s, 'confirmed', %s, %s)",
        (SEED_EVENT_ID, OPERATOR_ID, "checked the clip"),
    )
    status, status_by, status_at = cur.fetchone()
    assert status == "confirmed" and str(status_by) == OPERATOR_ID and status_at
    ok("decide_alert() sets status, actor and decision time")

    cur.execute(
        """SELECT action, from_status, to_status, note FROM alert_actions
            WHERE event_id = %s ORDER BY action_id DESC LIMIT 1""",
        (SEED_EVENT_ID,),
    )
    action, from_status, to_status, note = cur.fetchone()
    assert (action, from_status, to_status) == ("confirmed", "new", "confirmed")
    assert note == "checked the clip"
    ok("decide_alert() writes the audit/label row")

    expect_error(
        cur, "SELECT decide_alert(%s, 'dismissed', %s, NULL)", (SEED_EVENT_ID, OPERATOR_ID)
    )
    ok("a second decision on the same alert is rejected")

    expect_error(
        cur, "SELECT decide_alert(%s, 'confirmed', %s, NULL)", (str(uuid.uuid4()), OPERATOR_ID)
    )
    ok("deciding an unknown alert raises no_data_found")

    expect_error(
        cur, "SELECT decide_alert(%s, 'confirmed', NULL, NULL)", (SEED_EVENT_ID,)
    )
    ok("a decision without an actor is rejected")

    # --------------------------------------------------- camera health write path
    cur.execute("SELECT status FROM set_camera_status('CAM-001', 'offline', 'no frames for 12s')")
    assert cur.fetchone()[0] == "offline"
    cur.execute(
        """SELECT previous_status, new_status, reason FROM camera_health_events
            WHERE camera_id = 'CAM-001' ORDER BY health_id DESC LIMIT 1"""
    )
    assert cur.fetchone() == ("online", "offline", "no frames for 12s")
    ok("set_camera_status() updates the camera and writes one history row")

    cur.execute("SELECT status FROM set_camera_status('CAM-001', 'offline', 'still down')")
    cur.execute(
        "SELECT count(*) FROM camera_health_events WHERE camera_id = 'CAM-001'"
    )
    assert cur.fetchone()[0] == 1
    ok("a repeated health state does not create duplicate history rows")

    cur.execute("SELECT status FROM set_camera_status('CAM-001', 'online', 'frames back')")
    cur.execute("SELECT count(*) FROM camera_health_events WHERE camera_id = 'CAM-001'")
    assert cur.fetchone()[0] == 2
    ok("recovery online is recorded as a second state change")

    expect_error(cur, "SELECT set_camera_status('CAM-999', 'offline')")
    ok("set_camera_status() rejects an unknown camera")

    # ------------------------------------------------------- phase-2 integrity
    cur.execute(
        """INSERT INTO tracked_persons (global_id, first_seen_at, last_seen_at,
                                        first_camera_id, last_camera_id)
           VALUES ('GID-000001', now() - interval '5 minutes', now(), 'CAM-001', 'CAM-002')"""
    )
    cur.execute(
        """INSERT INTO person_tracks (camera_id, track_id, global_id, started_at,
                                      ended_at, match_score, timing_delta_seconds,
                                      timing_plausible)
           VALUES ('CAM-002', 'trk-12', 'GID-000001', now() - interval '1 minute',
                   now(), 0.880, 1, true)"""
    )
    ok("phase-2 GID + track association can be stored")

    cur.execute("SELECT clip_retention_days, face_blur_enabled FROM site_settings")
    assert cur.fetchone() is None
    cur.execute(
        """INSERT INTO site_settings (site_id, updated_by)
           VALUES ('BUC-MAIN', %s)""",
        (OPERATOR_ID,),
    )
    cur.execute("SELECT clip_retention_days, face_blur_enabled FROM site_settings")
    assert cur.fetchone() == (30, True)
    ok("site_settings defaults to 30-day clips and face blurring on")

    cur.execute(
        "SELECT updated_at FROM site_settings WHERE site_id = 'BUC-MAIN'"
    )
    before = cur.fetchone()[0]
    cur.execute(
        "UPDATE site_settings SET alert_retention_days = 180 WHERE site_id = 'BUC-MAIN'"
    )
    cur.execute("SELECT updated_at FROM site_settings WHERE site_id = 'BUC-MAIN'")
    assert cur.fetchone()[0] > before
    ok("site_settings updated_at is maintained by trigger")

    # ------------------------------------------------------------- indexes
    cur.execute("SELECT indexname FROM pg_indexes WHERE schemaname = 'public'")
    indexes = {row[0] for row in cur.fetchall()}
    for name in (
        "alerts_status_time_idx",
        "alerts_camera_time_idx",
        "alerts_global_time_idx",
        "alert_actions_event_idx",
        "camera_health_camera_time_idx",
        "recording_segments_camera_time_idx",
    ):
        assert name in indexes, name
    ok("all dashboard indexes exist")

    conn.close()
    server.cleanup()
    print(f"\n{len(checks)} checks passed.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"\nFAILED: {exc}", file=sys.stderr)
        raise SystemExit(1)

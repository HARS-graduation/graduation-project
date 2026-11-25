"""Data access layer. Everything SQL lives here so the storage can be swapped.

The SQLite version is used for the Sprint-1 demo; moving to PostgreSQL only means
replacing this module (the routes and the JSON contract stay unchanged).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from .schemas import AlertCreate, CameraCreate


class UnknownCamera(Exception):
    def __init__(self, camera_id: str) -> None:
        super().__init__(camera_id)
        self.camera_id = camera_id


class AlertNotFound(Exception):
    def __init__(self, event_id: str) -> None:
        super().__init__(event_id)
        self.event_id = event_id


class InvalidTransition(Exception):
    def __init__(self, current: str, requested: str) -> None:
        super().__init__(f"{current} -> {requested}")
        self.current = current
        self.requested = requested


class CameraAlreadyExists(Exception):
    def __init__(self, camera_id: str) -> None:
        super().__init__(camera_id)
        self.camera_id = camera_id


ALERT_SELECT = """
SELECT a.*, c.name AS camera_name, c.zone AS zone
FROM alerts a
JOIN cameras c ON c.camera_id = a.camera_id
"""


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _parse(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def alert_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    """Map a DB row to the public JSON shape (occurred_at -> timestamp)."""
    return {
        "event_id": row["event_id"],
        "event_type": row["event_type"],
        "camera_id": row["camera_id"],
        "camera_name": row["camera_name"],
        "zone": row["zone"],
        "timestamp": _parse(row["occurred_at"]),
        "confidence": row["confidence"],
        "track_id": row["track_id"],
        "global_id": row["global_id"],
        "clip_uri": row["clip_uri"],
        "snapshot_uri": row["snapshot_uri"],
        "reason": row["reason"],
        "status": row["status"],
        "status_by": row["status_by"],
        "status_at": _parse(row["status_at"]),
        "received_at": _parse(row["received_at"]),
    }


def camera_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "camera_id": row["camera_id"],
        "name": row["name"],
        "zone": row["zone"],
        "latitude": row["latitude"],
        "longitude": row["longitude"],
        "stream_path": row["stream_path"],
        "fps_target": row["fps_target"],
        "status": row["status"],
        "is_active": bool(row["is_active"]),
        "last_seen_at": _parse(row["last_seen_at"]),
        "created_at": _parse(row["created_at"]),
    }


def insert_alert(
    conn: sqlite3.Connection,
    payload: AlertCreate,
    received_at: datetime,
) -> bool:
    """Store an alert. Returns False when event_id already exists (idempotent)."""
    camera = conn.execute(
        "SELECT 1 FROM cameras WHERE camera_id = ? AND is_active = 1",
        (payload.camera_id,),
    ).fetchone()
    if camera is None:
        raise UnknownCamera(payload.camera_id)

    try:
        conn.execute(
            """
            INSERT INTO alerts (
                event_id, event_type, camera_id, occurred_at, confidence,
                track_id, global_id, clip_uri, snapshot_uri, reason, status, received_at,
                raw_payload
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'new', ?, ?)
            """,
            (
                str(payload.event_id),
                payload.event_type,
                payload.camera_id,
                _iso(payload.timestamp),
                float(payload.confidence),
                payload.track_id,
                payload.global_id,
                payload.clip_uri,
                payload.snapshot_uri,
                payload.reason,
                _iso(received_at),
                json.dumps(payload.model_dump(mode="json"), ensure_ascii=False),
            ),
        )
        conn.execute(
            """
            INSERT INTO alert_actions (event_id, actor_user_id, action,
                                       from_status, to_status, created_at)
            VALUES (?, NULL, 'created', NULL, 'new', ?)
            """,
            (str(payload.event_id), _iso(received_at)),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()
        return False
    return True


def get_alert(conn: sqlite3.Connection, event_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        ALERT_SELECT + " WHERE a.event_id = ?", (event_id,)
    ).fetchone()
    return alert_to_dict(row) if row else None


def list_alerts(
    conn: sqlite3.Connection,
    *,
    status: str | None = None,
    event_type: str | None = None,
    camera_id: str | None = None,
    global_id: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    min_confidence: float | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    clauses: list[str] = []
    params: list[Any] = []

    if status:
        clauses.append("a.status = ?")
        params.append(status)
    if event_type:
        clauses.append("a.event_type = ?")
        params.append(event_type)
    if camera_id:
        clauses.append("a.camera_id = ?")
        params.append(camera_id)
    if global_id:
        clauses.append("a.global_id = ?")
        params.append(global_id)
    if since:
        clauses.append("a.occurred_at >= ?")
        params.append(_iso(since))
    if until:
        clauses.append("a.occurred_at <= ?")
        params.append(_iso(until))
    if min_confidence is not None:
        clauses.append("a.confidence >= ?")
        params.append(min_confidence)

    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""

    total = conn.execute(
        "SELECT COUNT(*) AS n FROM alerts a" + where, params
    ).fetchone()["n"]

    rows = conn.execute(
        ALERT_SELECT
        + where
        + " ORDER BY a.occurred_at DESC, a.received_at DESC LIMIT ? OFFSET ?",
        [*params, limit, offset],
    ).fetchall()

    return [alert_to_dict(row) for row in rows], total


def update_alert_status(
    conn: sqlite3.Connection,
    *,
    event_id: str,
    new_status: str,
    actor: str | None,
    note: str | None,
    changed_at: datetime,
) -> dict[str, Any]:
    row = conn.execute(
        "SELECT status FROM alerts WHERE event_id = ?", (event_id,)
    ).fetchone()
    if row is None:
        raise AlertNotFound(event_id)
    if row["status"] != "new":
        raise InvalidTransition(row["status"], new_status)

    # Only an operator can move an alert out of 'new'; status_by is mandatory
    # for a final state, so fall back to the shared demo account when no header
    # is sent. Sprint 2 replaces this with the JWT subject.
    actor = actor or "demo-operator"

    cursor = conn.execute(
        """
        UPDATE alerts
           SET status = ?, status_by = ?, status_at = ?
         WHERE event_id = ? AND status = 'new'
        """,
        (new_status, actor, _iso(changed_at), event_id),
    )
    if cursor.rowcount == 0:
        conn.rollback()
        raise InvalidTransition(row["status"], new_status)

    conn.execute(
        """
        INSERT INTO alert_actions (event_id, actor_user_id, action,
                                   from_status, to_status, note, created_at)
        VALUES (?, ?, ?, 'new', ?, ?, ?)
        """,
        (event_id, actor, new_status, new_status, note, _iso(changed_at)),
    )
    conn.commit()

    updated = get_alert(conn, event_id)
    assert updated is not None
    return updated


def create_camera(
    conn: sqlite3.Connection, payload: CameraCreate, created_at: datetime
) -> dict[str, Any]:
    existing = conn.execute(
        "SELECT 1 FROM cameras WHERE camera_id = ?", (payload.camera_id,)
    ).fetchone()
    if existing is not None:
        raise CameraAlreadyExists(payload.camera_id)

    conn.execute(
        """
        INSERT INTO cameras (camera_id, name, zone, latitude, longitude,
                             stream_path, fps_target, status, is_active, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'unknown', ?, ?)
        """,
        (
            payload.camera_id,
            payload.name,
            payload.zone,
            payload.latitude,
            payload.longitude,
            payload.stream_path,
            payload.fps_target,
            1 if payload.is_active else 0,
            _iso(created_at),
        ),
    )
    conn.commit()
    return get_camera(conn, payload.camera_id)  # type: ignore[return-value]


def get_camera(conn: sqlite3.Connection, camera_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM cameras WHERE camera_id = ?", (camera_id,)
    ).fetchone()
    return camera_to_dict(row) if row else None


def list_cameras(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM cameras ORDER BY camera_id").fetchall()
    return [camera_to_dict(row) for row in rows]

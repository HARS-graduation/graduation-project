from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import build_app


def make_payload(**overrides):
    payload = {
        "event_id": str(uuid.uuid4()),
        "event_type": "fight",
        "camera_id": "CAM-001",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "confidence": 0.91,
        "track_id": "trk-12",
        "global_id": "GID-0001",
        "clip_uri": "s3://alerts/2026/10/27/evt.mp4",
        "reason": "two persons, sudden motion",
    }
    payload.update(overrides)
    return payload


@pytest.fixture()
def client(tmp_path):
    app = build_app(
        Settings(
            db_path=tmp_path / "alerts.db",
            ingest_api_key=None,
            seed_demo_cameras=True,
        )
    )
    with TestClient(app) as test_client:
        yield test_client


def test_post_alert_creates_new_alert(client):
    payload = make_payload()

    response = client.post("/api/v1/alerts", json=payload)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["event_id"] == payload["event_id"]
    assert body["status"] == "new"
    assert body["duplicate"] is False
    assert body["received_at"]

    stored = client.get(f"/api/v1/alerts/{payload['event_id']}")
    assert stored.status_code == 200
    alert = stored.json()
    assert alert["camera_id"] == "CAM-001"
    assert alert["camera_name"] == "Main Gate"
    assert alert["zone"] == "Outdoor"
    assert alert["confidence"] == pytest.approx(0.91)
    assert alert["event_type"] == "fight"
    assert alert["status"] == "new"


def test_post_alert_is_idempotent_on_event_id(client):
    payload = make_payload()

    first = client.post("/api/v1/alerts", json=payload)
    second = client.post("/api/v1/alerts", json=payload)

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["duplicate"] is True

    listed = client.get("/api/v1/alerts").json()
    assert listed["total"] == 1


def test_post_alert_rejects_unknown_camera(client):
    response = client.post("/api/v1/alerts", json=make_payload(camera_id="CAM-999"))

    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "unknown_camera"
    assert error["details"] == {"camera_id": "CAM-999"}


@pytest.mark.parametrize(
    "field,value",
    [
        ("confidence", 1.4),
        ("confidence", -0.1),
        ("event_type", "running"),
        ("status", "confirmed"),
    ],
)
def test_post_alert_validation_errors(client, field, value):
    response = client.post("/api/v1/alerts", json=make_payload(**{field: value}))

    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "validation_error"
    assert any(item["field"] == field for item in body["error"]["details"])


def test_post_alert_requires_timezone(client):
    naive = datetime.now().replace(tzinfo=None).isoformat()

    response = client.post("/api/v1/alerts", json=make_payload(timestamp=naive))

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"


def test_post_alert_rejects_far_future_timestamp(client):
    future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()

    response = client.post("/api/v1/alerts", json=make_payload(timestamp=future))

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"


# --- TC-AL02: QA validation cases ---

def test_post_alert_missing_required_fields(client):
    """TC-AL02: missing required fields -> 400 with validation_error."""
    required = ["event_id", "event_type", "camera_id", "timestamp", "confidence"]
    for field in required:
        payload = make_payload()
        del payload[field]
        response = client.post("/api/v1/alerts", json=payload)
        assert response.status_code == 400, f"missing {field}: {response.text}"
        body = response.json()
        assert body["error"]["code"] == "validation_error"


def test_post_alert_whitespace_camera_id(client):
    """TC-AL02: whitespace-only camera_id -> 400 with validation_error."""
    response = client.post(
        "/api/v1/alerts", json=make_payload(camera_id="   ")
    )
    assert response.status_code == 400, response.text
    body = response.json()
    assert body["error"]["code"] == "validation_error"


def test_post_alert_optional_fields_null_returns_201(client):
    """TC-AL02: null optional fields -> 201, GET returns clean null values."""
    payload = make_payload(track_id=None, global_id=None, clip_uri=None, reason=None)
    response = client.post("/api/v1/alerts", json=payload)
    assert response.status_code == 201, response.text

    stored = client.get(f"/api/v1/alerts/{payload['event_id']}")
    assert stored.status_code == 200
    alert = stored.json()
    assert alert["track_id"] is None
    assert alert["global_id"] is None
    assert alert["clip_uri"] is None
    assert alert["snapshot_uri"] is None
    assert alert["reason"] is None


def test_post_alert_snapshot_uri_sanitized_and_returned(client):
    """snapshot_uri is stripped, empty-string becomes None, and round-trips through GET."""
    uri = "  s3://alerts/snap/evt.jpg  "
    response = client.post(
        "/api/v1/alerts", json=make_payload(snapshot_uri=uri)
    )
    assert response.status_code == 201, response.text

    posted_id = response.json()["event_id"]
    stored = client.get(f"/api/v1/alerts/{posted_id}")
    assert stored.status_code == 200
    alert = stored.json()
    assert alert["snapshot_uri"] == "s3://alerts/snap/evt.jpg"


def test_post_alert_snapshot_uri_empty_becomes_none(client):
    """Whitespace-only snapshot_uri is sanitized to None."""
    response = client.post(
        "/api/v1/alerts", json=make_payload(snapshot_uri="   ")
    )
    assert response.status_code == 201, response.text

    posted_id = response.json()["event_id"]
    stored = client.get(f"/api/v1/alerts/{posted_id}")
    assert stored.status_code == 200
    assert stored.json()["snapshot_uri"] is None


def test_alert_list_filters(client):
    now = datetime.now(timezone.utc)
    client.post("/api/v1/alerts", json=make_payload(event_type="fight", confidence=0.95))
    client.post(
        "/api/v1/alerts",
        json=make_payload(event_type="smoking", camera_id="CAM-002", confidence=0.4),
    )
    client.post(
        "/api/v1/alerts",
        json=make_payload(
            event_type="camera_frozen",
            camera_id="CAM-003",
            confidence=1.0,
            clip_uri=None,
            timestamp=(now - timedelta(days=2)).isoformat(),
        ),
    )

    assert client.get("/api/v1/alerts").json()["total"] == 3

    fights = client.get("/api/v1/alerts", params={"event_type": "fight"}).json()
    assert [item["event_type"] for item in fights["items"]] == ["fight"]

    confident = client.get("/api/v1/alerts", params={"min_confidence": 0.9}).json()
    assert confident["total"] == 2

    by_camera = client.get("/api/v1/alerts", params={"camera_id": "CAM-002"}).json()
    assert by_camera["total"] == 1

    recent = client.get(
        "/api/v1/alerts",
        params={"from": (now - timedelta(hours=1)).isoformat()},
    ).json()
    assert recent["total"] == 2


def test_alert_list_pagination(client):
    for _ in range(3):
        client.post("/api/v1/alerts", json=make_payload())

    page = client.get("/api/v1/alerts", params={"limit": 2, "offset": 2}).json()

    assert page["total"] == 3
    assert page["limit"] == 2
    assert page["offset"] == 2
    assert len(page["items"]) == 1


def test_operator_can_confirm_once(client):
    event_id = make_payload()["event_id"]
    client.post("/api/v1/alerts", json=make_payload(event_id=event_id))

    decision = client.patch(
        f"/api/v1/alerts/{event_id}/status",
        json={"status": "confirmed", "note": "checked the clip"},
        headers={"X-User-Id": "operator-1"},
    )

    assert decision.status_code == 200, decision.text
    alert = decision.json()
    assert alert["status"] == "confirmed"
    assert alert["status_by"] == "operator-1"
    assert alert["status_at"]

    again = client.patch(
        f"/api/v1/alerts/{event_id}/status", json={"status": "dismissed"}
    )
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "invalid_status_transition"


def test_operator_decision_on_missing_alert_returns_404(client):
    response = client.patch(
        f"/api/v1/alerts/{uuid.uuid4()}/status", json={"status": "dismissed"}
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "alert_not_found"


def test_ingest_requires_api_key_when_configured(tmp_path):
    app = build_app(
        Settings(
            db_path=tmp_path / "secured.db",
            ingest_api_key="secret-key",
            seed_demo_cameras=True,
        )
    )
    with TestClient(app) as secured:
        missing = secured.post("/api/v1/alerts", json=make_payload())
        assert missing.status_code == 401
        assert missing.json()["error"]["code"] == "invalid_api_key"

        accepted = secured.post(
            "/api/v1/alerts",
            json=make_payload(),
            headers={"X-API-Key": "secret-key"},
        )
        assert accepted.status_code == 201


def test_camera_registration(client):
    camera = {
        "camera_id": "CAM-010",
        "name": "Library Entrance",
        "zone": "Library",
        "latitude": 30.0568,
        "longitude": 31.2798,
        "stream_path": "cam-010",
        "fps_target": 15,
    }

    created = client.post("/api/v1/cameras", json=camera)
    assert created.status_code == 201
    assert created.json()["status"] == "unknown"
    assert created.json()["is_active"] is True

    duplicate = client.post("/api/v1/cameras", json=camera)
    assert duplicate.status_code == 409

    cameras = client.get("/api/v1/cameras").json()
    assert {item["camera_id"] for item in cameras} >= {
        "CAM-001",
        "CAM-002",
        "CAM-003",
        "CAM-004",
        "CAM-010",
    }


def test_health_endpoint(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["database"] == "ok"


def test_openapi_document_is_generated(client):
    schema = client.get("/openapi.json").json()

    assert "post" in schema["paths"]["/api/v1/alerts"]
    assert "patch" in schema["paths"]["/api/v1/alerts/{event_id}/status"]
    assert schema["info"]["version"].startswith("0.1.0")

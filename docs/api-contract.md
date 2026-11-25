# API contract - Sprint 1 (alerts & cameras)

**Base URL (local):** `http://127.0.0.1:8000`
**Version:** `0.1.0-sprint1` | **Prefix:** `/api/v1`
**Machine-readable spec:** `api/openapi.json` (also served at `/openapi.json`, Swagger UI at `/docs`)

This document is the contract between the **AI services / health monitor** (producers),
the **backend**, and the **React dashboard** (consumer). Any change to a field name,
type or status code is a breaking change and must be agreed by the team first.

---

## 1. Conventions

| Topic | Rule |
| --- | --- |
| Encoding | JSON, `Content-Type: application/json`, UTF-8 |
| Timestamps | ISO-8601 **with offset**, UTC preferred (`2026-10-27T14:32:10.123Z`). Naive timestamps are rejected. Responses are always UTC and end in `Z`. |
| Precision | Milliseconds are enough; the DB keeps microseconds. |
| `confidence` | Float in `[0.0, 1.0]` with 3 decimals. **Not** a percentage. Rule-based events send `1.0`. |
| IDs | `event_id` and `camera_id` are the only identifiers clients need. `global_id` and `track_id` are optional strings. |
| Idempotency | `event_id` is the idempotency key. Re-posting the same event returns `200` with `duplicate: true` and changes nothing. |
| Casing | `snake_case` everywhere (matches Python, PostgreSQL and the AI team's code). |
| Time zone | All stored and returned times are UTC. The dashboard converts to local time. |

---

## 2. Authentication

Sprint 1 uses a **shared secret** so ingestion is not open by accident:

```
X-API-Key: <INGEST_API_KEY>
```

The check is **disabled** when `INGEST_API_KEY` is not set (local development default).
Sprint 2 replaces it with **JWT + RBAC** (`Authorization: Bearer <token>`), and the
`X-User-Id` header below with the JWT `sub` claim.

Operator decisions currently accept an optional `X-User-Id` header (defaults to
`demo-operator` in the spike). In the production schema a decision must reference
a real `users.user_id`, and Sprint 2 replaces the header with the JWT `sub` claim.

---

## 3. Error envelope

Every non-2xx response has this shape, so the dashboard can branch on `code`:

```json
{
  "error": {
    "code": "unknown_camera",
    "message": "Camera 'CAM-999' is not registered or is disabled. Register it with POST /api/v1/cameras first.",
    "details": { "camera_id": "CAM-999" }
  }
}
```

`details` is optional (object or list). Validation errors use a list:

```json
{
  "error": {
    "code": "validation_error",
    "message": "Request validation failed.",
    "details": [
      { "field": "confidence", "message": "Input should be less than or equal to 1" }
    ]
  }
}
```

| `code` | HTTP | When |
| --- | --- | --- |
| `validation_error` | 400 | Body/query does not match the schema (bad enum, confidence out of range, naive timestamp, future timestamp, `status != new` on create, empty or whitespace-only required string fields) |
| `unknown_camera` | 400 | `camera_id` does not exist or `is_active = false` |
| `invalid_api_key` | 401 | `INGEST_API_KEY` configured and header missing/wrong |
| `alert_not_found` | 404 | Unknown `event_id` |
| `invalid_status_transition` | 409 | Alert already `confirmed`/`dismissed` |
| `camera_already_exists` | 409 | Duplicate `camera_id` |
| `not_found` / `method_not_allowed` | 404 / 405 | Unknown route or verb |
| `internal_error` | 500 | Unexpected failure (logged with a stack trace) |

> Why `400` and not `422` for an unknown camera? The request targets the *alerts
> collection*, which exists. The **body** references a camera that cannot be
> resolved, which is a semantic validation failure - same category as a bad enum.

---

## 4. `POST /api/v1/alerts` - the Sprint-1 deliverable

Accepts **one** alert. Independent of the models: anything that can produce JSON can
call it (a Python script, `curl`, the health monitor, a future Kafka consumer).

### Request body

| Field | Type | Required | Rules |
| --- | --- | --- | --- |
| `event_id` | UUID string | yes | v4/v7, unique, immutable, used for retries |
| `event_type` | enum | yes | `fight`, `smoking`, `camera_disconnected`, `camera_frozen`, `person_handoff` |
| `camera_id` | string | yes | 1-64 chars, must exist and be active |
| `timestamp` | ISO-8601 datetime | yes | Must include an offset; at most 5 minutes in the future (clock-skew guard) |
| `confidence` | number | yes | `0.0` to `1.0` |
| `track_id` | string | no | ByteTrack local ID, <= 64 chars |
| `global_id` | string | no | Cross-camera ID (`GID-000123`), <= 64 chars |
| `clip_uri` | string | no | `s3://...` or `file://...`, <= 1024 chars. **Optional this sprint** |
| `snapshot_uri` | string | no | Snapshot/thumbnail URI captured at detection time, <= 1024 chars. **Optional this sprint** |
| `reason` | string | no | Explainable text for the operator, <= 500 chars |
| `status` | enum | no | Only `"new"` is accepted; defaults to `"new"` |

Unknown fields are rejected (`extra="forbid"`) so a typo cannot silently drop data.
`clip_uri` is the only conditional field: when the AI service already wrote the clip
to MinIO it sends the URI, otherwise it sends `null` and the dashboard shows a
placeholder. `person_handoff` alerts usually have no clip.

### Example request

```http
POST /api/v1/alerts HTTP/1.1
Host: 127.0.0.1:8000
Content-Type: application/json
X-API-Key: local-dev-key

{
  "event_id": "8f14e45f-ceea-4a67-9d2b-1b7c1e2f3a41",
  "event_type": "fight",
  "camera_id": "CAM-002",
  "timestamp": "2026-10-27T14:32:10.123Z",
  "confidence": 0.87,
  "track_id": "trk-12",
  "global_id": "GID-000001",
  "clip_uri": "s3://surveillance-alerts/2026/10/27/CAM-002/8f14e45f.mp4",
  "snapshot_uri": "s3://surveillance-alerts/2026/10/27/CAM-002/8f14e45f-snapshot.jpg",
  "reason": "two persons, high motion energy for 3 consecutive seconds"
}
```

### `201 Created`

```json
{
  "event_id": "8f14e45f-ceea-4a67-9d2b-1b7c1e2f3a41",
  "status": "new",
  "duplicate": false,
  "received_at": "2026-10-27T19:03:34.750250Z"
}
```

`received_at` is server time (when the row was written); `timestamp` in the request is
**detection** time. Keeping both lets us measure ingestion latency.

### `200 OK` - retry detected

Same body with `"duplicate": true` and the original `received_at`. The stored alert is
not modified. Producers can retry freely.

### `400 Bad Request` - unknown camera

```json
{
  "error": {
    "code": "unknown_camera",
    "message": "Camera 'CAM-999' is not registered or is disabled. Register it with POST /api/v1/cameras first.",
    "details": { "camera_id": "CAM-999" }
  }
}
```

### `400 Bad Request` - schema violation

```json
{
  "error": {
    "code": "validation_error",
    "message": "Request validation failed.",
    "details": [{ "field": "confidence", "message": "Input should be less than or equal to 1" }]
  }
}
```

### Producer rules (for the AI team)

1. **One row per real occurrence.** Do not emit an alert per frame; use the agreed
   debounce (e.g. smoking: 3 consecutive detections).
2. **`event_id` = UUIDv4 generated at detection time.** On retry, reuse the same value;
   never regenerate it.
3. **`timestamp` = detection time**, not upload time, and always with `Z`/offset.
4. **`confidence` in `[0,1]`**, rounded to 3 decimals.
5. **`track_id` is camera-local.** Two cameras will produce the same `track_id`; it is
   only meaningful together with `camera_id` and a time window.
6. **`global_id` may be missing.** Send the alert anyway; the tracker can enrich later
   (PATCH is not in this sprint, so send what you have).
7. **Clip upload is best-effort.** Send the alert first, upload the clip, and update the
   URI in Sprint 2. Never block the alert on a MinIO write.

---

## 5. `GET /api/v1/alerts` - dashboard feed

Newest first, joined with the camera name and zone.

| Query param | Type | Default | Notes |
| --- | --- | --- | --- |
| `status` | `new \| confirmed \| dismissed` | all | Operator queue = `status=new` |
| `event_type` | enum | all | |
| `camera_id` | string | all | |
| `global_id` | string | all | "Show me everything GID-000123 did" |
| `from` | ISO-8601 | - | `occurred_at >= from` (inclusive) |
| `to` | ISO-8601 | - | `occurred_at <= to` (inclusive) |
| `min_confidence` | float 0..1 | - | Hide weak detections |
| `limit` | int 1..200 | 50 | |
| `offset` | int >= 0 | 0 | |

```json
{
  "items": [
    {
      "event_id": "8f14e45f-ceea-4a67-9d2b-1b7c1e2f3a41",
      "event_type": "fight",
      "camera_id": "CAM-002",
      "camera_name": "Main Corridor",
      "zone": "Building A",
      "timestamp": "2026-10-27T14:32:10.123000Z",
      "confidence": 0.87,
      "track_id": "trk-12",
      "global_id": "GID-000001",
      "clip_uri": "s3://surveillance-alerts/2026/10/27/CAM-002/8f14e45f.mp4",
      "snapshot_uri": "s3://surveillance-alerts/2026/10/27/CAM-002/8f14e45f-snapshot.jpg",
      "reason": "two persons, high motion energy for 3 consecutive seconds",
      "status": "confirmed",
      "status_by": "USER-001",
      "status_at": "2026-10-27T19:03:34.810210Z",
      "received_at": "2026-10-27T19:03:34.750250Z"
    }
  ],
  "total": 1,
  "limit": 1,
  "offset": 0
}
```

`total` is the count **before** pagination, so the dashboard can render "1-50 of 231".

## 6. `GET /api/v1/alerts/{event_id}`

Returns one `AlertOut` object (same shape as an item above) or `404 alert_not_found`.

## 7. `PATCH /api/v1/alerts/{event_id}/status` - operator decision

```json
{ "status": "confirmed", "note": "operator reviewed the clip" }
```

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `status` | `confirmed \| dismissed` | yes | `new` is not a valid target |
| `note` | string <= 500 | no | Stored in the audit log |

* `200` -> updated `AlertOut` with `status_by` and `status_at`.
* `404` -> `alert_not_found`.
* `409` -> `invalid_status_transition` when the alert is already decided.

The decision writes an `alert_actions` row (append-only audit + human-in-the-loop
training label). A decision is final in Sprint 1.

## 8. Cameras

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/v1/cameras` | Map pins, camera grid, status panel |
| `POST` | `/api/v1/cameras` | Register a camera (demo helper until the admin UI exists) |

```json
POST /api/v1/cameras
{
  "camera_id": "CAM-010",
  "name": "Library Entrance",
  "zone": "Library",
  "latitude": 30.0568,
  "longitude": 31.2798,
  "stream_path": "cam-010",
  "fps_target": 15
}
```

`201` returns the camera with `status: "unknown"` and `is_active: true`.
`409 camera_already_exists` on a duplicate ID. Coordinates are validated to be on Earth.
`site_id` is set by the server (default `BUC-MAIN`) until the multi-site UI exists;
the client does not send it yet.

## 9. Meta

| Method | Path | Returns |
| --- | --- | --- |
| `GET` | `/health` | `{"status":"ok","database":"ok","version":"..."}` |
| `GET` | `/` | Service banner + endpoint list |
| `GET` | `/docs` | Swagger UI (interactive) |

## 10. curl examples

```bash
# 1. Post an alert
curl -X POST http://127.0.0.1:8000/api/v1/alerts \
  -H "Content-Type: application/json" \
  -d @api/samples/create_alert_fight.json

# 2. Read the operator queue
curl "http://127.0.0.1:8000/api/v1/alerts?status=new&limit=20"

# 3. Confirm it
curl -X PATCH http://127.0.0.1:8000/api/v1/alerts/8f14e45f-ceea-4a67-9d2b-1b7c1e2f3a41/status \
  -H "Content-Type: application/json" \
  -H "X-User-Id: USER-001" \
  -d "{\"status\":\"confirmed\",\"note\":\"checked the clip\"}"

# 4. Frozen camera event (no clip)
curl -X POST http://127.0.0.1:8000/api/v1/alerts \
  -H "Content-Type: application/json" \
  -d @api/samples/create_alert_camera_frozen.json
```

## 11. Deliberately out of scope for Sprint 1

| Not included | Planned |
| --- | --- |
| JWT login, refresh tokens, RBAC enforcement | Sprint 2 (`/auth/login`, `POST /users`) |
| WebSocket push of new alerts | Sprint 2 (`/ws/alerts`, event bus) |
| Clip upload endpoint (`multipart`) and presigned MinIO URLs | Sprint 2 |
| Alert enrichment after re-identification | Sprint 2 (`PATCH /alerts/{id}` for `global_id`) |
| Camera graph CRUD (`/cameras/{id}/links`) | Sprint 2, needed by Pipeline B |
| Retention/purge jobs, GDPR export | Sprint 3 |
| Realtime camera health thresholds from the DB | Sprint 2 (currently config/env) |

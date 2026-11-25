# Team agreement - Alert / Event contract (Sprint 1)

**Owner:** Mohamed Gehad Abdelmonem (Backend & Frontend)
**Version:** 1.0 - 27 October 2026
**Status:** proposed, open for team sign-off
**Related:** `docs/api-contract.md`, `db/schema.postgres.sql`

This is the one page the whole team needs to agree on **before** the AI services start
emitting events. Everything else (models, thresholds, dashboard widgets) can change
without breaking the pipeline; these field names and rules cannot.

---

## 1. Decisions we are asking the team to confirm

| # | Decision | Rationale |
| --- | --- | --- |
| D1 | The five event types are `fight`, `smoking`, `camera_disconnected`, `camera_frozen`, `person_handoff` | Matches the scope document exactly. No "unknown"/"other" bucket - a new type is a new enum value after agreement. |
| D2 | One alert row = one real occurrence, not one frame | Prevents thousands of rows per incident and keeps the operator queue usable. Debounce lives in the AI service. |
| D3 | `event_id` is a producer-generated UUID and is the idempotency key | Retries must be free. Re-posting the same ID is a no-op (`200 duplicate=true`). |
| D4 | `timestamp` is **detection** time, ISO-8601 **with offset**, UTC | The server also stores `received_at`, so we can measure pipeline latency. Naive datetimes are rejected at the door. |
| D5 | `confidence` is a float in `[0,1]` with 3 decimals, never a percentage | One representation everywhere (Python, DB, API, UI). Rule-based health events send `1.0`. |
| D6 | `clip_uri` is **optional** this sprint | MinIO upload can fail or not be wired yet; the alert is more important than the clip. Dashboard shows a placeholder. |
| D7 | `status` starts as `new` and is owned by the operator | Producers cannot create `confirmed`/`dismissed`. The AI never closes its own alert. |
| D8 | `track_id` is camera-local; `global_id` is cross-camera; both nullable | ByteTrack IDs collide across cameras, and re-identification finishes after the alert is sent. |
| D9 | Unknown fields are rejected, not ignored | A typo such as `confidence_score` must fail loudly in testing, not silently lose data. |
| D10 | `camera_id` values look like `CAM-001` and are never reused | Human-readable on the dashboard and stable in logs/alerts. |

## 2. The minimum viable event (what every producer must send)

```json
{
  "event_id": "8f14e45f-ceea-4a67-9d2b-1b7c1e2f3a41",
  "event_type": "fight",
  "camera_id": "CAM-002",
  "timestamp": "2026-10-27T14:32:10.123Z",
  "confidence": 0.87
}
```

Everything else (`track_id`, `global_id`, `clip_uri`, `reason`, `status`) is optional and
adds detail for the operator.

## 3. Who sends what

| Producer | Sends | Notes |
| --- | --- | --- |
| Fight classifier | `event_type=fight` + `clip_uri` + `reason` | One alert per detected fight window, not per clip chunk |
| Smoking detector | `event_type=smoking` + bounding-box reason text | Fire only after N consecutive detections |
| Tracker / Re-ID | `event_type=person_handoff` + `track_id` + `global_id` + `reason` | GID may be created a moment later; never block on it |
| Health monitor | `event_type=camera_disconnected` or `camera_frozen` + `confidence=1.0` + `reason` | Also updates `cameras.status` and `camera_health_events` |
| Dashboard (operator) | `PATCH .../status` -> `confirmed` / `dismissed` + `note` | Final decision, written to the audit log |

## 4. Rules the producers must follow

1. Generate `event_id` **once**, at detection time; reuse it on every retry.
2. Send UTC with `Z` (or an explicit offset). Do not send local time.
3. Never send `confidence > 1` or a percentage. Round to 3 decimals.
4. Do not send an alert before its camera is registered (`POST /api/v1/cameras`).
5. Do not flood: debounce per camera + event type (suggested: smoking 3 consecutive
   detections, fight minimum 1.5 s of activity, health events on state *change* only).
6. Treat `422 unknown_camera` as a configuration bug, not a retry.

## 5. Field mapping (so nobody renames anything by accident)

| API / event contract | Database | Type | Notes |
| --- | --- | --- | --- |
| `event_id` | `alerts.event_id` | `uuid` PK | idempotency key |
| `event_type` | `alerts.event_type` | `event_type` enum | 5 values |
| `camera_id` | `alerts.camera_id` | `text` FK -> `cameras` | |
| `timestamp` | `alerts.occurred_at` | `timestamptz` | renamed for SQL readability |
| `confidence` | `alerts.confidence` | `numeric(4,3)` | 0.000 - 1.000 |
| `track_id` | `alerts.track_id` | `text` | nullable |
| `global_id` | `alerts.global_id` | `text` | nullable, no FK on purpose |
| `clip_uri` | `alerts.clip_uri` | `text` | nullable this sprint |
| `reason` | `alerts.reason` | `text` | explainable alert |
| `status` | `alerts.status` | `alert_status` enum | `new`/`confirmed`/`dismissed` |
| - | `alerts.received_at` | `timestamptz` | server-side, for latency |
| - | `alerts.raw_payload` | `jsonb` | full producer payload for replay |

## 6. Change process

1. Propose the change in the group with the field, old value, new value and reason.
2. Update `docs/api-contract.md` **and** `backend/app/schemas.py` in the same commit.
3. Bump the contract version (`1.0` -> `1.1`) and note it in the sprint report.
4. A renamed field is a **breaking change**: announce it one day before merging and keep
   the old field readable for one sprint if any producer is mid-work.

## 7. Sign-off

| Member | Role | Agreed? | Date |
| --- | --- | --- | --- |
| Mohamed Gehad Abdelmonem | Backend & Frontend | proposed | 27 Oct 2026 |
| _Fight detection owner_ | AI | | |
| _Smoking detection owner_ | AI | | |
| _Tracking / Re-ID owner_ | AI | | |
| _Health monitor owner_ | AI | | |
| _Dashboard owner_ | Frontend | | |

## 8. Open questions for the team

| # | Question | Owner | Default if unanswered |
| --- | --- | --- | --- |
| Q1 | Minimum confidence to create an alert at all (e.g. 0.5)? | AI leads | Store everything >= 0.5, let the dashboard filter |
| Q2 | Debounce values per event type | AI leads | smoking 3 consecutive frames, fight 1.5 s, health on change |
| Q3 | Are clips uploaded per alert or per incident? | AI + backend | One clip per alert, 10 s before + 5 s after |
| Q4 | Should `person_handoff` appear in the operator queue or only on the map? | Dashboard owner | Map + history, hidden from the default queue |
| Q5 | Retention for alerts vs clips | College admin | alerts 12 months, clips 30 days |

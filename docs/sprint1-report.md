# Sprint 1 report - event contract, database design and ingestion spike

**Project:** Cloud Surveillance and Smart Security Platform (College Scope)
**Sprint:** 1 - data design
**Author:** Mohamed Gehad Abdelmonem - Backend Developer & Frontend Developer
**Date:** 27 October 2026
**Due:** 28 October 2026

---

## 1. Sprint goal

> Agree with the team on the minimum alert/event fields, draft a simple database
> schema for cameras and alerts, and create/documented one basic endpoint that
> accepts a sample alert - kept separate from full model integration.

The sprint freezes the **interface** between the AI services, the database and the
dashboard. Models, thresholds and UI widgets can change afterwards; these names,
types and rules cannot.

## 2. Deliverables

| # | Deliverable | Where | Status |
| --- | --- | --- | --- |
| 1 | Agreed event fields | `docs/team-agreement.md` | ready, awaiting team sign-off |
| 2 | Database design + ER diagram | `docs/database-design.md`, `docs/er-diagram.md`, `docs/diagrams/er-core.png` | done |
| 3 | Executable schema | `db/schema.postgres.sql` (7 core tables), `db/schema.phase2.postgres.sql` (5 designed tables) | done, executed on PostgreSQL 16 |
| 4 | API contract with examples | `docs/api-contract.md`, `api/openapi.json`, `api/samples/` | done |
| 5 | One endpoint that accepts a sample alert | `backend/` (FastAPI spike) | done, 17 tests |
| 6 | Verification | `scripts/validate_schema.py` (21 checks) + API tests | passing |

## 3. What was delivered

### 3.1 The event contract

The scope document already lists the full event fields; the supervisor's minimum
list is a subset. The contract keeps all of them and makes the extras optional, so
no AI service is blocked:

| Field | Required | Type | Notes |
| --- | --- | --- | --- |
| `event_id` | yes | UUID | producer-generated, idempotency key |
| `event_type` | yes | enum | fight, smoking, camera_disconnected, camera_frozen, person_handoff |
| `camera_id` | yes | string | must be a registered camera |
| `timestamp` | yes | ISO-8601 + offset | detection time, UTC |
| `confidence` | yes | 0..1 | three decimals; rule-based events send 1.0 |
| `track_id` | no | string | ByteTrack local ID |
| `global_id` | no | string | cross-camera ID |
| `clip_uri` | no | string | optional this sprint |
| `reason` | no | string | explainable text for the operator |
| `status` | no | enum | `new` only on create |

Nine decisions, a sign-off table and five open questions are in
`docs/team-agreement.md`.

### 3.2 Database design

Seven core tables, chosen so every scope feature has a home without reworking the
model later:

| Table | Purpose |
| --- | --- |
| `sites` | the college today, other campuses later |
| `users` | operator / college admin / system admin, for RBAC and audit |
| `cameras` | registry, map position (PostGIS point), MediaMTX path, current health |
| `camera_links` | the camera graph: measured transit time +/- tolerance |
| `alerts` | one row per real event, the operator queue |
| `alert_actions` | append-only decisions: audit trail + human-in-the-loop labels |
| `camera_health_events` | status timeline (disconnect / freeze / recovery) |

Design points that matter:

* **Idempotent ingestion.** `event_id` is the primary key, so a retry cannot create
  a second alert.
* **One queue, one state machine.** All five event types share the `alerts` table
  and the `new -> confirmed | dismissed` lifecycle.
* **Attribution is mandatory.** A decided alert must have `status_by` and
  `status_at`; the table check makes a half-finished decision impossible.
* **State changes go through functions.** `decide_alert()` locks the row, rejects a
  second decision and writes the audit row atomically. `set_camera_status()`
  updates the camera and writes the history row only on a real state change.
* **The graph carries a window, not an average.** `10 s +/- 3 s`, so Pipeline B can
  reject impossible handoffs before comparing appearance.
* **Phase 2 is additive.** Recordings, Global IDs, retention policy and the admin
  audit log live in `schema.phase2.postgres.sql`; no core table changes when they
  are enabled.

The full data dictionary, invariants, query/index mapping, capacity estimates,
privacy rules and rejected alternatives are in `docs/database-design.md`.

### 3.3 The endpoint (parked spike)

`POST /api/v1/alerts` was implemented early to prove the contract is usable:

```http
POST /api/v1/alerts
{
  "event_id": "8f14e45f-ceea-4a67-9d2b-1b7c1e2f3a41",
  "event_type": "fight",
  "camera_id": "CAM-002",
  "timestamp": "2026-10-27T14:32:10.123Z",
  "confidence": 0.87,
  "clip_uri": "s3://.../8f14e45f.mp4",
  "reason": "two persons, high motion energy for 3 consecutive seconds"
}
```

```json
201 Created
{ "event_id": "8f14e45f-...", "status": "new", "duplicate": false,
  "received_at": "2026-10-27T19:03:34.750250Z" }
```

A second POST with the same `event_id` returns `200` with `duplicate: true`.
The spike also has listing, filtering and confirm/dismiss, all covered by 17 tests.

**It is explicitly a spike.** It runs on SQLite and predates `sites`, the write
functions and the stricter decision rules. It will be rebuilt on PostgreSQL after
the design is approved; the JSON contract is the part that survives.

## 4. Verification

### 4.1 The schema really runs

```
python scripts/validate_schema.py
Applying core schema...
Applying seed...
Applying phase-2 schema...
  [ok] 7 core tables created (7)
  [ok] 5 phase-2 tables created (5)
  [ok] camera_edges exposes 3 links in both directions (6 rows)
  [ok] alert_feed joins the camera name and zone
  [ok] a duplicate event_id is rejected by the primary key
  [ok] confidence outside [0,1] is rejected
  [ok] a decided alert without status_by/status_at is rejected
  [ok] an event timestamp far in the future is rejected
  [ok] decide_alert() sets status, actor and decision time
  [ok] decide_alert() writes the audit/label row
  [ok] a second decision on the same alert is rejected
  [ok] deciding an unknown alert raises no_data_found
  [ok] a decision without an actor is rejected
  [ok] set_camera_status() updates the camera and writes one history row
  [ok] a repeated health state does not create duplicate history rows
  [ok] recovery online is recorded as a second state change
  [ok] set_camera_status() rejects an unknown camera
  [ok] phase-2 GID + track association can be stored
  [ok] site_settings defaults to 30-day clips and face blurring on
  [ok] site_settings updated_at is maintained by trigger
  [ok] all dashboard indexes exist

21 checks passed.
```

The test server does not bundle PostGIS, so `cameras.geom` and its trigger are
validated by review only; everything else is executed by PostgreSQL 16.

### 4.2 The API spike

```
cd backend
python -m pytest
.................                                                        [100%]
17 passed
```

### 4.3 Reviewer checklist (5 minutes)

1. Open `docs/diagrams/er-core.png` - the seven tables and their relationships.
2. Read `docs/database-design.md` section 15 - the decisions and the alternatives.
3. Run `python scripts/validate_schema.py` - 21 green checks.
4. Open `db/schema.postgres.sql` - every non-obvious column has a comment.

## 5. Top design decisions

| # | Decision | Why |
| --- | --- | --- |
| 1 | `event_id` is the primary key | retries are safe without a distributed lock |
| 2 | One `alerts` table for all event types | one operator queue, one decision flow |
| 3 | Decisions only through `decide_alert()` | the state machine and the audit row cannot be bypassed |
| 4 | `cameras.status` cached + history table | fast dashboard reads, full timeline, no drift |
| 5 | `sites` table from day one | the scope explicitly allows a second campus |
| 6 | No FK on `alerts.global_id` | an alert may arrive before the GID is committed |
| 7 | No partitioning now | ~44k alerts/year does not justify it; the threshold is documented |
| 8 | `clip_uri` nullable | a MinIO failure must not lose an incident |

## 6. Limitations (honest list)

| Limitation | Impact | Plan |
| --- | --- | --- |
| The API spike uses SQLite | not the production store | rebuild on PostgreSQL + the functions |
| PostGIS not executed locally | `geom` trigger unverified by execution | run the DDL on the deployment DB before the demo |
| Auth not implemented | decisions use a temporary header | JWT + RBAC in Sprint 2 |
| No replay / GID tables yet | phase-2 only | create when the features land (DDL is ready) |
| No Alembic migrations | schema applied by hand | Alembic revision 1 in Sprint 2 |
| Retention jobs not written | data grows | MinIO lifecycle + nightly jobs in Sprint 2 |

## 7. Next sprint (proposed)

| # | Task | Owner | Depends on |
| --- | --- | --- | --- |
| 1 | Apply the schema on the real PostgreSQL/PostGIS, add Alembic | Backend | design sign-off |
| 2 | JWT login + RBAC + `/auth/login` | Backend | 1 |
| 3 | Rebuild alert endpoints on PostgreSQL using `decide_alert()` | Backend | 1, 2 |
| 4 | WebSocket `/ws/alerts` + event bus | Backend | 3 |
| 5 | Dashboard: camera grid, alert queue, confirm/dismiss | Frontend | 3 |
| 6 | Emit fight/smoking alerts from the models through the contract | AI | contract sign-off |
| 7 | Camera health monitor writing `camera_health_events` | AI | 1 |
| 8 | Clip upload to MinIO + presigned playback | Backend + AI | 3 |

## 8. Files

```
graduation-project/
  README.md
  requirements.txt / requirements-dev.txt / .env.example
  db/
    schema.postgres.sql            core DDL, 7 tables
    schema.phase2.postgres.sql     additive DDL, 5 tables
    seed.sql                       demo site, cameras, graph, actor, alert
    schema.dbml                    ER source
  docs/
    database-design.md             full design document
    er-diagram.md                  one-page visual
    diagrams/er-core.png|svg       rendered ER
    team-agreement.md              event contract
    api-contract.md                endpoint contract
    sprint1-report.md              this report
  scripts/
    validate_schema.py             21 schema assertions
    render_er.py                   diagram generator
    send_sample_alert.py           demo client for the spike
  backend/                         parked FastAPI spike (SQLite, 17 tests)
  api/                             OpenAPI export + samples
```

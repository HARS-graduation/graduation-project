# Smart College Surveillance - Sprint 1

Part of the graduation project *Cloud Surveillance and Smart Security Platform
(College Scope)*.

**Current stage: database design.** The schema, the ER diagram and the design
document are the deliverables for 28 October. The API in `backend/` is an earlier
spike kept for reference; it will be rebuilt against this schema once the design
is signed off.

## Deliverables

| Deliverable | File |
| --- | --- |
| Team agreement on the minimum event fields | [`docs/team-agreement.md`](docs/team-agreement.md) |
| Database design (full document) | [`docs/database-design.md`](docs/database-design.md) |
| ER diagram | [`docs/er-diagram.md`](docs/er-diagram.md), [`docs/diagrams/er-core.png`](docs/diagrams/er-core.png) |
| Executable schema | [`db/schema.postgres.sql`](db/schema.postgres.sql) |
| Phase-2 schema (additive) | [`db/schema.phase2.postgres.sql`](db/schema.phase2.postgres.sql) |
| API contract + examples | [`docs/api-contract.md`](docs/api-contract.md), [`api/openapi.json`](api/openapi.json), [`api/samples/`](api/samples) |
| Schema validation | [`scripts/validate_schema.py`](scripts/validate_schema.py) - 21 checks |
| **One-file overview (PDF)** | [`docs/deliverables/design-overview.pdf`](docs/deliverables/design-overview.pdf) - file tree + per-file details |

## The design in one screen

Seven core tables:

```
sites ──< cameras ──< alerts ──< alert_actions
            │           ▲
            ├──< camera_links (the camera graph: transit time + tolerance)
            └──< camera_health_events (status timeline)
users ──────┘  (decides alerts, appears in the audit log)
```

Key properties:

* `alerts.event_id` is a producer-generated UUID and the **idempotency key**:
  a retry can never create a duplicate.
* One `alerts` table for all five event types; the operator sees one queue.
* A decided alert **must** have an actor and a timestamp; a second decision is
  impossible (`decide_alert()` locks the row).
* `cameras.status` is changed only through `set_camera_status()`, which writes the
  history row in the same transaction.
* The camera graph stores a measured time **window** (`10 s +/- 3 s`), not just an
  average, because that is what Pipeline B needs to reject impossible handoffs.
* Replay, Global IDs, retention and the admin audit log are already designed in
  `schema.phase2.postgres.sql` and require **no change** to the core tables.

## Read it in this order

1. [`docs/database-design.md`](docs/database-design.md) - requirements trace,
   principles, ERD, data dictionary, invariants, indexes, privacy, decisions.
2. [`docs/er-diagram.md`](docs/er-diagram.md) - the one-page visual.
3. [`docs/team-agreement.md`](docs/team-agreement.md) - what the team must agree on.
4. [`db/schema.postgres.sql`](db/schema.postgres.sql) - the executable truth.

## Validate the schema (really runs it)

```powershell
cd graduation-project
python -m pip install -r requirements-dev.txt
python scripts/validate_schema.py
```

Expected output: `21 checks passed.` It starts a throwaway PostgreSQL 16, applies
the core schema, the seed and the phase-2 schema, then asserts the constraints,
both functions, the views and the indexes. PostGIS is not bundled with the test
server, so `cameras.geom` and its trigger are the only pieces not executed there;
they are standard PostGIS and run on the deployment database.

## Regenerate the ER diagram

```powershell
python scripts/render_er.py
```

Reads `db/schema.dbml`, removes the enum boxes (listed in the document instead)
and writes `docs/diagrams/er-core.svg` and `.png`. The DBML also pastes directly
into <https://dbdiagram.io> for an interactive version.

## The API spike (parked)

`backend/` contains a working FastAPI slice with 17 tests that was written before
the design was refined. It is useful as evidence of the ingestion contract, but it
is **not** the implementation we will keep: it uses SQLite and predates `sites`,
the write functions and the stricter decision rules. It will be rebuilt on
PostgreSQL once the schema is approved.

```powershell
cd graduation-project
python -m pip install -r requirements.txt
cd backend
uvicorn app.main:app --reload --port 8000   # Swagger at /docs
python -m pytest                            # 17 passed
```

## Layout

```
graduation-project/
  db/
    schema.postgres.sql          core DDL (7 tables, 2 functions, 2 views, triggers)
    schema.phase2.postgres.sql   additive DDL (5 tables: recordings, GIDs, retention, audit)
    seed.sql                     demo site, 4 cameras, camera graph, demo actor, 1 alert
    schema.dbml                  ER source for dbdiagram.io
  docs/
    database-design.md           the main design document
    er-diagram.md                one-page visual reference
    diagrams/er-core.png|svg     rendered ER
    team-agreement.md            event contract to sign off
    api-contract.md              endpoint contract + examples
    sprint1-report.md            sprint summary
  scripts/
    validate_schema.py           21 assertions on a real PostgreSQL
    render_er.py                 regenerates the diagram from the DBML
  backend/                       parked Sprint-1 API spike (SQLite)
  api/                           OpenAPI export + request/response samples
```

## Scope boundaries

* No AI models, MediaMTX, MinIO or dashboard code in this sprint.
* No face recognition: appearance embeddings only (scope requirement).
* Login/JWT, replay, Global IDs, retention jobs and the audit log are designed
  (phase 2) but not implemented yet.
* The schema is PostgreSQL 15+ with PostGIS; the API spike uses SQLite only so it
  can run on any laptop.

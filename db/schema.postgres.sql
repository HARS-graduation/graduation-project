-- =====================================================================
--  Smart College Surveillance Platform
--  Sprint 1 database design - CORE schema (cameras, alerts, decisions)
-- =====================================================================
--
--  Target : PostgreSQL 15+ with PostGIS 3.x
--  Status : design draft v2 (27 Oct 2026)
--  Author : Mohamed Gehad Abdelmonem - Backend & Frontend
--
--  Apply a fresh database:
--      createdb surveillance
--      psql -d surveillance -v ON_ERROR_STOP=1 -f db/schema.postgres.sql
--      psql -d surveillance -v ON_ERROR_STOP=1 -f db/seed.sql
--
--  Phase-2 tables (recordings, global IDs, privacy settings, audit log)
--  are additive and live in db/schema.phase2.postgres.sql. Nothing below
--  has to change when they are added.
--
--  Reading order:
--    1. sites, users                  reference data
--    2. cameras, camera_links         the camera graph + live map
--    3. alerts                        one row per event (the operator queue)
--    4. alert_actions                 append-only decisions (audit + ML labels)
--    5. camera_health_events          status timeline
--    6. functions (the only write paths for status changes)
--    7. views (what the API and the dashboard read)
-- =====================================================================

BEGIN;

CREATE EXTENSION IF NOT EXISTS postgis;    -- geography(Point, 4326)
-- gen_random_uuid() is built into PostgreSQL 13+, so no pgcrypto is needed.

-- ---------------------------------------------------------------------
-- 0. Enumerations
--    Fixed, small value sets. Chosen over lookup tables because they are
--    part of the API contract and are validated in the database.
--    Adding a value: ALTER TYPE ... ADD VALUE (safe, transactional in PG12+).
--    Removing a value is a migration - plan the list carefully.
-- ---------------------------------------------------------------------
DO $$ BEGIN
    CREATE TYPE event_type AS ENUM (
        'fight',
        'smoking',
        'camera_disconnected',
        'camera_frozen',
        'person_handoff'
    );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE alert_status AS ENUM ('new', 'confirmed', 'dismissed');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE camera_status AS ENUM ('online', 'offline', 'frozen', 'unknown');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE user_role AS ENUM (
        'security_operator',
        'college_admin',
        'system_admin'
    );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- ---------------------------------------------------------------------
-- 1. Sites
--    The scope is one college, but the document says other sites may be
--    added later. One row today; site_id is carried by every camera.
--    timezone matters for "time of day" anomaly detection (innovation I-2).
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sites (
    site_id     text PRIMARY KEY
                CHECK (site_id ~ '^[A-Z0-9][A-Z0-9-]{1,31}$'),
    name        text NOT NULL CHECK (length(btrim(name)) BETWEEN 2 AND 120),
    timezone    text NOT NULL DEFAULT 'Africa/Cairo',
    address     text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE sites IS
    'A campus. One row for the college today; the schema is already multi-site.';

-- ---------------------------------------------------------------------
-- 2. Users
--    Three roles from the scope. Accounts are deactivated, never deleted,
--    because alerts and audit rows point at them.
--    site_id NULL = access to all sites (system admin), set = scoped user.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    user_id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    site_id       text REFERENCES sites(site_id) ON DELETE RESTRICT,
    email         text NOT NULL CHECK (position('@' IN email) > 1),
    full_name     text NOT NULL CHECK (length(btrim(full_name)) BETWEEN 2 AND 120),
    role          user_role NOT NULL DEFAULT 'security_operator',
    password_hash text NOT NULL CHECK (password_hash <> ''),
    is_active     boolean NOT NULL DEFAULT true,
    last_login_at timestamptz,
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now()
);

-- Case-insensitive uniqueness without the citext extension.
CREATE UNIQUE INDEX IF NOT EXISTS users_email_lower_key ON users (lower(email));

COMMENT ON COLUMN users.password_hash IS
    'Argon2id/bcrypt hash only. Never selected by the read API, never logged.';
COMMENT ON COLUMN users.site_id IS
    'NULL = all sites. Set for operators/admins scoped to one campus.';

-- ---------------------------------------------------------------------
-- 3. Cameras
--    camera_id is the public, stable identifier used in every event
--    (''CAM-001''). It must be globally unique, even after a second site is
--    added - use a site prefix such as BUC-CAM-001 for new sites.
--    Deleting a camera would orphan history, so is_active=false instead.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cameras (
    camera_id    text PRIMARY KEY
                 CHECK (camera_id ~ '^[A-Z0-9][A-Z0-9_-]{2,63}$'),
    site_id      text NOT NULL REFERENCES sites(site_id) ON DELETE RESTRICT,
    name         text NOT NULL CHECK (length(btrim(name)) BETWEEN 2 AND 120),
    zone         text NOT NULL CHECK (length(btrim(zone)) BETWEEN 1 AND 120),
    latitude     double precision NOT NULL CHECK (latitude BETWEEN -90 AND 90),
    longitude    double precision NOT NULL CHECK (longitude BETWEEN -180 AND 180),
    geom         geography(Point, 4326),
    stream_path  text NOT NULL UNIQUE
                 CHECK (stream_path ~ '^[a-z0-9][a-z0-9-]{1,63}$'),
    rtsp_url     text,
    fps_target   numeric(5,2) NOT NULL DEFAULT 25
                 CHECK (fps_target > 0 AND fps_target <= 120),
    status       camera_status NOT NULL DEFAULT 'unknown',
    last_seen_at timestamptz,
    is_active    boolean NOT NULL DEFAULT true,
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT cameras_rtsp_url_scheme
        CHECK (rtsp_url IS NULL OR rtsp_url ~* '^rtsps?://')
);

-- Health panel: "which active cameras are not healthy right now?"
CREATE INDEX IF NOT EXISTS cameras_attention_idx
    ON cameras (last_seen_at DESC)
    WHERE is_active AND status <> 'online';

COMMENT ON COLUMN cameras.camera_id IS
    'Stable public ID used by every event. Never reused after decommission.';
COMMENT ON COLUMN cameras.stream_path IS
    'MediaMTX path, e.g. cam-001. Unique because MediaMTX keys streams by path.';
COMMENT ON COLUMN cameras.rtsp_url IS
    'Sensitive: edge-pull source URL. Readable by system_admin only; never exposed to the browser.';
COMMENT ON COLUMN cameras.geom IS
    'Set from latitude/longitude by trigger. Used for map and nearest-camera queries.';
COMMENT ON COLUMN cameras.status IS
    'Current health state. Changed only through set_camera_status(), which also writes camera_health_events.';

-- ---------------------------------------------------------------------
-- 4. Camera graph (transit times)
--    Pipeline B uses this to reject impossible handoffs before comparing
--    appearance embeddings. transit_tolerance_seconds is the measured
--    walking-time window (e.g. 10 s +/- 3 s), not a guessed constant.
--    Both directions are exposed through the camera_edges view.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS camera_links (
    from_camera_id text NOT NULL REFERENCES cameras(camera_id) ON DELETE CASCADE,
    to_camera_id   text NOT NULL REFERENCES cameras(camera_id) ON DELETE CASCADE,
    transit_seconds integer NOT NULL CHECK (transit_seconds > 0),
    transit_tolerance_seconds integer NOT NULL DEFAULT 5
                  CHECK (transit_tolerance_seconds >= 0),
    distance_m     numeric(8,2) CHECK (distance_m IS NULL OR distance_m >= 0),
    is_bidirectional boolean NOT NULL DEFAULT true,
    measured_at    date,
    notes          text,
    PRIMARY KEY (from_camera_id, to_camera_id),
    CONSTRAINT camera_links_distinct CHECK (from_camera_id <> to_camera_id),
    CONSTRAINT camera_links_tolerance_fits CHECK (transit_tolerance_seconds < transit_seconds)
);

CREATE INDEX IF NOT EXISTS camera_links_reverse_idx
    ON camera_links (to_camera_id);

COMMENT ON TABLE camera_links IS
    'Directed edges of the camera graph with measured walking times. The tracker accepts a handoff only inside transit_seconds +/- tolerance.';

-- ---------------------------------------------------------------------
-- 5. Alerts
--    One row = one real occurrence (not one video frame). event_id is
--    generated by the producer, which makes ingestion idempotent: a retry
--    collides on the primary key and is ignored.
--
--    Fields follow the agreed event contract:
--      event_id, event_type, camera_id, timestamp, confidence,
--      track_id, global_id, clip_uri, reason, status
--    API "timestamp" is stored as occurred_at (SQL readability).
--
--    A decision is final in Sprint 1: new -> confirmed | dismissed.
--    Corrections are new alert_actions rows, never an UPDATE of history.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS alerts (
    event_id     uuid PRIMARY KEY,
    event_type   event_type NOT NULL,
    camera_id    text NOT NULL REFERENCES cameras(camera_id) ON DELETE RESTRICT,
    occurred_at  timestamptz NOT NULL,
    confidence   numeric(4,3) NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    track_id     text CHECK (track_id IS NULL OR length(track_id) BETWEEN 1 AND 64),
    global_id    text CHECK (global_id IS NULL OR length(global_id) BETWEEN 1 AND 64),
    clip_uri     text CHECK (clip_uri IS NULL OR length(clip_uri) BETWEEN 1 AND 1024),
    snapshot_uri text CHECK (snapshot_uri IS NULL OR length(snapshot_uri) BETWEEN 1 AND 1024),
    reason       text CHECK (reason IS NULL OR length(reason) <= 500),
    status       alert_status NOT NULL DEFAULT 'new',
    status_by    uuid REFERENCES users(user_id) ON DELETE RESTRICT,
    status_at    timestamptz,
    received_at  timestamptz NOT NULL DEFAULT now(),
    raw_payload  jsonb NOT NULL DEFAULT '{}'::jsonb,

    -- A decided alert always has an actor and a decision time; a new one has neither.
    CONSTRAINT alerts_decision_complete CHECK (
        (status = 'new' AND status_by IS NULL AND status_at IS NULL)
        OR
        (status <> 'new' AND status_by IS NOT NULL AND status_at IS NOT NULL)
    ),
    -- Producer clocks may drift a little; more than 10 minutes ahead is a bug.
    CONSTRAINT alerts_occurred_not_after_receipt CHECK (
        occurred_at <= received_at + interval '10 minutes'
    )
);

-- Operator queue: newest unresolved first (covers status+time; no extra index needed).
CREATE INDEX IF NOT EXISTS alerts_status_time_idx
    ON alerts (status, occurred_at DESC);
-- Camera history and live grid.
CREATE INDEX IF NOT EXISTS alerts_camera_time_idx
    ON alerts (camera_id, occurred_at DESC);
-- Person journey across cameras (only rows that have a global ID).
CREATE INDEX IF NOT EXISTS alerts_global_time_idx
    ON alerts (global_id, occurred_at)
    WHERE global_id IS NOT NULL;

COMMENT ON COLUMN alerts.event_id IS
    'Producer-generated UUID. Primary key = idempotency key: a retry cannot create a duplicate.';
COMMENT ON COLUMN alerts.occurred_at IS
    'Detection time reported by the producer. Exposed as "timestamp" in the API.';
COMMENT ON COLUMN alerts.confidence IS
    'Model confidence in [0,1] with 3 decimals. Not a percentage. Rule-based health events send 1.000.';
COMMENT ON COLUMN alerts.track_id IS
    'ByteTrack local ID, unique only inside one camera and time window.';
COMMENT ON COLUMN alerts.global_id IS
    'Cross-camera person ID from the re-identification pipeline. No FK on purpose: an alert may arrive before the GID row is committed.';
COMMENT ON COLUMN alerts.clip_uri IS
    'Optional in Sprint 1. s3:// URI of the materialised clip; NULL means the dashboard plays the recording window instead.';
COMMENT ON COLUMN alerts.snapshot_uri IS
    'Optional in Sprint 1. Snapshot/thumbnail URI captured at detection time; NULL when unavailable.';
COMMENT ON COLUMN alerts.raw_payload IS
    'Original producer payload for replay/debugging. Never returned by the API.';
COMMENT ON COLUMN alerts.status IS
    'new -> confirmed | dismissed. Final; re-opening is a new audited action, not an UPDATE.';

-- ---------------------------------------------------------------------
-- 6. Alert actions (append-only)
--    Two jobs at once:
--      a) audit trail: who decided what, when, with which note
--      b) human-in-the-loop training labels (innovation I-3)
--    'created' rows are written by the ingestion path (system actor = NULL).
--    'commented' and 'reopened' are reserved for later sprints.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS alert_actions (
    action_id     bigserial PRIMARY KEY,
    event_id      uuid NOT NULL REFERENCES alerts(event_id) ON DELETE CASCADE,
    actor_user_id uuid REFERENCES users(user_id) ON DELETE RESTRICT,
    action        text NOT NULL CHECK (action IN (
                      'created', 'confirmed', 'dismissed', 'commented', 'reopened')),
    from_status   alert_status,
    to_status     alert_status,
    note          text CHECK (note IS NULL OR length(note) <= 1000),
    created_at    timestamptz NOT NULL DEFAULT now(),

    -- Only the system can create an alert; every human action has an actor.
    CONSTRAINT alert_actions_actor_shape CHECK (
        (action = 'created' AND actor_user_id IS NULL)
        OR (action <> 'created' AND actor_user_id IS NOT NULL)
    ),
    -- A confirmation/dismissal always starts from 'new' and lands on itself.
    CONSTRAINT alert_actions_decision_shape CHECK (
        action NOT IN ('confirmed', 'dismissed')
        OR (from_status = 'new' AND to_status::text = action)
    )
);

CREATE INDEX IF NOT EXISTS alert_actions_event_idx
    ON alert_actions (event_id, created_at);

COMMENT ON TABLE alert_actions IS
    'Append-only audit log of every create/decision. Also the label source for human-in-the-loop retraining.';

-- ---------------------------------------------------------------------
-- 7. Camera health timeline
--    One row per real state change (online -> offline -> online ...).
--    The current state is denormalised on cameras.status for fast reads;
--    set_camera_status() keeps both in sync in one transaction.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS camera_health_events (
    health_id       bigserial PRIMARY KEY,
    camera_id       text NOT NULL REFERENCES cameras(camera_id) ON DELETE CASCADE,
    previous_status camera_status,
    new_status      camera_status NOT NULL,
    reason          text,
    detected_at     timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT camera_health_status_changed CHECK (
        previous_status IS NULL OR previous_status <> new_status
    )
);

CREATE INDEX IF NOT EXISTS camera_health_camera_time_idx
    ON camera_health_events (camera_id, detected_at DESC);

COMMENT ON COLUMN camera_health_events.reason IS
    'Explainable text, e.g. "no frames for 12 s (timeout 10 s)" or "frozen 30 s (SSIM 0.998)".';

-- ---------------------------------------------------------------------
-- 8. Triggers
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION touch_updated_at() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS sites_touch_updated_at ON sites;
CREATE TRIGGER sites_touch_updated_at
    BEFORE UPDATE ON sites
    FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

DROP TRIGGER IF EXISTS users_touch_updated_at ON users;
CREATE TRIGGER users_touch_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

DROP TRIGGER IF EXISTS cameras_touch_updated_at ON cameras;
CREATE TRIGGER cameras_touch_updated_at
    BEFORE UPDATE ON cameras
    FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

CREATE OR REPLACE FUNCTION cameras_set_geom() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    NEW.geom := ST_SetSRID(ST_MakePoint(NEW.longitude, NEW.latitude), 4326)::geography;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS cameras_set_geom_trg ON cameras;
CREATE TRIGGER cameras_set_geom_trg
    BEFORE INSERT OR UPDATE OF latitude, longitude ON cameras
    FOR EACH ROW EXECUTE FUNCTION cameras_set_geom();

-- ---------------------------------------------------------------------
-- 9. Write-path functions
--    Invariants that must never be bypassed live here, not in the API:
--      * a camera status change always produces a history row
--      * an alert decision is atomic, attributed and one-way
--    The API calls these functions; direct UPDATEs are revoked in production.
-- ---------------------------------------------------------------------

-- Change a camera's health state. No-op if the state did not change.
CREATE OR REPLACE FUNCTION set_camera_status(
    p_camera_id   text,
    p_status      camera_status,
    p_reason      text DEFAULT NULL,
    p_detected_at timestamptz DEFAULT now()
) RETURNS cameras
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_camera   cameras%ROWTYPE;
    v_previous camera_status;
BEGIN
    SELECT * INTO v_camera
      FROM cameras
     WHERE camera_id = p_camera_id
       FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'unknown camera: %', p_camera_id
              USING ERRCODE = 'no_data_found';
    END IF;

    v_previous := v_camera.status;

    -- Heartbeat for a healthy camera: only last_seen_at moves.
    IF v_previous = p_status THEN
        IF p_status = 'online' THEN
            UPDATE cameras
               SET last_seen_at = p_detected_at
             WHERE camera_id = p_camera_id
             RETURNING * INTO v_camera;
        END IF;
        RETURN v_camera;
    END IF;

    UPDATE cameras
       SET status       = p_status,
           last_seen_at = CASE WHEN p_status = 'online'
                               THEN p_detected_at
                               ELSE last_seen_at
                          END
     WHERE camera_id = p_camera_id
     RETURNING * INTO v_camera;

    INSERT INTO camera_health_events
        (camera_id, previous_status, new_status, reason, detected_at)
    VALUES
        (p_camera_id, v_previous, p_status, p_reason, p_detected_at);

    RETURN v_camera;
END;
$$;

COMMENT ON FUNCTION set_camera_status IS
    'The only supported way to change cameras.status. Writes camera_health_events atomically and ignores no-op changes. SECURITY DEFINER so the API role needs no UPDATE on cameras.status.';

REVOKE ALL ON FUNCTION set_camera_status(text, camera_status, text, timestamptz)
    FROM PUBLIC;

-- Record an operator decision atomically.
CREATE OR REPLACE FUNCTION decide_alert(
    p_event_id uuid,
    p_status   alert_status,
    p_actor    uuid,
    p_note     text DEFAULT NULL
) RETURNS alerts
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_alert alerts%ROWTYPE;
BEGIN
    IF p_status NOT IN ('confirmed', 'dismissed') THEN
        RAISE EXCEPTION 'a decision must be confirmed or dismissed, got %', p_status
              USING ERRCODE = 'check_violation';
    END IF;

    IF p_actor IS NULL THEN
        RAISE EXCEPTION 'a decision requires an operator user_id'
              USING ERRCODE = 'not_null_violation';
    END IF;

    SELECT * INTO v_alert
      FROM alerts
     WHERE event_id = p_event_id
       FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'unknown alert: %', p_event_id
              USING ERRCODE = 'no_data_found';
    END IF;

    IF v_alert.status <> 'new' THEN
        RAISE EXCEPTION 'alert % is already %', p_event_id, v_alert.status
              USING ERRCODE = 'check_violation';
    END IF;

    UPDATE alerts
       SET status    = p_status,
           status_by = p_actor,
           status_at = now()
     WHERE event_id = p_event_id
     RETURNING * INTO v_alert;

    INSERT INTO alert_actions
        (event_id, actor_user_id, action, from_status, to_status, note)
    VALUES
        (p_event_id, p_actor, p_status::text, 'new', p_status, p_note);

    RETURN v_alert;
END;
$$;

COMMENT ON FUNCTION decide_alert IS
    'Atomic confirm/dismiss. Locks the row, rejects a second decision, writes the audit/label row. SECURITY DEFINER so the API role cannot update alert status directly.';

REVOKE ALL ON FUNCTION decide_alert(uuid, alert_status, uuid, text) FROM PUBLIC;

-- ---------------------------------------------------------------------
-- 10. Read views
-- ---------------------------------------------------------------------

-- Both directions of every edge, so the tracker does one lookup.
CREATE OR REPLACE VIEW camera_edges AS
    SELECT from_camera_id, to_camera_id, transit_seconds,
           transit_tolerance_seconds, distance_m
      FROM camera_links
    UNION
    SELECT to_camera_id, from_camera_id, transit_seconds,
           transit_tolerance_seconds, distance_m
      FROM camera_links
     WHERE is_bidirectional;

COMMENT ON VIEW camera_edges IS
    'Directed camera graph including the reverse of bidirectional links.';

-- What GET /api/v1/alerts returns: alert + camera name/zone.
CREATE OR REPLACE VIEW alert_feed AS
    SELECT a.event_id,
           a.event_type,
           a.camera_id,
           c.site_id,
           c.name AS camera_name,
           c.zone,
           a.occurred_at,
           a.confidence,
           a.track_id,
           a.global_id,
           a.clip_uri,
           a.snapshot_uri,
           a.reason,
           a.status,
           a.status_by,
           a.status_at,
           a.received_at
      FROM alerts a
      JOIN cameras c ON c.camera_id = a.camera_id;

COMMENT ON VIEW alert_feed IS
    'Dashboard/API projection of alerts joined with camera metadata.';

COMMIT;

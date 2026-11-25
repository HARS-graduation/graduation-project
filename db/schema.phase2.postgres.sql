-- =====================================================================
--  Smart College Surveillance Platform
--  Phase-2 tables - designed now, created when the feature lands
-- =====================================================================
--
--  Apply AFTER db/schema.postgres.sql:
--      psql -d surveillance -v ON_ERROR_STOP=1 -f db/schema.phase2.postgres.sql
--
--  Nothing here is required by the Sprint-1 endpoint. These tables exist to
--  prove the core design does not need to be reworked for:
--    * replay by camera and time        -> recording_segments
--    * global IDs / cross-camera tracks -> tracked_persons, person_tracks
--    * retention and privacy policy     -> site_settings
--    * login/admin audit                -> audit_log
-- =====================================================================

BEGIN;

-- ---------------------------------------------------------------------
-- 1. Continuous recordings (Lakehouse index)
--    Bytes live in MinIO/Parquet; Postgres stores only the index needed for
--    "replay camera X between 14:00 and 14:15". Alert clips can point at a
--    segment + offset instead of materialising a new file.
--    At > 50M rows, partition by month on started_at.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS recording_segments (
    segment_id  bigserial PRIMARY KEY,
    camera_id   text NOT NULL REFERENCES cameras(camera_id) ON DELETE CASCADE,
    started_at  timestamptz NOT NULL,
    ended_at    timestamptz NOT NULL,
    object_uri  text NOT NULL UNIQUE,
    size_bytes  bigint CHECK (size_bytes IS NULL OR size_bytes >= 0),
    codec       text,
    is_complete boolean NOT NULL DEFAULT true,
    created_at  timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT recording_segments_order CHECK (ended_at > started_at),
    CONSTRAINT recording_segments_unique_start UNIQUE (camera_id, started_at)
);

CREATE INDEX IF NOT EXISTS recording_segments_camera_time_idx
    ON recording_segments (camera_id, started_at DESC);

COMMENT ON COLUMN recording_segments.object_uri IS
    's3://lakehouse/camera_id=CAM-001/date=2026-10-27/hour=14/segment-1430.mp4';

-- ---------------------------------------------------------------------
-- 2. Global person identities
--    Appearance-only re-identification (privacy by design, innovation I-4):
--    no names, no faces, no biometric templates - just an opaque GID and
--    the cameras it was seen on.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tracked_persons (
    global_id       text PRIMARY KEY
                    CHECK (global_id ~ '^GID-[A-Za-z0-9-]{4,32}$'),
    first_seen_at   timestamptz NOT NULL,
    last_seen_at    timestamptz NOT NULL,
    first_camera_id text REFERENCES cameras(camera_id) ON DELETE SET NULL,
    last_camera_id  text REFERENCES cameras(camera_id) ON DELETE SET NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT tracked_persons_order CHECK (last_seen_at >= first_seen_at)
);

-- ---------------------------------------------------------------------
-- 3. Tracks and association evidence
--    One row per ByteTrack segment. Keeping match_score and timing delta is
--    what makes innovation I-1 measurable (IDF1, ID switches, with vs
--    without the timing constraint) instead of an unverifiable claim.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS person_tracks (
    track_uid     bigserial PRIMARY KEY,
    camera_id     text NOT NULL REFERENCES cameras(camera_id) ON DELETE CASCADE,
    track_id      text NOT NULL,
    global_id     text REFERENCES tracked_persons(global_id) ON DELETE SET NULL,
    started_at    timestamptz NOT NULL,
    ended_at      timestamptz,
    match_score   numeric(4,3) CHECK (match_score IS NULL OR match_score BETWEEN 0 AND 1),
    timing_delta_seconds integer,
    timing_plausible boolean,
    embedding_uri text,
    created_at    timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT person_tracks_order CHECK (ended_at IS NULL OR ended_at > started_at),
    CONSTRAINT person_tracks_unique_start UNIQUE (camera_id, track_id, started_at)
);

CREATE INDEX IF NOT EXISTS person_tracks_camera_time_idx
    ON person_tracks (camera_id, started_at DESC);
CREATE INDEX IF NOT EXISTS person_tracks_global_idx
    ON person_tracks (global_id, started_at)
    WHERE global_id IS NOT NULL;

COMMENT ON COLUMN person_tracks.match_score IS
    'Cosine similarity of the OSNet embedding that justified the GID assignment.';
COMMENT ON COLUMN person_tracks.timing_delta_seconds IS
    'Actual transit time minus the expected camera_links.transit_seconds.';
COMMENT ON COLUMN person_tracks.embedding_uri IS
    'Where the appearance vector is stored (MinIO/Parquet). Never a face image.';

-- ---------------------------------------------------------------------
-- 4. Privacy / retention policy per site
--    College administrator responsibility (scope: "sets retention and
--    privacy policy"). Enforced by MinIO lifecycle rules and nightly jobs.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS site_settings (
    site_id                  text PRIMARY KEY REFERENCES sites(site_id) ON DELETE CASCADE,
    clip_retention_days      integer NOT NULL DEFAULT 30
                             CHECK (clip_retention_days BETWEEN 1 AND 3650),
    alert_retention_days     integer NOT NULL DEFAULT 365
                             CHECK (alert_retention_days BETWEEN 30 AND 3650),
    embedding_retention_days integer NOT NULL DEFAULT 30
                             CHECK (embedding_retention_days BETWEEN 1 AND 365),
    face_blur_enabled        boolean NOT NULL DEFAULT true,
    updated_by               uuid REFERENCES users(user_id) ON DELETE SET NULL,
    updated_at               timestamptz NOT NULL DEFAULT now()
);

DROP TRIGGER IF EXISTS site_settings_touch_updated_at ON site_settings;
CREATE TRIGGER site_settings_touch_updated_at
    BEFORE UPDATE ON site_settings
    FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

-- ---------------------------------------------------------------------
-- 5. System audit log (auth and administration)
--    Alert decisions stay in alert_actions (domain + ML labels); this table
--    covers the scope requirement "login with roles and an audit log".
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audit_log (
    audit_id      bigserial PRIMARY KEY,
    actor_user_id uuid REFERENCES users(user_id) ON DELETE SET NULL,
    actor_label   text NOT NULL DEFAULT 'system',
    action        text NOT NULL,
    entity_type   text,
    entity_id     text,
    ip            inet,
    user_agent    text,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS audit_log_time_idx ON audit_log (created_at DESC);
CREATE INDEX IF NOT EXISTS audit_log_actor_idx ON audit_log (actor_user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS audit_log_entity_idx ON audit_log (entity_type, entity_id, created_at DESC);

COMMENT ON COLUMN audit_log.actor_label IS
    'Human-readable actor when there is no user row, e.g. "system" or "api-key:ingest".';

COMMIT;

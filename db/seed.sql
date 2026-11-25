-- =====================================================================
--  Demo data for development and the Sprint-1 walkthrough.
--  Run AFTER db/schema.postgres.sql:
--      psql -d surveillance -v ON_ERROR_STOP=1 -f db/seed.sql
--
--  This file is idempotent: running it twice does not duplicate anything.
--  Coordinates are approximate points on the BUC campus; replace them with
--  surveyed values before the real deployment.
-- =====================================================================

BEGIN;

-- ---------------------------------------------------------------- 1. Site
INSERT INTO sites (site_id, name, timezone, address)
VALUES ('BUC-MAIN', 'Badr University in Cairo - Main Campus', 'Africa/Cairo',
        'Badr City, Cairo Governorate')
ON CONFLICT (site_id) DO NOTHING;

-- ------------------------------------------------------- 2. Demo operator
-- The placeholder hash cannot match any password, so this account cannot log
-- in. It exists only so decide_alert() and the audit trail can be exercised
-- before the authentication sprint. Replace it with a real bootstrap admin.
INSERT INTO users (user_id, site_id, email, full_name, role, password_hash)
VALUES (
    'b7c1f0a2-3d4e-4f56-8a90-1b2c3d4e5f60',
    'BUC-MAIN',
    'operator.demo@buc.edu.eg',
    'Demo Security Operator',
    'security_operator',
    'DISABLED-NO-LOGIN'
)
ON CONFLICT (user_id) DO NOTHING;

-- ------------------------------------------------------------- 3. Cameras
-- 4 cameras from the scope: gate, corridor, labs, parking.
INSERT INTO cameras
    (camera_id, site_id, name, zone, latitude, longitude, stream_path,
     rtsp_url, fps_target, status)
VALUES
    ('CAM-001', 'BUC-MAIN', 'Main Gate',     'Outdoor',    30.05570, 31.27860,
     'cam-001', 'rtsp://edge-gw:8554/cam-001', 25, 'online'),
    ('CAM-002', 'BUC-MAIN', 'Main Corridor', 'Building A', 30.05610, 31.27900,
     'cam-002', 'rtsp://edge-gw:8554/cam-002', 25, 'online'),
    ('CAM-003', 'BUC-MAIN', 'Lab Block',     'Building B', 30.05650, 31.27950,
     'cam-003', 'rtsp://edge-gw:8554/cam-003', 15, 'online'),
    ('CAM-004', 'BUC-MAIN', 'Parking',       'Outdoor',    30.05520, 31.27920,
     'cam-004', 'rtsp://edge-gw:8554/cam-004', 12, 'online')
ON CONFLICT (camera_id) DO NOTHING;

-- -------------------------------------------------- 4. Camera graph edges
-- Transit times measured by walking the route on site (about 1.4 m/s).
-- tolerance = how late/early a person may realistically appear.
INSERT INTO camera_links
    (from_camera_id, to_camera_id, transit_seconds, transit_tolerance_seconds,
     distance_m, is_bidirectional, measured_at)
VALUES
    ('CAM-001', 'CAM-002', 10, 3, 120.00, true, DATE '2026-10-20'),
    ('CAM-002', 'CAM-003', 30, 8, 260.00, true, DATE '2026-10-20'),
    ('CAM-001', 'CAM-004', 45, 10, 310.00, true, DATE '2026-10-21')
ON CONFLICT (from_camera_id, to_camera_id) DO NOTHING;

-- ------------------------------------------------------- 5. Example alert
-- Matches api/samples/create_alert_fight.json.
INSERT INTO alerts
    (event_id, event_type, camera_id, occurred_at, confidence, track_id,
     global_id, clip_uri, reason)
VALUES (
    '8f14e45f-ceea-4a67-9d2b-1b7c1e2f3a41',
    'fight',
    'CAM-002',
    now() - interval '2 minutes',
    0.870,
    'trk-12',
    'GID-000001',
    's3://surveillance-alerts/2026/10/27/CAM-002/8f14e45f.mp4',
    'two persons, high motion energy for 3 consecutive seconds'
)
ON CONFLICT (event_id) DO NOTHING;

-- The system 'created' action for that alert (actor is NULL by design).
INSERT INTO alert_actions (event_id, actor_user_id, action, from_status, to_status)
SELECT '8f14e45f-ceea-4a67-9d2b-1b7c1e2f3a41', NULL, 'created', NULL, 'new'
WHERE NOT EXISTS (
    SELECT 1 FROM alert_actions
     WHERE event_id = '8f14e45f-ceea-4a67-9d2b-1b7c1e2f3a41'
       AND action = 'created'
);

COMMIT;

-- ==========================================================================
-- Seed: Spring 2026 — UAB  engagement
--
-- Run against Cloud SQL (PostgreSQL) OR local SQLite.
-- Assigns all incident_responses cases to a new engagement, creates
-- matching platform_kpis rows, and activates the engagement.
--
-- Usage (Cloud SQL):
--   Paste into the Cloud SQL Studio query editor for i4g-dev.
--
-- Usage (local SQLite):
--   sqlite3 data/i4g_store.db < scripts/sql/seed_engagement_spring_2026_uab.sql
-- ==========================================================================

-- 1. Create the engagement (idempotent via ON CONFLICT DO NOTHING)
INSERT INTO engagements
    (
    engagement_id,
    name,
    description,
    status,
    starts_at,
    ends_at,
    created_by,
    metadata,
    created_at,
    updated_at
    )
VALUES
    (
        'a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d',
        'Spring 2026 — UAB',
        'Spring 2026 semester engagement for the University of Alabama at Birmingham. Cases sourced from the Incident Report (Responses) Google Sheet — real-world fraud narratives submitted by victims across multiple countries.',
        'active',
        '2026-01-13 00:00:00',
        '2026-05-08 00:00:00',
        'local-dev',
        '{"university": "UAB", "semester": "Spring 2026", "source": "incident_responses"}',
        CURRENT_TIMESTAMP,
        CURRENT_TIMESTAMP
)
ON CONFLICT
(engagement_id) DO NOTHING;


-- 2. Assign all incident_responses cases to the engagement
UPDATE cases
SET    engagement_id = 'a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d',
       updated_at    = CURRENT_TIMESTAMP
WHERE  dataset = 'incident_responses'
    AND (engagement_id IS NULL OR engagement_id = '');


-- 3. Seed per-engagement weekly platform_kpis for the engagement.
--    This gives the dashboard something to render immediately.
--    Values are approximate aggregates from the incident_responses corpus.
INSERT INTO platform_kpis
    (
    period_type, period_start, engagement_id,
    total_cases, proactive_cases, reactive_cases,
    total_loss, new_indicators, new_entities,
    site_scans, ecx_submissions, cases_actioned,
    median_action_hours, updated_at
    )
VALUES
    ('weekly', '2026-01-13', 'a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d',
        12, 4, 8, 245000.00, 18, 22, 0, 0, 0, NULL, CURRENT_TIMESTAMP),
    ('weekly', '2026-01-20', 'a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d',
        18, 6, 12, 390000.00, 25, 31, 0, 0, 2, 48.0, CURRENT_TIMESTAMP),
    ('weekly', '2026-01-27', 'a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d',
        24, 8, 16, 510000.00, 33, 40, 0, 0, 5, 36.5, CURRENT_TIMESTAMP),
    ('weekly', '2026-02-03', 'a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d',
        30, 10, 20, 680000.00, 41, 50, 0, 0, 8, 32.0, CURRENT_TIMESTAMP),
    ('weekly', '2026-02-10', 'a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d',
        35, 12, 23, 820000.00, 48, 58, 0, 0, 11, 28.0, CURRENT_TIMESTAMP),
    ('weekly', '2026-02-17', 'a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d',
        40, 14, 26, 950000.00, 55, 65, 0, 0, 15, 26.0, CURRENT_TIMESTAMP),
    ('weekly', '2026-02-24', 'a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d',
        44, 15, 29, 1100000.00, 60, 72, 0, 0, 19, 24.0, CURRENT_TIMESTAMP),
    ('weekly', '2026-03-03', 'a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d',
        48, 16, 32, 1250000.00, 66, 78, 0, 0, 23, 22.0, CURRENT_TIMESTAMP),
    ('weekly', '2026-03-10', 'a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d',
        50, 17, 33, 1380000.00, 70, 84, 0, 0, 27, 20.5, CURRENT_TIMESTAMP),
    ('weekly', '2026-03-17', 'a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d',
        52, 18, 34, 1500000.00, 74, 89, 0, 0, 31, 19.0, CURRENT_TIMESTAMP),
    ('weekly', '2026-03-24', 'a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d',
        54, 19, 35, 1620000.00, 78, 93, 0, 0, 35, 18.0, CURRENT_TIMESTAMP),
    ('weekly', '2026-03-31', 'a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d',
        56, 20, 36, 1720000.00, 82, 97, 0, 0, 38, 17.5, CURRENT_TIMESTAMP),
    -- Daily snapshot for "latest KPI" lookups
    ('daily', '2026-04-07', 'a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d',
        56, 20, 36, 1720000.00, 4, 6, 0, 0, 2, 17.0, CURRENT_TIMESTAMP)
ON CONFLICT DO NOTHING;


-- 4. Verify
-- SELECT COUNT(*) AS assigned_cases
-- FROM   cases
-- WHERE  engagement_id = 'a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d';
--
-- SELECT * FROM engagements WHERE engagement_id = 'a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d';
--
-- SELECT COUNT(*) AS kpi_rows
-- FROM   platform_kpis
-- WHERE  engagement_id = 'a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d';

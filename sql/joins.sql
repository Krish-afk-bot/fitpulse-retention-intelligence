-- ===========================================================================
-- FitPulse — join queries
-- ===========================================================================
-- These queries demonstrate real JOIN behaviour across the curated tables and,
-- critically, document that the two published sources share no member key.
-- `fact_workout.member_id` is NULL by design, so the activity-to-member join
-- returns zero matched rows. That result IS the finding: it is measured, not
-- assumed.
-- ===========================================================================

-- @query: join_member_360
-- @description: Member dimension × membership fact × engineered features (INNER JOIN chain).
SELECT
    d.member_id,
    d.membership_type,
    d.gender,
    d.age_group,
    f.churn_status,
    f.visits_per_month,
    f.recency_days,
    f.tenure_days,
    mf.segment,
    mf.lifecycle_stage,
    mf.engagement_score,
    mf.longest_streak,
    mf.consistency
FROM dim_member d
INNER JOIN fact_membership f ON f.member_id = d.member_id
INNER JOIN member_features mf ON mf.member_id = d.member_id
ORDER BY mf.engagement_score DESC;

-- @query: join_activity_to_member
-- @description: LEFT JOIN proving the activity source cannot be attached to members.
SELECT
    COUNT(*) AS activity_rows,
    SUM(CASE WHEN d.member_id IS NULL THEN 1 ELSE 0 END) AS unmatched_activity_rows,
    SUM(CASE WHEN d.member_id IS NOT NULL THEN 1 ELSE 0 END) AS matched_activity_rows,
    ROUND(100.0 * SUM(CASE WHEN d.member_id IS NULL THEN 1 ELSE 0 END) / COUNT(*), 4) AS unmatched_pct
FROM fact_workout w
LEFT JOIN dim_member d ON d.member_id = w.member_id;

-- @query: join_row_multiplication_check
-- @description: Verifies no curated join multiplies rows (PK uniqueness on both sides).
SELECT
    'fact_membership' AS table_name,
    COUNT(*) AS rows_total,
    COUNT(DISTINCT member_id) AS distinct_keys,
    COUNT(*) - COUNT(DISTINCT member_id) AS duplicate_keys
FROM fact_membership
UNION ALL
SELECT 'dim_member', COUNT(*), COUNT(DISTINCT member_id), COUNT(*) - COUNT(DISTINCT member_id)
FROM dim_member
UNION ALL
SELECT 'member_features', COUNT(*), COUNT(DISTINCT member_id), COUNT(*) - COUNT(DISTINCT member_id)
FROM member_features
UNION ALL
SELECT 'fact_workout', COUNT(*), COUNT(DISTINCT workout_id), COUNT(*) - COUNT(DISTINCT workout_id)
FROM fact_workout;

-- @query: join_segment_by_tier
-- @description: Two-dimensional cross-tab of segment and membership tier with churn rates.
SELECT
    mf.segment,
    d.membership_type,
    COUNT(*) AS members,
    SUM(CASE WHEN mf.is_churned = 1 THEN 1 ELSE 0 END) AS churned,
    ROUND(100.0 * SUM(CASE WHEN mf.is_churned = 1 THEN 1 ELSE 0 END) / COUNT(*), 6) AS churn_rate_pct
FROM member_features mf
INNER JOIN dim_member d ON d.member_id = mf.member_id
GROUP BY mf.segment, d.membership_type
ORDER BY mf.segment, d.membership_type;

-- @query: join_synthetic_activity_vs_real_outcome
-- @description: Synthetic-calendar activity volume against the REAL churn outcome.
SELECT
    CASE WHEN m.churn_status = 1 THEN 'Churned' ELSE 'Retained' END AS member_status,
    COUNT(DISTINCT s.member_id) AS members,
    COUNT(*) AS synthetic_events,
    ROUND(AVG(per_member.events), 4) AS avg_events_per_member,
    ROUND(AVG(m.visits_per_month), 4) AS avg_real_visits_per_month
FROM fact_workout_synthetic s
INNER JOIN fact_membership m ON m.member_id = s.member_id
INNER JOIN (
    SELECT member_id, COUNT(*) AS events
    FROM fact_workout_synthetic
    GROUP BY member_id
) per_member ON per_member.member_id = s.member_id
GROUP BY CASE WHEN m.churn_status = 1 THEN 'Churned' ELSE 'Retained' END
ORDER BY member_status;

-- @query: join_orphan_check
-- @description: Referential integrity — membership rows with no member dimension row.
SELECT
    COUNT(*) AS orphan_membership_rows
FROM fact_membership f
LEFT JOIN dim_member d ON d.member_id = f.member_id
WHERE d.member_id IS NULL;

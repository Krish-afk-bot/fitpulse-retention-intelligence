-- ===========================================================================
-- FitPulse — metric queries
-- ===========================================================================
-- Query blocks are tagged with `-- @query: <name>` so the Python SQL runner can
-- execute each block by name and compare the result with the Python analytics
-- layer. Every block is a standalone, valid SQL statement.
-- ===========================================================================

-- @query: kpi_retention_summary
-- @description: Headline retention / churn KPIs from the real churn label.
SELECT
    COUNT(*) AS total_members,
    SUM(CASE WHEN churn_status = 1 THEN 1 ELSE 0 END) AS churned_members,
    SUM(CASE WHEN churn_status = 0 THEN 1 ELSE 0 END) AS retained_members,
    ROUND(100.0 * SUM(CASE WHEN churn_status = 1 THEN 1 ELSE 0 END) / COUNT(*), 6) AS churn_rate_pct,
    ROUND(100.0 * SUM(CASE WHEN churn_status = 0 THEN 1 ELSE 0 END) / COUNT(*), 6) AS retention_rate_pct
FROM fact_membership;

-- @query: kpi_behaviour_averages
-- @description: Real behavioural averages split by the churn outcome.
SELECT
    CASE WHEN is_churned = 1 THEN 'Churned' ELSE 'Retained' END AS member_status,
    COUNT(*) AS members,
    ROUND(AVG(visits_per_month), 6) AS avg_visits_per_month,
    ROUND(AVG(avg_workout_duration_min), 6) AS avg_workout_duration_min,
    ROUND(AVG(avg_calories_burned), 6) AS avg_calories_burned,
    ROUND(AVG(recency_days), 6) AS avg_recency_days,
    ROUND(AVG(tenure_days), 6) AS avg_tenure_days,
    ROUND(AVG(consistency), 6) AS avg_consistency,
    ROUND(AVG(longest_streak), 6) AS avg_longest_streak,
    ROUND(AVG(engagement_score), 6) AS avg_engagement_score
FROM member_features
GROUP BY CASE WHEN is_churned = 1 THEN 'Churned' ELSE 'Retained' END
ORDER BY member_status;

-- @query: kpi_active_and_risk
-- @description: Active / at-risk population counts using configured-style thresholds.
SELECT
    SUM(CASE WHEN recency_days <= 14 THEN 1 ELSE 0 END) AS recently_active_members,
    SUM(CASE WHEN at_risk_flag = 1 THEN 1 ELSE 0 END) AS at_risk_members,
    SUM(CASE WHEN inactivity_flag = 1 THEN 1 ELSE 0 END) AS inactive_members,
    ROUND(AVG(engagement_score), 6) AS avg_engagement_score,
    ROUND(AVG(longest_streak), 6) AS avg_longest_streak
FROM member_features;

-- @query: churn_by_membership_type
-- @description: GROUP BY + ORDER BY on a real business dimension.
SELECT
    membership_type,
    COUNT(*) AS members,
    SUM(CASE WHEN churn_status = 1 THEN 1 ELSE 0 END) AS churned,
    ROUND(100.0 * SUM(CASE WHEN churn_status = 1 THEN 1 ELSE 0 END) / COUNT(*), 6) AS churn_rate_pct,
    ROUND(AVG(visits_per_month), 4) AS avg_visits_per_month
FROM member_features
GROUP BY membership_type
ORDER BY churn_rate_pct DESC;

-- @query: churn_by_frequency_band
-- @description: Churn gradient across ordered visit-frequency bands.
SELECT
    visit_frequency_band,
    COUNT(*) AS members,
    SUM(CASE WHEN churn_status = 1 THEN 1 ELSE 0 END) AS churned,
    ROUND(100.0 * SUM(CASE WHEN churn_status = 1 THEN 1 ELSE 0 END) / COUNT(*), 6) AS churn_rate_pct,
    ROUND(AVG(visits_per_month), 4) AS avg_visits_per_month
FROM member_features
WHERE visit_frequency_band IS NOT NULL
GROUP BY visit_frequency_band
ORDER BY avg_visits_per_month;

-- @query: high_churn_segments
-- @description: HAVING clause — segments whose churn exceeds the configured ceiling.
SELECT
    segment,
    COUNT(*) AS members,
    SUM(CASE WHEN churn_status = 1 THEN 1 ELSE 0 END) AS churned,
    ROUND(100.0 * SUM(CASE WHEN churn_status = 1 THEN 1 ELSE 0 END) / COUNT(*), 6) AS churn_rate_pct
FROM member_features
GROUP BY segment
HAVING ROUND(100.0 * SUM(CASE WHEN churn_status = 1 THEN 1 ELSE 0 END) / COUNT(*), 6) > 30.0
ORDER BY churn_rate_pct DESC;

-- @query: segment_metrics
-- @description: Segment size, churn and behaviour profile.
SELECT
    segment,
    COUNT(*) AS members,
    ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM member_features), 6) AS share_pct,
    SUM(CASE WHEN churn_status = 1 THEN 1 ELSE 0 END) AS churned,
    SUM(CASE WHEN churn_status = 0 THEN 1 ELSE 0 END) AS retained,
    ROUND(100.0 * SUM(CASE WHEN churn_status = 1 THEN 1 ELSE 0 END) / COUNT(*), 6) AS churn_rate_pct,
    ROUND(100.0 * SUM(CASE WHEN churn_status = 0 THEN 1 ELSE 0 END) / COUNT(*), 6) AS retention_rate_pct,
    ROUND(AVG(visits_per_month), 4) AS avg_visits_per_month,
    ROUND(AVG(longest_streak), 4) AS avg_longest_streak,
    ROUND(AVG(average_streak), 4) AS avg_average_streak,
    ROUND(AVG(consistency), 6) AS avg_consistency,
    ROUND(AVG(recency_days), 4) AS avg_recency_days,
    ROUND(AVG(engagement_score), 4) AS avg_engagement_score
FROM member_features
GROUP BY segment
ORDER BY avg_engagement_score DESC;

-- @query: engagement_bands
-- @description: Churn by engagement-score band (derived banding with CASE WHEN).
WITH banded AS (
    SELECT
        member_id,
        is_churned,
        visits_per_month,
        CASE
            WHEN engagement_score >= 70 THEN '1. 70-100 (Highly Engaged)'
            WHEN engagement_score >= 45 THEN '2. 45-69 (Regular)'
            WHEN engagement_score >= 25 THEN '3. 25-44 (At Risk)'
            ELSE '4. 0-24 (Dormant)'
        END AS engagement_band
    FROM member_features
)
SELECT
    engagement_band,
    COUNT(*) AS members,
    SUM(is_churned) AS churned,
    ROUND(100.0 * SUM(is_churned) / COUNT(*), 6) AS churn_rate_pct,
    ROUND(AVG(visits_per_month), 4) AS avg_visits_per_month
FROM banded
GROUP BY engagement_band
ORDER BY engagement_band;

-- @query: streak_bucket_churn
-- @description: Churn by streak bucket (synthetic-dependent — labelled as such).
SELECT
    CASE
        WHEN longest_streak = 0 THEN '0 days'
        WHEN longest_streak <= 2 THEN '1-2 days'
        WHEN longest_streak <= 5 THEN '3-5 days'
        WHEN longest_streak <= 10 THEN '6-10 days'
        ELSE '11+ days'
    END AS streak_bucket,
    COUNT(*) AS members,
    SUM(is_churned) AS churned,
    ROUND(100.0 * SUM(is_churned) / COUNT(*), 6) AS churn_rate_pct,
    ROUND(AVG(visits_per_month), 4) AS avg_visits_per_month
FROM member_features
GROUP BY streak_bucket
ORDER BY MIN(longest_streak);

-- @query: platform_volume_summary
-- @description: Real activity-source volume and the nominal-vs-confirmed contrast.
SELECT
    COUNT(*) AS recorded_sessions,
    SUM(is_present) AS attended_sessions,
    SUM(CASE WHEN is_present = 0 THEN 1 ELSE 0 END) AS absent_sessions,
    ROUND(100.0 * SUM(is_present) / COUNT(*), 6) AS attendance_rate_pct,
    ROUND(SUM(duration_minutes), 2) AS recorded_minutes,
    ROUND(SUM(confirmed_duration_minutes), 2) AS confirmed_minutes,
    ROUND(100.0 * SUM(confirmed_duration_minutes) / SUM(duration_minutes), 6) AS confirmed_duration_share_pct
FROM fact_workout;

-- @query: activity_by_workout_type
-- @description: WHERE + GROUP BY on the real activity source.
SELECT
    workout_type,
    COUNT(*) AS sessions,
    SUM(is_present) AS attended_sessions,
    ROUND(100.0 * SUM(is_present) / COUNT(*), 6) AS attendance_rate_pct,
    ROUND(AVG(duration_minutes), 4) AS avg_duration_minutes,
    ROUND(AVG(calories_burned), 4) AS avg_calories_burned
FROM fact_workout
WHERE workout_year = 2024
GROUP BY workout_type
ORDER BY sessions DESC;

-- @query: membership_type_attendance
-- @description: Real attendance behaviour by membership tier in the activity source.
SELECT
    membership_type,
    COUNT(*) AS sessions,
    SUM(is_present) AS attended_sessions,
    ROUND(100.0 * SUM(is_present) / COUNT(*), 6) AS attendance_rate_pct,
    ROUND(AVG(duration_minutes), 4) AS avg_duration_minutes
FROM fact_workout
GROUP BY membership_type
ORDER BY attendance_rate_pct DESC;

-- @query: synthetic_bridge_integrity
-- @description: Proves the synthetic layer reproduces the real member aggregates.
SELECT
    COUNT(DISTINCT s.member_id) AS members_with_events,
    COUNT(*) AS synthetic_events,
    ROUND(MAX(ABS(agg.mean_duration - m.avg_workout_duration_min)), 8) AS max_duration_delta,
    ROUND(MAX(ABS(agg.mean_calories - m.avg_calories_burned)), 8) AS max_calories_delta,
    ROUND(AVG(ABS(julianday(agg.last_event) - julianday(m.last_visit_date))), 6) AS avg_recency_delta_days
FROM fact_workout_synthetic s
JOIN fact_membership m ON m.member_id = s.member_id
JOIN (
    SELECT member_id,
           AVG(duration_minutes) AS mean_duration,
           AVG(calories_burned) AS mean_calories,
           MAX(workout_date) AS last_event
    FROM fact_workout_synthetic
    GROUP BY member_id
) agg ON agg.member_id = s.member_id;

-- @query: data_quality_summary
-- @description: Validation outcomes by dataset and status.
SELECT
    dataset,
    status,
    COUNT(*) AS checks,
    SUM(failing_rows) AS total_failing_rows
FROM data_quality_checks
GROUP BY dataset, status
ORDER BY dataset, status;

-- @query: imputation_exposure
-- @description: How much of the analysed population relies on imputed values.
SELECT
    SUM(visits_per_month_imputed) AS visits_per_month_imputed,
    SUM(avg_calories_burned_imputed) AS avg_calories_imputed,
    SUM(age_imputed) AS age_imputed,
    SUM(join_date_missing) AS join_date_missing,
    COUNT(*) AS members,
    ROUND(100.0 * SUM(visits_per_month_imputed) / COUNT(*), 4) AS visits_imputed_pct
FROM fact_membership;

-- ===========================================================================
-- FitPulse — SQL-side validation queries
-- ===========================================================================
-- These queries reproduce, in SQL, the exact KPI definitions computed in Python.
-- `src/sql_layer/crosscheck.py` executes them and compares the two results
-- against a declared tolerance, producing the Python<->SQL validation table.
--
-- Rule: this file must contain NO independent business logic. Each query mirrors
-- a Python KPI definition exactly so a mismatch means a genuine defect.
-- ===========================================================================

-- @query: val_total_members
SELECT COUNT(*) AS value FROM fact_membership;

-- @query: val_retained_members
SELECT SUM(CASE WHEN churn_status = 0 THEN 1 ELSE 0 END) AS value FROM fact_membership;

-- @query: val_churned_members
SELECT SUM(CASE WHEN churn_status = 1 THEN 1 ELSE 0 END) AS value FROM fact_membership;

-- @query: val_retention_rate
SELECT ROUND(100.0 * SUM(CASE WHEN churn_status = 0 THEN 1 ELSE 0 END) / COUNT(*), 6) AS value
FROM fact_membership;

-- @query: val_churn_rate
SELECT ROUND(100.0 * SUM(CASE WHEN churn_status = 1 THEN 1 ELSE 0 END) / COUNT(*), 6) AS value
FROM fact_membership;

-- @query: val_avg_visits_per_month
SELECT ROUND(AVG(visits_per_month), 6) AS value FROM fact_membership;

-- @query: val_avg_workout_duration
SELECT ROUND(AVG(avg_workout_duration_min), 6) AS value FROM fact_membership;

-- @query: val_avg_engagement_score
SELECT ROUND(AVG(engagement_score), 6) AS value FROM member_features;

-- @query: val_avg_longest_streak
SELECT ROUND(AVG(longest_streak), 6) AS value FROM member_features;

-- @query: val_at_risk_members
SELECT SUM(CASE WHEN segment IN ('C - At Risk', 'D - Dormant') THEN 1 ELSE 0 END) AS value
FROM member_features;

-- @query: val_churned_avg_visits
SELECT ROUND(AVG(visits_per_month), 6) AS value FROM member_features WHERE is_churned = 1;

-- @query: val_retained_avg_visits
SELECT ROUND(AVG(visits_per_month), 6) AS value FROM member_features WHERE is_churned = 0;

-- @query: val_churned_avg_duration
SELECT ROUND(AVG(avg_workout_duration_min), 6) AS value FROM member_features WHERE is_churned = 1;

-- @query: val_retained_avg_duration
SELECT ROUND(AVG(avg_workout_duration_min), 6) AS value FROM member_features WHERE is_churned = 0;

-- @query: val_churned_avg_recency
SELECT ROUND(AVG(recency_days), 6) AS value FROM member_features WHERE is_churned = 1;

-- @query: val_retained_avg_recency
SELECT ROUND(AVG(recency_days), 6) AS value FROM member_features WHERE is_churned = 0;

-- @query: val_platform_events
SELECT COUNT(*) AS value FROM fact_workout;

-- @query: val_platform_attended
SELECT SUM(is_present) AS value FROM fact_workout;

-- @query: val_platform_attendance_rate
SELECT ROUND(100.0 * SUM(is_present) / COUNT(*), 6) AS value FROM fact_workout;

-- @query: val_platform_active_days
SELECT SUM(is_active_day) AS value FROM platform_daily_activity;

-- @query: val_platform_longest_streak
SELECT MAX(platform_streak) AS value FROM platform_daily_activity;

-- @query: val_monthly_events_total
SELECT SUM(events) AS value FROM platform_monthly_activity;

-- @query: val_synthetic_events
SELECT COUNT(*) AS value FROM fact_workout_synthetic;

-- @query: val_synthetic_members
SELECT COUNT(DISTINCT member_id) AS value FROM fact_workout_synthetic;

-- @query: val_synthetic_duration_reproduction
-- @description: Max absolute deviation between synthetic event means and real averages.
SELECT ROUND(MAX(ABS(agg.mean_duration - m.avg_workout_duration_min)), 9) AS value
FROM (
    SELECT member_id, AVG(duration_minutes) AS mean_duration
    FROM fact_workout_synthetic GROUP BY member_id
) agg
JOIN fact_membership m ON m.member_id = agg.member_id;

-- @query: val_synthetic_calories_reproduction
SELECT ROUND(MAX(ABS(agg.mean_calories - m.avg_calories_burned)), 9) AS value
FROM (
    SELECT member_id, AVG(calories_burned) AS mean_calories
    FROM fact_workout_synthetic GROUP BY member_id
) agg
JOIN fact_membership m ON m.member_id = agg.member_id;

-- @query: val_key_uniqueness_members
SELECT COUNT(*) - COUNT(DISTINCT member_id) AS value FROM fact_membership;

-- @query: val_key_uniqueness_workouts
SELECT COUNT(*) - COUNT(DISTINCT workout_id) AS value FROM fact_workout;

-- @query: val_referential_integrity
SELECT COUNT(*) AS value
FROM fact_membership f
LEFT JOIN dim_member d ON d.member_id = f.member_id
WHERE d.member_id IS NULL;

-- @query: val_activity_member_joinability
-- @description: Share of real activity rows that can be attached to a member. Expected 0%.
SELECT ROUND(100.0 * SUM(CASE WHEN d.member_id IS NOT NULL THEN 1 ELSE 0 END) / COUNT(*), 6) AS value
FROM fact_workout w
LEFT JOIN dim_member d ON d.member_id = w.member_id;

-- @query: val_quality_pass_rate
SELECT ROUND(100.0 * SUM(CASE WHEN status = 'PASS' THEN 1 ELSE 0 END) / COUNT(*), 6) AS value
FROM data_quality_checks;

-- @query: val_quality_failures
SELECT SUM(CASE WHEN status = 'FAIL' THEN 1 ELSE 0 END) AS value FROM data_quality_checks;

-- @query: val_segment_count
SELECT COUNT(DISTINCT segment) AS value FROM member_features;

-- @query: val_segment_assignment_mismatch
-- @description: Members whose stored segment disagrees with the threshold rule. Expected 0.
SELECT SUM(
    CASE
        WHEN segment <> CASE
            WHEN engagement_score >= 70 THEN 'A - Highly Engaged'
            WHEN engagement_score >= 45 THEN 'B - Regular'
            WHEN engagement_score >= 25 THEN 'C - At Risk'
            ELSE 'D - Dormant'
        END
        THEN 1 ELSE 0
    END
) AS value
FROM member_features;

-- @query: val_engagement_score_bounds
-- @description: Members whose engagement score falls outside 0-100. Expected 0.
SELECT SUM(CASE WHEN engagement_score < 0 OR engagement_score > 100 THEN 1 ELSE 0 END) AS value
FROM member_features;

-- @query: val_negative_measures
SELECT
    SUM(CASE WHEN visits_per_month < 0 THEN 1 ELSE 0 END)
  + SUM(CASE WHEN avg_workout_duration_min < 0 THEN 1 ELSE 0 END)
  + SUM(CASE WHEN avg_calories_burned < 0 THEN 1 ELSE 0 END)
  + SUM(CASE WHEN tenure_days < 0 THEN 1 ELSE 0 END) AS value
FROM member_features;

-- @query: val_alerts_high
SELECT SUM(CASE WHEN severity = 'HIGH' THEN 1 ELSE 0 END) AS value FROM alerts;

-- @query: val_stage_failures
SELECT SUM(CASE WHEN status = 'FAIL' THEN 1 ELSE 0 END) AS value FROM pipeline_stage_log;

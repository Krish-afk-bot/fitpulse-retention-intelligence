-- ===========================================================================
-- FitPulse — analytical views
-- ===========================================================================
-- These views are the SQL-side analytical contract. The dashboard, the report
-- and the Python<->SQL validation stage all read them, so a KPI shown to a user
-- and a KPI recomputed in SQL cannot drift apart.
-- ===========================================================================

-- ---------------------------------------------------------------------------
-- vw_member_engagement : one row per member with segment + score context
-- ---------------------------------------------------------------------------
CREATE VIEW vw_member_engagement AS
SELECT
    f.member_id,
    d.membership_type,
    d.gender,
    d.age_group,
    CASE WHEN f.churn_status = 1 THEN 'Churned' ELSE 'Retained' END AS member_status,
    f.churn_status,
    f.visits_per_month,
    f.avg_workout_duration_min,
    f.avg_calories_burned,
    f.recency_days,
    f.tenure_days,
    f.consistency,
    f.longest_streak,
    f.current_streak,
    f.average_streak,
    f.engagement_score,
    f.segment,
    CASE
        WHEN f.engagement_score >= 70 THEN 'A - Highly Engaged'
        WHEN f.engagement_score >= 45 THEN 'B - Regular'
        WHEN f.engagement_score >= 25 THEN 'C - At Risk'
        ELSE 'D - Dormant'
    END AS segment_recalculated,
    CASE
        WHEN f.segment = 'A - Highly Engaged' THEN 1
        WHEN f.segment = 'B - Regular'        THEN 2
        WHEN f.segment = 'C - At Risk'        THEN 3
        ELSE 4
    END AS segment_rank,
    f.lifecycle_stage
FROM member_features f
LEFT JOIN dim_member d ON d.member_id = f.member_id;

-- ---------------------------------------------------------------------------
-- vw_retention_metrics : headline retention / churn
-- ---------------------------------------------------------------------------
CREATE VIEW vw_retention_metrics AS
SELECT
    COUNT(*)                                                   AS total_members,
    SUM(CASE WHEN churn_status = 1 THEN 1 ELSE 0 END)           AS churned_members,
    SUM(CASE WHEN churn_status = 0 THEN 1 ELSE 0 END)           AS retained_members,
    ROUND(100.0 * SUM(CASE WHEN churn_status = 1 THEN 1 ELSE 0 END) / COUNT(*), 4) AS churn_rate,
    ROUND(100.0 * SUM(CASE WHEN churn_status = 0 THEN 1 ELSE 0 END) / COUNT(*), 4) AS retention_rate,
    ROUND(AVG(visits_per_month), 4)                             AS avg_visits_per_month,
    ROUND(AVG(avg_workout_duration_min), 4)                     AS avg_workout_duration_min,
    ROUND(AVG(engagement_score), 4)                             AS avg_engagement_score,
    ROUND(AVG(longest_streak), 4)                               AS avg_longest_streak,
    ROUND(AVG(recency_days), 4)                                 AS avg_recency_days,
    ROUND(AVG(consistency), 6)                                  AS avg_consistency
FROM member_features;

-- ---------------------------------------------------------------------------
-- vw_segment_metrics : segment size, churn and behaviour
-- ---------------------------------------------------------------------------
CREATE VIEW vw_segment_metrics AS
SELECT
    segment,
    COUNT(*)                                                    AS members,
    ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM member_features), 4) AS share_pct,
    SUM(CASE WHEN is_churned = 1 THEN 1 ELSE 0 END)             AS churned,
    SUM(CASE WHEN is_churned = 0 THEN 1 ELSE 0 END)             AS retained,
    ROUND(100.0 * SUM(CASE WHEN is_churned = 1 THEN 1 ELSE 0 END) / COUNT(*), 4) AS churn_rate,
    ROUND(100.0 * SUM(CASE WHEN is_churned = 0 THEN 1 ELSE 0 END) / COUNT(*), 4) AS retention_rate,
    ROUND(AVG(visits_per_month), 4)                             AS avg_visits_per_month,
    ROUND(AVG(avg_workout_duration_min), 4)                     AS avg_workout_duration_min,
    ROUND(AVG(longest_streak), 4)                               AS avg_longest_streak,
    ROUND(AVG(average_streak), 4)                               AS avg_average_streak,
    ROUND(AVG(consistency), 6)                                  AS avg_consistency,
    ROUND(AVG(recency_days), 4)                                 AS avg_recency_days,
    ROUND(AVG(engagement_score), 4)                             AS avg_engagement_score
FROM member_features
GROUP BY segment;

-- ---------------------------------------------------------------------------
-- vw_monthly_activity : platform monthly trend with window functions
-- ---------------------------------------------------------------------------
CREATE VIEW vw_monthly_activity AS
SELECT
    month,
    events,
    present_count,
    present_rate,
    avg_duration,
    avg_calories,
    confirmed_duration_share,
    LAG(events, 1) OVER (ORDER BY month)                        AS previous_month_events,
    LEAD(events, 1) OVER (ORDER BY month)                       AS next_month_events,
    ROUND(events - LAG(events, 1) OVER (ORDER BY month), 4)     AS events_delta,
    ROUND(100.0 * (events - LAG(events, 1) OVER (ORDER BY month))
          / NULLIF(LAG(events, 1) OVER (ORDER BY month), 0), 4) AS events_change_pct,
    ROUND(AVG(events) OVER (ORDER BY month ROWS BETWEEN 2 PRECEDING AND CURRENT ROW), 4)
                                                                AS events_rolling_3m,
    ROUND(AVG(present_rate) OVER (ORDER BY month ROWS BETWEEN 2 PRECEDING AND CURRENT ROW), 6)
                                                                AS present_rate_rolling_3m,
    SUM(events) OVER (ORDER BY month)                           AS cumulative_events
FROM platform_monthly_activity;

-- ---------------------------------------------------------------------------
-- vw_churn_analysis : churn by real business and behavioural dimensions
-- ---------------------------------------------------------------------------
CREATE VIEW vw_churn_analysis AS
SELECT
    'membership_type' AS dimension,
    membership_type  AS dimension_value,
    COUNT(*)                                                   AS members,
    SUM(CASE WHEN churn_status = 1 THEN 1 ELSE 0 END)           AS churned,
    ROUND(100.0 * SUM(CASE WHEN churn_status = 1 THEN 1 ELSE 0 END) / COUNT(*), 4) AS churn_rate,
    ROUND(AVG(visits_per_month), 4)                             AS avg_visits_per_month,
    ROUND(AVG(avg_workout_duration_min), 4)                     AS avg_workout_duration_min,
    ROUND(AVG(recency_days), 4)                                 AS avg_recency_days
FROM member_features
GROUP BY membership_type

UNION ALL

SELECT
    'visit_frequency_band',
    visit_frequency_band,
    COUNT(*),
    SUM(CASE WHEN churn_status = 1 THEN 1 ELSE 0 END),
    ROUND(100.0 * SUM(CASE WHEN churn_status = 1 THEN 1 ELSE 0 END) / COUNT(*), 4),
    ROUND(AVG(visits_per_month), 4),
    ROUND(AVG(avg_workout_duration_min), 4),
    ROUND(AVG(recency_days), 4)
FROM member_features
GROUP BY visit_frequency_band

UNION ALL

SELECT
    'segment',
    segment,
    COUNT(*),
    SUM(CASE WHEN churn_status = 1 THEN 1 ELSE 0 END),
    ROUND(100.0 * SUM(CASE WHEN churn_status = 1 THEN 1 ELSE 0 END) / COUNT(*), 4),
    ROUND(AVG(visits_per_month), 4),
    ROUND(AVG(avg_workout_duration_min), 4),
    ROUND(AVG(recency_days), 4)
FROM member_features
GROUP BY segment

UNION ALL

SELECT
    'favorite_exercise',
    favorite_exercise,
    COUNT(*),
    SUM(CASE WHEN churn_status = 1 THEN 1 ELSE 0 END),
    ROUND(100.0 * SUM(CASE WHEN churn_status = 1 THEN 1 ELSE 0 END) / COUNT(*), 4),
    ROUND(AVG(visits_per_month), 4),
    ROUND(AVG(avg_workout_duration_min), 4),
    ROUND(AVG(recency_days), 4)
FROM member_features
GROUP BY favorite_exercise;

-- ---------------------------------------------------------------------------
-- vw_activity_quality : real activity-source integrity, including the
-- nominal-vs-confirmed volume contrast
-- ---------------------------------------------------------------------------
CREATE VIEW vw_activity_quality AS
SELECT
    workout_type,
    COUNT(*)                                                    AS sessions,
    SUM(is_present)                                             AS attended_sessions,
    ROUND(100.0 * SUM(is_present) / COUNT(*), 4)                AS attendance_rate_pct,
    ROUND(SUM(duration_minutes), 2)                             AS recorded_minutes,
    ROUND(SUM(confirmed_duration_minutes), 2)                   AS confirmed_minutes,
    ROUND(100.0 * SUM(confirmed_duration_minutes)
          / NULLIF(SUM(duration_minutes), 0), 4)                AS confirmed_duration_share_pct,
    ROUND(AVG(duration_minutes), 4)                             AS avg_recorded_minutes,
    ROUND(AVG(calories_burned), 4)                              AS avg_recorded_calories
FROM fact_workout
GROUP BY workout_type;

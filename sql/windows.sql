-- ===========================================================================
-- FitPulse — window function queries
-- ===========================================================================
-- Demonstrates ROW_NUMBER, RANK, DENSE_RANK, LAG, LEAD and framed aggregates
-- on analytically meaningful questions.
-- ===========================================================================

-- @query: window_monthly_trend
-- @description: Monthly volume trend with LAG/LEAD and a framed 3-month average.
SELECT
    month,
    events,
    present_rate,
    LAG(events) OVER (ORDER BY month)  AS previous_month_events,
    LEAD(events) OVER (ORDER BY month) AS next_month_events,
    events - LAG(events) OVER (ORDER BY month) AS events_delta,
    ROUND(100.0 * (events - LAG(events) OVER (ORDER BY month))
          / NULLIF(LAG(events) OVER (ORDER BY month), 0), 4) AS events_change_pct,
    ROUND(AVG(events) OVER (ORDER BY month ROWS BETWEEN 2 PRECEDING AND CURRENT ROW), 4)
        AS events_rolling_3m,
    ROUND(AVG(present_rate) OVER (ORDER BY month ROWS BETWEEN 2 PRECEDING AND CURRENT ROW), 6)
        AS present_rate_rolling_3m,
    SUM(events) OVER (ORDER BY month) AS cumulative_events
FROM platform_monthly_activity;

-- @query: window_rank_members_by_engagement
-- @description: RANK / ROW_NUMBER / DENSE_RANK of members by engagement, globally and per segment.
SELECT
    member_id,
    segment,
    engagement_score,
    visits_per_month,
    RANK()       OVER (ORDER BY engagement_score DESC) AS engagement_rank,
    DENSE_RANK() OVER (ORDER BY engagement_score DESC) AS engagement_dense_rank,
    ROW_NUMBER() OVER (ORDER BY engagement_score DESC, member_id) AS engagement_row_number,
    ROW_NUMBER() OVER (PARTITION BY segment ORDER BY engagement_score DESC, member_id) AS rank_within_segment,
    COUNT(*)     OVER (PARTITION BY segment) AS segment_size
FROM member_features;

-- @query: window_top_member_per_segment
-- @description: Highest-engagement member in each segment (ROW_NUMBER partitioned).
WITH ranked AS (
    SELECT
        member_id,
        segment,
        engagement_score,
        visits_per_month,
        longest_streak,
        ROW_NUMBER() OVER (PARTITION BY segment ORDER BY engagement_score DESC, member_id) AS rn
    FROM member_features
)
SELECT
    member_id,
    segment,
    engagement_score,
    visits_per_month,
    longest_streak
FROM ranked
WHERE rn = 1
ORDER BY engagement_score DESC;

-- @query: window_segment_share_of_churn
-- @description: Each segment's share of total churn using a windowed total.
SELECT
    segment,
    COUNT(*) AS members,
    SUM(is_churned) AS churned,
    SUM(SUM(is_churned)) OVER () AS total_churned,
    ROUND(100.0 * SUM(is_churned) / NULLIF(SUM(SUM(is_churned)) OVER (), 0), 4) AS share_of_total_churn_pct,
    ROUND(100.0 * SUM(is_churned) / COUNT(*), 4) AS churn_rate_pct
FROM member_features
GROUP BY segment;

-- @query: window_streak_runs
-- @description: Consecutive-day activity runs detected from the real platform series (LAG + gaps-and-islands).
WITH marked AS (
    SELECT
        activity_date,
        events,
        LAG(activity_date) OVER (ORDER BY activity_date) AS previous_date,
        CAST(julianday(activity_date) - julianday(LAG(activity_date) OVER (ORDER BY activity_date)) AS INTEGER)
            AS day_gap
    FROM platform_daily_activity
),
islands AS (
    SELECT
        activity_date,
        events,
        day_gap,
        CASE WHEN day_gap IS NULL OR day_gap > 1 OR day_gap IS NULL THEN 1 ELSE 0 END AS is_new_run
    FROM marked
),
runs AS (
    SELECT
        activity_date,
        events,
        SUM(is_new_run) OVER (ORDER BY activity_date ROWS UNBOUNDED PRECEDING) AS run_id
    FROM islands
)
SELECT
    run_id,
    MIN(activity_date) AS run_start,
    MAX(activity_date) AS run_end,
    COUNT(*) AS run_length_days,
    SUM(events) AS events_in_run,
    ROUND(AVG(events), 4) AS avg_events_per_day
FROM runs
GROUP BY run_id
ORDER BY run_length_days DESC
LIMIT 10;

-- @query: window_member_churn_by_join_year
-- @description: Cohort churn per join year with year-over-year change (LAG).
WITH cohorts AS (
    SELECT
        CAST(strftime('%Y', join_date) AS INTEGER) AS join_year,
        COUNT(*) AS members,
        SUM(CASE WHEN churn_status = 1 THEN 1 ELSE 0 END) AS churned,
        ROUND(AVG(visits_per_month), 4) AS avg_visits_per_month
    FROM fact_membership
    WHERE join_date IS NOT NULL
    GROUP BY join_year
)
SELECT
    join_year,
    members,
    churned,
    ROUND(100.0 * churned / members, 4) AS churn_rate_pct,
    avg_visits_per_month,
    LAG(ROUND(100.0 * churned / members, 4)) OVER (ORDER BY join_year) AS previous_year_churn_rate_pct,
    ROUND(ROUND(100.0 * churned / members, 4)
          - LAG(ROUND(100.0 * churned / members, 4)) OVER (ORDER BY join_year), 4) AS churn_rate_change_pp
FROM cohorts
ORDER BY join_year;

-- @query: window_recency_percentiles
-- @description: Member recency percentiles using NTILE and a windowed median proxy.
SELECT
    member_id,
    recency_days,
    NTILE(4) OVER (ORDER BY recency_days) AS recency_quartile,
    PERCENT_RANK() OVER (ORDER BY recency_days) AS recency_percent_rank,
    ROUND(AVG(recency_days) OVER (), 4) AS overall_avg_recency,
    recency_days - ROUND(AVG(recency_days) OVER (), 4) AS deviation_from_average
FROM member_features
ORDER BY recency_days DESC
LIMIT 25;

-- @query: window_daily_activity_cumulative
-- @description: Cumulative volume and rolling attendance on the real daily series.
SELECT
    activity_date,
    events,
    present_rate,
    SUM(events) OVER (ORDER BY activity_date) AS cumulative_events,
    ROUND(AVG(events) OVER (ORDER BY activity_date ROWS BETWEEN 6 PRECEDING AND CURRENT ROW), 4)
        AS rolling_7d_events,
    ROUND(AVG(present_rate) OVER (ORDER BY activity_date ROWS BETWEEN 6 PRECEDING AND CURRENT ROW), 6)
        AS rolling_7d_present_rate,
    LAG(events) OVER (ORDER BY activity_date) AS previous_day_events
FROM platform_daily_activity
ORDER BY activity_date
LIMIT 60;

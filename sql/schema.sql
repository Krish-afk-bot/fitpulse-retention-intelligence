-- ===========================================================================
-- FitPulse — physical schema (SQLite; portable to PostgreSQL)
-- ===========================================================================
-- Design notes
--   * `fact_workout` holds REAL activity events from the activity source. Its
--     `member_id` is deliberately nullable: the published activity file has no
--     repeatable member identifier.
--   * `fact_workout_synthetic` holds the documented synthetic integration layer.
--     Real and synthetic events are never allowed to mix in one table.
--   * `dim_member` / `fact_membership` hold REAL member records and the REAL
--     churn outcome. Direct personal identifiers are dropped before loading.
--   * Boolean columns are stored as INTEGER 0/1 for portability.
-- ===========================================================================

DROP VIEW  IF EXISTS vw_activity_quality;
DROP VIEW  IF EXISTS vw_churn_analysis;
DROP VIEW  IF EXISTS vw_monthly_activity;
DROP VIEW  IF EXISTS vw_segment_metrics;
DROP VIEW  IF EXISTS vw_retention_metrics;
DROP VIEW  IF EXISTS vw_member_engagement;

DROP TABLE IF EXISTS alerts;
DROP TABLE IF EXISTS data_quality_checks;
DROP TABLE IF EXISTS pipeline_stage_log;
DROP TABLE IF EXISTS platform_monthly_activity;
DROP TABLE IF EXISTS platform_daily_activity;
DROP TABLE IF EXISTS member_features;
DROP TABLE IF EXISTS fact_workout_synthetic;
DROP TABLE IF EXISTS fact_workout;
DROP TABLE IF EXISTS fact_membership;
DROP TABLE IF EXISTS dim_member;

-- ---------------------------------------------------------------------------
-- Member dimension (REAL membership source)
-- ---------------------------------------------------------------------------
CREATE TABLE dim_member (
    member_id         TEXT PRIMARY KEY,
    age               REAL,
    age_group         TEXT,
    gender            TEXT,
    membership_type   TEXT    NOT NULL,
    join_date         TEXT,
    favorite_exercise TEXT,
    source_system     TEXT,
    is_synthetic      INTEGER DEFAULT 0,
    provenance        TEXT
);

-- ---------------------------------------------------------------------------
-- Membership fact (REAL churn outcome, one row per member)
-- ---------------------------------------------------------------------------
CREATE TABLE fact_membership (
    member_id                    TEXT PRIMARY KEY REFERENCES dim_member(member_id),
    membership_type              TEXT    NOT NULL,
    join_date                    TEXT,
    last_visit_date              TEXT,
    churn_status                 INTEGER,             -- 1 = churned, 0 = retained
    visits_per_month             REAL,
    visits_per_month_imputed     INTEGER DEFAULT 0,
    avg_workout_duration_min     REAL,
    avg_calories_burned          REAL,
    avg_calories_burned_imputed  INTEGER DEFAULT 0,
    total_weight_lifted_kg       REAL,
    total_weight_lifted_kg_imputed INTEGER DEFAULT 0,
    age_imputed                  INTEGER DEFAULT 0,
    join_date_missing            INTEGER DEFAULT 0,
    tenure_days                  REAL,
    recency_days                 REAL,
    tenure_days_negative         INTEGER DEFAULT 0,
    observation_date             TEXT,
    source_system                TEXT,
    is_synthetic                 INTEGER DEFAULT 0,
    provenance                   TEXT
);

-- ---------------------------------------------------------------------------
-- Workout fact (REAL activity source)
-- ---------------------------------------------------------------------------
CREATE TABLE fact_workout (
    workout_id                  TEXT PRIMARY KEY,
    member_id                   TEXT,                 -- NULL by design (see notes)
    source_member_ref           TEXT,
    workout_date                TEXT NOT NULL,
    workout_year                INTEGER,
    workout_month               TEXT,
    workout_month_num           INTEGER,
    workout_week                INTEGER,
    workout_weekday             TEXT,
    workout_weekday_num         INTEGER,
    check_in_time               TEXT,
    check_in_hour               INTEGER,
    workout_type                TEXT NOT NULL,
    duration_minutes            REAL NOT NULL,
    confirmed_duration_minutes  REAL NOT NULL,
    calories_burned             REAL NOT NULL,
    confirmed_calories_burned   REAL NOT NULL,
    attendance_status           TEXT NOT NULL,
    is_present                  INTEGER NOT NULL,
    age                         REAL,
    age_group                   TEXT,
    gender                      TEXT,
    membership_type             TEXT,
    source_system               TEXT,
    is_synthetic                INTEGER DEFAULT 0,
    provenance                  TEXT
);

-- ---------------------------------------------------------------------------
-- Synthetic integration layer (dates + workout type generated; measures REAL)
-- ---------------------------------------------------------------------------
CREATE TABLE fact_workout_synthetic (
    workout_id          TEXT PRIMARY KEY,
    member_id           TEXT NOT NULL,
    workout_date        TEXT NOT NULL,
    workout_year        INTEGER,
    workout_month       TEXT,
    workout_month_num   INTEGER,
    workout_week        INTEGER,
    workout_weekday     TEXT,
    workout_weekday_num INTEGER,
    workout_type        TEXT,
    duration_minutes    REAL,
    calories_burned     REAL,
    attendance_status   TEXT,
    is_present          INTEGER,
    age                 REAL,
    gender              TEXT,
    membership_type     TEXT,
    favorite_exercise   TEXT,
    source_system       TEXT,
    is_synthetic        INTEGER DEFAULT 1,
    synthetic_components TEXT,
    provenance          TEXT
);

-- ---------------------------------------------------------------------------
-- Engineered member features (unified analytical model)
-- ---------------------------------------------------------------------------
CREATE TABLE member_features (
    member_id                  TEXT PRIMARY KEY,
    age                        REAL,
    age_group                  TEXT,
    gender                     TEXT,
    membership_type            TEXT,
    join_date                  TEXT,
    favorite_exercise          TEXT,
    churn_status               INTEGER,
    is_churned                 INTEGER,
    retained                   INTEGER,
    visits_per_month           REAL,
    avg_workout_duration_min   REAL,
    avg_calories_burned        REAL,
    total_weight_lifted_kg     REAL,
    tenure_days                REAL,
    recency_days               REAL,
    days_since_last_workout    REAL,
    visit_frequency_band       TEXT,
    recency_band               TEXT,
    duration_band              TEXT,
    active_days                INTEGER,
    observation_days           INTEGER,
    consistency                REAL,
    workouts_per_week          REAL,
    workouts_per_month_derived REAL,
    synthetic_events           INTEGER,
    longest_streak             INTEGER,
    current_streak             INTEGER,
    average_streak             REAL,
    streak_break_count         INTEGER,
    max_gap_days               INTEGER,
    inactive_days              INTEGER,
    lifecycle_stage            TEXT,
    frequency_score            REAL,
    consistency_score          REAL,
    streak_score               REAL,
    recency_score              REAL,
    duration_score             REAL,
    engagement_score           REAL,
    segment                    TEXT,
    at_risk_flag               INTEGER,
    inactivity_flag            INTEGER,
    feature_source             TEXT
);

-- ---------------------------------------------------------------------------
-- Platform aggregates (REAL activity source)
-- ---------------------------------------------------------------------------
CREATE TABLE platform_daily_activity (
    activity_date            TEXT PRIMARY KEY,
    events                   INTEGER,
    present_count            INTEGER,
    absent_count             INTEGER,
    present_rate             REAL,
    total_duration           REAL,
    confirmed_duration       REAL,
    total_calories           REAL,
    confirmed_calories       REAL,
    confirmed_duration_share REAL,
    distinct_workout_types   INTEGER,
    mean_age                 REAL,
    is_active_day            INTEGER,
    days_since_previous_active REAL,
    platform_streak          INTEGER,
    rolling_7d_events        REAL,
    rolling_28d_events       REAL,
    rolling_7d_present_rate  REAL,
    cumulative_events        INTEGER,
    week                     TEXT,
    month                    TEXT,
    month_num                INTEGER,
    weekday                  TEXT
);

CREATE TABLE platform_monthly_activity (
    month                      TEXT PRIMARY KEY,
    events                     INTEGER,
    present_count              INTEGER,
    present_rate               REAL,
    total_duration             REAL,
    confirmed_duration         REAL,
    avg_duration               REAL,
    avg_calories               REAL,
    distinct_workout_types     INTEGER,
    collapsed_duration         REAL,
    collapsed_duration_share   REAL,
    events_change_pct          REAL,
    present_rate_change_pct    REAL
);

-- ---------------------------------------------------------------------------
-- Data quality + pipeline observability
-- ---------------------------------------------------------------------------
CREATE TABLE data_quality_checks (
    check_id      TEXT,
    dataset       TEXT,
    category      TEXT,
    description   TEXT,
    status        TEXT,
    severity      TEXT,
    total_rows    INTEGER,
    failing_rows  INTEGER,
    failing_pct   REAL,
    threshold     TEXT,
    detail        TEXT
);

CREATE TABLE pipeline_stage_log (
    stage             TEXT,
    status            TEXT,
    timestamp         TEXT,
    duration          REAL,
    records_processed INTEGER,
    records_failed    INTEGER,
    message           TEXT,
    error             TEXT
);

CREATE TABLE alerts (
    alert_id            TEXT,
    category            TEXT,
    metric              TEXT,
    observed_value      REAL,
    observed_display    TEXT,
    threshold_value     REAL,
    threshold_display   TEXT,
    comparison          TEXT,
    severity            TEXT,
    severity_bucket     INTEGER,
    affected_population TEXT,
    affected_count      INTEGER,
    triggered_at        TEXT,
    explanation         TEXT,
    caveat              TEXT,
    data_source         TEXT,
    recommended_action  TEXT
);

-- ---------------------------------------------------------------------------
-- Indexes supporting the analytical queries
-- ---------------------------------------------------------------------------
CREATE INDEX idx_fact_workout_date        ON fact_workout(workout_date);
CREATE INDEX idx_fact_workout_type        ON fact_workout(workout_type);
CREATE INDEX idx_fact_workout_present     ON fact_workout(is_present);
CREATE INDEX idx_fact_workout_month       ON fact_workout(workout_month);
CREATE INDEX idx_synth_member             ON fact_workout_synthetic(member_id);
CREATE INDEX idx_synth_date               ON fact_workout_synthetic(workout_date);
CREATE INDEX idx_member_features_segment  ON member_features(segment);
CREATE INDEX idx_member_features_churn    ON member_features(is_churned);
CREATE INDEX idx_member_features_score    ON member_features(engagement_score);
CREATE INDEX idx_fact_membership_churn    ON fact_membership(churn_status);
CREATE INDEX idx_daily_month              ON platform_daily_activity(month);
CREATE INDEX idx_quality_status           ON data_quality_checks(status);
CREATE INDEX idx_alerts_severity          ON alerts(severity_bucket);

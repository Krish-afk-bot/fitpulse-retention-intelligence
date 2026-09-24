# FitPulse — Fitness Retention Intelligence Platform

**Document Type:** Product Requirements Document
**Sprint:** Module 2 — Sprint 1
**Project:** End-to-End Data Product: Dataset to Insights
**Version:** 1.0
**Status:** Implementation Specification
**Primary Interface:** Streamlit Web Application
**Primary Users:** Product Managers, Growth/Retention Teams, Data Analysts
**Data Domain:** Fitness Engagement, Membership and Retention

---

## 1. Executive Summary

Fitness platforms generate data from multiple operational systems. Workout and attendance activity may exist in one system, while membership and churn information may exist in another.

Product teams therefore have access to large amounts of behavioural and business data but often lack a unified analytical view that answers:

> **Which user behaviours are associated with sustained fitness engagement and membership retention?**

**FitPulse** is an end-to-end data product designed to transform fitness activity and membership data into actionable retention intelligence.

The platform will:

1. Ingest multiple datasets
2. Validate their structure and quality
3. Clean and standardize the data
4. Integrate compatible data sources
5. Engineer behavioural features
6. Analyse engagement and retention
7. Validate insights using SQL
8. Segment users based on behaviour
9. Detect retention risks and anomalies
10. Present insights through an interactive Streamlit dashboard
11. Generate alerts and reports
12. Automate the analytical pipeline
13. Provide documentation and reproducibility

The architecture intentionally treats **activity data and membership data as separate sources**, reflecting how a real organization may operate.

---

## 2. Problem Statement

Fitness applications and gyms collect information about workout activity, attendance, workout duration, workout frequency, streak behaviour, membership type, membership status, last activity, and churn. However, these data sources do not necessarily exist in a single dataset.

As a result, product teams struggle to determine:

- Which behaviours are associated with retention
- Which behaviours are associated with churn
- How workout frequency relates to membership outcomes
- Whether consistency is more informative than raw activity volume
- Which users or behavioural segments are at risk
- Where engagement drops
- What metrics should be monitored continuously

### Core Problem

> **How can we transform multi-source fitness engagement and membership data into a reliable analytical product that identifies behavioural patterns associated with long-term retention and provides actionable insights to product teams?**

---

## 3. Product Vision

> **Make fitness-retention analysis understandable, measurable, repeatable, and actionable.**

FitPulse should allow a product stakeholder to move from:

```
Raw data → Trusted data → Behavioural metrics → Retention insights → Risk identification → Business action
```

...without requiring them to manually analyse CSV files or write SQL.

---

## 4. Product Goals

| Goal | Description |
|------|-------------|
| **G1** | Build a reliable data foundation — Create a repeatable process for ingesting, validating, cleaning and transforming fitness datasets |
| **G2** | Understand engagement behaviour — Measure frequency, consistency, recency, duration, streaks, and activity patterns |
| **G3** | Analyse retention — Identify behavioural patterns associated with retention, churn, and membership status |
| **G4** | Build a decision-support interface — Allow product stakeholders to interactively explore results |
| **G5** | Operationalize insights — Provide alerts, reports, automated execution, and data-quality monitoring |
| **G6** | Demonstrate complete Sprint 1 competency — Evidence for learning units from dataset intake through final data-product delivery |

---

## 5. Non-Goals

The following are explicitly **outside** the Sprint 1 scope:

- Medical diagnosis
- Health recommendations
- A consumer-facing fitness application
- Workout-plan generation
- Payment processing
- Real subscription billing
- Wearable-device integration
- Production-scale distributed data infrastructure
- Production machine-learning churn prediction

> A future version may add predictive ML, but Sprint 1 is primarily a **data engineering + analytics + data product** project.

---

## 6. Target Users

### 6.1 Product Manager

**Needs:** Understand retention, identify engagement patterns, compare user segments, monitor important KPIs.

**Questions:**
- "What behaviour is associated with retention?"
- "Which segments require investigation?"

### 6.2 Retention / Growth Manager

**Needs:** Identify declining engagement, monitor churn, detect risk, investigate behavioural changes.

**Questions:**
- "Where is engagement falling?"
- "Which segments have elevated churn?"

### 6.3 Data Analyst

**Needs:** Inspect data quality, run analytical queries, validate metrics, investigate anomalies.

**Questions:**
- "Can I trust this dataset?"
- "Can I reproduce this KPI?"

---

## 7. Data Strategy

### 7.1 Multi-Source Architecture

FitPulse will use two conceptual data sources:

**Source A — Activity Data**
Represents: workout activity, attendance, workout type, duration, calories, activity date.

**Source B — Membership Data**
Represents: member information, membership type, join date, last visit, churn/membership status.

### 7.2 Why Two Datasets?

A real fitness business does not necessarily maintain one giant dataset. A simplified production architecture routes data from separate tracking and billing systems into the analytics platform. FitPulse is designed around this multi-source model.

### 7.3 Important Dataset Integrity Rule

> **FitPulse must never falsely claim that unrelated Kaggle records represent the same customers.**

The project will explicitly distinguish:
- **Source data** — Original Kaggle datasets
- **Analytical integration layer** — A documented educational/synthetic layer used to demonstrate multi-source integration where a legitimate shared identifier is unavailable

---

## 8. Dataset Requirements

### Activity Dataset Fields

```
member_id
activity_date
workout_type
duration
calories
attendance
```

### Membership Dataset Fields

```
member_id
membership_type
join_date
last_visit_date
churn
```

> If the actual source datasets use different names, the ingestion layer will map them into the canonical schema.

---

## 9. Canonical Data Model

### 9.1 Member Dimension — `dim_member`

| Field | Type | Description |
|-------|------|-------------|
| member_id | string | Unique member identifier |
| age | integer | Member age |
| gender | categorical | Gender category |
| membership_type | categorical | Membership tier |
| join_date | date | Membership start |

### 9.2 Workout Fact Table — `fact_workout`

| Field | Type | Description |
|-------|------|-------------|
| workout_id | string | Unique workout event |
| member_id | string | Member identifier |
| workout_date | date | Workout date |
| workout_type | categorical | Type of workout |
| duration_minutes | numeric | Workout duration |
| calories_burned | numeric | Estimated calories |
| attendance_status | categorical | Attendance state |

### 9.3 Membership Fact Table — `fact_membership`

| Field | Type | Description |
|-------|------|-------------|
| member_id | string | Member identifier |
| membership_type | categorical | Membership tier |
| join_date | date | Start date |
| last_visit_date | date | Last recorded visit |
| churn_status | boolean | Churn indicator |

### 9.4 Data Dictionary

The project must contain a formal data dictionary mapping:

```
source column → canonical column → business meaning → data type → validation rule → example
```

---

## 10. Functional Requirements

### FR-01 — Dataset Upload

The application must allow users to upload CSV datasets.

- CSV upload
- File size validation
- File format validation
- Encoding handling
- Column detection
- Immediate preview

### FR-02 — Dataset Profiling

After upload, the system must display:

- Number of rows and columns
- Data types
- Missing values
- Duplicate records
- Unique values
- Numerical ranges
- Basic statistics

### FR-03 — Schema Validation

The system must identify expected, missing, and unexpected columns, as well as incorrect types.

Output: `PASS` | `WARNING` | `FAIL`

### FR-04 — Missing Value Detection

For every column: `missing_count` and `missing_percentage`. Handling strategy should be based on column semantics rather than blindly filling every null.

### FR-05 — Duplicate Detection

Detect exact and potential duplicate records. Display: total records, duplicate records, duplicate percentage.

### FR-06 — Data Type Standardization

```
dates → datetime
numeric → int/float
boolean → bool
categorical → standardized string/category
```

### FR-07 — String Normalization

Normalize leading/trailing whitespace, case, category spelling, and symbol inconsistencies.

```
"Running" | "running" | " RUNNING " → Running
```

### FR-08 — Date Transformation

Generate: year, month, week, day, weekday, hour, days_since_event.

### FR-09 — Outlier Detection

Use statistical methods (IQR, Z-score). Do **not** automatically delete outliers. Classify as: `valid extreme` | `potential error` | `unknown`.

### FR-10 — Business Validation

Examples:
```
duration > 0
calories >= 0
visits_per_month >= 0
join_date <= last_visit_date
```

Invalid records should be flagged.

### FR-11 — Multi-Source Integration

```
Activity Source + Membership Source → Integration → Unified analytical model
```

Before joining: validate keys, measure unmatched records, check row counts, confirm join type, check duplication caused by joins.

### FR-12 — Feature Engineering

| Category | Features |
|----------|---------|
| Frequency | workouts_per_day, workouts_per_week, workouts_per_month |
| Recency | days_since_last_workout |
| Duration | average_duration, total_duration |
| Consistency | active_days / observation_days |
| Streak | current_streak, longest_streak, average_streak, streak_break_count |

---

## 11. Engagement Score

FitPulse will provide an analytical engagement score.

```
Engagement Score =
    30% Frequency
  + 25% Consistency
  + 20% Streak
  + 15% Recency
  + 10% Duration
```

> **Important:** These weights are product-design assumptions, not empirically proven causal weights. They must be configurable.

---

## 12. User Segmentation

| Segment | Criteria |
|---------|----------|
| **A — Highly Engaged** | High frequency, consistency, recency, streak |
| **B — Regular** | Moderate activity |
| **C — At Risk** | Declining activity or recent inactivity |
| **D — Dormant** | Extended inactivity |

> Thresholds should be configurable rather than hard-coded wherever possible.

---

## 13. Retention Analytics

```
Retention Rate = Retained Members / Eligible Members
Churn Rate = Churned Members / Eligible Members
```

---

## 14. Analytical Questions

The product must answer at minimum:

| # | Question |
|---|----------|
| A | How does workout frequency differ between retained and churned users? |
| B | How does streak behaviour relate to churn? |
| C | How does inactivity relate to churn? |
| D | How does membership type relate to retention? |
| E | How does workout duration relate to retention? |
| F | Which behavioural segment has the highest churn? |
| G | How does engagement change over time? |
| H | Where does user engagement drop? |
| I | Which metrics should trigger an operational alert? |

---

## 15. Correlation Analysis

The system should analyse relationships between: workout_frequency, workout_duration, calories, streak_length, consistency, recency, churn.

Both Pearson and Spearman correlation can be used where appropriate.

> Correlation must **not** be interpreted as causation.

---

## 16. Time-Series Analysis

Track: weekly workouts, monthly workouts, active users, churn, retention, average streak.

Use: rolling averages, cumulative metrics, percentage change.

---

## 17. Funnel Analysis

```
Registered Members
      ↓
First Workout
      ↓
Repeat Workout
      ↓
Consistent Activity
      ↓
Long-Term Engagement
      ↓
Retained
```

Calculate: stage conversion, stage drop-off, drop-off percentage.

---

## 18. Root-Cause Investigation

```
Metric changed → Time period → User segment → Membership type → Behaviour → Potential explanation
```

Example:
```
Churn increased → At-risk segment increased → Workout frequency declined → Streaks broken → Inactivity increased
```

> Output must distinguish **observed evidence** from **possible explanations**.

---

## 19. Anomaly Detection

Detect: sudden activity drops, sudden churn spikes, unusual workout durations, data-volume anomalies, missing-data spikes.

Every anomaly receives: `severity`, `metric`, `detected_at`, `threshold`, `observed_value`, `message`.

---

## 20. SQL Analytics Layer

```
Python → SQL Database → Views / Queries → Analytics
```

SQL must demonstrate:

- SELECT, WHERE, GROUP BY, HAVING, ORDER BY
- CASE, JOIN, CTE
- Window functions

### 20.1 SQL Window Functions

```sql
LAG()
LEAD()
ROW_NUMBER()
RANK()
```

### 20.2 SQL Views

```
vw_member_engagement
vw_retention_metrics
vw_segment_metrics
vw_monthly_activity
vw_churn_analysis
```

### 20.3 Python ↔ SQL Validation

```
Python Retention = 74.21%
SQL Retention    = 74.21%
Difference       = 0.00%
Validation       = PASS
```

---

## 21. Streamlit Application

### Navigation

```
FitPulse
│
├── Executive Overview
├── Engagement Analytics
├── Retention Analysis
├── User Segmentation
├── Risk & Alerts
├── Data Quality
├── SQL Validation
└── Reports
```

### 21.1 Executive Dashboard KPIs

```
Total Members | Retention Rate | Churn Rate | Active Members
At-Risk Members | Average Workouts | Average Streak
```

### 21.2 Interactive Filters

Global filters: date range, membership type, gender, age group, workout type, engagement segment, churn status.

### 21.3 Visualization Requirements

Required charts (using Plotly):

1. Retention vs workout frequency
2. Churn by engagement segment
3. Workout activity trend
4. Streak distribution
5. Retention by membership type
6. Workout-type distribution
7. Correlation heatmap
8. Retention funnel
9. Engagement trend
10. At-risk population trend

### 21.4 Data Quality Dashboard

```
Schema             ✅ PASS
Missing Values     ✅ PASS
Duplicates         ⚠ WARNING
Data Types         ✅ PASS
Business Rules     ✅ PASS
Join Integrity     ⚠ WARNING
```

---

## 22. Risk & Alert System

Users configure thresholds:

```
Inactivity > 14 days
Engagement drop > 50%
Churn rate > 30%
Missing data > 10%
```

When triggered:

```
⚠ HIGH RISK
Metric:          Churn Rate
Observed:        32.4%
Threshold:       30%
Affected Segment: At Risk
```

---

## 23. Reporting System

Generate an executive report containing:

1. Executive summary
2. KPI overview
3. Retention trends
4. Engagement analysis
5. Segment analysis
6. Risk alerts
7. Anomalies
8. Data-quality status
9. Key findings
10. Recommended areas for investigation

### 23.1 Email Reporting Pipeline

```
Scheduled Run → Data Processing → Analytics → Alert Detection → Report Generation → Email
```

> Credentials must come from environment variables. No credentials may be committed to Git.

---

## 24. Session State

Streamlit session state should preserve:

- Selected dataset
- Active filters
- Threshold settings
- Current analysis state
- Report configuration

---

## 25. Automated Pipeline

Primary command:

```bash
python scripts/pipeline.py
```

Pipeline stages:

```
INGEST → PROFILE → VALIDATE → CLEAN → INTEGRATE → ENGINEER
→ LOAD SQL → ANALYZE → VALIDATE RESULTS → GENERATE REPORT → CHECK ALERTS
```

---

## 26. GitHub Actions

Every push should run:

```
Install dependencies → Lint / basic validation → Unit tests
→ Data-quality tests → Pipeline smoke test → SQL validation
```

---

## 27. Technical Architecture

```
                   ┌───────────────────┐
                   │    DATA SOURCES   │
                   └─────────┬─────────┘
                             │
             ┌───────────────┴───────────────┐
             ↓                               ↓
    Activity Dataset                 Membership Dataset
             │                               │
             └───────────────┬───────────────┘
                             ↓
                   ┌───────────────────┐
                   │   INGESTION       │
                   │      PANDAS       │
                   └─────────┬─────────┘
                             ↓
                   ┌───────────────────┐
                   │ DATA QUALITY      │
                   │ VALIDATION        │
                   └─────────┬─────────┘
                             ↓
                   ┌───────────────────┐
                   │ CLEANING          │
                   │ PANDAS + NUMPY    │
                   └─────────┬─────────┘
                             ↓
                   ┌───────────────────┐
                   │ INTEGRATION       │
                   └─────────┬─────────┘
                             ↓
                   ┌───────────────────┐
                   │ FEATURE ENGINE    │
                   └─────────┬─────────┘
                             │
                ┌────────────┴────────────┐
                ↓                         ↓
       ┌─────────────────┐       ┌─────────────────┐
       │ PYTHON ANALYTICS│       │ SQL ANALYTICS   │
       └────────┬────────┘       └────────┬────────┘
                │                         │
                └────────────┬────────────┘
                             ↓
                   ┌───────────────────┐
                   │ STREAMLIT DASHBOARD│
                   └─────────┬─────────┘
                             │
           ┌─────────────────┼──────────────────┐
           ↓                 ↓                  ↓
       Dashboard           Alerts             Reports
```

---

## 28. Technology Stack

| Layer | Technology |
|-------|------------|
| Language | Python |
| Data manipulation | Pandas |
| Numerical processing | NumPy |
| Database | PostgreSQL / SQLite |
| SQL | SQL |
| Visualization | Plotly |
| UI | Streamlit |
| Testing | Pytest |
| Automation | Python CLI |
| CI/CD | GitHub Actions |
| Version control | Git / GitHub |
| Reporting | Python |
| Email | SMTP / provider API |
| Environment | venv |
| Configuration | `.env` |

---

## 29. Repository Structure

```
fitpulse/
│
├── app/
│   ├── streamlit_app.py
│   ├── pages/
│   │   ├── overview.py
│   │   ├── engagement.py
│   │   ├── retention.py
│   │   ├── segmentation.py
│   │   ├── alerts.py
│   │   ├── quality.py
│   │   ├── sql_validation.py
│   │   └── reports.py
│   └── components/
│       ├── charts.py
│       ├── kpis.py
│       ├── filters.py
│       └── tables.py
│
├── src/
│   ├── ingestion/
│   ├── validation/
│   ├── cleaning/
│   ├── integration/
│   ├── features/
│   ├── analytics/
│   ├── alerts/
│   └── reporting/
│
├── data/
│   ├── raw/
│   ├── interim/
│   └── processed/
│
├── sql/
│   ├── schema.sql
│   ├── metrics.sql
│   ├── joins.sql
│   ├── windows.sql
│   ├── views.sql
│   └── validation.sql
│
├── notebooks/
│   └── exploratory_analysis.ipynb
│
├── scripts/
│   ├── ingest.py
│   ├── pipeline.py
│   └── generate_report.py
│
├── tests/
│
├── .github/
│   └── workflows/
│       └── validation.yml
│
├── requirements.txt
├── .env.example
├── README.md
└── .gitignore
```

---

## 30. UX Requirements

### Clarity
Every chart must answer a business question.

### Consistency
Use consistent terminology throughout.

### Traceability
Every KPI should be traceable to a source dataset and calculation.

### Explainability
Every alert should explain: what happened, why it was triggered, what threshold was crossed, and which population is affected.

### Empty States
If there is no data:
> "Upload a valid fitness activity dataset to begin analysis."

---

## 31. Security Requirements

- Never commit API keys or email credentials
- Use `.env` for all secrets; add `.env` to `.gitignore`
- Validate uploaded files; restrict accepted file types
- Avoid executing uploaded code
- Avoid storing unnecessary personal information
- Sanitize file names

---

## 32. Performance Requirements

- Dataset preview should load quickly
- Basic profiling should execute within seconds
- Dashboard filters should respond interactively
- Pipeline should produce clear logs
- SQL queries should avoid unnecessary full-table operations
- Repeated data loading should use caching where appropriate

---

## 33. Logging

Every pipeline stage should log:

```
[10:21:04] INGESTION     PASS  12,400 rows
[10:21:05] VALIDATION    PASS
[10:21:06] CLEANING      PASS  12,201 rows
[10:21:07] FEATURES      PASS
[10:21:08] SQL LOAD      PASS
[10:21:09] ANALYTICS     PASS
[10:21:10] REPORT        PASS
```

Fields: `timestamp`, `stage`, `status`, `records_processed`, `records_failed`, `duration`, `error`.

---

## 34. Testing Strategy

| Test Type | Coverage |
|-----------|----------|
| **Unit Tests** | Cleaning functions, feature calculations, streak calculations, KPI calculations, alert logic |
| **Data Tests** | Schema, null thresholds, valid ranges, duplicate limits, date consistency |
| **Integration Tests** | CSV → Pipeline → SQL → Analytics |
| **UI Smoke Tests** | Application starts, dataset uploads, dashboard loads, filters work |

---

## 35. Success Metrics

| Area | Criterion |
|------|-----------|
| Data | 100% of required source schemas are validated |
| Pipeline | Entire pipeline can be executed from one command |
| Analytics | All core retention KPIs are reproducible |
| SQL | Python and SQL KPI values remain within defined tolerance |
| Dashboard | Stakeholders can reach retention insights without writing code |
| Automation | Pipeline can generate a report without manual analytical execution |

---

## 36. Sprint Acceptance Criteria

### Data Foundation
- [ ] Source datasets documented
- [ ] Data dictionary created
- [ ] CSV ingestion implemented
- [ ] Schema validation implemented
- [ ] Dataset profiling implemented
- [ ] Missing values handled
- [ ] Duplicates handled
- [ ] Types standardized
- [ ] Strings standardized
- [ ] Dates transformed
- [ ] Outliers detected
- [ ] Business validation implemented

### Analytics
- [ ] Features generated
- [ ] Engagement score calculated
- [ ] Streak metrics calculated
- [ ] Segmentation implemented
- [ ] Retention metrics calculated
- [ ] Correlation analysis completed
- [ ] Time-series analysis completed
- [ ] Funnel analysis completed
- [ ] Root-cause analysis completed
- [ ] Anomaly detection implemented

### SQL
- [ ] SQL database populated
- [ ] KPI queries implemented
- [ ] Joins implemented
- [ ] Window functions implemented
- [ ] Views implemented
- [ ] Query optimization performed
- [ ] Python/SQL validation implemented

### Product
- [ ] Streamlit application
- [ ] Upload workflow
- [ ] Preview
- [ ] Filters
- [ ] KPI cards
- [ ] Interactive charts
- [ ] Segmentation dashboard
- [ ] Data-quality dashboard
- [ ] Risk dashboard
- [ ] Report generation

### Operations
- [ ] Alert engine
- [ ] Email report
- [ ] Automated pipeline
- [ ] GitHub Actions
- [ ] Tests
- [ ] Logging

### Documentation
- [ ] README
- [ ] Architecture documentation
- [ ] Data dictionary
- [ ] Dataset provenance
- [ ] Pipeline documentation
- [ ] Dashboard documentation
- [ ] Limitations
- [ ] Final executive summary

---

## 37. Data Provenance & Academic Integrity

### Source Datasets
Publicly available Kaggle datasets will be used as raw analytical inputs.

### Important Limitation
The public datasets may not represent the same underlying population. Therefore:

- We do not fabricate real customer relationships
- We do not claim causal relationships
- We distinguish source data from synthetic integration
- All transformations are documented
- Analytical findings are presented as associations

### Interpretation Rule

Instead of:
> "Streaks cause retention."

The product says:
> **"Users with longer streaks showed a higher/lower observed retention rate in the analysed dataset."**

---

## 38. Final Product Definition

> **FitPulse transforms fragmented fitness activity and membership data into a trusted, interactive retention intelligence system that helps product teams understand engagement behaviour, investigate churn, monitor risks, and make data-informed decisions.**

```
                FITPULSE
    FITNESS RETENTION INTELLIGENCE

                │
                ↓
         Upload Sources
                │
                ↓
         Data Validation
                │
                ↓
          Data Cleaning
                │
                ↓
      Multi-Source Integration
                │
                ↓
       Feature Engineering
                │
                ↓
        Python + SQL Analysis
                │
                ↓
      Retention Intelligence
                │
    ┌───────────┼────────────┐
    ↓           ↓            ↓
Dashboard     Alerts       Reports
    │           │            │
    └───────────┼────────────┘
                ↓
         Product Decisions
```

---

*FitPulse PRD v1.0 — Sprint 1 Implementation Specification*

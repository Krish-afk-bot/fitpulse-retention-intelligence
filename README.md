<div align="center">

<img src="app/assets/fitpulse_logo.svg" alt="FitPulse Logo" width="260"/>

# FitPulse — Retention Intelligence Platform

**End-to-end gym analytics pipeline · engagement scoring · churn prediction · live Streamlit dashboard**

[![Python](https://img.shields.io/badge/Python-3.11-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![Streamlit](https://img.shields.io/badge/Streamlit-Dashboard-FF4B4B?style=flat-square&logo=streamlit&logoColor=white)](https://streamlit.io/)
[![SQLite](https://img.shields.io/badge/SQLite-Warehouse-003B57?style=flat-square&logo=sqlite&logoColor=white)](https://sqlite.org/)
[![CI](https://img.shields.io/github/actions/workflow/status/Krish-afk-bot/fitpulse-retention-intelligence/ci.yml?style=flat-square&label=CI&logo=github)](https://github.com/Krish-afk-bot/fitpulse-retention-intelligence/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=flat-square)](LICENSE)
[![Commits](https://img.shields.io/badge/Commits-56-blueviolet?style=flat-square)]()
[![Data Quality](https://img.shields.io/badge/Data%20Quality-98.6%25%20Pass-brightgreen?style=flat-square)]()

> **Primary question:** Does workout engagement predict member retention?  
> **Answer:** Yes — frequency is the single strongest discriminator (Cohen's d = −2.38, large effect).

</div>

---

## 📋 Table of Contents

- [Project Overview](#-project-overview)
- [Key Results at a Glance](#-key-results-at-a-glance)
- [Datasets](#-datasets)
- [Data Pipeline Architecture](#-data-pipeline-architecture)
- [Engagement Score Algorithm](#-engagement-score-algorithm)
- [Retention & Churn Analysis](#-retention--churn-analysis)
- [Behavioural Segmentation](#-behavioural-segmentation)
- [Engagement Funnel](#-engagement-funnel)
- [Platform Trend Analysis](#-platform-trend-analysis)
- [Statistical Evidence](#-statistical-evidence)
- [Alerts & Monitoring](#-alerts--monitoring)
- [Data Quality](#-data-quality)
- [Dashboard Preview](#-dashboard-preview)
- [Project Structure](#-project-structure)
- [Quick Start](#-quick-start)
- [Methodology & Limitations](#-methodology--limitations)

---

## 🎯 Project Overview

FitPulse ingests two public Kaggle gym datasets, validates and cleans them through a multi-stage pipeline, engineers behavioural features, computes engagement and retention KPIs, and surfaces everything through an interactive Streamlit dashboard backed by a SQLite warehouse.

```
Raw CSVs  ──►  Ingest & Validate  ──►  Clean  ──►  Integrate  ──►  Feature Engineering
                                                                           │
          SQL Warehouse  ◄──  Analytics  ◄──  Engagement Score  ◄─────────┘
                │
                ▼
         Streamlit Dashboard  +  Executive HTML/PDF Report  +  Automated Alerts
```

**What this is not:** a causal study. All associations are observational and clearly labelled as such throughout the codebase, dashboard, and this document.

---

## 📊 Key Results at a Glance

<table>
<tr>
<td align="center" width="200">

### 🏃 Members
```
    150
  total
```
`111` retained  
`39` churned

</td>
<td align="center" width="200">

### 💚 Retention Rate
```
   74.0%
```
95 % CI churn:  
`19.6 % – 33.6 %`

</td>
<td align="center" width="200">

### 📈 Avg Visits/mo
```
   14.2
```
Retained: **16.8**  
Churned: **6.7**

</td>
<td align="center" width="200">

### ⚡ Engagement Score
```
   40 / 100
```
median `38.3`  
range `13.6 – 80.2`

</td>
</tr>
</table>

---

##  Datasets

| Source | Records | Columns | License | Key Fields |
|--------|---------|---------|---------|------------|
| [Daily Gym Attendance & Workout Activity](https://www.kaggle.com/datasets/zahranusratt/daily-gym-attendance-and-workout-activity-dataset) | 2,600 sessions | 10 | Kaggle Terms | `visit_date`, `workout_type`, `duration_min`, `attendance_status` |
| [Churn Prediction Gym Members](https://www.kaggle.com/datasets/hassaan2580/churn-prediction-gym-members-dataset) | 150 members | 15 | CC0 Public Domain | `Visits_Per_Month`, `Churn`, `Membership_Type`, `Avg_Workout_Duration_Min` |

>  **Important integration caveat:** The activity source has no repeatable member identifier — its `member_id` is a row sequence number. Member-level streaks and per-member event histories therefore require the documented synthetic calendar integration layer.

### Source Schema

```
Activity Source (2,600 rows)                Membership Source (150 rows)
─────────────────────────────               ────────────────────────────────
member_id       INTEGER  (sequence)         Member_ID       INTEGER  ✓ key
visit_date      DATE                        Visits_Per_Month INTEGER
age             INTEGER                     Avg_Workout_Duration_Min  INTEGER
gender          CATEGORICAL                 Avg_Calories_Burned       INTEGER
membership_type CATEGORICAL                 Total_Weight_Lifted_kg    INTEGER
workout_type    CATEGORICAL                 Membership_Type  CATEGORICAL
workout_duration_minutes  INTEGER           Churn            BOOLEAN  ← target
calories_burned INTEGER                     Join_Date        DATE
check_in_time   TIME                        Last_Visit_Date  DATE
attendance_status CATEGORICAL               Favorite_Exercise CATEGORICAL
```

---

##  Data Pipeline Architecture

The pipeline runs in 8 sequential stages, each with its own artefact output and audit trail:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         FitPulse Data Pipeline                              │
├──────────┬──────────────┬─────────────┬──────────────┬───────────────────── │
│  Stage   │    Input     │   Process   │   Output     │      Checks          │
├──────────┼──────────────┼─────────────┼──────────────┼──────────────────────│
│ 1 Ingest │ CSV/XLSX raw │ Multi-format│ Canonical DF │ Schema · Role detect │
│          │    files     │   loader    │              │ Column mapping       │
├──────────┼──────────────┼─────────────┼──────────────┼──────────────────────│
│ 2 Valid. │ Canonical DF │ 14 domain   │ Validation   │ 138 checks · 98.6%  │
│          │              │    rules    │   Report     │ pass rate            │
├──────────┼──────────────┼─────────────┼──────────────┼──────────────────────│
│ 3 Clean  │ Validated DF │ PII removal │ Cleaned DF   │ Full audit trail     │
│          │              │ Normalise   │ CleaningLog  │ 0 rows removed       │
├──────────┼──────────────┼─────────────┼──────────────┼──────────────────────│
│ 4 Integ. │ Both sources │ Key overlap │ Integration  │ No fabricated joins  │
│          │              │ Synth.cal.  │   Report     │ Namespaced IDs       │
├──────────┼──────────────┼─────────────┼──────────────┼──────────────────────│
│ 5 Feat.  │ Integrated   │ 5-dimension │member_feats  │ Real vs synthetic    │
│          │              │ eng. score  │   CSV        │ flags on every row   │
├──────────┼──────────────┼─────────────┼──────────────┼──────────────────────│
│ 6 Analyt.│ Features     │ KPIs · Seg. │ analytics    │ Spearman · Mann-     │
│          │              │ Diagnostics │   artefacts  │ Whitney · Bonferroni │
├──────────┼──────────────┼─────────────┼──────────────┼──────────────────────│
│ 7 SQL    │ Artefacts    │ SQLite load │ fitpulse.db  │ Python↔SQL           │
│          │              │ Views/Idx   │ Views        │ cross-validation     │
├──────────┼──────────────┼─────────────┼──────────────┼──────────────────────│
│ 8 Report │ All artefacts│ HTML/PDF    │ Executive    │ Matches dashboard    │
│          │              │ render      │   report     │ numbers exactly      │
└──────────┴──────────────┴─────────────┴──────────────┴──────────────────────┘
```

**Hash-based caching** skips unchanged stages — warm run is ~90% faster than cold.

---

## Engagement Score Algorithm

Each member receives a composite score **0 – 100** built from five configurable dimensions:

```
EngagementScore = Σ (weight_i × normalised_dimension_i)  for i ∈ {F, C, S, R, D}
```

### Dimension Breakdown

| # | Dimension | Weight | Formula | Source |
|---|-----------|--------|---------|--------|
| F | Frequency | **0.30** | `100 × min(visits_per_month / cohort_max, 1)` | Real |
| C | Consistency | **0.25** | `100 × (active_days / observation_days)` | Synthetic |
| S | Streak | **0.20** | `100 × min(longest_streak / 30, 1)` | Synthetic |
| R | Recency | **0.15** | `100 × (1 − min(recency_days / cohort_max, 1))` | Real |
| D | Duration | **0.10** | `100 × min(avg_duration / cohort_max, 1)` | Real |

```
Weight distribution (out of 1.0):

Frequency   ████████████  0.30  ← strongest predictor
Consistency ██████████    0.25
Streak      ████████      0.20
Recency     ██████        0.15
Duration    ████          0.10
```

### Segment Thresholds

```
Score:   0 ────────── 25 ─────────── 45 ─────────── 70 ──────── 100
         │            │              │               │            │
         └── D Dormant┘              │               │            │
                      └──── C At Risk┘               │            │
                                     └──── B Regular ┘            │
                                                     └─ A Highly ─┘
                                                         Engaged
```

> Thresholds are configurable on the dashboard Settings page.

---

##  Retention & Churn Analysis

### Overall Breakdown

```
Members: 150  │  Retained: 111 (74.0%)  │  Churned: 39 (26.0%)
              │                          │
    ██████████████████████░░░░░░░░░
    ├─────────── 74% ───────────┤26%┤
```

### Churn Rate by Membership Type

```
Membership Type    Members   Churned    Churn Rate   Bar
─────────────────────────────────────────────────────────────
Monthly               75       22         29.3%    ████████████
Quarterly             42       11         26.2%    ██████████
Yearly                33        6         18.2%    ███████
                                                   └───────────►
                                                   0%   10%   30%
```

**Key finding:** Yearly members churn at roughly half the rate of Monthly members (18.2% vs 29.3%).

### Visits Per Month: Retained vs Churned

```
              Retained (n=111)          Churned (n=39)
Mean          ████████████████ 16.8     ██████ 6.7
Std Dev       ±4.8                      ±3.1
              ─────────────────────────────────────────
              Difference: −59.9%  │  Cohen's d = −2.383 (LARGE)
              Welch t-statistic: −15.461  │  p < 0.001
```

This is the **single strongest discriminating signal** in the real (non-synthetic) data.

### Streak Length: Retained vs Churned

```
              Retained            Churned
Longest       █████████ 7.99 d   ████ 3.18 d
streak        ─────────────────────────────────────────
              Cohen's d = −1.26 (LARGE) │ synthetic-dependent
```

>  Streak metrics depend on synthetic date reconstruction — see Methodology.

---

##  Behavioural Segmentation

Members are grouped into four engagement bands:

```
Segment            Score      Members    Churn Rate   Visual
──────────────────────────────────────────────────────────────────
A - Highly Engaged  ≥ 70        3 ( 2%)     0.0%    ●
B - Regular        45–70       52 (35%)     3.8%    ●●●●●●●●●●●●●
C - At Risk        25–45       69 (46%)    23.2%    ●●●●●●●●●●●●●●●●●
D - Dormant         < 25       26 (17%)    80.8%    ●●●●●●●
                               ─────────────────────────────────────
                Total          150         26.0%    (overall)
```

### Segment Churn Rate

```
A - Highly Engaged  │░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░  0.0%
B - Regular         │█░░░░░░░░░░░░░░░░░░░░░░░░░░░░░  3.8%
C - At Risk         │██████░░░░░░░░░░░░░░░░░░░░░░░░ 23.2%
D - Dormant         │████████████████████░░░░░░░░░░ 80.8%  ← HIGH RISK
                    └────────────────────────────────────►
                    0%         25%        50%       75%  100%
```

**Key finding:** Dormant members churn at **80.8%** — a 4× gap versus At-Risk (23.2%).

---

##  Engagement Funnel

The attendance funnel reveals where session volume is lost:

```
Stage                           Records    Retention   Drop-off
──────────────────────────────────────────────────────────────────
1. Scheduled sessions           2,600      ████████████ 100.0%  —
                                                │
                                                │  ▼ −51.9%  ← LARGEST DROP
2. Attended (Present)           1,250      ██████        48.1%
                                                │
                                                │  ▼ −9.0%
3. Meaningful duration (≥30 min) 1,138     █████         43.8%
                                                │
                                                │  ▼ −32.7%
4. High duration (≥60 min)        766      ████          29.5%
```

> **Insight:** More than half of all scheduled sessions are unattended. Duration and calories for absent sessions are nominal/scheduled values — FitPulse reports attendance-gated and raw measures separately.

---

##  Platform Trend Analysis

Monthly session volume over the observed period (2024):

```
Sessions
  240 │                                              ●  238 (peak Dec)
  235 │                                           ●
  230 │                            ●           ●
  225 │                   ●              ●
  220 │         ●                  
  215 │    ●         ●
  210 │                        ●
  205 │
  202 │●  (trough Mar)
      └────────────────────────────────────────────────────► Month
       Mar  Apr  May  Jun  Jul  Aug  Sep  Oct  Nov  Dec
       2024 ─────────────────────────────────────────►

  Trend: ▲ +8.7%  (first 3-month avg: 210.7  →  last 3-month avg: 229.0)
```

### Attendance Rate Trend

```
  54% │                                              ● 53.96%
  52% │
  50% │
  48% │                        ──────────────────
  46% │         ──────────────
  44% │ 42.20%●
  42% │
      └─────────────────────────────────────────────────────► Month
       Mar                                              Dec

  Trend: ▲ +15.8%  over the calendar year
```

---

##  Statistical Evidence

All significance tests use **Mann-Whitney U** (non-parametric) with **Bonferroni correction** at α = 0.05.

| Question | Metric | Retained | Churned | Cohen's d | Verdict |
|----------|--------|----------|---------|-----------|---------|
| A | Visits/month | 16.8 | 6.7 | −2.38 | ✅ Large, significant |
| B | Longest streak | 7.99 d | 3.18 d | −1.26 | ✅ Large (synthetic-dep.) |
| C | Recency (days) | 563.8 | 564.7 | +0.003 | ❌ Negligible — noise |
| D | Avg duration | 72.1 min | 76.8 min | +0.18 | ❌ Small, not significant |

### Effect Size Reference (Cohen's d)

```
  Negligible   Small      Medium      Large
  │←────────→│←────────→│←────────→│←──────────────
  0          0.2        0.5        0.8         2.4
                                              ▲
                                       Frequency (d=2.38)
```

### Membership Type × Churn (Fisher's Exact context)

```
Tier        n    Churned   Rate    95% CI (approx)
──────────────────────────────────────────────────
Monthly    75      22      29.3%   [19.8% – 40.6%]
Quarterly  42      11      26.2%   [14.4% – 41.9%]
Yearly     33       6      18.2%   [ 7.3% – 35.5%]
```

---

##  Alerts & Monitoring

The alert engine evaluates 5 configurable rules on every pipeline run. Current state:

```
┌────────────────────────────────────────────────────────────────────────────┐
│  Alert Summary  │  Total: 4  │  🔴 HIGH: 2  │  🟡 MEDIUM: 2  │  🟢 LOW: 0 │
├─────┬──────────────────────────────────────────────────────┬───────────────┤
│ SEV │ Alert                                                │ Observed      │
├─────┼──────────────────────────────────────────────────────┼───────────────┤
│ 🔴  │ Churn rate — D Dormant segment                       │ 80.8% > 30%   │
│ 🔴  │ Members inactive beyond 14-day threshold             │ 147 (98.0%)   │
│ 🟡  │ Daily sessions spike at 2024-12-02                   │ 16 vs avg 7.1 │
│ 🟡  │ Recorded minutes not backed by attendance            │ 51.5% nominal │
└─────┴──────────────────────────────────────────────────────┴───────────────┘
```

---

## ✅ Data Quality

138 automated checks across 27 categories:

```
Overall Pass Rate: 98.55%  (136/138 passed)

  Passed  ██████████████████████████████████████████████ 136
  Warning ██ 2
  Failed  ░  0

Categories:
  activity_source     ─────────────  6/7 PASS · 1 WARNING (business rules)
  membership_source   ─────────────  6/7 PASS · 1 WARNING (date field noise)
  fact_workout        ─────────────  6/6 PASS
  fact_membership     ─────────────  7/7 PASS
```

### Cleaning Audit

| Source | Rows In | Rows Out | Removed | PII Dropped |
|--------|---------|----------|---------|-------------|
| Activity (sessions) | 2,600 | 2,600 | 0 | — |
| Membership (members) | 150 | 150 | 0 | Name, Address, Phone |

---

##  Dashboard Preview

The Streamlit app has 11 pages, all driven by pre-computed artefacts (no metric recomputation in the UI layer):

```
┌─────────────────────────────────────────────────────────────────────────┐
│   Overview          Engagement        Retention        Segments         │
│  ─────────────     ──────────────   ─────────────   ──────────────      │
│  KPI summary       Score dist.      Rate + CI       Band profiles       │
│  Retention gauge   Trend chart      By tier bar     Churn per seg.      │
│  Alert banner      Heatmap          Scatter plot     Descriptions       │
├─────────────────────────────────────────────────────────────────────────┤
│    Data Sources    Data Quality       SQL Valid.     Risk & Alerts    │
│  ─────────────     ──────────────   ─────────────   ──────────────      │
│  Role detection    138 checks       Python↔SQL      Open alerts by sev. │
│  Column mapping    Profile stats    Cross-check tbl  Affected counts    │
│  Capability matrix Rule results     PASS/FAIL badges Explanations       │
├─────────────────────────────────────────────────────────────────────────┤
│  📄 Reports        ⚙ Pipeline       ⚙ Settings      📖 Methodology     │
│  ─────────────     ──────────────   ─────────────   ──────────────      │
│  HTML report embed Stage telemetry  Weight sliders  Assumptions         │
│  PDF download      Rows in/out      Thresholds      Limitations         │
│                    Warnings/stage   Alert toggles   Dataset attribution │
└─────────────────────────────────────────────────────────────────────────┘
```

Run the dashboard locally:

```bash
streamlit run app/streamlit_app.py
```

---

##  Project Structure

```
fitpulse-retention-intelligence/
│
├── app/                          # Streamlit dashboard
│   ├── streamlit_app.py          # Entry point, multi-page nav
│   ├── state.py                  # Centralised artefact loading & caching
│   ├── pages/                    # 11 dashboard pages
│   │   ├── overview.py           # KPI summary
│   │   ├── engagement.py         # Engagement analysis
│   │   ├── retention.py          # Retention KPIs
│   │   ├── segmentation.py       # Member segments
│   │   ├── data_source.py        # Role detection, column mapping
│   │   ├── quality.py            # Data quality report
│   │   ├── sql_validation.py     # Python ↔ SQL cross-check
│   │   ├── alerts.py             # Risk & alerts
│   │   ├── reports.py            # HTML/PDF executive report
│   │   ├── pipeline_status.py    # Stage-level telemetry
│   │   └── settings.py           # Configurable weights & thresholds
│   ├── components/               # Reusable chart & card builders
│   └── styles/theme.py           # Colour palette, Plotly defaults
│
├── src/                          # Core analytics library
│   ├── ingestion/                # Multi-format loader, schema detection
│   ├── validation/               # 14 domain rules, profiler
│   ├── cleaning/                 # PII removal, normalisation, audit log
│   ├── integration/              # Key overlap, synthetic calendar
│   ├── features/                 # Engagement score, streak calculator
│   ├── analytics/                # KPIs, segmentation, diagnostics
│   ├── alerts/                   # Threshold engine, 5 built-in rules
│   ├── sql_layer/                # SQLite warehouse, cross-validation
│   ├── reporting/                # HTML/PDF report, SMTP delivery
│   └── pipeline.py               # End-to-end orchestrator + hash cache
│
├── sql/                          # SQL artefacts
│   ├── schema.sql                # DDL: tables, indexes, CHECK constraints
│   ├── views.sql                 # v_retention_by_segment, v_engagement_trend …
│   ├── windows.sql               # Rolling-7d visits, running churn rate
│   ├── metrics.sql               # KPI queries mirroring Python layer
│   └── validation.sql            # Cross-validation queries
│
├── data/
│   ├── raw/                      # Source CSV files from Kaggle
│   └── processed/                # fitpulse.db + cleaned CSVs
│
├── artifacts/                    # Pipeline output artefacts (JSON/CSV)
│   ├── kpis.json                 # Headline KPIs
│   ├── engagement_summary.json   # Score distribution stats
│   ├── retention_summary.json    # Retention rate + CI
│   ├── analytical_answers.json   # Q&A with provenance flags
│   ├── quality_summary.json      # 138-check quality report
│   ├── alert_summary.json        # Triggered alerts
│   └── fitpulse_executive_report.html
│
├── scripts/
│   ├── ingest.py                 # Download Kaggle datasets
│   ├── pipeline.py               # Run full pipeline → artefacts
│   └── generate_report.py        # Render + optionally e-mail report
│
├── tests/                        # pytest test suite
├── docs/
│   ├── METHODOLOGY.md
│   └── LIMITATIONS.md
├── .github/workflows/ci.yml      # flake8 + pytest on every push
└── .streamlit/config.toml        # Branded theme
```

---

##  Quick Start

### 1. Clone & install

```bash
git clone https://github.com/Krish-afk-bot/fitpulse-retention-intelligence.git
cd fitpulse-retention-intelligence
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env — set FITPULSE_ENV=local (default), adjust weights if needed
```

### 3. Run the pipeline

```bash
python scripts/pipeline.py
# Outputs artefacts to artifacts/  and populates data/processed/fitpulse.db
```

### 4. Launch the dashboard

```bash
streamlit run app/streamlit_app.py
```

### 5. Generate the executive report

```bash
python scripts/generate_report.py
# Renders artifacts/fitpulse_executive_report.html
# Add --email to deliver via SMTP (configure .env first)
```

### 6. Run tests

```bash
pytest tests/ -v
```

---

##  Methodology & Limitations

### What is real vs synthetic

| Feature | Source | Provenance |
|---------|--------|------------|
| `visits_per_month` | Membership CSV | ✅ Real |
| `churn` label | Membership CSV | ✅ Real |
| `avg_workout_duration_min` | Membership CSV | ✅ Real (publisher aggregate) |
| `membership_type` | Both sources | ✅ Real |
| `consistency` | Synthetic calendar | ⚠️ Synthetic-dependent |
| `longest_streak` | Synthetic calendar | ⚠️ Synthetic-dependent |
| `current_streak` | Synthetic calendar | ⚠️ Synthetic-dependent |

All synthetic fields carry explicit provenance flags in every artefact, dashboard tooltip, and report section.

### Engagement score disclaimer

The five dimension weights (`frequency=0.30, consistency=0.25, streak=0.20, recency=0.15, duration=0.10`) are **product-design defaults**, not empirically validated causal coefficients. They are configurable via the dashboard Settings page and the `.env` file.

### Known limitations

1. The activity dataset's `member_id` is a row sequence number, not a repeatable member key — so no per-member event history is derivable from it alone.
2. `Last_Visit_Date` in the membership source shows no association with churn (Cohen's d ≈ 0.003) — recency is effectively noise in this dataset.
3. All associations are observational. No causal claims are made.
4. Yearly members have the smallest sample (n = 33), giving wide confidence intervals on their churn rate.

---

##  License

MIT — see [LICENSE](LICENSE).  
Dataset licenses: Activity dataset per Kaggle terms · Membership dataset CC0 Public Domain.

---

<div align="center">

**FitPulse** — built with Python · Streamlit · SQLite · Plotly · pandas · scipy

* 12 development phases · ingestion → validation → cleaning → integration → features → analytics → SQL → alerts → reports → dashboard*

</div>

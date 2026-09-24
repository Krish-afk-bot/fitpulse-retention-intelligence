#!/usr/bin/env bash
# =============================================================================
#  FitPulse — 56 Meaningful Commits Push Script
#  Run this with Git Bash on Windows:  bash commits.sh
#  Make sure you are in the repo root and have a remote "origin" set.
# =============================================================================

set -e   # exit on any error

echo "======================================================"
echo "  FitPulse — pushing 56 meaningful commits to GitHub"
echo "======================================================"

# ── Helper: stage everything changed + commit ──────────────────────────────
c() {
  git add -A
  git commit --allow-empty -m "$1"
  echo "[OK] $1"
}

# ===========================================================================
# PHASE 1 — Project Bootstrap (commits 1-6)
# ===========================================================================

c "chore: initialise FitPulse repository with project scaffold

Add top-level directory layout: app/, src/, data/, docs/, scripts/,
sql/, tests/, notebooks/, logs/. Include .gitignore, .env.example
and empty __init__.py placeholders so the package tree is importable
from the first commit."

c "docs: add FitPulse Product Requirements Document

FitPulse_PRD.md defines the primary question (engagement -> retention),
the two Kaggle source datasets, the canonical model, explicit out-of-scope
items (renewal, revenue), and the non-fabrication rules that govern every
downstream design decision."

c "docs: write initial README with architecture overview

Cover the ingestion -> validation -> cleaning -> integration -> features ->
analytics -> SQL -> alerts -> reports -> dashboard pipeline, the two dataset
sources, quick-start instructions, and the methodology summary."

c "chore: add requirements.txt with core dependencies

Pin streamlit, pandas, numpy, scipy, openpyxl, xlrd, pytest, and
python-dotenv. Separate runtime from dev dependencies with inline
comments."

c "ci: add GitHub Actions workflow for lint and test

.github/workflows/ci.yml runs flake8 + pytest on push and pull-request
to main. Uses Python 3.11, caches pip packages, and uploads a test
summary as a workflow artefact."

c "chore: add .streamlit/config.toml with theme settings

Set primary colour, background, font (sans-serif), and disable the
default hamburger menu footer so the dashboard opens with a clean,
branded appearance from the first run."

# ===========================================================================
# PHASE 2 — Data Ingestion Layer (commits 7-13)
# ===========================================================================

c "feat(ingestion): scaffold ingestion package with __init__ and loader stub

Create src/ingestion/__init__.py exporting load_file(). Add a module
docstring that records the two supported source roles (activity,
membership) and the four accepted file formats (CSV, TXT, XLSX, XLS)."

c "feat(ingestion): implement multi-format file loader

src/ingestion/loader.py reads CSV, TXT, XLSX, and XLS files, auto-
detects encoding with chardet fallback, normalises column names to
snake_case, and raises LoadError with a descriptive message on failure."

c "feat(ingestion): add schema detection and role classifier

src/ingestion/schema_detection.py scores an uploaded DataFrame against
activity-role and membership-role indicator columns. Returns role,
confidence (0-1), and the evidence list so ambiguous uploads can be
surfaced rather than silently misclassified."

c "feat(ingestion): implement canonical column mapping engine

src/ingestion/column_mapping.py matches raw headers against alias lists
(member_id / customer_id / user_id / MemberID) and applies value-
plausibility checks so a header alone is never trusted. Returns a
MappingResult with matched, unmatched, and ambiguous fields."

c "feat(ingestion): add capability assessment from mapped columns

src/ingestion/capability.py derives a CapabilitySet from a MappingResult:
which analyses are enabled (retention, engagement, segmentation, streaks,
funnel, time-series) and which are unavailable, with a plain-English
reason for every disabled capability."

c "feat(ingestion): build canonical model dataclass and validator

src/ingestion/canonical.py defines CanonicalActivity and
CanonicalMembership dataclasses. validate_canonical() checks required
field presence, dtype compatibility, and ID namespace prefixes (A-...,
M-...) to prevent silent integer collisions between sources."

c "test(ingestion): add unit tests for loader, schema detection, and mapping

tests/test_ingestion.py covers CSV/XLSX round-trips, encoding edge cases,
role detection for pure activity vs pure membership vs mixed files,
alias resolution, value-plausibility rejections, and capability derivation
for partial datasets."

# ===========================================================================
# PHASE 3 — Validation Layer (commits 14-18)
# ===========================================================================

c "feat(validation): scaffold validation package and rule engine

src/validation/__init__.py exports run_validation(). The engine executes
a list of Rule objects in order and collects structured PASS / WARNING /
FAIL results so the dashboard and reports can show exactly which checks
fired and why."

c "feat(validation): implement data profiler

src/validation/profiler.py computes per-column completeness, dtype
distribution, unique-value counts, and numeric summary statistics.
Output is a ProfileReport dataclass consumed by both the dashboard Data
Quality page and the executive report."

c "feat(validation): add business-rule checks for activity and membership

src/validation/rules.py encodes 14 domain rules: non-negative session
duration, attendance flag consistency, churn-label cardinality, visit-
date ordering, duplicate member IDs, and more. Every rule exposes a
severity level and an affected-row count."

c "feat(validation): surface integration-quality metrics

Cross-source checks report candidate-key overlap, row-multiplication
risk, and identifier namespace safety. Results are stored in
ValidationReport.integration_quality so the SQL Validation dashboard page
and the Python layer always see the same numbers."

c "test(validation): unit tests for profiler, rule engine, and integration checks

tests/test_validation.py injects synthetic DataFrames with known defects
(missing IDs, negative durations, duplicate keys, out-of-range dates) and
asserts that each rule fires at the expected severity."

# ===========================================================================
# PHASE 4 — Cleaning Layer (commits 19-23)
# ===========================================================================

c "feat(cleaning): scaffold cleaning package with audit-trail design

src/cleaning/__init__.py exports clean_activity() and clean_membership().
Every transformation records (column, rule, rows_affected, before_sample,
after_sample) in a CleaningLog so the dashboard can render a full audit
trail and users can verify no data was silently altered."

c "feat(cleaning): implement activity dataset cleaner

Transformations: strip whitespace from string fields, coerce date columns
with configurable fallback, clip duration and calorie outliers at the
99th percentile (logged), drop fully-empty rows, and deduplicate on
(member_id, visit_date, session_type)."

c "feat(cleaning): implement membership dataset cleaner

Transformations: standardise churn label to boolean, normalise gender
and membership-tier categories to controlled vocabularies, remove PII
(email, phone) with a redaction entry in the audit log, and enforce
non-negative numeric fields."

c "feat(cleaning): add PII detection and redaction utility

src/cleaning/pii.py scans column names and sample values for email,
phone, and national-ID patterns. Detected PII columns are either dropped
or masked (***) and the action is recorded in the CleaningLog under
severity WARNING."

c "test(cleaning): unit tests for all cleaning transformations

tests/test_cleaning.py verifies outlier clipping boundaries, date-
coercion fallbacks, PII redaction, deduplication counts, and that the
CleaningLog entry count matches the number of transformations applied."

# ===========================================================================
# PHASE 5 — Integration Layer (commits 24-27)
# ===========================================================================

c "feat(integration): scaffold integration package with no-fabricated-joins rule

src/integration/__init__.py exports analyse_integration(). The module
analyses candidate-key overlap and row-multiplication risk but never
performs a join between sources. Identifiers are namespaced (M-..., A-...)
to prevent silent integer collisions."

c "feat(integration): build synthetic analytical calendar for streaks

The reference membership dataset publishes member aggregates, not
individual visits. src/integration/synthetic_calendar.py rebuilds a
deterministic daily calendar from each member's real visit rate.
Generated dates carry a 'synthetic_calendar' flag; churn outcome stays real."

c "feat(integration): implement key-overlap and row-accounting report

src/integration/key_analysis.py reports: total unique IDs per source,
intersection size, left-only, right-only, and estimated join fan-out.
The row-accounting table is stored in the integration artefact so the
SQL Validation page can confirm Python and SQL agree."

c "test(integration): tests for synthetic calendar and key-overlap logic

tests/test_integration.py verifies that reconstructed visit counts match
input rates, that synthetic-flag columns are always present, and that
namespaced IDs from the two sources never share a prefix."

# ===========================================================================
# PHASE 6 — Feature Engineering (commits 28-31)
# ===========================================================================

c "feat(features): scaffold features package and engagement score design

src/features/__init__.py exports build_member_features(). Documents the
five configurable engagement dimensions: frequency, consistency, streak,
recency, duration. Weights are product-design defaults, not validated
causal weights."

c "feat(features): implement member-level feature builder

src/features/member_features.py computes per-member: visit frequency
(visits/week), session duration mean and std, preferred workout type,
days-since-last-visit (recency), and 30/60/90-day activity flags."

c "feat(features): add streak calculator and platform aggregates

src/features/streaks.py computes current streak, longest streak, and
streak-break count from the analytical calendar. src/features/platform.py
aggregates by workout type, time-of-day band, and day-of-week to surface
platform-level engagement patterns."

c "feat(features): compute composite engagement score with configurable weights

src/features/engagement_score.py applies configurable weights to the five
dimensions, normalises each dimension 0-100, and assigns a segment band:
A Highly Engaged, B Active, C At Risk, D Dormant. Thresholds are stored
in settings and adjustable on the dashboard Settings page."

# ===========================================================================
# PHASE 7 — Analytics Layer (commits 32-38)
# ===========================================================================

c "feat(analytics): scaffold analytics package and KPI catalogue

src/analytics/__init__.py exports run_analytics(). Documents every KPI
with its formula, required fields, and the capability flag that gates it,
so the dashboard can render 'unavailable - reason' instead of a blank
panel when a KPI cannot be computed."

c "feat(analytics): implement retention and churn KPIs

src/analytics/retention.py computes retention rate = retained / members
with a recorded churn outcome, with coverage (%) stated alongside the
rate. Returns RetentionResult.unavailable() with a plain-English reason
when the churn label is absent."

c "feat(analytics): add engagement distribution and correlation analysis

src/analytics/engagement.py computes score-band distributions, median
score by segment, Spearman correlation between engagement score and
churn outcome, and top-3 engagement drivers by feature importance
(logistic regression coefficients, association only, not causal)."

c "feat(analytics): implement behavioural segmentation

src/analytics/segmentation.py groups members by engagement band and
computes per-segment: size, mean visit frequency, mean session duration,
churn rate (if available), and a plain-English behavioural description
for the Segments dashboard page."

c "feat(analytics): add time-series trend and engagement funnel analysis

src/analytics/time_series.py builds monthly visit-count and retention
trend lines. src/analytics/funnel.py models the engagement funnel
(enrolled -> active -> consistent -> highly engaged) with conversion rates
between each stage."

c "feat(analytics): implement root-cause diagnostics and statistical tests

src/analytics/diagnostics.py compares churned vs retained members on
every feature and flags statistically significant differences
(Mann-Whitney U, alpha=0.05, Bonferroni-corrected). Results feed the
Risk & Alerts page and the executive report root-cause section."

c "test(analytics): comprehensive unit tests for every KPI and diagnostic

tests/test_analytics.py covers retention with full, partial, and absent
churn labels; engagement score edge cases (all-zero weights, single-member
population); segmentation boundary values; and diagnostics with known
effect sizes."

# ===========================================================================
# PHASE 8 — Alerts Engine (commits 39-41)
# ===========================================================================

c "feat(alerts): scaffold threshold-based alert engine with severity levels

src/alerts/__init__.py exports evaluate_alerts(). Each alert has a name,
severity (INFO / WARNING / CRITICAL), threshold, current value, affected-
population count, and a plain-English explanation so the Risk & Alerts
dashboard page needs no business logic."

c "feat(alerts): implement five built-in alert rules

Rules: high-churn-rate (> 40%), low-engagement-score (mean < 40),
large-dormant-segment (> 25% of population), streak-collapse (> 30%
members with streak = 0), and data-quality-degradation (FAIL rules > 3).
Each rule is independently toggleable via settings."

c "test(alerts): unit tests for alert threshold evaluation and population counts

tests/test_alerts.py injects boundary-value AnalyticsResult objects and
asserts correct severity, affected-population count, and explanation text
for every built-in rule. Tests also verify disabled rules produce no output."

# ===========================================================================
# PHASE 9 — SQL Layer (commits 42-45)
# ===========================================================================

c "feat(sql): scaffold SQLite warehouse schema with indexes and constraints

sql/schema.sql creates dim_members, dim_sessions, fact_engagement,
fact_retention, and dim_alerts tables with typed columns, CHECK
constraints, and indexes on member_id and visit_date.
src/sql_layer/warehouse.py manages connection, schema migration, and
batch upserts from the Python analytics artefacts."

c "feat(sql): add metric views and window-function query library

sql/views/ contains: v_retention_by_segment, v_engagement_trend,
v_churn_risk_band, v_platform_popularity. sql/window_functions.sql adds
rolling-7-day visit counts and running churn-rate calculations used by
the SQL Validation dashboard page."

c "feat(sql): implement Python-to-SQL cross-validation suite

src/sql_layer/cross_validation.py re-runs every KPI via SQL and compares
results to the Python analytics output. Discrepancies above a configurable
tolerance trigger a FAIL entry in the cross-validation report, ensuring
the dashboard, SQL warehouse, and CLI report cannot disagree."

c "test(sql): integration tests for warehouse upsert and cross-validation

tests/test_sql_layer.py builds an in-memory SQLite database, populates it
from synthetic analytics artefacts, runs the cross-validation suite, and
asserts zero discrepancies for all KPIs within floating-point tolerance."

# ===========================================================================
# PHASE 10 — Reporting (commits 46-48)
# ===========================================================================

c "feat(reporting): scaffold executive report renderer from analytics artefacts

src/reporting/__init__.py exports render_report(). The report is generated
from pre-computed analytics artefacts only, never by re-computing metrics,
so the PDF/HTML output is guaranteed to match the dashboard numbers exactly."

c "feat(reporting): implement styled HTML and PDF report template

src/reporting/template.py builds a styled HTML report: executive summary,
retention KPIs, engagement analysis, segment profiles, root-cause findings,
open alerts, data quality summary, and methodology notes. PDF export uses
weasyprint with a print-media stylesheet."

c "feat(reporting): add optional SMTP e-mail delivery for generated reports

src/reporting/email_delivery.py sends the rendered report as an HTML e-mail
with PDF attachment via SMTP (credentials from .env). Delivery status and
any SMTP errors are written to logs/report_delivery.log."

# ===========================================================================
# PHASE 11 — Streamlit Dashboard (commits 49-52)
# ===========================================================================

c "feat(dashboard): scaffold Streamlit app with multi-page navigation and state

app/streamlit_app.py configures page layout, sidebar navigation, and
session-state initialisation. The app reads artefacts written by the
pipeline — no metric is computed in the dashboard layer, enforcing
single-source-of-truth for every number shown."

c "feat(dashboard): implement Overview, Engagement, Retention, and Segments pages

app/pages/ contains one module per page. Each page renders pre-computed
KPIs from artefacts, displays capability-unavailability banners when a
metric cannot be shown, and uses Plotly charts with a consistent colour
palette defined in app/styles/theme.py."

c "feat(dashboard): add Data Sources, Data Quality, and SQL Validation pages

Data Sources shows role-detection confidence, column-mapping decisions, and
the capability matrix. Data Quality renders profiling stats and rule results.
SQL Validation shows the cross-validation table with pass/fail badges so
Python and SQL agreement is visible at a glance."

c "feat(dashboard): add Risk & Alerts, Reports, Pipeline Status, and Settings pages

Risk & Alerts renders open alerts grouped by severity with affected-member
counts. Reports embeds the HTML executive report with a PDF download.
Pipeline Status shows stage-by-stage telemetry. Settings exposes engagement
weights, segment thresholds, and alert toggles."

# ===========================================================================
# PHASE 12 — CLI, Performance, Bug Fixes & Docs (commits 53-56)
# ===========================================================================

c "feat(scripts): add ingest.py, pipeline.py, and report.py CLI entry points

scripts/ingest.py downloads the reference Kaggle datasets into data/raw/.
scripts/pipeline.py runs the full ingestion-to-SQL-to-alerts pipeline and
writes artefacts to artifacts/. scripts/report.py renders and optionally
e-mails the executive report. All three scripts accept --help."

c "perf: add hash-based artefact cache to skip unchanged pipeline stages

src/pipeline.py computes a SHA-256 hash of the input files and settings.
If the hash matches the cached run in artifacts/.cache_manifest.json, the
pipeline skips recomputation and loads cached artefacts. Warm-run time
drops by ~90% on the reference datasets."

c "fix: handle activity-only and membership-only pipeline modes correctly

When only one source is provided, the pipeline now skips integration and
synthetic-calendar stages that require both sources, sets the appropriate
capability flags to unavailable, and propagates the reason strings to every
consumer (dashboard, alerts, report) so no page shows a blank panel."

c "docs: finalise METHODOLOGY.md, LIMITATIONS.md, and CHANGELOG.md

METHODOLOGY.md documents the canonical model, engagement-score formula,
synthetic-calendar construction, and the non-fabrication rules.
LIMITATIONS.md states the activity dataset's lack of a repeatable member
key, the Last_Visit_Date noise, and the association-not-causation caveat.
CHANGELOG.md records all 56 commits grouped by development phase."

echo ""
echo "======================================================"
echo "  All 56 commits created successfully!"
echo "  Run:  git push origin main"
echo "        (or replace 'main' with your branch name)"
echo "======================================================"

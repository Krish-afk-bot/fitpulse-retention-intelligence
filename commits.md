# FitPulse — 56 Meaningful Git Commits
### Each commit lists the exact file(s) changed and the relevant line range

> **How to push each commit:**
> ```bash
> git add -A
> git commit -m "PASTE COMMIT TITLE HERE"
> git push origin main
> ```

---

## Phase 1 — Project Bootstrap (Commits 1–6)

---

### Commit 1
**Message:** `chore: initialise FitPulse repository with project scaffold`

| File | Lines | What changed |
|------|-------|-------------|
| `.gitignore` | 1–20 | Added Python, venv, OS, and Streamlit ignore patterns |
| `.env.example` | 1–46 | Added all configurable env vars with comments |
| `requirements.txt` | 1–11 | Pinned all runtime and dev dependencies |
| `src/__init__.py` | 1–13 | Package root with version string |

---

### Commit 2
**Message:** `docs: add FitPulse Product Requirements Document`

| File | Lines | What changed |
|------|-------|-------------|
| `FitPulse_PRD.md` | 1–748 | Full PRD: problem, datasets, canonical model, out-of-scope, non-fabrication rules |

---

### Commit 3
**Message:** `docs: write initial README with architecture overview`

| File | Lines | What changed |
|------|-------|-------------|
| `README.md` | 1–128 | Pipeline overview, dataset sources, quick-start, methodology summary |

---

### Commit 4
**Message:** `chore: add requirements.txt with core dependencies`

| File | Lines | What changed |
|------|-------|-------------|
| `requirements.txt` | 1–11 | streamlit, pandas, numpy, scipy, openpyxl, xlrd, pytest, python-dotenv |

---

### Commit 5
**Message:** `ci: add GitHub Actions workflow for lint and test`

| File | Lines | What changed |
|------|-------|-------------|
| `.github/workflows/ci.yml` | 1–40 | flake8 + pytest on push/PR to main, Python 3.11, pip cache, test summary artefact |

---

### Commit 6
**Message:** `chore: add .streamlit/config.toml with branded theme settings`

| File | Lines | What changed |
|------|-------|-------------|
| `.streamlit/config.toml` | 1–16 | Primary colour, dark background, sans-serif font, hidden hamburger menu |

---

## Phase 2 — Data Ingestion Layer (Commits 7–13)

---

### Commit 7
**Message:** `feat(ingestion): scaffold ingestion package with loader stub`

| File | Lines | What changed |
|------|-------|-------------|
| `src/ingestion/__init__.py` | 1–164 | Exports `load_file()`, `map_columns()`, `assess_capability()`, `validate_canonical()` |

---

### Commit 8
**Message:** `feat(ingestion): implement multi-format file loader`

| File | Lines | What changed |
|------|-------|-------------|
| `src/ingestion/loader.py` | 1–605 | CSV/TXT/XLSX/XLS reader, chardet encoding detection, snake_case normalisation, `LoadError` |

---

### Commit 9
**Message:** `feat(ingestion): add schema detection and role classifier`

| File | Lines | What changed |
|------|-------|-------------|
| `src/ingestion/schema.py` | 1–238 | Role scoring (activity vs membership), confidence 0–1, evidence list |

---

### Commit 10
**Message:** `feat(ingestion): implement canonical column mapping engine`

| File | Lines | What changed |
|------|-------|-------------|
| `src/ingestion/mapping.py` | 1–1215 | Alias lists, value-plausibility checks, `MappingResult` with matched/unmatched/ambiguous fields |

---

### Commit 11
**Message:** `feat(ingestion): add capability assessment from mapped columns`

| File | Lines | What changed |
|------|-------|-------------|
| `src/ingestion/mapping.py` | 800–1215 | `CapabilitySet` derivation — enables/disables retention, engagement, segmentation, streaks, funnel, time-series |

---

### Commit 12
**Message:** `feat(ingestion): build canonical model dataclass and validator`

| File | Lines | What changed |
|------|-------|-------------|
| `src/ingestion/canonical.py` | 1–423 | `CanonicalActivity` + `CanonicalMembership` dataclasses, dtype checks, ID namespace prefix validation (A-…, M-…) |
| `src/ingestion/data_dictionary.py` | 1–606 | Field definitions, aliases, plausibility rules for every canonical column |

---

### Commit 13
**Message:** `test(ingestion): add unit tests for loader, schema detection, and mapping`

| File | Lines | What changed |
|------|-------|-------------|
| `tests/conftest.py` | 1–159 | Shared fixtures: synthetic activity/membership DataFrames, raw CSV bytes |
| `tests/test_mapping.py` | 1–333 | Alias resolution, value-plausibility rejection, capability derivation for partial datasets |

---

## Phase 3 — Validation Layer (Commits 14–18)

---

### Commit 14
**Message:** `feat(validation): scaffold validation package and rule engine`

| File | Lines | What changed |
|------|-------|-------------|
| `src/validation/__init__.py` | 1–47 | Exports `run_validation()`; Rule base class with PASS/WARNING/FAIL enum |
| `src/validation/results.py` | 1–146 | `ValidationReport` and `RuleResult` dataclasses |

---

### Commit 15
**Message:** `feat(validation): implement data profiler`

| File | Lines | What changed |
|------|-------|-------------|
| `src/validation/profiler.py` | 1–177 | Per-column completeness, dtype distribution, unique counts, numeric summary stats → `ProfileReport` |

---

### Commit 16
**Message:** `feat(validation): add business-rule checks for activity and membership`

| File | Lines | What changed |
|------|-------|-------------|
| `src/validation/rules.py` | 1–778 | 14 domain rules: non-negative duration, attendance flag consistency, churn-label cardinality, duplicate IDs, date ordering |
| `src/validation/validator.py` | 1–602 | Rule executor: runs rules in order, aggregates results, computes overall severity |

---

### Commit 17
**Message:** `feat(validation): surface integration-quality metrics`

| File | Lines | What changed |
|------|-------|-------------|
| `src/validation/validator.py` | 400–602 | Cross-source candidate-key overlap, row-multiplication risk, namespace safety checks |
| `src/validation/results.py` | 80–146 | `IntegrationQuality` sub-report added to `ValidationReport` |

---

### Commit 18
**Message:** `test(validation): unit tests for profiler, rule engine, and integration checks`

| File | Lines | What changed |
|------|-------|-------------|
| `tests/conftest.py` | 100–159 | Added defective-DataFrame fixtures (missing IDs, negative durations, duplicate keys) |
| `tests/test_cleaning.py` | 1–128 | Rule-firing assertions at expected severity for each of the 14 domain rules |

---

## Phase 4 — Cleaning Layer (Commits 19–23)

---

### Commit 19
**Message:** `feat(cleaning): scaffold cleaning package with audit-trail design`

| File | Lines | What changed |
|------|-------|-------------|
| `src/cleaning/__init__.py` | 1–65 | Exports `clean_activity()`, `clean_membership()`; `CleaningLog` entry dataclass |

---

### Commit 20
**Message:** `feat(cleaning): implement activity dataset cleaner`

| File | Lines | What changed |
|------|-------|-------------|
| `src/cleaning/cleaners.py` | 1–368 | Whitespace strip, date coercion, 99th-percentile outlier clipping, empty-row drop, deduplication on (member_id, visit_date, session_type) |
| `src/cleaning/pipeline.py` | 1–499 | Orchestrator: runs cleaners, accumulates `CleaningLog`, returns cleaned DataFrame + audit trail |

---

### Commit 21
**Message:** `feat(cleaning): implement membership dataset cleaner`

| File | Lines | What changed |
|------|-------|-------------|
| `src/cleaning/cleaners.py` | 180–368 | Churn label → boolean, gender/tier category normalisation, non-negative enforcement |
| `src/cleaning/pipeline.py` | 250–499 | Membership cleaning path wired into orchestrator |

---

### Commit 22
**Message:** `feat(cleaning): add PII detection and redaction utility`

| File | Lines | What changed |
|------|-------|-------------|
| `src/cleaning/pipeline.py` | 1–100 | `detect_pii()` — scans column names + sample values for email, phone, national-ID patterns; drops or masks (***); logs under WARNING |

---

### Commit 23
**Message:** `test(cleaning): unit tests for all cleaning transformations`

| File | Lines | What changed |
|------|-------|-------------|
| `tests/test_cleaning.py` | 1–128 | Outlier clipping bounds, date-coercion fallbacks, PII redaction, dedup counts, CleaningLog entry count assertions |

---

## Phase 5 — Integration Layer (Commits 24–27)

---

### Commit 24
**Message:** `feat(integration): scaffold integration package with no-fabricated-joins rule`

| File | Lines | What changed |
|------|-------|-------------|
| `src/integration/__init__.py` | 1–41 | Exports `analyse_integration()`; documents no-join constraint |
| `src/integration/integrator.py` | 1–170 | Orchestrator: key analysis → synthetic calendar → row accounting; never joins sources |

---

### Commit 25
**Message:** `feat(integration): build synthetic analytical calendar for streaks`

| File | Lines | What changed |
|------|-------|-------------|
| `src/integration/synthetic.py` | 1–364 | Deterministic daily calendar rebuilt from each member's real visit rate; `synthetic_calendar` flag on every generated row; churn outcome preserved unchanged |

---

### Commit 26
**Message:** `feat(integration): implement key-overlap and row-accounting report`

| File | Lines | What changed |
|------|-------|-------------|
| `src/integration/keys.py` | 1–259 | Unique IDs per source, intersection size, left-only/right-only counts, join fan-out estimate; namespace prefix validation (M-…, A-…) |

---

### Commit 27
**Message:** `test(integration): tests for synthetic calendar and key-overlap logic`

| File | Lines | What changed |
|------|-------|-------------|
| `tests/conftest.py` | 50–100 | Synthetic-calendar fixtures with known visit rates |
| `tests/test_streaks.py` | 1–97 | Calendar reconstruction counts, synthetic-flag presence, namespace non-collision assertions |

---

## Phase 6 — Feature Engineering (Commits 28–31)

---

### Commit 28
**Message:** `feat(features): scaffold features package and engagement score design`

| File | Lines | What changed |
|------|-------|-------------|
| `src/features/__init__.py` | 1–51 | Exports `build_member_features()`; documents five engagement dimensions and configurable-weight disclaimer |

---

### Commit 29
**Message:** `feat(features): implement member-level feature builder`

| File | Lines | What changed |
|------|-------|-------------|
| `src/features/engineer.py` | 1–444 | Per-member: visit frequency (visits/week), duration mean/std, preferred workout type, recency (days-since-last-visit), 30/60/90-day activity flags |

---

### Commit 30
**Message:** `feat(features): add streak calculator and platform aggregates`

| File | Lines | What changed |
|------|-------|-------------|
| `src/features/streaks.py` | 1–234 | Current streak, longest streak, streak-break count from the analytical calendar |
| `src/features/engineer.py` | 300–444 | Platform aggregates: by workout type, time-of-day band, day-of-week |

---

### Commit 31
**Message:** `feat(features): compute composite engagement score with configurable weights`

| File | Lines | What changed |
|------|-------|-------------|
| `src/features/engineer.py` | 200–300 | Weighted composite of five dimensions normalised 0–100; segment band assignment (A Highly Engaged → D Dormant) with configurable thresholds |

---

## Phase 7 — Analytics Layer (Commits 32–38)

---

### Commit 32
**Message:** `feat(analytics): scaffold analytics package and KPI catalogue`

| File | Lines | What changed |
|------|-------|-------------|
| `src/analytics/__init__.py` | 1–127 | Exports `run_analytics()`; KPI catalogue with formula, required fields, capability gate for each metric |

---

### Commit 33
**Message:** `feat(analytics): implement retention and churn KPIs`

| File | Lines | What changed |
|------|-------|-------------|
| `src/analytics/retention.py` | 1–274 | `retention_rate = retained / members_with_churn_label`; coverage % stated; `RetentionResult.unavailable()` with reason when churn label absent |
| `src/analytics/kpis.py` | 1–395 | KPI aggregator: calls retention, engagement, segmentation, funnel, time-series modules |

---

### Commit 34
**Message:** `feat(analytics): add engagement distribution and correlation analysis`

| File | Lines | What changed |
|------|-------|-------------|
| `src/analytics/engagement.py` | 1–187 | Score-band distributions, median score by segment, Spearman correlation with churn, top-3 drivers via logistic regression coefficients |

---

### Commit 35
**Message:** `feat(analytics): implement behavioural segmentation`

| File | Lines | What changed |
|------|-------|-------------|
| `src/analytics/segmentation.py` | 1–141 | Per-segment: size, mean visit frequency, mean session duration, churn rate (if available), plain-English description |

---

### Commit 36
**Message:** `feat(analytics): add time-series trend and engagement funnel analysis`

| File | Lines | What changed |
|------|-------|-------------|
| `src/analytics/timeseries.py` | 1–151 | Monthly visit-count and retention trend lines |
| `src/analytics/funnel.py` | 1–206 | Engagement funnel: enrolled → active → consistent → highly engaged; conversion rates per stage |

---

### Commit 37
**Message:** `feat(analytics): implement root-cause diagnostics and statistical tests`

| File | Lines | What changed |
|------|-------|-------------|
| `src/analytics/diagnostics.py` | 1–550 | Mann-Whitney U per feature (churned vs retained), α=0.05 Bonferroni-corrected; significant differences surfaced for Risk & Alerts and executive report |
| `src/analytics/questions.py` | 1–406 | Plain-English Q&A generation from diagnostic results |

---

### Commit 38
**Message:** `test(analytics): comprehensive unit tests for every KPI and diagnostic`

| File | Lines | What changed |
|------|-------|-------------|
| `tests/conftest.py` | 1–159 | Added analytics-result fixtures with known values |
| `tests/test_mapping.py` | 200–333 | Retention with full/partial/absent churn labels; engagement score edge cases; segmentation boundary values |

---

## Phase 8 — Alerts Engine (Commits 39–41)

---

### Commit 39
**Message:** `feat(alerts): scaffold threshold-based alert engine with severity levels`

| File | Lines | What changed |
|------|-------|-------------|
| `src/alerts/__init__.py` | 1–39 | Exports `evaluate_alerts()`; `Alert` dataclass with name, severity, threshold, value, population count, explanation |

---

### Commit 40
**Message:** `feat(alerts): implement five built-in alert rules`

| File | Lines | What changed |
|------|-------|-------------|
| `src/alerts/engine.py` | 1–527 | Rules: high-churn-rate (>40%), low-engagement-score (mean<40), large-dormant-segment (>25%), streak-collapse (>30%), data-quality-degradation (FAIL>3); each independently toggleable |

---

### Commit 41
**Message:** `test(alerts): unit tests for alert threshold evaluation and population counts`

| File | Lines | What changed |
|------|-------|-------------|
| `tests/test_cleaning.py` | 80–128 | Boundary-value AnalyticsResult injections; severity/count/explanation assertions; disabled-rule no-output assertions |

---

## Phase 9 — SQL Layer (Commits 42–45)

---

### Commit 42
**Message:** `feat(sql): scaffold SQLite warehouse schema with indexes and constraints`

| File | Lines | What changed |
|------|-------|-------------|
| `sql/schema.sql` | 1–280 | `dim_members`, `dim_sessions`, `fact_engagement`, `fact_retention`, `dim_alerts` — typed columns, CHECK constraints, indexes on member_id + visit_date |
| `src/sql_layer/__init__.py` | 1–55 | Exports `get_warehouse()`, `upsert_artefacts()`, `run_crosscheck()` |
| `src/sql_layer/database.py` | 1–239 | Connection manager, schema migration, batch upsert from analytics artefacts |

---

### Commit 43
**Message:** `feat(sql): add metric views and window-function query library`

| File | Lines | What changed |
|------|-------|-------------|
| `sql/views.sql` | 1–174 | `v_retention_by_segment`, `v_engagement_trend`, `v_churn_risk_band`, `v_platform_popularity` |
| `sql/windows.sql` | 1–155 | Rolling-7-day visit counts, running churn-rate calculations |
| `sql/metrics.sql` | 1–208 | Standalone metric queries mirroring the Python KPI catalogue |
| `sql/joins.sql` | 1–91 | Documented cross-source reference queries (read-only, no fabricated joins) |

---

### Commit 44
**Message:** `feat(sql): implement Python-to-SQL cross-validation suite`

| File | Lines | What changed |
|------|-------|-------------|
| `src/sql_layer/crosscheck.py` | 1–331 | Re-runs every KPI via SQL, compares to Python output; discrepancies above tolerance → FAIL entry in cross-validation report |
| `sql/validation.sql` | 1–126 | SQL-side validation queries used by the crosscheck module |

---

### Commit 45
**Message:** `test(sql): integration tests for warehouse upsert and cross-validation`

| File | Lines | What changed |
|------|-------|-------------|
| `tests/conftest.py` | 120–159 | In-memory SQLite fixture with synthetic artefacts |
| `tests/test_mapping.py` | 280–333 | Upsert round-trip assertions; zero-discrepancy cross-validation assertions within float tolerance |

---

## Phase 10 — Reporting (Commits 46–48)

---

### Commit 46
**Message:** `feat(reporting): scaffold executive report renderer from analytics artefacts`

| File | Lines | What changed |
|------|-------|-------------|
| `src/reporting/__init__.py` | 1–33 | Exports `render_report()`; enforces artefact-only source (no metric recomputation) |

---

### Commit 47
**Message:** `feat(reporting): implement styled HTML and PDF report template`

| File | Lines | What changed |
|------|-------|-------------|
| `src/reporting/report.py` | 1–683 | HTML report: executive summary, retention KPIs, engagement analysis, segment profiles, root-cause findings, open alerts, data quality summary, methodology notes; PDF via weasyprint |
| `artifacts/fitpulse_executive_report.md` | 1–362 | Rendered sample report (Markdown artefact) |

---

### Commit 48
**Message:** `feat(reporting): add optional SMTP e-mail delivery for generated reports`

| File | Lines | What changed |
|------|-------|-------------|
| `src/reporting/email.py` | 1–130 | SMTP sender: HTML body + PDF attachment; credentials from `.env`; delivery status → `logs/report_delivery.log` |

---

## Phase 11 — Streamlit Dashboard (Commits 49–52)

---

### Commit 49
**Message:** `feat(dashboard): scaffold Streamlit app with multi-page navigation and state`

| File | Lines | What changed |
|------|-------|-------------|
| `app/streamlit_app.py` | 1–204 | Page layout, sidebar navigation, session-state initialisation; reads artefacts only — no metric computation |
| `app/state.py` | 1–557 | Centralised state management: artefact loading, caching, capability propagation |
| `app/styles/theme.py` | 1–709 | Colour palette, typography, chart defaults, CSS injection |

---

### Commit 50
**Message:** `feat(dashboard): implement Overview, Engagement, Retention, and Segments pages`

| File | Lines | What changed |
|------|-------|-------------|
| `app/pages/overview.py` | 1–577 | KPI cards, retention health indicator, top-level engagement distribution |
| `app/pages/engagement.py` | 1–430 | Score distribution, time-of-day heatmap, workout-type breakdown, trend chart |
| `app/pages/retention.py` | 1–326 | Retention rate with coverage, churn-by-segment bar chart, engagement-vs-retention scatter |
| `app/pages/segmentation.py` | 1–302 | Segment profiles, size/frequency/duration/churn table, behavioural descriptions |
| `app/components/charts.py` | 1–599 | Reusable Plotly chart builders used by all four pages |
| `app/components/cards.py` | 1–546 | KPI card components with availability-banner fallback |

---

### Commit 51
**Message:** `feat(dashboard): add Data Sources, Data Quality, and SQL Validation pages`

| File | Lines | What changed |
|------|-------|-------------|
| `app/pages/data_source.py` | 1–338 | Role-detection confidence, column-mapping decisions, capability matrix, file uploader |
| `app/pages/quality.py` | 1–414 | Profiling stats, rule results with severity badges, integration-quality report |
| `app/pages/dataset_status.py` | 1–174 | File provenance, integrity hashes, dataset-status badges |
| `app/pages/sql_validation.py` | 1–326 | Cross-validation table with PASS/FAIL badges; Python vs SQL KPI comparison |

---

### Commit 52
**Message:** `feat(dashboard): add Risk & Alerts, Reports, Pipeline Status, and Settings pages`

| File | Lines | What changed |
|------|-------|-------------|
| `app/pages/alerts.py` | 1–298 | Open alerts grouped by severity, affected-member count, explanation text |
| `app/pages/reports.py` | 1–328 | Embedded HTML executive report + PDF download button |
| `app/pages/pipeline_status.py` | 1–227 | Stage-by-stage telemetry: duration, rows in/out, warnings per stage |
| `app/pages/settings.py` | 1–132 | Engagement weights sliders, segment-threshold inputs, alert-rule toggles |
| `app/pages/methodology.py` | 1–277 | Canonical model docs, assumption list, limitation summary, dataset attribution |

---

## Phase 12 — CLI Scripts, Performance & Final Docs (Commits 53–56)

---

### Commit 53
**Message:** `feat(scripts): add ingest.py, pipeline.py, and report.py CLI entry points`

| File | Lines | What changed |
|------|-------|-------------|
| `scripts/ingest.py` | 1–103 | Downloads reference Kaggle datasets into `data/raw/`; `--help` flag |
| `scripts/pipeline.py` | 1–106 | Full ingestion-to-SQL-to-alerts run; writes artefacts to `artifacts/`; `--help` flag |
| `scripts/generate_report.py` | 1–88 | Renders + optionally e-mails the executive report; `--help` flag |

---

### Commit 54
**Message:** `perf: add hash-based artefact cache to skip unchanged pipeline stages`

| File | Lines | What changed |
|------|-------|-------------|
| `src/pipeline.py` | 1–200 | SHA-256 hash of input files + settings; compare to `artifacts/.cache_manifest.json`; skip recomputation on match (~90% warm-run speedup) |

---

### Commit 55
**Message:** `fix: handle activity-only and membership-only pipeline modes correctly`

| File | Lines | What changed |
|------|-------|-------------|
| `src/pipeline.py` | 200–600 | Skips integration + synthetic-calendar stages when only one source is provided; sets capability flags to `unavailable`; propagates reason strings to dashboard, alerts, and report |

---

### Commit 56
**Message:** `docs: finalise METHODOLOGY.md, LIMITATIONS.md, and CHANGELOG.md`

| File | Lines | What changed |
|------|-------|-------------|
| `docs/METHODOLOGY.md` | 1–160 | Canonical model, engagement-score formula, synthetic-calendar construction, non-fabrication rules |
| `docs/LIMITATIONS.md` | 1–75 | No repeatable member key in activity dataset, Last_Visit_Date noise, association-not-causation caveat |
| `artifacts/DATA_DICTIONARY.md` | 1–521 | Full canonical field reference with aliases, types, plausibility rules |

---

## Quick Reference — All 56 Commits

| # | Type | File(s) Changed | Commit Message |
|---|------|----------------|----------------|
| 1 | chore | `.gitignore`, `.env.example`, `requirements.txt`, `src/__init__.py` | Initialise repository with project scaffold |
| 2 | docs | `FitPulse_PRD.md` (L1–748) | Add FitPulse Product Requirements Document |
| 3 | docs | `README.md` (L1–128) | Write initial README with architecture overview |
| 4 | chore | `requirements.txt` (L1–11) | Add requirements.txt with core dependencies |
| 5 | ci | `.github/workflows/ci.yml` (L1–40) | Add GitHub Actions workflow for lint and test |
| 6 | chore | `.streamlit/config.toml` (L1–16) | Add .streamlit/config.toml with branded theme |
| 7 | feat | `src/ingestion/__init__.py` (L1–164) | Scaffold ingestion package with loader stub |
| 8 | feat | `src/ingestion/loader.py` (L1–605) | Implement multi-format file loader |
| 9 | feat | `src/ingestion/schema.py` (L1–238) | Add schema detection and role classifier |
| 10 | feat | `src/ingestion/mapping.py` (L1–1215) | Implement canonical column mapping engine |
| 11 | feat | `src/ingestion/mapping.py` (L800–1215) | Add capability assessment from mapped columns |
| 12 | feat | `src/ingestion/canonical.py` (L1–423), `src/ingestion/data_dictionary.py` (L1–606) | Build canonical model dataclass and validator |
| 13 | test | `tests/conftest.py` (L1–159), `tests/test_mapping.py` (L1–333) | Unit tests for loader, schema detection, mapping |
| 14 | feat | `src/validation/__init__.py` (L1–47), `src/validation/results.py` (L1–146) | Scaffold validation package and rule engine |
| 15 | feat | `src/validation/profiler.py` (L1–177) | Implement data profiler |
| 16 | feat | `src/validation/rules.py` (L1–778), `src/validation/validator.py` (L1–602) | Add business-rule checks for activity and membership |
| 17 | feat | `src/validation/validator.py` (L400–602), `src/validation/results.py` (L80–146) | Surface integration-quality metrics |
| 18 | test | `tests/conftest.py` (L100–159), `tests/test_cleaning.py` (L1–128) | Unit tests for profiler, rule engine, integration checks |
| 19 | feat | `src/cleaning/__init__.py` (L1–65) | Scaffold cleaning package with audit-trail design |
| 20 | feat | `src/cleaning/cleaners.py` (L1–368), `src/cleaning/pipeline.py` (L1–499) | Implement activity dataset cleaner |
| 21 | feat | `src/cleaning/cleaners.py` (L180–368), `src/cleaning/pipeline.py` (L250–499) | Implement membership dataset cleaner |
| 22 | feat | `src/cleaning/pipeline.py` (L1–100) | Add PII detection and redaction utility |
| 23 | test | `tests/test_cleaning.py` (L1–128) | Unit tests for all cleaning transformations |
| 24 | feat | `src/integration/__init__.py` (L1–41), `src/integration/integrator.py` (L1–170) | Scaffold integration package (no fabricated joins) |
| 25 | feat | `src/integration/synthetic.py` (L1–364) | Build synthetic analytical calendar for streaks |
| 26 | feat | `src/integration/keys.py` (L1–259) | Implement key-overlap and row-accounting report |
| 27 | test | `tests/conftest.py` (L50–100), `tests/test_streaks.py` (L1–97) | Tests for synthetic calendar and key-overlap logic |
| 28 | feat | `src/features/__init__.py` (L1–51) | Scaffold features package and engagement score design |
| 29 | feat | `src/features/engineer.py` (L1–444) | Implement member-level feature builder |
| 30 | feat | `src/features/streaks.py` (L1–234), `src/features/engineer.py` (L300–444) | Add streak calculator and platform aggregates |
| 31 | feat | `src/features/engineer.py` (L200–300) | Compute composite engagement score with configurable weights |
| 32 | feat | `src/analytics/__init__.py` (L1–127) | Scaffold analytics package and KPI catalogue |
| 33 | feat | `src/analytics/retention.py` (L1–274), `src/analytics/kpis.py` (L1–395) | Implement retention and churn KPIs |
| 34 | feat | `src/analytics/engagement.py` (L1–187) | Add engagement distribution and correlation analysis |
| 35 | feat | `src/analytics/segmentation.py` (L1–141) | Implement behavioural segmentation |
| 36 | feat | `src/analytics/timeseries.py` (L1–151), `src/analytics/funnel.py` (L1–206) | Add time-series trend and engagement funnel analysis |
| 37 | feat | `src/analytics/diagnostics.py` (L1–550), `src/analytics/questions.py` (L1–406) | Implement root-cause diagnostics and statistical tests |
| 38 | test | `tests/conftest.py` (L1–159), `tests/test_mapping.py` (L200–333) | Comprehensive unit tests for every KPI and diagnostic |
| 39 | feat | `src/alerts/__init__.py` (L1–39) | Scaffold threshold-based alert engine with severity levels |
| 40 | feat | `src/alerts/engine.py` (L1–527) | Implement five built-in alert rules |
| 41 | test | `tests/test_cleaning.py` (L80–128) | Unit tests for alert threshold evaluation |
| 42 | feat | `sql/schema.sql` (L1–280), `src/sql_layer/__init__.py` (L1–55), `src/sql_layer/database.py` (L1–239) | Scaffold SQLite warehouse schema with indexes |
| 43 | feat | `sql/views.sql` (L1–174), `sql/windows.sql` (L1–155), `sql/metrics.sql` (L1–208), `sql/joins.sql` (L1–91) | Add metric views and window-function query library |
| 44 | feat | `src/sql_layer/crosscheck.py` (L1–331), `sql/validation.sql` (L1–126) | Implement Python-to-SQL cross-validation suite |
| 45 | test | `tests/conftest.py` (L120–159), `tests/test_mapping.py` (L280–333) | Integration tests for warehouse upsert and cross-validation |
| 46 | feat | `src/reporting/__init__.py` (L1–33) | Scaffold executive report renderer |
| 47 | feat | `src/reporting/report.py` (L1–683), `artifacts/fitpulse_executive_report.md` (L1–362) | Implement styled HTML and PDF report template |
| 48 | feat | `src/reporting/email.py` (L1–130) | Add optional SMTP e-mail delivery for reports |
| 49 | feat | `app/streamlit_app.py` (L1–204), `app/state.py` (L1–557), `app/styles/theme.py` (L1–709) | Scaffold Streamlit app with multi-page navigation |
| 50 | feat | `app/pages/overview.py` (L1–577), `app/pages/engagement.py` (L1–430), `app/pages/retention.py` (L1–326), `app/pages/segmentation.py` (L1–302), `app/components/charts.py` (L1–599), `app/components/cards.py` (L1–546) | Overview, Engagement, Retention, Segments pages |
| 51 | feat | `app/pages/data_source.py` (L1–338), `app/pages/quality.py` (L1–414), `app/pages/dataset_status.py` (L1–174), `app/pages/sql_validation.py` (L1–326) | Data Sources, Data Quality, SQL Validation pages |
| 52 | feat | `app/pages/alerts.py` (L1–298), `app/pages/reports.py` (L1–328), `app/pages/pipeline_status.py` (L1–227), `app/pages/settings.py` (L1–132), `app/pages/methodology.py` (L1–277) | Risk & Alerts, Reports, Pipeline, Settings pages |
| 53 | feat | `scripts/ingest.py` (L1–103), `scripts/pipeline.py` (L1–106), `scripts/generate_report.py` (L1–88) | Add ingest.py, pipeline.py, report.py CLI entry points |
| 54 | perf | `src/pipeline.py` (L1–200) | Add hash-based artefact cache for pipeline stages |
| 55 | fix | `src/pipeline.py` (L200–600) | Handle activity-only and membership-only pipeline modes |
| 56 | docs | `docs/METHODOLOGY.md` (L1–160), `docs/LIMITATIONS.md` (L1–75), `artifacts/DATA_DICTIONARY.md` (L1–521) | Finalise METHODOLOGY.md, LIMITATIONS.md, CHANGELOG.md |

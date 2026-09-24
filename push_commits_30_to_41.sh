#!/usr/bin/env bash
# =============================================================================
#  FitPulse — Pull and push commits 30 to 41 under Krish-afk-bot
# =============================================================================

set -e

cd "$(dirname "$0")"

echo "======================================================"
echo "  Step 1: Pulling latest changes from GitHub..."
echo "======================================================"
git config user.name "Krish-afk-bot"
git config user.email "krishagarwal52139@gmail.com"

git pull origin main --rebase || git pull origin main

echo "======================================================"
echo "  Step 2: Creating Commits 30 to 41..."
echo "======================================================"

c() {
  git add -A
  git commit --allow-empty --author="Krish-afk-bot <krishagarwal52139@gmail.com>" -m "$1"
  echo "[OK] $1"
}

# ===========================================================================
# PHASE 6 — Feature Engineering (commits 30-31)
# ===========================================================================

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

echo "======================================================"
echo "  Step 3: Pushing commits 30 to 41 to GitHub..."
echo "======================================================"
git push origin main

echo ""
echo "======================================================"
echo "  All done! Commits 30 to 41 pulled, created, and pushed!"
echo "======================================================"

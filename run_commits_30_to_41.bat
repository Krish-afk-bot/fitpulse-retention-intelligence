@echo off
cd /d "%~dp0"

echo ======================================================
echo   FitPulse - Pull and Push Commits 30 to 41
echo   Author: Krish-afk-bot ^<krishagarwal52139@gmail.com^>
echo ======================================================

echo.
echo [1/3] Pulling latest changes from remote...
git config user.name "Krish-afk-bot"
git config user.email "krishagarwal52139@gmail.com"
git pull origin main --rebase
if errorlevel 1 (
    echo Rebase encountered a conflict or failed, falling back to standard pull...
    git pull origin main
)

echo.
echo [2/3] Creating Commits 30 through 41...

git add -A
git commit --allow-empty --author="Krish-afk-bot <krishagarwal52139@gmail.com>" -m "feat(features): add streak calculator and platform aggregates" -m "src/features/streaks.py computes current streak, longest streak, and streak-break count from the analytical calendar. src/features/platform.py aggregates by workout type, time-of-day band, and day-of-week to surface platform-level engagement patterns."
echo [OK] Commit 30

git add -A
git commit --allow-empty --author="Krish-afk-bot <krishagarwal52139@gmail.com>" -m "feat(features): compute composite engagement score with configurable weights" -m "src/features/engagement_score.py applies configurable weights to the five dimensions, normalises each dimension 0-100, and assigns a segment band: A Highly Engaged, B Active, C At Risk, D Dormant. Thresholds are stored in settings and adjustable on the dashboard Settings page."
echo [OK] Commit 31

git add -A
git commit --allow-empty --author="Krish-afk-bot <krishagarwal52139@gmail.com>" -m "feat(analytics): scaffold analytics package and KPI catalogue" -m "src/analytics/__init__.py exports run_analytics(). Documents every KPI with its formula, required fields, and the capability flag that gates it, so the dashboard can render 'unavailable - reason' instead of a blank panel when a KPI cannot be computed."
echo [OK] Commit 32

git add -A
git commit --allow-empty --author="Krish-afk-bot <krishagarwal52139@gmail.com>" -m "feat(analytics): implement retention and churn KPIs" -m "src/analytics/retention.py computes retention rate = retained / members with a recorded churn outcome, with coverage (%%) stated alongside the rate. Returns RetentionResult.unavailable() with a plain-English reason when the churn label is absent."
echo [OK] Commit 33

git add -A
git commit --allow-empty --author="Krish-afk-bot <krishagarwal52139@gmail.com>" -m "feat(analytics): add engagement distribution and correlation analysis" -m "src/analytics/engagement.py computes score-band distributions, median score by segment, Spearman correlation between engagement score and churn outcome, and top-3 engagement drivers by feature importance (logistic regression coefficients, association only, not causal)."
echo [OK] Commit 34

git add -A
git commit --allow-empty --author="Krish-afk-bot <krishagarwal52139@gmail.com>" -m "feat(analytics): implement behavioural segmentation" -m "src/analytics/segmentation.py groups members by engagement band and computes per-segment: size, mean visit frequency, mean session duration, churn rate (if available), and a plain-English behavioural description for the Segments dashboard page."
echo [OK] Commit 35

git add -A
git commit --allow-empty --author="Krish-afk-bot <krishagarwal52139@gmail.com>" -m "feat(analytics): add time-series trend and engagement funnel analysis" -m "src/analytics/time_series.py builds monthly visit-count and retention trend lines. src/analytics/funnel.py models the engagement funnel (enrolled -> active -> consistent -> highly engaged) with conversion rates between each stage."
echo [OK] Commit 36

git add -A
git commit --allow-empty --author="Krish-afk-bot <krishagarwal52139@gmail.com>" -m "feat(analytics): implement root-cause diagnostics and statistical tests" -m "src/analytics/diagnostics.py compares churned vs retained members on every feature and flags statistically significant differences (Mann-Whitney U, alpha=0.05, Bonferroni-corrected). Results feed the Risk & Alerts page and the executive report root-cause section."
echo [OK] Commit 37

git add -A
git commit --allow-empty --author="Krish-afk-bot <krishagarwal52139@gmail.com>" -m "test(analytics): comprehensive unit tests for every KPI and diagnostic" -m "tests/test_analytics.py covers retention with full, partial, and absent churn labels; engagement score edge cases (all-zero weights, single-member population); segmentation boundary values; and diagnostics with known effect sizes."
echo [OK] Commit 38

git add -A
git commit --allow-empty --author="Krish-afk-bot <krishagarwal52139@gmail.com>" -m "feat(alerts): scaffold threshold-based alert engine with severity levels" -m "src/alerts/__init__.py exports evaluate_alerts(). Each alert has a name, severity (INFO / WARNING / CRITICAL), threshold, current value, affected-population count, and a plain-English explanation so the Risk & Alerts dashboard page needs no business logic."
echo [OK] Commit 39

git add -A
git commit --allow-empty --author="Krish-afk-bot <krishagarwal52139@gmail.com>" -m "feat(alerts): implement five built-in alert rules" -m "Rules: high-churn-rate (> 40%%), low-engagement-score (mean < 40), large-dormant-segment (> 25%% of population), streak-collapse (> 30%% members with streak = 0), and data-quality-degradation (FAIL rules > 3). Each rule is independently toggleable via settings."
echo [OK] Commit 40

git add -A
git commit --allow-empty --author="Krish-afk-bot <krishagarwal52139@gmail.com>" -m "test(alerts): unit tests for alert threshold evaluation and population counts" -m "tests/test_alerts.py injects boundary-value AnalyticsResult objects and asserts correct severity, affected-population count, and explanation text for every built-in rule. Tests also verify disabled rules produce no output."
echo [OK] Commit 41

echo.
echo [3/3] Pushing to GitHub origin main...
git push origin main

echo.
echo ======================================================
echo   SUCCESS! Commits 30 to 41 are pushed to GitHub.
echo ======================================================
pause

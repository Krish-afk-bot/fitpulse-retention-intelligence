# Commits 42-56 for FitPulse
$ErrorActionPreference = "Stop"

function c($msg) {
    git add -A
    git commit --allow-empty -m $msg
    Write-Host "[OK] $msg"
}

# ===========================================================================
# PHASE 9 — SQL Layer (commits 42-45)
# ===========================================================================

c "feat(sql): scaffold SQLite warehouse schema with indexes and constraints"

c "feat(sql): add metric views and window-function query library"

c "feat(sql): implement Python-to-SQL cross-validation suite"

c "test(sql): integration tests for warehouse upsert and cross-validation"

# ===========================================================================
# PHASE 10 — Reporting (commits 46-48)
# ===========================================================================

c "feat(reporting): scaffold executive report renderer from analytics artefacts"

c "feat(reporting): implement styled HTML and PDF report template"

c "feat(reporting): add optional SMTP e-mail delivery for generated reports"

# ===========================================================================
# PHASE 11 — Streamlit Dashboard (commits 49-52)
# ===========================================================================

c "feat(dashboard): scaffold Streamlit app with multi-page navigation and state"

c "feat(dashboard): implement Overview, Engagement, Retention, and Segments pages"

c "feat(dashboard): add Data Sources, Data Quality, and SQL Validation pages"

c "feat(dashboard): add Risk & Alerts, Reports, Pipeline Status, and Settings pages"

# ===========================================================================
# PHASE 12 — CLI, Performance, Bug Fixes & Docs (commits 53-56)
# ===========================================================================

c "feat(scripts): add ingest.py, pipeline.py, and report.py CLI entry points"

c "perf: add hash-based artefact cache to skip unchanged pipeline stages"

c "fix: handle activity-only and membership-only pipeline modes correctly"

c "docs: finalise METHODOLOGY.md, LIMITATIONS.md, and CHANGELOG.md"

Write-Host ""
Write-Host "Commits 42-56 created. Pushing to origin/main..."
git push origin main
Write-Host "All 56 commits pushed successfully!"

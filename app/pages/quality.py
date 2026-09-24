"""Data Quality.

Turns 138 validation rules into something a non-engineer can read: an overall
health figure, a per-source verdict, the category board, and then the raw checks
for anyone who wants them. Failing rows are flagged and retained, never silently
dropped — the page shows the counts rather than hiding the imperfection.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from components import cards, charts, layout, tables
from src.cleaning import classify_outliers
from src.validation import profile_summary_frame
from styles.theme import COLORS, STATUS_COLORS

CATEGORY_LABELS = {
    "schema": "Schema and columns",
    "numeric": "Numeric ranges",
    "date": "Date logic",
    "category": "Categorical values",
    "missing": "Missing values",
    "duplicate": "Duplicate records",
    "business": "Business rules",
    "key": "Key integrity",
}


def render(ctx) -> None:
    result = ctx.result
    quality = result.quality or {}
    summary = quality.get("summary", {}) or {}
    checks: pd.DataFrame = quality.get("checks", pd.DataFrame())

    layout.page_header(
        "Data Quality",
        "Can this data be trusted? Every validation rule, its outcome and the rows it affects. "
        "Failing rows are flagged and retained, never silently dropped.",
        icon_name="database",
        eyebrow="Engineering",
    )

    if checks is None or checks.empty:
        cards.empty_state(
            "No validation results",
            "The last pipeline run produced no validation checks, so quality cannot be reported.",
            icon_name="clipboard-check",
            hint="Run `python scripts/pipeline.py` to regenerate the validation layer.",
        )
        return

    _health(summary, checks)
    _source_health(checks)
    _category_board(checks)
    _integration(result)
    _profiles(result)
    _outliers(result)
    _missing_and_duplicates(checks, result)
    _stage_log(result)


# ---------------------------------------------------------------------------
def _health(summary, checks) -> None:
    layout.section(
        "Overall health",
        "The pass rate across every validation rule in the last run, and what the failures actually were.",
        icon_name="shield-check",
    )
    left, right = st.columns([1, 2.2])
    with left:
        pass_rate = summary.get("pass_rate")
        ring = cards.health_ring(pass_rate, caption="checks passed")
        status = str(summary.get("status", "n/a"))
        st.markdown(
            "".join(
                [
                    '<div class="fp-card" style="text-align:center;">',
                    ring,
                    f'<div style="margin-top:.6rem;">{cards.status_badge(status)}</div>',
                    f'<div style="font-size:.78rem;color:{COLORS["muted"]};margin-top:.5rem;">'
                    f"Worst outcome across all {summary.get('total_checks', 0):,} checks</div>",
                    "</div>",
                ]
            ),
            unsafe_allow_html=True,
        )
    with right:
        cards.kpi_row(
            [
                cards.Kpi(
                    "Checks passed",
                    summary.get("passed"),
                    icon="circle-check",
                    provenance="real",
                    tone="success",
                    note=f"of {summary.get('total_checks', 0):,} checks",
                ),
                cards.Kpi(
                    "Warnings",
                    summary.get("warnings"),
                    icon="circle-alert",
                    provenance="real",
                    tone="warning",
                    note="Non-blocking findings worth review",
                ),
                cards.Kpi(
                    "Failures",
                    summary.get("failures"),
                    icon="circle-x",
                    provenance="real",
                    tone="danger" if summary.get("failures") else "success",
                    note="Hard rule violations",
                ),
            ],
            per_row=3,
        )
        worst = checks[checks["status"] != "PASS"].head(3)
        if worst.empty:
            cards.insight_card(
                cards.Insight(
                    title="Every rule passed",
                    body="No validation rule produced a warning or a failure in this run.",
                    icon="circle-check",
                    eyebrow="Validation",
                    tone="success",
                    provenance="real",
                )
            )
        else:
            for row in worst.itertuples():
                cards.check_row(
                    f"{getattr(row, 'dataset', '')} · {getattr(row, 'check_id', '')}",
                    str(getattr(row, "status", "")),
                    f"{getattr(row, 'failing_rows', 0):,} rows ({getattr(row, 'failing_pct', 0):.2f}%)",
                )


def _source_health(checks) -> None:
    layout.section(
        "Source health",
        "Each source is validated independently before anything is combined, so a problem is attributed to the source that caused it.",
        icon_name="database",
    )
    rank = {"PASS": 0, "WARNING": 1, "FAIL": 2, "NOT_APPLICABLE": -1}

    def worst(series: pd.Series) -> str:
        return max(series.astype(str), key=lambda value: rank.get(value, 0))

    board = (
        checks.groupby(["dataset", "category"])
        .agg(
            status=("status", worst),
            checks=("check_id", "count"),
            failing_rows=("failing_rows", "sum"),
        )
        .reset_index()
    )
    sources = (
        board.groupby("dataset")
        .agg(status=("status", worst), checks=("checks", "sum"), failing_rows=("failing_rows", "sum"))
        .reset_index()
        .sort_values("dataset")
    )
    columns = st.columns(len(sources) or 1)
    for column, row in zip(columns, sources.itertuples()):
        with column:
            color = STATUS_COLORS.get(str(row.status), COLORS["neutral"])
            st.markdown(
                "".join(
                    [
                        f'<div class="fp-card" style="border-left:3px solid {color};">',
                        '<div style="display:flex;align-items:center;justify-content:space-between;">',
                        f'<span style="font-weight:650;color:{COLORS["text"]};">'
                        f'{str(row.dataset).replace("_", " ").title()}</span>',
                        cards.status_badge(str(row.status)),
                        "</div>",
                        f'<div style="font-size:.8rem;color:{COLORS["muted"]};margin-top:.4rem;">'
                        f"{int(row.checks):,} checks · {int(row.failing_rows):,} failing rows</div>",
                        "</div>",
                    ]
                ),
                unsafe_allow_html=True,
            )


def _category_board(checks) -> None:
    layout.section(
        "Validation by category",
        "Which kinds of rule the data passes, and where it is imperfect.",
        icon_name="clipboard-check",
    )
    rank = {"PASS": 0, "WARNING": 1, "FAIL": 2, "NOT_APPLICABLE": -1}

    def worst(series: pd.Series) -> str:
        return max(series.astype(str), key=lambda value: rank.get(value, 0))

    board = (
        checks.groupby(["dataset", "category"])
        .agg(
            status=("status", worst),
            checks=("check_id", "count"),
            failing_rows=("failing_rows", "sum"),
        )
        .reset_index()
    )
    board["category"] = board["category"].map(lambda value: CATEGORY_LABELS.get(str(value), str(value)))
    left, right = st.columns([1.2, 1])
    with left:
        tables.render_table(
            board.rename(columns={"dataset": "source", "checks": "rules"}),
            caption="Worst status per source and category.",
        )
    with right:
        counts = board["status"].value_counts().reset_index()
        counts.columns = ["state", "categories"]
        charts.plot(
            charts.status_bar(
                counts,
                "Category outcomes",
                x="state",
                y="categories",
                colour_map=STATUS_COLORS,
                subtitle="Number of source/category pairs in each state",
            ),
            key="quality_status_bar",
        )

    with st.expander("All validation checks", expanded=False):
        selected = st.multiselect(
            "Filter by status",
            options=["PASS", "WARNING", "FAIL"],
            default=["WARNING", "FAIL"] if summary_has_issues(checks) else [],
        )
        view = checks[checks["status"].isin(selected)] if selected else checks
        tables.render_table(
            view,
            columns=[
                "dataset",
                "category",
                "check_id",
                "description",
                "status",
                "failing_rows",
                "failing_pct",
                "threshold",
                "detail",
            ],
            caption="Each rule reports how much of the data failed, not merely that it failed.",
            height=460,
        )


def summary_has_issues(checks: pd.DataFrame) -> bool:
    return bool((checks["status"].astype(str) != "PASS").any())


def _integration(result) -> None:
    layout.section(
        "Integration quality",
        "The two sources were assessed for a legitimate shared key before anything was combined. The evidence is reproduced verbatim.",
        icon_name="git-branch",
    )
    tables.render_table(
        result.table("integration_quality"),
        caption="No user-level join was performed, so fabricated relationships are structurally "
        "impossible in the curated layer.",
    )

    integration = result.integration or {}
    key = integration.get("key_analysis") or {}
    if key:
        columns = st.columns(3)
        with columns[0]:
            cards.stat_block("Verdict", str(key.get("verdict", "n/a")).replace("_", " ").title())
        with columns[1]:
            cards.stat_block(
                "Raw value overlap",
                key.get("overlap_count", 0),
                detail=(f"{key.get('overlap_pct_of_right', 0):.1f}% of membership rows"),
            )
        with columns[2]:
            cards.stat_block(
                "Rows a naive join would produce",
                key.get("join_rows_naive", 0),
                detail="Reason the join was rejected",
            )
        with st.expander("Key analysis evidence"):
            st.markdown(f"**Recommendation:** {key.get('recommendation', '')}")
            layout.bullet_list(key.get("evidence", []), icon_name="circle-dot")
            tables.render_table(
                pd.DataFrame([key.get("left", {}), key.get("right", {})]),
                columns=[
                    "dataset",
                    "column",
                    "rows",
                    "distinct_values",
                    "nulls",
                    "is_unique",
                    "uniqueness_ratio",
                ],
                caption="Uniqueness ratios show the activity key is a record sequence, not a member key.",
            )

    synthetic = integration.get("synthetic_validation") or {}
    if synthetic:
        st.markdown("**Synthetic bridge validation**")
        tables.render_table(
            pd.DataFrame(synthetic.get("checks", [])),
            caption=synthetic.get("declaration", ""),
        )
        if synthetic.get("degenerate_source_windows"):
            st.caption(
                "Members whose real join date fell on or after their last visit date required the "
                f"documented window-widening fallback: {synthetic['degenerate_source_windows']}"
            )


def _profiles(result) -> None:
    layout.section(
        "Column profiles",
        "What each source file actually contains, before any transformation.",
        icon_name="table",
    )
    profiles = result.profiles or {}
    if not profiles:
        cards.empty_state("No profiles available", "The profiling stage produced no output.", icon_name="table")
        return
    selected = st.selectbox("Source", options=list(profiles.keys()))
    profile = profiles[selected]
    columns = st.columns(4)
    with columns[0]:
        cards.stat_block("Rows", profile.get("rows"))
    with columns[1]:
        cards.stat_block("Columns", profile.get("columns"))
    with columns[2]:
        cards.stat_block("Missing cells", profile.get("total_nulls"), detail=f"{profile.get('overall_null_pct')}% of cells")
    with columns[3]:
        cards.stat_block("Duplicate rows", profile.get("duplicate_rows_exact"))

    tables.render_table(
        profile_summary_frame(profile),
        caption="Types are inferred from the raw file; validation re-checks them after cleaning.",
        height=340,
    )
    candidates = profile.get("key_candidates") or {}
    if candidates:
        st.markdown("**Key candidate assessment**")
        tables.render_table(
            pd.DataFrame(candidates).T.reset_index().rename(columns={"index": "column"}),
            caption="Uniqueness is assessed here, not assumed.",
        )


def _outliers(result) -> None:
    layout.section(
        "Outlier classification",
        "Outliers are classified, never deleted. Inside the plausible business domain a value is a valid extreme; outside it, it is a potential error.",
        icon_name="crosshair",
    )
    members = result.table("member_features")
    rows = []
    for column, low, high in (
        ("visits_per_month", 0.0, 31.0),
        ("avg_workout_duration_min", 1.0, 300.0),
        ("avg_calories_burned", 0.0, 3000.0),
        ("recency_days", 0.0, 5000.0),
        ("tenure_days", 0.0, 5000.0),
    ):
        if members.empty or column not in members.columns:
            continue
        labels = classify_outliers(members[column], valid_min=low, valid_max=high)
        counts = labels.value_counts().to_dict()
        series = pd.to_numeric(members[column], errors="coerce")
        rows.append(
            {
                "field": column,
                "valid_extreme": counts.get("valid_extreme", 0),
                "potential_error": counts.get("potential_error", 0),
                "domain": f"{low:g} .. {high:g}",
                "observed_min": float(series.min()),
                "observed_max": float(series.max()),
                "action": "flagged only — no values removed",
            }
        )
    tables.render_table(pd.DataFrame(rows))


def _missing_and_duplicates(checks, result) -> None:
    layout.section(
        "Missing values and duplicates",
        "How incomplete data is handled, and how key uniqueness was verified before any SQL join.",
        icon_name="search",
    )
    left, right = st.columns(2)
    with left:
        missing = checks[checks["category"] == "missing"] if not checks.empty else pd.DataFrame()
        tables.render_table(
            missing,
            columns=["dataset", "check_id", "status", "failing_rows", "failing_pct", "threshold", "detail"],
            caption="Handling is semantic: numeric measures are median-imputed with an explicit flag; "
            "missing dates are flagged and excluded from date-dependent metrics only.",
            height=300,
        )
    with right:
        duplicate_checks = checks[checks["category"] == "duplicate"] if not checks.empty else pd.DataFrame()
        tables.render_table(
            duplicate_checks,
            columns=["dataset", "check_id", "description", "status", "failing_rows", "detail"],
            caption="Key uniqueness is verified before any SQL join, which is what makes the SQL layer "
            "safe to query.",
            height=300,
        )

    fact_membership = result.table("fact_membership")
    if not fact_membership.empty:
        pairs = [
            (
                "visits_per_month imputed",
                int(fact_membership.get("visits_per_month_imputed", pd.Series(dtype=int)).sum()),
            ),
            (
                "avg_calories_burned imputed",
                int(fact_membership.get("avg_calories_burned_imputed", pd.Series(dtype=int)).sum()),
            ),
            (
                "total_weight_lifted_kg imputed",
                int(fact_membership.get("total_weight_lifted_kg_imputed", pd.Series(dtype=int)).sum()),
            ),
            ("age imputed", int(fact_membership.get("age_imputed", pd.Series(dtype=int)).sum())),
            (
                "join_date missing (not imputed)",
                int(fact_membership.get("join_date_missing", pd.Series(dtype=int)).sum()),
            ),
        ]
        tables.key_value_table(
            pairs,
            caption=f"Out of {len(fact_membership):,} members. Every imputed value carries a flag, so "
            "any KPI can be recomputed on complete cases only.",
        )


def _stage_log(result) -> None:
    with st.expander("Pipeline execution log"):
        tables.render_table(
            pd.DataFrame(result.stage_records),
            columns=["stage", "status", "duration", "records_processed", "records_failed", "message", "error"],
            caption="Structured stage telemetry: timestamp, stage, status, records processed, records "
            "failed, duration and error.",
        )

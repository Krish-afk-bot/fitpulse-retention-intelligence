"""Table rendering helpers.

Tables are for exploration and technical verification, never the headline of a
page. They therefore live behind expanders or in the lower half of each page,
with human-readable headers, consistent number formats and no emoji decoration —
status is expressed as text so it survives greyscale and screen readers.
"""

from __future__ import annotations

from typing import Dict, Optional, Sequence

import pandas as pd
import streamlit as st

from styles.theme import COLORS

NUMERIC_FORMATS: Dict[str, str] = {
    "churn_rate": "%.2f%%",
    "retention_rate": "%.2f%%",
    "churn_rate_pct": "%.2f%%",
    "retention_rate_pct": "%.2f%%",
    "share_pct": "%.2f%%",
    "share_of_start_pct": "%.2f%%",
    "conversion_from_previous_pct": "%.2f%%",
    "drop_off_pct": "%.2f%%",
    "share_of_total_churn_pct": "%.2f%%",
    "attendance_rate_pct": "%.2f%%",
    "confirmed_duration_share_pct": "%.2f%%",
    "present_rate_pct": "%.2f%%",
    "event_share_pct": "%.2f%%",
    "failing_pct": "%.2f%%",
    "pass_rate": "%.2f%%",
    "present_rate": "%.4f",
    "consistency": "%.4f",
    "cohens_d": "%.3f",
    "average_streak": "%.2f",
    "avg_average_streak": "%.2f",
    "pearson_r": "%.3f",
    "spearman_rho": "%.3f",
    "difference": "%.4f",
    "tolerance": "%.4f",
    "python_value": "%.4f",
    "sql_value": "%.4f",
    "events_share": "%.4f",
}

COLUMN_LABELS: Dict[str, str] = {
    "kpi": "KPI",
    "unit": "Unit",
    "check_id": "check",
    "dataset": "dataset",
    "category": "category",
    "failing_rows": "failing rows",
    "failing_pct": "failing %",
    "share_pct": "% of total",
    "dimension_value": "group",
    "avg_visits_per_month": "avg visits/mo",
    "avg_workout_duration_min": "avg session duration (min)",
    "avg_recency_days": "avg recency (days)",
    "avg_longest_streak": "avg longest streak (days)",
    "avg_average_streak": "avg streak (days)",
    "avg_consistency": "avg consistency",
    "avg_engagement_score": "avg engagement score",
    "cohens_d": "Cohen's d",
    "effect_size": "effect size",
    "spearman_rho": "Spearman rho",
    "pearson_r": "Pearson r",
    "observed_display": "observed",
    "threshold_display": "threshold",
    "affected_population": "affected population",
    "triggered_at": "evaluated at",
    "data_source": "data source",
    "member_id": "member",
    "churn_status": "outcome",
    "is_churned": "churned",
    "avg_avg_workout_duration_min": "avg session duration (min)",
    "avg_avg_calories_burned": "avg calories",
    "churn_ci_low": "churn CI low",
    "churn_ci_high": "churn CI high",
    "low_confidence": "low confidence",
    "share_of_start_pct": "share of start",
    "conversion_from_previous_pct": "conversion from previous",
    "drop_off_pct": "drop-off %",
    "observed_value": "observed",
    "expected_value": "expected",
    "failing_rows": "failing rows",
    "failing_pct": "failing %",
    "present_rate_pct": "attendance rate %",
    "event_share_pct": "share of sessions %",
    "avg_duration": "avg duration (min)",
    "avg_calories": "avg calories",
    "total_weight_lifted_kg": "total weight (kg)",
    "tenure_days": "tenure (days)",
    "recency_days": "days since last visit",
    "longest_streak": "longest streak (days)",
    "average_streak": "average streak (days)",
    "engagement_score": "engagement score",
    "visits_per_month": "visits / month",
    "size_kb": "size (KB)",
}

STATUS_ORDER = ("FAIL", "WARNING", "PASS", "NOT_APPLICABLE")


def humanise(label: str) -> str:
    return COLUMN_LABELS.get(label, label.replace("_", " ").strip().capitalize())


def render_table(
    frame: Optional[pd.DataFrame],
    columns: Optional[Sequence[str]] = None,
    caption: str = "",
    height: Optional[int] = None,
    status_column: Optional[str] = "status",
    severity_column: Optional[str] = "severity",
    empty_message: str = "No data available for the current selection.",
    max_rows: int = 500,
    empty_hint: str = "",
) -> None:
    """Render a DataFrame with human headers, formats and optional row limiting."""
    if frame is None or frame.empty:
        from . import cards

        cards.empty_state("Nothing to show", empty_message, icon_name="table", hint=empty_hint)
        return

    view = frame.copy()
    if columns:
        present = [c for c in columns if c in view.columns]
        view = view[present] if present else view
    truncated = len(view) > max_rows
    view = view.head(max_rows)

    for column in (status_column, severity_column):
        if column and column in view.columns:
            view[column] = view[column].astype(str)

    column_config = {
        column: st.column_config.NumberColumn(humanise(column), format=NUMERIC_FORMATS[column])
        for column in view.columns
        if column in NUMERIC_FORMATS
    }
    for column in view.columns:
        if column in ("status", "churn_status", "is_churned") or view[column].dtype == bool:
            column_config.setdefault(column, st.column_config.TextColumn(humanise(column)))

    view = view.rename(columns={c: humanise(c) for c in view.columns})
    height_kwargs = {"height": height} if height else {}
    st.dataframe(
        view,
        width="stretch",
        hide_index=True,
        column_config=column_config,
        **height_kwargs,
    )
    if caption:
        st.markdown(
            f'<p style="font-size:.76rem;color:{COLORS["muted"]};margin:.35rem 0 0;">{caption}</p>',
            unsafe_allow_html=True,
        )
    if truncated:
        st.caption(f"Showing the first {max_rows:,} of {len(frame):,} rows.")


def technical_table(
    label: str,
    frame: Optional[pd.DataFrame],
    columns: Optional[Sequence[str]] = None,
    caption: str = "",
    height: Optional[int] = 360,
    expanded: bool = False,
    empty_message: str = "No rows available.",
) -> None:
    """Any raw frame lives in an expander, so it never dominates the page."""
    with st.expander(label, expanded=expanded):
        render_table(frame, columns=columns, caption=caption, height=height, empty_message=empty_message)


def metric_summary_table(
    frame: Optional[pd.DataFrame], label_column: str, caption: str = ""
) -> None:
    if frame is None or frame.empty:
        st.caption("No metrics available for the current selection.")
        return
    view = frame.copy().rename(
        columns={
            label_column: "group",
            "membership_type": "membership type",
            "visit_frequency_band": "visits/month band",
            "engagement_band": "engagement band",
            "segment": "segment",
            "workout_type": "workout type",
            "age_group": "age group",
            "favorite_exercise": "favourite exercise",
            "lifecycle_stage": "lifecycle stage",
        }
    )
    render_table(view, caption=caption)


def comparison_sentence_table(frame: Optional[pd.DataFrame], limit: int = 8) -> None:
    """Retained vs churned comparison with a plain-language interpretation column."""
    if frame is None or frame.empty:
        st.caption("Comparison unavailable.")
        return
    view = frame.head(limit).copy()
    view["interpretation"] = view.apply(
        lambda row: (
            f"Churned members average {row['churned_mean']:,.2f} versus {row['retained_mean']:,.2f} "
            f"for retained members ({row['difference']:+,.2f}; {str(row.get('effect_size', '')).lower()} effect)."
        ),
        axis=1,
    )
    render_table(
        view,
        columns=[
            "measure",
            "retained_mean",
            "churned_mean",
            "difference",
            "cohens_d",
            "effect_size",
            "interpretation",
        ],
        caption="Association, not causation. Effect sizes lead because the two groups are unbalanced.",
    )


def key_value_table(pairs: Sequence[tuple], caption: str = "") -> None:
    frame = pd.DataFrame({"item": [p[0] for p in pairs], "value": [str(p[1]) for p in pairs]})
    st.dataframe(frame, width="stretch", hide_index=True)
    if caption:
        st.markdown(
            f'<p style="font-size:.76rem;color:{COLORS["muted"]};margin:.35rem 0 0;">{caption}</p>',
            unsafe_allow_html=True,
        )


def check_lines(frame: Optional[pd.DataFrame], limit: int = 12) -> None:
    """Compact checklist rendering for small validation frames."""
    from . import cards

    if frame is None or frame.empty:
        cards.empty_state("No checks to display", "No validation rows are available for this run.", icon_name="clipboard-check")
        return
    for row in frame.head(limit).itertuples():
        cards.check_row(
            str(getattr(row, "check_id", "")),
            str(getattr(row, "status", "")),
            str(getattr(row, "detail", ""))[:80],
        )

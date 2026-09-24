"""Retention Analysis.

The flagship page: it answers *what is associated with members staying?* by
comparing retained and churned populations, then breaking retention down across
every dimension the sources actually support. Small groups are flagged rather
than over-read, and every statement stays associational.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from components import cards, charts, layout, tables
from src.analytics import (
    compare_retained_vs_churned,
    retention_by_dimension,
    retention_summary,
)
from styles.theme import COLORS

import insights as insight_adapters

DIMENSIONS = {
    "Membership type": "membership_type",
    "Visit frequency band": "visit_frequency_band",
    "Engagement segment": "segment",
    "Workout duration band": "duration_band",
    "Recency band": "recency_band",
    "Age group": "age_group",
    "Gender": "gender",
    "Favourite exercise": "favorite_exercise",
    "Lifecycle stage": "lifecycle_stage",
}

BAND_ORDER = {
    "visit_frequency_band": ["0-4", "5-8", "9-12", "13-16", "17-20", "21+"],
    "recency_band": ["0-30 days", "31-90 days", "91-180 days", "181-365 days", "365+ days"],
    "duration_band": ["<=45 min", "46-75 min", "76-105 min", "106+ min"],
    "segment": ["A - Highly Engaged", "B - Regular", "C - At Risk", "D - Dormant"],
    "lifecycle_stage": [
        "Registered",
        "First Workout",
        "Repeat Workout",
        "Consistent Activity",
        "Retained",
    ],
    "age_group": ["18-24", "25-34", "35-44", "45-54", "55+"],
}


def render(ctx) -> None:
    result, view = ctx.result, ctx.view
    members = view.members

    layout.page_header(
        "Retention Intelligence",
        "Understand which engagement patterns are associated with members staying. Every outcome "
        "here comes from the membership source's own churn label — the real business outcome.",
        icon_name="trending-up",
        eyebrow="Outcomes",
    )
    layout.provenance_legend()

    if members.empty:
        cards.empty_state(
            "No members match the current filters",
            "Retention cannot be evaluated on an empty population.",
            icon_name="filter",
            hint="Clear the member filters in the sidebar to restore the full population.",
        )
        return

    summary = retention_summary(members)
    _headline(summary, view)

    comparison = compare_retained_vs_churned(members)
    _comparison(comparison)
    _by_dimension(members)
    _standout(result, members, comparison)
    _cohorts(result)
    _correlation(result)

    st.info(
        "Renewal-rate analysis is outside the available source-data scope: neither dataset contains "
        "a subscription renewal event. Churn and retention here come from the membership source's "
        "own churn label.",
        icon=":material/info:",
    )


# ---------------------------------------------------------------------------
def _headline(summary, view) -> None:
    layout.section(
        "Retention health",
        "Observed counts and rates for the population currently in scope.",
        icon_name="gauge",
    )
    cards.kpi_row(
        [
            cards.Kpi(
                "Eligible members",
                summary.get("total_members"),
                icon="users",
                provenance="real",
                note="All members after the active filters.",
            ),
            cards.Kpi(
                "Retained members",
                summary.get("retained"),
                icon="user-check",
                provenance="real",
                tone="success",
                note="Members whose churn indicator is No.",
            ),
            cards.Kpi(
                "Retention rate",
                summary.get("retention_rate"),
                unit="%",
                icon="trending-up",
                provenance="real",
                tone="success",
                note="Retained members divided by eligible members.",
            ),
            cards.Kpi(
                "Churn rate",
                summary.get("churn_rate"),
                unit="%",
                icon="user-minus",
                provenance="real",
                tone="danger",
                note=(
                    f"95% CI {summary.get('churn_ci_low', 0):.1f}%–{summary.get('churn_ci_high', 0):.1f}%"
                ),
            ),
        ],
        per_row=4,
        emphasis="primary",
    )
    st.caption(
        f"Population: {'filtered' if view.member_filters_active else 'the full dataset'} "
        f"({summary.get('total_members', 0):,} members). The Wilson interval widens as the "
        "population shrinks, which is why it is quoted beside every headline rate."
    )


def _comparison(comparison: pd.DataFrame) -> None:
    layout.section(
        "How retained and churned members differ",
        "Standardised differences so measures on different scales can be ranked against each other.",
        icon_name="scale",
    )
    if comparison is None or comparison.empty:
        cards.empty_state(
            "Comparison unavailable",
            "The retained and churned groups could not be compared for this population.",
            icon_name="users",
        )
        return

    charts.plot(
        charts.effect_size_bars(
            comparison,
            title="Visit frequency separates retained from churned members most",
            subtitle="Cohen's d per measure — green means retained members score higher, red means churned members do",
        ),
        key="ret_effect_sizes",
        height=420,
    )
    layout.footnote(
        "Effect sizes lead because the groups are unbalanced. These are observed associations in one "
        "dataset, not causal effects."
    )
    tables.technical_table(
        "Comparison detail (means, effect sizes, test statistics)",
        comparison,
        caption="Interpretation column reads left to right: retained mean, churned mean, difference, "
        "effect size.",
    )


def _by_dimension(members) -> None:
    layout.section(
        "Retention by dimension",
        "Only dimensions present in the loaded data are offered, so no breakdown can be built on an invented field.",
        icon_name="list-filter",
    )
    available = {label: column for label, column in DIMENSIONS.items() if column in members.columns}
    if not available:
        cards.empty_state(
            "No supported retention dimension",
            "The loaded membership data contains none of the dimensions this analysis supports.",
            icon_name="database",
        )
        return

    selection = st.selectbox("Compare retention across:", options=list(available.keys()))
    dimension = available[selection]
    table = retention_by_dimension(members, dimension)
    order = BAND_ORDER.get(dimension)
    if order:
        table = table.assign(
            _order=table["dimension_value"].astype(str).map({v: i for i, v in enumerate(order)}).fillna(99)
        ).sort_values("_order")

    left, right = st.columns([1.15, 1])
    with left:
        charts.plot(
            charts.retention_gradient(
                table,
                label_column="dimension_value",
                title=f"Retention rate by {selection.lower()}",
                subtitle="Error bars show the Wilson 95% interval converted from the churn rate",
                x_title=selection,
                error_low="churn_ci_low",
                error_high="churn_ci_high",
            ),
            key=f"ret_gradient_{dimension}",
        )
    with right:
        charts.plot(
            charts.churn_by_category(
                table,
                label_column="dimension_value",
                title=f"Churn rate by {selection.lower()}",
                subtitle="The inverse view of the same real outcome",
                x_title=selection,
            ),
            key=f"ret_churn_{dimension}",
        )

    tables.render_table(
        table,
        columns=[
            "dimension_value",
            "members",
            "retained",
            "churned",
            "churn_rate",
            "retention_rate",
            "churn_ci_low",
            "churn_ci_high",
            "avg_visits_per_month",
            "avg_avg_workout_duration_min",
            "low_confidence",
        ],
        caption="Groups below the minimum size are flagged as low confidence rather than published as "
        "headline findings.",
    )


def _standout(result, members, comparison: pd.DataFrame) -> None:
    layout.section(
        "What stands out?",
        "Findings assembled from the pipeline's computed results — never authored for the dashboard.",
        icon_name="lightbulb",
    )
    plan = retention_by_dimension(members, "membership_type") if "membership_type" in members.columns else pd.DataFrame()
    found = [
        insight
        for insight in (
            insight_adapters.frequency_gradient(result),
            insight_adapters.largest_behavioural_gap(result, comparison),
            insight_adapters.retention_by_membership_type(result, plan),
            insight_adapters.segmentation_summary(result),
            insight_adapters.strongest_association(result),
        )
        if insight
    ]
    if found:
        cards.insight_row(found, per_row=2)
    else:
        cards.empty_state(
            "No standout findings",
            "The analytical layer produced no retention findings for this population.",
            icon_name="lightbulb",
        )


def _cohorts(result) -> None:
    layout.section(
        "Cohort behaviour",
        "Members grouped by the quarter they joined, ranked by their observed churn outcome.",
        icon_name="calendar-days",
    )
    cohorts = result.analysis("cohorts", pd.DataFrame())
    if cohorts.empty:
        cards.empty_state(
            "Cohort analysis unavailable",
            "Join dates are required to build cohorts, and they are missing or unparseable in this data.",
            icon_name="calendar-days",
        )
        return
    charts.plot(
        charts.bar_chart(
            cohorts,
            x="join_quarter",
            y="churn_rate",
            title="Churn differs across join cohorts",
            subtitle="Observed churn rate (%) by join quarter",
            x_title="Join quarter",
            y_title="Churn rate (%)",
            colour=COLORS["info"],
            text_format="%{y:.1f}%",
        ),
        key="ret_cohorts",
    )
    layout.footnote(
        "Quarterly groups are small, so individual points are indicative. The membership source has no "
        "churn event date, which is why churn cannot be plotted over calendar time."
    )
    tables.technical_table("Cohort detail", cohorts, height=300)


def _correlation(result) -> None:
    layout.section(
        "Correlation with the churn outcome",
        "Spearman rank correlations, chosen because the measures are not normally distributed and the groups are unbalanced.",
        icon_name="crosshair",
    )
    correlations = result.analysis("correlations", {}) or {}
    churn_corr = correlations.get("churn", pd.DataFrame())
    if churn_corr is None or churn_corr.empty:
        cards.empty_state(
            "Correlation analysis unavailable",
            "Too few complete cases were available to compute correlations.",
            icon_name="crosshair",
        )
        return

    left, right = st.columns([1.1, 1])
    with left:
        charts.plot(
            charts.bar_chart(
                churn_corr,
                x="feature",
                y="spearman_rho",
                title="Visit frequency and streaks dominate the churn signal",
                subtitle="Spearman rho per feature; negative values mean lower churn",
                x_title="Feature",
                y_title="Spearman rho",
                colour=COLORS["info"],
                text_format="%{y:.2f}",
            ),
            key="ret_churn_corr",
        )
    with right:
        tables.render_table(
            churn_corr,
            columns=["feature", "n", "pearson_r", "spearman_rho", "strength", "direction"],
            caption=correlations.get("caveat", ""),
            height=380,
        )
    layout.footnote(
        "Streak and consistency features depend on the documented synthetic activity calendar; visit "
        "frequency, duration, calories, tenure and the churn outcome are real source values."
    )

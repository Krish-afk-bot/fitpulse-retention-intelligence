"""User Segmentation.

Behavioural segments derived from the configurable engagement score. Segment
membership depends on product-design thresholds and, for the consistency and
streak components, on the documented synthetic calendar — the churn outcome used
to evaluate each segment is real, and every card says so.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from components import cards, charts, layout, tables
from src.analytics import engagement_score_profile, segment_metrics, segment_member_list
from src.features import score_reference_values, segment_definition_frame
from styles.theme import COLORS, SEGMENT_COLORS


def render(ctx) -> None:
    result, view = ctx.result, ctx.view
    members = view.members

    layout.page_header(
        "User Segments",
        "Four behavioural segments, each described by its real churn outcome and its engagement "
        "composition, so retention effort can be aimed rather than broadcast.",
        icon_name="users",
        eyebrow="Population",
    )
    layout.provenance_legend()

    if members.empty:
        cards.empty_state(
            "No members match the current filters",
            "Segments cannot be built on an empty population.",
            icon_name="filter",
            hint="Clear the member filters in the sidebar to restore the full population.",
        )
        return

    metrics = segment_metrics(members)
    if metrics.empty:
        cards.empty_state(
            "Segmentation unavailable",
            "The engagement score could not be computed for this population, so no segments exist.",
            icon_name="users",
        )
        return

    _headline(members, metrics)
    _cards(metrics)
    _composition(metrics)
    _composition_drivers(members)
    _behaviour(members)
    _definitions()
    _drilldown(members, metrics)


# ---------------------------------------------------------------------------
def _headline(members, metrics) -> None:
    layout.section(
        "Segment health",
        "Where the population sits, and where the churn risk concentrates.",
        icon_name="gauge",
    )
    largest = metrics.sort_values("members", ascending=False).iloc[0]
    riskiest = metrics.sort_values("churn_rate", ascending=False).iloc[0]
    score = pd.to_numeric(members.get("engagement_score"), errors="coerce")
    cards.kpi_row(
        [
            cards.Kpi(
                "Segments",
                len(metrics),
                icon="layers",
                provenance="derived",
                note="Behavioural segments defined by the engagement score.",
            ),
            cards.Kpi(
                "Largest segment share",
                largest["share_pct"],
                unit="%",
                icon="users",
                provenance="derived",
                decimals=1,
                note=f"{largest['segment']} — {int(largest['members'])} members",
            ),
            cards.Kpi(
                "Highest churn segment",
                riskiest["churn_rate"],
                unit="%",
                icon="triangle-alert",
                provenance="real",
                tone="danger",
                note=f"{riskiest['segment']} churn rate ({int(riskiest['churned'])} of {int(riskiest['members'])} members)",
            ),
            cards.Kpi(
                "Mean engagement score",
                float(score.mean()) if not score.empty else None,
                unit="score",
                icon="target",
                provenance="derived",
                note="Weighted composite, 0-100. Product-design weights, not validated causal weights.",
            ),
        ],
        per_row=4,
    )


def _cards(metrics) -> None:
    layout.section(
        "Segment profile cards",
        "Segment size is drawn to scale; the churn badge is the real observed outcome for that segment.",
        icon_name="layout-dashboard",
    )
    largest = int(metrics["members"].max())
    ordered = metrics.sort_values("segment")
    columns = st.columns(len(ordered))
    for column, row in zip(columns, ordered.itertuples()):
        with column:
            cards.segment_card(
                segment=str(row.segment),
                members=int(row.members),
                share_pct=float(row.share_pct),
                churn_rate=float(row.churn_rate),
                avg_visits=float(row.avg_visits_per_month),
                avg_recency=float(row.avg_recency_days),
                avg_streak=float(row.avg_longest_streak),
                max_members=largest,
            )


def _composition(metrics) -> None:
    layout.section(
        "Segment composition and outcomes",
        "Churn is the inverse of retention, so only churn is plotted to avoid showing the same number twice.",
        icon_name="chart-pie",
    )
    left, right = st.columns(2)
    with left:
        charts.plot(
            charts.segment_donut(metrics, "Member mix across behavioural segments", "Share of members"),
            key="seg_donut",
        )
    with right:
        charts.plot(
            charts.segment_metric_bar(
                metrics,
                "churn_rate",
                "Churn concentrates in the low-engagement segments",
                "Real churn outcome per segment, with 95% Wilson intervals in the table below",
                y_title="Churn rate (%)",
                text_format="%{y:.1f}%",
            ),
            key="seg_churn",
        )

    tables.render_table(
        metrics,
        columns=[
            "segment",
            "members",
            "share_pct",
            "retained",
            "churned",
            "churn_rate",
            "retention_rate",
            "churn_ci_low",
            "churn_ci_high",
            "avg_visits_per_month",
            "avg_avg_workout_duration_min",
            "avg_longest_streak",
            "avg_average_streak",
            "avg_consistency",
            "avg_recency_days",
            "avg_engagement_score",
        ],
        caption="Retention and churn are real outcomes. Averages of streak and consistency depend on "
        "the synthetic calendar; the visit rate, duration, calories and tenure averages are real.",
    )


def _composition_drivers(members) -> None:
    layout.section(
        "What drives each segment's score",
        "The engagement score is a weighted composite. This is how each component contributes per segment.",
        icon_name="target",
    )
    profile = engagement_score_profile(members)
    if profile is None or profile.empty:
        cards.empty_state(
            "Score composition unavailable",
            "Component scores could not be computed for this population.",
            icon_name="target",
        )
        return
    left, right = st.columns([1, 1.1])
    with left:
        charts.plot(charts.score_radar(profile), key="seg_radar")
    with right:
        component_long = profile.melt(
            id_vars=["segment"],
            value_vars=[c for c in profile.columns if c.endswith("_score") and c != "engagement_score"],
            var_name="component",
            value_name="score",
        )
        component_long["component"] = (
            component_long["component"].str.replace("_score", "", regex=False).str.title()
        )
        charts.plot(
            charts.grouped_bar(
                component_long,
                x="component",
                y="score",
                colour="segment",
                title="Frequency and recency carry the most weight",
                subtitle="Mean component score (0-100) by segment",
                x_title="Score component",
                y_title="Mean component score (0-100)",
                colour_map=SEGMENT_COLORS,
            ),
            key="seg_components",
        )


def _behaviour(members) -> None:
    layout.section(
        "Segment behaviour distributions",
        "The spread behind each segment average, on the two real fields that matter most.",
        icon_name="chart-column",
    )
    left, right = st.columns(2)
    with left:
        charts.plot(
            charts.box_distribution(
                members,
                x="segment",
                y="visits_per_month",
                title="Visit frequency barely overlaps between segments",
                subtitle="Monthly visit rate by segment (real field)",
                x_title="Segment",
                y_title="Visits per month",
                colour_map=SEGMENT_COLORS,
            ),
            key="seg_box_visits",
        )
    with right:
        charts.plot(
            charts.box_distribution(
                members,
                x="segment",
                y="recency_days",
                title="Recency is high across every segment",
                subtitle="Days since last recorded visit, by segment",
                x_title="Segment",
                y_title="Days since last visit",
                colour_map=SEGMENT_COLORS,
            ),
            key="seg_box_recency",
        )
    layout.footnote(
        "Recency is measured against the observation date of the source extract, so it describes "
        "source date behaviour as much as member disengagement."
    )


def _definitions() -> None:
    with st.expander("Segment thresholds and score references"):
        st.caption(
            "Thresholds are configuration, not statistically optimised cut points. They can be "
            "changed in the sidebar or in .env; the pipeline reads the same values."
        )
        tables.render_table(
            segment_definition_frame(),
            caption="Segment definitions as configured for this run.",
        )
        references = score_reference_values()
        if references:
            st.markdown("**Score component references**")
            tables.key_value_table(
                [(key.replace("_", " "), value) for key, value in references.items()],
                caption="Component definitions are read from the same configuration the pipeline uses.",
            )


def _drilldown(members, metrics) -> None:
    layout.section(
        "Member drill-down",
        "The members behind a segment, ordered by engagement score.",
        icon_name="search",
    )
    selected = st.selectbox("Segment", options=list(metrics["segment"]), key="seg_drilldown")
    drill = segment_member_list(members, selected, limit=200)
    if "churn_status" in drill.columns:
        drill = drill.assign(
            outcome=drill["churn_status"].map({True: "Churned", False: "Retained"})
        )
    layout.footnote(retention_direction(metrics, selected))
    tables.render_table(
        drill,
        columns=[
            "member_id",
            "segment",
            "engagement_score",
            "visits_per_month",
            "longest_streak",
            "consistency",
            "recency_days",
            "membership_type",
            "outcome",
            "lifecycle_stage",
        ],
        caption="Ordered by engagement score, highest first. Member identifiers are namespaced "
        "(M-####) from the membership source; no personal identifiers are stored in the curated layer.",
        height=380,
    )


def retention_direction(metrics: pd.DataFrame, segment: str) -> str:
    """A factual one-liner about the selected segment, from the real outcome."""
    row = metrics[metrics["segment"] == segment]
    if row.empty:
        return ""
    record = row.iloc[0]
    return (
        f"{segment} holds {int(record['members'])} members ({record['share_pct']:.1f}%), of whom "
        f"{int(record['churned'])} churned: a churn rate of {record['churn_rate']:.1f}% "
        f"(95% CI {record['churn_ci_low']:.1f}%–{record['churn_ci_high']:.1f}%)."
    )

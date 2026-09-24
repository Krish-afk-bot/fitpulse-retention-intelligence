"""Executive Overview.

The entry point answers one question: *what is the retention health of this
member base, and what is driving it?* It reads top to bottom as context → KPIs →
engagement → retention → segments → risk → findings, so an evaluator understands
the product before touching a filter.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from components import cards, charts, layout, tables
from src.analytics import (
    compare_retained_vs_churned,
    retention_by_dimension,
    retention_summary,
    segment_metrics,
)
from styles.theme import COLORS, STATUS_COLORS

import insights as insight_adapters


def render(ctx) -> None:
    result, view, kpis = ctx.result, ctx.view, ctx.kpis
    members = view.members

    _hero(result, kpis, view)

    if members.empty:
        if ctx.supports("activity_analysis"):
            # Activity-only dataset: report activity honestly and state plainly that
            # retention is out of scope rather than showing an empty member view.
            _activity_only_overview(ctx)
        else:
            cards.empty_state(
                "No members match the current filters",
                "The membership model is empty after filtering, so retention cannot be evaluated.",
                icon_name="filter",
                hint="Clear the member filters in the sidebar to restore the full population.",
            )
        return

    summary = retention_summary(members) if ctx.has_outcome else {}
    _headline_kpis(kpis, summary, view, ctx)

    _engagement_section(result, view)
    _retention_section(result, members)
    _segments_section(members)
    _risk_section(result)
    _findings_section(result, members, ctx)

    with st.expander("KPI definitions and provenance"):
        tables.render_table(
            _kpi_table(result),
            caption="Every KPI carries its definition and provenance so any figure can be traced "
            "back to the analytical layer.",
        )
    for note in kpis.get("notes", []) or []:
        st.caption(f"Data caveat — {note}")


# ---------------------------------------------------------------------------
def _hero(result, kpis, view) -> None:
    quality = (result.quality or {}).get("summary", {}) or {}
    alerts = result.analyses.get("alert_summary", {}) or {}
    synthetic_events = int(kpis.get("synthetic_events") or 0)
    total_events = int(kpis.get("platform_events") or 0) + synthetic_events
    synthetic_share = 100.0 * synthetic_events / total_events if total_events else 0.0

    def metric(key: str, unit: str = "", decimals: int = 0) -> str:
        value = kpis.get(key)
        if value is None:
            return "n/a"
        return f"{float(value):,.{decimals}f}{unit}"
    layout.hero(
        title="Understand engagement. Improve retention.",
        subtitle=(
            "FitPulse joins workout activity with membership outcomes to show which engagement "
            "behaviours are associated with members staying, and which populations are drifting "
            "toward churn."
        ),
        eyebrow="Fitness retention intelligence",
        chips=[
            {
                "label": "Data status",
                "value": str(quality.get("status", "n/a")),
                "icon": "shield-check",
                "color": STATUS_COLORS.get(str(quality.get("status", "")).upper()),
            },
            {"label": "Members", "value": metric("total_members"), "icon": "users"},
            {
                "label": "Sessions",
                "value": metric("platform_events"),
                "icon": "activity",
            },
            {
                "label": "Risk posture",
                "value": str(alerts.get("status", "n/a")),
                "icon": "warning",
                "color": STATUS_COLORS.get(str(alerts.get("status", "")).upper()),
            },
        ],
        footnote=(
            f"Observation date {result.metadata.get('observation_date', 'n/a')}"
            + (
                f" · {synthetic_share:.0f}% of event dates come from the documented synthetic "
                "analytical calendar"
                if synthetic_share
                else ""
            )
        ),
    )


def _activity_only_overview(ctx) -> None:
    """Overview for a dataset with activity events but no membership outcome."""
    kpis = ctx.kpis
    result = ctx.result
    layout.unavailable_state(
        "Retention is out of scope for the loaded data",
        "Only an activity source is loaded, so there is no churn or membership outcome to measure "
        "retention against. FitPulse reports what the data does support instead of estimating it.",
        needs=[
            "A membership dataset with a member identifier and a churn/retention outcome",
        ],
        hint="Load a membership export on the Data sources page to enable retention, churn and "
        "segmentation analysis.",
    )
    layout.section(
        "Activity at a glance",
        "Recorded volume, attendance and session measures from the loaded activity source.",
        icon_name="activity",
    )
    cards.kpi_row(
        [
            cards.Kpi("Recorded sessions", kpis.get("platform_events"), icon="activity", provenance="real"),
            cards.Kpi(
                "Attendance rate",
                kpis.get("platform_attendance_rate"),
                unit="%",
                icon="circle-check",
                provenance="real",
                note="Sessions recorded as attended.",
            ),
            cards.Kpi(
                "Confirmed share",
                kpis.get("platform_confirmed_duration_share"),
                unit="%",
                icon="clock",
                provenance="derived",
                note="Share of recorded minutes belonging to attended sessions.",
            ),
            cards.Kpi(
                "Workout types",
                kpis.get("workout_types"),
                icon="layers",
                provenance="real",
                note="Distinct session types in the activity source.",
            ),
        ],
        per_row=4,
    )
    cards.kpi_row(
        [
            cards.Kpi(
                "Recorded hours",
                kpis.get("platform_total_recorded_hours"),
                unit="h",
                icon="timer",
                provenance="real",
                decimals=1,
            ),
            cards.Kpi(
                "Average duration",
                kpis.get("platform_avg_duration"),
                unit="min",
                icon="timer",
                provenance="real",
                decimals=1,
            ),
            cards.Kpi(
                "Active days",
                kpis.get("platform_active_days"),
                icon="calendar-check",
                provenance="real",
                note=f"of {kpis.get('platform_calendar_days', 0):,} calendar days",
            ),
            cards.Kpi(
                "Longest active streak",
                kpis.get("platform_longest_active_streak"),
                unit="days",
                icon="flame",
                provenance="real",
                note="Platform-level consecutive active days.",
            ),
        ],
        per_row=4,
    )
    layout.section(
        "What this data supports",
        "Capabilities derived from the confirmed column mapping.",
        icon_name="shield-check",
    )
    _system_strip(result)
    for note in (kpis.get("notes") or []):
        st.caption(f"Data caveat — {note}")
    layout.action_hint(
        "The Engagement page carries the full activity analysis: trends, frequency distribution, "
        "streak behaviour and workout-type mix."
    )


def _headline_kpis(kpis, summary, view, ctx) -> None:
    layout.section(
        "Retention health",
        "Real outcomes from the membership source, followed by the engagement measures that move with them.",
        icon_name="gauge",
    )
    summary = summary or {}
    outcome_cards = (
        [
            cards.Kpi(
                "Total members",
                kpis.get("total_members"),
                icon="users",
                provenance="real",
                note="Distinct members in the loaded membership source.",
            ),
            cards.Kpi(
                "Retention rate",
                kpis.get("retention_rate"),
                unit="%",
                icon="trending-up",
                provenance="real",
                tone="success",
                note=f"{summary.get('retained', 0):,} retained of {summary.get('total_members', 0):,} eligible",
                help="Retained members divided by eligible members, from the source churn label.",
            ),
            cards.Kpi(
                "Churn rate",
                kpis.get("churn_rate"),
                unit="%",
                icon="user-minus",
                provenance="real",
                tone="danger" if (kpis.get("churn_rate") or 0) >= 25 else "warning",
                note=(
                    f"95% CI {summary.get('churn_ci_low', 0):.1f}%–{summary.get('churn_ci_high', 0):.1f}%"
                    if summary
                    else ""
                ),
            ),
            cards.Kpi(
                "At-risk members",
                kpis.get("at_risk_members"),
                icon="triangle-alert",
                provenance="derived",
                tone="warning",
                note="Members in the At Risk or Dormant behavioural segments.",
            ),
        ]
        if ctx.has_outcome
        else [
            cards.Kpi(
                "Total members",
                kpis.get("total_members"),
                icon="users",
                provenance="real",
                note="Distinct members in the loaded membership source.",
            ),
            cards.Kpi(
                "Avg visits / month",
                kpis.get("avg_visits_per_month"),
                icon="footprints",
                provenance="real",
                decimals=1,
            ),
            cards.Kpi(
                "Avg engagement score",
                kpis.get("avg_engagement_score"),
                unit="score",
                icon="target",
                provenance="derived",
            ),
            cards.Kpi(
                "Avg longest streak",
                kpis.get("avg_longest_streak"),
                unit="days",
                icon="flame",
                provenance="synthetic",
            ),
        ]
    )
    cards.kpi_row(outcome_cards, per_row=4, emphasis="primary")
    if not ctx.has_outcome:
        st.caption(
            "No churn/retention outcome was detected in the loaded membership data, so retention, "
            "churn and segmentation are reported as unavailable."
        )
    cards.kpi_row(
        [
            cards.Kpi(
                "Avg visits / month",
                kpis.get("avg_visits_per_month"),
                icon="footprints",
                provenance="real",
                decimals=1,
                note="Mean monthly visit rate recorded per member.",
            ),
            cards.Kpi(
                "Avg engagement score",
                kpis.get("avg_engagement_score"),
                unit="score",
                icon="target",
                provenance="derived",
                note="Weighted composite of frequency, consistency, streak, recency and duration.",
            ),
            cards.Kpi(
                "Avg longest streak",
                kpis.get("avg_longest_streak"),
                unit="days",
                icon="flame",
                provenance="synthetic",
                note="Longest run of consecutive active days, from the synthetic calendar.",
            ),
            cards.Kpi(
                "Recorded sessions",
                kpis.get("platform_events"),
                icon="activity",
                provenance="real",
                note=f"{kpis.get('platform_active_days', 0):,} active days across the loaded year",
            ),
        ],
        per_row=4,
    )


def _system_strip(result) -> None:
    quality = (result.quality or {}).get("summary", {}) or {}
    validation = (result.validation or {}).get("summary", {}) or {}
    alerts = result.analyses.get("alert_summary", {}) or {}
    cards.kpi_row(
        [
            cards.Kpi(
                "Data quality",
                icon="database",
                provenance="real",
                status=str(quality.get("status", "n/a")),
                note=f"{quality.get('passed', 0)} of {quality.get('total_checks', 0)} checks passed",
            ),
            cards.Kpi(
                "Python ↔ SQL",
                icon="terminal",
                provenance="derived",
                status=str(validation.get("status", "n/a")),
                note=f"{validation.get('kpi_passed', 0)} of {validation.get('kpi_checks', 0)} KPIs agree",
            ),
            cards.Kpi(
                "Risk posture",
                icon="warning",
                provenance="derived",
                status=str(alerts.get("status", "n/a")),
                note=f"{alerts.get('total', 0)} threshold breaches open",
            ),
            cards.Kpi(
                "Integration",
                icon="git-branch",
                provenance="derived",
                status="WARNING",
                note="No member-level key existed between the two sources, so no join was performed",
            ),
        ],
        per_row=4,
    )


# ---------------------------------------------------------------------------
def _engagement_section(result, view) -> None:
    layout.section(
        "Engagement overview",
        "Volume and attendance from the activity source; member visit frequency from the membership source.",
        icon_name="activity",
    )
    monthly = result.analysis("monthly_trend", pd.DataFrame())
    bands = result.analysis("engagement_bands", pd.DataFrame())
    left, right = st.columns([1.35, 1])
    with left:
        charts.plot(charts.monthly_dual_axis(monthly), key="ov_monthly")
    with right:
        charts.plot(
            charts.bar_chart(
                bands.rename(columns={"engagement_band": "band"}) if not bands.empty else bands,
                x="score_range" if not bands.empty and "score_range" in bands.columns else "band",
                y="churn_rate",
                title="Churn falls as the engagement score rises",
                subtitle="Churn rate (%) by engagement-score band",
                x_title="Engagement score band",
                y_title="Churn rate (%)",
                text_format="%{y:.1f}%",
            ),
            key="ov_bands",
        )

    insight_cards = [i for i in (insight_adapters.activity_trend(result), insight_adapters.engagement_summary(result)) if i]
    if insight_cards:
        cards.insight_row(insight_cards, per_row=2)


def _retention_section(result, members) -> None:
    layout.section(
        "Retention overview",
        "What the churn outcome looks like across the dimensions this dataset actually supports.",
        icon_name="trending-up",
    )
    gradient = result.analysis("retention").frequency_gradient if result.analysis("retention") else pd.DataFrame()
    plan = retention_by_dimension(members, "membership_type")
    left, right = st.columns(2)
    with left:
        charts.plot(
            charts.retention_gradient(
                gradient,
                label_column="dimension_value",
                title="Retention climbs with monthly visit frequency",
                subtitle="Retention rate (%) by visits per month, with Wilson 95% intervals",
                x_title="Visits per month",
            ),
            key="ov_gradient",
        )
    with right:
        charts.plot(
            charts.retention_gradient(
                plan,
                label_column="dimension_value",
                title="Longer plans retain slightly better",
                subtitle="Retention rate (%) by membership type",
                x_title="Membership type",
                error_low="churn_ci_low",
                error_high="churn_ci_high",
            ),
            key="ov_plan",
        )

    cohort = result.analysis("cohorts", pd.DataFrame())
    if not cohort.empty:
        with st.expander("Cohort detail — churn by join quarter"):
            charts.plot(
                charts.bar_chart(
                    cohort,
                    x="join_quarter",
                    y="churn_rate",
                    title="Churn rate by join-quarter cohort",
                    subtitle="Observed churn outcome grouped by the quarter a member joined",
                    x_title="Join quarter",
                    y_title="Churn rate (%)",
                    colour=COLORS["info"],
                    text_format="%{y:.1f}%",
                ),
                key="ov_cohort",
            )
            layout.footnote(
                "Quarterly groups are small, so individual points are indicative. The membership "
                "source has no churn event date, so churn over calendar time cannot be derived."
            )

    insight_cards = [i for i in (insight_adapters.frequency_gradient(result), insight_adapters.retention_by_membership_type(result, plan)) if i]
    if insight_cards:
        cards.insight_row(insight_cards, per_row=2)


def _segments_section(members) -> None:
    layout.section(
        "User segments",
        "Behavioural segments built from the configurable engagement score. Segment thresholds are product design; the churn outcome used to evaluate them is real.",
        icon_name="users",
    )
    metrics = segment_metrics(members)
    if metrics.empty:
        cards.empty_state("Segmentation unavailable", "No segment metrics could be computed.", icon_name="users")
        return

    largest = int(metrics["members"].max())
    columns = st.columns(len(metrics))
    for column, row in zip(columns, metrics.sort_values("segment").itertuples()):
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

    left, right = st.columns([1, 1.2])
    with left:
        charts.plot(
            charts.segment_donut(
                metrics, "Member mix across behavioural segments", "Share of members by segment"
            ),
            key="ov_seg_donut",
        )
    with right:
        charts.plot(
            charts.segment_metric_bar(
                metrics,
                "churn_rate",
                "Churn concentrates in the low-engagement segments",
                "Real churn outcome per segment",
                y_title="Churn rate (%)",
                text_format="%{y:.1f}%",
            ),
            key="ov_seg_churn",
        )
    layout.footnote(
        "Segment membership depends on the configurable engagement weights and, for the consistency "
        "and streak components, on the documented synthetic activity calendar."
    )


def _risk_section(result) -> None:
    layout.section(
        "Risk & alerts",
        "Threshold breaches across retention, engagement and data quality, with the population each one affects.",
        icon_name="warning",
    )
    alerts = st.session_state.get("active_alerts")
    if alerts is None or not isinstance(alerts, pd.DataFrame):
        alerts = result.alerts
    summary = result.analyses.get("alert_summary", {}) or {}

    left, right = st.columns([1, 2.4])
    with left:
        cards.stat_block("Open alerts", summary.get("total", 0), detail=f"Status {summary.get('status', 'n/a')}")
        cards.stat_block("High severity", summary.get("high", 0), detail="Require attention now")
        cards.stat_block("Warnings", summary.get("medium", 0), detail="Monitor and investigate")
    with right:
        if alerts is not None and not alerts.empty:
            for _, alert in alerts.sort_values("severity").head(2).iterrows():
                cards.alert_card(alert)
                st.write("")
            layout.footnote(
                f"{len(alerts)} alerts are open in total. The Risk &amp; Alerts page carries the "
                "full monitor, anomaly detection and root-cause investigation."
            )
        else:
            cards.insight_card(
                cards.Insight(
                    title="No thresholds breached",
                    body="No configured retention, engagement or data-quality threshold is currently "
                    "breached for the selected population.",
                    icon="shield-check",
                    eyebrow="Risk & alerts",
                    tone="success",
                    provenance="derived",
                )
            )


def _findings_section(result, members, ctx=None) -> None:
    layout.section(
        "Key insights",
        "Findings assembled from the pipeline's own computed results. Every statement is "
        "associational — this data describes, it does not prove causation.",
        icon_name="lightbulb",
    )
    comparison = compare_retained_vs_churned(members)
    insight_cards = insight_adapters.combined(result, comparison=comparison, limit=6)
    if insight_cards:
        cards.insight_row(insight_cards, per_row=2)
    else:
        cards.empty_state(
            "No findings available",
            "The analytical layer produced no insight statements for this population.",
            icon_name="lightbulb",
        )

    # Operational checks are important but secondary: they answer "can I trust these
    # numbers?", not "how is retention?". Keeping them out of the opening viewport
    # lets the KPIs and the two headline charts carry the page.
    with st.expander("Data quality, SQL agreement and integration"):
        _system_strip(result)

    # Provenance sits at the same level as the checks above rather than nested
    # inside them, so the disclosure is one click away instead of two.
    layout.provenance_notes(ctx)

    layout.section(
        "Pipeline status",
        "Stage telemetry from the run that produced every number on this page.",
        icon_name="workflow",
    )
    _pipeline_strip(result)


def _pipeline_strip(result) -> None:
    records = pd.DataFrame(result.stage_records)
    if records.empty:
        st.caption("No stage telemetry recorded for this run.")
        return
    chips = "".join(
        cards.status_chip(f"{str(row.stage).title()} · {row.duration:.2f}s", str(row.status))
        for row in records.itertuples()
    )
    st.markdown(
        f'<div style="display:flex;flex-wrap:wrap;gap:.4rem;">{chips}</div>',
        unsafe_allow_html=True,
    )
    total = pd.to_numeric(records.get("duration"), errors="coerce").sum()
    layout.footnote(
        f"{len(records)} stages completed in {total:,.2f}s. Full telemetry is on the Pipeline Status page."
    )


def _kpi_table(result) -> pd.DataFrame:
    from src.analytics import kpi_display_frame

    return kpi_display_frame(result.kpis)

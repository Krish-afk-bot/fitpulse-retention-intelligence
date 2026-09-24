"""Risk & Alerts.

An operational monitor: what is breaching its threshold right now, how severe it
is, who is affected, and what to look at next. Thresholds are configuration and
are stated as such — they are not statistically optimal cut points.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from components import cards, charts, layout, tables
from src.alerts import alert_summary
from styles.theme import COLORS, SEVERITY_COLORS

SEVERITY_ORDER = ["HIGH", "MEDIUM", "LOW", "INFO"]
MAX_CARDS = 12


def render(ctx) -> None:
    result, view = ctx.result, ctx.view
    alerts = st.session_state.get("active_alerts")
    if alerts is None or not isinstance(alerts, pd.DataFrame):
        alerts = result.alerts
    if alerts is None:
        alerts = pd.DataFrame()
    summary = alert_summary(alerts)

    layout.page_header(
        "Risk Monitor",
        "Threshold-driven detection across retention, engagement and data quality. Every alert "
        "states what happened, which threshold was crossed, who is affected and why it fired.",
        icon_name="warning",
        eyebrow="Operations",
    )

    _monitor(summary, alerts)
    _alert_cards(alerts)
    _anomalies(result, view)
    _root_causes(result)
    _at_risk(view)


# ---------------------------------------------------------------------------
def _monitor(summary, alerts) -> None:
    layout.section(
        "Risk monitor",
        "Severity is derived from how far the observed value exceeds its threshold. Thresholds are "
        "configuration, editable in the sidebar.",
        icon_name="gauge",
    )
    counts = alerts["severity"].astype(str).str.upper().value_counts().to_dict() if not alerts.empty else {}
    left, right = st.columns([1.1, 1])
    with left:
        columns = st.columns(4)
        for column, severity in zip(columns, SEVERITY_ORDER):
            with column:
                color = SEVERITY_COLORS.get(severity, COLORS["neutral"])
                st.markdown(
                    "".join(
                        [
                            f'<div class="fp-card" style="border-left:3px solid {color};">',
                            f'<div style="display:flex;align-items:center;gap:.5rem;">'
                            f'{cards.severity_badge(severity)}</div>',
                            f'<div style="font-size:1.6rem;font-weight:700;color:{COLORS["text"]};'
                            f'margin-top:.4rem;">{counts.get(severity, 0)}</div>',
                            f'<div style="font-size:.75rem;color:{COLORS["muted"]};">'
                            f"{'Requires attention now' if severity == 'HIGH' else 'Open findings'}</div>",
                            "</div>",
                        ]
                    ),
                    unsafe_allow_html=True,
                )
    with right:
        cards.insight_card(
            cards.Insight(
                title=f"Overall posture: {summary.get('status', 'n/a')}",
                body=str(summary.get("headline", "")),
                icon="shield-alert",
                eyebrow="Alert status",
                tone={"HIGH": "danger", "MEDIUM": "warning"}.get(str(summary.get("status", "")).upper(), "success"),
                provenance="derived",
            )
        )
        layout.action_hint(
            "Thresholds come from .env and the sidebar. Changing them re-evaluates alerts immediately; "
            "the CLI pipeline uses the configured values."
        )


def _alert_cards(alerts) -> None:
    layout.section(
        "Active alerts",
        "Highest severity first. Each card shows the observed value, the threshold, the affected "
        "population and the reason it fired.",
        icon_name="bell",
    )
    if alerts is None or alerts.empty:
        cards.insight_card(
            cards.Insight(
                title="No thresholds breached",
                body="No configured retention, engagement or data-quality threshold is currently "
                "breached for the selected population.",
                icon="circle-check",
                eyebrow="All clear",
                tone="success",
                provenance="derived",
            )
        )
        return

    ordered = alerts.assign(
        _rank=alerts["severity"].astype(str).str.upper().map(
            {severity: index for index, severity in enumerate(SEVERITY_ORDER)}
        ).fillna(99)
    ).sort_values(["_rank", "metric"]).drop(columns="_rank")

    for _, alert in ordered.head(MAX_CARDS).iterrows():
        cards.alert_card(alert)
        st.write("")

    if len(ordered) > MAX_CARDS:
        st.caption(f"Showing the {MAX_CARDS} highest-severity alerts of {len(ordered)} currently open.")

    with st.expander("All alerts (technical table)"):
        tables.render_table(
            ordered,
            columns=[
                "severity",
                "category",
                "metric",
                "observed_display",
                "threshold_display",
                "affected_population",
                "affected_count",
                "triggered_at",
            ],
            caption="Severity is derived from the distance between the observed value and its threshold.",
        )
        st.markdown(
            "- **HIGH** — the metric exceeds its threshold by 50% or more, or a hard validation rule failed\n"
            "- **MEDIUM** — the metric exceeds its threshold\n"
            "- **LOW** — the metric is within 20% of its threshold\n"
            "- **INFO** — reported for context only"
        )


def _anomalies(result, view) -> None:
    layout.section(
        "Anomaly detection",
        "Statistical outliers in the activity series, classified and reported. No source value is deleted or capped.",
        icon_name="crosshair",
    )
    anomalies = result.analysis("anomalies", pd.DataFrame())
    if anomalies is None or anomalies.empty:
        cards.insight_card(
            cards.Insight(
                title="No anomalies beyond the detection thresholds",
                body="Volume, attendance and member-level measures all sit inside the expected bands.",
                icon="circle-check",
                eyebrow="Anomalies",
                tone="success",
                provenance="derived",
            )
        )
        return

    left, right = st.columns([1.5, 1])
    with left:
        daily = view.platform_daily
        if not daily.empty:
            charts.plot(
                charts.line_trend(
                    daily,
                    x="activity_date",
                    y="events",
                    title="Daily session volume against its 28-day baseline",
                    subtitle="Recorded sessions per day with the rolling baseline used for detection",
                    x_title="Date",
                    y_title="Recorded sessions",
                    rolling=["rolling_28d_events"],
                    rolling_labels=["28-day baseline"],
                    dense=True,
                ),
                key="alerts_daily",
            )
    with right:
        counts = (
            anomalies.groupby("severity").size().reset_index(name="findings").rename(columns={"severity": "state"})
        )
        charts.plot(
            charts.status_bar(
                counts,
                "Findings by severity",
                x="state",
                y="findings",
                colour_map=SEVERITY_COLORS,
                subtitle="Classified anomalies in the current run",
            ),
            key="alerts_anomaly_counts",
        )
    tables.technical_table(
        "All detected anomalies",
        anomalies,
        columns=[
            "metric",
            "detected_at",
            "severity",
            "method",
            "threshold",
            "observed_value",
            "expected_value",
            "population",
            "message",
        ],
        caption="Methods: z-score against the series mean, sustained deviation from a rolling baseline, "
        "and IQR fences for member-level values.",
    )


def _root_causes(result) -> None:
    layout.section(
        "Root-cause investigation",
        "Observed evidence and possible explanations are kept strictly separate. Nothing here is a causal claim.",
        icon_name="git-branch",
    )
    chains = result.analysis("root_cause_chains", [])
    if not chains:
        cards.empty_state(
            "No investigation chains",
            "No metric moved far enough for the diagnostics layer to build an investigation.",
            icon_name="git-branch",
        )
        return
    for chain in chains:
        with st.expander(f"{chain.subject} — confidence {chain.confidence}", expanded=False):
            st.markdown(f"**Metric examined:** {chain.metric_changed}  \n**Period:** {chain.period}")
            st.markdown("**Observed evidence**")
            layout.bullet_list(chain.observed_evidence, icon_name="circle-dot")
            st.markdown("**Possible explanations (not verified)**")
            layout.bullet_list(chain.possible_explanations, icon_name="circle-dot", color=COLORS["warning"])
            if chain.data_caveats:
                st.markdown("**Data caveats**")
                layout.bullet_list(chain.data_caveats, icon_name="circle-dot", color=COLORS["muted"])


def _at_risk(view) -> None:
    layout.section(
        "At-risk population",
        "The members in the At Risk and Dormant segments — the actionable cohort for a retention campaign.",
        icon_name="users",
    )
    members = view.members
    if members.empty or "at_risk_flag" not in members.columns:
        cards.empty_state(
            "At-risk population unavailable",
            "The at-risk flag could not be computed for the current selection.",
            icon_name="users",
        )
        return
    at_risk = members[members["at_risk_flag"].astype(bool)]
    share = 100.0 * len(at_risk) / max(len(members), 1)
    columns = st.columns(3)
    with columns[0]:
        cards.stat_block("Members at risk", len(at_risk), detail=f"{share:.1f}% of the selected population")
    with columns[1]:
        cards.stat_block(
            "Median visits / month",
            float(pd.to_numeric(at_risk["visits_per_month"], errors="coerce").median()) if not at_risk.empty else None,
            detail="Against the full-population median",
        )
    with columns[2]:
        cards.stat_block(
            "Observed churn rate",
            float(at_risk["is_churned"].astype(bool).mean() * 100) if not at_risk.empty else None,
            unit="%",
            detail="Real churn outcome inside this cohort",
        )

    if at_risk.empty:
        return
    left, right = st.columns([1, 1.2])
    with left:
        by_segment = (
            at_risk.groupby("segment", observed=True)
            .agg(members=("member_id", "count"))
            .reset_index()
        )
        charts.plot(
            charts.bar_chart(
                by_segment,
                x="segment",
                y="members",
                title="At-risk members by segment",
                subtitle="Where retention effort would land first",
                x_title="Segment",
                y_title="Members",
                colour_column="segment",
                colour_map=charts.SEGMENT_COLOURS,
                text_format="%{y:,}",
            ),
            key="alerts_at_risk",
        )
    with right:
        tables.render_table(
            at_risk.sort_values("recency_days", ascending=False)[
                [
                    column
                    for column in (
                        "member_id",
                        "segment",
                        "visits_per_month",
                        "recency_days",
                        "longest_streak",
                        "membership_type",
                    )
                    if column in at_risk.columns
                ]
            ],
            caption="Highest recency first — the members already furthest from their last visit.",
            height=360,
        )

"""Engagement Analytics.

Answers one question: *how actively are members engaging, and where does activity
concentrate?* Member-level visit frequency comes from the membership source;
platform volume, duration and attendance come from the activity source;
member-level streak history depends on the documented synthetic calendar and is
labelled as such wherever it appears.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from components import cards, charts, layout, tables
from styles.theme import COLORS

import insights as insight_adapters


def render(ctx) -> None:
    result, view, kpis = ctx.result, ctx.view, ctx.kpis
    members = view.members
    fact = view.fact_workout
    daily = view.platform_daily
    monthly = result.analysis("monthly_trend", pd.DataFrame())

    layout.page_header(
        "Engagement Intelligence",
        "How actively members engage: visit frequency, session volume, duration, streak behaviour "
        "and workout-type mix — each measure labelled with where it comes from.",
        icon_name="activity",
        eyebrow="Behaviour",
    )
    layout.provenance_legend()

    _kpis(kpis, view, members)
    _activity(result, monthly, daily, view)
    _frequency(result, members)
    _streaks(result, members)
    _duration_and_behaviour(result, fact)
    _insights(result)

    with st.expander("Distribution statistics (technical)"):
        stats_by_metric = result.analysis("distribution_stats", {}) or {}
        rows = [
            {"metric": name.replace("_", " "), **stats}
            for name, stats in stats_by_metric.items()
            if stats
        ]
        tables.render_table(
            pd.DataFrame(rows),
            caption="Descriptive statistics for the key measures. Duration comes from the activity "
            "source and includes sessions recorded as absent.",
        )
        histograms = result.analysis("distributions", {}) or {}
        for name, histogram in histograms.items():
            if not isinstance(histogram, pd.DataFrame) or histogram.empty:
                continue
            st.markdown(f"**{name.replace('_', ' ').title()} — binned distribution**")
            tables.render_table(
                histogram[[c for c in ("bin_label", "count", "share_pct") if c in histogram.columns]],
                caption="Bin boundaries are closed on the left, open on the right.",
            )


# ---------------------------------------------------------------------------
def _kpis(kpis, view, members) -> None:
    layout.section(
        "Engagement at a glance",
        "Frequency is the strongest real signal in this dataset; consistency and streaks depend on the synthetic calendar.",
        icon_name="gauge",
    )
    visits = pd.to_numeric(members.get("visits_per_month"), errors="coerce") if not members.empty else pd.Series(dtype=float)
    consistency = pd.to_numeric(members.get("consistency"), errors="coerce") if not members.empty else pd.Series(dtype=float)
    weekly = pd.to_numeric(members.get("workouts_per_week"), errors="coerce") if not members.empty else pd.Series(dtype=float)

    cards.kpi_row(
        [
            cards.Kpi(
                "Mean visits / month",
                float(visits.mean()) if not visits.empty else None,
                icon="footprints",
                provenance="real",
                decimals=1,
                note="Real field recorded in the membership source.",
            ),
            cards.Kpi(
                "Median visits / month",
                float(visits.median()) if not visits.empty else None,
                icon="target",
                provenance="real",
                decimals=1,
                note="Less sensitive to extreme visit rates than the mean.",
            ),
            cards.Kpi(
                "Mean visits / week",
                float(weekly.mean()) if not weekly.empty else None,
                icon="calendar-days",
                provenance="synthetic",
                decimals=2,
                note="Derived from the synthetic calendar's active-day rate.",
            ),
            cards.Kpi(
                "Mean consistency",
                float(consistency.mean()) if not consistency.empty else None,
                icon="repeat",
                provenance="synthetic",
                decimals=3,
                note="Active days divided by observation days.",
            ),
        ],
        per_row=4,
        emphasis="primary",
    )
    cards.kpi_row(
        [
            cards.Kpi(
                "Attendance rate",
                kpis.get("platform_attendance_rate"),
                unit="%",
                icon="calendar-check",
                provenance="real",
                tone="info",
                note="Share of scheduled sessions recorded as attended.",
            ),
            cards.Kpi(
                "Recorded sessions",
                kpis.get("platform_events"),
                icon="activity",
                provenance="real",
                note=f"{kpis.get('platform_active_days', 0):,} active days in the window",
            ),
            cards.Kpi(
                "Recorded hours",
                kpis.get("platform_total_recorded_hours"),
                unit="hours",
                icon="timer",
                provenance="real",
                decimals=0,
                note="Nominal duration, including sessions recorded as absent.",
            ),
            cards.Kpi(
                "Confirmed hours",
                kpis.get("platform_confirmed_hours"),
                unit="hours",
                icon="circle-check",
                provenance="real",
                tone="success",
                decimals=0,
                note="Duration belonging to attended sessions only.",
            ),
        ],
        per_row=4,
    )


def _activity(result, monthly, daily, view) -> None:
    layout.section(
        "Workout activity",
        "Volume and attendance rate from the real activity source, with rolling baselines so genuine shifts are visible.",
        icon_name="activity",
    )
    charts.plot(
        charts.monthly_dual_axis(
            monthly,
            title="Session volume is stable while the attendance rate climbs",
            subtitle="Monthly recorded sessions, the 3-month average and the share actually attended",
        ),
        key="eng_monthly",
    )
    if not daily.empty:
        charts.plot(
            charts.line_trend(
                daily,
                x="activity_date",
                y="events",
                title="Daily sessions sit inside a stable band",
                subtitle="Recorded sessions per day with 7- and 28-day rolling averages",
                x_title="Date",
                y_title="Recorded sessions",
                rolling=["rolling_7d_events", "rolling_28d_events"],
                rolling_labels=["7-day average", "28-day average"],
                dense=True,
                height=400,
            ),
            key="eng_daily",
        )

    trend = result.analysis("trend_summary", {}) or {}
    events = trend.get("events_trend", {})
    rate = trend.get("present_rate_trend", {})
    if events.get("explanation"):
        columns = st.columns(3)
        with columns[0]:
            cards.stat_block(
                "Session volume trend",
                events.get("change_pct"),
                unit="%",
                detail=f"{events.get('direction', 'n/a')} across the window",
            )
        with columns[1]:
            cards.stat_block(
                "Attendance rate trend",
                rate.get("change_pct"),
                unit="%",
                detail=f"{rate.get('direction', 'n/a')} across the window",
            )
        with columns[2]:
            peak = trend.get("peak_month")
            cards.stat_block(
                "Peak month",
                peak,
                detail=f"{trend.get('peak_events', 0):,} sessions" if trend.get("peak_events") else "",
            )
        st.caption(events["explanation"])


def _frequency(result, members) -> None:
    layout.section(
        "Frequency distribution",
        "How visit frequency is spread across the member base, and how that spread lines up with retention.",
        icon_name="chart-column",
    )
    left, right = st.columns(2)
    with left:
        charts.plot(
            charts.histogram(
                members,
                "visits_per_month",
                "Visit frequency is spread across the whole range",
                "Members by monthly visit rate (real field)",
                x_title="Visits per month",
                bins=15,
            ),
            key="eng_visits_hist",
        )
    with right:
        bands = (
            members.groupby("visit_frequency_band", observed=True)
            .agg(members=("member_id", "count"))
            .reset_index()
            .rename(columns={"visit_frequency_band": "band"})
        )
        order = ["0-4", "5-8", "9-12", "13-16", "17-20", "21+"]
        bands["_order"] = bands["band"].astype(str).map({value: index for index, value in enumerate(order)}).fillna(99)
        bands = bands.sort_values("_order").drop(columns="_order")
        charts.plot(
            charts.bar_chart(
                bands,
                x="band",
                y="members",
                title="Most members sit between 9 and 20 visits per month",
                subtitle="Members in each visit-frequency band",
                x_title="Visits per month band",
                y_title="Members",
                text_format="%{y:,}",
            ),
            key="eng_bands",
        )

    gradient = result.analysis("retention").frequency_gradient if result.analysis("retention") else pd.DataFrame()
    charts.plot(
        charts.retention_gradient(
            gradient,
            label_column="dimension_value",
            title="Retention rises sharply with visit frequency",
            subtitle="Retention rate (%) by visits per month, with Wilson 95% intervals",
            x_title="Visits per month",
        ),
        key="eng_frequency_retention",
    )
    layout.footnote(
        "The lowest band contains very few members, so its rate is indicative only. Frequency is "
        "associated with retention here; this is not a causal estimate."
    )


def _streaks(result, members) -> None:
    layout.section(
        "Streak behaviour",
        "Streaks require chronological per-member activity. The activity source has no repeatable member identifier, so these derive from the documented synthetic calendar.",
        icon_name="flame",
    )
    streak_table = result.analysis("streak_distribution", pd.DataFrame())
    left, right = st.columns(2)
    with left:
        charts.plot(
            charts.histogram(
                members,
                "longest_streak",
                "Longest streaks cluster below two weeks",
                "Distribution of longest consecutive-day streaks",
                x_title="Longest streak (consecutive days)",
                bins=15,
                colour=COLORS["warning"],
            ),
            key="eng_streak_hist",
        )
    with right:
        charts.plot(
            charts.bar_chart(
                streak_table.rename(columns={"streak_bucket": "band"}) if not streak_table.empty else streak_table,
                x="band",
                y="churn_rate",
                title="Longer streaks are associated with lower churn",
                subtitle="Churn rate (%) by longest-streak bucket",
                x_title="Longest streak bucket",
                y_title="Churn rate (%)",
                text_format="%{y:.1f}%",
            ),
            key="eng_streak_churn",
        )
    summary = pd.to_numeric(members.get("longest_streak"), errors="coerce") if "longest_streak" in members.columns else pd.Series(dtype=float)
    if not summary.empty:
        columns = st.columns(4)
        for column, (label, value) in zip(
            columns,
            [
                ("Mean longest streak", summary.mean()),
                ("Median longest streak", summary.median()),
                ("Mean average streak", pd.to_numeric(members["average_streak"], errors="coerce").mean()),
                ("Mean streak breaks", pd.to_numeric(members["streak_break_count"], errors="coerce").mean()),
            ],
        ):
            with column:
                cards.stat_block(label, float(value), unit="days" if "streak" in label.lower() else "")
    layout.footnote(
        "Streak dates are generated from each member's real visit rate; the visit rate itself, the "
        "churn outcome and all duration and calorie measures remain real source values."
    )


def _duration_and_behaviour(result, fact) -> None:
    layout.section(
        "Session duration and workout behaviour",
        "Recorded duration is nominal — it is stored for sessions marked absent as well as attended — so attendance-gated measures are shown beside it.",
        icon_name="timer",
    )
    contrast = result.analysis("attendance_contrast", pd.DataFrame())
    type_mix = result.analysis("workout_type_mix", pd.DataFrame())
    left, right = st.columns(2)
    with left:
        charts.plot(
            charts.histogram(
                fact,
                "duration_minutes",
                "Scheduled sessions cluster around the mid-70s",
                "Recorded duration of all scheduled sessions (minutes)",
                x_title="Recorded duration (minutes)",
                bins=25,
                colour=COLORS["info"],
            ),
            key="eng_duration_hist",
        )
    with right:
        if not contrast.empty:
            charts.plot(
                charts.grouped_bar(
                    contrast.melt(
                        id_vars=["attendance_status"],
                        value_vars=[c for c in ("mean_duration", "mean_calories") if c in contrast.columns],
                        var_name="metric",
                        value_name="value",
                    ).replace({"mean_duration": "Mean duration (min)", "mean_calories": "Mean calories"}),
                    x="attendance_status",
                    y="value",
                    colour="metric",
                    title="Absent sessions carry almost the same recorded measures",
                    subtitle="Mean recorded duration and calories by attendance outcome",
                    x_title="Attendance status",
                    y_title="Mean recorded value",
                ),
                key="eng_contrast",
            )
            layout.footnote(
                "Because absent sessions carry near-identical nominal duration, attendance-gated "
                "('confirmed') measures are reported alongside totals throughout the product."
            )
        else:
            charts.plot(charts.empty_chart("Attendance contrast unavailable."), key="eng_contrast_empty")

    if not type_mix.empty:
        charts.plot(
            charts.bar_chart(
                type_mix,
                x="workout_type",
                y="present_rate_pct",
                title="Attendance rate barely differs by workout type",
                subtitle="Share of scheduled sessions attended, by workout type",
                x_title="Workout type",
                y_title="Attendance rate (%)",
                colour=COLORS["primary"],
                text_format="%{y:.1f}%",
            ),
            key="eng_type_rate",
        )
    else:
        charts.plot(charts.empty_chart("Workout-type data unavailable."), key="eng_type_empty")

    if not type_mix.empty:
        columns = st.columns(3)
        top = type_mix.sort_values("events", ascending=False).iloc[0]
        with columns[0]:
            cards.stat_block("Most frequent workout", top["workout_type"], detail=f"{int(top['events']):,} sessions")
        with columns[1]:
            cards.stat_block(
                "Attendance range",
                f"{type_mix['present_rate_pct'].min():.1f}–{type_mix['present_rate_pct'].max():.1f}%",
                detail="Across all workout types",
            )
        with columns[2]:
            cards.stat_block(
                "Workout types tracked",
                len(type_mix),
                detail="Distinct types in the activity source",
            )
        tables.technical_table(
            "Workout-type detail",
            type_mix,
            columns=[
                "workout_type",
                "events",
                "present_count",
                "present_rate_pct",
                "event_share_pct",
                "avg_duration",
                "avg_calories",
            ],
            caption="Attendance sits in a narrow band across workout types, so workout type does not "
            "explain attendance variation in this dataset.",
        )


def _insights(result) -> None:
    layout.section(
        "Key insights",
        "Findings computed by the pipeline, not written for the dashboard.",
        icon_name="lightbulb",
    )
    cards_found = [
        insight
        for insight in (
            insight_adapters.engagement_summary(result),
            insight_adapters.attendance_summary(result),
            insight_adapters.activity_trend(result),
        )
        if insight
    ]
    if cards_found:
        cards.insight_row(cards_found, per_row=3)
    else:
        cards.empty_state(
            "No engagement findings available",
            "The analytical layer produced no engagement statements for this population.",
            icon_name="lightbulb",
        )

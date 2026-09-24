"""Headline KPIs plus a machine-readable KPI catalogue.

Every KPI carries its own definition, formula and provenance so that any number
shown in the dashboard or report can be traced back to a source field
(PRD §30 traceability). Retention KPIs use the **real** churn outcome from the
membership source; platform KPIs use the **real** activity source.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from ..common.logging_utils import get_logger

logger = get_logger("analytics.kpis")


@dataclass(frozen=True)
class KpiDefinition:
    key: str
    label: str
    definition: str
    formula: str
    source: str
    unit: str = "count"
    provenance: str = "real"


KPI_CATALOGUE: tuple[KpiDefinition, ...] = (
    KpiDefinition(
        key="total_members",
        label="Total Members",
        definition="Distinct members present in the membership source.",
        formula="count(distinct member_id)",
        source="membership",
        unit="members",
    ),
    KpiDefinition(
        key="retained_members",
        label="Retained Members",
        definition="Members whose churn indicator is No.",
        formula="count(member_id where churn_status = False)",
        source="membership",
        unit="members",
    ),
    KpiDefinition(
        key="churned_members",
        label="Churned Members",
        definition="Members whose churn indicator is Yes.",
        formula="count(member_id where churn_status = True)",
        source="membership",
        unit="members",
    ),
    KpiDefinition(
        key="retention_rate",
        label="Retention Rate",
        definition="Share of eligible members retained (source churn label).",
        formula="retained_members / total_members",
        source="membership",
        unit="%",
    ),
    KpiDefinition(
        key="churn_rate",
        label="Churn Rate",
        definition="Share of eligible members churned (source churn label).",
        formula="churned_members / total_members",
        source="membership",
        unit="%",
    ),
    KpiDefinition(
        key="active_members",
        label="Active Members",
        definition="Members retained per the source churn label.",
        formula="count(member_id where churn_status = False)",
        source="membership",
        unit="members",
    ),
    KpiDefinition(
        key="recently_active_members",
        label="Recently Active Members",
        definition=(
            "Members whose last recorded visit is within the configured inactivity "
            "threshold of the observation date."
        ),
        formula="count(member_id where recency_days <= inactivity_threshold_days)",
        source="membership",
        unit="members",
    ),
    KpiDefinition(
        key="at_risk_members",
        label="At-Risk Members",
        definition="Members in the At Risk or Dormant behavioural segments.",
        formula="count(member_id where segment in {'C - At Risk','D - Dormant'})",
        source="membership + synthetic activity features",
        unit="members",
        provenance="real outcome, synthetic-dependent segment",
    ),
    KpiDefinition(
        key="avg_visits_per_month",
        label="Average Visits / Month",
        definition="Mean monthly visit rate recorded in the membership source.",
        formula="mean(visits_per_month)",
        source="membership",
        unit="visits",
    ),
    KpiDefinition(
        key="avg_workout_duration",
        label="Average Workout Duration",
        definition="Mean of the member-level average workout duration.",
        formula="mean(avg_workout_duration_min)",
        source="membership",
        unit="minutes",
    ),
    KpiDefinition(
        key="avg_engagement_score",
        label="Average Engagement Score",
        definition="Mean weighted engagement composite (0-100).",
        formula="mean(engagement_score)",
        source="derived (configurable weights)",
        unit="score",
        provenance="derived",
    ),
    KpiDefinition(
        key="avg_longest_streak",
        label="Average Longest Streak",
        definition="Mean of each member's longest run of consecutive active days.",
        formula="mean(longest_streak)",
        source="synthetic activity calendar",
        unit="days",
        provenance="synthetic date placement",
    ),
    KpiDefinition(
        key="platform_events",
        label="Recorded Sessions",
        definition="Rows in the activity source (scheduled sessions).",
        formula="count(workout_id)",
        source="activity",
        unit="sessions",
    ),
    KpiDefinition(
        key="platform_attendance_rate",
        label="Platform Attendance Rate",
        definition="Share of recorded sessions with attendance status Present.",
        formula="sum(is_present) / count(workout_id)",
        source="activity",
        unit="%",
    ),
    KpiDefinition(
        key="platform_confirmed_duration_share",
        label="Confirmed Duration Share",
        definition=(
            "Share of total recorded minutes belonging to attended sessions; "
            "exposes that the source records nominal duration for absent sessions."
        ),
        formula="sum(confirmed_duration_minutes) / sum(duration_minutes)",
        source="activity",
        unit="%",
    ),
    KpiDefinition(
        key="synthetic_events",
        label="Synthetic Bridge Events",
        definition=(
            "Rows in the documented synthetic activity calendar used to demonstrate "
            "multi-source integration. Generated dates; real measures and outcomes."
        ),
        formula="count(synthetic workout_id)",
        source="synthetic integration layer",
        unit="events",
        provenance="synthetic date placement",
    ),
    KpiDefinition(
        key="synthetic_members",
        label="Members in Synthetic Bridge",
        definition="Distinct members covered by the synthetic activity calendar.",
        formula="count(distinct member_id in synthetic events)",
        source="synthetic integration layer",
        unit="members",
        provenance="synthetic date placement",
    ),
)


def kpi_catalogue_frame() -> pd.DataFrame:
    """The KPI catalogue as a table (used by the dashboard and report)."""
    return pd.DataFrame([asdict(definition) for definition in KPI_CATALOGUE])


def _pct(numerator: float, denominator: float) -> float:
    if not denominator:
        return 0.0
    return round(100.0 * float(numerator) / float(denominator), 4)


def headline_kpis(
    member_features: pd.DataFrame,
    platform_daily: Optional[pd.DataFrame] = None,
    fact_workout: Optional[pd.DataFrame] = None,
    inactivity_threshold_days: int = 14,
) -> Dict[str, Any]:
    """Compute every headline KPI from the analytical frames.

    Robust to missing optional inputs: unavailable metrics are reported as
    ``None`` with an explanatory note instead of crashing (PRD §34).
    """
    kpis: Dict[str, Any] = {}
    notes: List[str] = []

    if member_features is None or member_features.empty:
        notes.append("Member features unavailable; member-level KPIs are not reported.")
        members = pd.DataFrame()
    else:
        members = member_features

    if not members.empty:
        total = int(len(members))
        # The churn outcome can be genuinely absent from a loaded dataset. In that
        # case retention/churn are reported as unavailable (None) — never assumed
        # to be zero, which would be an invented business result.
        if "is_churned" in members.columns and members["is_churned"].notna().any():
            # Rates are computed over members whose outcome is actually recorded,
            # so a partially-populated churn column cannot distort them.
            known_mask = members["is_churned"].notna()
            outcome_known = int(known_mask.sum())
            outcome_available = outcome_known > 0
            churned = int(members.loc[known_mask, "is_churned"].astype(bool).sum())
            retained = outcome_known - churned
        else:
            outcome_available = False
            outcome_known = 0
            churned = retained = None
            notes.append(
                "No churn/retention outcome is present in the loaded dataset, so retention and "
                "churn rates are not reported."
            )

        def _mean(column: str):
            if column not in members.columns:
                return None
            series = pd.to_numeric(members[column], errors="coerce").dropna()
            return round(float(series.mean()), 6) if not series.empty else None

        def _median(column: str):
            if column not in members.columns:
                return None
            series = pd.to_numeric(members[column], errors="coerce").dropna()
            return round(float(series.median()), 4) if not series.empty else None

        kpis.update(
            {
                "outcome_available": outcome_available,
                "outcome_known_members": outcome_known,
                "population": "members",
                "total_members": total,
                "retained_members": retained,
                "churned_members": churned,
                "active_members": retained,
                "retention_rate": _pct(retained, outcome_known) if outcome_available else None,
                "churn_rate": _pct(churned, outcome_known) if outcome_available else None,
                "avg_visits_per_month": _mean("visits_per_month"),
                "avg_workout_duration": _mean("avg_workout_duration_min"),
                "avg_engagement_score": _mean("engagement_score"),
                "avg_longest_streak": _mean("longest_streak"),
                "at_risk_members": (
                    int(members["segment"].isin(["C - At Risk", "D - Dormant"]).sum())
                    if "segment" in members
                    else None
                ),
                "recently_active_members": (
                    int(
                        (
                            pd.to_numeric(members["recency_days"], errors="coerce")
                            <= inactivity_threshold_days
                        ).sum()
                    )
                    if "recency_days" in members
                    else None
                ),
                "median_recency_days": _median("recency_days"),
            }
        )
        if outcome_available and outcome_known < total:
            notes.append(
                f"The churn outcome is recorded for {outcome_known} of {total} members; retention and "
                "churn rates are computed over those members only."
            )
        if kpis.get("recently_active_members") is not None and total:
            notes.append(
                f"Only {kpis['recently_active_members']} of {total} members visited within "
                f"{inactivity_threshold_days} days of the observation date. The membership "
                "source's last-visit dates are widely dispersed, so this reflects source date "
                "behaviour as much as member disengagement."
            )

    if fact_workout is not None and not fact_workout.empty:
        events = int(len(fact_workout))
        present = int(fact_workout["is_present"].sum())
        total_duration = float(pd.to_numeric(fact_workout["duration_minutes"], errors="coerce").sum())
        confirmed_duration = float(
            pd.to_numeric(fact_workout["confirmed_duration_minutes"], errors="coerce").sum()
        )
        kpis.update(
            {
                "platform_events": events,
                "platform_attended_sessions": present,
                "platform_absent_sessions": events - present,
                "platform_attendance_rate": _pct(present, events),
                "platform_confirmed_duration_share": _pct(confirmed_duration, total_duration),
                "platform_total_recorded_hours": round(total_duration / 60.0, 2),
                "platform_confirmed_hours": round(confirmed_duration / 60.0, 2),
            }
        )

    if platform_daily is not None and not platform_daily.empty:
        kpis.update(
            {
                "platform_active_days": int(platform_daily["is_active_day"].sum()),
                "platform_calendar_days": int(len(platform_daily)),
                "platform_longest_active_streak": int(platform_daily["platform_streak"].max()),
            }
        )

    kpis["notes"] = notes
    kpis["inactivity_threshold_days"] = inactivity_threshold_days
    return kpis


def platform_kpis(
    platform_daily: Optional[pd.DataFrame] = None,
    fact_workout: Optional[pd.DataFrame] = None,
    member_activity: Optional[pd.DataFrame] = None,
) -> Dict[str, Any]:
    """Headline KPIs for an activity-only dataset.

    Used when the loaded data contains event-level activity but no membership or
    churn source. Member-level outcomes are deliberately absent rather than
    guessed; ``population`` tells the UI which KPI set it is rendering.
    """
    kpis: Dict[str, Any] = {"population": "platform", "outcome_available": False}
    notes: List[str] = [
        "Only an activity source is loaded, so member retention and churn are out of scope. "
        "These KPIs describe recorded activity at platform level."
    ]

    if fact_workout is not None and not fact_workout.empty:
        events = int(len(fact_workout))
        present = int(fact_workout["is_present"].sum())
        durations = pd.to_numeric(fact_workout.get("duration_minutes"), errors="coerce")
        calories = pd.to_numeric(fact_workout.get("calories_burned"), errors="coerce")
        confirmed = pd.to_numeric(fact_workout.get("confirmed_duration_minutes"), errors="coerce")
        kpis.update(
            {
                "platform_events": events,
                "platform_attended_sessions": present,
                "platform_absent_sessions": events - present,
                "platform_attendance_rate": _pct(present, events),
                "platform_confirmed_duration_share": _pct(confirmed.sum(), durations.sum()),
                "platform_total_recorded_hours": round(float(durations.sum()) / 60.0, 2),
                "platform_confirmed_hours": round(float(confirmed.sum()) / 60.0, 2),
                "platform_avg_duration": round(float(durations.mean()), 4) if durations.notna().any() else None,
                "platform_avg_calories": round(float(calories.mean()), 4) if calories.notna().any() else None,
                "workout_types": int(fact_workout["workout_type"].nunique())
                if "workout_type" in fact_workout
                else None,
            }
        )
        observed = pd.to_datetime(fact_workout["workout_date"], errors="coerce")
        if observed.notna().any():
            kpis["period_start"] = str(observed.min().date())
            kpis["period_end"] = str(observed.max().date())

    if platform_daily is not None and not platform_daily.empty:
        kpis.update(
            {
                "platform_active_days": int(platform_daily["is_active_day"].sum()),
                "platform_calendar_days": int(len(platform_daily)),
                "platform_longest_active_streak": int(platform_daily["platform_streak"].max()),
            }
        )

    if member_activity is not None and not member_activity.empty:
        if "longest_streak" in member_activity:
            kpis["avg_longest_streak"] = round(
                float(pd.to_numeric(member_activity["longest_streak"], errors="coerce").mean()), 4
            )
            kpis["member_streak_features"] = int(len(member_activity))
        if "consistency" in member_activity:
            kpis["avg_consistency"] = round(
                float(pd.to_numeric(member_activity["consistency"], errors="coerce").mean()), 6
            )

    kpis["notes"] = notes
    return kpis


def kpi_display_frame(kpis: Dict[str, Any]) -> pd.DataFrame:
    """Format KPIs for display with units and labels from the catalogue."""
    rows: List[Dict[str, Any]] = []
    for definition in KPI_CATALOGUE:
        value = kpis.get(definition.key)
        if value is None:
            continue
        if definition.unit == "%":
            display = f"{value:.2f}%"
        elif definition.unit == "minutes":
            display = f"{value:.1f} min"
        elif definition.unit == "score":
            display = f"{value:.1f} / 100"
        else:
            display = f"{value:,.0f}" if isinstance(value, (int, float)) else str(value)
        rows.append(
            {
                "kpi": definition.label,
                "value": display,
                "unit": definition.unit,
                "definition": definition.definition,
                "provenance": definition.provenance,
            }
        )
    return pd.DataFrame(rows)


def kpi_value(kpis: Dict[str, Any], key: str, default: Any = None) -> Any:
    return kpis.get(key, default)


def format_pct(value: Optional[float], digits: int = 2) -> str:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "n/a"
    return f"{value:.{digits}f}%"

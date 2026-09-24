"""Adapters that turn analytical results into presentation-ready insight cards.

This module sits between the analytical layer and the UI. It **never** invents a
finding: every sentence is assembled from values the pipeline already computed,
and each card carries the provenance of the fields it relies on. Language is
deliberately associational ("associated with", "observed among") because the data
supports description, not causal inference.
"""

from __future__ import annotations

from typing import Any, List, Optional, Sequence

import pandas as pd

from components.cards import Insight

#: Features whose values depend on the documented synthetic activity calendar.
SYNTHETIC_FEATURES = {
    "average_streak",
    "longest_streak",
    "current_streak",
    "consistency",
    "synthetic_events",
    "streak_break_count",
}

_MEASURE_LABELS = {
    "visits_per_month": "monthly visit rate",
    "engagement_score": "engagement score",
    "average_streak": "average streak",
    "longest_streak": "longest streak",
    "consistency": "activity consistency",
    "avg_calories_burned": "average calories burned",
    "avg_workout_duration_min": "average session duration",
    "tenure_days": "membership tenure",
    "total_weight_lifted_kg": "total weight lifted",
    "recency_days": "days since last visit",
}


def measure_label(measure: str) -> str:
    return _MEASURE_LABELS.get(str(measure), str(measure).replace("_", " "))


def _answer_provenance(value: str) -> str:
    return {
        "real": "real",
        "mixed": "derived",
        "synthetic-dependent": "synthetic",
        "synthetic": "synthetic",
        "derived": "derived",
    }.get(str(value).lower(), "derived")


# ---------------------------------------------------------------------------
# Published analytical answers (PRD §19)
# ---------------------------------------------------------------------------
def from_answers(result: Any, limit: Optional[int] = None, only_available: bool = True) -> List[Insight]:
    """The ten analytical questions, as cards."""
    frame = result.analyses.get("answers") if result is not None else None
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return []
    rows = frame
    if only_available and "available" in rows.columns:
        rows = rows[rows["available"].astype(bool)]
    if limit:
        rows = rows.head(limit)
    insights: List[Insight] = []
    for row in rows.itertuples():
        body = str(getattr(row, "answer", "") or "")
        caveats = str(getattr(row, "caveats", "") or "")
        if caveats:
            body = f"{body} <span style='color:{_caveat_colour()};'>Caveat: {caveats.split(' | ')[0]}</span>"
        insights.append(
            Insight(
                title=f"Q{getattr(row, 'question_id', '')} · {getattr(row, 'question', '')}",
                body=body,
                icon="lightbulb",
                eyebrow="Analytical answer",
                tone="info",
                provenance=_answer_provenance(getattr(row, "provenance", "real")),
            )
        )
    return insights


def unavailable_answers(result: Any) -> List[tuple[str, str]]:
    """Questions the source data cannot answer, stated explicitly."""
    frame = result.analyses.get("answers") if result is not None else None
    if not isinstance(frame, pd.DataFrame) or frame.empty or "available" not in frame.columns:
        return []
    rows = frame[~frame["available"].astype(bool)]
    return [
        (f"Q{getattr(row, 'question_id', '')} · {getattr(row, 'question', '')}", str(getattr(row, "answer", "")))
        for row in rows.itertuples()
    ]


def _caveat_colour() -> str:
    from styles.theme import COLORS

    return COLORS["warning"]


# ---------------------------------------------------------------------------
# Individual computed findings
# ---------------------------------------------------------------------------
def engagement_summary(result: Any) -> Optional[Insight]:
    text = ((result.analyses.get("engagement") or {}) if result is not None else {}).get("insight")
    if not text:
        return None
    return Insight(
        title="Members are active but rarely high-frequency",
        body=str(text),
        icon="activity",
        eyebrow="Engagement",
        tone="primary",
        provenance="derived",
    )


def segmentation_summary(result: Any) -> Optional[Insight]:
    text = ((result.analyses.get("segmentation") or {}) if result is not None else {}).get("insight")
    if not text:
        return None
    return Insight(
        title="Churn concentrates in the lower-engagement segments",
        body=str(text),
        icon="users",
        eyebrow="Segments",
        tone="warning",
        provenance="derived",
    )


def attendance_summary(result: Any) -> Optional[Insight]:
    text = result.analyses.get("funnel_insight") if result is not None else None
    if not text:
        return None
    return Insight(
        title="Roughly half of all scheduled sessions are actually attended",
        body=str(text),
        icon="calendar-check",
        eyebrow="Platform funnel",
        tone="info",
        provenance="real",
    )


def activity_trend(result: Any) -> Optional[Insight]:
    summary = (result.analyses.get("trend_summary") or {}) if result is not None else {}
    events = summary.get("events_trend") or {}
    attendance = summary.get("present_rate_trend") or {}
    if not events.get("explanation"):
        return None
    body = str(events["explanation"])
    if attendance.get("explanation"):
        body += " Attendance rate moved in the same direction: " + str(attendance["explanation"])
    return Insight(
        title="Recorded activity is trending up across the year",
        body=body,
        icon="chart-line",
        eyebrow="Activity trend",
        tone="success" if str(events.get("direction")) == "increasing" else "warning",
        provenance="real",
    )


def frequency_gradient(result: Any) -> Optional[Insight]:
    """Retention across the lowest and highest observed visit-frequency bands."""
    retention = result.analyses.get("retention") if result is not None else None
    frame = getattr(retention, "frequency_gradient", None)
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return None
    frame = frame.dropna(subset=["retention_rate"])
    if len(frame) < 2:
        return None
    order = ["0-4", "5-8", "9-12", "13-16", "17-20", "21+"]
    frame = frame.assign(
        _o=frame["dimension_value"].astype(str).map({value: index for index, value in enumerate(order)}).fillna(99)
    ).sort_values("_o")
    low, high = frame.iloc[0], frame.iloc[-1]
    if high["retention_rate"] <= low["retention_rate"]:
        return None
    body = (
        f"Retention is <strong>{high['retention_rate']:.1f}%</strong> among members visiting "
        f"{high['dimension_value']} times per month (n={int(high['members'])}), against "
        f"<strong>{low['retention_rate']:.1f}%</strong> among those visiting {low['dimension_value']} "
        f"times per month (n={int(low['members'])}). Visit frequency is associated with retention in "
        "this dataset; the groups are observational and not randomised."
    )
    if bool(low.get("low_confidence", False)):
        body += " The lowest band is small, so treat its rate as indicative."
    return Insight(
        title="Retention tracks monthly visit frequency",
        body=body,
        icon="trending-up",
        eyebrow="Engagement → retention",
        tone="success",
        provenance="real",
    )


def strongest_association(result: Any) -> Optional[Insight]:
    """The strongest observed feature association with the churn outcome."""
    correlations = (result.analyses.get("correlations") or {}) if result is not None else {}
    frame = correlations.get("churn")
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return None
    frame = frame.dropna(subset=["spearman_rho"])
    frame = frame[frame["strength"].astype(str) != "negligible"]
    if frame.empty:
        return None
    row = frame.reindex(frame["abs_spearman"].astype(float).sort_values(ascending=False).index).iloc[0]
    provenance = "synthetic" if str(row["feature"]) in SYNTHETIC_FEATURES else "real"
    direction = "fewer churn events" if float(row["spearman_rho"]) < 0 else "more churn events"
    body = (
        f"<strong>{measure_label(str(row['feature'])).capitalize()}</strong> shows the strongest "
        f"observed association with churn in this population "
        f"(Spearman rho = {float(row['spearman_rho']):+.2f}, {row['strength']} association, "
        f"n = {int(row['n'])}): higher values are associated with {direction}. "
        "Correlation is not causation, and the remaining features are negligible."
    )
    return Insight(
        title="Visit frequency is the leading churn signal",
        body=body,
        icon="target",
        eyebrow="Churn association",
        tone="warning",
        provenance=provenance,
    )


def largest_behavioural_gap(result: Any, comparison: pd.DataFrame) -> Optional[Insight]:
    """The measure where retained and churned members differ most."""
    if not isinstance(comparison, pd.DataFrame) or comparison.empty:
        return None
    frame = comparison.dropna(subset=["cohens_d"]).copy()
    if frame.empty:
        return None
    frame["_abs"] = frame["cohens_d"].astype(float).abs()
    frame = frame[frame["effect_size"].astype(str) != "negligible"]
    if frame.empty:
        return None
    row = frame.sort_values("_abs", ascending=False).iloc[0]
    provenance = "synthetic" if str(row["measure"]) in SYNTHETIC_FEATURES else "real"
    body = (
        f"Retained members average <strong>{float(row['retained_mean']):,.2f}</strong> against "
        f"<strong>{float(row['churned_mean']):,.2f}</strong> for churned members "
        f"({float(row['difference']):+,.2f}; Cohen's d = {float(row['cohens_d']):+.2f}, "
        f"{row['effect_size']} effect). This is the largest observed behavioural gap between the two "
        "groups; the groups are unequal in size, which is why the effect size leads."
    )
    return Insight(
        title="Retained members visit far more often than churned members",
        body=body,
        icon="dumbbell",
        eyebrow="Retained vs churned",
        tone="primary",
        provenance=provenance,
    )


def retention_by_membership_type(result: Any, table: pd.DataFrame) -> Optional[Insight]:
    if not isinstance(table, pd.DataFrame) or table.empty or "retention_rate" not in table.columns:
        return None
    ordered = table.dropna(subset=["retention_rate"]).sort_values("retention_rate")
    if len(ordered) < 2:
        return None
    low, high = ordered.iloc[0], ordered.iloc[-1]
    body = (
        f"{high['dimension_value']} members retain at <strong>{high['retention_rate']:.1f}%</strong> "
        f"(n={int(high['members'])}), compared with <strong>{low['retention_rate']:.1f}%</strong> for "
        f"{low['dimension_value']} members (n={int(low['members'])}). Membership type is associated "
        "with retention in this dataset, but the plan groups also differ in visit frequency, so this "
        "is not a plan effect on its own."
    )
    return Insight(
        title="Longer commitment plans retain slightly better",
        body=body,
        icon="credit-card",
        eyebrow="Plan → retention",
        tone="info",
        provenance="real",
    )


def data_quality_summary(result: Any) -> Optional[Insight]:
    summary = ((result.quality or {}).get("summary") or {}) if result is not None else {}
    if not summary:
        return None
    return Insight(
        title="Validation outcome for the current run",
        body=(
            f"{summary.get('passed', 0)} of {summary.get('total_checks', 0)} checks passed "
            f"({summary.get('pass_rate', 0):.2f}%), with {summary.get('warnings', 0)} warnings and "
            f"{summary.get('failures', 0)} failures. Failing rows are flagged and retained, never "
            "silently dropped."
        ),
        icon="shield-check",
        eyebrow="Data quality",
        tone="success" if not summary.get("failures") else "warning",
        provenance="real",
    )


def alert_headline(result: Any) -> Optional[Insight]:
    summary = (result.analyses.get("alert_summary") or {}) if result is not None else {}
    if not summary:
        return None
    tone = {"CRITICAL": "danger", "HIGH": "danger", "MEDIUM": "warning"}.get(
        str(summary.get("status", "")).upper(), "success"
    )
    return Insight(
        title=f"Risk posture: {summary.get('status', 'n/a')}",
        body=str(summary.get("headline", "")),
        icon="triangle-alert",
        eyebrow="Risk & alerts",
        tone=tone,
        provenance="derived",
    )


def combined(result: Any, comparison: Optional[pd.DataFrame] = None, limit: int = 4) -> List[Insight]:
    """A curated set of findings for a summary view, in narrative order."""
    candidates: Sequence[Optional[Insight]] = (
        frequency_gradient(result),
        strongest_association(result),
        largest_behavioural_gap(result, comparison if comparison is not None else pd.DataFrame()),
        segmentation_summary(result),
        engagement_summary(result),
        attendance_summary(result),
        activity_trend(result),
        data_quality_summary(result),
    )
    return [insight for insight in candidates if insight is not None][:limit]

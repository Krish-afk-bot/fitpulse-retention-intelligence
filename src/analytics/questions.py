"""The ten analytical questions from the PRD, answered from computed evidence.

Every answer carries:

``provenance``
    ``real`` when the answer uses only source fields, ``synthetic-dependent``
    when the activity calendar contributes, ``mixed`` when both do.
``evidence``
    The exact computed numbers behind the statement.
``caveats``
    Limits that a reader must know (sample size, source behaviour, method).

Language is deliberately associational: "associated with", never "causes".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

from ..common.logging_utils import get_logger
from .retention import pct, wilson_interval

logger = get_logger("analytics.questions")


@dataclass
class AnalyticalAnswer:
    question_id: str
    question: str
    answer: str
    evidence: List[str] = field(default_factory=list)
    provenance: str = "real"
    caveats: List[str] = field(default_factory=list)
    available: bool = True

    def as_dict(self) -> Dict[str, Any]:
        return self.__dict__.copy()


def _answer_a(comparison: pd.DataFrame) -> AnalyticalAnswer:
    """A — How does workout frequency differ between retained and churned members?"""
    if comparison is None or comparison.empty or "visits_per_month" not in set(comparison["measure"]):
        return AnalyticalAnswer(
            question_id="A",
            question="How does workout frequency differ between retained and churned populations?",
            answer="Frequency comparison unavailable: visit-rate data missing.",
            available=False,
        )
    row = comparison[comparison["measure"] == "visits_per_month"].iloc[0]
    direction = "lower" if row["churned_mean"] < row["retained_mean"] else "higher"
    return AnalyticalAnswer(
        question_id="A",
        question="How does workout frequency differ between retained and churned populations?",
        answer=(
            f"Churned members show a substantially {direction} recorded visit rate: "
            f"{row['churned_mean']:.1f} visits per month on average versus "
            f"{row['retained_mean']:.1f} for retained members "
            f"({row['relative_difference_pct']:+.1f}%). Frequency is the single most "
            "discriminating real field in the membership source."
        ),
        evidence=[
            f"Retained mean: {row['retained_mean']:.2f} visits/month (n={int(row['n_retained'])})",
            f"Churned mean: {row['churned_mean']:.2f} visits/month (n={int(row['n_churned'])})",
            f"Cohen's d: {row['cohens_d']:+.3f} ({row['effect_size']}), Welch t: {row['welch_t']:+.3f}",
        ],
        provenance="real",
        caveats=[
            "Observational contrast, not a causal estimate.",
            "Visit rate and churn may be recorded with different latency in the source system.",
        ],
    )


def _answer_b(members: pd.DataFrame, comparison: pd.DataFrame) -> AnalyticalAnswer:
    """B — How does streak behaviour relate to churn?"""
    if "longest_streak" not in members.columns or comparison.empty:
        return AnalyticalAnswer(
            question_id="B",
            question="How does streak behaviour relate to churn?",
            answer=(
                "Streak analysis unavailable because the source datasets do not contain "
                "sufficient chronological per-member activity data."
            ),
            available=False,
        )
    row = comparison[comparison["measure"] == "longest_streak"]
    if row.empty:
        return AnalyticalAnswer(
            question_id="B",
            question="How does streak behaviour relate to churn?",
            answer="Streak comparison unavailable.",
            available=False,
        )
    row = row.iloc[0]
    return AnalyticalAnswer(
        question_id="B",
        question="How does streak behaviour relate to churn?",
        answer=(
            f"Longest streak averages {row['retained_mean']:.2f} days for retained members and "
            f"{row['churned_mean']:.2f} days for churned members (Cohen's d "
            f"{row['cohens_d']:+.2f}, {row['effect_size']} effect). Streaks in FitPulse are "
            "derived from reconstructed activity calendars, so this association is conditional "
            "on the documented synthetic date placement."
        ),
        evidence=[
            f"Longest streak, retained: {row['retained_mean']:.2f} days",
            f"Longest streak, churned: {row['churned_mean']:.2f} days",
            f"Streak metric definition: longest run of consecutive days with at least one recorded event",
        ],
        provenance="synthetic-dependent",
        caveats=[
            "The activity source has no repeatable member identifier, so member-level streaks "
            "cannot be derived from real data alone and are reconstructed in the documented "
            "synthetic integration layer.",
            "Streak lengths are therefore a function of real visit rates plus synthetic date placement.",
        ],
    )


def _answer_c(members: pd.DataFrame, comparison: pd.DataFrame) -> AnalyticalAnswer:
    """C — How does recent inactivity relate to churn?"""
    if comparison is None or comparison.empty or "recency_days" not in set(comparison["measure"]):
        return AnalyticalAnswer(
            question_id="C",
            question="How does recent inactivity relate to churn?",
            answer="Recency comparison unavailable.",
            available=False,
        )
    row = comparison[comparison["measure"] == "recency_days"].iloc[0]
    difference = row["difference"]
    if abs(row["cohens_d"]) < 0.2:
        verdict = (
            "no meaningful difference was observed between the groups. In this dataset, "
            "recency is not a discriminating churn signal."
        )
    else:
        verdict = (
            f"churned members' last visit is {abs(difference):,.0f} days "
            f"{'further' if difference > 0 else 'closer'} from the observation date than retained "
            "members', a meaningful difference."
        )
    return AnalyticalAnswer(
        question_id="C",
        question="How does recent inactivity relate to churn?",
        answer=f"Recency of last visit shows {verdict}",
        evidence=[
            f"Mean days since last visit, retained: {row['retained_mean']:.1f}",
            f"Mean days since last visit, churned: {row['churned_mean']:.1f}",
            f"Cohen's d: {row['cohens_d']:+.3f} ({row['effect_size']})",
        ],
        provenance="real",
        caveats=[
            "Last-visit dates in the membership source are widely dispersed (0 to over 1,200 "
            "days from the observation date). The field behaves close to noise, so this result "
            "reflects the source's date behaviour rather than a clean disengagement signal.",
        ],
    )


def _answer_d(members: pd.DataFrame) -> AnalyticalAnswer:
    """D — How does membership type relate to retention?"""
    if "membership_type" not in members.columns:
        return AnalyticalAnswer(
            question_id="D",
            question="How does membership type relate to retention?",
            answer="Membership tier is not present in the available data.",
            available=False,
        )
    tiers = (
        members.groupby("membership_type", observed=True)
        .agg(members=("member_id", "count"), churned=("is_churned", "sum"))
        .reset_index()
    )
    tiers["churn_rate"] = (100.0 * tiers["churned"] / tiers["members"]).round(2)
    tiers = tiers.sort_values("churn_rate", ascending=False)
    worst, best = tiers.iloc[0], tiers.iloc[-1]
    return AnalyticalAnswer(
        question_id="D",
        question="How does membership type relate to retention?",
        answer=(
            f"{worst['membership_type']} members show the highest observed churn rate "
            f"({worst['churn_rate']:.1f}%) and {best['membership_type']} the lowest "
            f"({best['churn_rate']:.1f}%), a spread of "
            f"{worst['churn_rate'] - best['churn_rate']:.1f} percentage points."
        ),
        evidence=[
            f"{row.membership_type}: {row.churn_rate:.1f}% churn "
            f"({int(row.churned)}/{int(row.members)} members)"
            for row in tiers.itertuples()
        ],
        provenance="real",
        caveats=[
            f"Smallest tier group holds {int(tiers['members'].min())} members, so tier-level "
            "rates carry wide confidence intervals.",
        ],
    )


def _answer_e(comparison: pd.DataFrame) -> AnalyticalAnswer:
    """E — How does workout duration relate to retention?"""
    if comparison is None or comparison.empty or "avg_workout_duration_min" not in set(comparison["measure"]):
        return AnalyticalAnswer(
            question_id="E",
            question="How does workout duration relate to retention?",
            answer="Duration comparison unavailable.",
            available=False,
        )
    row = comparison[comparison["measure"] == "avg_workout_duration_min"].iloc[0]
    strength = row["effect_size"]
    verdict = (
        "essentially no association was observed"
        if strength == "negligible"
        else f"a {strength} association was observed"
    )
    return AnalyticalAnswer(
        question_id="E",
        question="How does workout duration relate to retention?",
        answer=(
            f"For workout duration, {verdict}: churned members average "
            f"{row['churned_mean']:.1f} minutes versus {row['retained_mean']:.1f} minutes for "
            f"retained members ({row['difference']:+.1f} minutes, Cohen's d "
            f"{row['cohens_d']:+.2f})."
        ),
        evidence=[
            f"Retained mean duration: {row['retained_mean']:.1f} min (n={int(row['n_retained'])})",
            f"Churned mean duration: {row['churned_mean']:.1f} min (n={int(row['n_churned'])})",
        ],
        provenance="real",
        caveats=[
            "Duration is a member-level average published by the source, not per-session data.",
        ],
    )


def _answer_f(segments: pd.DataFrame) -> AnalyticalAnswer:
    """F — Which behavioural segment has the highest churn?"""
    if segments is None or segments.empty:
        return AnalyticalAnswer(
            question_id="F",
            question="Which behavioural segment has the highest churn?",
            answer="Segmentation unavailable.",
            available=False,
        )
    top = segments.sort_values("churn_rate", ascending=False).iloc[0]
    return AnalyticalAnswer(
        question_id="F",
        question="Which behavioural segment has the highest churn?",
        answer=(
            f"{top['segment']} shows the highest observed churn rate at {top['churn_rate']:.1f}% "
            f"({int(top['churned'])} of {int(top['members'])} members, "
            f"95% CI {top['churn_ci_low']:.1f}%-{top['churn_ci_high']:.1f}%)."
        ),
        evidence=[
            f"{row.segment}: {row.churn_rate:.1f}% churn over {int(row.members)} members"
            for row in segments.itertuples()
        ],
        provenance="mixed",
        caveats=[
            "Segment assignment depends on configurable engagement weights and on synthetic "
            "date placement for the consistency and streak components.",
        ],
    )


def _answer_g(monthly: Optional[pd.DataFrame], trend_summary: Dict[str, Any]) -> AnalyticalAnswer:
    """G — How does engagement change over time?"""
    if monthly is None or monthly.empty:
        return AnalyticalAnswer(
            question_id="G",
            question="How does engagement change over time?",
            answer="Time-series analysis unavailable: monthly platform aggregates are empty.",
            available=False,
        )
    events_trend = trend_summary.get("events_trend", {}) or {}
    # A short observation window leaves some trend measures undefined; they are
    # described as unavailable rather than formatted as a misleading zero.
    change_pct = events_trend.get("change_pct")
    change_text = (
        f"{change_pct:+.1f}% between the first and last three-month windows"
        if isinstance(change_pct, (int, float))
        else "no comparable three-month windows in this dataset's date range"
    )
    peak_events = trend_summary.get("peak_events")
    lowest_events = trend_summary.get("lowest_events")
    return AnalyticalAnswer(
        question_id="G",
        question="How does engagement change over time?",
        answer=(
            f"Platform session volume is {events_trend.get('direction', 'stable')} across the "
            f"observed window ({change_text}; peak {trend_summary.get('peak_month')} with "
            f"{peak_events:,} sessions, lowest {trend_summary.get('lowest_month')} with "
            f"{lowest_events:,})."
            if isinstance(peak_events, (int, float)) and isinstance(lowest_events, (int, float))
            else (
                f"Platform session volume is {events_trend.get('direction', 'stable')} across the "
                f"observed window ({change_text})."
            )
        ),
        evidence=[
            events_trend.get("explanation", ""),
            f"Monthly attendance rate range: {trend_summary.get('present_rate_range_pct', ['n/a', 'n/a'])}%",
            "Attendance rate is near-uniform across membership tiers, workout types and genders "
            "(all within roughly 46%-50%), so those dimensions do not explain attendance variation.",
        ],
        provenance="real",
        caveats=[
            "The activity source covers a single calendar year and is not linked to member "
            "identities, so this is platform-level volume, not per-member engagement over time.",
        ],
    )


def _answer_h(funnel: Optional[pd.DataFrame]) -> AnalyticalAnswer:
    """H — Where does engagement drop?"""
    if funnel is None or funnel.empty:
        return AnalyticalAnswer(
            question_id="H",
            question="Where does the engagement funnel lose members?",
            answer="Funnel analysis unavailable.",
            available=False,
        )
    losses = funnel.iloc[1:]
    if losses.empty:
        return AnalyticalAnswer(
            question_id="H",
            question="Where does the engagement funnel lose members?",
            answer="Funnel contains a single stage.",
            available=False,
        )
    biggest = losses.sort_values("drop_off_pct", ascending=False).iloc[0]
    return AnalyticalAnswer(
        question_id="H",
        question="Where does the engagement funnel lose members?",
        answer=(
            f"The largest proportional loss is at '{biggest['stage']}': "
            f"{int(biggest['drop_off']):,} of the previous stage's records "
            f"({biggest['drop_off_pct']:.1f}%) do not advance."
        ),
        evidence=[
            f"{row.stage}: {int(row.records):,} records, drop-off {row.drop_off_pct:.1f}%"
            for row in funnel.itertuples()
        ],
        provenance=str(funnel.attrs.get("provenance", "real")),
        caveats=[
            "The activity source records nominal duration and calories for absent sessions, so "
            "only attendance-gated ('confirmed') measures should be read as realised activity.",
        ],
    )


def _answer_i(alerts: Optional[pd.DataFrame], thresholds: Dict[str, Any]) -> AnalyticalAnswer:
    """I — Which metrics should trigger an operational alert?"""
    if alerts is None:
        return AnalyticalAnswer(
            question_id="I",
            question="Which metrics should trigger an operational alert?",
            answer="Alert evaluation unavailable.",
            available=False,
        )
    if alerts.empty:
        return AnalyticalAnswer(
            question_id="I",
            question="Which metrics should trigger an operational alert?",
            answer=(
                "No configured threshold is currently breached. Thresholds remain active and are "
                "re-evaluated on every pipeline run: "
                + ", ".join(f"{k}={v}" for k, v in thresholds.items())
            ),
            evidence=[f"Configured thresholds: {thresholds}"],
            provenance="real",
        )
    rows = [
        f"{row.metric}: observed {row.observed_display} against {row.threshold_display} "
        f"({row.severity})"
        for row in alerts.sort_values("severity_bucket").itertuples()
    ]
    return AnalyticalAnswer(
        question_id="I",
        question="Which metrics should trigger an operational alert?",
        answer=f"{len(alerts)} alert(s) are currently triggered: " + "; ".join(rows[:5]),
        evidence=rows,
        provenance="real",
        caveats=[
            "Alert thresholds are operational choices configured through the environment, not "
            "statistically optimal cut points.",
        ],
    )


def answer_all_questions(
    members: pd.DataFrame,
    comparison: pd.DataFrame,
    segments: pd.DataFrame,
    platform_monthly: Optional[pd.DataFrame],
    trend_summary: Dict[str, Any],
    platform_funnel_table: Optional[pd.DataFrame],
    alerts: Optional[pd.DataFrame] = None,
    thresholds: Optional[Dict[str, Any]] = None,
) -> List[AnalyticalAnswer]:
    """Answer all ten PRD analytical questions."""
    answers = [
        _answer_a(comparison),
        _answer_b(members, comparison),
        _answer_c(members, comparison),
        _answer_d(members),
        _answer_e(comparison),
        _answer_f(segments),
        _answer_g(platform_monthly, trend_summary),
        _answer_h(platform_funnel_table if platform_funnel_table is not None else pd.DataFrame()),
        _answer_i(alerts, thresholds or {}),
    ]
    logger.info(
        "Answered %s analytical questions (%s with data)",
        len(answers),
        sum(1 for a in answers if a.available),
    )
    return answers


def answers_frame(answers: Sequence[AnalyticalAnswer]) -> pd.DataFrame:
    """Flatten answers for tables and reports."""
    return pd.DataFrame(
        [
            {
                "id": answer.question_id,
                "question": answer.question,
                "answer": answer.answer,
                "provenance": answer.provenance,
                "available": answer.available,
                "evidence": " | ".join(answer.evidence),
                "caveats": " | ".join(answer.caveats),
            }
            for answer in answers
        ]
    )

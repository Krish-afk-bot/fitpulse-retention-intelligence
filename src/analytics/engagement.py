"""Engagement analytics.

Covers workout frequency, duration, activity trends, streak distribution,
workout-type mix and the relationship between engagement and the real churn
outcome. The attendance-versus-nominal contrast from the activity source is
surfaced explicitly, because the source records duration and calories for
absent sessions.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from ..common.logging_utils import get_logger
from ..features.engineer import SCORE_COMPONENTS
from .retention import pct

logger = get_logger("analytics.engagement")

HISTOGRAM_BINS = 20


def numeric_distribution(series: pd.Series, bins: int = HISTOGRAM_BINS) -> pd.DataFrame:
    """Histogram plus descriptive statistics for one numeric series."""
    numeric = pd.to_numeric(series, errors="coerce").dropna()
    if numeric.empty:
        return pd.DataFrame(columns=["bin_start", "bin_end", "count", "share_pct"])
    counts, edges = np.histogram(numeric, bins=min(bins, max(1, numeric.nunique())))
    frame = pd.DataFrame(
        {
            "bin_start": edges[:-1].round(4),
            "bin_end": edges[1:].round(4),
            "count": counts,
        }
    )
    frame["share_pct"] = (100.0 * frame["count"] / counts.sum()).round(4)
    frame["bin_label"] = [
        f"{start:,.0f}-{end:,.0f}" for start, end in zip(frame["bin_start"], frame["bin_end"])
    ]
    return frame


def describe_distribution(series: pd.Series) -> Dict[str, float]:
    numeric = pd.to_numeric(series, errors="coerce").dropna()
    if numeric.empty:
        return {}
    return {
        "count": int(len(numeric)),
        "mean": round(float(numeric.mean()), 4),
        "std": round(float(numeric.std()), 4) if len(numeric) > 1 else 0.0,
        "min": round(float(numeric.min()), 4),
        "p25": round(float(numeric.quantile(0.25)), 4),
        "median": round(float(numeric.median()), 4),
        "p75": round(float(numeric.quantile(0.75)), 4),
        "max": round(float(numeric.max()), 4),
        "skew": round(float(numeric.skew()), 4) if len(numeric) > 2 else 0.0,
    }


def attendance_contrast(fact_workout: pd.DataFrame) -> pd.DataFrame:
    """Real comparison of attended vs not-attended sessions.

    Demonstrates that duration and calories in the activity source are recorded
    for absent sessions too, which is why FitPulse keeps attendance-gated
    'confirmed' measures alongside the raw ones.
    """
    if fact_workout is None or fact_workout.empty:
        return pd.DataFrame()
    frame = fact_workout.copy()
    grouped = (
        frame.groupby("attendance_status")
        .agg(
            sessions=("workout_id", "count"),
            mean_duration=("duration_minutes", "mean"),
            median_duration=("duration_minutes", "median"),
            mean_calories=("calories_burned", "mean"),
            median_calories=("calories_burned", "median"),
            confirmed_duration=("confirmed_duration_minutes", "sum"),
            total_duration=("duration_minutes", "sum"),
        )
        .reset_index()
    )
    grouped["share_of_sessions_pct"] = (100.0 * grouped["sessions"] / len(frame)).round(4)
    grouped["confirmed_duration_share_pct"] = (
        100.0 * grouped["confirmed_duration"] / grouped["total_duration"]
    ).round(4)
    return grouped


def workout_type_mix(platform_type: pd.DataFrame) -> pd.DataFrame:
    """Session mix by workout type, with attendance and confirmed volume."""
    if platform_type is None or platform_type.empty:
        return pd.DataFrame()
    frame = platform_type.copy()
    frame["present_rate_pct"] = (100.0 * frame["present_rate"]).round(4)
    frame["event_share_pct"] = (100.0 * frame["event_share"]).round(4)
    frame["avg_duration"] = frame["avg_duration"].round(2)
    frame["avg_calories"] = frame["avg_calories"].round(2)
    return frame.sort_values("events", ascending=False).reset_index(drop=True)


def streak_distribution(members: pd.DataFrame) -> pd.DataFrame:
    """Distribution of longest-streak values across members (synthetic-dependent)."""
    if members is None or members.empty or "longest_streak" not in members.columns:
        return pd.DataFrame(columns=["streak_bucket", "members", "share_pct", "churn_rate"])
    frame = members.copy()
    frame["streak_bucket"] = pd.cut(
        frame["longest_streak"],
        bins=[-1, 0, 1, 2, 3, 5, 7, 14, 1000],
        labels=["0", "1", "2", "3", "4-5", "6-7", "8-14", "15+"],
    )
    grouped = (
        frame.groupby("streak_bucket", observed=True)
        .agg(
            members=("member_id", "count"),
            churned=("is_churned", "sum"),
            avg_visits=("visits_per_month", "mean"),
            avg_engagement=("engagement_score", "mean"),
        )
        .reset_index()
    )
    grouped["share_pct"] = (100.0 * grouped["members"] / grouped["members"].sum()).round(4)
    grouped["churn_rate"] = (100.0 * grouped["churned"] / grouped["members"]).round(4)
    return grouped.rename(columns={"streak_bucket": "streak_bucket"})


def engagement_vs_retention(members: pd.DataFrame, bins: int = 5) -> pd.DataFrame:
    """Churn rate by engagement-score decile/quantile band (real outcome)."""
    if members is None or members.empty or "engagement_score" not in members.columns:
        return pd.DataFrame(columns=["band", "members", "churn_rate", "avg_visits_per_month"])
    frame = members.copy()
    frame["band"] = pd.qcut(
        frame["engagement_score"].rank(method="first"), q=min(bins, max(2, len(frame) // 10)),
        labels=False,
    )
    grouped = (
        frame.groupby("band")
        .agg(
            members=("member_id", "count"),
            churned=("is_churned", "sum"),
            avg_engagement=("engagement_score", "mean"),
            avg_visits_per_month=("visits_per_month", "mean"),
            avg_longest_streak=("longest_streak", "mean"),
        )
        .reset_index()
    )
    grouped["churn_rate"] = (100.0 * grouped["churned"] / grouped["members"]).round(4)
    grouped["retention_rate"] = (100.0 - grouped["churn_rate"]).round(4)
    grouped["score_range"] = grouped.apply(
        lambda r: f"{frame[frame['band'] == r['band']]['engagement_score'].min():.0f}-"
        f"{frame[frame['band'] == r['band']]['engagement_score'].max():.0f}",
        axis=1,
    )
    return grouped.rename(columns={"band": "engagement_band"})


def engagement_score_profile(members: pd.DataFrame) -> pd.DataFrame:
    """Mean component scores per segment — shows what drives the composite."""
    if members is None or members.empty or "segment" not in members.columns:
        return pd.DataFrame()
    components = [c.name for c in SCORE_COMPONENTS]
    columns = [f"{c}_score" for c in components if f"{c}_score" in members.columns]
    if not columns:
        return pd.DataFrame()
    grouped = members.groupby("segment", observed=True)[columns].mean().round(2).reset_index()
    grouped["engagement_score"] = (
        members.groupby("segment", observed=True)["engagement_score"].mean().round(2).values
    )
    return grouped.sort_values("engagement_score", ascending=False).reset_index(drop=True)


def engagement_summary(
    members: pd.DataFrame,
    platform_daily: Optional[pd.DataFrame] = None,
    fact_workout: Optional[pd.DataFrame] = None,
) -> Dict[str, Any]:
    """Narrative-ready engagement summary with distributions and caveats."""
    summary: Dict[str, Any] = {}
    if members is not None and not members.empty:
        summary["visits_per_month"] = describe_distribution(members["visits_per_month"])
        summary["engagement_score"] = describe_distribution(members["engagement_score"])
        summary["longest_streak"] = describe_distribution(members["longest_streak"])
        summary["consistency"] = describe_distribution(members["consistency"])
        score_dist = describe_distribution(members["engagement_score"])
        summary["insight"] = (
            f"Mean engagement score is {score_dist.get('mean', 0):.1f}/100 (median "
            f"{score_dist.get('median', 0):.1f}), with a mean recorded visit rate of "
            f"{summary['visits_per_month'].get('mean', 0):.1f} visits per month. "
            "Frequency is the dominant real component; consistency and streak components "
            "depend on synthetic date placement."
        )
    if platform_daily is not None and not platform_daily.empty:
        summary["daily_sessions"] = describe_distribution(platform_daily["events"])
        summary["attendance_rate"] = describe_distribution(platform_daily["present_rate"] * 100.0)
    if fact_workout is not None and not fact_workout.empty:
        summary["duration"] = describe_distribution(fact_workout["duration_minutes"])
        contrast = attendance_contrast(fact_workout)
        if not contrast.empty:
            absent = contrast[contrast["attendance_status"] == "Absent"]
            if not absent.empty:
                summary["nominal_value_caveat"] = (
                    f"{int(absent.iloc[0]['sessions']):,} absent sessions still carry an average of "
                    f"{absent.iloc[0]['mean_duration']:.1f} minutes and "
                    f"{absent.iloc[0]['mean_calories']:.1f} calories. Duration and calories in the "
                    "activity source are nominal (scheduled) values, so attendance-gated measures "
                    "are reported alongside raw ones."
                )
    return summary

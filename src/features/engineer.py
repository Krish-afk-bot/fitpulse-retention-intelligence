"""Feature engineering.

Three feature families are produced, with provenance kept explicit:

``platform_activity``
    Daily and monthly platform aggregates from the **real** activity source.
``member_real_features``
    Member-level features derived **only** from real membership fields
    (visit rate, duration, calories, tenure, recency, churn outcome).
``member_features``
    The unified analytical model: real features plus activity features derived
    from the documented synthetic calendar. Every synthetic-derived column is
    listed in ``SYNTHETIC_FEATURE_COLUMNS`` so the UI and reports can label it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from ..common.config import EngagementWeights, SegmentThresholds, get_settings
from ..common.logging_utils import get_logger
from .streaks import streak_features_for_groups, platform_streak_series

logger = get_logger("features")

#: Columns in ``member_features`` whose values depend on synthetic date placement.
SYNTHETIC_FEATURE_COLUMNS: Tuple[str, ...] = (
    "synthetic_events",
    "active_days",
    "observation_days",
    "consistency",
    "workouts_per_week",
    "workouts_per_month_derived",
    "longest_streak",
    "current_streak",
    "average_streak",
    "streak_break_count",
    "max_gap_days",
    "inactive_days",
    "lifecycle_stage",
)

SEGMENT_ORDER = ("A - Highly Engaged", "B - Regular", "C - At Risk", "D - Dormant")

LIFECYCLE_STAGES = ("Registered", "First Workout", "Repeat Workout", "Consistent Activity", "Retained")

#: Lifecycle thresholds, documented and configurable at the top of this module.
LIFECYCLE_CONFIG = {
    "first_workout_min_events": 1,
    "repeat_workout_min_events": 2,
    "consistent_min_events": 8,
    "consistent_min_consistency": 0.15,
}


# ---------------------------------------------------------------------------
# Engagement score specification
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ScoreComponent:
    """One weighted input to the engagement score."""

    name: str
    label: str
    description: str
    reference: str
    formula: str


SCORE_COMPONENTS: Tuple[ScoreComponent, ...] = (
    ScoreComponent(
        name="frequency",
        label="Frequency",
        description="Monthly visit rate recorded in the membership source.",
        reference="scaled against the highest observed monthly visit rate in the analysed cohort",
        formula="100 x min(visits_per_month / cohort_max, 1)",
    ),
    ScoreComponent(
        name="consistency",
        label="Consistency",
        description="Share of observed days on which the member was active.",
        reference="naturally bounded 0-100%",
        formula="100 x (active_days / observation_days)",
    ),
    ScoreComponent(
        name="streak",
        label="Streak",
        description="Longest run of consecutive active days.",
        reference="30-day reference horizon",
        formula="100 x min(longest_streak / 30, 1)",
    ),
    ScoreComponent(
        name="recency",
        label="Recency",
        description="How recently the member last visited, relative to the cohort.",
        reference="scaled against the smallest/largest observed recency in the cohort",
        formula="100 x (1 - min(recency_days / cohort_max, 1))",
    ),
    ScoreComponent(
        name="duration",
        label="Duration",
        description="Average workout duration recorded in the membership source.",
        reference="scaled against the longest observed average duration in the cohort",
        formula="100 x min(avg_duration / cohort_max, 1)",
    ),
)


def score_reference_values(weights: EngagementWeights | None = None) -> Dict[str, str]:
    """Human-readable statement of every scaling reference, for the UI/report."""
    settings = get_settings()
    weights = weights or settings.engagement_weights
    return {
        "weights": " | ".join(f"{k}={v:.2f}" for k, v in weights.normalized().as_dict().items()),
        "disclaimer": (
            "These weights are product-design assumptions, not empirically validated "
            "causal weights, and are configurable via environment variables."
        ),
        **{component.name: component.formula + " (" + component.reference + ")" for component in SCORE_COMPONENTS},
    }


def _cap_score(series: pd.Series, reference_max: float) -> pd.Series:
    if reference_max is None or reference_max <= 0 or pd.isna(reference_max):
        return pd.Series(0.0, index=series.index)
    return (100.0 * (pd.to_numeric(series, errors="coerce") / reference_max)).clip(0, 100)


def compute_component_scores(
    frame: pd.DataFrame, reference: Optional[Dict[str, float]] = None
) -> Tuple[pd.DataFrame, Dict[str, float]]:
    """Compute the five 0-100 component scores plus the weighted total."""
    out = frame.copy()

    cohort_max_visits = float(
        reference.get("max_visits_per_month") if reference else pd.to_numeric(out["visits_per_month"], errors="coerce").max()
    )
    cohort_max_recency = float(
        reference.get("max_recency_days") if reference else pd.to_numeric(out["recency_days"], errors="coerce").max()
    )
    cohort_max_duration = float(
        reference.get("max_avg_duration") if reference else pd.to_numeric(out["avg_workout_duration_min"], errors="coerce").max()
    )

    out["frequency_score"] = _cap_score(out["visits_per_month"], cohort_max_visits)
    out["consistency_score"] = (100.0 * pd.to_numeric(out["consistency"], errors="coerce")).clip(0, 100)
    out["streak_score"] = _cap_score(out["longest_streak"], 30.0)
    recency_numeric = pd.to_numeric(out["recency_days"], errors="coerce")
    out["recency_score"] = (
        100.0 * (1.0 - (recency_numeric / cohort_max_recency).clip(0, 1))
        if cohort_max_recency and not pd.isna(cohort_max_recency)
        else pd.Series(0.0, index=out.index)
    )
    out["duration_score"] = _cap_score(out["avg_workout_duration_min"], cohort_max_duration)

    settings = get_settings()
    weights = settings.engagement_weights.normalized()
    weight_map = weights.as_dict()

    total = (
        out["frequency_score"].fillna(0) * weight_map["frequency"]
        + out["consistency_score"].fillna(0) * weight_map["consistency"]
        + out["streak_score"].fillna(0) * weight_map["streak"]
        + out["recency_score"].fillna(0) * weight_map["recency"]
        + out["duration_score"].fillna(0) * weight_map["duration"]
    )
    out["engagement_score"] = total.clip(0, 100).round(4)

    references = {
        "max_visits_per_month": cohort_max_visits,
        "max_recency_days": cohort_max_recency,
        "max_avg_duration": cohort_max_duration,
        "weights": weight_map,
    }
    return out, references


def assign_segment(
    frame: pd.DataFrame, thresholds: Optional[SegmentThresholds] = None, column: str = "engagement_score"
) -> pd.DataFrame:
    """Map engagement score onto the four behavioural segments."""
    settings = get_settings()
    thresholds = thresholds or settings.segment_thresholds
    out = frame.copy()
    score = pd.to_numeric(out[column], errors="coerce").fillna(0.0)
    out["segment"] = score.map(thresholds.label_for)
    out["segment_order"] = out["segment"].map({name: i for i, name in enumerate(SEGMENT_ORDER)})
    return out


def segment_definition_frame(thresholds: Optional[SegmentThresholds] = None) -> pd.DataFrame:
    """Documented threshold table rendered by the dashboard."""
    settings = get_settings()
    thresholds = thresholds or settings.segment_thresholds
    return pd.DataFrame(
        [
            {
                "segment": "A - Highly Engaged",
                "engagement_score": f">= {thresholds.highly_engaged:g}",
                "interpretation": "High visit rate, high consistency, long streaks, recent activity.",
            },
            {
                "segment": "B - Regular",
                "engagement_score": f"{thresholds.regular:g} - {thresholds.highly_engaged:g}",
                "interpretation": "Moderate activity across all components.",
            },
            {
                "segment": "C - At Risk",
                "engagement_score": f"{thresholds.at_risk:g} - {thresholds.regular:g}",
                "interpretation": "Declining activity or recent inactivity.",
            },
            {
                "segment": "D - Dormant",
                "engagement_score": f"< {thresholds.at_risk:g}",
                "interpretation": "Extended inactivity; lowest observed engagement.",
            },
        ]
    )


# ---------------------------------------------------------------------------
# Real-only member features
# ---------------------------------------------------------------------------
def build_real_member_features(
    dim_member: pd.DataFrame, fact_membership: pd.DataFrame
) -> pd.DataFrame:
    """Member features computed exclusively from real source fields."""
    frame = dim_member.merge(
        fact_membership, on="member_id", how="inner", suffixes=("", "_membership")
    )

    # The churn outcome is kept nullable: if the loaded membership dataset has no
    # churn field, every row stays null and the retention analyses report
    # "unavailable" instead of silently counting everyone as retained.
    frame["churn_status"] = frame["churn_status"].astype("boolean")
    frame["is_churned"] = frame["churn_status"]
    frame["retained"] = frame["is_churned"].map({True: False, False: True})
    frame["outcome_known"] = frame["is_churned"].notna()

    # Recency is real but the membership source's last-visit dates are widely
    # dispersed; the flag lets the UI show how reliable it is as a signal.
    frame["recency_days"] = pd.to_numeric(frame["recency_days"], errors="coerce")
    frame["tenure_days"] = pd.to_numeric(frame["tenure_days"], errors="coerce")
    frame["tenure_months"] = (frame["tenure_days"] / 30.4375).round(2)

    frame["visits_per_month"] = pd.to_numeric(frame["visits_per_month"], errors="coerce")
    frame["visit_frequency_band"] = pd.cut(
        frame["visits_per_month"],
        bins=[-np.inf, 4, 8, 12, 16, 20, np.inf],
        labels=["0-4", "5-8", "9-12", "13-16", "17-20", "21+"],
    ).astype("string")
    frame["recency_band"] = pd.cut(
        frame["recency_days"],
        bins=[-np.inf, 30, 90, 180, 365, np.inf],
        labels=["0-30 days", "31-90 days", "91-180 days", "181-365 days", "365+ days"],
    ).astype("string")
    frame["duration_band"] = pd.cut(
        pd.to_numeric(frame["avg_workout_duration_min"], errors="coerce"),
        bins=[-np.inf, 45, 75, 105, np.inf],
        labels=["<=45 min", "46-75 min", "76-105 min", "106+ min"],
    ).astype("string")

    frame["feature_source"] = "real_source_fields"
    return frame


# ---------------------------------------------------------------------------
# Synthetic-calendar-derived activity features
# ---------------------------------------------------------------------------
def build_activity_features(
    synthetic_events: pd.DataFrame, reference_date: Optional[pd.Timestamp] = None
) -> pd.DataFrame:
    """Member-level activity features derived from the synthetic calendar."""
    if synthetic_events.empty:
        return pd.DataFrame(columns=["member_id", *SYNTHETIC_FEATURE_COLUMNS])
    streaks = streak_features_for_groups(
        synthetic_events, reference_date=reference_date
    )
    agg = synthetic_events.groupby("member_id").agg(
        synthetic_events=("workout_id", "count"),
        total_duration=("duration_minutes", "sum"),
        total_calories=("calories_burned", "sum"),
        avg_duration_derived=("duration_minutes", "mean"),
        first_event=("workout_date", "min"),
        last_event=("workout_date", "max"),
        distinct_workout_types=("workout_type", "nunique"),
        dominant_workout_type=("workout_type", lambda s: s.mode().iloc[0] if not s.mode().empty else None),
    ).reset_index()

    out = streaks.merge(agg, on="member_id", how="outer")
    out["workouts_per_week"] = (
        7.0 * pd.to_numeric(out["active_days"], errors="coerce")
        / pd.to_numeric(out["observation_days"], errors="coerce").replace(0, np.nan)
    ).round(4)
    out["workouts_per_month_derived"] = (out["workouts_per_week"] * 30.4375 / 7.0).round(4)
    out["feature_source"] = "synthetic_date_placement"
    return out


def lifecycle_stage(row: pd.Series) -> str:
    """Behavioural funnel stage for one member (synthetic-activity dependent)."""
    events = row.get("synthetic_events") or 0
    consistency = row.get("consistency") or 0.0
    if events < LIFECYCLE_CONFIG["first_workout_min_events"]:
        return "Registered"
    if events < LIFECYCLE_CONFIG["repeat_workout_min_events"]:
        return "First Workout"
    if events < LIFECYCLE_CONFIG["consistent_min_events"] or consistency < LIFECYCLE_CONFIG["consistent_min_consistency"]:
        return "Repeat Workout"
    if row.get("churn_status") is True or row.get("is_churned") is True:
        return "Consistent Activity"
    return "Retained"


def build_member_features(
    real_features: pd.DataFrame,
    synthetic_events: pd.DataFrame,
    reference_date: Optional[pd.Timestamp] = None,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Unified member-level analytical model.

    Returns the feature frame and a metadata payload describing exactly which
    columns are synthetic-derived plus the score scaling references used.
    """
    frame = real_features.copy()
    activity = build_activity_features(synthetic_events, reference_date=reference_date)
    frame = frame.merge(activity, on="member_id", how="left")
    # Merge suffixes would otherwise create feature_source_x/feature_source_y.
    frame = frame.drop(columns=[c for c in frame.columns if c.startswith("feature_source")], errors="ignore")

    for column in SYNTHETIC_FEATURE_COLUMNS:
        if column not in frame.columns:
            frame[column] = np.nan
    for column in (
        "synthetic_events",
        "active_days",
        "observation_days",
        "longest_streak",
        "current_streak",
        "streak_break_count",
        "max_gap_days",
        "inactive_days",
    ):
        frame[column] = pd.to_numeric(frame[column], errors="coerce").fillna(0).astype("int64")
    for column in ("consistency", "workouts_per_week", "workouts_per_month_derived", "average_streak"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce").fillna(0.0)

    frame["lifecycle_stage"] = frame.apply(lifecycle_stage, axis=1)

    # Days since last workout is real (derived from the real Last_Visit_Date).
    frame["days_since_last_workout"] = pd.to_numeric(frame["recency_days"], errors="coerce")

    frame, references = compute_component_scores(frame)
    frame = assign_segment(frame)

    settings = get_settings()
    inactivity_threshold = settings.alert_thresholds.inactivity_days
    frame["inactivity_flag"] = frame["days_since_last_workout"] > inactivity_threshold
    frame["at_risk_flag"] = frame["segment"].isin(["C - At Risk", "D - Dormant"])
    frame["activity_feature_source"] = "synthetic_date_placement"
    frame["feature_source"] = "mixed: real membership fields + synthetic calendar features"
    frame["engagement_score_disclaimer"] = (
        "Weighted product-design composite; not a validated behavioural measurement."
    )

    metadata = {
        "synthetic_feature_columns": list(SYNTHETIC_FEATURE_COLUMNS),
        "real_feature_columns": [
            "visits_per_month",
            "avg_workout_duration_min",
            "avg_calories_burned",
            "total_weight_lifted_kg",
            "recency_days",
            "tenure_days",
            "age",
            "membership_type",
            "gender",
            "favorite_exercise",
            "churn_status",
        ],
        "score_references": references,
        "score_spec": score_reference_values(settings.engagement_weights),
        "segment_definition": segment_definition_frame(settings.segment_thresholds).to_dict("records"),
        "lifecycle_config": dict(LIFECYCLE_CONFIG),
        "note": (
            "Frequency, recency and duration components come from real source fields. "
            "Consistency and streak components come from synthetic date placement and are "
            "listed in synthetic_feature_columns."
        ),
    }
    logger.info("Member features built for %s members", f"{len(frame):,}")
    return frame, metadata


# ---------------------------------------------------------------------------
# Platform-level (real activity source) features
# ---------------------------------------------------------------------------
def build_platform_activity(fact_workout: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    """Daily / monthly platform aggregates from the real activity source."""
    frame = fact_workout.copy()
    if frame.empty:
        empty = pd.DataFrame()
        return {"daily": empty, "monthly": empty, "workout_type": empty, "weekday": empty, "hour": empty}

    frame["workout_date"] = pd.to_datetime(frame["workout_date"])
    frame["date"] = frame["workout_date"].dt.normalize()

    grouped = frame.groupby("date")
    daily = grouped.agg(
        events=("workout_id", "count"),
        present_count=("is_present", "sum"),
        total_duration=("duration_minutes", "sum"),
        confirmed_duration=("confirmed_duration_minutes", "sum"),
        total_calories=("calories_burned", "sum"),
        confirmed_calories=("confirmed_calories_burned", "sum"),
        distinct_workout_types=("workout_type", "nunique"),
        mean_age=("age", "mean"),
    ).reset_index()
    daily = daily.rename(columns={"date": "activity_date"})
    daily["absent_count"] = daily["events"] - daily["present_count"]
    daily["present_rate"] = (daily["present_count"] / daily["events"]).round(6)
    daily["is_active_day"] = daily["events"] > 0
    daily["confirmed_duration_share"] = (
        daily["confirmed_duration"] / daily["total_duration"]
    ).round(6)
    daily = platform_streak_series(daily)
    daily["rolling_7d_events"] = daily["events"].rolling(7, min_periods=1).mean().round(4)
    daily["rolling_28d_events"] = daily["events"].rolling(28, min_periods=1).mean().round(4)
    daily["rolling_7d_present_rate"] = daily["present_rate"].rolling(7, min_periods=1).mean().round(6)
    daily["cumulative_events"] = daily["events"].cumsum()
    daily["week"] = daily["activity_date"].dt.to_period("W").astype("string")
    daily["month"] = daily["activity_date"].dt.to_period("M").astype("string")
    daily["weekday"] = daily["activity_date"].dt.day_name()
    daily["month_num"] = daily["activity_date"].dt.month

    monthly = (
        frame.assign(month=frame["workout_date"].dt.to_period("M").astype("string"))
        .groupby("month")
        .agg(
            events=("workout_id", "count"),
            present_count=("is_present", "sum"),
            total_duration=("duration_minutes", "sum"),
            confirmed_duration=("confirmed_duration_minutes", "sum"),
            total_calories=("calories_burned", "sum"),
            avg_duration=("duration_minutes", "mean"),
            avg_calories=("calories_burned", "mean"),
            distinct_workout_types=("workout_type", "nunique"),
        )
        .reset_index()
    )
    monthly["present_rate"] = (monthly["present_count"] / monthly["events"]).round(6)
    monthly["collapsed_duration"] = monthly["total_duration"] - monthly["confirmed_duration"]
    monthly["collapsed_duration_share"] = (
        monthly["collapsed_duration"] / monthly["total_duration"]
    ).round(6)
    monthly["events_change_pct"] = (
        monthly["events"].pct_change() * 100.0
    ).round(4)
    monthly["present_rate_change_pct"] = (
        monthly["present_rate"].pct_change() * 100.0
    ).round(4)

    workout_type = (
        frame.groupby("workout_type")
        .agg(
            events=("workout_id", "count"),
            present_count=("is_present", "sum"),
            avg_duration=("duration_minutes", "mean"),
            avg_calories=("calories_burned", "mean"),
            confirmed_duration=("confirmed_duration_minutes", "sum"),
        )
        .reset_index()
    )
    workout_type["present_rate"] = (workout_type["present_count"] / workout_type["events"]).round(6)
    workout_type["event_share"] = (workout_type["events"] / workout_type["events"].sum()).round(6)
    workout_type = workout_type.sort_values("events", ascending=False)

    weekday = (
        frame.groupby(["workout_weekday_num", "workout_weekday"])
        .agg(events=("workout_id", "count"), present_count=("is_present", "sum"))
        .reset_index()
        .sort_values("workout_weekday_num")
    )
    weekday["present_rate"] = (weekday["present_count"] / weekday["events"]).round(6)

    hour = (
        frame.dropna(subset=["check_in_hour"])
        .groupby("check_in_hour")
        .agg(events=("workout_id", "count"), present_count=("is_present", "sum"))
        .reset_index()
    )
    hour["present_rate"] = (hour["present_count"] / hour["events"].replace(0, np.nan)).round(6)

    return {
        "daily": daily,
        "monthly": monthly,
        "workout_type": workout_type,
        "weekday": weekday,
        "hour": hour,
    }

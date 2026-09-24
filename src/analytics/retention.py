"""Retention analysis on the real churn outcome.

Retention/churn are computed from the membership source's own churn label.
Behavioural dimensions are attached from real fields (visit rate, duration,
membership tier, age band, favourite exercise, tenure) and, where clearly
labelled, from synthetic-calendar activity features.

Small group sizes are a genuine constraint here (150 members), so every rate is
reported with a **Wilson 95% score interval** and groups below a configurable
minimum size are flagged rather than silently published as a headline.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

from ..common.logging_utils import get_logger

logger = get_logger("analytics.retention")

#: Groups smaller than this are flagged as low-confidence in the output.
MIN_GROUP_SIZE = 10


def pct(value: float, denominator: float) -> float:
    if not denominator:
        return 0.0
    return round(100.0 * float(value) / float(denominator), 4)


def wilson_interval(successes: int, total: int, z: float = 1.959964) -> tuple[float, float]:
    """Wilson 95% score interval for a proportion (percent scale)."""
    if total <= 0:
        return (0.0, 0.0)
    phat = successes / total
    denominator = 1 + z**2 / total
    centre = (phat + z**2 / (2 * total)) / denominator
    half = (z * math.sqrt(phat * (1 - phat) / total + z**2 / (4 * total**2))) / denominator
    return (round(100.0 * max(centre - half, 0.0), 4), round(100.0 * min(centre + half, 1.0), 4))


def retention_summary(members: pd.DataFrame) -> Dict[str, Any]:
    """Headline retention/churn figures with confidence intervals."""
    total = int(len(members))
    if total == 0:
        return {
            "total_members": 0,
            "retained": 0,
            "churned": 0,
            "retention_rate": 0.0,
            "churn_rate": 0.0,
            "churn_ci_low": 0.0,
            "churn_ci_high": 0.0,
            "eligible_definition": "all members present in the membership source",
        }
    churned = int(members["is_churned"].astype(bool).sum())
    retained = total - churned
    low, high = wilson_interval(churned, total)
    return {
        "total_members": total,
        "retained": retained,
        "churned": churned,
        "retention_rate": pct(retained, total),
        "churn_rate": pct(churned, total),
        "churn_ci_low": low,
        "churn_ci_high": high,
        "eligible_definition": "all members present in the membership source",
        "eligible_rule": "Retention Rate = Retained Members / Eligible Members",
    }


def retention_by_dimension(
    members: pd.DataFrame,
    dimension: str,
    min_group_size: int = MIN_GROUP_SIZE,
    behaviour_columns: Optional[Sequence[str]] = None,
) -> pd.DataFrame:
    """Retention/churn broken down by one behavioural or business dimension."""
    if dimension not in members.columns or members.empty:
        return pd.DataFrame()

    behaviour_columns = behaviour_columns or [
        "visits_per_month",
        "avg_workout_duration_min",
        "avg_calories_burned",
        "recency_days",
        "tenure_days",
        "engagement_score",
        "longest_streak",
        "consistency",
    ]
    available = [c for c in behaviour_columns if c in members.columns]

    grouped = members.groupby(dimension, dropna=False, observed=True)
    rows: List[Dict[str, Any]] = []
    for key, group in grouped:
        total = int(len(group))
        churned = int(group["is_churned"].astype(bool).sum())
        retained = total - churned
        low, high = wilson_interval(churned, total)
        row: Dict[str, Any] = {
            "dimension": dimension,
            "dimension_value": "Missing" if pd.isna(key) else str(key),
            "members": total,
            "retained": retained,
            "churned": churned,
            "churn_rate": pct(churned, total),
            "retention_rate": pct(retained, total),
            "churn_ci_low": low,
            "churn_ci_high": high,
            "low_confidence": total < min_group_size,
        }
        for column in available:
            row[f"avg_{column}"] = round(
                float(pd.to_numeric(group[column], errors="coerce").mean()), 4
            )
        rows.append(row)

    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    frame["dimension"] = dimension
    return frame.sort_values("churn_rate", ascending=False).reset_index(drop=True)


def retention_by_all_dimensions(
    members: pd.DataFrame,
    dimensions: Optional[Sequence[str]] = None,
    min_group_size: int = MIN_GROUP_SIZE,
) -> Dict[str, pd.DataFrame]:
    """Retention table per supported dimension.

    Only dimensions actually present in the data are returned, so the dashboard
    never renders an empty chart for an unavailable field.
    """
    dimensions = dimensions or [
        "membership_type",
        "visit_frequency_band",
        "recency_band",
        "duration_band",
        "segment",
        "age_group",
        "gender",
        "favorite_exercise",
        "lifecycle_stage",
        "churn_status",
    ]
    available = [d for d in dimensions if d in members.columns and d != "churn_status"]
    return {
        dimension: retention_by_dimension(members, dimension, min_group_size=min_group_size)
        for dimension in available
    }


def frequency_gradient(members: pd.DataFrame, band_column: str = "visit_frequency_band") -> pd.DataFrame:
    """Churn/retention gradient across ordered visit-frequency bands."""
    if band_column not in members.columns or members.empty:
        return pd.DataFrame()
    frame = retention_by_dimension(members, band_column)
    order = ["0-4", "5-8", "9-12", "13-16", "17-20", "21+"]
    frame["_order"] = frame["dimension_value"].map({v: i for i, v in enumerate(order)}).fillna(99)
    return frame.sort_values("_order").drop(columns="_order").reset_index(drop=True)


def retention_by_join_year(members: pd.DataFrame) -> pd.DataFrame:
    """Cohort view: retention by the year the member joined."""
    if "join_date" not in members.columns or members.empty:
        return pd.DataFrame()
    frame = members.copy()
    frame["join_year"] = pd.to_datetime(frame["join_date"], errors="coerce").dt.year
    frame = frame.dropna(subset=["join_year"])
    if frame.empty:
        return pd.DataFrame()
    frame["join_year"] = frame["join_year"].astype(int).astype(str)
    out = retention_by_dimension(frame, "join_year")
    return out.sort_values("dimension_value").reset_index(drop=True)


def retention_trend_by_join_year(members: pd.DataFrame) -> pd.DataFrame:
    """Churn rate per join-year cohort, ordered chronologically."""
    frame = retention_by_join_year(members)
    if frame.empty:
        return frame
    frame = frame.rename(columns={"dimension_value": "join_year"})
    frame["churn_rate_change_pp"] = frame["churn_rate"].diff().round(4)
    return frame


def compare_retained_vs_churned(
    members: pd.DataFrame, measures: Optional[Sequence[str]] = None
) -> pd.DataFrame:
    """Side-by-side behaviour of retained vs churned members, with effect sizes.

    Reports a Welch t statistic and Cohen's d. Because the two groups can be very
    unbalanced (111 vs 39 members), the effect size is the headline and the
    significance figure carries an explicit normal-approximation caveat.
    """
    measures = measures or [
        "visits_per_month",
        "avg_workout_duration_min",
        "avg_calories_burned",
        "total_weight_lifted_kg",
        "recency_days",
        "tenure_days",
        "consistency",
        "longest_streak",
        "average_streak",
        "engagement_score",
    ]
    available = [m for m in measures if m in members.columns]
    rows: List[Dict[str, Any]] = []

    retained = members[~members["is_churned"].astype(bool)]
    churned = members[members["is_churned"].astype(bool)]

    for measure in available:
        a = pd.to_numeric(retained[measure], errors="coerce").dropna().to_numpy()
        b = pd.to_numeric(churned[measure], errors="coerce").dropna().to_numpy()
        if len(a) < 2 or len(b) < 2:
            continue
        mean_a, mean_b = float(np.mean(a)), float(np.mean(b))
        var_a, var_b = float(np.var(a, ddof=1)), float(np.var(b, ddof=1))
        pooled = math.sqrt(((len(a) - 1) * var_a + (len(b) - 1) * var_b) / max(len(a) + len(b) - 2, 1))
        cohens_d = (mean_b - mean_a) / pooled if pooled > 0 else 0.0
        se = math.sqrt(var_a / len(a) + var_b / len(b))
        t_stat = (mean_b - mean_a) / se if se > 0 else 0.0
        p_value = 2 * 0.5 * math.erfc(abs(t_stat) / math.sqrt(2)) if se > 0 else 1.0

        rows.append(
            {
                "measure": measure,
                "retained_mean": round(mean_a, 4),
                "churned_mean": round(mean_b, 4),
                "difference": round(mean_b - mean_a, 4),
                "relative_difference_pct": round(
                    100.0 * (mean_b - mean_a) / mean_a, 4
                ) if mean_a else None,
                "cohens_d": round(cohens_d, 4),
                "effect_size": _effect_label(abs(cohens_d)),
                "welch_t": round(t_stat, 4),
                "p_value_normal_approx": round(min(p_value, 1.0), 6),
                "n_retained": int(len(a)),
                "n_churned": int(len(b)),
            }
        )

    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    return frame.reindex(frame["cohens_d"].abs().sort_values(ascending=False).index).reset_index(drop=True)


def _effect_label(size: float) -> str:
    if size < 0.2:
        return "negligible"
    if size < 0.5:
        return "small"
    if size < 0.8:
        return "medium"
    return "large"


def association_sentence(row: pd.Series, measure_label: Optional[str] = None) -> str:
    """Neutral-language description of one retained-vs-churned comparison."""
    label = measure_label or str(row["measure"]).replace("_", " ")
    direction = "higher" if row["difference"] > 0 else "lower"
    strength = row["effect_size"]
    return (
        f"Churned members show a {strength} difference in {label}: "
        f"churned mean {row['churned_mean']:,.2f} vs retained mean {row['retained_mean']:,.2f} "
        f"({direction} by {abs(row['difference']):,.2f}). This is an observed association, "
        "not evidence of causation."
    )


@dataclass
class RetentionResult:
    """Container for all retention outputs."""

    summary: Dict[str, Any]
    by_dimension: Dict[str, pd.DataFrame]
    comparison: pd.DataFrame
    frequency_gradient: pd.DataFrame
    cohort_trend: pd.DataFrame

    def as_dict(self) -> Dict[str, Any]:
        return {
            "summary": self.summary,
            "dimensions": list(self.by_dimension),
            "comparison": self.comparison.to_dict("records"),
            "cohort_trend": self.cohort_trend.to_dict("records"),
        }


def analyse_retention(members: pd.DataFrame) -> RetentionResult:
    """Run the complete retention analysis."""
    summary = retention_summary(members)
    by_dimension = retention_by_all_dimensions(members)
    comparison = compare_retained_vs_churned(members)
    gradient = frequency_gradient(members)
    cohort = retention_trend_by_join_year(members)
    logger.info(
        "Retention: %.2f%% retained (%s/%s members)",
        summary["retention_rate"],
        summary["retained"],
        summary["total_members"],
    )
    return RetentionResult(
        summary=summary,
        by_dimension=by_dimension,
        comparison=comparison,
        frequency_gradient=gradient,
        cohort_trend=cohort,
    )

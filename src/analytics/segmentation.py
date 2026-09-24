"""Behavioural segmentation analytics.

Segments are derived from the configurable engagement score (see
:mod:`src.features.engineer`). This module reports how each segment behaves and
how each segment's **real** churn outcome compares.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd

from ..common.logging_utils import get_logger
from ..features.engineer import SEGMENT_ORDER, segment_definition_frame
from .retention import pct, wilson_interval

logger = get_logger("analytics.segmentation")

SEGMENT_METRIC_COLUMNS = (
    "visits_per_month",
    "avg_workout_duration_min",
    "avg_calories_burned",
    "recency_days",
    "longest_streak",
    "average_streak",
    "consistency",
    "engagement_score",
    "tenure_days",
    "synthetic_events",
)


def segment_metrics(members: pd.DataFrame) -> pd.DataFrame:
    """Size, retention, churn and behaviour averages per segment."""
    if members.empty or "segment" not in members.columns:
        return pd.DataFrame()

    rows: List[Dict[str, Any]] = []
    total_members = int(len(members))
    for segment in SEGMENT_ORDER:
        group = members[members["segment"] == segment]
        size = int(len(group))
        if size == 0:
            rows.append(
                {
                    "segment": segment,
                    "members": 0,
                    "share_pct": 0.0,
                    "retained": 0,
                    "churned": 0,
                    "churn_rate": 0.0,
                    "retention_rate": 0.0,
                    "churn_ci_low": 0.0,
                    "churn_ci_high": 0.0,
                }
            )
            continue
        churned = int(group["is_churned"].astype(bool).sum())
        low, high = wilson_interval(churned, size)
        row: Dict[str, Any] = {
            "segment": segment,
            "members": size,
            "share_pct": pct(size, total_members),
            "retained": size - churned,
            "churned": churned,
            "churn_rate": pct(churned, size),
            "retention_rate": pct(size - churned, size),
            "churn_ci_low": low,
            "churn_ci_high": high,
        }
        for column in SEGMENT_METRIC_COLUMNS:
            if column in group.columns:
                row[f"avg_{column}"] = round(
                    float(pd.to_numeric(group[column], errors="coerce").mean()), 4
                )
        rows.append(row)

    frame = pd.DataFrame(rows)
    frame["_order"] = frame["segment"].map({s: i for i, s in enumerate(SEGMENT_ORDER)})
    return frame.sort_values("_order").drop(columns="_order").reset_index(drop=True)


def segment_churn_ranking(members: pd.DataFrame) -> pd.DataFrame:
    """Segments ordered by churn rate, for the 'which segment churns most' question."""
    frame = segment_metrics(members)
    if frame.empty:
        return frame
    return frame.sort_values("churn_rate", ascending=False).reset_index(drop=True)


def segment_transition_risk(members: pd.DataFrame) -> pd.DataFrame:
    """Which segments hold the population most exposed to churn."""
    frame = segment_metrics(members)
    if frame.empty:
        return frame
    frame = frame.copy()
    frame["churned_members"] = frame["churned"]
    frame["share_of_total_churn_pct"] = (
        100.0 * frame["churned"] / max(frame["churned"].sum(), 1)
    ).round(4)
    return frame[
        ["segment", "members", "share_pct", "churned_members", "share_of_total_churn_pct", "churn_rate"]
    ].sort_values("churned_members", ascending=False).reset_index(drop=True)


def segmentation_report(members: pd.DataFrame) -> Dict[str, Any]:
    """All segmentation outputs plus the documented threshold table."""
    metrics = segment_metrics(members)
    if metrics.empty:
        return {
            "metrics": metrics,
            "definition": segment_definition_frame(),
            "insight": "Segmentation unavailable: engagement score not computed.",
        }

    highest = metrics.sort_values("churn_rate", ascending=False).iloc[0]
    lowest = metrics.sort_values("churn_rate", ascending=True).iloc[0]
    largest = metrics.sort_values("members", ascending=False).iloc[0]
    insight = (
        f"The {highest['segment']} segment shows the highest observed churn rate "
        f"({highest['churn_rate']:.1f}%, n={int(highest['members'])}), while "
        f"{lowest['segment']} shows the lowest ({lowest['churn_rate']:.1f}%, "
        f"n={int(lowest['members'])}). The largest population share sits in "
        f"{largest['segment']} ({largest['share_pct']:.1f}% of members). "
        "Segment membership depends on the configurable engagement weights and on "
        "synthetic date placement for the consistency and streak components."
    )
    logger.info("Segmentation computed for %s segments", len(metrics))
    return {
        "metrics": metrics,
        "ranking": segment_churn_ranking(members),
        "risk": segment_transition_risk(members),
        "definition": segment_definition_frame(),
        "insight": insight,
    }


def segment_member_list(members: pd.DataFrame, segment: str, limit: int = 200) -> pd.DataFrame:
    """Members belonging to one segment, for drill-down tables."""
    if "segment" not in members.columns:
        return pd.DataFrame()
    columns = [
        c
        for c in (
            "member_id",
            "segment",
            "engagement_score",
            "visits_per_month",
            "longest_streak",
            "consistency",
            "recency_days",
            "membership_type",
            "churn_status",
            "lifecycle_stage",
        )
        if c in members.columns
    ]
    frame = members[members["segment"] == segment][columns]
    return frame.sort_values("engagement_score", ascending=False).head(limit).reset_index(drop=True)

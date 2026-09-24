"""Funnel analysis.

Two funnels are produced, and their provenance is stated explicitly:

``platform_funnel`` (REAL)
    Every record in the activity source is a scheduled session carrying an
    attendance outcome. The funnel therefore measures **scheduled → attended →
    confirmed volume** on real data.

``member_lifecycle_funnel`` (MIXED)
    Registered → First Workout → Repeat Workout → Consistent Activity → Retained.
    Stage membership depends on the synthetic activity calendar, while the final
    ``Retained`` stage uses the **real** churn outcome. Stage counts are
    therefore labelled mixed-provenance.

``behavioural_drop_off`` (REAL)
    Where engagement drops, measured on real fields: visit-frequency bands and
    the real recency distribution.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from ..common.logging_utils import get_logger
from ..features.engineer import LIFECYCLE_STAGES
from .retention import pct

logger = get_logger("analytics.funnel")


def _stage_table(stages: List[Dict[str, Any]], base: Optional[float] = None) -> pd.DataFrame:
    """Build the funnel table. The stage size column is named ``records``
    deliberately: ``count`` would shadow ``namedtuple.count`` in
    ``itertuples()`` loops."""
    frame = pd.DataFrame(stages)
    if frame.empty:
        return frame
    size = "records"
    base = base if base is not None else float(frame.loc[0, size])
    frame["share_of_start_pct"] = (100.0 * frame[size] / base).round(4) if base else 0.0
    frame["conversion_from_previous_pct"] = (100.0 * frame[size] / frame[size].shift(1)).round(4)
    frame.loc[frame.index[0], "conversion_from_previous_pct"] = 100.0
    frame["drop_off"] = (frame[size].shift(1) - frame[size]).fillna(0).astype(int)
    frame["drop_off_pct"] = (100.0 * frame["drop_off"] / frame[size].shift(1)).round(4)
    frame.loc[frame.index[0], "drop_off_pct"] = 0.0
    return frame


def platform_funnel(fact_workout: pd.DataFrame) -> pd.DataFrame:
    """Real attendance funnel over scheduled sessions."""
    if fact_workout is None or fact_workout.empty:
        return pd.DataFrame()
    frame = fact_workout.copy()
    scheduled = int(len(frame))
    present = int(frame["is_present"].sum())
    confirmed_duration = float(pd.to_numeric(frame["confirmed_duration_minutes"], errors="coerce").sum())
    recorded_duration = float(pd.to_numeric(frame["duration_minutes"], errors="coerce").sum())
    confirmed_calories = float(pd.to_numeric(frame["confirmed_calories_burned"], errors="coerce").sum())

    stages = [
        {
            "stage": "Scheduled sessions",
            "records": scheduled,
            "definition": "Every row in the activity source carries a scheduled date, check-in time and outcome.",
            "provenance": "real",
        },
        {
            "stage": "Attended sessions (Present)",
            "records": present,
            "definition": "Rows with attendance_status = Present.",
            "provenance": "real",
        },
        {
            "stage": "Sessions with meaningful duration (>=30 min)",
            "records": int(((frame["is_present"]) & (frame["duration_minutes"] >= 30)).sum()),
            "definition": "Attended sessions at or above a 30-minute duration threshold.",
            "provenance": "real",
        },
        {
            "stage": "Sessions with high duration (>=60 min)",
            "records": int(((frame["is_present"]) & (frame["duration_minutes"] >= 60)).sum()),
            "definition": "Attended sessions at or above a 60-minute duration threshold.",
            "provenance": "real",
        },
    ]
    table = _stage_table(stages, base=scheduled)
    table.attrs["confirmed_duration_hours"] = round(confirmed_duration / 60.0, 2)
    table.attrs["recorded_duration_hours"] = round(recorded_duration / 60.0, 2)
    table.attrs["confirmed_calories"] = round(confirmed_calories, 2)
    return table


def member_lifecycle_funnel(member_features: pd.DataFrame) -> pd.DataFrame:
    """Member funnel across lifecycle stages (mixed provenance)."""
    if member_features is None or member_features.empty:
        return pd.DataFrame()
    members = member_features
    total = int(len(members))
    events = pd.to_numeric(members["synthetic_events"], errors="coerce").fillna(0)
    consistency = pd.to_numeric(members["consistency"], errors="coerce").fillna(0)
    retained = ~members["is_churned"].astype(bool)

    stages = [
        {
            "stage": "Registered Members",
            "records": total,
            "definition": "Members present in the membership source.",
            "provenance": "real",
        },
        {
            "stage": "First Workout",
            "records": int((events >= 1).sum()),
            "definition": "At least one recorded visit in the observation window.",
            "provenance": "mixed (synthetic calendar)",
        },
        {
            "stage": "Repeat Workout",
            "records": int((events >= 2).sum()),
            "definition": "Two or more recorded visits.",
            "provenance": "mixed (synthetic calendar)",
        },
        {
            "stage": "Consistent Activity",
            "records": int(((events >= 8) & (consistency >= 0.15)).sum()),
            "definition": "At least 8 visits and activity on >=15% of observed days.",
            "provenance": "mixed (synthetic calendar)",
        },
        {
            "stage": "Long-Term Engagement",
            "records": int(((events >= 8) & (consistency >= 0.15) & retained).sum()),
            "definition": "Consistent activity and not churned.",
            "provenance": "mixed (real outcome + synthetic activity)",
        },
        {
            "stage": "Retained",
            "records": int(retained.sum()),
            "definition": "Churn indicator = No in the membership source.",
            "provenance": "real",
        },
    ]
    table = _stage_table(stages, base=total)
    table.attrs["note"] = (
        "Stages 2-5 depend on synthetic date placement; the final Retained stage uses the "
        "real churn outcome. Interpret stage-level drop-off as illustrative of the "
        "architecture, not as a measured business funnel."
    )
    return table


def behavioural_drop_off(members: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    """Where engagement drops, measured on real fields only."""
    out: Dict[str, pd.DataFrame] = {}
    if members is None or members.empty:
        return out

    if "visit_frequency_band" in members.columns:
        band = (
            members.groupby("visit_frequency_band", observed=True)
            .agg(
                members=("member_id", "count"),
                retained=("is_churned", lambda s: int((~s.astype(bool)).sum())),
                churned=("is_churned", lambda s: int(s.astype(bool).sum())),
                avg_engagement_score=("engagement_score", "mean"),
            )
            .reset_index()
            .rename(columns={"visit_frequency_band": "band"})
        )
        band["retention_rate"] = (100.0 * band["retained"] / band["members"]).round(4)
        band["churn_rate"] = (100.0 * band["churned"] / band["members"]).round(4)
        order = ["0-4", "5-8", "9-12", "13-16", "17-20", "21+"]
        band["_order"] = band["band"].astype(str).map({v: i for i, v in enumerate(order)}).fillna(99)
        band["retention_change_pp"] = band.sort_values("_order")["retention_rate"].diff().reindex(band.index).round(4)
        out["by_frequency_band"] = band.sort_values("_order").drop(columns="_order").reset_index(drop=True)

    if "recency_band" in members.columns:
        recency = (
            members.groupby("recency_band", observed=True)
            .agg(
                members=("member_id", "count"),
                retained=("is_churned", lambda s: int((~s.astype(bool)).sum())),
                churned=("is_churned", lambda s: int(s.astype(bool).sum())),
            )
            .reset_index()
            .rename(columns={"recency_band": "band"})
        )
        recency["retention_rate"] = (100.0 * recency["retained"] / recency["members"]).round(4)
        order = ["0-30 days", "31-90 days", "91-180 days", "181-365 days", "365+ days"]
        recency["_order"] = recency["band"].astype(str).map({v: i for i, v in enumerate(order)}).fillna(99)
        out["by_recency_band"] = (
            recency.sort_values("_order").drop(columns="_order").reset_index(drop=True)
        )

    if "segment" in members.columns:
        segment = (
            members.groupby("segment", observed=True)
            .agg(
                members=("member_id", "count"),
                retained=("is_churned", lambda s: int((~s.astype(bool)).sum())),
                churned=("is_churned", lambda s: int(s.astype(bool).sum())),
                avg_engagement_score=("engagement_score", "mean"),
            )
            .reset_index()
        )
        segment["retention_rate"] = (100.0 * segment["retained"] / segment["members"]).round(4)
        out["by_segment"] = segment.sort_values("retention_rate", ascending=False).reset_index(drop=True)

    return out


def funnel_insight(platform: pd.DataFrame, member: pd.DataFrame) -> str:
    """One neutral-language sentence describing the biggest funnel loss."""
    if platform is not None and not platform.empty:
        row = platform.iloc[1]
        return (
            f"On the real activity source, {int(row['records']):,} of "
            f"{int(platform.iloc[0]['records']):,} scheduled sessions were attended "
            f"({row['conversion_from_previous_pct']:.1f}% conversion; "
            f"{row['drop_off_pct']:.1f}% drop-off). Because the source records nominal "
            "duration for absent sessions, the confirmed-duration measure in this funnel "
            "is materially lower than total recorded minutes."
        )
    if member is not None and not member.empty:
        return (
            "Member-level lifecycle stages depend on synthetic date placement; treat them "
            "as an illustration of the integration architecture."
        )
    return "Funnel analysis unavailable: required input frames are empty."

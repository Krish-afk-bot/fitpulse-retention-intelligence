"""Streak mathematics.

A **streak** is a run of consecutive calendar days on which at least one
activity event occurred. Definitions used consistently across the product:

``longest_streak``
    Length in days of the longest run.
``current_streak``
    Length of the final run, but only if the last active day falls within
    ``grace_days`` of the reference date — otherwise ``0`` (the streak is
    broken). A streak that has ended is never reported as current.
``streak_ending_at_last_activity``
    The raw length of the final run regardless of whether it is still alive.
    Reported alongside ``current_streak`` so the grace-day decision is visible
    rather than hidden.
``average_streak``
    Mean run length across all runs.
``streak_break_count``
    Number of times a run ended (``runs - 1``): the count of active-to-inactive
    transitions.
``max_gap_days``
    Longest stretch of inactive days between two active days.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

_DAY_NS = 24 * 3600 * 10**9


def _to_days(dates) -> np.ndarray:
    """Convert dates to whole days since the epoch as int64."""
    normalized = pd.to_datetime(pd.Series(dates)).dropna().dt.normalize()
    return (normalized.astype("datetime64[ns]").astype("int64") // _DAY_NS).to_numpy()


@dataclass
class StreakSummary:
    """Streak metrics for one activity series."""

    first_active_date: Optional[pd.Timestamp]
    last_active_date: Optional[pd.Timestamp]
    active_days: int
    observation_days: int
    consistency: float
    longest_streak: int
    current_streak: int
    streak_ending_at_last_activity: int
    average_streak: float
    streak_break_count: int
    run_count: int
    max_gap_days: int
    inactive_days: int

    def as_dict(self) -> Dict[str, Any]:
        payload = self.__dict__.copy()
        for key in ("first_active_date", "last_active_date"):
            value = payload[key]
            payload[key] = None if value is None or pd.isna(value) else pd.Timestamp(value).date().isoformat()
        return payload


def run_lengths(active_dates: pd.Series) -> List[int]:
    """Lengths of every consecutive-day run in a date series (vectorised)."""
    if active_dates.empty:
        return []
    days = np.sort(pd.to_datetime(pd.Series(active_dates)).dropna().dt.normalize().unique())
    if len(days) == 0:
        return []
    values = _to_days(days)
    breaks = np.diff(values) != 1
    run_ids = np.concatenate([[0], np.cumsum(breaks)])
    return pd.Series(run_ids).value_counts(sort=False).sort_index().tolist()


def daily_activity_index(active_dates: pd.Series, start=None, end=None) -> pd.DataFrame:
    """Full daily calendar with an ``is_active`` flag — the basis of time series."""
    dates = pd.to_datetime(pd.Series(active_dates)).dropna().dt.normalize()
    if dates.empty:
        return pd.DataFrame(columns=["activity_date", "is_active"])
    start = pd.Timestamp(start).normalize() if start is not None else dates.min()
    end = pd.Timestamp(end).normalize() if end is not None else dates.max()
    if start > end:
        start, end = end, start
    index = pd.date_range(start, end, freq="D")
    active = pd.Index(dates.unique())
    out = pd.DataFrame({"activity_date": index})
    out["is_active"] = out["activity_date"].isin(active)
    out["gap_days"] = _gap_days(out["is_active"])
    out["streak_length"] = streak_lengths_for_days(out["activity_date"][out["is_active"]])
    return out


def _gap_days(is_active: pd.Series) -> pd.Series:
    """Days since the previous active day, NaN on active days."""
    counter = np.full(len(is_active), np.nan)
    last_active = None
    for position, flag in enumerate(is_active.to_numpy()):
        if flag:
            last_active = position
            continue
        if last_active is not None:
            counter[position] = position - last_active
    return pd.Series(counter, index=is_active.index)


def streak_lengths_for_days(active_days: pd.Series) -> pd.Series:
    """For each active day, the length of the run it belongs to."""
    if active_days.empty:
        return pd.Series(dtype="int64")
    days = pd.to_datetime(pd.Series(active_days)).dt.normalize()
    order = days.sort_values()
    values = _to_days(order)
    breaks = np.concatenate([[True], np.diff(values) != 1])
    group = np.cumsum(breaks)
    lengths = pd.Series(group).map(pd.Series(group).value_counts())
    return pd.Series(lengths.to_numpy(), index=order.index).sort_index().astype("int64")


def streak_summary(
    active_dates: pd.Series,
    reference_date: Optional[pd.Timestamp] = None,
    grace_days: int = 1,
    observation_start: Optional[pd.Timestamp] = None,
) -> StreakSummary:
    """Compute the full streak metric set for one activity series.

    Parameters
    ----------
    active_dates:
        Dates on which activity happened (duplicates are collapsed).
    reference_date:
        "Today" for current-streak purposes. Defaults to the last active date.
    grace_days:
        How many days after the last active day a streak is still considered
        current. ``1`` treats a streak as live if the member was active today or
        yesterday.
    observation_start:
        Start of the observation window used for the consistency denominator.
        Defaults to the first active date.
    """
    dates = pd.to_datetime(pd.Series(active_dates)).dropna().dt.normalize()
    empty = StreakSummary(
        first_active_date=None,
        last_active_date=None,
        active_days=0,
        observation_days=0,
        consistency=0.0,
        longest_streak=0,
        current_streak=0,
        streak_ending_at_last_activity=0,
        average_streak=0.0,
        streak_break_count=0,
        run_count=0,
        max_gap_days=0,
        inactive_days=0,
    )
    if dates.empty:
        return empty

    unique_days = np.sort(dates.unique())
    first, last = pd.Timestamp(unique_days[0]), pd.Timestamp(unique_days[-1])
    reference = pd.Timestamp(reference_date).normalize() if reference_date is not None else last
    start = (
        pd.Timestamp(observation_start).normalize() if observation_start is not None else first
    )

    runs = run_lengths(dates)
    run_count = len(runs)
    observation_days = int((max(reference, last) - start).days) + 1
    active_days = int(len(unique_days))
    inactive_days = int(max(observation_days - active_days, 0))
    final_run = runs[-1] if runs else 0
    recency_from_last_activity = int((reference - last).days)
    current = final_run if recency_from_last_activity <= grace_days else 0

    gaps = np.diff(_to_days(unique_days))
    max_gap = int(gaps.max() - 1) if len(gaps) else 0

    return StreakSummary(
        first_active_date=first,
        last_active_date=last,
        active_days=active_days,
        observation_days=observation_days,
        consistency=round(active_days / observation_days, 6) if observation_days else 0.0,
        longest_streak=int(max(runs)) if runs else 0,
        current_streak=int(current),
        streak_ending_at_last_activity=int(final_run),
        average_streak=round(float(np.mean(runs)), 4) if runs else 0.0,
        streak_break_count=max(run_count - 1, 0),
        run_count=run_count,
        max_gap_days=max_gap,
        inactive_days=inactive_days,
    )


def streak_features_for_groups(
    events: pd.DataFrame,
    member_col: str = "member_id",
    date_col: str = "workout_date",
    reference_date: Optional[pd.Timestamp] = None,
    grace_days: int = 1,
) -> pd.DataFrame:
    """Member-level streak metrics for an event table.

    Used for the synthetic calendar layer; the returned ``feature_source``
    column states explicitly that date placement is synthetic.
    """
    if events.empty:
        return pd.DataFrame(
            columns=[
                member_col,
                "active_days",
                "observation_days",
                "consistency",
                "longest_streak",
                "current_streak",
                "streak_ending_at_last_activity",
                "average_streak",
                "streak_break_count",
                "run_count",
                "max_gap_days",
                "inactive_days",
                "first_active_date",
                "last_active_date",
            ]
        )
    frame = events.copy()
    frame[date_col] = pd.to_datetime(frame[date_col])
    rows: List[Dict[str, Any]] = []
    for member_id, group in frame.groupby(member_col, sort=False):
        summary = streak_summary(
            group[date_col], reference_date=reference_date, grace_days=grace_days
        )
        row = summary.as_dict()
        row[member_col] = member_id
        rows.append(row)
    out = pd.DataFrame(rows)
    out["feature_source"] = "synthetic_date_placement"
    return out


def platform_streak_series(daily: pd.DataFrame, date_col: str = "activity_date") -> pd.DataFrame:
    """Streak columns for a platform-level daily activity frame."""
    out = daily.copy()
    if out.empty:
        out["is_active_day"] = pd.Series(dtype=bool)
        out["platform_streak"] = pd.Series(dtype="int64")
        out["days_since_previous_active"] = pd.Series(dtype="float64")
        return out
    out[date_col] = pd.to_datetime(out[date_col])
    active = out["is_active_day"] if "is_active_day" in out.columns else out.get("events", 0) > 0
    out["is_active_day"] = active.fillna(False).astype(bool)
    out["days_since_previous_active"] = _gap_days(out["is_active_day"])
    out["platform_streak"] = (
        streak_lengths_for_days(out.loc[out["is_active_day"], date_col])
        .reindex(out.index)
        .fillna(0)
        .astype("int64")
    )
    return out

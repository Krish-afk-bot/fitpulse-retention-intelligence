"""Time-series analysis.

Two distinct time axes exist in FitPulse and they are kept strictly separate:

* **Platform activity time series** (real) — daily/monthly session volume and
  attendance rate from the activity source, covering calendar year 2024.
* **Member cohort series** (real) — retention/churn by join-year cohort from the
  membership source. This is *not* a monthly churn series: the membership source
  has no churn event date, so monthly churn over time is not derivable and is not
  fabricated.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from ..common.logging_utils import get_logger

logger = get_logger("analytics.timeseries")


def _add_rolling(frame: pd.DataFrame, column: str, windows: tuple[int, ...] = (7, 28)) -> pd.DataFrame:
    out = frame.copy()
    for window in windows:
        out[f"{column}_rolling_{window}"] = (
            out[column].rolling(window, min_periods=1).mean().round(6)
        )
    return out


def platform_daily_trend(daily: pd.DataFrame, value_column: str = "events") -> pd.DataFrame:
    """Daily platform series with rolling averages, cumulative totals and change."""
    if daily is None or daily.empty:
        return pd.DataFrame()
    frame = daily.sort_values("activity_date").copy()
    frame["activity_date"] = pd.to_datetime(frame["activity_date"])
    frame = _add_rolling(frame, value_column, windows=(7, 28))
    frame[f"{value_column}_cumulative"] = frame[value_column].cumsum()
    frame[f"{value_column}_change"] = frame[value_column].diff().round(4)
    frame[f"{value_column}_change_pct"] = (frame[value_column].pct_change() * 100).round(4)
    return frame


def platform_monthly_trend(monthly: pd.DataFrame) -> pd.DataFrame:
    """Monthly platform series with month-over-month change and a 3-month average."""
    if monthly is None or monthly.empty:
        return pd.DataFrame()
    frame = monthly.sort_values("month").copy()
    frame["month_index"] = range(1, len(frame) + 1)
    for column in ("events", "present_rate", "avg_duration", "total_calories"):
        if column in frame.columns:
            frame[f"{column}_rolling_3m"] = frame[column].rolling(3, min_periods=1).mean().round(6)
    if "events" in frame.columns:
        frame["events_mom_pct"] = (frame["events"].pct_change() * 100).round(4)
        frame["events_cumulative"] = frame["events"].cumsum()
    if "present_rate" in frame.columns:
        frame["present_rate_mom_pp"] = (frame["present_rate"].diff() * 100).round(4)
    return frame


def platform_weekly_trend(daily: pd.DataFrame) -> pd.DataFrame:
    """Weekly aggregation of the real daily platform series."""
    if daily is None or daily.empty:
        return pd.DataFrame()
    frame = daily.copy()
    frame["activity_date"] = pd.to_datetime(frame["activity_date"])
    frame["week_start"] = frame["activity_date"] - pd.to_timedelta(
        frame["activity_date"].dt.dayofweek, unit="D"
    )
    weekly = (
        frame.groupby(frame["week_start"].dt.date)
        .agg(
            events=("events", "sum"),
            present_count=("present_count", "sum"),
            total_duration=("total_duration", "sum"),
            active_days=("is_active_day", "sum"),
            calendar_days=("is_active_day", "count"),
        )
        .reset_index()
        .rename(columns={"week_start": "week_start"})
    )
    weekly["present_rate"] = (weekly["present_count"] / weekly["events"]).round(6)
    weekly["events_wow_pct"] = (weekly["events"].pct_change() * 100).round(4)
    weekly["events_rolling_4w"] = weekly["events"].rolling(4, min_periods=1).mean().round(4)
    return weekly


def monthly_retention_cohorts(members: pd.DataFrame) -> pd.DataFrame:
    """Retention by join-year cohort (the only honest cohort axis available)."""
    if members is None or members.empty or "join_date" not in members.columns:
        return pd.DataFrame()
    frame = members.copy()
    frame["join_ts"] = pd.to_datetime(frame["join_date"], errors="coerce")
    frame = frame.dropna(subset=["join_ts"])
    if frame.empty:
        return pd.DataFrame()
    frame["join_year"] = frame["join_ts"].dt.year
    frame["join_quarter"] = frame["join_ts"].dt.to_period("Q").astype("string")
    out = (
        frame.groupby(["join_year", "join_quarter"])
        .agg(
            members=("member_id", "count"),
            retained=("is_churned", lambda s: int((~s.astype(bool)).sum())),
            churned=("is_churned", lambda s: int(s.astype(bool).sum())),
            avg_visits_per_month=("visits_per_month", "mean"),
            avg_tenure_days=("tenure_days", "mean"),
        )
        .reset_index()
    )
    out["churn_rate"] = (100.0 * out["churned"] / out["members"]).round(4)
    out["retention_rate"] = (100.0 * out["retained"] / out["members"]).round(4)
    out["cumulative_members"] = out["members"].cumsum()
    return out.sort_values("join_quarter").reset_index(drop=True)


def detect_trend_direction(series: pd.Series, window: int = 3) -> Dict[str, Any]:
    """Lightweight trend statement: compare the last `window` points to the first."""
    values = pd.to_numeric(pd.Series(series), errors="coerce").dropna()
    if len(values) < window * 2:
        return {
            "direction": "insufficient_data",
            "change_pct": None,
            "explanation": "Not enough periods to assess a trend reliably.",
        }
    first = float(values.head(window).mean())
    last = float(values.tail(window).mean())
    change = 100.0 * (last - first) / first if first else 0.0
    if change > 2:
        direction = "increasing"
    elif change < -2:
        direction = "decreasing"
    else:
        direction = "stable"
    return {
        "direction": direction,
        "change_pct": round(change, 4),
        "first_window_mean": round(first, 4),
        "last_window_mean": round(last, 4),
        "explanation": (
            f"Mean of the first {window} periods is {first:,.2f} and of the last {window} "
            f"periods is {last:,.2f} ({change:+.2f}%)."
        ),
    }


def time_series_summary(
    daily: Optional[pd.DataFrame] = None, monthly: Optional[pd.DataFrame] = None
) -> Dict[str, Any]:
    """Narrative-ready summary of the platform time series."""
    summary: Dict[str, Any] = {}
    if monthly is not None and not monthly.empty:
        events_trend = detect_trend_direction(monthly["events"])
        summary["events_trend"] = events_trend
        summary["peak_month"] = str(monthly.loc[monthly["events"].idxmax(), "month"])
        summary["peak_events"] = int(monthly["events"].max())
        summary["lowest_month"] = str(monthly.loc[monthly["events"].idxmin(), "month"])
        summary["lowest_events"] = int(monthly["events"].min())
        if "present_rate" in monthly.columns:
            summary["present_rate_trend"] = detect_trend_direction(monthly["present_rate"])
            summary["present_rate_range_pct"] = [
                round(100.0 * float(monthly["present_rate"].min()), 2),
                round(100.0 * float(monthly["present_rate"].max()), 2),
            ]
    if daily is not None and not daily.empty:
        summary["active_day_share_pct"] = round(
            100.0 * float(daily["is_active_day"].mean()), 4
        )
        summary["longest_platform_streak_days"] = int(daily["platform_streak"].max())
    return summary

"""Streak-calculation tests.

Streaks are the one metric the real activity source cannot support (its
``member_id`` is a record sequence), so the derivation has to be exactly right
for the documented synthetic calendar to be trustworthy.
"""

from __future__ import annotations

import pandas as pd

from src.features import (
    run_lengths,
    streak_features_for_groups,
    streak_lengths_for_days,
    streak_summary,
)


def _days(*values: str) -> pd.Series:
    return pd.Series(pd.to_datetime(list(values)))


def test_run_lengths_splits_on_gaps():
    dates = _days("2024-01-01", "2024-01-02", "2024-01-03", "2024-01-06", "2024-01-07")
    assert run_lengths(dates) == [3, 2]


def test_run_lengths_collapses_duplicate_days():
    dates = _days("2024-01-01", "2024-01-01", "2024-01-02")
    assert run_lengths(dates) == [2]


def test_run_lengths_ignores_null_and_empty_input():
    assert run_lengths(pd.Series([], dtype="datetime64[ns]")) == []
    assert run_lengths(pd.Series([pd.NaT, pd.NaT])) == []


def test_streak_summary_basic_counts():
    summary = streak_summary(
        _days("2024-01-01", "2024-01-02", "2024-01-03", "2024-01-10"),
        reference_date=pd.Timestamp("2024-01-12"),
        grace_days=1,
    )
    assert summary.active_days == 4
    assert summary.longest_streak == 3
    assert summary.run_count == 2
    assert summary.average_streak == 2.0
    assert summary.streak_break_count == 1
    assert summary.max_gap_days == 6
    assert summary.first_active_date == pd.Timestamp("2024-01-01")
    assert summary.last_active_date == pd.Timestamp("2024-01-10")


def test_current_streak_requires_recent_activity():
    recent = streak_summary(
        _days("2024-03-01", "2024-03-02", "2024-03-03"),
        reference_date=pd.Timestamp("2024-03-03"),
    )
    assert recent.current_streak == 3
    # Two days of silence with grace_days=1 breaks the current streak but keeps
    # the "streak that ended at the last activity" measure intact.
    stale = streak_summary(
        _days("2024-03-01", "2024-03-02", "2024-03-03"),
        reference_date=pd.Timestamp("2024-03-05"),
        grace_days=1,
    )
    assert stale.current_streak == 0
    assert stale.streak_ending_at_last_activity == 3


def test_consistency_uses_the_observation_window():
    summary = streak_summary(
        _days("2024-01-01", "2024-01-11"),
        reference_date=pd.Timestamp("2024-01-11"),
    )
    assert summary.observation_days == 11
    assert summary.consistency == round(2 / 11, 6)
    assert summary.inactive_days == 9


def test_empty_series_returns_zeroed_summary():
    summary = streak_summary(pd.Series([], dtype="datetime64[ns]"))
    assert summary.active_days == 0
    assert summary.longest_streak == 0
    assert summary.first_active_date is None
    assert summary.consistency == 0.0


def test_streak_summary_is_a_pure_function_of_its_inputs():
    dates = _days("2024-05-01", "2024-05-02", "2024-05-09")
    first = streak_summary(dates, reference_date=pd.Timestamp("2024-05-10"))
    second = streak_summary(dates, reference_date=pd.Timestamp("2024-05-10"))
    assert first == second


def test_streak_features_for_groups_never_leaks_across_members():
    events = pd.DataFrame(
        {
            "member_id": ["A", "A", "A", "B", "B"],
            "workout_date": pd.to_datetime(
                ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-01", "2024-01-05"]
            ),
        }
    )
    features = streak_features_for_groups(
        events, reference_date=pd.Timestamp("2024-01-06")
    ).set_index("member_id")
    assert features.loc["A", "longest_streak"] == 3
    assert features.loc["B", "longest_streak"] == 1
    assert features.loc["A", "active_days"] == 3
    assert features.loc["B", "active_days"] == 2


def test_streak_features_degrade_gracefully_on_empty_input():
    empty = pd.DataFrame({"member_id": [], "workout_date": []})
    features = streak_features_for_groups(empty)
    assert features.empty


def test_streak_lengths_for_days_labels_each_day_with_its_run_length():
    days = pd.Series(pd.to_datetime(["2024-02-01", "2024-02-02", "2024-02-05"]))
    lengths = streak_lengths_for_days(days)
    assert lengths.tolist() == [2, 2, 1]
    assert sorted(set(lengths)) == sorted(set(run_lengths(days)))

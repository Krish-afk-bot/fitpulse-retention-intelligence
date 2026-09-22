"""Cleaning-layer tests: every transformation must be measurable and auditable."""

from __future__ import annotations

import pandas as pd

import pytest

from src.cleaning import clean_activity_source, clean_membership_source, observation_date_from
from src.common.config import get_settings


# ---------------------------------------------------------------------------
# Activity source
# ---------------------------------------------------------------------------
def test_activity_duplicate_records_are_removed_and_counted(cleaned_activity, dirty_activity_frame):
    assert cleaned_activity.rows_in == len(dirty_activity_frame)
    # Two records are unusable and therefore removed, each with its own measured
    # step: the exact duplicate, and the row whose activity date cannot be parsed.
    assert cleaned_activity.rows_out == len(dirty_activity_frame) - 2
    duplicates = next(s for s in cleaned_activity.steps if s.step == "drop_duplicate_workout_id")
    assert duplicates.rows_before - duplicates.rows_after == 1


def test_activity_categories_are_normalised(cleaned_activity):
    frame = cleaned_activity.frame
    # "male" / " monthly " / "cardio" / "present" in the raw file.
    assert set(frame["gender"].dropna()) <= {"Male", "Female"}
    assert set(frame["membership_type"].dropna()) <= {"Monthly", "Annual", "Quarterly"}
    assert set(frame["workout_type"].dropna()) <= {
        "Cardio",
        "HIIT",
        "Yoga",
        "Strength Training",
        "CrossFit",
    }
    assert set(frame["attendance_status"].dropna()) <= {"Present", "Absent"}


def test_activity_placeholder_string_becomes_null(cleaned_activity):
    frame = cleaned_activity.frame
    row = frame.loc[frame["source_member_ref"].astype(str) == "11"]
    assert len(row) == 1
    assert pd.isna(row["membership_type"].iloc[0])


def test_activity_unparseable_date_is_flagged_and_removed(cleaned_activity):
    """A session that cannot be placed in time is reported, then dropped.

    Keeping it would let the headline session total exceed the sum of the daily
    time series, so the removal is explicit and auditable instead.
    """
    parsed = next(s for s in cleaned_activity.steps if s.step == "parse_date[visit_date]")
    assert "unparseable dates: 1" in parsed.note
    dropped = next(s for s in cleaned_activity.steps if s.step == "drop_unparseable_workout_date")
    assert dropped.rows_before - dropped.rows_after == 1
    assert "could not be parsed" in dropped.note
    assert cleaned_activity.frame["workout_date"].isna().sum() == 0


def test_activity_negative_duration_is_preserved_for_validation(cleaned_activity):
    durations = cleaned_activity.frame["duration_minutes"]
    assert (durations < 0).any(), "cleaning must not silently repair negative durations"


def test_activity_member_id_is_intentionally_null(cleaned_activity):
    """The activity source's member_id is a record sequence, not a member key."""
    assert cleaned_activity.frame["member_id"].isna().all()
    assert cleaned_activity.frame["source_member_ref"].notna().all()


def test_activity_audit_trail_covers_every_step(cleaned_activity):
    steps = {s.step for s in cleaned_activity.steps}
    for expected in (
        "placeholder_to_null",
        "strip_whitespace",
        "cast_numeric",
        "drop_unparseable_workout_date",
        "drop_duplicate_workout_id",
    ):
        assert expected in steps
    assert cleaned_activity.rows_in - cleaned_activity.rows_out == cleaned_activity.duplicates_removed
    assert cleaned_activity.summary_text().startswith("Rows before:")


def test_activity_outlier_classification_is_reported_not_applied(cleaned_activity):
    assert any("Outlier classification" in note for note in cleaned_activity.notes)


# ---------------------------------------------------------------------------
# Membership source
# ---------------------------------------------------------------------------
def test_membership_pii_is_dropped(cleaned_membership):
    tables = {name: result.frame for name, result in cleaned_membership.items()}
    for name, frame in tables.items():
        for column in ("Name", "Address", "Phone_Number"):
            assert column not in frame.columns, f"{column} leaked into {name}"


def test_membership_duplicate_member_removed(cleaned_membership, dirty_membership_frame):
    dim_member = cleaned_membership["dim_member"].frame
    assert len(dim_member) == len(dirty_membership_frame) - 1
    assert dim_member["member_id"].is_unique


def test_membership_missing_values_are_imputed_with_flags(cleaned_membership):
    dim_member = cleaned_membership["dim_member"].frame
    fact = cleaned_membership["fact_membership"].frame
    assert dim_member["age"].notna().all()
    assert fact["visits_per_month"].notna().all()
    # Member 6 has no Age and member 5 has no Visits_Per_Month in the fixture; every
    # imputation carries an explicit flag so KPIs can be recomputed on complete cases.
    assert bool(fact.loc[fact["member_id"] == "M-0006", "age_imputed"].iloc[0]) is True
    assert bool(fact.loc[fact["member_id"] == "M-0005", "visits_per_month_imputed"].iloc[0]) is True
    assert bool(fact.loc[fact["member_id"] == "M-0006", "visits_per_month_imputed"].iloc[0]) is False
    assert bool(fact.loc[fact["member_id"] == "M-0001", "age_imputed"].iloc[0]) is False
    assert bool(fact.loc[fact["member_id"] == "M-0001", "visits_per_month_imputed"].iloc[0]) is False


def test_membership_broken_date_order_is_preserved_for_validation(cleaned_membership):
    """join_date > last_visit_date is a business-rule finding, not a silent edit."""
    fact = cleaned_membership["fact_membership"].frame
    broken = fact[fact["join_date"] > fact["last_visit_date"]]
    assert len(broken) == 1
    assert broken["member_id"].iloc[0] == "M-0004"


def test_membership_churn_label_is_boolean(cleaned_membership):
    fact = cleaned_membership["fact_membership"].frame
    assert pd.api.types.is_bool_dtype(fact["churn_status"])
    # "yes"/"No"/" yes " in the fixture.
    assert fact["churn_status"].sum() == 3


def test_membership_median_imputation_leaves_row_count_unchanged(cleaned_membership):
    fact = cleaned_membership["fact_membership"]
    assert fact.rows_in == fact.rows_out


def test_observation_date_falls_back_to_the_configured_date(loaded_membership):
    """An explicit observation date wins; otherwise the last known visit is used."""
    settings = get_settings()
    if settings.as_of_date:
        pytest.skip("FITPULSE_AS_OF_DATE is set, so the configured date always wins")
    explicit = observation_date_from(loaded_membership, fallback=pd.Timestamp("2020-01-01"))
    assert explicit == pd.Timestamp("2024-06-30")
    assert observation_date_from(None, fallback=pd.Timestamp("2020-01-01")) == pd.Timestamp("2020-01-01")


def test_clean_membership_without_pii_column_does_not_crash(dirty_membership_frame):
    frame = dirty_membership_frame.drop(columns=["Phone_Number", "Address"])
    from src.ingestion.loader import LoadedSource

    from src.ingestion import MEMBERSHIP_SOURCE, inspect_source_schema

    source = LoadedSource(
        name="membership",
        path=None,
        frame=frame,
        schema_report=inspect_source_schema(frame, MEMBERSHIP_SOURCE),
    )
    result = clean_membership_source(source)
    assert "dim_member" in result


def test_cleaning_never_mutates_the_input_frame(dirty_activity_frame, loaded_activity):
    before = dirty_activity_frame.copy(deep=True)
    clean_activity_source(loaded_activity)
    pd.testing.assert_frame_equal(dirty_activity_frame, before)

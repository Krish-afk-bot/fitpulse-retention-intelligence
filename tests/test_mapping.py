"""Tests for the canonical mapping layer and capability-driven pipeline.

These cover the dataset-flexibility requirements directly: arbitrary column
names, value-plausibility rejections, ambiguous flags, missing outcomes, partial
datasets, and the integrity rules that prevent fabricated joins.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.ingestion import (
    ROLE_ACTIVITY,
    ROLE_MEMBERSHIP,
    assess_compatibility,
    capability_map,
    contract_frame,
    detect_role,
    ingest_mapped_frame,
    member_key_repeatable,
    suggest_mapping,
)
from src.pipeline import run_pipeline


@pytest.fixture(scope="module")
def activity_frame() -> pd.DataFrame:
    rng = np.random.default_rng(11)
    n = 240
    return pd.DataFrame(
        {
            "customer_id": [f"C{i:04d}" for i in range(n)],
            "session_date": pd.date_range("2024-01-01", periods=n, freq="6h").astype(str),
            "activity_type": rng.choice(["Cardio", "Yoga", "HIIT"], n),
            "duration": rng.integers(20, 90, n),
            "calories": rng.integers(100, 900, n),
            "attended": rng.choice(["yes", "no"], n),
            "start_time": [f"{hour:02d}:30" for hour in rng.integers(6, 21, n)],
        }
    )


@pytest.fixture(scope="module")
def membership_frame() -> pd.DataFrame:
    rng = np.random.default_rng(12)
    rows = 90
    return pd.DataFrame(
        {
            "user_id": [f"U{i}" for i in range(rows)],
            "member_age": rng.integers(18, 65, rows),
            "sex": rng.choice(["M", "F"], rows),
            "plan": rng.choice(["Monthly", "Annual"], rows),
            "signup_date": pd.date_range("2021-01-01", periods=rows, freq="5D").astype(str),
            "last_seen": pd.date_range("2024-06-01", periods=rows, freq="1D").astype(str),
            "avg_duration": rng.integers(30, 100, rows),
            "avg_visits_per_month": rng.integers(1, 25, rows),
            "is_churned": rng.choice(["No", "Yes"], rows, p=[0.7, 0.3]),
        }
    )


# ---------------------------------------------------------------------------
# Detection and mapping
# ---------------------------------------------------------------------------
def test_role_detection_separates_activity_from_membership(activity_frame, membership_frame):
    assert detect_role(activity_frame).role == ROLE_ACTIVITY
    assert detect_role(membership_frame).role == ROLE_MEMBERSHIP
    assert detect_role(activity_frame).confidence in {"high", "medium"}


def test_renamed_columns_map_onto_the_canonical_model(activity_frame):
    mapping = suggest_mapping(activity_frame)
    assert mapping.column_for("activity_date") == "session_date"
    assert mapping.column_for("duration_minutes") == "duration"
    assert mapping.column_for("calories_burned") == "calories"
    assert mapping.column_for("attendance_status") == "attended"
    assert mapping.column_for("member_id") == "customer_id"
    matches = mapping.matches
    assert matches["activity_date"].confidence == "high"


def test_aliases_accept_common_spellings():
    frame = pd.DataFrame(
        {
            "MemberID": ["1", "2", "3"],
            "Workout Date": ["2024-01-01", "2024-01-02", "2024-01-03"],
            "Calories Burned": [100, 200, 300],
        }
    )
    mapping = suggest_mapping(frame)
    assert mapping.column_for("member_id") == "MemberID"
    assert mapping.column_for("activity_date") == "Workout Date"
    assert mapping.column_for("calories_burned") == "Calories Burned"


def test_values_must_be_plausible_for_the_field():
    """A numeric column must never be mapped onto a date field."""
    frame = pd.DataFrame(
        {
            "revenue": [10.5, 20.25, 30.75, 40.0, 55.5],
            "member_id": ["A", "B", "C", "D", "E"],
        }
    )
    mapping = suggest_mapping(frame, role=ROLE_ACTIVITY)
    assert mapping.column_for("activity_date") is None


def test_missing_churn_removes_retention_capabilities(membership_frame):
    without_churn = membership_frame.drop(columns=["is_churned"])
    mapping = suggest_mapping(without_churn, role=ROLE_MEMBERSHIP)
    report = assess_compatibility(without_churn, mapping)
    capabilities = capability_map(report.capabilities)
    assert capabilities["retention_analysis"] is False
    assert capabilities["churn_analysis"] is False
    assert capabilities["segmentation"] is False
    # Engagement measures are still real and still available.
    assert capabilities["engagement_analysis"] is True
    assert "no churn" in " ".join(report.warnings).lower()


def test_ambiguous_flag_requires_confirmation():
    """Two-state values with no recognisable vocabulary are flagged, not guessed."""
    frame = pd.DataFrame(
        {
            "customer_id": [f"C{i}" for i in range(10)],
            "session_date": pd.date_range("2024-01-01", periods=10, freq="D").astype(str),
            "outcome": ["gold"] * 8 + ["silver"] * 2,
        }
    )
    mapping = suggest_mapping(frame)
    match = mapping.matches.get("attendance_status")
    if match:
        assert match.needs_confirmation
        assert match.confidence in {"low", "medium"}


def test_inverted_active_flag_expresses_churn(membership_frame):
    frame = membership_frame.drop(columns=["is_churned"]).copy()
    frame["active"] = np.tile([1, 0], len(frame) // 2)
    source, mapping, report = ingest_mapped_frame(frame, role=ROLE_MEMBERSHIP)
    assert mapping.column_for("churn_status") == "active"
    values = set(source.frame["Churn"].dropna().unique())
    assert values <= {"Yes", "No"}
    assert source.frame["Churn"].eq("No").sum() == int((frame["active"] == 1).sum())


def test_manual_override_wins_and_is_recorded():
    frame = pd.DataFrame(
        {
            "customer_id": [f"C{i}" for i in range(20)],
            "when": pd.date_range("2024-01-01", periods=20, freq="D").astype(str),
            "how_long": np.arange(20) + 10,
        }
    )
    auto = suggest_mapping(frame)
    assert auto.column_for("duration_minutes") is None
    auto_report = assess_compatibility(frame, auto)
    overridden = suggest_mapping(frame, overrides={"duration_minutes": "how_long"})
    assert overridden.column_for("duration_minutes") == "how_long"
    assert overridden.matches["duration_minutes"].matched_by == "confirmed by user"
    assert overridden.confirmed is True
    assert len(assess_compatibility(frame, overridden).available_capabilities) >= len(
        auto_report.available_capabilities
    )


# ---------------------------------------------------------------------------
# Degraded source files
# ---------------------------------------------------------------------------
def test_a_partly_malformed_date_column_still_runs():
    """A date column with a few unusable values is still a date column."""
    frame = pd.DataFrame(
        {
            "member_id": [f"M{i}" for i in range(12)],
            "workout_date": [f"2024-01-{day:02d}" for day in range(1, 11)] + ["not a date", ""],
            "duration": [30] * 12,
        }
    )
    source, mapping, report = ingest_mapped_frame(frame, role=ROLE_ACTIVITY, label="messy.csv", origin="test")
    assert mapping.column_for("activity_date") == "workout_date"
    result = _run({"activity": source})
    assert result.mode == "activity_only"
    # Unparseable dates are dropped by cleaning, not counted as sessions.
    assert result.kpis["platform_events"] == 10
    assert len(result.table("fact_workout")) == 10
    # Headline sessions must equal the sum of the time series.
    daily = result.table("platform_daily_activity")
    assert len(daily) == 10
    steps = pd.DataFrame(result.metadata["cleaning"]["activity"]["steps"])
    dropped = steps[steps["step"].eq("drop_unparseable_workout_date")]
    assert int(dropped["rows_removed"].sum()) == 2


def test_a_mostly_unusable_date_column_is_refused_and_can_be_confirmed():
    """A column that is not really a date must not be mapped on the header alone."""
    frame = pd.DataFrame(
        {
            "member_id": [f"M{i}" for i in range(12)],
            "workout_date": ["2024-01-01", "not a date", "2024-03-15"] + [""] * 9,
            "duration": [30, 45, 60] + [None] * 9,
        }
    )
    mapping = suggest_mapping(frame, role=ROLE_ACTIVITY)
    assert mapping.column_for("activity_date") is None
    report = assess_compatibility(frame, mapping)
    assert report.status == "FAIL"
    assert "activity_date" in report.missing_required
    # The user can still assert the mapping; then it is recorded as confirmed.
    confirmed = suggest_mapping(frame, role=ROLE_ACTIVITY, overrides={"activity_date": "workout_date"})
    assert confirmed.column_for("activity_date") == "workout_date"
    assert confirmed.matches["activity_date"].matched_by == "confirmed by user"


def test_no_timeline_is_invented_without_a_real_date():
    """A membership export with no usable dates degrades instead of crashing."""
    frame = pd.DataFrame(
        {
            "user_id": [f"U{i}" for i in range(40)],
            "plan": ["Monthly", "Annual"] * 20,
            "avg_visits_per_month": [12] * 40,
            "is_churned": ["No"] * 28 + ["Yes"] * 12,
        }
    )
    membership, _mapping, _report = ingest_mapped_frame(frame, role=ROLE_MEMBERSHIP, label="nodates.csv", origin="test")
    result = _run({"membership": membership})
    assert result.kpis["retention_rate"] is not None
    synthetic = result.table("fact_workout_synthetic")
    assert synthetic.empty
    assert result.integration["join_performed"] is False


def test_missing_values_do_not_block_a_run(membership_frame):
    """Optional fields with gaps still support the analyses that do not need them."""
    frame = membership_frame.copy()
    frame.loc[frame.index[:30], "avg_visits_per_month"] = np.nan
    frame.loc[frame.index[:15], "member_age"] = np.nan
    membership, mapping, report = ingest_mapped_frame(frame, role=ROLE_MEMBERSHIP, label="gaps.csv", origin="test")
    assert mapping.column_for("member_id") == "user_id"
    assert report.status != "FAIL"
    result = _run({"membership": membership})
    assert result.kpis["total_members"] == len(frame)
    assert result.kpis["retention_rate"] is not None


def test_duplicate_identifiers_are_counted_not_invented(membership_frame):
    """Repeated ids must be reported as duplicates rather than fabricating members."""
    frame = pd.concat([membership_frame, membership_frame.head(10)], ignore_index=True)
    membership, _mapping, report = ingest_mapped_frame(frame, role=ROLE_MEMBERSHIP, label="dupes.csv", origin="test")
    assert len(frame) > len(membership_frame)
    result = _run({"membership": membership})
    # Distinct members is the deduplicated truth, never the raw row count.
    assert len(frame) == len(membership_frame) + 10
    assert result.kpis["total_members"] == len(membership_frame)
    # The removal is measured, not silent: the cleaning audit trail records it.
    steps = pd.DataFrame(result.metadata["cleaning"]["dim_member"]["steps"])
    dedupe = steps[steps["step"].astype(str).str.contains("duplicate")]
    assert not dedupe.empty
    assert int(dedupe["rows_removed"].sum()) == 10


def test_unknown_dataset_is_reported_not_guessed():
    frame = pd.DataFrame({"foo": ["a", "b", "c"], "bar": [1, 2, 3]})
    detection = detect_role(frame)
    assert detection.role == "unknown"
    report = assess_compatibility(frame, suggest_mapping(frame))
    assert report.status == "FAIL"
    assert report.missing_required
    assert report.score < 50


# ---------------------------------------------------------------------------
# Contract adaptation
# ---------------------------------------------------------------------------
def test_contract_frame_uses_role_specific_column_names(activity_frame, membership_frame):
    activity_contract, _ = contract_frame(activity_frame, suggest_mapping(activity_frame))
    assert "visit_date" in activity_contract.columns
    assert "member_id" in activity_contract.columns
    assert "Member_ID" not in activity_contract.columns

    membership_contract, _ = contract_frame(
        membership_frame, suggest_mapping(membership_frame, role=ROLE_MEMBERSHIP)
    )
    assert "Member_ID" in membership_contract.columns
    assert "Churn" in membership_contract.columns


def test_activity_identifier_repeatability_is_detected():
    unique = pd.DataFrame({"member_id": ["1", "2", "3"], "visit_date": ["2024-01-01"] * 3})
    repeating = pd.DataFrame({"member_id": ["1", "1", "2"], "visit_date": ["2024-01-01"] * 3})
    assert member_key_repeatable(unique, "member_id") is False
    assert member_key_repeatable(repeating, "member_id") is True


def test_sequential_record_number_is_not_treated_as_a_member_key():
    frame = pd.DataFrame(
        {
            "session_date": pd.date_range("2024-01-01", periods=15, freq="D").astype(str),
            "duration": np.arange(15) + 20,
        }
    )
    source, _mapping, _report = ingest_mapped_frame(frame, role=ROLE_ACTIVITY)
    assert source.member_key_repeatable is False
    assert any("record number" in note for note in source.assumptions)


# ---------------------------------------------------------------------------
# Capability-driven pipeline
# ---------------------------------------------------------------------------
def _run(sources):
    return run_pipeline(sources=sources, write_artifacts=False, build_database=False)


def test_full_mode_with_renamed_datasets_matches_reference_behaviour(activity_frame, membership_frame):
    activity, _, _ = ingest_mapped_frame(activity_frame, label="activity.csv", origin="test")
    membership, _, _ = ingest_mapped_frame(membership_frame, label="members.csv", origin="test")
    result = _run({"activity": activity, "membership": membership})
    assert result.mode == "full"
    assert result.kpis["total_members"] == len(membership_frame)
    assert result.kpis["platform_events"] == len(activity_frame)
    assert 0 <= result.kpis["retention_rate"] <= 100
    assert result.supports("sql_validation")


def test_membership_only_mode_reports_retention_without_activity(membership_frame):
    membership, _, _ = ingest_mapped_frame(membership_frame, label="members.csv", origin="test")
    result = _run({"membership": membership})
    assert result.mode == "membership_only"
    assert result.kpis["retention_rate"] is not None
    assert result.kpis.get("platform_events") is None
    assert result.supports("retention_analysis") is True
    assert result.supports("activity_analysis") is False
    assert result.supports("sql_validation") is False


def test_activity_only_mode_reports_platform_metrics_only(activity_frame):
    activity, _, _ = ingest_mapped_frame(activity_frame, label="activity.csv", origin="test")
    result = _run({"activity": activity})
    assert result.mode == "activity_only"
    assert result.kpis["platform_events"] == len(activity_frame)
    assert result.kpis.get("retention_rate") is None
    assert result.kpis.get("total_members") is None
    assert result.supports("retention_analysis") is False
    # The session-level funnel and trends are still real.
    assert result.supports("funnel_analysis") is True
    assert not result.analysis("platform_funnel").empty


def test_membership_without_churn_reports_no_retention(membership_frame):
    membership, _, _ = ingest_mapped_frame(
        membership_frame.drop(columns=["is_churned"]), label="no-churn.csv", origin="test"
    )
    result = _run({"membership": membership})
    assert result.kpis["outcome_available"] is False
    assert result.kpis["retention_rate"] is None
    assert result.kpis["churn_rate"] is None
    # Engagement measures are real and must still be reported.
    assert result.kpis["avg_visits_per_month"] is not None
    assert result.supports("retention_analysis") is False
    assert result.analyses["unavailable"]


def test_partial_run_produces_a_capability_report(activity_frame):
    activity, _, _ = ingest_mapped_frame(activity_frame, label="activity.csv", origin="test")
    result = _run({"activity": activity})
    assert result.report_markdown
    assert "Not available with this dataset" in result.report_markdown


def test_no_fabricated_join_between_sources(activity_frame, membership_frame):
    """Identifiers are namespaced and no join is performed."""
    activity, _, _ = ingest_mapped_frame(activity_frame, label="activity.csv", origin="test")
    membership, _, _ = ingest_mapped_frame(membership_frame, label="members.csv", origin="test")
    result = _run({"activity": activity, "membership": membership})
    assert result.integration["join_performed"] is False
    assert "none" in str(result.integration["join_type"]).lower()
    # Membership keys and activity references live in different namespaces.
    member_ids = set(result.table("dim_member")["member_id"].head(20))
    activity_refs = set(result.table("fact_workout")["source_member_ref"].head(20))
    assert member_ids and activity_refs
    assert member_ids.isdisjoint(activity_refs)
    # The synthetic bridge stays in its own table, clearly labelled.
    synthetic = result.table("fact_workout_synthetic")
    if not synthetic.empty:
        assert bool(synthetic["is_synthetic"].all())


def test_pipeline_rejects_an_empty_dataset_set():
    from src.ingestion import IngestionError

    with pytest.raises(IngestionError):
        run_pipeline(sources={}, write_artifacts=False, build_database=False)

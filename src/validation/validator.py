"""Validation orchestrator.

Assembles the reusable rules from :mod:`src.validation.rules` into complete,
source-specific validation reports. Every rule set below is grounded in the
*actual* observed schema of the two Kaggle sources.
"""

from __future__ import annotations

from typing import Any, Dict, Sequence

import pandas as pd

from ..common.logging_utils import get_logger
from ..ingestion.loader import LoadedSource
from ..ingestion.schema import ACTIVITY_SOURCE, MEMBERSHIP_SOURCE
from .results import (
    FAIL,
    PASS,
    WARNING,
    CheckResult,
    ValidationReport,
    worst_status,
)
from .rules import (
    check_categories,
    check_conditional_values,
    check_date_order,
    check_distinct_dates,
    check_intentionally_null,
    check_date_within_window,
    check_duplicate_rows,
    check_key_uniqueness,
    check_missingness,
    check_numeric_between,
    check_numeric_min,
    check_referential_columns,
    check_required_columns,
    check_share_of_population,
    check_type_conversion,
    check_unexpected_columns,
    check_value_domain,
    check_whitespace_hygiene,
)

logger = get_logger("validation")

# --- Documented category domains, observed in the real source files --------
ACTIVITY_GENDERS = ("Male", "Female", "Other")
ACTIVITY_MEMBERSHIP_TYPES = ("Monthly", "Quarterly", "Annual")
ACTIVITY_WORKOUT_TYPES = ("Strength Training", "Cardio", "HIIT", "CrossFit", "Yoga")
ATTENDANCE_STATES = ("Present", "Absent")

MEMBERSHIP_GENDERS = ("Male", "Female")
MEMBERSHIP_TYPES = ("Monthly", "Quarterly", "Yearly")
MEMBERSHIP_CHURN_VALUES = ("Yes", "No")
MEMBERSHIP_EXERCISES = (
    "Deadlift",
    "Pull-ups",
    "Squats",
    "Bench Press",
    "Treadmill",
    "Cycling",
)

ACTIVITY_DATE_WINDOW = (pd.Timestamp("2024-01-01"), pd.Timestamp("2024-12-31"))


# ---------------------------------------------------------------------------
# Activity source
# ---------------------------------------------------------------------------
def validate_activity_source(
    frame: pd.DataFrame, dataset: str = "activity_source"
) -> ValidationReport:
    """Full rule set for the activity/attendance source.

    Note the deliberate check ``business.nominal_values_for_absent`` — the real
    source records non-zero duration and calories for sessions marked
    ``Absent``, so those measures are nominal (scheduled) rather than confirmed.
    """
    report = ValidationReport(dataset=dataset)
    report.add(
        check_required_columns(frame, ACTIVITY_SOURCE.required_columns, dataset)
    )
    report.add(
        check_unexpected_columns(frame, ACTIVITY_SOURCE.expected_columns, dataset)
    )

    # --- types ---
    report.add(
        check_type_conversion(
            frame["visit_date"] if "visit_date" in frame else pd.Series(dtype=object),
            "date",
            dataset,
            "schema.visit_date_parseable",
            "visit_date parses as a date",
            fail_pct=0.0,
        )
    )
    report.add(
        check_type_conversion(
            frame["check_in_time"] if "check_in_time" in frame else pd.Series(dtype=object),
            "time",
            dataset,
            "schema.check_in_time_parseable",
            "check_in_time parses as HH:MM",
            fail_pct=1.0,
        )
    )
    for column in ACTIVITY_SOURCE.numeric_columns:
        if column in frame.columns:
            report.add(
                check_type_conversion(
                    frame[column],
                    "numeric",
                    dataset,
                    f"schema.{column}_numeric",
                    f"{column} is numeric",
                    fail_pct=0.0,
                )
            )

    # --- numeric ranges ---
    report.add(
        check_numeric_min(
            frame,
            "workout_duration_minutes",
            0,
            dataset,
            "numeric.duration_non_negative",
            "workout_duration_minutes >= 0",
            fail_pct=0.0,
        )
    )
    report.add(
        check_numeric_min(
            frame,
            "calories_burned",
            0,
            dataset,
            "numeric.calories_non_negative",
            "calories_burned >= 0",
            fail_pct=0.0,
        )
    )
    report.add(
        check_numeric_between(
            frame,
            "workout_duration_minutes",
            1,
            300,
            dataset,
            "numeric.duration_plausible",
            "1 <= workout_duration_minutes <= 300",
            fail_pct=2.0,
        )
    )
    report.add(
        check_numeric_between(
            frame,
            "age",
            13,
            100,
            dataset,
            "numeric.age_plausible",
            "13 <= age <= 100",
            fail_pct=1.0,
        )
    )
    report.add(
        check_numeric_between(
            frame,
            "calories_burned",
            0,
            3000,
            dataset,
            "numeric.calories_plausible",
            "0 <= calories_burned <= 3000",
            fail_pct=2.0,
        )
    )

    # --- dates ---
    report.add(
        check_date_within_window(
            frame,
            "visit_date",
            *ACTIVITY_DATE_WINDOW,
            dataset,
            "date.visit_date_window",
            fail_pct=0.0,
        )
    )

    # --- categories ---
    report.add(check_categories(frame, "gender", ACTIVITY_GENDERS, dataset, "category.gender_allowed"))
    report.add(
        check_categories(
            frame, "membership_type", ACTIVITY_MEMBERSHIP_TYPES, dataset, "category.membership_type_allowed"
        )
    )
    report.add(
        check_categories(frame, "workout_type", ACTIVITY_WORKOUT_TYPES, dataset, "category.workout_type_allowed")
    )
    report.add(
        check_categories(
            frame, "attendance_status", ATTENDANCE_STATES, dataset, "category.attendance_status_allowed"
        )
    )
    report.add(
        check_whitespace_hygiene(
            frame, ACTIVITY_SOURCE.categorical_columns, dataset, "category.activity_string_hygiene"
        )
    )

    # --- duplicates ---
    report.add(
        check_duplicate_rows(
            frame, dataset, warn_pct=1.0, fail_pct=5.0, check_id="duplicate.exact_rows"
        )
    )
    report.add(
        check_key_uniqueness(frame, "member_id", dataset, "duplicate.member_id_uniqueness")
    )

    # --- missingness ---
    report.extend(
        check_missingness(
            frame,
            dataset,
            default_warn_pct=1.0,
            default_fail_pct=10.0,
            check_id="missing.activity_null_rate",
        )
    )

    # --- business rules ---
    report.add(
        check_conditional_values(
            frame,
            condition_column="attendance_status",
            condition_value="Absent",
            value_columns=("workout_duration_minutes", "calories_burned"),
            dataset=dataset,
            check_id="business.nominal_values_for_absent",
            description=(
                "Absent sessions should not report completed duration/calories "
                "(flags nominal vs confirmed workout measures)"
            ),
            warn_pct=10.0,
        )
    )
    report.add(
        check_share_of_population(
            frame,
            "attendance_status",
            "Present",
            expected_min_pct=20.0,
            expected_max_pct=80.0,
            dataset=dataset,
            check_id="business.attendance_rate_plausible",
            description="Attendance (Present) share is within a plausible band",
        )
    )
    return report


# ---------------------------------------------------------------------------
# Membership source
# ---------------------------------------------------------------------------
def validate_membership_source(
    frame: pd.DataFrame, dataset: str = "membership_source"
) -> ValidationReport:
    """Full rule set for the membership/churn source."""
    report = ValidationReport(dataset=dataset)
    report.add(
        check_required_columns(frame, MEMBERSHIP_SOURCE.required_columns, dataset)
    )
    report.add(
        check_unexpected_columns(frame, MEMBERSHIP_SOURCE.expected_columns, dataset)
    )

    for column in ("Join_Date", "Last_Visit_Date"):
        if column in frame.columns:
            report.add(
                check_type_conversion(
                    frame[column],
                    "date",
                    dataset,
                    f"schema.{column.lower()}_parseable",
                    f"{column} parses as a date",
                    fail_pct=2.0,
                )
            )
    for column in ("Visits_Per_Month", "Avg_Workout_Duration_Min", "Avg_Calories_Burned", "Age"):
        if column in frame.columns:
            report.add(
                check_type_conversion(
                    frame[column],
                    "numeric",
                    dataset,
                    f"schema.{column.lower()}_numeric",
                    f"{column} is numeric",
                    fail_pct=2.0,
                )
            )

    # --- numeric ranges ---
    report.add(
        check_numeric_min(
            frame, "Visits_Per_Month", 0, dataset, "numeric.visits_per_month_non_negative",
            "Visits_Per_Month >= 0", fail_pct=0.0,
        )
    )
    report.add(
        check_numeric_min(
            frame, "Avg_Workout_Duration_Min", 0, dataset, "numeric.avg_duration_non_negative",
            "Avg_Workout_Duration_Min >= 0", fail_pct=0.0,
        )
    )
    report.add(
        check_numeric_between(
            frame, "Age", 13, 100, dataset, "numeric.age_plausible", "13 <= Age <= 100", fail_pct=5.0
        )
    )
    report.add(
        check_numeric_between(
            frame, "Visits_Per_Month", 0, 31, dataset, "numeric.visits_plausible",
            "0 <= Visits_Per_Month <= 31", fail_pct=5.0,
        )
    )
    report.add(
        check_numeric_between(
            frame, "Avg_Calories_Burned", 0, 3000, dataset, "numeric.avg_calories_plausible",
            "0 <= Avg_Calories_Burned <= 3000", fail_pct=5.0,
        )
    )

    # --- dates ---
    report.add(
        check_date_order(
            frame,
            "Join_Date",
            "Last_Visit_Date",
            dataset,
            "date.join_lte_last_visit",
            "Join_Date <= Last_Visit_Date",
            fail_pct=0.0,
        )
    )
    report.add(
        check_date_within_window(
            frame,
            "Join_Date",
            pd.Timestamp("2000-01-01"),
            pd.Timestamp("2026-12-31"),
            dataset,
            "date.join_date_window",
            fail_pct=2.0,
        )
    )
    report.add(
        check_distinct_dates(
            frame,
            "Join_Date",
            "Last_Visit_Date",
            dataset,
            "date.degenerate_observation_window",
            "Join_Date differs from Last_Visit_Date (non-degenerate observation window)",
        )
    )

    # --- categories ---
    report.add(check_categories(frame, "Gender", MEMBERSHIP_GENDERS, dataset, "category.gender_allowed"))
    report.add(
        check_categories(
            frame, "Membership_Type", MEMBERSHIP_TYPES, dataset, "category.membership_type_allowed"
        )
    )
    report.add(check_categories(frame, "Churn", MEMBERSHIP_CHURN_VALUES, dataset, "category.churn_allowed"))
    report.add(
        check_categories(
            frame, "Favorite_Exercise", MEMBERSHIP_EXERCISES, dataset, "category.favorite_exercise_allowed"
        )
    )
    report.add(
        check_whitespace_hygiene(
            frame, MEMBERSHIP_SOURCE.categorical_columns, dataset, "category.membership_string_hygiene"
        )
    )

    # --- duplicates ---
    report.add(check_duplicate_rows(frame, dataset, warn_pct=1.0, fail_pct=5.0))
    report.add(
        check_key_uniqueness(frame, "Member_ID", dataset, "duplicate.member_id_uniqueness")
    )

    # --- missingness (per-column thresholds reflect real observed levels) ---
    report.extend(
        check_missingness(
            frame,
            dataset,
            thresholds={
                "Age": {"warn": 10.0, "fail": 25.0},
                "Name": {"warn": 20.0, "fail": 40.0},
                "Join_Date": {"warn": 8.0, "fail": 25.0},
                "Avg_Calories_Burned": {"warn": 10.0, "fail": 25.0},
                "Total_Weight_Lifted_kg": {"warn": 8.0, "fail": 25.0},
                "Visits_Per_Month": {"warn": 10.0, "fail": 25.0},
            },
            default_warn_pct=2.0,
            default_fail_pct=20.0,
            check_id="missing.membership_null_rate",
        )
    )

    # --- business rules ---
    report.add(
        check_referential_columns(
            frame,
            ("Avg_Workout_Duration_Min", "Avg_Calories_Burned", "Total_Weight_Lifted_kg", "Visits_Per_Month"),
            dataset,
            "business.measures_non_negative",
        )
    )
    report.add(
        check_share_of_population(
            frame,
            "Churn",
            "Yes",
            expected_min_pct=5.0,
            expected_max_pct=60.0,
            dataset=dataset,
            check_id="business.churn_share_plausible",
            description="Churn class balance is within a plausible band",
        )
    )
    report.add(
        check_value_domain(
            frame,
            "Total_Weight_Lifted_kg",
            dataset,
            "business.weight_lifted_domain",
            "Total_Weight_Lifted_kg within a plausible lifetime range",
            min_acceptable=0.0,
            max_acceptable=1_000_000.0,
        )
    )
    report.add(
        check_value_domain(
            frame,
            "Visits_Per_Month",
            dataset,
            "business.visits_per_month_domain",
            "Visits_Per_Month within a plausible monthly range",
            min_acceptable=0.0,
            max_acceptable=31.0,
        )
    )
    return report


# ---------------------------------------------------------------------------
# Canonical (post-cleaning) validation
# ---------------------------------------------------------------------------
def validate_canonical_fact_workout(
    frame: pd.DataFrame, dataset: str = "fact_workout"
) -> ValidationReport:
    """Post-cleaning re-validation of the canonical workout fact."""
    report = ValidationReport(dataset=dataset)
    required = [
        "workout_id",
        "workout_date",
        "workout_type",
        "duration_minutes",
        "calories_burned",
        "attendance_status",
        "is_present",
        "membership_type",
        "gender",
        "age",
    ]
    report.add(check_required_columns(frame, required, dataset))
    report.add(
        check_numeric_min(frame, "duration_minutes", 0, dataset, "numeric.duration_non_negative", "duration_minutes >= 0", fail_pct=0.0)
    )
    report.add(
        check_numeric_min(frame, "calories_burned", 0, dataset, "numeric.calories_non_negative", "calories_burned >= 0", fail_pct=0.0)
    )
    report.add(
        check_numeric_between(frame, "age", 13, 100, dataset, "numeric.age_plausible", "13 <= age <= 100", fail_pct=1.0)
    )
    report.add(check_categories(frame, "workout_type", ACTIVITY_WORKOUT_TYPES, dataset, "category.workout_type_allowed"))
    report.add(
        check_categories(frame, "attendance_status", ATTENDANCE_STATES, dataset, "category.attendance_status_allowed")
    )
    report.add(
        check_categories(
            frame,
            "membership_type",
            tuple(sorted(set(ACTIVITY_MEMBERSHIP_TYPES) | set(MEMBERSHIP_TYPES))),
            dataset,
            "category.membership_type_allowed",
        )
    )
    report.add(check_key_uniqueness(frame, "workout_id", dataset, "duplicate.workout_id_unique"))
    report.add(check_duplicate_rows(frame, dataset, warn_pct=1.0, fail_pct=5.0))
    report.add(
        check_intentionally_null(
            frame,
            "member_id",
            dataset,
            "business.member_id_null_by_design",
            (
                "fact_workout.member_id is null by design: the activity source exposes no "
                "repeatable member key"
            ),
        )
    )
    report.extend(
        check_missingness(
            frame,
            dataset,
            # member_id is deliberately null, so it is excluded from the
            # missingness rule rather than reported as a data defect.
            thresholds={"member_id": {"warn": 100.0, "fail": 101.0}},
            default_warn_pct=1.0,
            default_fail_pct=10.0,
            check_id="missing.workout_null_rate",
        )
    )
    return report


def validate_canonical_membership(
    frame: pd.DataFrame, dataset: str = "fact_membership"
) -> ValidationReport:
    """Post-cleaning re-validation of the canonical membership fact."""
    report = ValidationReport(dataset=dataset)
    required = ["member_id", "churn_status", "membership_type", "visits_per_month"]
    report.add(check_required_columns(frame, required, dataset))
    report.add(check_key_uniqueness(frame, "member_id", dataset, "duplicate.member_id_unique"))
    report.add(check_duplicate_rows(frame, dataset, warn_pct=1.0, fail_pct=5.0))
    report.add(
        check_numeric_min(frame, "visits_per_month", 0, dataset, "numeric.visits_non_negative", "visits_per_month >= 0", fail_pct=0.0)
    )
    report.add(
        check_categories(frame, "membership_type", MEMBERSHIP_TYPES, dataset, "category.membership_type_allowed")
    )
    report.add(
        check_date_order(
            frame, "join_date", "last_visit_date", dataset, "date.join_lte_last_visit",
            "join_date <= last_visit_date", fail_pct=0.0,
        )
    )
    report.extend(
        check_missingness(
            frame,
            dataset,
            # join_date nulls are flagged rather than imputed, and tenure_days is
            # undefined whenever join_date is missing, so both inherit that rate.
            thresholds={
                "join_date": {"warn": 8.0, "fail": 25.0},
                "last_visit_date": {"warn": 2.0, "fail": 20.0},
                "tenure_days": {"warn": 8.0, "fail": 25.0},
            },
            default_warn_pct=2.0,
            default_fail_pct=20.0,
            check_id="missing.membership_null_rate",
        )
    )
    report.add(
        check_share_of_population(
            frame,
            "churn_status",
            True,
            expected_min_pct=5.0,
            expected_max_pct=60.0,
            dataset=dataset,
            check_id="business.churn_share_plausible",
            description="Churn class balance is within a plausible band",
        )
    )
    return report


# ---------------------------------------------------------------------------
# Convenience wrappers
# ---------------------------------------------------------------------------
def validate_loaded_sources(sources: Dict[str, LoadedSource]) -> Dict[str, ValidationReport]:
    """Validate every loaded source, returning a name-keyed report mapping."""
    reports: Dict[str, ValidationReport] = {}
    if "activity" in sources:
        reports["activity"] = validate_activity_source(sources["activity"].frame)
    if "membership" in sources:
        reports["membership"] = validate_membership_source(sources["membership"].frame)
    for name, report in reports.items():
        logger.info("%s validation -> %s", name, report.status)
    return reports


def validate_no_data(dataset: str = "missing") -> ValidationReport:
    """Explicit empty-state report so the UI can render a friendly message."""
    return ValidationReport(
        dataset=dataset,
        checks=[
            CheckResult(
                check_id="data.available",
                dataset=dataset,
                category="schema",
                description="A source dataset is available for analysis",
                status=FAIL,
                severity="critical",
                detail="Please upload a valid dataset to begin.",
            )
        ],
    )


def summarize_quality(reports: Sequence[ValidationReport]) -> Dict[str, Any]:
    """Roll several validation reports into dashboard-ready counters."""
    all_checks = [c for report in reports for c in report.checks]
    total = len(all_checks)
    passed = sum(1 for c in all_checks if c.status == PASS)
    warnings = sum(1 for c in all_checks if c.status == WARNING)
    failures = sum(1 for c in all_checks if c.status == FAIL)
    return {
        "status": worst_status(*[r.status for r in reports]) if reports else PASS,
        "total_checks": total,
        "passed": passed,
        "warnings": warnings,
        "failures": failures,
        "pass_rate": round(100.0 * passed / total, 2) if total else 0.0,
        "by_category": {
            f"{report.dataset}.{category}": status
            for report in reports
            for category, status in report.by_category().items()
        },
    }

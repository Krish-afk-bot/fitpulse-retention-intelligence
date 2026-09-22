"""Source and canonical schema contracts.

Two conceptual sources feed FitPulse, mirroring how a real fitness business
routes separate operational systems into one analytics platform:

* **Source A — Activity System**: ``Daily Gym Attendance and Workout Activity``
* **Source B — Membership System**: ``Churn Prediction Gym Members``

The column lists below were derived by *inspecting the actual downloaded
files*, not from assumptions about the PRD. Fields the PRD mentions but the
sources do not contain (for example subscription renewal events) are simply
absent and are documented as limitations in ``LIMITATIONS.md``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence


@dataclass(frozen=True)
class SourceSchema:
    """Contract describing one upstream source file."""

    name: str
    label: str
    url: str
    license: str
    filename: str
    grain: str
    description: str
    expected_columns: Sequence[str]
    required_columns: Sequence[str]
    numeric_columns: Sequence[str]
    date_columns: Sequence[str]
    categorical_columns: Sequence[str]
    #: candidate columns that *might* act as a member key
    key_candidates: Sequence[str]
    #: source column -> canonical column renames applied at canonicalisation
    column_map: Dict[str, str] = field(default_factory=dict)
    known_limitations: Sequence[str] = field(default_factory=tuple)

    def has_column(self, column: str) -> bool:
        return column in self.expected_columns


# ---------------------------------------------------------------------------
# Source A — Activity system
# ---------------------------------------------------------------------------
ACTIVITY_SOURCE = SourceSchema(
    name="activity",
    label="Daily Gym Attendance and Workout Activity Dataset",
    url="https://www.kaggle.com/datasets/zahranusratt/daily-gym-attendance-and-workout-activity-dataset",
    license="See Kaggle dataset page for the applicable license/terms.",
    filename="daily_gym_attendance_workout_data.csv",
    grain="One scheduled gym session record (no repeatable member key)",
    description=(
        "Attendance and workout records for calendar year 2024. Each row is a "
        "distinct scheduled session including workout type, nominal duration, "
        "nominal calories and an attendance outcome."
    ),
    expected_columns=(
        "member_id",
        "visit_date",
        "age",
        "gender",
        "membership_type",
        "workout_type",
        "workout_duration_minutes",
        "calories_burned",
        "check_in_time",
        "attendance_status",
    ),
    required_columns=(
        "member_id",
        "visit_date",
        "workout_type",
        "workout_duration_minutes",
        "calories_burned",
        "attendance_status",
    ),
    numeric_columns=("age", "workout_duration_minutes", "calories_burned"),
    date_columns=("visit_date",),
    categorical_columns=("gender", "membership_type", "workout_type", "attendance_status"),
    key_candidates=("member_id",),
    column_map={
        "member_id": "source_member_ref",
        "visit_date": "workout_date",
        "workout_duration_minutes": "duration_minutes",
        "calories_burned": "calories_burned",
        "check_in_time": "check_in_time",
        "attendance_status": "attendance_status",
        "workout_type": "workout_type",
        "membership_type": "membership_type",
        "gender": "gender",
        "age": "age",
    },
    known_limitations=(
        "`member_id` has 2,600 distinct values across 2,600 rows: it is a record "
        "sequence number, not a repeatable member identifier, so no per-member "
        "event history (and therefore no per-member streak metric) is derivable "
        "from this source alone.",
        "Absent rows still carry non-zero duration and calories, and their "
        "distribution matches Present rows. Duration/calories in this source are "
        "therefore nominal (scheduled) values rather than confirmed workout "
        "output. FitPulse keeps both a raw and an attendance-gated measure.",
        "No churn, membership status, join date or payment information exists in "
        "this source, so it cannot produce retention outcomes on its own.",
        "No calendar-year coverage beyond 2024 and no member-level continuity, so "
        "this source supports platform-level trend/seasonality analysis only.",
    ),
)


# ---------------------------------------------------------------------------
# Source B — Membership system
# ---------------------------------------------------------------------------
MEMBERSHIP_SOURCE = SourceSchema(
    name="membership",
    label="Churn Prediction Gym Members Dataset",
    url="https://www.kaggle.com/datasets/hassaan2580/churn-prediction-gym-members-dataset",
    license="CC0: Public Domain (per the Kaggle dataset page).",
    filename="gym_members_dataset.csv",
    grain="One row per member (member-level snapshot with real churn outcome)",
    description=(
        "Member-level snapshot containing membership tier, join date, last visit "
        "date, behavioural aggregates derived by the publisher, and a churn label."
    ),
    expected_columns=(
        "Member_ID",
        "Name",
        "Age",
        "Gender",
        "Address",
        "Phone_Number",
        "Membership_Type",
        "Join_Date",
        "Last_Visit_Date",
        "Favorite_Exercise",
        "Avg_Workout_Duration_Min",
        "Avg_Calories_Burned",
        "Total_Weight_Lifted_kg",
        "Visits_Per_Month",
        "Churn",
    ),
    required_columns=("Member_ID", "Membership_Type", "Churn"),
    numeric_columns=(
        "Age",
        "Avg_Workout_Duration_Min",
        "Avg_Calories_Burned",
        "Total_Weight_Lifted_kg",
        "Visits_Per_Month",
    ),
    date_columns=("Join_Date", "Last_Visit_Date"),
    categorical_columns=("Gender", "Membership_Type", "Favorite_Exercise", "Churn"),
    key_candidates=("Member_ID",),
    column_map={
        "Member_ID": "member_id",
        "Age": "age",
        "Gender": "gender",
        "Membership_Type": "membership_type",
        "Join_Date": "join_date",
        "Last_Visit_Date": "last_visit_date",
        "Favorite_Exercise": "favorite_exercise",
        "Avg_Workout_Duration_Min": "avg_workout_duration_min",
        "Avg_Calories_Burned": "avg_calories_burned",
        "Total_Weight_Lifted_kg": "total_weight_lifted_kg",
        "Visits_Per_Month": "visits_per_month",
        "Churn": "churn_status",
    },
    known_limitations=(
        "Contains direct personal identifiers (`Name`, `Address`, "
        "`Phone_Number`). They are dropped during cleaning and never persisted.",
        "`Last_Visit_Date` values are spread over several years and show no "
        "association with the churn label, so date-derived recency in this source "
        "behaves close to noise. This is reported rather than smoothed over.",
        "No subscription renewal event exists, so renewal-rate analysis is out of "
        "scope. Only the churn/membership-status outcome is available.",
        "`Avg_Workout_Duration_Min` and `Avg_Calories_Burned` are publisher "
        "aggregates; raw per-workout events for these members are not provided, so "
        "the activity calendar for these members is rebuilt by the documented "
        "synthetic integration layer.",
    ),
)


# ---------------------------------------------------------------------------
# Canonical model
# ---------------------------------------------------------------------------
CANONICAL_FACT_WORKOUT: Sequence[str] = (
    "workout_id",
    "member_id",
    "source_member_ref",
    "workout_date",
    "workout_year",
    "workout_month",
    "workout_week",
    "workout_weekday",
    "check_in_time",
    "workout_type",
    "duration_minutes",
    "calories_burned",
    "attendance_status",
    "is_present",
    "age",
    "age_group",
    "gender",
    "membership_type",
    "source_system",
    "is_synthetic",
    "provenance",
)

CANONICAL_DIM_MEMBER: Sequence[str] = (
    "member_id",
    "age",
    "age_group",
    "gender",
    "membership_type",
    "join_date",
    "favorite_exercise",
    "source_system",
    "is_synthetic",
    "provenance",
)

CANONICAL_FACT_MEMBERSHIP: Sequence[str] = (
    "member_id",
    "membership_type",
    "join_date",
    "last_visit_date",
    "churn_status",
    "visits_per_month",
    "avg_workout_duration_min",
    "avg_calories_burned",
    "total_weight_lifted_kg",
    "tenure_days",
    "recency_days",
    "observation_date",
    "source_system",
    "is_synthetic",
    "provenance",
)

SOURCES: Dict[str, SourceSchema] = {
    ACTIVITY_SOURCE.name: ACTIVITY_SOURCE,
    MEMBERSHIP_SOURCE.name: MEMBERSHIP_SOURCE,
}


def get_source_schema(name: str) -> SourceSchema:
    """Look up a source contract by name (``"activity"`` / ``"membership"``)."""
    try:
        return SOURCES[name]
    except KeyError as exc:  # pragma: no cover - defensive
        raise KeyError(f"Unknown source '{name}'. Known sources: {sorted(SOURCES)}") from exc


def list_sources() -> List[str]:
    return list(SOURCES)

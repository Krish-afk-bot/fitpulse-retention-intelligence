"""Canonical field registry.

FitPulse is not tied to one dataset. Any fitness/activity/membership export can
be brought in as long as its columns can be mapped onto this canonical set. The
registry is the single source of truth for that mapping:

* ``name``        — canonical field name used by the analytics layer.
* ``aliases``      — header spellings seen in real exports. Matching is
  case/space/underscore/punctuation insensitive, so ``"Member ID"``,
  ``"memberID"`` and ``"member_id"`` all resolve to the same alias.
* ``kind``         — the *shape* of a valid value. Used to sanity-check a
  candidate column: a column whose values never parse as dates is not a date,
  whatever its header says.
* ``role``         — which side of the product the field belongs to
  (``activity`` events, ``membership`` records, or ``shared`` identity).
* ``required``     — whether the canonical *source role* is unusable without it.
  Most fields are optional and simply disable the analyses that need them.
* ``contract_name``— the column name the cleaning layer works with. The
  adapter renames mapped columns onto these names so the curated model stays
  identical no matter which dataset was loaded.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

#: Roles a dataset can play.
ROLE_ACTIVITY = "activity"
ROLE_MEMBERSHIP = "membership"
ROLES: Tuple[str, ...] = (ROLE_ACTIVITY, ROLE_MEMBERSHIP)

#: Kinds of canonical field.
KIND_IDENTIFIER = "identifier"
KIND_DATE = "date"
KIND_TIME = "time"
KIND_NUMERIC = "numeric"
KIND_CATEGORICAL = "categorical"
KIND_BOOLEAN = "boolean"


@dataclass(frozen=True)
class CanonicalField:
    """One canonical field and the header spellings it accepts."""

    name: str
    label: str
    description: str
    role: str
    kind: str
    aliases: Sequence[str]
    required: bool = False
    contract_name: Optional[str] = None
    unit: str = ""
    expected_min: Optional[float] = None
    expected_max: Optional[float] = None
    allowed_values: str = ""
    business_meaning: str = ""


def _aliases(*names: str) -> Tuple[str, ...]:
    return tuple(names)


CANONICAL_FIELDS: Tuple[CanonicalField, ...] = (
    # ---------------------------------------------------------------- identity
    CanonicalField(
        name="member_id",
        label="Member ID",
        description="Identifier for the member the record belongs to.",
        role="shared",
        kind=KIND_IDENTIFIER,
        aliases=_aliases(
            "member_id", "memberid", "member", "members", "member_no", "member_number",
            "member_code", "member_key", "member_ref", "mbr_id", "cust_id", "customer_id",
            "customerid", "customer", "customer_no", "customer_number", "user_id", "userid",
            "user", "username", "client_id", "clientid", "client", "subscriber_id",
            "subscriber", "account_id", "account", "person_id", "guest_id", "id",
            "user_key", "customer_key", "memberidnumber",
        ),
        required=True,
        contract_name="Member_ID",
        business_meaning="Primary key used to count distinct members and to group records.",
    ),
    # -------------------------------------------------------------- activity
    CanonicalField(
        name="activity_date",
        label="Activity date",
        description="Date on which the session or workout took place.",
        role=ROLE_ACTIVITY,
        kind=KIND_DATE,
        aliases=_aliases(
            "activity_date", "workout_date", "session_date", "visit_date", "date",
            "activity_day", "workout_day", "workout_dt", "session_dt", "visit_dt",
            "checkin_date", "check_in_date", "checkin_day", "date_of_activity",
            "activity_dt", "training_date", "class_date", "class_day", "event_date",
            "event_day", "obstime", "timestamp", "datetime", "recorded_at",
        ),
        required=True,
        contract_name="visit_date",
        business_meaning="Drives every time-series, trend and streak calculation.",
    ),
    CanonicalField(
        name="workout_type",
        label="Workout type",
        description="Kind of session or class performed.",
        role=ROLE_ACTIVITY,
        kind=KIND_CATEGORICAL,
        aliases=_aliases(
            "workout_type", "workouttype", "activity_type", "activity", "exercise_type",
            "exercise", "class_type", "class", "workout", "workout_name", "session_type",
            "training_type", "program", "programme", "workout_class", "discipline",
            "activity_name", "session_name", "favourite_exercise", "favorite_exercise",
            "workout_category",
        ),
        contract_name="workout_type",
        business_meaning="Workout-type mix and attendance rates by discipline.",
    ),
    CanonicalField(
        name="duration_minutes",
        label="Duration",
        description="Length of the session in minutes.",
        role=ROLE_ACTIVITY,
        kind=KIND_NUMERIC,
        aliases=_aliases(
            "duration_minutes", "duration", "duration_min", "duration_mins", "workout_duration",
            "workout_duration_minutes", "workout_duration_min", "session_duration",
            "session_duration_minutes", "session_length", "workout_length", "class_duration",
            "minutes", "time_minutes", "active_minutes", "length_minutes", "duration_hrs",
            "duration_hours",
        ),
        contract_name="workout_duration_minutes",
        unit="minutes",
        expected_min=0.0,
        expected_max=600.0,
        business_meaning="Session intensity and total recorded training volume.",
    ),
    CanonicalField(
        name="calories_burned",
        label="Calories burned",
        description="Energy reported for the session.",
        role=ROLE_ACTIVITY,
        kind=KIND_NUMERIC,
        aliases=_aliases(
            "calories_burned", "calories", "calorie", "cal_burned", "cals", "kcal",
            "energy", "energy_expended", "total_calories", "calories_burned_kcal",
            "calories_kcal", "calories_burnt", "cal_burnt", "calories_out",
        ),
        contract_name="calories_burned",
        unit="kcal",
        expected_min=0.0,
        expected_max=6000.0,
        business_meaning="Secondary intensity measure used in the effort contrast.",
    ),
    CanonicalField(
        name="attendance_status",
        label="Attendance outcome",
        description="Whether the scheduled session was actually attended.",
        role=ROLE_ACTIVITY,
        kind=KIND_BOOLEAN,
        aliases=_aliases(
            "attendance_status", "attendance", "attended", "attended_flag", "attendance_flag",
            "is_present", "present", "show", "showed_up", "show_up", "checkin_status",
            "check_in_status", "session_status", "status", "attendance_outcome",
            "attended_status", "no_show", "noshow",
        ),
        contract_name="attendance_status",
        business_meaning="Attendance rate, drop-off and the attendance-gated measures.",
    ),
    CanonicalField(
        name="check_in_time",
        label="Check-in time",
        description="Time of day the member checked in.",
        role=ROLE_ACTIVITY,
        kind=KIND_TIME,
        aliases=_aliases(
            "check_in_time", "checkin_time", "check_in", "checkin", "start_time",
            "session_time", "entry_time", "arrival_time", "time", "visit_time",
            "workout_time", "class_time",
        ),
        contract_name="check_in_time",
        business_meaning="Time-of-day demand pattern.",
    ),
    # ------------------------------------------------------------ membership
    CanonicalField(
        name="churn_status",
        label="Churn outcome",
        description="Whether the member had churned at the observation date.",
        role=ROLE_MEMBERSHIP,
        kind=KIND_BOOLEAN,
        aliases=_aliases(
            "churn", "churn_status", "is_churned", "churned", "churn_flag", "churn_label",
            "attrition", "attrition_flag", "has_churned", "cancelled", "canceled",
            "cancellation", "cancel_flag", "exited", "terminated", "left", "left_gym",
            "retained", "is_retained", "retention", "retention_status", "active",
            "is_active", "active_flag", "status", "membership_status", "subscription_status",
            "contract_status", "state",
        ),
        contract_name="Churn",
        business_meaning="The real business outcome behind every retention metric.",
    ),
    CanonicalField(
        name="membership_type",
        label="Membership type",
        description="Plan or tier the member is on.",
        role=ROLE_MEMBERSHIP,
        kind=KIND_CATEGORICAL,
        aliases=_aliases(
            "membership_type", "membership", "membership_plan", "membership_level",
            "membership_category", "plan", "plan_type", "plantype", "plan_name", "tier",
            "subscription", "subscription_type", "subscription_plan", "package",
            "package_type", "product", "product_type", "contract_type", "membership_tier",
        ),
        contract_name="Membership_Type",
        business_meaning="Retention comparison across plan tiers.",
    ),
    CanonicalField(
        name="join_date",
        label="Join date",
        description="Date the membership started.",
        role=ROLE_MEMBERSHIP,
        kind=KIND_DATE,
        aliases=_aliases(
            "join_date", "joined_date", "join_dt", "date_joined", "joined", "join",
            "signup_date", "sign_up_date", "sign_up", "registration_date", "registered_on",
            "enrolment_date", "enrollment_date", "enrolled_date", "start_date",
            "membership_start", "membership_start_date", "contract_start", "contract_start_date",
            "subscription_start", "member_since", "created_date", "created_at",
        ),
        contract_name="Join_Date",
        business_meaning="Tenure and cohort-based retention analysis.",
    ),
    CanonicalField(
        name="last_visit_date",
        label="Last visit",
        description="Most recent visit recorded for the member.",
        role=ROLE_MEMBERSHIP,
        kind=KIND_DATE,
        aliases=_aliases(
            "last_visit_date", "last_visit", "lastvisit", "last_seen", "last_seen_date",
            "last_activity_date", "last_active", "last_active_date", "last_login",
            "last_login_date", "most_recent_visit", "recent_visit_date", "last_checkin",
            "last_check_in", "last_session", "last_session_date", "final_visit_date",
            "recent_activity_date",
        ),
        contract_name="Last_Visit_Date",
        business_meaning="Recency: how long since the member last trained.",
    ),
    CanonicalField(
        name="visits_per_month",
        label="Visits per month",
        description="Recorded monthly visit rate for the member.",
        role=ROLE_MEMBERSHIP,
        kind=KIND_NUMERIC,
        aliases=_aliases(
            "visits_per_month", "visits_per_mth", "visit_per_month", "monthly_visits",
            "monthly_visit_rate", "avg_visits_per_month", "average_visits_per_month",
            "avg_monthly_visits", "visits_month", "visit_frequency", "frequency",
            "workouts_per_month", "sessions_per_month", "avg_visits", "visits",
            "attendance_frequency", "activity_frequency", "num_visits_per_month",
        ),
        contract_name="Visits_Per_Month",
        unit="visits/month",
        expected_min=0.0,
        expected_max=80.0,
        business_meaning="The dominant real engagement signal in the reference data.",
    ),
    CanonicalField(
        name="avg_workout_duration_min",
        label="Average duration",
        description="Mean session duration recorded for the member.",
        role=ROLE_MEMBERSHIP,
        kind=KIND_NUMERIC,
        aliases=_aliases(
            "avg_workout_duration_min", "avg_workout_duration_minutes", "average_workout_duration",
            "average_workout_duration_minutes", "avg_duration", "average_duration",
            "avg_session_duration", "avg_session_duration_minutes", "mean_duration",
            "avg_duration_minutes", "avg_workout_duration", "average_session_length",
        ),
        contract_name="Avg_Workout_Duration_Min",
        unit="minutes",
        expected_min=0.0,
        expected_max=600.0,
        business_meaning="Member-level effort, used as an engagement-score component.",
    ),
    CanonicalField(
        name="avg_calories_burned",
        label="Average calories",
        description="Mean calories burned per session for the member.",
        role=ROLE_MEMBERSHIP,
        kind=KIND_NUMERIC,
        aliases=_aliases(
            "avg_calories_burned", "average_calories_burned", "avg_calories", "average_calories",
            "mean_calories", "avg_calorie_burn", "calories_avg", "avg_kcal", "average_kcal",
        ),
        contract_name="Avg_Calories_Burned",
        unit="kcal",
        expected_min=0.0,
        expected_max=6000.0,
        business_meaning="Secondary effort measure in the member profile.",
    ),
    CanonicalField(
        name="total_weight_lifted_kg",
        label="Total weight lifted",
        description="Cumulative weight lifted by the member.",
        role=ROLE_MEMBERSHIP,
        kind=KIND_NUMERIC,
        aliases=_aliases(
            "total_weight_lifted_kg", "total_weight_lifted", "weight_lifted_kg", "weight_lifted",
            "total_weight", "total_kg_lifted", "total_load", "volume_kg", "tonnage",
        ),
        contract_name="Total_Weight_Lifted_kg",
        unit="kg",
        expected_min=0.0,
        expected_max=10_000_000.0,
        business_meaning="Strength-training volume where the source records it.",
    ),
    CanonicalField(
        name="favorite_exercise",
        label="Favourite exercise",
        description="Preferred exercise recorded for the member.",
        role=ROLE_MEMBERSHIP,
        kind=KIND_CATEGORICAL,
        aliases=_aliases(
            "favorite_exercise", "favourite_exercise", "favorite_workout", "favourite_workout",
            "preferred_exercise", "preferred_workout", "favourite_activity", "favorite_activity",
            "preferred_class", "favourite_class",
        ),
        contract_name="Favorite_Exercise",
        business_meaning="Preference split by member outcome.",
    ),
    CanonicalField(
        name="age",
        label="Age",
        description="Member age in years.",
        role="shared",
        kind=KIND_NUMERIC,
        aliases=_aliases(
            "age", "member_age", "customer_age", "age_years", "age_value", "age_band_years",
            "years_old", "user_age",
        ),
        contract_name="Age",
        unit="years",
        expected_min=10.0,
        expected_max=110.0,
        business_meaning="Age banding for demographic segmentation.",
    ),
    CanonicalField(
        name="gender",
        label="Gender",
        description="Member gender as recorded by the source.",
        role="shared",
        kind=KIND_CATEGORICAL,
        aliases=_aliases(
            "gender", "sex", "member_gender", "customer_gender", "user_gender", "gender_identity",
        ),
        contract_name="Gender",
        business_meaning="Demographic segmentation.",
    ),
)

FIELDS_BY_NAME: Dict[str, CanonicalField] = {field.name: field for field in CANONICAL_FIELDS}


def fields_for_role(role: str) -> List[CanonicalField]:
    """Canonical fields that a dataset in ``role`` can provide.

    ``shared`` fields (identity, demographics) are valid in either role.
    """
    if role not in ROLES:
        raise ValueError(f"Unknown role '{role}'. Expected one of {ROLES}.")
    return [f for f in CANONICAL_FIELDS if f.role in (role, "shared")]


def required_fields_for_role(role: str) -> List[CanonicalField]:
    return [f for f in fields_for_role(role) if f.required]


def get_field(name: str) -> CanonicalField:
    try:
        return FIELDS_BY_NAME[name]
    except KeyError as exc:  # pragma: no cover - defensive
        raise KeyError(f"Unknown canonical field '{name}'.") from exc


def alias_index() -> Dict[str, List[CanonicalField]]:
    """Map normalized alias -> the fields that claim it (for conflict reporting)."""
    from .mapping import normalize_key  # local import avoids a cycle

    index: Dict[str, List[CanonicalField]] = {}
    for field in CANONICAL_FIELDS:
        for alias in field.aliases:
            index.setdefault(normalize_key(alias), []).append(field)
    return index


#: Some canonical fields are spelled differently on each side of the product:
#: the activity contract uses lowercase headers, the membership contract uses the
#: publisher's capitalised headers. The adapter honours this so a mapped dataset
#: is indistinguishable from a reference dataset by the time cleaning runs.
def contract_names_map() -> Dict[str, Dict[str, str]]:
    """Contract column names for every role (used by the data dictionary)."""
    return {role: contract_names(role) for role in ROLES}


ROLE_CONTRACT_OVERRIDES: Dict[str, Dict[str, str]] = {
    "activity": {
        "member_id": "member_id",
        "age": "age",
        "gender": "gender",
        "membership_type": "membership_type",
    },
    "membership": {
        "member_id": "Member_ID",
        "age": "Age",
        "gender": "Gender",
        "membership_type": "Membership_Type",
        "churn_status": "Churn",
    },
}


def field_options_for_role(role: str) -> List[Dict[str, object]]:
    """Field metadata for the manual mapping UI (required fields first)."""
    ordered = sorted(
        fields_for_role(role),
        key=lambda field: (not field.required, field.name),
    )
    return [
        {
            "name": field.name,
            "label": field.label,
            "required": field.required,
            "kind": field.kind,
            "description": field.description,
            "business_meaning": field.business_meaning,
            "unit": field.unit,
            "allowed_values": field.allowed_values,
            "aliases": list(field.aliases),
        }
        for field in ordered
    ]


def contract_names(role: str) -> Dict[str, str]:
    """Canonical -> contract column name for one role.

    The adapter uses this to hand a mapped dataset to the cleaning layer under
    the names it already understands.
    """
    overrides = ROLE_CONTRACT_OVERRIDES.get(role, {})
    names: Dict[str, str] = {}
    for field in fields_for_role(role):
        if field.contract_name:
            names[field.name] = overrides.get(field.name, field.contract_name)
    return names

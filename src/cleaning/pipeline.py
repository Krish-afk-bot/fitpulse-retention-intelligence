"""Source-specific cleaning pipelines.

Turns each raw source into a canonical model while recording a measurable audit
trail. Three integrity decisions are enforced here:

1. **Activity records get a row identifier, not a member identifier.**
   ``member_id`` is only populated when the source genuinely repeats an
   identifier across rows (a real member key). When the identifier is unique per
   row — as in the reference activity dataset — ``member_id`` stays null and the
   original value is preserved as ``source_member_ref``.

2. **Membership identifiers are namespaced** as ``M-####`` so that a raw integer
   can never be silently joined against an unrelated source's integer identifier.

3. **Optional fields may be absent.** Any source column the dataset does not
   provide yields an all-null canonical column rather than a crash or an invented
   value, and the absence is recorded in the audit trail and in the capability
   report.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from ..common.config import get_settings
from ..common.logging_utils import get_logger
from ..ingestion.loader import LoadedSource, map_to_canonical
from ..ingestion.schema import ACTIVITY_SOURCE, MEMBERSHIP_SOURCE
from .cleaners import (
    CleaningResult,
    add_age_group,
    age_group,
    add_missing_flags,
    clean_null_strings,
    drop_exact_duplicates,
    drop_pii,
    impute_numeric_median,
    normalize_boolean,
    normalize_category,
    outlier_summary,
    parse_time_of_day,
    strip_whitespace,
    to_datetime_safe,
    to_numeric_safe,
)

logger = get_logger("cleaning")

# --- canonical spellings ---------------------------------------------------
MEMBERSHIP_TYPE_MAP = {
    "monthly": "Monthly",
    "quarterly": "Quarterly",
    "annual": "Annual",
    "yearly": "Yearly",
    "annual plan": "Annual",
}
GENDER_MAP = {"male": "Male", "female": "Female", "other": "Other", "m": "Male", "f": "Female"}
WORKOUT_TYPE_MAP = {
    "strength training": "Strength Training",
    "cardio": "Cardio",
    "hiit": "HIIT",
    "crossfit": "CrossFit",
    "yoga": "Yoga",
}
ATTENDANCE_MAP = {"present": "Present", "absent": "Absent", "no": "Absent", "yes": "Present"}
EXERCISE_MAP = {
    "deadlift": "Deadlift",
    "pull-ups": "Pull-ups",
    "pull ups": "Pull-ups",
    "squats": "Squats",
    "bench press": "Bench Press",
    "treadmill": "Treadmill",
    "cycling": "Cycling",
}

ACTIVITY_NUMERIC_DOMAIN = {
    "duration_minutes": (1.0, 300.0),
    "calories_burned": (0.0, 3000.0),
    "age": (13.0, 100.0),
}
MEMBERSHIP_NUMERIC_DOMAIN = {
    "visits_per_month": (0.0, 31.0),
    "avg_workout_duration_min": (1.0, 300.0),
    "avg_calories_burned": (0.0, 3000.0),
    "total_weight_lifted_kg": (0.0, 1_000_000.0),
    "age": (13.0, 100.0),
}


# ---------------------------------------------------------------------------
# Optional-field helpers
# ---------------------------------------------------------------------------
def _series(frame: pd.DataFrame, column: str, dtype: str = "object") -> pd.Series:
    """Return a column, or an all-null series when the dataset lacks it."""
    if column in frame.columns:
        return frame[column]
    return pd.Series(pd.NA, index=frame.index, dtype=dtype)


def _missing_fields(frame: pd.DataFrame, wanted: List[str]) -> List[str]:
    return [column for column in wanted if column not in frame.columns]


def _key_prefix(role: str) -> Tuple[str, int]:
    return ("A-", 5) if role == ACTIVITY_SOURCE.name else ("M-", 4)


def _stringify_ids(values: pd.Series, prefix: str, width: int) -> List[str]:
    """Turn any identifier (numeric or textual) into a stable namespaced key.

    Numeric identifiers keep the reference layout (``M-0001``); anything else is
    slugged so unusual source keys (``C00042``, ``abc-12``) still produce a
    readable, collision-resistant identifier.
    """
    out: List[str] = []
    for value in values.tolist():
        if value is None or (isinstance(value, float) and np.isnan(value)) or pd.isna(value):
            out.append(f"{prefix}unknown")
            continue
        text = str(value).strip()
        if not text:
            out.append(f"{prefix}unknown")
            continue
        numeric = pd.to_numeric(pd.Series([text]), errors="coerce").iloc[0]
        if pd.notna(numeric) and float(numeric).is_integer():
            out.append(f"{prefix}{int(numeric):0{width}d}")
        else:
            slug = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").upper() or "UNKNOWN"
            out.append(f"{prefix}{slug}")
    return out


def _aligned(frame: pd.DataFrame, values: Any, dtype: str = "object") -> pd.Series:
    """Coerce a mapped value (Series, scalar or None) to a frame-aligned series."""
    if isinstance(values, pd.Series):
        return values
    return pd.Series(values, index=frame.index, dtype=dtype)


# ---------------------------------------------------------------------------
# Activity source
# ---------------------------------------------------------------------------
def clean_activity_source(source: LoadedSource) -> CleaningResult:
    """Clean the activity source into the canonical ``fact_workout`` model."""
    frame = source.frame.copy()
    result = CleaningResult(name="activity", frame=frame, rows_in=len(frame))

    # 1. placeholder strings -> null
    frame, changed = clean_null_strings(frame, list(frame.columns))
    result.add("placeholder_to_null", len(frame), len(frame), changed, list(frame.columns))

    # 2. whitespace + category normalisation
    frame, changed = strip_whitespace(
        frame, ["gender", "membership_type", "workout_type", "attendance_status"]
    )
    result.add("strip_whitespace", len(frame), len(frame), changed)

    for column, mapping in (
        ("gender", GENDER_MAP),
        ("membership_type", MEMBERSHIP_TYPE_MAP),
        ("workout_type", WORKOUT_TYPE_MAP),
        ("attendance_status", ATTENDANCE_MAP),
    ):
        frame, changed = normalize_category(frame, column, mapping)
        result.add(f"normalize_category[{column}]", len(frame), len(frame), changed, [column])

    # 3. type conversion (each step skips columns the dataset does not provide)
    before = len(frame)
    frame, failures = to_datetime_safe(frame, ["visit_date"])
    result.add(
        "parse_date[visit_date]",
        before,
        len(frame),
        0,
        ["visit_date"],
        note=f"unparseable dates: {failures.get('visit_date', 0)}",
    )

    # A record whose date cannot be parsed is not a usable observation: it can be
    # placed in no trend, cohort, weekday or streak. Removing it here (and
    # reporting the count) keeps the headline session total equal to the sum of the
    # time series, which would otherwise silently disagree.
    if "visit_date" in frame.columns:
        parsed_dates = pd.to_datetime(frame["visit_date"], errors="coerce")
        unparseable_dates = int(parsed_dates.isna().sum())
        if unparseable_dates:
            parsed_before = len(frame)
            frame = frame.loc[parsed_dates.notna()].copy()
            result.add(
                "drop_unparseable_workout_date",
                parsed_before,
                len(frame),
                unparseable_dates,
                ["visit_date"],
                note=(
                    f"{unparseable_dates} record(s) dropped: the activity date could not be "
                    "parsed, so the session cannot be placed in time"
                ),
            )
    frame, time_failures = parse_time_of_day(frame, "check_in_time")
    result.add(
        "parse_time[check_in_time]",
        len(frame),
        len(frame),
        0,
        ["check_in_time"],
        note=f"unparseable times: {time_failures}",
    )
    frame, numeric_failures = to_numeric_safe(
        frame, ["age", "workout_duration_minutes", "calories_burned"]
    )
    result.add("cast_numeric", len(frame), len(frame), numeric_failures)

    # 4. canonical projection ------------------------------------------------
    canonical = map_to_canonical(frame, ACTIVITY_SOURCE)
    workout_date = pd.to_datetime(_aligned(frame, canonical.get("workout_date")), errors="coerce")
    duration = pd.to_numeric(_aligned(frame, canonical.get("duration_minutes")), errors="coerce")
    calories = pd.to_numeric(_aligned(frame, canonical.get("calories_burned")), errors="coerce")
    source_ref = _aligned(frame, canonical.get("source_member_ref"))

    repeatable = bool(getattr(source, "member_key_repeatable", False))
    missing = _missing_fields(
        frame,
        ["gender", "membership_type", "workout_type", "attendance_status", "check_in_time", "age"],
    )

    out = pd.DataFrame(index=frame.index)
    out["source_member_ref"] = source_ref
    out["workout_date"] = workout_date
    out["workout_type"] = _aligned(frame, canonical.get("workout_type"))
    out["duration_minutes"] = duration
    out["calories_burned"] = calories
    out["attendance_status"] = _aligned(frame, canonical.get("attendance_status"))
    out["check_in_time"] = _series(frame, "check_in_time")
    out["check_in_hour"] = _series(frame, "check_in_hour")
    out["age"] = _aligned(frame, canonical.get("age"))
    out["gender"] = _aligned(frame, canonical.get("gender"))
    out["membership_type"] = _aligned(frame, canonical.get("membership_type"))

    # 5. derived columns -----------------------------------------------------
    if out["source_member_ref"].isna().all():
        out["source_member_ref"] = [str(i + 1) for i in range(len(out))]
    out["workout_id"] = _stringify_ids(out["source_member_ref"], "ACT-", 5)
    if repeatable:
        # A genuine repeatable key: preserve it so per-member activity is possible.
        out["member_id"] = _stringify_ids(out["source_member_ref"], *_key_prefix("activity"))
    else:
        # Deliberate: a per-row sequence is not a member identity.
        out["member_id"] = pd.NA
    out["is_present"] = out["attendance_status"].eq("Present")
    out["workout_year"] = workout_date.dt.year
    out["workout_month"] = workout_date.dt.to_period("M").astype("string")
    out["workout_month_num"] = workout_date.dt.month
    out["workout_week"] = workout_date.dt.isocalendar().week.astype("Int64")
    out["workout_weekday"] = workout_date.dt.day_name()
    out["workout_weekday_num"] = workout_date.dt.dayofweek
    out["confirmed_duration_minutes"] = np.where(out["is_present"], duration, 0.0)
    out["confirmed_calories_burned"] = np.where(out["is_present"], calories, 0.0)
    out = add_age_group(out, "age")
    out["source_system"] = ACTIVITY_SOURCE.name
    out["is_synthetic"] = False
    out["provenance"] = (
        "source:activity (nominal duration/calories; member-level identity attributed)"
        if repeatable
        else "source:activity (nominal duration/calories; member_id unavailable)"
    )

    # 6. duplicates
    before = len(out)
    out, removed = drop_exact_duplicates(out, subset=["workout_id"])
    result.add("drop_duplicate_workout_id", before, len(out), removed, ["workout_id"])

    # 7. outliers (classified, not removed)
    result.notes.append(
        "Outlier classification (no values removed): "
        + str(outlier_summary(out, list(ACTIVITY_NUMERIC_DOMAIN), ACTIVITY_NUMERIC_DOMAIN))
    )

    order = [
        "workout_id",
        "member_id",
        "source_member_ref",
        "workout_date",
        "workout_year",
        "workout_month",
        "workout_month_num",
        "workout_week",
        "workout_weekday",
        "workout_weekday_num",
        "check_in_time",
        "check_in_hour",
        "workout_type",
        "duration_minutes",
        "confirmed_duration_minutes",
        "calories_burned",
        "confirmed_calories_burned",
        "attendance_status",
        "is_present",
        "age",
        "age_group",
        "gender",
        "membership_type",
        "source_system",
        "is_synthetic",
        "provenance",
    ]
    result.frame = out[order].reset_index(drop=True)

    if repeatable:
        result.notes.append(
            "The activity source repeats a member identifier, so records are attributed to members "
            "and per-member activity features can be computed from real events."
        )
    else:
        result.notes.append(
            "member_id is intentionally NULL: the activity identifier is unique per row, so it is a "
            "record sequence rather than a member key."
        )
    if missing:
        result.notes.append(
            f"Fields absent from the activity dataset (left null, not imputed): {missing}"
        )
    for assumption in getattr(source, "assumptions", []) or []:
        result.notes.append(f"Documented assumption: {assumption}")
    logger.info("Activity cleaned: %s rows", f"{result.rows_out:,}")
    return result


# ---------------------------------------------------------------------------
# Membership source
# ---------------------------------------------------------------------------
def clean_membership_source(
    source: LoadedSource, observation_date: Optional[pd.Timestamp] = None
) -> Dict[str, CleaningResult]:
    """Clean the membership source into ``dim_member`` + ``fact_membership``."""
    frame = source.frame.copy()
    result = CleaningResult(name="membership", frame=frame, rows_in=len(frame))

    # 1. placeholders
    frame, changed = clean_null_strings(frame, list(frame.columns))
    result.add("placeholder_to_null", len(frame), len(frame), changed)

    # 2. drop PII early (never persisted)
    frame, dropped = drop_pii(frame)
    result.add(
        "drop_pii", len(frame), len(frame), 0, dropped,
        note=f"Dropped personal identifiers: {dropped}",
    )
    result.notes.append(
        "Direct identifiers (Name, Address, Phone_Number) are removed during cleaning "
        "and are never written to the curated layer or the SQL database."
    )

    # 3. whitespace + categories
    frame, changed = strip_whitespace(
        frame, ["Gender", "Membership_Type", "Favorite_Exercise", "Churn"]
    )
    result.add("strip_whitespace", len(frame), len(frame), changed)

    for column, mapping in (
        ("Gender", GENDER_MAP),
        ("Membership_Type", MEMBERSHIP_TYPE_MAP),
        ("Favorite_Exercise", EXERCISE_MAP),
    ):
        frame, changed = normalize_category(frame, column, mapping)
        result.add(f"normalize_category[{column}]", len(frame), len(frame), changed, [column])

    # 4. types
    frame, failures = to_datetime_safe(frame, ["Join_Date", "Last_Visit_Date"])
    result.add(
        "parse_dates",
        len(frame),
        len(frame),
        0,
        ["Join_Date", "Last_Visit_Date"],
        note=f"unparseable: {failures}",
    )
    frame, numeric_failures = to_numeric_safe(
        frame, ["Age", "Avg_Workout_Duration_Min", "Avg_Calories_Burned", "Total_Weight_Lifted_kg", "Visits_Per_Month"],
    )
    result.add("cast_numeric", len(frame), len(frame), numeric_failures)

    # 5. missing-value strategy (semantic, not blanket) ----------------------
    frame, added = add_missing_flags(frame, ["Join_Date", "Age"])
    result.add(
        "flag_missing_join_date_age",
        len(frame),
        len(frame),
        added,
        ["Join_Date_missing", "Age_missing"],
        note="Nulls are flagged, not fabricated: tenure metrics skip rows without Join_Date.",
    )
    frame, imputed = impute_numeric_median(
        frame, ["Age", "Avg_Calories_Burned", "Total_Weight_Lifted_kg", "Visits_Per_Month"]
    )
    result.add(
        "median_impute_numeric",
        len(frame),
        len(frame),
        sum(imputed.values()),
        list(imputed),
        note=f"Median-imputed counts (flag columns added): {imputed}",
    )
    result.notes.append(
        "Median imputation is applied to numeric member measures. Every imputed value "
        "carries an explicit `<column>_imputed` flag so KPIs can be recomputed on "
        "complete cases only; the imputed share is reported in the Data Quality page."
    )

    # 6. duplicates
    before = len(frame)
    subset = ["Member_ID"] if "Member_ID" in frame.columns else None
    frame, removed = drop_exact_duplicates(frame, subset=subset)
    result.add(
        "drop_duplicate_member_id" if subset else "drop_exact_duplicates",
        before,
        len(frame),
        removed,
        subset or [],
    )

    # 7. outliers
    result.notes.append(
        "Outlier classification (no values removed): "
        + str(outlier_summary(frame, list(MEMBERSHIP_NUMERIC_DOMAIN), MEMBERSHIP_NUMERIC_DOMAIN))
    )

    # 8. canonical outputs ---------------------------------------------------
    settings = get_settings()
    last_visit = pd.to_datetime(_series(frame, "Last_Visit_Date"), errors="coerce")
    join_date = pd.to_datetime(_series(frame, "Join_Date"), errors="coerce")
    if observation_date is None:
        configured = settings.as_of_date
        observation_date = pd.Timestamp(configured) if configured else (
            last_visit.max() if last_visit.notna().any() else None
        )
    observation_date = pd.Timestamp(observation_date) if observation_date is not None else pd.Timestamp("2025-12-31")

    member_ids = _stringify_ids(_series(frame, "Member_ID"), *_key_prefix("membership"))
    churn_raw = _series(frame, "Churn")
    churn_status = normalize_boolean(churn_raw, true_values=("yes", "true", "1", "y"))
    churn_available = bool(churn_raw.notna().any())

    missing = _missing_fields(
        frame,
        [
            "Age", "Gender", "Membership_Type", "Join_Date", "Last_Visit_Date",
            "Favorite_Exercise", "Avg_Workout_Duration_Min", "Avg_Calories_Burned",
            "Total_Weight_Lifted_kg", "Visits_Per_Month",
        ],
    )

    dim_member = pd.DataFrame(
        {
            "member_id": member_ids,
            "age": _series(frame, "Age"),
            "gender": _series(frame, "Gender"),
            "membership_type": _series(frame, "Membership_Type"),
            "join_date": join_date,
            "favorite_exercise": _series(frame, "Favorite_Exercise"),
            "age_group": _series(frame, "Age").map(age_group),
            "source_system": MEMBERSHIP_SOURCE.name,
            "is_synthetic": False,
            "provenance": "source:membership",
        }
    )

    fact_membership = pd.DataFrame(
        {
            "member_id": member_ids,
            "membership_type": _series(frame, "Membership_Type"),
            "join_date": join_date,
            "last_visit_date": last_visit,
            "churn_status": churn_status.astype("boolean"),
            "visits_per_month": pd.to_numeric(_series(frame, "Visits_Per_Month"), errors="coerce"),
            "visits_per_month_imputed": _series(frame, "Visits_Per_Month_imputed", dtype="boolean"),
            "avg_workout_duration_min": pd.to_numeric(
                _series(frame, "Avg_Workout_Duration_Min"), errors="coerce"
            ),
            "avg_calories_burned": pd.to_numeric(_series(frame, "Avg_Calories_Burned"), errors="coerce"),
            "avg_calories_burned_imputed": _series(frame, "Avg_Calories_Burned_imputed", dtype="boolean"),
            "total_weight_lifted_kg": pd.to_numeric(
                _series(frame, "Total_Weight_Lifted_kg"), errors="coerce"
            ),
            "total_weight_lifted_kg_imputed": _series(
                frame, "Total_Weight_Lifted_kg_imputed", dtype="boolean"
            ),
            "age_imputed": _series(frame, "Age_imputed", dtype="boolean"),
            "join_date_missing": _series(frame, "Join_Date_missing", dtype="boolean"),
            "source_system": MEMBERSHIP_SOURCE.name,
            "is_synthetic": False,
            "provenance": "source:membership",
        }
    )

    fact_membership["tenure_days"] = (observation_date - fact_membership["join_date"]).dt.days
    fact_membership["recency_days"] = (observation_date - fact_membership["last_visit_date"]).dt.days
    fact_membership["observation_date"] = observation_date
    # Negative tenure would mean a join date in the future — surfaced, not hidden.
    fact_membership["tenure_days_negative"] = fact_membership["tenure_days"] < 0
    result.notes.append(
        f"Observation date = {observation_date.date()} (latest Last_Visit_Date, "
        "overridable via FITPULSE_AS_OF_DATE). tenure_days = observation - join_date; "
        "recency_days = observation - last_visit_date."
    )
    if not churn_available:
        result.notes.append(
            "No churn/retention outcome was present in this dataset. churn_status is null and every "
            "retention, churn and segmentation output is reported as unavailable rather than invented."
        )
    if missing:
        result.notes.append(f"Fields absent from the membership dataset (left null, not imputed): {missing}")
    for assumption in getattr(source, "assumptions", []) or []:
        result.notes.append(f"Documented assumption: {assumption}")

    member_result = CleaningResult(
        name="dim_member", frame=dim_member.reset_index(drop=True), rows_in=len(dim_member)
    )
    member_result.steps = list(result.steps)
    member_result.notes = list(result.notes)

    membership_result = CleaningResult(
        name="fact_membership",
        frame=fact_membership.reset_index(drop=True),
        rows_in=len(fact_membership),
    )
    membership_result.steps = list(result.steps)
    membership_result.notes = list(result.notes)

    logger.info(
        "Membership cleaned: %s members | churn=%s | observation_date=%s",
        f"{len(dim_member):,}",
        int(churn_status.fillna(False).sum()),
        observation_date.date(),
    )
    return {"dim_member": member_result, "fact_membership": membership_result}


def observation_date_from(
    loaded_membership: Optional[LoadedSource] = None,
    fallback: Optional[pd.Timestamp] = None,
) -> pd.Timestamp:
    """Resolve the analysis observation date consistently across the pipeline."""
    settings = get_settings()
    if settings.as_of_date:
        return pd.Timestamp(settings.as_of_date)
    if loaded_membership is not None:
        for column in ("Last_Visit_Date", "last_visit_date", "Join_Date", "join_date"):
            if column in loaded_membership.frame.columns:
                parsed = pd.to_datetime(loaded_membership.frame[column], errors="coerce")
                if parsed.notna().any():
                    return pd.Timestamp(parsed.max())
    return fallback or pd.Timestamp("2025-12-31")

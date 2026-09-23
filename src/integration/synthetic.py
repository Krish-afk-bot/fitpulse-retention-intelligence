"""The documented synthetic integration layer.

Why this exists
---------------
The two published sources share no legitimate entity key (see
:mod:`src.integration.keys`). The PRD therefore requires a *documented*
educational bridge rather than a fake join.

What is real and what is synthetic
----------------------------------
For every member in the membership source, the following values are **copied
exactly** from the real source record:

``avg_workout_duration_min``, ``avg_calories_burned``, ``visits_per_month``,
``membership_type``, ``gender``, ``age``, ``join_date``, ``last_visit_date``,
``favorite_exercise`` and the ``churn_status`` outcome.

Only two things are synthesised:

1. **Event date placement** — the individual calendar dates on which that
   member's recorded visits happened, distributed inside the member's real
   ``[join_date, last_visit_date]`` window.
2. **Per-event workout type** — derived deterministically from the member's
   real ``favorite_exercise``.

Because event counts come from the real ``visits_per_month`` and per-event
measures are the real member averages, the synthetic layer **reproduces the
real member-level aggregates exactly**. That property is asserted by
:func:`validate_synthetic_layer`, so the bridge is verifiable rather than
merely asserted.

Consequently every member-level streak/consistency feature is *date-placement
dependent* and is flagged ``is_synthetic_features = True`` throughout the
product. Findings that use them are labelled accordingly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from ..common.logging_utils import get_logger

logger = get_logger("integration.synthetic")

#: Documented mapping from a member's real favourite exercise to the workout
#: type likely recorded for their sessions.
EXERCISE_TO_WORKOUT_TYPE: Dict[str, str] = {
    "Deadlift": "Strength Training",
    "Bench Press": "Strength Training",
    "Squats": "Strength Training",
    "Pull-ups": "Strength Training",
    "Treadmill": "Cardio",
    "Cycling": "Cardio",
}

DEFAULT_WORKOUT_TYPE = "Strength Training"
DAYS_PER_MONTH = 30.4375

SYNTHETIC_COMPONENTS = "event_date;workout_type"
SYNTHETIC_METHOD = (
    "Deterministic calendar reconstruction: one event per recorded visit per month "
    "(real Visits_Per_Month x window length), placed on distinct dates inside the "
    "member's real [Join_Date, Last_Visit_Date] window with the final event pinned to "
    "the real Last_Visit_Date; per-event duration/calories equal the member's real "
    "published averages."
)


@dataclass
class SyntheticLayer:
    """The generated event calendar plus its provenance metadata."""

    events: pd.DataFrame
    metadata: Dict[str, Any] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)

    @property
    def rows(self) -> int:
        return int(self.events.shape[0])

    @property
    def members(self) -> int:
        if self.events.empty:
            return 0
        return int(self.events["member_id"].nunique())


def _resolve_window(
    row: pd.Series,
) -> Tuple[Optional[pd.Timestamp], Optional[pd.Timestamp]]:
    """Real observation window for one member, with documented fallbacks.

    Returns ``(None, None)`` when the source records no usable end date. The
    window is the one piece of the bridge that cannot be assumed: without it there
    is no defensible span to place events in, so the member is skipped and
    reported rather than given an invented timeline.
    """
    raw_end = row.get("last_visit_date")
    if raw_end is None or pd.isna(raw_end):
        return None, None
    end = pd.Timestamp(raw_end)
    join = row.get("join_date")
    if join is None or pd.isna(join):
        start = end - pd.Timedelta(days=365)
    else:
        start = pd.Timestamp(join)
    if pd.isna(start):
        start = end - pd.Timedelta(days=365)
    if start >= end:
        # A degenerate window (join on/after last visit) is widened to 30 days so
        # the member still has a defensible observation period. Reported, not hidden.
        start = end - pd.Timedelta(days=30)
    return start, end


def _expected_event_count(
    visits_per_month: float, window_days: int, scale: float = 1.0
) -> int:
    """Number of recorded visits implied by the real monthly visit rate."""
    if visits_per_month is None or np.isnan(visits_per_month):
        return 0
    months = max(window_days / DAYS_PER_MONTH, 1.0 / DAYS_PER_MONTH)
    raw = float(visits_per_month) * months * scale
    return int(np.clip(round(raw), 0, window_days))


def synthesize_activity_calendar(
    members: pd.DataFrame,
    seed: int = 42,
    event_scale: float = 1.0,
    member_id_col: str = "member_id",
) -> SyntheticLayer:
    """Generate the documented synthetic event calendar.

    Parameters
    ----------
    members:
        Member-level frame containing ``member_id``, ``join_date``,
        ``last_visit_date``, ``visits_per_month``,
        ``avg_workout_duration_min``, ``avg_calories_burned``,
        ``favorite_exercise`` and the descriptive attributes.
    seed:
        Seed for the deterministic date placement. The same seed always
        produces the same calendar, so results are reproducible.
    event_scale:
        Optional sensitivity knob (``1.0`` = use the real monthly visit rate
        as published). Exposed so the effect of date density can be tested.
    """
    required = {
        "member_id",
        "join_date",
        "last_visit_date",
        "visits_per_month",
        "avg_workout_duration_min",
        "avg_calories_burned",
        "favorite_exercise",
    }
    missing = required - set(members.columns)
    if missing:
        raise ValueError(f"synthesize_activity_calendar requires columns: {sorted(missing)}")

    records: List[Dict[str, Any]] = []
    members_without_events: List[str] = []
    members_without_window: List[str] = []
    widened_windows = 0
    total_expected = 0

    for position, (_, row) in enumerate(members.iterrows()):
        start, end = _resolve_window(row)
        if start is None or end is None:
            # No real date information to anchor a timeline: skip, never invent one.
            members_without_window.append(str(row[member_id_col]))
            continue
        effective_start = start
        if pd.notna(row.get("join_date")) and pd.notna(row.get("last_visit_date")) and pd.Timestamp(row["join_date"]) >= pd.Timestamp(row["last_visit_date"]):
            widened_windows += 1
        window_days = int((end - effective_start).days) + 1
        expected = _expected_event_count(row["visits_per_month"], window_days, event_scale)
        total_expected += expected
        if expected <= 0:
            members_without_events.append(str(row[member_id_col]))
            continue

        rng = np.random.default_rng(seed + position)
        if expected >= window_days:
            offsets = np.arange(window_days)
        else:
            offsets = np.sort(rng.choice(window_days, size=expected, replace=False))

        # Pin the final event to the real Last_Visit_Date so recency derived from
        # the synthetic layer agrees with the real source by construction.
        last_offset = window_days - 1
        if offsets[-1] != last_offset:
            offsets[-1] = last_offset
            offsets = np.unique(offsets)

        workout_type = EXERCISE_TO_WORKOUT_TYPE.get(
            str(row.get("favorite_exercise")), DEFAULT_WORKOUT_TYPE
        )

        for index, offset in enumerate(offsets):
            event_date = effective_start + pd.Timedelta(days=int(offset))
            records.append(
                {
                    "member_id": row[member_id_col],
                    "workout_id": f"SYN-{row[member_id_col]}-{index + 1:04d}",
                    "workout_date": event_date,
                    "workout_type": workout_type,
                    "duration_minutes": float(row["avg_workout_duration_min"]),
                    "calories_burned": float(row["avg_calories_burned"]),
                    "attendance_status": "Present",
                    "is_present": True,
                    "age": row.get("age"),
                    "gender": row.get("gender"),
                    "membership_type": row.get("membership_type"),
                    "favorite_exercise": row.get("favorite_exercise"),
                    "source_system": "synthetic_bridge",
                    "is_synthetic": True,
                    "synthetic_components": SYNTHETIC_COMPONENTS,
                    "provenance": "synthetic:calendar_from_real_member_aggregates",
                }
            )

    events = pd.DataFrame.from_records(records)
    if not events.empty:
        events["workout_date"] = pd.to_datetime(events["workout_date"])
        events["workout_year"] = events["workout_date"].dt.year
        events["workout_month"] = events["workout_date"].dt.to_period("M").astype("string")
        events["workout_month_num"] = events["workout_date"].dt.month
        events["workout_week"] = events["workout_date"].dt.isocalendar().week.astype("Int64")
        events["workout_weekday"] = events["workout_date"].dt.day_name()
        events["workout_weekday_num"] = events["workout_date"].dt.dayofweek
        events = events.sort_values(["member_id", "workout_date"]).reset_index(drop=True)

    notes = [
        "SYNTHETIC ANALYTICAL DATA: event dates and per-event workout type are generated.",
        "REAL DATA carried through unchanged: churn outcome, membership type, visits per "
        "month, average duration, average calories, join date, last visit date, age, gender.",
        f"Final event date is pinned to each member's real Last_Visit_Date; "
        f"{widened_windows} member window(s) required the documented 30-day widening fallback.",
    ]
    if members_without_events:
        notes.append(
            f"{len(members_without_events)} member(s) imply fewer than one visit in their "
            f"window and therefore have no synthetic events: {members_without_events[:10]}"
        )
    if members_without_window:
        notes.append(
            f"{len(members_without_window)} member(s) have no usable last-visit date, so no "
            f"timeline was generated for them: {members_without_window[:10]}"
        )

    metadata = {
        "rows": int(events.shape[0]),
        "members_with_events": int(events["member_id"].nunique()) if not events.empty else 0,
        "members_input": int(members.shape[0]),
        "expected_events": int(total_expected),
        "seed": int(seed),
        "event_scale": float(event_scale),
        "method": SYNTHETIC_METHOD,
        "components": SYNTHETIC_COMPONENTS,
        "is_synthetic": True,
    }
    logger.info(
        "Synthetic bridge: %s events across %s members (seed=%s)",
        f"{int(events.shape[0]):,}",
        metadata["members_with_events"],
        seed,
    )
    return SyntheticLayer(events=events, metadata=metadata, notes=notes)


def validate_synthetic_layer(
    members: pd.DataFrame, layer: SyntheticLayer, duration_tolerance: float = 1e-6
) -> Dict[str, Any]:
    """Assert that the synthetic layer reproduces the real member aggregates.

    Returns a structured check payload — this is the evidence that the bridge
    preserves source truth rather than inventing behaviour.
    """
    events = layer.events
    checks: List[Dict[str, Any]] = []

    if events.empty:
        return {
            "status": "WARNING",
            "checks": [
                {
                    "check": "synthetic_layer_populated",
                    "status": "WARNING",
                    "detail": "No synthetic events were generated.",
                }
            ],
        }

    # 1. one event per member at minimum
    coverage = events["member_id"].nunique() / max(members["member_id"].nunique(), 1)

    # 2. durations reproduce the real published averages exactly
    agg = events.groupby("member_id").agg(
        mean_duration=("duration_minutes", "mean"),
        mean_calories=("calories_burned", "mean"),
        max_date=("workout_date", "max"),
        min_date=("workout_date", "min"),
        event_count=("workout_id", "count"),
    )
    reference = members.set_index("member_id")[
        ["avg_workout_duration_min", "avg_calories_burned", "last_visit_date"]
    ]
    merged = agg.join(reference, how="inner")
    duration_delta = (merged["mean_duration"] - merged["avg_workout_duration_min"]).abs().max()
    calories_delta = (merged["mean_calories"] - merged["avg_calories_burned"]).abs().max()
    date_delta = (merged["max_date"] - pd.to_datetime(merged["last_visit_date"])).abs().dt.days.max()

    # 3. events must fall inside each member's observation window.
    #    Members whose real Join_Date is on or after their real Last_Visit_Date have a
    #    degenerate window and are handled by the documented 30-day widening fallback;
    #    they are reported separately instead of being masked as a pass.
    reference_full = members.set_index("member_id")[["join_date", "last_visit_date"]].reindex(agg.index)
    join_dates = pd.to_datetime(reference_full["join_date"])
    last_dates = pd.to_datetime(reference_full["last_visit_date"])
    degenerate = join_dates >= last_dates
    degenerate_members = [str(m) for m in agg.index[degenerate.fillna(False)]]
    before_join = (merged["min_date"] < join_dates) & ~degenerate.fillna(False)
    window_violations = int(before_join.sum())

    def add(name: str, ok: bool, detail: str, warn: bool = False) -> None:
        checks.append(
            {
                "check": name,
                "status": "PASS" if ok else ("WARNING" if warn else "FAIL"),
                "detail": detail,
            }
        )

    add(
        "synthetic_member_coverage",
        coverage == 1.0,
        f"{coverage:.1%} of members received at least one synthetic event",
        warn=True,
    )
    add(
        "synthetic_duration_reproduces_source",
        float(duration_delta) <= 1e-6,
        f"max |mean event duration - real Avg_Workout_Duration_Min| = {duration_delta:.6f} minutes",
    )
    add(
        "synthetic_calories_reproduces_source",
        float(calories_delta) <= 1e-6,
        f"max |mean event calories - real Avg_Calories_Burned| = {calories_delta:.6f} kcal",
    )
    add(
        "synthetic_recency_reproduces_source",
        int(date_delta) == 0,
        f"max |last synthetic event date - real Last_Visit_Date| = {int(date_delta)} days",
    )
    add(
        "synthetic_events_inside_window",
        window_violations == 0,
        f"{window_violations} member(s) have synthetic events before their real Join_Date",
    )
    add(
        "synthetic_degenerate_source_windows",
        not degenerate_members,
        (
            "All real [Join_Date, Last_Visit_Date] windows are non-degenerate."
            if not degenerate_members
            else f"{len(degenerate_members)} member(s) have Join_Date on/after Last_Visit_Date in the "
            f"real source ({degenerate_members}); the documented 30-day widening fallback was applied"
        ),
        warn=True,
    )
    add(
        "synthetic_event_volume",
        abs(int(events.shape[0]) - int(layer.metadata.get("expected_events", 0))) == 0,
        f"{events.shape[0]:,} events generated vs {layer.metadata.get('expected_events', 0):,} implied by the real visit rate",
    )

    status = "PASS"
    if any(c["status"] == "FAIL" for c in checks):
        status = "FAIL"
    elif any(c["status"] == "WARNING" for c in checks):
        status = "WARNING"

    return {
        "status": status,
        "checks": checks,
        "coverage": round(float(coverage), 6),
        "degenerate_source_windows": degenerate_members,
        "max_duration_delta": float(duration_delta),
        "max_calories_delta": float(calories_delta),
        "max_recency_delta_days": int(date_delta),
        "declaration": (
            "Synthetic layer declared: event dates and per-event workout type are "
            "generated; all member-level outcomes and measures are real."
        ),
    }


def synthetic_ground_truth_note() -> Dict[str, str]:
    """Short provenance statement reused by the dashboard and reports."""
    return {
        "source_data": "Original Kaggle datasets, unmodified.",
        "derived_data": "Deterministically calculated from source records (rates, banding, features).",
        "synthetic_data": (
            "Educationally generated event dates and workout types used only to demonstrate "
            "multi-source integration where the public datasets share no legitimate common "
            "identifier. Member outcomes and measures remain real."
        ),
    }

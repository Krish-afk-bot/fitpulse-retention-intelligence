"""Integration layer: unify the two sources without fabricating a join.

Integration output
------------------
``fact_workout``
    Real activity events from the activity source (``is_synthetic = False``).
    ``member_id`` is null because the source exposes no repeatable member key.
``dim_member`` / ``fact_membership``
    Real member-level records and the real churn outcome from the membership
    source.
``fact_workout_synthetic``
    The documented synthetic bridge: member-level events whose dates come from
    the synthetic calendar while every measure and outcome is real.
``member_activity``
    The unified analytical model — one row per member with real outcomes plus
    activity features. Columns derived from synthetic date placement are listed
    in ``synthetic_feature_columns``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pandas as pd

from ..common.logging_utils import get_logger
from ..cleaning.cleaners import CleaningResult
from .keys import KeyAnalysis, analyze_key_candidates
from .synthetic import (
    SyntheticLayer,
    synthesize_activity_calendar,
    synthetic_ground_truth_note,
    validate_synthetic_layer,
)

logger = get_logger("integration")


@dataclass
class IntegrationResult:
    """Everything produced by the integration stage."""

    fact_workout: pd.DataFrame
    dim_member: pd.DataFrame
    fact_membership: pd.DataFrame
    fact_workout_synthetic: pd.DataFrame
    key_analysis: Optional[KeyAnalysis] = None
    synthetic_layer: Optional[SyntheticLayer] = None
    synthetic_validation: Dict[str, Any] = field(default_factory=dict)
    row_counts: Dict[str, Any] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)
    join_performed: bool = False
    join_type: str = "none — no legitimate shared key exists"

    def as_dict(self) -> Dict[str, Any]:
        return {
            "join_performed": self.join_performed,
            "join_type": self.join_type,
            "key_analysis": self.key_analysis.as_dict() if self.key_analysis else None,
            "synthetic_validation": self.synthetic_validation,
            "row_counts": self.row_counts,
            "notes": self.notes,
            "synthetic_metadata": self.synthetic_layer.metadata if self.synthetic_layer else None,
            "provenance_statement": synthetic_ground_truth_note(),
        }

    def status(self) -> str:
        if self.synthetic_validation.get("status") == "FAIL":
            return "FAIL"
        if self.key_analysis and self.key_analysis.verdict == "COINCIDENTAL_OVERLAP":
            return "WARNING"
        return self.synthetic_validation.get("status", "PASS")


def integrate_sources(
    activity_raw: pd.DataFrame,
    membership_raw: pd.DataFrame,
    activity_clean: CleaningResult,
    dim_member_result: CleaningResult,
    fact_membership_result: CleaningResult,
    seed: int = 42,
    event_scale: float = 1.0,
) -> IntegrationResult:
    """Run key analysis, build the synthetic bridge and report row accounting."""
    notes: List[str] = []

    # --- 1. Pre-join key assessment (always runs, even when no join is possible)
    key_analysis: Optional[KeyAnalysis] = None
    try:
        key_analysis = analyze_key_candidates(activity_raw, membership_raw)
        notes.append(
            f"Key verdict: {key_analysis.verdict} — {key_analysis.recommendation}"
        )
    except KeyError as exc:  # pragma: no cover - defensive
        notes.append(f"Key analysis skipped: {exc}")

    # --- 2. Synthetic bridge over the real member records
    member_records = dim_member_result.frame.merge(
        fact_membership_result.frame,
        on="member_id",
        how="inner",
        suffixes=("", "_membership"),
    )
    layer = synthesize_activity_calendar(member_records, seed=seed, event_scale=event_scale)
    validation = validate_synthetic_layer(member_records, layer)
    notes.extend(layer.notes)

    # --- 3. Row accounting: before / after, and join-multiplication control
    row_counts = {
        "activity_source_rows": int(len(activity_raw)),
        "activity_canonical_rows": int(len(activity_clean.frame)),
        "membership_source_rows": int(len(membership_raw)),
        "dim_member_rows": int(len(dim_member_result.frame)),
        "fact_membership_rows": int(len(fact_membership_result.frame)),
        "synthetic_event_rows": int(layer.rows),
        "unified_member_rows": int(len(dim_member_result.frame)),
    }
    if key_analysis:
        row_counts["naive_join_rows_if_performed"] = key_analysis.join_rows_naive
        row_counts["join_row_multiplication_factor"] = key_analysis.row_multiplication_factor
    notes.append(
        "No join was performed between the sources, so there is no risk of join-induced "
        "row multiplication in the curated layer."
    )
    notes.append(
        "Activity events (real) and the synthetic event calendar are kept in separate "
        "tables so real and synthetic activity can never be silently combined."
    )

    logger.info(
        "Integration complete | real events=%s | synthetic events=%s | members=%s | status=%s",
        f"{len(activity_clean.frame):,}",
        f"{layer.rows:,}",
        f"{len(dim_member_result.frame):,}",
        validation.get("status"),
    )

    return IntegrationResult(
        fact_workout=activity_clean.frame,
        dim_member=dim_member_result.frame,
        fact_membership=fact_membership_result.frame,
        fact_workout_synthetic=layer.events,
        key_analysis=key_analysis,
        synthetic_layer=layer,
        synthetic_validation=validation,
        row_counts=row_counts,
        notes=notes,
    )


def integration_summary_frame(result: IntegrationResult) -> pd.DataFrame:
    """Compact table for the Data Quality page's 'Integration quality' panel."""
    rows: List[Dict[str, Any]] = [
        {
            "item": "Sources integrated",
            "value": "2 (activity, membership)",
            "status": "PASS",
            "detail": "Both sources ingested, validated and canonically modelled.",
        },
        {
            "item": "Legitimate shared key",
            "value": "None",
            "status": "WARNING",
            "detail": (
                result.key_analysis.recommendation
                if result.key_analysis
                else "No candidate key available."
            ),
        },
        {
            "item": "Raw identifier overlap",
            "value": f"{result.key_analysis.overlap_count if result.key_analysis else 0:,} values",
            "status": "WARNING",
            "detail": "Coincidental sequential integers; demographic agreement is near chance.",
        },
        {
            "item": "User-level join performed",
            "value": "No",
            "status": "PASS",
            "detail": "Fabricated relationships are structurally prevented.",
        },
        {
            "item": "Synthetic bridge",
            "value": f"{result.synthetic_layer.rows if result.synthetic_layer else 0:,} events",
            "status": result.synthetic_validation.get("status", "PASS"),
            "detail": result.synthetic_validation.get("declaration", ""),
        },
    ]
    return pd.DataFrame(rows)

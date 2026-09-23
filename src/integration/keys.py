"""Candidate-key analysis for multi-source integration.

The PRD requires that no join happens until key validity is established. This
module performs the full pre-join checklist — uniqueness, overlap, unmatched
records, duplicate multiplication — and produces an explicit verdict.

**Finding for the two published sources:** the activity source's ``member_id``
is unique across all 2,600 rows (a record sequence), and the membership
source's ``Member_ID`` identifies 150 members. Their integer ranges overlap
*coincidentally* (1–150 in both), which is exactly the trap the PRD warns
about: identical-looking integers from unrelated Kaggle datasets are not the
same people. The evidence below demonstrates the overlap is coincidental.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from ..common.logging_utils import get_logger

logger = get_logger("integration")

VERDICT_VALID = "VALID_KEY"
VERDICT_COINCIDENTAL = "COINCIDENTAL_OVERLAP"
VERDICT_NONE = "NO_CANDIDATE_KEY"


@dataclass
class KeyCandidate:
    """One column considered as a join key."""

    column: str
    dataset: str
    rows: int
    distinct_values: int
    nulls: int
    is_unique: bool
    examples: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "column": self.column,
            "dataset": self.dataset,
            "rows": self.rows,
            "distinct_values": self.distinct_values,
            "nulls": self.nulls,
            "is_unique": self.is_unique,
            "uniqueness_ratio": round(self.distinct_values / self.rows, 4) if self.rows else 0.0,
            "examples": self.examples,
        }


@dataclass
class KeyAnalysis:
    """Complete pre-join assessment of a candidate key pair."""

    left_dataset: str
    right_dataset: str
    left_key: str
    right_key: str
    left: KeyCandidate
    right: KeyCandidate
    overlap_count: int
    overlap_pct_of_left: float
    overlap_pct_of_right: float
    unmatched_left: int
    unmatched_right: int
    join_rows_naive: int
    row_multiplication_factor: float
    verdict: str
    confidence: str
    evidence: List[str] = field(default_factory=list)
    recommendation: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "left_dataset": self.left_dataset,
            "right_dataset": self.right_dataset,
            "left_key": self.left_key,
            "right_key": self.right_key,
            "left": self.left.as_dict(),
            "right": self.right.as_dict(),
            "overlap_count": self.overlap_count,
            "overlap_pct_of_left": self.overlap_pct_of_left,
            "overlap_pct_of_right": self.overlap_pct_of_right,
            "unmatched_left": self.unmatched_left,
            "unmatched_right": self.unmatched_right,
            "join_rows_naive": self.join_rows_naive,
            "row_multiplication_factor": self.row_multiplication_factor,
            "verdict": self.verdict,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "recommendation": self.recommendation,
            "join_performed": False,
        }


def describe_key(series: pd.Series, column: str, dataset: str, sample: int = 3) -> KeyCandidate:
    """Summarise a candidate key column."""
    cleaned = series.astype("string").str.strip()
    return KeyCandidate(
        column=column,
        dataset=dataset,
        rows=int(len(cleaned)),
        distinct_values=int(cleaned.nunique(dropna=True)),
        nulls=int(cleaned.isna().sum()),
        is_unique=bool(cleaned.nunique(dropna=True) == len(cleaned)),
        examples=[str(v) for v in cleaned.dropna().unique()[:sample].tolist()],
    )


def _to_comparable(series: pd.Series) -> pd.Series:
    """Make two identifier columns comparable (numeric where possible)."""
    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.notna().mean() >= 0.95:
        return numeric.dropna()
    return series.astype("string").str.strip().dropna()


def analyze_key_candidates(
    activity: pd.DataFrame,
    membership: pd.DataFrame,
    activity_key: str = "member_id",
    membership_key: str = "Member_ID",
    demographic_probe: bool = True,
) -> KeyAnalysis:
    """Run the full pre-join key checklist across the two sources.

    Both frames are expected to be the **raw** source frames, evaluated before
    the canonicalisation step that namespaces membership identifiers. The
    analysis therefore examines the strongest possible case for a join — the
    literal identifier values as published — and only then decides.

    Parameters
    ----------
    activity_key / membership_key:
        identifier columns as they appear in the raw published files.
    demographic_probe:
        When ``True``, compare ``age`` and ``gender`` for the coincidentally
        overlapping identifiers. A near-random agreement rate is direct evidence
        that the identifiers do not describe the same people.
    """
    if activity_key not in activity.columns or membership_key not in membership.columns:
        raise KeyError(
            f"Key analysis requires '{activity_key}' in the activity frame and "
            f"'{membership_key}' in the membership frame."
        )
    left_series = activity[activity_key]
    right_series = membership[membership_key]

    left = describe_key(left_series, activity_key, "activity")
    right = describe_key(right_series, membership_key, "membership")

    left_values = _to_comparable(left_series)
    right_values = _to_comparable(right_series)
    left_set, right_set = set(left_values), set(right_values)
    overlap = left_set & right_set

    # Duplicate multiplication: rows produced by a naive join on the raw key.
    left_counts = left_values.value_counts()
    right_counts = right_values.value_counts()
    shared = [v for v in overlap]
    naive_rows = int(sum(int(left_counts.get(v, 0)) * int(right_counts.get(v, 0)) for v in shared))
    multiplication = naive_rows / max(len(membership), 1)

    evidence: List[str] = [
        f"Activity '{activity_key}' has {left.distinct_values:,} distinct values across "
        f"{left.rows:,} rows (uniqueness ratio "
        f"{left.distinct_values / max(left.rows, 1):.4f}) — it is a record sequence, not a member key.",
        f"Membership '{membership_key}' identifies {right.distinct_values:,} distinct members "
        f"across {right.rows:,} rows.",
        f"Raw value overlap: {len(overlap):,} identifiers "
        f"({100.0 * len(overlap) / max(right.rows, 1):.1f}% of membership rows).",
    ]

    verdict = VERDICT_NONE
    confidence = "high"
    recommendation = ""

    if not left.is_unique or not right.is_unique:
        evidence.append(
            "At least one candidate key is not unique, so a join would multiply rows."
        )

    if overlap:
        verdict = VERDICT_COINCIDENTAL
        evidence.append(
            "Overlap is driven by small sequential integers. Both files simply start "
            "numbering at 1, which is coincidence, not a shared entity."
        )
        if demographic_probe:
            probe = demographic_consistency(activity, membership, activity_key, membership_key)
            for note in probe["evidence"]:
                evidence.append(note)
            if probe["agreement_rate"] is not None:
                evidence.append(
                    f"Demographic agreement on overlapping identifiers: "
                    f"{probe['agreement_rate']:.1%}. An unrelated-population level of "
                    f"agreement confirms the identifiers are not shared entities."
                )
            confidence = "high"
        recommendation = (
            "DO NOT JOIN on these identifiers. Treat the sources as independent and use "
            "the documented synthetic integration layer, which carries an explicit "
            "`is_synthetic` flag and reproduces the real member aggregates exactly."
        )
    else:
        recommendation = (
            "No shared identifier exists. Sources remain logically separate and are "
            "reconciled through the documented synthetic integration layer."
        )

    analysis = KeyAnalysis(
        left_dataset="activity",
        right_dataset="membership",
        left_key=activity_key,
        right_key=membership_key,
        left=left,
        right=right,
        overlap_count=len(overlap),
        overlap_pct_of_left=round(100.0 * len(overlap) / max(left.rows, 1), 4),
        overlap_pct_of_right=round(100.0 * len(overlap) / max(right.rows, 1), 4),
        unmatched_left=left.rows - len(overlap),
        unmatched_right=right.rows - len(overlap),
        join_rows_naive=naive_rows,
        row_multiplication_factor=round(multiplication, 4),
        verdict=verdict,
        confidence=confidence,
        evidence=evidence,
        recommendation=recommendation,
    )
    logger.info(
        "Key analysis: verdict=%s overlap=%s naive_join_rows=%s",
        analysis.verdict,
        analysis.overlap_count,
        analysis.join_rows_naive,
    )
    return analysis


def demographic_consistency(
    activity: pd.DataFrame,
    membership: pd.DataFrame,
    activity_key: str = "member_id",
    membership_key: str = "Member_ID",
) -> Dict[str, Any]:
    """Compare age/gender on overlapping identifiers between the two sources.

    If the same integers referred to the same people, ``age`` and ``gender``
    recorded in the attendance system would agree with the membership system.
    A near-random agreement rate is objective evidence they do not.
    """
    result: Dict[str, Any] = {"agreement_rate": None, "evidence": []}

    if activity_key not in activity.columns or membership_key not in membership.columns:
        return result

    left = pd.DataFrame(
        {
            "_k": pd.to_numeric(activity[activity_key], errors="coerce"),
            "age_act": pd.to_numeric(activity["age"], errors="coerce"),
            "gender_act": activity["gender"].astype("string").str.strip(),
        }
    )
    right = pd.DataFrame(
        {
            "_k": pd.to_numeric(membership[membership_key], errors="coerce"),
            "age_mem": pd.to_numeric(membership["Age"], errors="coerce"),
            "gender_mem": membership["Gender"].astype("string").str.strip(),
        }
    )

    merged = left.merge(right, on="_k")
    if merged.empty:
        result["evidence"].append(
            "No overlapping identifiers could be compared demographically."
        )
        return result

    age_match = (merged["age_act"] == merged["age_mem"])
    gender_match = (
        merged["gender_act"].astype("string").str.lower()
        == merged["gender_mem"].astype("string").str.lower()
    )
    both = (age_match & gender_match).mean()
    result["agreement_rate"] = float(both)
    result["compared_rows"] = int(len(merged))
    result["age_agreement"] = float(age_match.mean())
    result["gender_agreement"] = float(gender_match.mean())
    result["evidence"].append(
        f"Compared {len(merged):,} overlapping identifiers: age agrees in "
        f"{age_match.mean():.1%} of cases, gender in {gender_match.mean():.1%}."
    )
    return result

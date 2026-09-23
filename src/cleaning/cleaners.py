"""Reusable cleaning primitives.

Design rules:

* **Nothing is silently deleted.** Every step records how many rows changed.
* **Missing values are handled by semantics**, not by blanket filling: a null
  ``Join_Date`` is not the same kind of gap as a null ``Age``. Where a value is
  imputed, an accompanying ``*_imputed`` flag is added so downstream analysis
  can exclude it.
* **Outliers are classified, never dropped.**
* **Personal identifiers are dropped** as part of cleaning, not merely hidden.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from ..common.logging_utils import get_logger

logger = get_logger("cleaning")

#: Columns that must never be persisted downstream (PRD §31).
PII_COLUMNS: Tuple[str, ...] = (
    "Name",
    "Address",
    "Phone_Number",
    "name",
    "address",
    "phone_number",
    "Email",
    "email",
)

OUTLIER_VALID_EXTREME = "valid_extreme"
OUTLIER_POTENTIAL_ERROR = "potential_error"
OUTLIER_UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------
@dataclass
class CleaningStep:
    """One measurable transformation."""

    step: str
    rows_before: int
    rows_after: int
    cells_changed: int = 0
    columns: List[str] = field(default_factory=list)
    note: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "step": self.step,
            "rows_before": self.rows_before,
            "rows_after": self.rows_after,
            "rows_removed": self.rows_before - self.rows_after,
            "cells_changed": self.cells_changed,
            "columns": self.columns,
            "note": self.note,
        }


@dataclass
class CleaningResult:
    """Cleaned frame plus the audit trail of how it got there."""

    name: str
    frame: pd.DataFrame
    steps: List[CleaningStep] = field(default_factory=list)
    rows_in: int = 0
    notes: List[str] = field(default_factory=list)

    def add(
        self,
        step: str,
        rows_before: int,
        rows_after: int,
        cells_changed: int = 0,
        columns: Optional[Sequence[str]] = None,
        note: str = "",
    ) -> "CleaningResult":
        self.steps.append(
            CleaningStep(
                step=step,
                rows_before=int(rows_before),
                rows_after=int(rows_after),
                cells_changed=int(cells_changed),
                columns=list(columns or []),
                note=note,
            )
        )
        return self

    @property
    def rows_out(self) -> int:
        return int(self.frame.shape[0])

    @property
    def duplicates_removed(self) -> int:
        return sum(s.rows_before - s.rows_after for s in self.steps)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "rows_in": self.rows_in,
            "rows_out": self.rows_out,
            "rows_removed": self.rows_in - self.rows_out,
            "steps": [s.as_dict() for s in self.steps],
            "notes": self.notes,
        }

    def summary_text(self) -> str:
        lines = [f"Rows before: {self.rows_in:,}"]
        for step in self.steps:
            removed = step.rows_before - step.rows_after
            if removed:
                lines.append(f"  {step.step}: rows removed {removed:,}")
            elif step.cells_changed:
                lines.append(f"  {step.step}: cells changed {step.cells_changed:,}")
        lines.append(f"Rows after: {self.rows_out:,}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# String / category normalisation
# ---------------------------------------------------------------------------
def strip_whitespace(frame: pd.DataFrame, columns: Sequence[str]) -> Tuple[pd.DataFrame, int]:
    """Trim leading/trailing whitespace plus collapse internal runs of spaces."""
    out = frame.copy()
    changed = 0
    for column in columns:
        if column not in out.columns:
            continue
        original = out[column].astype("string")
        cleaned = original.str.strip().str.replace(r"\s+", " ", regex=True)
        changed += int((original.fillna("") != cleaned.fillna("")).sum())
        out[column] = cleaned
    return out, changed


def normalize_category(
    frame: pd.DataFrame,
    column: str,
    mapping: Optional[Dict[str, str]] = None,
    title_case: bool = True,
) -> Tuple[pd.DataFrame, int]:
    """Normalise a categorical column to canonical spelling.

    ``"Running" | "running" | " RUNNING " -> "Running"``

    ``mapping`` is applied case-insensitively after trimming.
    """
    out = frame.copy()
    if column not in out.columns:
        return out, 0
    original = out[column].astype("string").str.strip().str.replace(r"\s+", " ", regex=True)
    cleaned = original
    if title_case:
        cleaned = cleaned.map(
            lambda v: v
            if pd.isna(v) or v == "" or (str(v).lower() in {"hiit", "crossfit"})
            else str(v).title()
        )
    # The explicit mapping is applied last so documented canonical spellings
    # (for example "Pull-ups", which title-casing would turn into "Pull-Ups")
    # always win over generic casing rules.
    if mapping:
        lookup = {k.strip().lower(): v for k, v in mapping.items()}
        cleaned = cleaned.map(lambda v: lookup.get(str(v).lower(), v) if pd.notna(v) else v)
    changed = int((original.fillna("") != cleaned.fillna("")).sum())
    out[column] = cleaned
    return out, changed


def to_numeric_safe(
    frame: pd.DataFrame, columns: Sequence[str], errors: str = "coerce"
) -> Tuple[pd.DataFrame, int]:
    """Convert columns to numeric, counting values that failed conversion."""
    out = frame.copy()
    failed = 0
    for column in columns:
        if column not in out.columns:
            continue
        before = out[column]
        converted = pd.to_numeric(before, errors=errors)
        failed += int(converted.isna().sum() - before.isna().sum())
        out[column] = converted
    return out, max(failed, 0)


def to_datetime_safe(
    frame: pd.DataFrame, columns: Sequence[str], dayfirst: bool = False
) -> Tuple[pd.DataFrame, Dict[str, int]]:
    """Parse date columns, reporting per-column failures."""
    out = frame.copy()
    failures: Dict[str, int] = {}
    for column in columns:
        if column not in out.columns:
            continue
        before = out[column]
        parsed = pd.to_datetime(before, errors="coerce", format="mixed", dayfirst=dayfirst)
        failures[column] = int(parsed.isna().sum() - before.isna().sum())
        out[column] = parsed
    return out, failures


def parse_time_of_day(frame: pd.DataFrame, column: str) -> Tuple[pd.DataFrame, int]:
    """Parse ``HH:MM`` strings into minutes-since-midnight (integer)."""
    out = frame.copy()
    if column not in out.columns:
        return out, 0
    text = out[column].astype("string").str.strip()
    parsed = pd.to_datetime(text, format="%H:%M", errors="coerce")
    minutes = (parsed.dt.hour * 60 + parsed.dt.minute)
    failures = int(minutes.isna().sum() - out[column].isna().sum())
    out[f"{column}_minutes"] = minutes
    out["check_in_hour"] = parsed.dt.hour
    out["check_in_minutes"] = minutes
    return out, max(failures, 0)


def drop_pii(frame: pd.DataFrame, columns: Sequence[str] = PII_COLUMNS) -> Tuple[pd.DataFrame, List[str]]:
    """Drop direct personal identifiers. Returns the frame and the dropped names."""
    present = [c for c in columns if c in frame.columns]
    return frame.drop(columns=present), present


# ---------------------------------------------------------------------------
# Duplicates
# ---------------------------------------------------------------------------
def drop_exact_duplicates(
    frame: pd.DataFrame, subset: Optional[Sequence[str]] = None
) -> Tuple[pd.DataFrame, int]:
    """Remove exact duplicate rows on ``subset`` (or all columns)."""
    before = len(frame)
    deduped = frame.drop_duplicates(subset=list(subset) if subset else None, keep="first")
    return deduped.reset_index(drop=True), before - len(deduped)


# ---------------------------------------------------------------------------
# Outliers
# ---------------------------------------------------------------------------
def classify_outliers(
    series: pd.Series,
    valid_min: Optional[float] = None,
    valid_max: Optional[float] = None,
    iqr_multiplier: float = 1.5,
) -> pd.Series:
    """Classify each value as normal / valid extreme / potential error.

    * ``potential_error`` — outside the statistically plausible fence **and**
      outside the hard business domain (impossible for a real workout).
    * ``valid_extreme`` — outside the IQR fence but inside the business domain:
      genuinely unusual but real values. **Never deleted.**
    * ``unknown`` — inside the IQR fence, or non-numeric.
    """
    numeric = pd.to_numeric(series, errors="coerce")
    labels = pd.Series(OUTLIER_UNKNOWN, index=series.index, dtype="object")
    valid = numeric.dropna()
    if valid.empty:
        return labels

    q1, q3 = valid.quantile(0.25), valid.quantile(0.75)
    iqr = q3 - q1
    low_fence = q1 - iqr_multiplier * iqr
    high_fence = q3 + iqr_multiplier * iqr

    outside_fence = (numeric < low_fence) | (numeric > high_fence)
    domain_violation = pd.Series(False, index=series.index)
    if valid_min is not None:
        domain_violation |= numeric < valid_min
    if valid_max is not None:
        domain_violation |= numeric > valid_max

    labels[outside_fence & domain_violation] = OUTLIER_POTENTIAL_ERROR
    labels[outside_fence & ~domain_violation] = OUTLIER_VALID_EXTREME
    return labels


def outlier_summary(
    frame: pd.DataFrame,
    columns: Sequence[str],
    domains: Optional[Dict[str, Tuple[Optional[float], Optional[float]]]] = None,
) -> Dict[str, Dict[str, Any]]:
    """Classify outliers for several columns at once (reported, not removed)."""
    domains = domains or {}
    summary: Dict[str, Dict[str, Any]] = {}
    for column in columns:
        if column not in frame.columns:
            continue
        low, high = domains.get(column, (None, None))
        labels = classify_outliers(frame[column], valid_min=low, valid_max=high)
        counts = labels.value_counts().to_dict()
        summary[column] = {
            "valid_extreme": int(counts.get(OUTLIER_VALID_EXTREME, 0)),
            "potential_error": int(counts.get(OUTLIER_POTENTIAL_ERROR, 0)),
            "unknown": int(counts.get(OUTLIER_UNKNOWN, 0)),
            "domain": {"min": low, "max": high},
            "action": "flagged only — no values deleted",
        }
    return summary


# ---------------------------------------------------------------------------
# Missing values
# ---------------------------------------------------------------------------
def impute_numeric_median(
    frame: pd.DataFrame, columns: Sequence[str], flag_suffix: str = "_imputed"
) -> Tuple[pd.DataFrame, Dict[str, int]]:
    """Median-impute numeric columns and add an explicit imputation flag.

    Median (rather than mean) is used because the measures are bounded and
    right-skewed. The flag column lets every downstream KPI be recomputed on
    complete cases only.
    """
    out = frame.copy()
    imputed: Dict[str, int] = {}
    for column in columns:
        if column not in out.columns:
            continue
        numeric = pd.to_numeric(out[column], errors="coerce")
        mask = numeric.isna()
        count = int(mask.sum())
        imputed[column] = count
        if count:
            out[f"{column}{flag_suffix}"] = mask
            out[column] = numeric.fillna(numeric.median())
        else:
            out[f"{column}{flag_suffix}"] = False
    return out, imputed


def add_missing_flags(frame: pd.DataFrame, columns: Sequence[str]) -> Tuple[pd.DataFrame, int]:
    """Add ``<col>_missing`` booleans without imputing anything."""
    out = frame.copy()
    added = 0
    for column in columns:
        if column not in out.columns:
            continue
        out[f"{column}_missing"] = out[column].isna()
        added += 1
    return out, added


def clean_null_strings(frame: pd.DataFrame, columns: Sequence[str]) -> Tuple[pd.DataFrame, int]:
    """Convert placeholder strings ('', 'NA', 'N/A', 'null', '-') into real nulls."""
    placeholders = {"", "na", "n/a", "null", "none", "nan", "-", "--", "unknown?"}
    out = frame.copy()
    changed = 0
    for column in columns:
        if column not in out.columns:
            continue
        series = out[column].astype("string")
        stripped = series.str.strip()
        is_placeholder = stripped.str.lower().isin(placeholders)
        changed += int(is_placeholder.fillna(False).sum())
        out[column] = series.where(~is_placeholder.fillna(False), pd.NA)
    return out, changed


# ---------------------------------------------------------------------------
# Derived helpers
# ---------------------------------------------------------------------------
def age_group(age: Any) -> str:
    """Deterministic age banding used for segmentation and filtering."""
    if pd.isna(age):
        return "Unknown"
    try:
        value = float(age)
    except (TypeError, ValueError):
        return "Unknown"
    if value < 25:
        return "18-24"
    if value < 35:
        return "25-34"
    if value < 45:
        return "35-44"
    if value < 55:
        return "45-54"
    return "55+"


def add_age_group(frame: pd.DataFrame, column: str = "age") -> pd.DataFrame:
    out = frame.copy()
    if column in out.columns:
        out["age_group"] = out[column].map(age_group)
    return out


def normalize_boolean(
    series: pd.Series, true_values: Iterable[str] = ("yes", "true", "1", "y", "churn")
) -> pd.Series:
    """Convert assorted truthy spellings into a nullable boolean."""
    truthy = {v.lower() for v in true_values}
    text = series.astype("string").str.strip().str.lower()
    out = pd.Series(pd.NA, index=series.index, dtype="boolean")
    out[text.isin(truthy)] = True
    out[text.notna() & ~text.isin(truthy)] = False
    return out


def clamp(series: pd.Series, low: float, high: float) -> pd.Series:
    """Clamp a numeric series into ``[low, high]`` (used for score components)."""
    return pd.to_numeric(series, errors="coerce").clip(lower=low, upper=high)


def safe_divide(numerator: Any, denominator: Any, default: float = 0.0) -> float:
    """Division that never raises and never returns inf/NaN."""
    try:
        num = float(numerator)
        den = float(denominator)
    except (TypeError, ValueError):
        return default
    if den == 0 or np.isnan(den) or np.isnan(num):
        return default
    return num / den


def minmax_scale(series: pd.Series, low: float = 0.0, high: float = 100.0) -> pd.Series:
    """Scale a series to ``[low, high]``; constant series maps to ``low``."""
    numeric = pd.to_numeric(series, errors="coerce")
    minimum, maximum = numeric.min(), numeric.max()
    if pd.isna(minimum) or pd.isna(maximum) or maximum == minimum:
        return pd.Series(low, index=series.index, dtype="float64")
    scaled = (numeric - minimum) / (maximum - minimum)
    return low + scaled * (high - low)

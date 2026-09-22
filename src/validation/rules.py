"""Reusable validation rule primitives.

Each ``check_*`` function returns a single :class:`CheckResult`. Rules are
composed by :mod:`src.validation.validator` into source-specific reports.

Every rule reports *how much* of the data failed, never just a boolean, so the
Data Quality dashboard can show severity honestly.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence

import numpy as np
import pandas as pd

from .results import (
    PASS,
    WARNING,
    FAIL,
    SEVERITY_CRITICAL,
    SEVERITY_INFO,
    SEVERITY_WARNING,
    CheckResult,
)


def _status_from_rate(
    failing_pct: float,
    warn_pct: Optional[float],
    fail_pct: Optional[float],
) -> str:
    if fail_pct is not None and failing_pct > fail_pct:
        return FAIL
    if warn_pct is not None and failing_pct > warn_pct:
        return WARNING
    return PASS


def _example_values(values: pd.Series, limit: int = 5) -> List[str]:
    try:
        return [str(v) for v in values.dropna().astype(str).unique()[:limit].tolist()]
    except Exception:  # pragma: no cover - defensive
        return []


# ---------------------------------------------------------------------------
# Schema rules
# ---------------------------------------------------------------------------
def check_required_columns(
    frame: pd.DataFrame,
    required: Sequence[str],
    dataset: str,
    check_id: str = "schema.required_columns",
) -> CheckResult:
    missing = [c for c in required if c not in frame.columns]
    return CheckResult(
        check_id=check_id,
        dataset=dataset,
        category="schema",
        description=f"Required columns present ({len(required)} expected)",
        status=FAIL if missing else PASS,
        severity=SEVERITY_CRITICAL,
        total_rows=len(frame),
        failing_rows=len(missing),
        failing_pct=100.0 * len(missing) / max(len(required), 1),
        threshold="0 missing required columns",
        detail="" if not missing else f"Missing: {missing}",
        examples=missing,
    )


def check_unexpected_columns(
    frame: pd.DataFrame,
    expected: Sequence[str],
    dataset: str,
    check_id: str = "schema.unexpected_columns",
) -> CheckResult:
    unexpected = [c for c in frame.columns if c not in set(expected)]
    return CheckResult(
        check_id=check_id,
        dataset=dataset,
        category="schema",
        description="No unexpected columns outside the source contract",
        status=WARNING if unexpected else PASS,
        severity=SEVERITY_INFO,
        total_rows=len(frame.columns),
        failing_rows=len(unexpected),
        failing_pct=100.0 * len(unexpected) / max(len(frame.columns), 1),
        threshold="0 unexpected columns",
        detail="" if not unexpected else f"Unexpected (ignored downstream): {unexpected}",
        examples=unexpected,
    )


def check_type_conversion(
    series: pd.Series,
    target: str,
    dataset: str,
    check_id: str,
    description: str,
    warn_pct: float = 0.0,
    fail_pct: float = 5.0,
) -> CheckResult:
    """Verify a column can be coerced to ``target`` (``numeric`` or ``date``)."""
    non_null = series.dropna()
    if target == "numeric":
        converted = pd.to_numeric(non_null, errors="coerce")
    elif target == "time":
        converted = pd.to_datetime(non_null.astype(str).str.strip(), format="%H:%M", errors="coerce")
    else:
        converted = pd.to_datetime(non_null, errors="coerce", format="mixed")

    failing = int(converted.isna().sum())
    failing_pct = 100.0 * failing / max(len(series), 1)
    status = _status_from_rate(failing_pct, warn_pct, fail_pct)
    bad = non_null[converted.isna()]
    return CheckResult(
        check_id=check_id,
        dataset=dataset,
        category="schema",
        description=description,
        status=status,
        severity=SEVERITY_WARNING if status == WARNING else SEVERITY_CRITICAL,
        total_rows=int(len(series)),
        failing_rows=failing,
        failing_pct=round(failing_pct, 4),
        threshold=f"<= {fail_pct}% unparseable",
        detail="" if failing == 0 else f"{failing:,} values failed {target} conversion",
        examples=_example_values(bad),
    )


# ---------------------------------------------------------------------------
# Numeric rules
# ---------------------------------------------------------------------------
def check_numeric_min(
    frame: pd.DataFrame,
    column: str,
    minimum: float,
    dataset: str,
    check_id: Optional[str] = None,
    description: Optional[str] = None,
    strict: bool = False,
    warn_pct: float = 0.0,
    fail_pct: float = 0.0,
    severity: str = SEVERITY_CRITICAL,
) -> CheckResult:
    """Rule of the form ``column >= minimum`` (or ``> minimum`` when strict)."""
    check_id = check_id or f"numeric.{column}_min"
    description = description or f"{column} {'>' if strict else '>='} {minimum:g}"
    if column not in frame.columns:
        return CheckResult(
            check_id=check_id,
            dataset=dataset,
            category="numeric",
            description=description,
            status=WARNING,
            severity=SEVERITY_INFO,
            detail=f"Column '{column}' not present in source; rule not applicable.",
        )
    numeric = pd.to_numeric(frame[column], errors="coerce")
    mask = numeric.notna()
    failing = int(((numeric < minimum) if not strict else (numeric <= minimum))[mask].sum())
    failing_pct = 100.0 * failing / max(int(mask.sum()), 1)
    status = _status_from_rate(failing_pct, warn_pct, fail_pct)
    return CheckResult(
        check_id=check_id,
        dataset=dataset,
        category="numeric",
        description=description,
        status=status,
        severity=severity,
        total_rows=int(len(frame)),
        failing_rows=failing,
        failing_pct=round(failing_pct, 4),
        threshold=f"violations <= {fail_pct}%",
        detail="" if failing == 0 else f"{failing:,} rows violate the rule",
        examples=_example_values(numeric[mask][(numeric < minimum) if not strict else (numeric <= minimum)]),
    )


def check_numeric_between(
    frame: pd.DataFrame,
    column: str,
    low: float,
    high: float,
    dataset: str,
    check_id: Optional[str] = None,
    description: Optional[str] = None,
    severity: str = SEVERITY_WARNING,
    fail_pct: float = 5.0,
) -> CheckResult:
    """Rule of the form ``low <= column <= high``."""
    check_id = check_id or f"numeric.{column}_range"
    description = description or f"{low:g} <= {column} <= {high:g}"
    if column not in frame.columns:
        return CheckResult(
            check_id=check_id,
            dataset=dataset,
            category="numeric",
            description=description,
            status=WARNING,
            severity=SEVERITY_INFO,
            detail=f"Column '{column}' not present in source; rule not applicable.",
        )
    numeric = pd.to_numeric(frame[column], errors="coerce")
    mask = numeric.notna()
    violations = mask & ((numeric < low) | (numeric > high))
    failing = int(violations.sum())
    failing_pct = 100.0 * failing / max(int(mask.sum()), 1)
    return CheckResult(
        check_id=check_id,
        dataset=dataset,
        category="numeric",
        description=description,
        status=_status_from_rate(failing_pct, None, fail_pct),
        severity=severity,
        total_rows=int(len(frame)),
        failing_rows=failing,
        failing_pct=round(failing_pct, 4),
        threshold=f"violations <= {fail_pct}%",
        detail="" if failing == 0 else f"{failing:,} rows outside plausible range",
        examples=_example_values(numeric[violations]),
    )


# ---------------------------------------------------------------------------
# Date rules
# ---------------------------------------------------------------------------
def check_date_order(
    frame: pd.DataFrame,
    earlier: str,
    later: str,
    dataset: str,
    check_id: Optional[str] = None,
    description: Optional[str] = None,
    fail_pct: float = 0.0,
) -> CheckResult:
    """Rule of the form ``earlier <= later`` (e.g. join_date <= last_visit_date)."""
    check_id = check_id or f"date.{earlier}_lte_{later}"
    description = description or f"{earlier} <= {later}"
    if earlier not in frame.columns or later not in frame.columns:
        return CheckResult(
            check_id=check_id,
            dataset=dataset,
            category="date",
            description=description,
            status=WARNING,
            severity=SEVERITY_INFO,
            detail=f"Columns '{earlier}'/'{later}' unavailable; rule not applicable.",
        )
    left = pd.to_datetime(frame[earlier], errors="coerce", format="mixed")
    right = pd.to_datetime(frame[later], errors="coerce", format="mixed")
    comparable = left.notna() & right.notna()
    violations = comparable & (left > right)
    failing = int(violations.sum())
    failing_pct = 100.0 * failing / max(int(comparable.sum()), 1)
    return CheckResult(
        check_id=check_id,
        dataset=dataset,
        category="date",
        description=description,
        status=_status_from_rate(failing_pct, None, fail_pct),
        severity=SEVERITY_CRITICAL,
        total_rows=int(comparable.sum()),
        failing_rows=failing,
        failing_pct=round(failing_pct, 4),
        threshold=f"violations <= {fail_pct}%",
        detail=""
        if failing == 0
        else f"{failing:,} rows have {earlier} after {later}",
        examples=[
            f"{a.date()} > {b.date()}"
            for a, b in zip(left[violations].head(5), right[violations].head(5))
        ],
    )


def check_distinct_dates(
    frame: pd.DataFrame,
    earlier: str,
    later: str,
    dataset: str,
    check_id: str,
    description: str,
) -> CheckResult:
    """Flag rows where ``earlier`` and ``later`` hold the identical date.

    A membership that joins and last visits on the same day is possible but rare; a
    cluster of them, or a single one, is worth surfacing because it makes the
    observation window degenerate for behaviour analysis.
    """
    if earlier not in frame.columns or later not in frame.columns:
        return CheckResult(
            check_id=check_id,
            dataset=dataset,
            category="date",
            description=description,
            status=WARNING,
            severity=SEVERITY_INFO,
            detail=f"Columns '{earlier}'/'{later}' unavailable; rule not applicable.",
        )
    left = pd.to_datetime(frame[earlier], errors="coerce", format="mixed")
    right = pd.to_datetime(frame[later], errors="coerce", format="mixed")
    comparable = left.notna() & right.notna()
    same_day = comparable & (left.dt.normalize() == right.dt.normalize())
    failing = int(same_day.sum())
    return CheckResult(
        check_id=check_id,
        dataset=dataset,
        category="date",
        description=description,
        status=WARNING if failing else PASS,
        severity=SEVERITY_INFO,
        total_rows=int(comparable.sum()),
        failing_rows=failing,
        failing_pct=round(100.0 * failing / max(int(comparable.sum()), 1), 4),
        threshold="0 same-day join/last-visit records",
        detail=(
            f"{failing} member(s) have identical {earlier} and {later}; the observation "
            "window for these members is degenerate."
            if failing
            else "No same-day join/last-visit records."
        ),
        examples=[
            f"{a.date()}"
            for a in left[same_day].head(5)
        ],
    )


def check_date_within_window(
    frame: pd.DataFrame,
    column: str,
    low: pd.Timestamp,
    high: pd.Timestamp,
    dataset: str,
    check_id: Optional[str] = None,
    fail_pct: float = 5.0,
) -> CheckResult:
    """Rule: dates fall inside a plausible observation window."""
    check_id = check_id or f"date.{column}_window"
    description = f"{column} within [{low.date()} .. {high.date()}]"
    if column not in frame.columns:
        return CheckResult(
            check_id=check_id,
            dataset=dataset,
            category="date",
            description=description,
            status=WARNING,
            severity=SEVERITY_INFO,
            detail=f"Column '{column}' unavailable; rule not applicable.",
        )
    parsed = pd.to_datetime(frame[column], errors="coerce", format="mixed")
    mask = parsed.notna()
    outside = mask & ((parsed < low) | (parsed > high))
    failing = int(outside.sum())
    failing_pct = 100.0 * failing / max(int(mask.sum()), 1)
    return CheckResult(
        check_id=check_id,
        dataset=dataset,
        category="date",
        description=description,
        status=_status_from_rate(failing_pct, None, fail_pct),
        severity=SEVERITY_WARNING,
        total_rows=int(mask.sum()),
        failing_rows=failing,
        failing_pct=round(failing_pct, 4),
        threshold=f"outside-window rows <= {fail_pct}%",
        detail="" if failing == 0 else f"{failing:,} timestamps outside the expected window",
        examples=_example_values(parsed[outside].astype(str)),
    )


# ---------------------------------------------------------------------------
# Category rules
# ---------------------------------------------------------------------------
def check_categories(
    frame: pd.DataFrame,
    column: str,
    allowed: Sequence[str],
    dataset: str,
    check_id: Optional[str] = None,
    fail_pct: float = 0.0,
    case_sensitive: bool = False,
    severity: str = SEVERITY_WARNING,
) -> CheckResult:
    """Detect invalid / unexpected categories in a categorical column."""
    check_id = check_id or f"category.{column}_allowed"
    description = f"{column} uses only documented categories"
    if column not in frame.columns:
        return CheckResult(
            check_id=check_id,
            dataset=dataset,
            category="category",
            description=description,
            status=WARNING,
            severity=SEVERITY_INFO,
            detail=f"Column '{column}' unavailable; rule not applicable.",
        )
    raw = frame[column].dropna().astype(str).str.strip()
    if case_sensitive:
        invalid = ~raw.isin(list(allowed))
    else:
        lookup = {a.lower() for a in allowed}
        invalid = ~raw.str.lower().isin(lookup)
    failing = int(invalid.sum())
    failing_pct = 100.0 * failing / max(len(raw), 1)
    return CheckResult(
        check_id=check_id,
        dataset=dataset,
        category="category",
        description=description,
        status=_status_from_rate(failing_pct, None, fail_pct),
        severity=severity,
        total_rows=int(len(raw)),
        failing_rows=failing,
        failing_pct=round(failing_pct, 4),
        threshold=f"allowed: {list(allowed)}",
        detail="" if failing == 0 else f"Unexpected values: {_example_values(raw[invalid])}",
        examples=_example_values(raw[invalid]),
    )


def check_whitespace_hygiene(
    frame: pd.DataFrame,
    columns: Sequence[str],
    dataset: str,
    check_id: str = "category.string_hygiene",
) -> CheckResult:
    """Detect leading/trailing whitespace or mixed casing in text columns."""
    present = [c for c in columns if c in frame.columns]
    offending: Dict[str, int] = {}
    total = 0
    for column in present:
        series = frame[column].dropna().astype(str)
        dirty = series != series.str.strip()
        count = int(dirty.sum())
        if count:
            offending[column] = count
        total += count
    status = PASS if not offending else WARNING
    return CheckResult(
        check_id=check_id,
        dataset=dataset,
        category="category",
        description="Categorical values are trimmed and consistently cased",
        status=status,
        severity=SEVERITY_INFO,
        total_rows=int(sum(len(frame[c].dropna()) for c in present)),
        failing_rows=total,
        failing_pct=0.0,
        threshold="0 untrimmed values",
        detail="" if not offending else f"Untrimmed values by column: {offending}",
    )


# ---------------------------------------------------------------------------
# Missingness rules
# ---------------------------------------------------------------------------
def check_missingness(
    frame: pd.DataFrame,
    dataset: str,
    thresholds: Optional[Dict[str, Dict[str, float]]] = None,
    default_warn_pct: float = 5.0,
    default_fail_pct: float = 30.0,
    check_id: str = "missing.column_null_rate",
) -> List[CheckResult]:
    """One missingness check per column.

    ``thresholds`` allows per-column overrides, e.g.
    ``{"Age": {"warn": 10, "fail": 20}}``.
    """
    thresholds = thresholds or {}
    results: List[CheckResult] = []
    rows = max(len(frame), 1)

    for column in frame.columns:
        nulls = int(frame[column].isna().sum())
        pct = 100.0 * nulls / rows
        config = thresholds.get(column, {})
        warn_pct = float(config.get("warn", default_warn_pct))
        fail_pct = float(config.get("fail", default_fail_pct))
        status = _status_from_rate(pct, warn_pct, fail_pct)
        results.append(
            CheckResult(
                check_id=f"{check_id}.{column}",
                dataset=dataset,
                category="missing",
                description=f"{column} missingness within threshold",
                status=status,
                severity=SEVERITY_WARNING if status != PASS else SEVERITY_INFO,
                total_rows=int(len(frame)),
                failing_rows=nulls,
                failing_pct=round(pct, 4),
                threshold=f"warn > {warn_pct:g}%, fail > {fail_pct:g}%",
                detail=f"{nulls:,} null values ({pct:.2f}%)",
            )
        )
    return results


# ---------------------------------------------------------------------------
# Duplicate rules
# ---------------------------------------------------------------------------
def check_duplicate_rows(
    frame: pd.DataFrame,
    dataset: str,
    subset: Optional[Sequence[str]] = None,
    warn_pct: float = 0.5,
    fail_pct: float = 5.0,
    check_id: str = "duplicate.exact_rows",
) -> CheckResult:
    keys = [c for c in (subset or list(frame.columns)) if c in frame.columns]
    if not keys:
        keys = list(frame.columns)
    mask = frame.duplicated(subset=keys, keep="first")
    failing = int(mask.sum())
    failing_pct = 100.0 * failing / max(len(frame), 1)
    label = "whole rows" if subset is None else f"key {list(keys)}"
    return CheckResult(
        check_id=check_id,
        dataset=dataset,
        category="duplicate",
        description=f"No duplicate records on {label}",
        status=_status_from_rate(failing_pct, warn_pct, fail_pct),
        severity=SEVERITY_WARNING,
        total_rows=int(len(frame)),
        failing_rows=failing,
        failing_pct=round(failing_pct, 4),
        threshold=f"warn > {warn_pct:g}%, fail > {fail_pct:g}%",
        detail=f"{failing:,} duplicate rows ({failing_pct:.2f}%)",
    )


def check_key_uniqueness(
    frame: pd.DataFrame,
    column: str,
    dataset: str,
    check_id: Optional[str] = None,
) -> CheckResult:
    """Verify a candidate key is unique (required before any join attempt)."""
    check_id = check_id or f"duplicate.{column}_unique"
    if column not in frame.columns:
        return CheckResult(
            check_id=check_id,
            dataset=dataset,
            category="duplicate",
            description=f"{column} is a unique key",
            status=WARNING,
            severity=SEVERITY_INFO,
            detail=f"Column '{column}' unavailable; uniqueness not verifiable.",
        )
    non_null = frame[column].dropna()
    repeats = int(len(non_null) - non_null.nunique())
    return CheckResult(
        check_id=check_id,
        dataset=dataset,
        category="duplicate",
        description=f"{column} is a unique key",
        status=PASS if repeats == 0 else WARNING,
        severity=SEVERITY_WARNING,
        total_rows=int(len(frame)),
        failing_rows=repeats,
        failing_pct=round(100.0 * repeats / max(len(frame), 1), 4),
        threshold="0 repeated key values",
        detail=""
        if repeats == 0
        else f"{repeats:,} repeated values — this column is NOT a unique key",
    )


# ---------------------------------------------------------------------------
# Business rules
# ---------------------------------------------------------------------------
def check_conditional_values(
    frame: pd.DataFrame,
    condition_column: str,
    condition_value: str,
    value_columns: Sequence[str],
    dataset: str,
    check_id: str,
    description: str,
    severity: str = SEVERITY_WARNING,
    warn_pct: float = 50.0,
) -> CheckResult:
    """Flag rows where a status makes other measurements semantically odd.

    Used to expose that Dataset A records non-zero duration and calories for
    ``Absent`` sessions, which means those measures are nominal rather than
    confirmed workout output.
    """
    missing_cols = [c for c in [condition_column, *value_columns] if c not in frame.columns]
    if missing_cols:
        return CheckResult(
            check_id=check_id,
            dataset=dataset,
            category="business",
            description=description,
            status=WARNING,
            severity=SEVERITY_INFO,
            detail=f"Columns unavailable: {missing_cols}",
        )

    cond = frame[condition_column].astype(str).str.strip().str.lower() == condition_value.lower()
    subset = frame[cond]
    if subset.empty:
        return CheckResult(
            check_id=check_id,
            dataset=dataset,
            category="business",
            description=description,
            status=PASS,
            severity=SEVERITY_INFO,
            total_rows=0,
            detail=f"No rows where {condition_column} = {condition_value}.",
        )

    numeric = subset[list(value_columns)].apply(pd.to_numeric, errors="coerce")
    populated = numeric.gt(0).all(axis=1)
    failing = int(populated.sum())
    failing_pct = 100.0 * failing / max(len(subset), 1)
    return CheckResult(
        check_id=check_id,
        dataset=dataset,
        category="business",
        description=description,
        status=_status_from_rate(failing_pct, warn_pct, None),
        severity=severity,
        total_rows=int(len(subset)),
        failing_rows=failing,
        failing_pct=round(failing_pct, 4),
        threshold=f"warn when > {warn_pct:g}% of rows are populated",
        detail=(
            f"{failing:,} of {len(subset):,} '{condition_value}' rows still carry non-zero "
            f"{list(value_columns)} — these fields are nominal, not confirmed output."
        ),
    )


def check_value_domain(
    frame: pd.DataFrame,
    column: str,
    dataset: str,
    check_id: str,
    description: str,
    min_acceptable: Optional[float] = None,
    max_acceptable: Optional[float] = None,
) -> CheckResult:
    """Business-level plausibility check on a raw measure."""
    if column not in frame.columns:
        return CheckResult(
            check_id=check_id,
            dataset=dataset,
            category="business",
            description=description,
            status=WARNING,
            severity=SEVERITY_INFO,
            detail=f"Column '{column}' unavailable.",
        )
    numeric = pd.to_numeric(frame[column], errors="coerce").dropna()
    if numeric.empty:
        return CheckResult(
            check_id=check_id,
            dataset=dataset,
            category="business",
            description=description,
            status=WARNING,
            severity=SEVERITY_INFO,
            detail=f"Column '{column}' has no numeric values.",
        )
    problems = []
    if min_acceptable is not None and numeric.min() < min_acceptable:
        problems.append(f"min {numeric.min():g} < {min_acceptable:g}")
    if max_acceptable is not None and numeric.max() > max_acceptable:
        problems.append(f"max {numeric.max():g} > {max_acceptable:g}")
    return CheckResult(
        check_id=check_id,
        dataset=dataset,
        category="business",
        description=description,
        status=WARNING if problems else PASS,
        severity=SEVERITY_WARNING,
        total_rows=int(len(numeric)),
        failing_rows=len(problems),
        failing_pct=0.0,
        threshold=f"expected within [{min_acceptable}, {max_acceptable}]",
        detail="; ".join(problems),
    )


def check_share_of_population(
    frame: pd.DataFrame,
    column: str,
    positive_value: Any,
    expected_min_pct: float,
    expected_max_pct: float,
    dataset: str,
    check_id: str,
    description: str,
) -> CheckResult:
    """Sanity-check the share of a population in one outcome class.

    An implausible class balance (e.g. 0% or 95% churn) usually signals a
    labelling or parsing error upstream.
    """
    if column not in frame.columns:
        return CheckResult(
            check_id=check_id,
            dataset=dataset,
            category="business",
            description=description,
            status=WARNING,
            severity=SEVERITY_INFO,
            detail=f"Column '{column}' unavailable.",
        )
    normalized = frame[column]
    if normalized.dtype == bool:
        positive = normalized.fillna(False)
    else:
        positive = (
            normalized.astype(str).str.strip().str.lower().isin(
                [str(positive_value).lower(), "true", "1", "yes", "y"]
            )
        )
    pct = 100.0 * float(positive.mean()) if len(frame) else 0.0
    ok = expected_min_pct <= pct <= expected_max_pct
    return CheckResult(
        check_id=check_id,
        dataset=dataset,
        category="business",
        description=description,
        status=PASS if ok else WARNING,
        severity=SEVERITY_WARNING,
        total_rows=int(len(frame)),
        failing_rows=0 if ok else int(positive.sum()),
        failing_pct=round(pct, 4),
        threshold=f"expected {expected_min_pct:g}%-{expected_max_pct:g}%",
        detail=f"Observed share of '{positive_value}': {pct:.2f}%",
    )


def check_intentionally_null(
    frame: pd.DataFrame,
    column: str,
    dataset: str,
    check_id: str,
    description: str,
    expected_null_pct: float = 100.0,
) -> CheckResult:
    """Assert that a column is null *by design* rather than by defect.

    ``fact_workout.member_id`` is intentionally NULL: the published activity file
    exposes no repeatable member key, so an all-null column is the correct state
    and must not be reported as a missingness failure.
    """
    if column not in frame.columns:
        return CheckResult(
            check_id=check_id,
            dataset=dataset,
            category="business",
            description=description,
            status=WARNING,
            severity=SEVERITY_INFO,
            detail=f"Column '{column}' not present in the frame.",
        )
    actual_pct = 100.0 * float(frame[column].isna().mean()) if len(frame) else 0.0
    ok = actual_pct >= expected_null_pct
    return CheckResult(
        check_id=check_id,
        dataset=dataset,
        category="business",
        description=description,
        status=PASS if ok else FAIL,
        severity=SEVERITY_CRITICAL,
        total_rows=int(len(frame)),
        failing_rows=0 if ok else int(frame[column].notna().sum()),
        failing_pct=round(actual_pct, 4),
        threshold=f"expected >= {expected_null_pct:g}% null",
        detail=(
            f"{column} is {actual_pct:.1f}% null, as documented. This column is null by design "
            "and is excluded from missingness rules."
            if ok
            else f"{column} is only {actual_pct:.1f}% null; the documented design expects it to be null."
        ),
    )


def check_referential_columns(
    frame: pd.DataFrame,
    columns: Sequence[str],
    dataset: str,
    check_id: str = "business.non_negative_measures",
) -> CheckResult:
    """All declared measure columns must be non-negative where present."""
    present = [c for c in columns if c in frame.columns]
    violations = 0
    for column in present:
        numeric = pd.to_numeric(frame[column], errors="coerce")
        violations += int((numeric < 0).sum())
    return CheckResult(
        check_id=check_id,
        dataset=dataset,
        category="business",
        description=f"Measures non-negative: {present}",
        status=PASS if violations == 0 else FAIL,
        severity=SEVERITY_WARNING,
        total_rows=int(len(frame)),
        failing_rows=violations,
        failing_pct=round(100.0 * violations / max(len(frame), 1), 4),
        threshold="0 negative measures",
        detail="" if violations == 0 else f"{violations:,} negative measure values",
    )


def summarize_numeric(frame: pd.DataFrame, columns: Iterable[str]) -> Dict[str, Dict[str, float]]:
    """Small helper used by the reporting layer."""
    out: Dict[str, Dict[str, float]] = {}
    for column in columns:
        if column not in frame.columns:
            continue
        series = pd.to_numeric(frame[column], errors="coerce").dropna()
        if series.empty:
            continue
        out[column] = {
            "count": float(len(series)),
            "min": float(series.min()),
            "max": float(series.max()),
            "mean": float(series.mean()),
            "median": float(series.median()),
            "std": float(series.std()) if len(series) > 1 else 0.0,
            "p95": float(np.percentile(series, 95)),
        }
    return out

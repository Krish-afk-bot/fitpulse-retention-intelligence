"""Python ↔ SQL KPI cross-validation.

For every critical KPI the Python analytics layer and the SQL layer are computed
independently and compared against a declared tolerance. The output is the
validation table the PRD requires::

    RetenSPontion Rate
    Python: 74.21%
    SQL:    74.21%
    Diff:    0.00%
    Status:  PASS

Tolerances are explicit per KPI. Counts require exact agreement (tolerance 0);
rates and averages allow a small numerical tolerance, which is stated rather
than implied.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from ..common.logging_utils import get_logger
from .database import read_script, run_query

logger = get_logger("sql_layer.crosscheck")

STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"
STATUS_WARNING = "WARNING"
STATUS_NA = "NOT_APPLICABLE"


@dataclass(frozen=True)
class KpiComparisonSpec:
    """Maps one Python KPI onto its SQL validation query."""

    key: str
    label: str
    query: str
    tolerance: float
    unit: str = ""
    note: str = ""


#: The cross-validation contract. Tolerance is absolute on the metric's own scale.
KPI_COMPARISONS: Tuple[KpiComparisonSpec, ...] = (
    KpiComparisonSpec("total_members", "Total Members", "val_total_members", 0.0, "members"),
    KpiComparisonSpec("retained_members", "Retained Members", "val_retained_members", 0.0, "members"),
    KpiComparisonSpec("churned_members", "Churned Members", "val_churned_members", 0.0, "members"),
    KpiComparisonSpec("retention_rate", "Retention Rate", "val_retention_rate", 0.01, "%"),
    KpiComparisonSpec("churn_rate", "Churn Rate", "val_churn_rate", 0.01, "%"),
    KpiComparisonSpec("avg_visits_per_month", "Average Visits / Month", "val_avg_visits_per_month", 1e-4, "visits"),
    KpiComparisonSpec("avg_workout_duration", "Average Workout Duration", "val_avg_workout_duration", 1e-4, "minutes"),
    KpiComparisonSpec("avg_engagement_score", "Average Engagement Score", "val_avg_engagement_score", 0.01, "score"),
    KpiComparisonSpec("avg_longest_streak", "Average Longest Streak", "val_avg_longest_streak", 0.01, "days"),
    KpiComparisonSpec("at_risk_members", "At-Risk Members", "val_at_risk_members", 0.0, "members"),
    KpiComparisonSpec("churned_avg_visits", "Churned — avg visits/month", "val_churned_avg_visits", 1e-4, "visits"),
    KpiComparisonSpec("retained_avg_visits", "Retained — avg visits/month", "val_retained_avg_visits", 1e-4, "visits"),
    KpiComparisonSpec("churned_avg_duration", "Churned — avg duration", "val_churned_avg_duration", 1e-4, "minutes"),
    KpiComparisonSpec("retained_avg_duration", "Retained — avg duration", "val_retained_avg_duration", 1e-4, "minutes"),
    KpiComparisonSpec("churned_avg_recency", "Churned — avg recency", "val_churned_avg_recency", 1e-4, "days"),
    KpiComparisonSpec("retained_avg_recency", "Retained — avg recency", "val_retained_avg_recency", 1e-4, "days"),
    KpiComparisonSpec("platform_events", "Recorded Sessions", "val_platform_events", 0.0, "sessions"),
    KpiComparisonSpec("platform_attended_sessions", "Attended Sessions", "val_platform_attended", 0.0, "sessions"),
    KpiComparisonSpec("platform_attendance_rate", "Platform Attendance Rate", "val_platform_attendance_rate", 0.01, "%"),
    KpiComparisonSpec("platform_active_days", "Active Days", "val_platform_active_days", 0.0, "days"),
    KpiComparisonSpec("platform_longest_active_streak", "Longest Active Streak", "val_platform_longest_streak", 0.0, "days"),
    KpiComparisonSpec("synthetic_events", "Synthetic Events", "val_synthetic_events", 0.0, "events"),
)


def _difference(python_value: float, sql_value: float) -> float:
    return round(float(sql_value) - float(python_value), 9)


def _status(difference: float, tolerance: float) -> str:
    if abs(difference) <= tolerance:
        return STATUS_PASS
    return STATUS_FAIL


def compare_kpis(
    connection: sqlite3.Connection,
    python_kpis: Dict[str, Any],
    specs: Sequence[KpiComparisonSpec] = KPI_COMPARISONS,
    validation_script: Optional[str] = None,
) -> pd.DataFrame:
    """Compare every declared KPI between Python and SQL."""
    rows: List[Dict[str, Any]] = []

    for spec in specs:
        python_value = python_kpis.get(spec.key)
        try:
            sql_result = run_query(connection, f"SELECT * FROM ({_query_for(spec.query, validation_script)})")
            sql_value = float(sql_result.iloc[0, 0]) if not sql_result.empty and pd.notna(sql_result.iloc[0, 0]) else None
        except Exception as exc:  # noqa: BLE001 - reported as a failure row
            rows.append(
                {
                    "kpi": spec.label,
                    "unit": spec.unit,
                    "python_value": python_value,
                    "sql_value": None,
                    "difference": None,
                    "tolerance": spec.tolerance,
                    "status": STATUS_FAIL,
                    "note": f"SQL query '{spec.query}' failed: {exc}",
                }
            )
            continue

        if python_value is None or sql_value is None:
            rows.append(
                {
                    "kpi": spec.label,
                    "unit": spec.unit,
                    "python_value": python_value,
                    "sql_value": sql_value,
                    "difference": None,
                    "tolerance": spec.tolerance,
                    "status": STATUS_NA,
                    "note": "Value unavailable on one side; comparison not applicable.",
                }
            )
            continue

        difference = _difference(float(python_value), sql_value)
        rows.append(
            {
                "kpi": spec.label,
                "unit": spec.unit,
                "python_value": round(float(python_value), 6),
                "sql_value": round(float(sql_value), 6),
                "difference": difference,
                "tolerance": spec.tolerance,
                "status": _status(difference, spec.tolerance),
                "note": spec.note,
            }
        )

    frame = pd.DataFrame(rows)
    frame["abs_difference"] = frame["difference"].abs()
    logger.info(
        "KPI cross-validation: %s/%s PASS",
        int((frame["status"] == STATUS_PASS).sum()),
        len(frame),
    )
    return frame


_QUERY_CACHE: Dict[str, str] = {}


def _query_for(name: str, validation_script: Optional[str] = None) -> str:
    """Resolve a validation query by name from ``sql/validation.sql``."""
    from .database import parse_named_queries  # local import avoids a cycle

    if not _QUERY_CACHE:
        script = validation_script
        if script is None:
            from ..common.config import SQL_DIR

            script = read_script(SQL_DIR / "validation.sql")
        _QUERY_CACHE.update(parse_named_queries(script))
    if name not in _QUERY_CACHE:
        raise KeyError(f"Unknown validation query '{name}'")
    return _QUERY_CACHE[name]


def compare_tables(
    python_table: pd.DataFrame,
    sql_table: pd.DataFrame,
    key_columns: Sequence[str],
    columns: Dict[str, str],
    tolerance: float = 1e-4,
    label: str = "table",
) -> pd.DataFrame:
    """Row-wise comparison of a Python table against its SQL equivalent.

    Parameters
    ----------
    columns:
        ``{python_column: sql_column}`` pairs to compare. The two layers use
        slightly different column names (``events`` vs ``sessions``,
        ``churn_rate`` vs ``churn_rate_pct``), so the mapping is explicit rather
        than inferred — an unpaired column would otherwise look like a silent pass.
    """
    if python_table is None or python_table.empty or sql_table is None or sql_table.empty:
        return pd.DataFrame(
            [
                {
                    "comparison": label,
                    "key": "n/a",
                    "column": "n/a",
                    "python_value": None,
                    "sql_value": None,
                    "difference": None,
                    "tolerance": tolerance,
                    "status": STATUS_NA,
                    "detail": "One side is empty; comparison not applicable.",
                }
            ]
        )

    left = python_table.copy()
    right = sql_table.copy()
    left["_key"] = left[list(key_columns)].astype(str).agg(" | ".join, axis=1)
    right["_key"] = right[list(key_columns)].astype(str).agg(" | ".join, axis=1)

    rename_left = {py: f"{py}__py" for py in columns if py in left.columns}
    rename_right = {sql: f"{sql}__sql" for sql in columns.values() if sql in right.columns}
    left = left.rename(columns=rename_left)
    right = right.rename(columns=rename_right)

    merged = left.merge(right, on="_key", how="outer")

    rows: List[Dict[str, Any]] = []
    for key, group in merged.groupby("_key", dropna=False):
        for python_column, sql_column in columns.items():
            py_series = group.get(f"{python_column}__py", pd.Series([None], index=group.index))
            sql_series = group.get(f"{sql_column}__sql", pd.Series([None], index=group.index))
            py_value = py_series.iloc[0] if len(py_series) else None
            sql_value = sql_series.iloc[0] if len(sql_series) else None

            if py_value is None or sql_value is None or pd.isna(py_value) or pd.isna(sql_value):
                status, difference = STATUS_NA, None
                detail = (
                    f"Both layers must expose '{python_column}' / '{sql_column}' for a comparison."
                )
            else:
                difference = round(float(sql_value) - float(py_value), 9)
                status = STATUS_PASS if abs(difference) <= tolerance else STATUS_FAIL
                detail = ""
            rows.append(
                {
                    "comparison": label,
                    "key": key,
                    "column": f"{python_column} / {sql_column}",
                    "python_value": py_value,
                    "sql_value": sql_value,
                    "difference": difference,
                    "tolerance": tolerance,
                    "status": status,
                    "detail": detail,
                }
            )
    return pd.DataFrame(rows)


def integrity_checks(connection: sqlite3.Connection) -> pd.DataFrame:
    """Structural checks that must hold for any trustworthy load."""
    checks = [
        ("Member key uniqueness", "duplicate.member_id", "val_key_uniqueness_members", 0),
        ("Workout key uniqueness", "duplicate.workout_id", "val_key_uniqueness_workouts", 0),
        ("Membership → member referential integrity", "referential.membership_dim", "val_referential_integrity", 0),
        ("Activity rows joinable to members (expected 0%)", "integration.activity_joinability", "val_activity_member_joinability", 0.0),
        ("Segment assignment matches thresholds", "derived.segment_rule", "val_segment_assignment_mismatch", 0),
        ("Engagement score within 0-100", "derived.score_bounds", "val_engagement_score_bounds", 0),
        ("No negative measures", "numeric.non_negative", "val_negative_measures", 0),
        ("High-severity alerts (informational)", "alerts.high_severity", "val_alerts_high", -1),
    ]
    rows: List[Dict[str, Any]] = []
    for label, check_id, query, expected in checks:
        if expected == -1:
            # Informational counters (open alerts) are reported, not asserted.
            try:
                value = run_query(connection, f"SELECT * FROM ({_query_for(query)})").iloc[0, 0]
                value = float(value) if value is not None and pd.notna(value) else 0.0
            except Exception as exc:  # noqa: BLE001
                rows.append(
                    {
                        "check": label,
                        "check_id": check_id,
                        "observed": None,
                        "expected": "informational",
                        "status": STATUS_FAIL,
                        "detail": str(exc),
                    }
                )
                continue
            rows.append(
                {
                    "check": label,
                    "check_id": check_id,
                    "observed": value,
                    "expected": "informational",
                    "status": STATUS_NA,
                    "detail": "Open alerts are reported for context and are not a data defect.",
                }
            )
            continue
        try:
            value = run_query(connection, f"SELECT * FROM ({_query_for(query)})").iloc[0, 0]
            value = float(value) if value is not None and pd.notna(value) else 0.0
        except Exception as exc:  # noqa: BLE001
            rows.append(
                {
                    "check": label,
                    "check_id": check_id,
                    "observed": None,
                    "expected": expected,
                    "status": STATUS_FAIL,
                    "detail": str(exc),
                }
            )
            continue
        rows.append(
            {
                "check": label,
                "check_id": check_id,
                "observed": value,
                "expected": expected,
                "status": STATUS_PASS if value == float(expected) else STATUS_FAIL,
                "detail": "" if value == float(expected) else f"Expected {expected}, observed {value}",
            }
        )
    return pd.DataFrame(rows)


def validation_summary(crosscheck: pd.DataFrame, integrity: pd.DataFrame) -> Dict[str, Any]:
    """Aggregate validation status for dashboards and reports.

    A validation stage that never ran (for example when a single dataset was
    loaded and there was nothing to cross-validate) is reported as
    ``NOT_APPLICABLE`` rather than PASS — an unrun check is not a passed check.
    """
    crosscheck = crosscheck if crosscheck is not None else pd.DataFrame()
    has_status = "status" in crosscheck.columns
    total = len(crosscheck)
    passed = int((crosscheck["status"] == STATUS_PASS).sum()) if has_status else 0
    failed = int((crosscheck["status"] == STATUS_FAIL).sum()) if has_status else 0
    na = int((crosscheck["status"] == STATUS_NA).sum()) if has_status else 0
    integrity_failed = (
        int((integrity["status"] == STATUS_FAIL).sum())
        if integrity is not None and not integrity.empty and "status" in integrity.columns
        else 0
    )
    integrity_not_applicable = (
        int((integrity["status"] == STATUS_NA).sum())
        if integrity is not None and not integrity.empty and "status" in integrity.columns
        else 0
    )
    worst = 0.0
    if failed and "abs_difference" in crosscheck.columns:
        observed = crosscheck.loc[crosscheck["status"] == STATUS_FAIL, "abs_difference"].max()
        worst = float(observed) if pd.notna(observed) else 0.0

    integrity_checks = 0 if integrity is None else len(integrity)
    stage_ran = total > 0 or integrity_checks > 0
    if not stage_ran:
        status = STATUS_NA
    elif failed == 0 and integrity_failed == 0:
        status = STATUS_PASS
    else:
        status = STATUS_FAIL

    return {
        "kpi_checks": total,
        "kpi_passed": passed,
        "kpi_failed": failed,
        "kpi_not_applicable": na,
        "max_difference": None if not failed else round(worst, 6),
        "integrity_checks": integrity_checks,
        "integrity_failed": integrity_failed,
        "integrity_informational": integrity_not_applicable,
        "status": status,
        "ran": stage_ran,
        "tolerance_policy": (
            "Counts require exact agreement; rates and averages use the per-KPI absolute "
            "tolerance declared in crosscheck.KPI_COMPARISONS."
        ),
    }

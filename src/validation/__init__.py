"""Validation: profiling, rule-based checks, Python<->SQL KPI cross-checks."""

from .results import (
    PASS,
    WARNING,
    FAIL,
    CheckResult,
    ValidationReport,
    combine_reports,
    worst_status,
)
from .profiler import (
    profile_columns,
    profile_frame,
    profile_report_markdown,
    profile_summary_frame,
    duplicate_summary,
)
from .validator import (
    validate_activity_source,
    validate_membership_source,
    validate_canonical_fact_workout,
    validate_canonical_membership,
    validate_loaded_sources,
    validate_no_data,
    summarize_quality,
)

__all__ = [
    "PASS",
    "WARNING",
    "FAIL",
    "CheckResult",
    "ValidationReport",
    "combine_reports",
    "worst_status",
    "profile_columns",
    "profile_frame",
    "profile_report_markdown",
    "profile_summary_frame",
    "duplicate_summary",
    "validate_activity_source",
    "validate_membership_source",
    "validate_canonical_fact_workout",
    "validate_canonical_membership",
    "validate_loaded_sources",
    "validate_no_data",
    "summarize_quality",
]

"""Structured validation result containers.

The PRD requires validation to return a structured payload shaped like::

    {
        "status": "PASS",
        "checks": [...],
        "warnings": [...],
        "errors": [...]
    }

:class:`ValidationReport` provides exactly that, plus row-level accounting so
every finding can be traced back to the source file.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

PASS = "PASS"
WARNING = "WARNING"
FAIL = "FAIL"

SEVERITY_INFO = "info"
SEVERITY_WARNING = "warning"
SEVERITY_CRITICAL = "critical"

_STATUS_RANK = {PASS: 0, WARNING: 1, FAIL: 2}


@dataclass
class CheckResult:
    """Outcome of a single validation rule."""

    check_id: str
    dataset: str
    category: str
    description: str
    status: str = PASS
    severity: str = SEVERITY_WARNING
    total_rows: int = 0
    failing_rows: int = 0
    failing_pct: float = 0.0
    threshold: str = ""
    detail: str = ""
    examples: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @property
    def passed(self) -> bool:
        return self.status == PASS


@dataclass
class ValidationReport:
    """Aggregated validation output for one or more datasets."""

    dataset: str
    checks: List[CheckResult] = field(default_factory=list)

    def add(self, check: CheckResult) -> "ValidationReport":
        self.checks.append(check)
        return self

    def extend(self, checks: List[CheckResult]) -> "ValidationReport":
        self.checks.extend(checks)
        return self

    def merge(self, other: "ValidationReport") -> "ValidationReport":
        self.checks.extend(other.checks)
        return self

    # -- derived views ----------------------------------------------------
    @property
    def warnings(self) -> List[CheckResult]:
        return [c for c in self.checks if c.status == WARNING]

    @property
    def errors(self) -> List[CheckResult]:
        return [c for c in self.checks if c.status == FAIL]

    @property
    def status(self) -> str:
        if any(c.status == FAIL for c in self.checks):
            return FAIL
        if any(c.status == WARNING for c in self.checks):
            return WARNING
        return PASS

    def by_category(self) -> Dict[str, str]:
        """Worst status per category — used by the Data Quality dashboard."""
        summary: Dict[str, str] = {}
        for check in self.checks:
            current = summary.get(check.category, PASS)
            summary[check.category] = (
                check.status
                if _STATUS_RANK[check.status] > _STATUS_RANK[current]
                else current
            )
        return summary

    def to_frame(self):
        import pandas as pd

        if not self.checks:
            return pd.DataFrame(
                columns=[
                    "check_id",
                    "dataset",
                    "category",
                    "description",
                    "status",
                    "severity",
                    "total_rows",
                    "failing_rows",
                    "failing_pct",
                    "threshold",
                    "detail",
                ]
            )
        return pd.DataFrame([c.as_dict() for c in self.checks])[
            [
                "check_id",
                "dataset",
                "category",
                "description",
                "status",
                "severity",
                "total_rows",
                "failing_rows",
                "failing_pct",
                "threshold",
                "detail",
            ]
        ]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "dataset": self.dataset,
            "status": self.status,
            "checks": [c.as_dict() for c in self.checks],
            "warnings": [c.as_dict() for c in self.warnings],
            "errors": [c.as_dict() for c in self.errors],
            "summary_by_category": self.by_category(),
            "totals": {
                "checks": len(self.checks),
                "passed": sum(1 for c in self.checks if c.status == PASS),
                "warnings": len(self.warnings),
                "errors": len(self.errors),
            },
        }

    def human_summary(self) -> str:
        lines = [f"{self.dataset}: {self.status}"]
        for check in self.checks:
            mark = {PASS: "[PASS]", WARNING: "[WARN]", FAIL: "[FAIL]"}[check.status]
            detail = f" ({check.failing_rows:,}/{check.total_rows:,} rows)" if check.total_rows else ""
            lines.append(f"  {mark} {check.category:<9} {check.check_id:<28} {check.description}{detail}")
        return "\n".join(lines)


def combine_reports(*reports: ValidationReport, dataset: str = "all") -> ValidationReport:
    """Merge multiple reports into one for cross-dataset validation."""
    merged = ValidationReport(dataset=dataset)
    for report in reports:
        merged.extend(report.checks)
    return merged


def worst_status(*statuses: Optional[str]) -> str:
    ranked = [s for s in statuses if s]
    if not ranked:
        return PASS
    return max(ranked, key=lambda s: _STATUS_RANK.get(s, 0))

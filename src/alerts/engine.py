"""Threshold-driven alert engine.

Every alert states: the metric, the observed value, the threshold it crossed,
the severity, the affected population and size, when it was evaluated, an
explanation of *why* it fired, and a caveat where the underlying field is weak.

Thresholds are configuration, not hard-coded logic: they come from
:class:`src.common.config.AlertThresholds` and can be overridden from the
environment or the dashboard.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence

import numpy as np
import pandas as pd

from ..common.config import AlertThresholds, get_settings
from ..common.logging_utils import get_logger

logger = get_logger("alerts")

SEVERITY_HIGH = "HIGH"
SEVERITY_MEDIUM = "MEDIUM"
SEVERITY_LOW = "LOW"
SEVERITY_INFO = "INFO"

SEVERITY_BUCKET = {
    SEVERITY_HIGH: 0,
    SEVERITY_MEDIUM: 1,
    SEVERITY_LOW: 2,
    SEVERITY_INFO: 3,
}


@dataclass
class Alert:
    """One evaluated alert."""

    alert_id: str
    category: str
    metric: str
    observed_value: float
    observed_display: str
    threshold_value: float
    threshold_display: str
    comparison: str
    severity: str
    severity_bucket: int
    affected_population: str
    affected_count: Optional[int]
    triggered_at: str
    explanation: str
    caveat: str = ""
    data_source: str = ""
    recommended_action: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _severity_ratio(observed: float, threshold: float, higher_is_worse: bool = True) -> str:
    """Map how far a metric exceeds its threshold onto a severity level."""
    if threshold in (0, None) or (isinstance(threshold, float) and np.isnan(threshold)):
        return SEVERITY_MEDIUM
    ratio = observed / threshold if higher_is_worse else threshold / observed if observed else np.inf
    if ratio >= 1.5:
        return SEVERITY_HIGH
    if ratio >= 1.0:
        return SEVERITY_MEDIUM
    if ratio >= 0.8:
        return SEVERITY_LOW
    return SEVERITY_INFO


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Individual evaluators
# ---------------------------------------------------------------------------
def evaluate_inactivity_alert(
    members: pd.DataFrame, thresholds: AlertThresholds
) -> List[Alert]:
    """Membership recency beyond the configured inactivity window."""
    if members is None or members.empty or "recency_days" not in members.columns:
        return []
    recency = pd.to_numeric(members["recency_days"], errors="coerce")
    affected_mask = recency > thresholds.inactivity_days
    affected = int(affected_mask.sum())
    total = int(recency.notna().sum())
    share = 100.0 * affected / total if total else 0.0
    if affected == 0:
        return []

    severity = _severity_ratio(share, 20.0)
    return [
        Alert(
            alert_id="inactivity_threshold",
            category="Retention risk",
            metric="Members inactive beyond threshold",
            observed_value=float(affected),
            observed_display=f"{affected:,} members ({share:.1f}% of the base)",
            threshold_value=float(thresholds.inactivity_days),
            threshold_display=f"> {thresholds.inactivity_days} days since last visit",
            comparison="exceeds",
            severity=severity,
            severity_bucket=SEVERITY_BUCKET[severity],
            affected_population="Members whose last recorded visit predates the inactivity window",
            affected_count=affected,
            triggered_at=_now(),
            explanation=(
                f"{affected:,} of {total:,} members last visited more than "
                f"{thresholds.inactivity_days} days before the observation date "
                f"(median recency {recency.median():,.0f} days)."
            ),
            caveat=(
                "The membership source's last-visit dates span 0 to over 1,200 days and show no "
                "association with the churn label, so this alert is dominated by how that field "
                "was generated rather than by genuine disengagement. It is reported for "
                "completeness and should be re-baselined once a live activity feed is connected."
            ),
            data_source="membership.last_visit_date (real)",
            recommended_action=(
                "Treat as a data-contract item: confirm whether last-visit dates are maintained "
                "for all members before acting on this population."
            ),
        )
    ]


def evaluate_churn_rate_alert(
    members: pd.DataFrame, thresholds: AlertThresholds
) -> List[Alert]:
    """Overall churn rate against the configured ceiling."""
    if members is None or members.empty or "is_churned" not in members.columns:
        return []
    total = int(len(members))
    churned = int(members["is_churned"].astype(bool).sum())
    rate = 100.0 * churned / total if total else 0.0
    if rate <= thresholds.churn_rate_pct:
        return []
    severity = _severity_ratio(rate, thresholds.churn_rate_pct)
    return [
        Alert(
            alert_id="churn_rate_ceiling",
            category="Retention risk",
            metric="Churn rate",
            observed_value=round(rate, 4),
            observed_display=f"{rate:.2f}% ({churned}/{total} members)",
            threshold_value=float(thresholds.churn_rate_pct),
            threshold_display=f"> {thresholds.churn_rate_pct:.0f}%",
            comparison="exceeds",
            severity=severity,
            severity_bucket=SEVERITY_BUCKET[severity],
            affected_population="All members in the membership source",
            affected_count=churned,
            triggered_at=_now(),
            explanation=(
                f"Observed churn is {rate:.2f}%, above the configured {thresholds.churn_rate_pct:.0f}% "
                f"ceiling, based on the source churn label."
            ),
            caveat=(
                f"The membership sample holds {total} members, so the 95% confidence interval "
                "around this rate is wide."
            ),
            data_source="membership.churn_status (real)",
            recommended_action=(
                "Prioritise the highest-churn behavioural segment and membership tier for retention "
                "experiments, and confirm the label definition with the data owner."
            ),
        )
    ]


def evaluate_segment_churn_alerts(
    segment_metrics: pd.DataFrame, thresholds: AlertThresholds
) -> List[Alert]:
    """Segment-level churn above the ceiling."""
    if segment_metrics is None or segment_metrics.empty:
        return []
    alerts: List[Alert] = []
    for row in segment_metrics.itertuples():
        if getattr(row, "members", 0) == 0:
            continue
        rate = float(getattr(row, "churn_rate", 0.0))
        if rate <= thresholds.churn_rate_pct:
            continue
        severity = _severity_ratio(rate, thresholds.churn_rate_pct)
        alerts.append(
            Alert(
                alert_id=f"segment_churn::{getattr(row, 'segment')}",
                category="Retention risk",
                metric=f"Churn rate — {getattr(row, 'segment')}",
                observed_value=round(rate, 4),
                observed_display=f"{rate:.2f}% ({int(getattr(row, 'churned', 0))}/{int(getattr(row, 'members', 0))} members)",
                threshold_value=float(thresholds.churn_rate_pct),
                threshold_display=f"> {thresholds.churn_rate_pct:.0f}%",
                comparison="exceeds",
                severity=severity,
                severity_bucket=SEVERITY_BUCKET[severity],
                affected_population=f"{getattr(row, 'segment')} segment",
                affected_count=int(getattr(row, "members", 0)),
                triggered_at=_now(),
                explanation=(
                    f"The {getattr(row, 'segment')} segment churns at {rate:.2f}%, above the "
                    f"{thresholds.churn_rate_pct:.0f}% ceiling."
                ),
                caveat=(
                    "Segment membership depends on the configurable engagement weights and on "
                    "synthetic date placement for consistency and streak components."
                ),
                data_source="membership.churn_status (real) + derived segment",
                recommended_action="Review the segment's frequency and recency components before acting.",
            )
        )
    return alerts


def evaluate_engagement_drop_alert(
    platform_monthly: pd.DataFrame, thresholds: AlertThresholds
) -> List[Alert]:
    """Engagement (session volume) decline against a rolling baseline."""
    if platform_monthly is None or platform_monthly.empty or len(platform_monthly) < 4:
        return []
    frame = platform_monthly.sort_values("month")
    latest = float(frame["events"].iloc[-1])
    baseline = float(frame["events"].iloc[-4:-1].mean())
    if baseline <= 0:
        return []
    drop_pct = 100.0 * (baseline - latest) / baseline
    if drop_pct < thresholds.engagement_drop_pct:
        return []
    severity = _severity_ratio(drop_pct, thresholds.engagement_drop_pct)
    return [
        Alert(
            alert_id="engagement_drop",
            category="Engagement",
            metric="Monthly session volume decline",
            observed_value=round(drop_pct, 4),
            observed_display=f"-{drop_pct:.1f}% vs the prior 3-month baseline",
            threshold_value=float(thresholds.engagement_drop_pct),
            threshold_display=f"> {thresholds.engagement_drop_pct:.0f}% decline",
            comparison="exceeds",
            severity=severity,
            severity_bucket=SEVERITY_BUCKET[severity],
            affected_population=f"Organisation-wide activity volume ({frame['month'].iloc[-1]})",
            affected_count=int(latest),
            triggered_at=_now(),
            explanation=(
                f"Sessions in {frame['month'].iloc[-1]} were {latest:,.0f} versus a prior "
                f"3-month average of {baseline:,.0f} ({drop_pct:+.1f}%)."
            ),
            caveat=(
                "The activity source covers one calendar year with no member identifiers, so a "
                "volume drop cannot be attributed to specific members or cohorts."
            ),
            data_source="activity.visit_date (real)",
            recommended_action="Check seasonality and intake before treating this as an engagement failure.",
        )
    ]


def evaluate_activity_drop_alert(
    platform_daily: pd.DataFrame, thresholds: AlertThresholds
) -> List[Alert]:
    """Recent 7-day volume versus the 28-day baseline."""
    if platform_daily is None or platform_daily.empty or len(platform_daily) < 35:
        return []
    frame = platform_daily.sort_values("activity_date")
    recent = float(frame["events"].tail(7).mean())
    baseline = float(frame["events"].tail(35).head(28).mean())
    if baseline <= 0:
        return []
    drop_pct = 100.0 * (baseline - recent) / baseline
    if drop_pct < thresholds.activity_drop_pct:
        return []
    severity = _severity_ratio(drop_pct, thresholds.activity_drop_pct)
    return [
        Alert(
            alert_id="activity_drop_7d",
            category="Engagement",
            metric="7-day session volume vs 28-day baseline",
            observed_value=round(drop_pct, 4),
            observed_display=f"-{drop_pct:.1f}% (7-day mean {recent:.1f} vs baseline {baseline:.1f})",
            threshold_value=float(thresholds.activity_drop_pct),
            threshold_display=f"> {thresholds.activity_drop_pct:.0f}% decline",
            comparison="exceeds",
            severity=severity,
            severity_bucket=SEVERITY_BUCKET[severity],
            affected_population="Platform activity in the most recent 7 days",
            affected_count=int(recent),
            triggered_at=_now(),
            explanation=(
                f"The most recent 7 days averaged {recent:.1f} sessions per day versus a "
                f"{baseline:.1f} baseline, a {drop_pct:.1f}% decline."
            ),
            caveat="Single-year data cannot separate trend from seasonal effects.",
            data_source="activity.visit_date (real)",
            recommended_action="Compare against the same period in a prior year once more history is available.",
        )
    ]


#: Columns that are never carried downstream, so their missingness is not an
#: operational risk. Direct identifiers are dropped during cleaning, and
#: ``member_id`` in the activity fact is null by documented design.
ALERT_EXEMPT_MISSING_COLUMNS = {
    "name",
    "address",
    "phone_number",
    "email",
    "member_id",
}


def evaluate_missing_data_alert(
    validation_reports: Sequence[Any], thresholds: AlertThresholds, dataset: str = "uploaded data"
) -> List[Alert]:
    """Columns whose null rate exceeds the configured missingness ceiling.

    Columns that are dropped as personal identifiers, or that are null by
    documented design, are excluded: alerting on them would be noise.
    """
    alerts: List[Alert] = []
    for report in validation_reports or []:
        for check in getattr(report, "checks", []):
            if check.category != "missing":
                continue
            if check.failing_pct <= thresholds.missing_data_pct:
                continue
            column = check.check_id.split(".")[-1]
            if column.strip().lower() in ALERT_EXEMPT_MISSING_COLUMNS:
                continue
            severity = _severity_ratio(check.failing_pct, thresholds.missing_data_pct)
            alerts.append(
                Alert(
                    alert_id=f"missing_data::{check.dataset}::{column}",
                    category="Data quality",
                    metric=f"Missing values — {column}",
                    observed_value=round(check.failing_pct, 4),
                    observed_display=f"{check.failing_pct:.2f}% missing ({check.failing_rows:,} rows)",
                    threshold_value=float(thresholds.missing_data_pct),
                    threshold_display=f"> {thresholds.missing_data_pct:.0f}% missing",
                    comparison="exceeds",
                    severity=severity,
                    severity_bucket=SEVERITY_BUCKET[severity],
                    affected_population=f"{check.dataset} / column {column}",
                    affected_count=int(check.failing_rows),
                    triggered_at=_now(),
                    explanation=(
                        f"{check.failing_rows:,} values ({check.failing_pct:.2f}%) are null, above the "
                        f"{thresholds.missing_data_pct:.0f}% ceiling. Rows were retained and flagged "
                        "rather than deleted."
                    ),
                    caveat=(
                        "Missingness is handled per column semantics: numeric measures are "
                        "median-imputed with an explicit imputation flag; dates are flagged and "
                        "excluded from date-dependent metrics only."
                    ),
                    data_source=check.dataset,
                    recommended_action="Confirm with the data owner whether the gap is systematic.",
                )
            )
    return alerts


def evaluate_data_quality_alerts(
    validation_reports: Sequence[Any],
) -> List[Alert]:
    """Any validation check that failed outright."""
    alerts: List[Alert] = []
    for report in validation_reports or []:
        for check in getattr(report, "checks", []):
            if check.status != "FAIL":
                continue
            alerts.append(
                Alert(
                    alert_id=f"validation_fail::{check.check_id}",
                    category="Data quality",
                    metric=f"Validation FAIL — {check.description}",
                    observed_value=float(check.failing_rows),
                    observed_display=f"{check.failing_rows:,} failing rows",
                    threshold_value=float(check.failing_rows),
                    threshold_display=check.threshold or "rule violated",
                    comparison="violates",
                    severity=SEVERITY_HIGH,
                    severity_bucket=SEVERITY_BUCKET[SEVERITY_HIGH],
                    affected_population=f"{check.dataset} ({check.category})",
                    affected_count=int(check.failing_rows),
                    triggered_at=_now(),
                    explanation=check.detail or "A hard validation rule failed.",
                    caveat="Failing rows are retained and flagged, never silently dropped.",
                    data_source=check.dataset,
                    recommended_action="Resolve the source-data contract before trusting downstream KPIs.",
                )
            )
    return alerts


def evaluate_confirmed_volume_alert(fact_workout: pd.DataFrame) -> List[Alert]:
    """Data-semantics alert: nominal vs confirmed workout volume."""
    if fact_workout is None or fact_workout.empty:
        return []
    total = float(pd.to_numeric(fact_workout["duration_minutes"], errors="coerce").sum())
    confirmed = float(pd.to_numeric(fact_workout["confirmed_duration_minutes"], errors="coerce").sum())
    if total <= 0:
        return []
    collapsed = 100.0 * (total - confirmed) / total
    absent = int((~fact_workout["is_present"].astype(bool)).sum())
    return [
        Alert(
            alert_id="nominal_vs_confirmed_volume",
            category="Data semantics",
            metric="Recorded minutes not backed by attendance",
            observed_value=round(collapsed, 4),
            observed_display=f"{collapsed:.1f}% of recorded minutes ({absent:,} absent sessions)",
            threshold_value=10.0,
            threshold_display="> 10% nominal-only volume",
            comparison="exceeds",
            severity=SEVERITY_MEDIUM,
            severity_bucket=SEVERITY_BUCKET[SEVERITY_MEDIUM],
            affected_population="All sessions in the activity source",
            affected_count=absent,
            triggered_at=_now(),
            explanation=(
                f"{absent:,} sessions are marked Absent yet still carry duration and calories. "
                f"Those nominal minutes are {collapsed:.1f}% of all recorded minutes, so "
                "volume-based KPIs overstate realised activity unless attendance-gated."
            ),
            caveat=(
                "This is a property of the source data, not an operational incident. FitPulse "
                "therefore reports confirmed (attendance-gated) measures alongside raw ones."
            ),
            data_source="activity.attendance_status (real)",
            recommended_action="Prefer attendance-gated measures for engagement reporting.",
        )
    ]


def evaluate_anomaly_alerts(
    anomalies: Optional[pd.DataFrame], limit: int = 5, per_metric_limit: int = 1
) -> List[Alert]:
    """Promote the most severe anomalies into alerts.

    Only one alert per metric is raised: a single sustained shift otherwise
    produces a burst of near-duplicate alerts on consecutive dates, which buries
    the other findings. ``limit`` caps the total promoted.
    """
    if anomalies is None or anomalies.empty:
        return []
    severe = anomalies[anomalies["severity"].isin(["critical", "high"])]
    if severe.empty:
        return []
    severity_rank = {"critical": 0, "high": 1}
    severe = severe.assign(_rank=severe["severity"].map(severity_rank)).sort_values("_rank")
    severe = severe.groupby("metric", as_index=False, sort=False).head(per_metric_limit)

    alerts: List[Alert] = []
    for row in severe.head(limit).itertuples():
        alerts.append(
            Alert(
                alert_id=f"anomaly::{row.metric}::{row.detected_at}",
                category="Anomaly",
                metric=str(row.metric),
                observed_value=float(row.observed_value),
                observed_display=f"{row.observed_value:,.2f} at {row.detected_at}",
                threshold_value=float(row.expected_value) if row.expected_value == row.expected_value else float("nan"),
                threshold_display=str(row.threshold),
                comparison="outside expected range",
                severity=SEVERITY_HIGH if row.severity == "critical" else SEVERITY_MEDIUM,
                severity_bucket=SEVERITY_BUCKET[SEVERITY_HIGH if row.severity == "critical" else SEVERITY_MEDIUM],
                affected_population=str(row.population),
                affected_count=None,
                triggered_at=_now(),
                explanation=str(row.message),
                caveat=str(row.method),
                data_source=str(row.population),
                recommended_action="Review the underlying records before drawing conclusions.",
            )
        )
    return alerts


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def evaluate_alerts(
    members: Optional[pd.DataFrame] = None,
    segment_metrics: Optional[pd.DataFrame] = None,
    platform_daily: Optional[pd.DataFrame] = None,
    platform_monthly: Optional[pd.DataFrame] = None,
    fact_workout: Optional[pd.DataFrame] = None,
    validation_reports: Optional[Sequence[Any]] = None,
    anomalies: Optional[pd.DataFrame] = None,
    thresholds: Optional[AlertThresholds] = None,
    include_informational: bool = True,
) -> pd.DataFrame:
    """Evaluate every alert rule and return a single, severity-sorted table."""
    settings = get_settings()
    thresholds = thresholds or settings.alert_thresholds

    alerts: List[Alert] = []
    alerts += evaluate_churn_rate_alert(members, thresholds)
    alerts += evaluate_inactivity_alert(members, thresholds)
    alerts += evaluate_segment_churn_alerts(segment_metrics, thresholds)
    alerts += evaluate_engagement_drop_alert(platform_monthly, thresholds)
    alerts += evaluate_activity_drop_alert(platform_daily, thresholds)
    alerts += evaluate_missing_data_alert(validation_reports or [], thresholds)
    alerts += evaluate_data_quality_alerts(validation_reports or [])
    alerts += evaluate_confirmed_volume_alert(fact_workout)
    alerts += evaluate_anomaly_alerts(anomalies)

    if not alerts:
        frame = pd.DataFrame(
            columns=[f.name for f in Alert.__dataclass_fields__.values()]
        )
        logger.info("Alert evaluation: no thresholds breached")
        return frame

    frame = pd.DataFrame([a.as_dict() for a in alerts])
    frame = frame.sort_values(["severity_bucket", "category", "metric"]).reset_index(drop=True)
    if not include_informational:
        frame = frame[frame["severity"] != SEVERITY_INFO].reset_index(drop=True)

    logger.info(
        "Alert evaluation: %s alert(s) — %s",
        len(frame),
        frame["severity"].value_counts().to_dict(),
    )
    return frame


def alert_summary(alerts: pd.DataFrame) -> Dict[str, Any]:
    """Counts and the worst severities for dashboard headers."""
    if alerts is None or alerts.empty:
        return {
            "total": 0,
            "high": 0,
            "medium": 0,
            "low": 0,
            "info": 0,
            "status": "PASS",
            "headline": "No configured threshold is currently breached.",
        }
    counts = alerts["severity"].value_counts().to_dict()
    high = int(counts.get(SEVERITY_HIGH, 0))
    medium = int(counts.get(SEVERITY_MEDIUM, 0))
    status = "FAIL" if high else ("WARNING" if medium else "PASS")
    headline = (
        f"{high} high-severity alert(s) require attention."
        if high
        else f"{medium} medium-severity alert(s) are open."
        if medium
        else "Only low-severity or informational alerts are open."
    )
    return {
        "total": int(len(alerts)),
        "high": high,
        "medium": medium,
        "low": int(counts.get(SEVERITY_LOW, 0)),
        "info": int(counts.get(SEVERITY_INFO, 0)),
        "status": status,
        "headline": headline,
    }


def severity_emoji(severity: str) -> str:
    return {
        SEVERITY_HIGH: "🔴",
        SEVERITY_MEDIUM: "🟠",
        SEVERITY_LOW: "🟡",
        SEVERITY_INFO: "🔵",
    }.get(severity, "⚪")

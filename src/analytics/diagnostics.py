"""Correlation, anomaly detection and root-cause investigation.

All three deliberately separate **observed evidence** from **possible
explanation**, as the PRD requires. Nothing in this module assigns causation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

from ..common.logging_utils import get_logger
from .retention import pct

logger = get_logger("analytics.diagnostics")

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


# ---------------------------------------------------------------------------
# Correlation
# ---------------------------------------------------------------------------
DEFAULT_CORRELATION_FEATURES = (
    "visits_per_month",
    "avg_workout_duration_min",
    "avg_calories_burned",
    "total_weight_lifted_kg",
    "consistency",
    "longest_streak",
    "average_streak",
    "recency_days",
    "tenure_days",
    "engagement_score",
    "synthetic_events",
    "is_churned",
)


def correlation_matrix(
    frame: pd.DataFrame,
    columns: Optional[Sequence[str]] = None,
    method: str = "pearson",
    min_periods: int = 5,
) -> pd.DataFrame:
    """Correlation matrix over the numeric columns available in ``frame``."""
    columns = [c for c in (columns or DEFAULT_CORRELATION_FEATURES) if c in frame.columns]
    numeric = frame[columns].apply(pd.to_numeric, errors="coerce")
    numeric = numeric.loc[:, numeric.notna().sum() >= min_periods]
    if numeric.shape[1] < 2:
        return pd.DataFrame()
    return numeric.corr(method=method, min_periods=min_periods).round(4)


def churn_correlations(
    frame: pd.DataFrame,
    target: str = "is_churned",
    features: Optional[Sequence[str]] = None,
) -> pd.DataFrame:
    """Pearson and Spearman correlation of each feature with the churn outcome."""
    if target not in frame.columns or frame.empty:
        return pd.DataFrame()
    features = [
        c
        for c in (features or DEFAULT_CORRELATION_FEATURES)
        if c in frame.columns and c != target
    ]
    y = pd.to_numeric(frame[target].astype(float), errors="coerce")
    rows: List[Dict[str, Any]] = []
    for feature in features:
        x = pd.to_numeric(frame[feature], errors="coerce")
        mask = x.notna() & y.notna()
        if mask.sum() < 5 or x[mask].nunique() < 2:
            continue
        pearson = float(x[mask].corr(y[mask], method="pearson"))
        spearman = float(x[mask].corr(y[mask], method="spearman"))
        rows.append(
            {
                "feature": feature,
                "n": int(mask.sum()),
                "pearson_r": round(pearson, 4),
                "spearman_rho": round(spearman, 4),
                "abs_spearman": round(abs(spearman), 4),
                "direction": "higher feature -> more churn" if spearman > 0 else "higher feature -> less churn",
                "strength": _strength(abs(spearman)),
            }
        )
    frame_out = pd.DataFrame(rows)
    if frame_out.empty:
        return frame_out
    return frame_out.sort_values("abs_spearman", ascending=False).reset_index(drop=True)


def _strength(value: float) -> str:
    if value < 0.1:
        return "negligible"
    if value < 0.3:
        return "weak"
    if value < 0.5:
        return "moderate"
    return "strong"


def correlation_caveat() -> str:
    return (
        "Correlation measures linear/monotonic association in this dataset only. It is not "
        "evidence of causation, and the membership sample is small (150 members)."
    )


# ---------------------------------------------------------------------------
# Anomaly detection
# ---------------------------------------------------------------------------
@dataclass
class Anomaly:
    metric: str
    detected_at: str
    severity: str
    method: str
    threshold: str
    observed_value: float
    expected_value: Optional[float]
    population: str
    message: str

    def as_dict(self) -> Dict[str, Any]:
        return self.__dict__.copy()


def zscore_anomalies(
    values: pd.Series,
    labels: pd.Series,
    metric: str,
    population: str,
    z_threshold: float = 2.5,
    min_points: int = 8,
) -> List[Anomaly]:
    """Point anomalies in a series via z-score against its own mean/std."""
    numeric = pd.to_numeric(values, errors="coerce")
    clean = numeric.dropna()
    if len(clean) < min_points:
        return []
    mean, std = float(clean.mean()), float(clean.std(ddof=1))
    if std == 0 or np.isnan(std):
        return []

    anomalies: List[Anomaly] = []
    for position, value in clean.items():
        z = (value - mean) / std
        if abs(z) < z_threshold:
            continue
        severity = "critical" if abs(z) >= 4 else ("high" if abs(z) >= 3 else "medium")
        anomalies.append(
            Anomaly(
                metric=metric,
                detected_at=str(labels.loc[position]),
                severity=severity,
                method=f"z-score (|z| >= {z_threshold:g})",
                threshold=f"{mean + z_threshold * std:,.2f} / {mean - z_threshold * std:,.2f}",
                observed_value=round(float(value), 4),
                expected_value=round(mean, 4),
                population=population,
                message=(
                    f"{metric} was {value:,.2f} at {labels.loc[position]} versus an expected "
                    f"{mean:,.2f} (z = {z:+.2f})."
                ),
            )
        )
    return anomalies


def rolling_deviation_anomalies(
    values: pd.Series,
    labels: pd.Series,
    metric: str,
    population: str,
    window: int = 28,
    relative_threshold: float = 0.25,
    min_points: int = 40,
    smoothing: int = 7,
) -> List[Anomaly]:
    """Detect *sustained* deviations from a rolling baseline (volume changes)."""
    numeric = pd.to_numeric(values, errors="coerce")
    if numeric.dropna().shape[0] < min_points:
        return []

    # Two guards keep this detector meaningful for an alerting product:
    #  * the baseline requires a FULL window, so warm-up periods cannot produce
    #    deviations that reflect a thin baseline rather than a real change;
    #  * the observed side is a short rolling mean, so single-day spikes are not
    #    promoted as sustained shifts.
    baseline = numeric.rolling(window, min_periods=window).mean().shift(1)
    smoothed = numeric.rolling(smoothing, min_periods=max(2, smoothing // 2)).mean()

    anomalies: List[Anomaly] = []
    for position in numeric.index:
        current, base = smoothed.loc[position], baseline.loc[position]
        if pd.isna(current) or pd.isna(base) or base == 0:
            continue
        deviation = (current - base) / base
        if abs(deviation) < relative_threshold:
            continue
        severity = "high" if abs(deviation) >= 0.5 else "medium"
        anomalies.append(
            Anomaly(
                metric=f"{metric} ({smoothing}-period mean)",
                detected_at=str(labels.loc[position]),
                severity=severity,
                method=(
                    f"{smoothing}-period mean vs {window}-period rolling baseline "
                    f"(deviation >= {relative_threshold:.0%})"
                ),
                threshold=f"{base * (1 - relative_threshold):,.2f} / {base * (1 + relative_threshold):,.2f}",
                observed_value=round(float(current), 4),
                expected_value=round(float(base), 4),
                population=population,
                message=(
                    f"The {smoothing}-period mean of {metric} deviated {deviation:+.1%} from its "
                    f"{window}-period rolling baseline at {labels.loc[position]}."
                ),
            )
        )
    return anomalies


def iqr_anomalies(
    values: pd.Series,
    metric: str,
    population: str,
    multiplier: float = 1.5,
    plausible_min: Optional[float] = None,
    plausible_max: Optional[float] = None,
) -> List[Anomaly]:
    """Unusual member-level values, classified rather than removed."""
    numeric = pd.to_numeric(values, errors="coerce")
    clean = numeric.dropna()
    if clean.empty:
        return []
    q1, q3 = float(clean.quantile(0.25)), float(clean.quantile(0.75))
    iqr = q3 - q1
    low, high = q1 - multiplier * iqr, q3 + multiplier * iqr
    outside = clean[(clean < low) | (clean > high)]
    anomalies: List[Anomaly] = []
    for position, value in outside.items():
        domain_violation = False
        if plausible_min is not None and value < plausible_min:
            domain_violation = True
        if plausible_max is not None and value > plausible_max:
            domain_violation = True
        anomalies.append(
            Anomaly(
                metric=metric,
                detected_at=str(position),
                severity="high" if domain_violation else "low",
                method=f"IQR fence (x{multiplier:g})",
                threshold=f"{low:,.2f} .. {high:,.2f}",
                observed_value=round(float(value), 4),
                expected_value=round(float(clean.median()), 4),
                population=population,
                message=(
                    f"{metric} = {value:,.2f}, outside the IQR fence "
                    f"[{low:,.2f}, {high:,.2f}]. Classified as "
                    f"{'potential error' if domain_violation else 'valid extreme'} — retained, not removed."
                ),
            )
        )
    return anomalies


def outlier_boundary_notes(
    members: pd.DataFrame,
    checks: Sequence[tuple[str, float, float]] = (
        ("average workout duration (minutes)", 1.0, 300.0),
        ("visits per month", 0.0, 31.0),
    ),
    multiplier: float = 1.5,
) -> List[Anomaly]:
    """Record the *outcome* of member-level outlier screening.

    Bounded fields (duration, visit rate) legitimately contain no values beyond the
    IQR fence. Emitting a low-severity row documents that the check ran and found
    nothing, rather than leaving the reader unsure whether screening happened.
    """
    notes: List[Anomaly] = []
    for column, low, high in checks:
        if column not in members.columns:
            continue
        numeric = pd.to_numeric(members[column], errors="coerce").dropna()
        if numeric.empty:
            continue
        q1, q3 = float(numeric.quantile(0.25)), float(numeric.quantile(0.75))
        iqr = q3 - q1
        fence_low, fence_high = q1 - multiplier * iqr, q3 + multiplier * iqr
        outside = int(((numeric < fence_low) | (numeric > fence_high)).sum())
        notes.append(
            Anomaly(
                metric=f"{column} — outlier screening",
                detected_at="membership snapshot",
                severity="low",
                method=f"IQR fence (x{multiplier:g}), domain [{low:g}, {high:g}]"
                + (" — declared below the alerting threshold" if multiplier <= 1.5 else ""),
                threshold=f"{fence_low:,.2f} .. {fence_high:,.2f}",
                observed_value=round(float(numeric.max()), 4),
                expected_value=round(float(numeric.median()), 4),
                population="membership (real)",
                message=(
                    f"{outside} value(s) outside the IQR fence. Observed range "
                    f"{numeric.min():,.0f}-{numeric.max():,.0f}; values remain inside the plausible "
                    "business domain, so no member-level outlier alert is raised."
                ),
            )
        )
    return notes


def detect_all_anomalies(
    platform_daily: Optional[pd.DataFrame] = None,
    platform_monthly: Optional[pd.DataFrame] = None,
    member_features: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """Run every anomaly detector and return one combined, sorted table."""
    anomalies: List[Anomaly] = []

    if platform_daily is not None and not platform_daily.empty:
        daily = platform_daily.copy()
        daily["activity_date"] = pd.to_datetime(daily["activity_date"])
        labels = daily["activity_date"].dt.date.astype(str)
        # Daily session counts are small integers, so z-fences are only meaningful
        # at a demanding threshold; otherwise ordinary discretisation noise fires.
        anomalies += zscore_anomalies(
            daily["events"],
            labels,
            "daily recorded sessions",
            "platform activity (real)",
            z_threshold=3.0,
        )
        anomalies += rolling_deviation_anomalies(
            daily["events"],
            labels,
            "daily recorded sessions",
            "platform activity (real)",
            window=28,
            relative_threshold=0.35,
        )
        if "present_rate" in daily.columns:
            anomalies += zscore_anomalies(
                daily["present_rate"] * 100.0,
                labels,
                "daily attendance rate (%)",
                "platform activity (real)",
                z_threshold=3.0,
            )

    if platform_monthly is not None and not platform_monthly.empty:
        monthly = platform_monthly.copy()
        labels = monthly["month"].astype(str)
        anomalies += zscore_anomalies(
            monthly["events"], labels, "monthly recorded sessions", "platform activity (real)"
        )

    if member_features is not None and not member_features.empty:
        members = member_features
        anomalies += iqr_anomalies(
            members.set_index("member_id")["avg_workout_duration_min"],
            "average workout duration (minutes)",
            "membership (real)",
            plausible_min=1,
            plausible_max=300,
        )
        anomalies += iqr_anomalies(
            members.set_index("member_id")["visits_per_month"],
            "visits per month",
            "membership (real)",
            plausible_min=0,
            plausible_max=31,
        )
        anomalies += outlier_boundary_notes(members)

    if not anomalies:
        return pd.DataFrame(
            columns=[
                "metric",
                "detected_at",
                "severity",
                "method",
                "threshold",
                "observed_value",
                "expected_value",
                "population",
                "message",
            ]
        )

    frame = pd.DataFrame([a.as_dict() for a in anomalies])
    frame["_rank"] = frame["severity"].map(SEVERITY_ORDER).fillna(9)
    frame = frame.sort_values(["_rank", "detected_at"]).drop(columns="_rank").reset_index(drop=True)
    logger.info("Anomaly detection produced %s findings", f"{len(frame):,}")
    return frame


# ---------------------------------------------------------------------------
# Root-cause investigation
# ---------------------------------------------------------------------------
@dataclass
class RootCauseChain:
    """One investigated signal with evidence separated from explanation."""

    subject: str
    metric_changed: str
    period: str
    observed_evidence: List[str] = field(default_factory=list)
    possible_explanations: List[str] = field(default_factory=list)
    confidence: str = "low"
    data_caveats: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "subject": self.subject,
            "metric_changed": self.metric_changed,
            "period": self.period,
            "observed_evidence": self.observed_evidence,
            "possible_explanations": self.possible_explanations,
            "confidence": self.confidence,
            "data_caveats": self.data_caveats,
        }


def _largest_month_change(monthly: pd.DataFrame, column: str) -> Optional[Dict[str, Any]]:
    if monthly is None or monthly.empty or column not in monthly.columns or len(monthly) < 2:
        return None
    frame = monthly.sort_values("month")
    deltas = frame[column].diff()
    if deltas.abs().dropna().empty:
        return None
    index = deltas.abs().idxmax()
    previous = frame[column].shift(1).loc[index]
    return {
        "month": str(frame.loc[index, "month"]),
        "value": float(frame.loc[index, column]),
        "previous": float(previous) if pd.notna(previous) else None,
        "delta": float(deltas.loc[index]),
        "change_pct": float(100.0 * deltas.loc[index] / previous) if pd.notna(previous) and previous else None,
    }


def root_cause_analysis(
    member_features: pd.DataFrame,
    platform_monthly: Optional[pd.DataFrame] = None,
    comparison: Optional[pd.DataFrame] = None,
) -> List[RootCauseChain]:
    """Build root-cause investigation chains from real, computed evidence."""
    chains: List[RootCauseChain] = []
    if member_features is None or member_features.empty:
        return chains

    # --- chain 1: the strongest real behavioural difference -----------------
    if comparison is not None and not comparison.empty:
        top = comparison.iloc[0]
        chain = RootCauseChain(
            subject="Behavioural contrast between retained and churned members",
            metric_changed="churn outcome",
            period="membership snapshot",
            observed_evidence=[
                f"Churned members average {top['churned_mean']:,.2f} for {top['measure']} "
                f"versus {top['retained_mean']:,.2f} for retained members "
                f"(difference {top['difference']:+,.2f}, Cohen's d = {top['cohens_d']:+.2f}, "
                f"{top['effect_size']} effect).",
                f"Groups compared: {int(top['n_retained'])} retained and {int(top['n_churned'])} churned members.",
            ],
            possible_explanations=[
                "Members with a low recorded visit rate may be disengaging before the churn "
                "decision is recorded.",
                "The visit-rate field may itself be maintained less aggressively for members "
                "who have already churned, which would put the arrow of time in the opposite "
                "direction.",
            ],
            confidence="moderate" if abs(top["cohens_d"]) >= 0.8 else "low",
            data_caveats=[
                "Observational data: no randomisation, so no causal claim is supported.",
                "Churn and visit rate may be recorded inconsistently by the publishing system.",
            ],
        )
        chains.append(chain)

    # --- chain 2: segment concentration ------------------------------------
    if "segment" in member_features.columns:
        segments = (
            member_features.groupby("segment")
            .agg(members=("member_id", "count"), churned=("is_churned", "sum"))
            .reset_index()
        )
        segments["churn_rate"] = (100.0 * segments["churned"] / segments["members"]).round(4)
        top_segment = segments.sort_values("churn_rate", ascending=False).iloc[0]
        total_churned = float(member_features["is_churned"].astype(bool).sum())
        share_of_churn = pct(float(top_segment["churned"]), total_churned)
        chains.append(
            RootCauseChain(
                subject="Churn concentration by behavioural segment",
                metric_changed="segment churn rate",
                period="membership snapshot",
                observed_evidence=[
                    f"{top_segment['segment']} carries the highest observed churn rate at "
                    f"{top_segment['churn_rate']:.1f}% ({int(top_segment['churned'])} of "
                    f"{int(top_segment['members'])} members).",
                    f"That segment accounts for {share_of_churn:.1f}% of all churned members.",
                ],
                possible_explanations=[
                    "Segment membership is a composite of frequency, consistency, streak and "
                    "recency, so the elevated churn may be driven primarily by the frequency "
                    "component rather than by low consistency or short streaks.",
                ],
                confidence="low",
                data_caveats=[
                    "Segment thresholds are configurable product-design choices, not validated "
                    "behavioural cut points.",
                    "Consistency and streak components depend on synthetic date placement.",
                ],
            )
        )

    # --- chain 3: membership tier -----------------------------------------
    if "membership_type" in member_features.columns:
        tiers = (
            member_features.groupby("membership_type")
            .agg(members=("member_id", "count"), churned=("is_churned", "sum"))
            .reset_index()
        )
        tiers["churn_rate"] = (100.0 * tiers["churned"] / tiers["members"]).round(4)
        worst = tiers.sort_values("churn_rate", ascending=False).iloc[0]
        best = tiers.sort_values("churn_rate").iloc[0]
        chains.append(
            RootCauseChain(
                subject="Churn difference across membership tiers",
                metric_changed="tier churn rate",
                period="membership snapshot",
                observed_evidence=[
                    f"{worst['membership_type']} members churn at {worst['churn_rate']:.1f}% "
                    f"({int(worst['churned'])} of {int(worst['members'])}), versus "
                    f"{best['membership_type']} at {best['churn_rate']:.1f}% "
                    f"({int(best['churned'])} of {int(best['members'])}).",
                ],
                possible_explanations=[
                    "Shorter commitment periods surface churn decisions more frequently.",
                    "Tier pricing or contract length may correlate with a different member mix.",
                ],
                confidence="low",
                data_caveats=[
                    f"Smallest tier group is {int(tiers['members'].min())} members, so tier "
                    "differences carry wide confidence intervals.",
                ],
            )
        )

    # --- chain 4: platform-side change ------------------------------------
    change = _largest_month_change(platform_monthly, "events") if platform_monthly is not None else None
    if change:
        chains.append(
            RootCauseChain(
                subject="Platform session-volume change",
                metric_changed="monthly recorded sessions",
                period=change["month"],
                observed_evidence=[
                    f"Recorded sessions moved from {change['previous']:,.0f} to "
                    f"{change['value']:,.0f} in {change['month']} "
                    f"({change['delta']:+,.0f} sessions, "
                    f"{change['change_pct']:+.1f}%)."
                    if change["previous"] is not None
                    else f"Sessions in {change['month']}: {change['value']:,.0f}.",
                ],
                possible_explanations=[
                    "Seasonal patterns (new-year intake versus holiday periods) are a plausible "
                    "driver of month-to-month volume in a single calendar year.",
                    "The activity source covers only 2024 and shares no member key with the "
                    "membership source, so platform volume cannot be linked to member churn.",
                ],
                confidence="low",
                data_caveats=[
                    "One calendar year of data: seasonality and trend cannot be separated.",
                ],
            )
        )

    return chains


def root_cause_frame(chains: Sequence[RootCauseChain]) -> pd.DataFrame:
    """Flatten root-cause chains for tabular display."""
    rows: List[Dict[str, Any]] = []
    for chain in chains:
        rows.append(
            {
                "subject": chain.subject,
                "metric_changed": chain.metric_changed,
                "period": chain.period,
                "confidence": chain.confidence,
                "observed_evidence": " | ".join(chain.observed_evidence),
                "possible_explanations": " | ".join(chain.possible_explanations),
                "data_caveats": " | ".join(chain.data_caveats),
                "evidence_type": "observed evidence + possible explanation (not causal)",
            }
        )
    return pd.DataFrame(rows)

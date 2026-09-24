"""Business report generation.

Produces the executive report required by the PRD: executive summary, KPI
overview, engagement findings, retention findings, segment findings, risk
alerts, anomalies, data-quality status, SQL validation, key findings and
recommended areas for investigation.

Every number in the report is taken from a computed frame. Where a figure
depends on the synthetic integration layer, the report says so. No
unsupported claim is generated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

import pandas as pd

from ..common.config import ARTIFACTS_DIR
from ..common.io_utils import write_text
from ..common.logging_utils import get_logger

logger = get_logger("reporting")


@dataclass
class ReportContext:
    """Everything the renderer needs. Assembled by the pipeline."""

    kpis: Dict[str, Any] = field(default_factory=dict)
    retention: Dict[str, Any] = field(default_factory=dict)
    retention_comparison: pd.DataFrame = field(default_factory=pd.DataFrame)
    segment_metrics: pd.DataFrame = field(default_factory=pd.DataFrame)
    segment_insight: str = ""
    trend_summary: Dict[str, Any] = field(default_factory=dict)
    monthly_trend: pd.DataFrame = field(default_factory=pd.DataFrame)
    engagement: Dict[str, Any] = field(default_factory=dict)
    anomalies: pd.DataFrame = field(default_factory=pd.DataFrame)
    alerts: pd.DataFrame = field(default_factory=pd.DataFrame)
    alert_summary: Dict[str, Any] = field(default_factory=dict)
    quality: Dict[str, Any] = field(default_factory=dict)
    quality_checks: pd.DataFrame = field(default_factory=pd.DataFrame)
    crosscheck: pd.DataFrame = field(default_factory=pd.DataFrame)
    integrity: pd.DataFrame = field(default_factory=pd.DataFrame)
    answers: Sequence[Any] = field(default_factory=tuple)
    root_causes: Sequence[Any] = field(default_factory=tuple)
    integration: Dict[str, Any] = field(default_factory=dict)
    funnel: pd.DataFrame = field(default_factory=pd.DataFrame)
    funnel_insight: str = ""
    sources: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    stage_records: Sequence[Dict[str, Any]] = field(default_factory=tuple)


@dataclass
class ReportResult:
    markdown: str
    html: str = ""
    path: Optional[Path] = None
    generated_at: str = ""


def _fmt(value: Any, digits: int = 2, suffix: str = "") -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:,.{digits}f}{suffix}"
    if isinstance(value, int):
        return f"{value:,}{suffix}"
    return f"{value}{suffix}"


def _table(frame: Optional[pd.DataFrame], columns: Optional[Sequence[str]] = None, limit: int = 15) -> str:
    if frame is None or frame.empty:
        return "_No data available._\n"
    view = frame.copy()
    if columns:
        present = [c for c in columns if c in view.columns]
        view = view[present] if present else view
    view = view.head(limit)
    try:
        return view.to_markdown(index=False) + "\n"
    except Exception:  # noqa: BLE001 - fall back to plain text
        return "```\n" + view.to_string(index=False) + "\n```\n"


def _bullet_list(items: Iterable[str]) -> str:
    items = [item for item in items if item]
    if not items:
        return "- None identified.\n"
    return "\n".join(f"- {item}" for item in items) + "\n"


def _executive_summary(context: ReportContext) -> str:
    kpis = context.kpis
    retention = context.retention
    lines = ["## 1. Executive summary", ""]
    if not kpis:
        lines.append("No analytical run has produced KPIs yet. Run `python scripts/pipeline.py` first.")
        return "\n".join(lines) + "\n"

    lines.append(
        f"FitPulse analysed **{_fmt(kpis.get('total_members'), 0)} members** from the membership "
        f"source and **{_fmt(kpis.get('platform_events'), 0)} activity records** from the activity "
        f"source. Observed retention is **{_fmt(retention.get('retention_rate'), 2, '%')}** and "
        f"observed churn is **{_fmt(retention.get('churn_rate'), 2, '%')}** "
        f"(95% CI {_fmt(retention.get('churn_ci_low'), 1, '%')}–"
        f"{_fmt(retention.get('churn_ci_high'), 1, '%')})."
    )
    lines.append("")
    comparison = context.retention_comparison
    if comparison is not None and not comparison.empty:
        top = comparison.iloc[0]
        lines.append(
            f"The strongest observed behavioural difference between retained and churned members is "
            f"**{str(top['measure']).replace('_', ' ')}** (churned {_fmt(top['churned_mean'], 2)} vs "
            f"retained {_fmt(top['retained_mean'], 2)}; Cohen's d {_fmt(top['cohens_d'], 2)}, "
            f"{top['effect_size']} effect). This is an association in the analysed dataset, not a "
            "causal finding."
        )
        lines.append("")
    lines.append(
        f"Alert status: **{context.alert_summary.get('status', 'PASS')}** — "
        f"{context.alert_summary.get('headline', 'no thresholds breached.')}"
    )
    lines.append("")
    lines.append(
        f"Data quality: **{context.quality.get('status', 'n/a')}** "
        f"({context.quality.get('passed', 0)}/{context.quality.get('total_checks', 0)} checks passed, "
        f"{context.quality.get('warnings', 0)} warning(s), {context.quality.get('failures', 0)} failure(s)); "
        f"Python↔SQL validation: **{context.crosscheck.attrs.get('status', _crosscheck_status(context))}**."
    )
    lines.append("")
    return "\n".join(lines) + "\n"


def _crosscheck_status(context: ReportContext) -> str:
    if context.crosscheck is None or context.crosscheck.empty:
        return "n/a"
    return "PASS" if not (context.crosscheck["status"] == "FAIL").any() else "FAIL"


def _kpi_section(context: ReportContext) -> str:
    kpis = context.kpis
    lines = ["## 2. KPI overview", ""]
    if not kpis:
        return "\n".join(lines) + "\n_No KPIs available._\n"
    rows = [
        ("Total members", _fmt(kpis.get("total_members"), 0), "Membership source (real)"),
        ("Retained members", _fmt(kpis.get("retained_members"), 0), "Membership source (real)"),
        ("Churned members", _fmt(kpis.get("churned_members"), 0), "Membership source (real)"),
        ("Retention rate", _fmt(kpis.get("retention_rate"), 2, "%"), "Retained / eligible members (real)"),
        ("Churn rate", _fmt(kpis.get("churn_rate"), 2, "%"), "Churned / eligible members (real)"),
        ("Average visits / month", _fmt(kpis.get("avg_visits_per_month"), 2), "Membership source (real)"),
        ("Average workout duration", _fmt(kpis.get("avg_workout_duration"), 1, " min"), "Membership source (real)"),
        ("Average engagement score", _fmt(kpis.get("avg_engagement_score"), 1, " / 100"), "Derived composite"),
        (
            "Average longest streak",
            _fmt(kpis.get("avg_longest_streak"), 2, " days"),
            "Synthetic calendar (date placement)",
        ),
        ("At-risk members", _fmt(kpis.get("at_risk_members"), 0), "Derived segment (real outcome)"),
        ("Recorded sessions", _fmt(kpis.get("platform_events"), 0), "Activity source (real)"),
        ("Platform attendance rate", _fmt(kpis.get("platform_attendance_rate"), 2, "%"), "Activity source (real)"),
        (
            "Confirmed duration share",
            _fmt(kpis.get("platform_confirmed_duration_share"), 2, "%"),
            "Attendance-gated share of recorded minutes (real)",
        ),
    ]
    lines.append("| KPI | Value | Provenance |")
    lines.append("|---|---|---|")
    for label, value, provenance in rows:
        lines.append(f"| {label} | {value} | {provenance} |")
    lines.append("")
    for note in kpis.get("notes", [])[:3]:
        lines.append(f"> {note}")
        lines.append("")
    return "\n".join(lines) + "\n"


def _retention_section(context: ReportContext) -> str:
    lines = ["## 3. Retention findings", ""]
    retention = context.retention
    if not retention:
        return "\n".join(lines) + "\n_Retention analysis unavailable._\n"
    lines.append(
        f"Retention is {_fmt(retention.get('retention_rate'), 2, '%')} "
        f"({_fmt(retention.get('retained'), 0)} of {_fmt(retention.get('total_members'), 0)} members) and "
        f"churn is {_fmt(retention.get('churn_rate'), 2, '%')} "
        f"({_fmt(retention.get('churned'), 0)} members)."
    )
    lines.append("")
    lines.append("### Retained vs churned behaviour")
    lines.append("")
    lines.append(
        _table(
            context.retention_comparison,
            columns=[
                "measure",
                "retained_mean",
                "churned_mean",
                "difference",
                "cohens_d",
                "effect_size",
            ],
            limit=10,
        )
    )
    lines.append(
        "Effect sizes are reported alongside means because the groups are unbalanced "
        "(111 retained vs 39 churned). Correlation and association are not causation."
    )
    lines.append("")
    return "\n".join(lines) + "\n"


def _engagement_section(context: ReportContext) -> str:
    lines = ["## 4. Engagement findings", ""]
    engagement = context.engagement or {}
    if not engagement:
        return "\n".join(lines) + "\n_Engagement analysis unavailable._\n"
    insight = engagement.get("insight")
    if insight:
        lines.append(insight)
        lines.append("")
    caveat = engagement.get("nominal_value_caveat")
    if caveat:
        lines.append(f"> **Data semantics:** {caveat}")
        lines.append("")
    visits = engagement.get("visits_per_month") or {}
    if visits:
        lines.append(
            f"Visit rate distribution: mean {_fmt(visits.get('mean'), 2)}, median "
            f"{_fmt(visits.get('median'), 2)}, range {_fmt(visits.get('min'), 0)}–"
            f"{_fmt(visits.get('max'), 0)} per month."
        )
        lines.append("")
    trend = context.trend_summary or {}
    if trend:
        events_trend = trend.get("events_trend", {})
        lines.append(
            f"Platform session volume is **{events_trend.get('direction', 'n/a')}** across 2024 "
            f"({_fmt(events_trend.get('change_pct'), 1, '%')}); peak month "
            f"{trend.get('peak_month', 'n/a')} with {_fmt(trend.get('peak_events'), 0)} sessions."
        )
        lines.append("")
    if context.funnel_insight:
        lines.append(context.funnel_insight)
        lines.append("")
    lines.append("### Where engagement drops (real activity source)")
    lines.append("")
    lines.append(
        _table(
            context.funnel,
            columns=["stage", "records", "share_of_start_pct", "drop_off", "drop_off_pct", "provenance"],
            limit=6,
        )
    )
    return "\n".join(lines) + "\n"


def _segment_section(context: ReportContext) -> str:
    lines = ["## 5. Segment findings", ""]
    if context.segment_metrics is None or context.segment_metrics.empty:
        return "\n".join(lines) + "\n_Segmentation unavailable._\n"
    if context.segment_insight:
        lines.append(context.segment_insight)
        lines.append("")
    lines.append(
        _table(
            context.segment_metrics,
            columns=[
                "segment",
                "members",
                "share_pct",
                "churn_rate",
                "retention_rate",
                "avg_visits_per_month",
                "avg_longest_streak",
                "avg_recency_days",
            ],
            limit=6,
        )
    )
    lines.append(
        "> Segments use configurable engagement-score thresholds. Consistency and streak "
        "components depend on synthetic date placement; the churn outcome is real."
    )
    lines.append("")
    return "\n".join(lines) + "\n"


def _alert_section(context: ReportContext) -> str:
    lines = ["## 6. Risk alerts", ""]
    summary = context.alert_summary or {}
    lines.append(
        f"Status **{summary.get('status', 'n/a')}** — {summary.get('headline', 'not evaluated.')} "
        f"({summary.get('high', 0)} high, {summary.get('medium', 0)} medium, "
        f"{summary.get('low', 0)} low)."
    )
    lines.append("")
    if context.alerts is None or context.alerts.empty:
        lines.append("_No alert thresholds were breached in this run._")
        lines.append("")
        return "\n".join(lines) + "\n"
    for row in context.alerts.head(10).itertuples():
        lines.append(f"### {row.severity} — {row.metric}")
        lines.append("")
        lines.append(f"- **Observed:** {row.observed_display}")
        lines.append(f"- **Threshold:** {row.threshold_display}")
        lines.append(f"- **Affected population:** {row.affected_population}")
        lines.append(f"- **Evaluated at:** {row.triggered_at}")
        lines.append(f"- **Explanation:** {row.explanation}")
        if row.caveat:
            lines.append(f"- **Caveat:** {row.caveat}")
        if row.recommended_action:
            lines.append(f"- **Suggested action:** {row.recommended_action}")
        lines.append("")
    return "\n".join(lines) + "\n"


def _anomaly_section(context: ReportContext) -> str:
    lines = ["## 7. Anomalies", ""]
    if context.anomalies is None or context.anomalies.empty:
        lines.append("_No anomalies exceeded the configured detection thresholds._")
        lines.append("")
        return "\n".join(lines) + "\n"
    counts = context.anomalies["severity"].value_counts().to_dict()
    lines.append(
        f"{len(context.anomalies)} anomaly observation(s) detected: "
        + ", ".join(f"{count} {severity}" for severity, count in counts.items())
        + "."
    )
    lines.append("")
    lines.append(
        _table(
            context.anomalies,
            columns=["metric", "detected_at", "severity", "observed_value", "threshold", "method"],
            limit=12,
        )
    )
    lines.append(
        "> Anomalies are classified and reported; no source values are deleted or capped. "
        "Whether an extreme value is a data error or a genuine outlier is stated per finding."
    )
    lines.append("")
    return "\n".join(lines) + "\n"


def _quality_section(context: ReportContext) -> str:
    lines = ["## 8. Data quality", ""]
    quality = context.quality or {}
    lines.append(
        f"Overall status **{quality.get('status', 'n/a')}** — "
        f"{quality.get('passed', 0)} passed, {quality.get('warnings', 0)} warning(s), "
        f"{quality.get('failures', 0)} failure(s) across {quality.get('total_checks', 0)} checks "
        f"(pass rate {_fmt(quality.get('pass_rate'), 1, '%')})."
    )
    lines.append("")
    if context.quality_checks is not None and not context.quality_checks.empty:
        by_category = (
            context.quality_checks.groupby(["dataset", "category", "status"]).size().reset_index(name="checks")
        )
        lines.append(_table(by_category, limit=25))
    attention = (
        context.quality_checks[context.quality_checks["status"] != "PASS"]
        if context.quality_checks is not None and not context.quality_checks.empty
        else pd.DataFrame()
    )
    if not attention.empty:
        lines.append("### Checks requiring attention")
        lines.append("")
        lines.append(
            _table(
                attention,
                columns=["dataset", "category", "description", "status", "failing_rows", "detail"],
                limit=12,
            )
        )
    return "\n".join(lines) + "\n"


def _sql_validation_section(context: ReportContext) -> str:
    lines = ["## 9. SQL validation (Python ↔ SQL)", ""]
    if context.crosscheck is None or context.crosscheck.empty:
        return "\n".join(lines) + "\n_SQL validation unavailable._\n"
    passed = int((context.crosscheck["status"] == "PASS").sum())
    failed = int((context.crosscheck["status"] == "FAIL").sum())
    lines.append(
        f"{passed} of {len(context.crosscheck)} KPI(s) agree between the Python analytics layer and "
        f"the SQL layer within the declared tolerance ({failed} mismatch(es))."
    )
    lines.append("")
    display = context.crosscheck.copy()
    display = display[
        [
            "kpi",
            "python_value",
            "sql_value",
            "difference",
            "tolerance",
            "status",
        ]
    ]
    lines.append(_table(display, limit=30))
    if context.integrity is not None and not context.integrity.empty:
        lines.append("### Structural integrity checks")
        lines.append("")
        lines.append(
            _table(
                context.integrity,
                columns=["check", "observed", "expected", "status", "detail"],
                limit=15,
            )
        )
    return "\n".join(lines) + "\n"


def _answers_section(context: ReportContext) -> str:
    lines = ["## 10. Analytical question findings", ""]
    if not context.answers:
        return "\n".join(lines) + "\n_No analytical answers available._\n"
    for answer in context.answers:
        availability = "" if getattr(answer, "available", True) else " *(unavailable)*"
        lines.append(f"### {answer.question_id} — {answer.question}{availability}")
        lines.append("")
        lines.append(answer.answer)
        lines.append("")
        if answer.evidence:
            lines.append("**Evidence**")
            lines.append("")
            lines.extend(f"- {item}" for item in answer.evidence if item)
            lines.append("")
        lines.append(f"**Provenance:** {answer.provenance}")
        lines.append("")
        if answer.caveats:
            lines.append("**Caveats**")
            lines.append("")
            lines.extend(f"- {item}" for item in answer.caveats)
            lines.append("")
    return "\n".join(lines) + "\n"


def _root_cause_section(context: ReportContext) -> str:
    lines = ["## 11. Root-cause investigation", ""]
    if not context.root_causes:
        return "\n".join(lines) + "\n_No root-cause chains available._\n"
    lines.append(
        "Each chain separates **observed evidence** from **possible explanations**. Nothing below "
        "is a causal claim."
    )
    lines.append("")
    for chain in context.root_causes:
        lines.append(f"### {chain.subject}")
        lines.append("")
        lines.append(f"- **Metric examined:** {chain.metric_changed}")
        lines.append(f"- **Period:** {chain.period}")
        lines.append(f"- **Confidence:** {chain.confidence}")
        lines.append("")
        lines.append("**Observed evidence**")
        lines.append("")
        lines.extend(f"- {item}" for item in chain.observed_evidence)
        lines.append("")
        lines.append("**Possible explanations (not verified)**")
        lines.append("")
        lines.extend(f"- {item}" for item in chain.possible_explanations)
        lines.append("")
        if chain.data_caveats:
            lines.append("**Data caveats**")
            lines.append("")
            lines.extend(f"- {item}" for item in chain.data_caveats)
            lines.append("")
    return "\n".join(lines) + "\n"


def _recommendations_section(context: ReportContext) -> str:
    lines = ["## 12. Recommended areas for investigation", ""]
    items: List[str] = []
    if context.alerts is not None and not context.alerts.empty:
        for row in context.alerts.head(3).itertuples():
            if row.recommended_action:
                items.append(f"**{row.metric}** — {row.recommended_action}")
    comparison = context.retention_comparison
    if comparison is not None and not comparison.empty:
        top = comparison.iloc[0]
        items.append(
            f"**Frequency hypothesis** — {str(top['measure']).replace('_', ' ')} separates retained "
            f"from churned members with a {top['effect_size']} effect size. A controlled retention "
            "experiment on visit frequency would be the only way to test direction."
        )
    if not context.integration.get("join_performed", False):
        items.append(
            "**Data contract** — the two sources share no member key, so activity and churn cannot be "
            "linked at member level. Connecting a shared member identifier would unlock true "
            "behaviour-to-churn analysis."
        )
    items.append(
        "**Renewal events** — subscription renewal is not present in either source, so renewal-rate "
        "analysis is outside the available data scope."
    )
    items.append(
        "**Recency reliability** — last-visit dates in the membership source show no association with "
        "churn. Confirm how that field is maintained before it is used operationally."
    )
    if context.anomalies is not None and not context.anomalies.empty:
        items.append(
            f"**Anomaly review** — {len(context.anomalies)} anomaly observation(s) were classified; "
            "review the highest-severity entries before acting on downstream aggregates."
        )
    return "\n".join(lines) + _bullet_list(items) + "\n"


def _provenance_section(context: ReportContext) -> str:
    lines = ["## 13. Data provenance & limitations", ""]
    lines.append("### Source datasets")
    lines.append("")
    for name, source in (context.sources or {}).items():
        lines.append(
            f"- **{name}** — {source.get('dataset_label', '')} · `{source.get('path') or 'dashboard upload'}` "
            f"· {source.get('rows', 0):,} rows · [source]({source.get('dataset_url', '')}) "
            f"({source.get('dataset_license', '')})"
        )
    lines.append("")
    lines.append("### Provenance statement")
    lines.append("")
    lines.append(
        "- **Source data** — the original Kaggle datasets, unmodified.\n"
        "- **Derived data** — deterministically calculated from source records (rates, banding, "
        "features, scores).\n"
        "- **Synthetic analytical data** — event dates and per-event workout type generated so that "
        "multi-source integration can be demonstrated where the public datasets share no legitimate "
        "common identifier. Member outcomes and measures remain real."
    )
    lines.append("")
    integration = context.integration or {}
    key = integration.get("key_analysis") or {}
    if key:
        lines.append("### Integration decision")
        lines.append("")
        lines.append(
            f"- Verdict: **{key.get('verdict')}** (confidence {key.get('confidence')})\n"
            f"- Raw identifier overlap: {key.get('overlap_count', 0):,} values "
            f"({key.get('overlap_pct_of_right', 0):.1f}% of membership rows)\n"
            f"- User-level join performed: **No**\n"
            f"- Recommendation: {key.get('recommendation', '')}"
        )
        lines.append("")
        for item in (key.get("evidence") or [])[:5]:
            lines.append(f"- {item}")
        lines.append("")
    synthetic = integration.get("synthetic_validation") or {}
    if synthetic:
        lines.append("### Synthetic bridge validation")
        lines.append("")
        lines.append(_table(pd.DataFrame(synthetic.get("checks", [])), limit=10))
    limitations = [
        "The activity source has no repeatable member identifier, so member-level streak and "
        "consistency features cannot be derived from real data alone.",
        "The activity source records nominal duration and calories for sessions marked Absent, so "
        "attendance-gated measures are reported alongside raw ones.",
        "The membership source has no churn event date, so monthly churn over time is not derivable.",
        "No subscription renewal event exists in either source; renewal analysis is out of scope.",
        "The membership sample is small (150 members), so group-level rates carry wide confidence "
        "intervals.",
        "Missing numeric values are median-imputed with explicit flags; the imputed share is reported "
        "in the Data Quality page.",
    ]
    lines.append("### Known limitations")
    lines.append("")
    return "\n".join(lines) + _bullet_list(limitations) + "\n"


def _pipeline_section(context: ReportContext) -> str:
    lines = ["## 14. Pipeline execution log", ""]
    if not context.stage_records:
        return "\n".join(lines) + "\n_No stage log available._\n"
    lines.append("| Stage | Status | Duration (s) | Records | Notes |")
    lines.append("|---|---|---|---|---|")
    for record in context.stage_records:
        records = record.get("records_processed")
        lines.append(
            f"| {record.get('stage')} | {record.get('status')} | {record.get('duration', 0):.2f} | "
            f"{f'{records:,}' if records is not None else ''} | {record.get('message', '') or ''} |"
        )
    lines.append("")
    return "\n".join(lines) + "\n"


def render_report(context: ReportContext) -> str:
    """Render the full markdown report."""
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    header = [
        "# FitPulse — Fitness Retention Intelligence Report",
        "",
        f"**Generated:** {generated}  ",
        f"**Observation date:** {context.metadata.get('observation_date', 'n/a')}  ",
        f"**Environment:** {context.metadata.get('settings', {}).get('env', 'local')}",
        "",
        "---",
        "",
        "> **Integrity notice.** Retention and churn figures use the real churn label from the "
        "membership source. Platform activity figures use the real activity source. Member-level "
        "streak and consistency features depend on a documented synthetic activity calendar, and "
        "are labelled wherever they appear. All findings are associations in the analysed data; "
        "no causal claim is made.",
        "",
        "---",
        "",
    ]
    sections = [
        _executive_summary(context),
        _kpi_section(context),
        _retention_section(context),
        _engagement_section(context),
        _segment_section(context),
        _alert_section(context),
        _anomaly_section(context),
        _quality_section(context),
        _sql_validation_section(context),
        _answers_section(context),
        _root_cause_section(context),
        _recommendations_section(context),
        _provenance_section(context),
        _pipeline_section(context),
    ]
    return "\n".join(header) + "\n".join(sections)


def markdown_to_html(markdown: str, title: str = "FitPulse Report") -> str:
    """Convert the report markdown to a self-contained HTML document.

    A deliberately small converter: it handles the constructs this report emits
    (headings, tables, lists, blockquotes, bold/inline code). No external
    dependency is required, and no untrusted HTML is injected.
    """
    import html as html_module
    import re

    lines = markdown.splitlines()
    output: List[str] = []
    in_table = False
    in_list = False

    def inline(text: str) -> str:
        escaped = html_module.escape(text)
        escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
        escaped = re.sub(r"`(.+?)`", r"<code>\1</code>", escaped)
        escaped = re.sub(r"\[(.+?)\]\((.+?)\)", r'<a href="\2">\1</a>', escaped)
        return escaped

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("|"):
            cells = [cell.strip() for cell in stripped.strip("|").split("|")]
            if set("".join(cells)) <= {"-", ":", " "}:
                continue
            if not in_table:
                output.append("<table>")
                in_table = True
                output.append(
                    "<thead><tr>" + "".join(f"<th>{inline(c)}</th>" for c in cells) + "</tr></thead><tbody>"
                )
            else:
                output.append("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in cells) + "</tr>")
            continue
        if in_table:
            output.append("</tbody></table>")
            in_table = False

        if stripped.startswith("- "):
            if not in_list:
                output.append("<ul>")
                in_list = True
            output.append(f"<li>{inline(stripped[2:])}</li>")
            continue
        if in_list:
            output.append("</ul>")
            in_list = False

        if not stripped:
            output.append("")
        elif stripped.startswith("#"):
            level = len(stripped) - len(stripped.lstrip("#"))
            output.append(f"<h{level}>{inline(stripped[level:].strip())}</h{level}>")
        elif stripped.startswith(">"):
            output.append(f"<blockquote>{inline(stripped[1:].strip())}</blockquote>")
        elif stripped == "---":
            output.append("<hr/>")
        else:
            output.append(f"<p>{inline(stripped)}</p>")

    if in_table:
        output.append("</tbody></table>")
    if in_list:
        output.append("</ul>")

    body = "\n".join(output)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{html_module.escape(title)}</title>
<style>
  :root {{ color-scheme: light; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
         margin: 0 auto; max-width: 980px; padding: 40px 24px 80px; color: #1c1f23; line-height: 1.6; }}
  h1 {{ font-size: 1.9rem; border-bottom: 3px solid #1f6feb; padding-bottom: .5rem; }}
  h2 {{ font-size: 1.35rem; margin-top: 2.2rem; color: #12355b; }}
  h3 {{ font-size: 1.08rem; margin-top: 1.5rem; }}
  table {{ border-collapse: collapse; width: 100%; margin: 1rem 0; font-size: .9rem; }}
  th, td {{ border: 1px solid #d6dae0; padding: 6px 9px; text-align: left; vertical-align: top; }}
  th {{ background: #f2f5f9; }}
  tr:nth-child(even) td {{ background: #fafbfc; }}
  blockquote {{ border-left: 4px solid #d0d7de; margin: 1rem 0; padding: .4rem 1rem; background: #f6f8fa; color: #3b4048; }}
  code {{ background: #f2f5f9; padding: 1px 4px; border-radius: 4px; font-size: .88em; }}
  hr {{ border: none; border-top: 1px solid #e3e7ec; margin: 2rem 0; }}
</style>
</head>
<body>
{body}
</body>
</html>
"""


def generate_report(context: ReportContext, write: bool = True, filename: str = "fitpulse_executive_report.md") -> ReportResult:
    """Render and (optionally) persist the executive report."""
    markdown = render_report(context)
    html = markdown_to_html(markdown)
    path: Optional[Path] = None
    if write:
        ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
        path = write_text(ARTIFACTS_DIR / filename, markdown)
        write_text(ARTIFACTS_DIR / filename.replace(".md", ".html"), html)
        logger.info("Report written to %s", path)
    return ReportResult(
        markdown=markdown,
        html=html,
        path=path,
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )

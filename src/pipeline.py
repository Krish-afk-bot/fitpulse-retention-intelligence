"""FitPulse end-to-end pipeline.

Stages
------
``INGEST → PROFILE → VALIDATE → CLEAN → INTEGRATE → FEATURES → LOAD SQL →
ANALYZE → VALIDATE (Python↔SQL) → ALERTS → REPORT``

The pipeline is a plain Python call: the CLI wrapper
(:mod:`scripts.pipeline`) and the Streamlit dashboard both drive it, so the UI
never contains business logic of its own.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from .alerts import alert_summary, evaluate_alerts
from .analytics import (
    analyse_retention,
    answer_all_questions,
    answers_frame,
    attendance_contrast,
    behavioural_drop_off,
    churn_correlations,
    correlation_caveat,
    correlation_matrix,
    detect_all_anomalies,
    engagement_score_profile,
    engagement_summary,
    engagement_vs_retention,
    describe_distribution,
    funnel_insight,
    headline_kpis,
    kpi_catalogue_frame,
    kpi_display_frame,
    member_lifecycle_funnel,
    monthly_retention_cohorts,
    numeric_distribution,
    platform_daily_trend,
    platform_funnel,
    platform_kpis,
    platform_monthly_trend,
    platform_weekly_trend,
    root_cause_analysis,
    root_cause_frame,
    segment_metrics,
    segmentation_report,
    streak_distribution,
    time_series_summary,
    workout_type_mix,
)
from .cleaning import (
    CleaningResult,
    clean_activity_source,
    clean_membership_source,
    observation_date_from,
)
from .common.config import (
    ARTIFACTS_DIR,
    DB_PATH,
    PROCESSED_DIR,
    SQL_DIR,
    get_settings,
)
from .common.io_utils import write_csv, write_json, write_text
from .common.logging_utils import StageLogger, get_logger, stage_records, write_stage_log
from .features import build_member_features, build_platform_activity, build_real_member_features
from .features.streaks import streak_features_for_groups
from .ingestion import (
    CAPABILITY_LABELS,
    IngestionError,
    LoadedSource,
    load_dataset_path,
    load_sources,
    reference_source,
)
from .ingestion.data_dictionary import dictionary_csv, dictionary_markdown
from .integration import integrate_sources, integration_summary_frame
from .reporting import ReportContext, generate_report
from .sql_layer import (
    apply_schema,
    apply_views,
    compare_kpis,
    compare_tables,
    connect,
    integrity_checks,
    load_tables,
    run_script_library,
    validation_summary,
)
from .validation import (
    profile_frame,
    profile_summary_frame,
    summarize_quality,
    validate_canonical_fact_workout,
    validate_canonical_membership,
    validate_loaded_sources,
)

logger = get_logger("pipeline")

MODE_FULL = "full"
MODE_ACTIVITY_ONLY = "activity_only"
MODE_MEMBERSHIP_ONLY = "membership_only"

MODE_LABELS = {
    MODE_FULL: "Activity + membership",
    MODE_ACTIVITY_ONLY: "Activity only",
    MODE_MEMBERSHIP_ONLY: "Membership only",
}


def capability_map_by_dict(capabilities: List[Dict[str, Any]]) -> Dict[str, bool]:
    return {str(item.get("key")): bool(item.get("available")) for item in capabilities or []}


def _mode_label(has_activity: bool, has_membership: bool) -> str:
    if has_activity and has_membership:
        return MODE_FULL
    if has_activity:
        return MODE_ACTIVITY_ONLY
    return MODE_MEMBERSHIP_ONLY


def _load_reference_sources(
    activity_path: Optional[Path], membership_path: Optional[Path]
) -> Dict[str, LoadedSource]:
    """Load the documented reference sources, or explicit path overrides.

    Each file is still described by the mapping engine so the reference path
    reports the same capabilities as any other dataset.
    """
    sources: Dict[str, LoadedSource] = {}
    for role, path in (("activity", activity_path), ("membership", membership_path)):
        try:
            sources[role] = load_dataset_path(path, role=role) if path else reference_source(role)
        except (IngestionError, FileNotFoundError) as exc:
            logger.warning("Reference source '%s' unavailable: %s", role, exc)
    if not sources:
        sources = load_sources()
    return sources


def merge_source_capabilities(sources: Dict[str, LoadedSource]) -> List[Dict[str, Any]]:
    """Merge per-dataset capabilities into the product-level capability list."""
    merged: Dict[str, Dict[str, Any]] = {}
    reasons: Dict[str, List[str]] = {}
    for source in sources.values():
        for capability in source.capabilities or []:
            key = str(capability.get("key"))
            existing = merged.get(key)
            if existing is None or (capability.get("available") and not existing.get("available")):
                merged[key] = dict(capability)
            if not capability.get("available") and capability.get("reason"):
                reasons.setdefault(key, []).append(str(capability["reason"]))
    both = len({name for name in sources if name in {"activity", "membership"}}) == 2
    order = list(CAPABILITY_LABELS)
    for key, capability in merged.items():
        if key in ("integration", "sql_validation"):
            capability["available"] = both
            capability["reason"] = (
                "both sources loaded" if both else "requires both an activity and a membership source"
            )
        elif not capability.get("available"):
            capability["reason"] = "; ".join(dict.fromkeys(reasons.get(key, [])))
    return sorted(merged.values(), key=lambda item: order.index(item["key"]) if item["key"] in order else 99)


def dataset_report(sources: Dict[str, LoadedSource]) -> List[Dict[str, Any]]:
    """Per-dataset detection, mapping and compatibility statements."""
    rows: List[Dict[str, Any]] = []
    for name, source in sources.items():
        compatibility = source.compatibility or {}
        rows.append(
            {
                "role": name,
                "label": source.dataset_label or name,
                "origin": source.origin,
                "rows": source.rows,
                "columns": source.columns,
                "source_columns": source.source_columns,
                "compatibility_score": compatibility.get("score"),
                "compatibility_status": compatibility.get("status"),
                "missing_required": compatibility.get("missing_required", []),
                "missing_optional": compatibility.get("missing_optional", []),
                "detected_type": (compatibility.get("role_label") or name),
                "confidence": (source.mapping or {}).get("detection", {}).get("confidence")
                if source.mapping
                else None,
                "mapping": source.mapping,
                "assumptions": source.assumptions,
                "warnings": compatibility.get("warnings", []),
                "is_reference": source.is_reference,
            }
        )
    return rows


def _key_candidates(source: LoadedSource) -> List[str]:
    """Member-key columns to test during profiling, from the mapping when known."""
    mapping = source.mapping or {}
    matches = mapping.get("matches") or {}
    member = matches.get("member_id") or {}
    if member.get("column"):
        return [str(member["column"])]
    return ["member_id"] if source.name == "activity" else ["Member_ID"]


@dataclass
class PipelineResult:
    """Everything the pipeline produced, ready for the UI, SQL and reports."""

    tables: Dict[str, pd.DataFrame] = field(default_factory=dict)
    kpis: Dict[str, Any] = field(default_factory=dict)
    analyses: Dict[str, Any] = field(default_factory=dict)
    validation: Dict[str, Any] = field(default_factory=dict)
    integration: Dict[str, Any] = field(default_factory=dict)
    alerts: pd.DataFrame = field(default_factory=pd.DataFrame)
    quality: Dict[str, Any] = field(default_factory=dict)
    answers: List[Any] = field(default_factory=list)
    profiles: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    stage_records: List[Dict[str, Any]] = field(default_factory=list)
    report_markdown: str = ""
    db_path: Optional[Path] = None
    errors: List[str] = field(default_factory=list)
    #: Product-level capabilities derived from the loaded datasets. Analyses that
    #: the data cannot support are absent here and are never invented downstream.
    capabilities: List[Dict[str, Any]] = field(default_factory=list)
    #: Per-dataset detection/compatibility statements for the UI.
    dataset_report: List[Dict[str, Any]] = field(default_factory=list)

    # -- capability helpers used by the dashboard --------------------------
    def supports(self, capability: str) -> bool:
        """Whether the loaded data supports an analysis.

        Artifact bundles written before capabilities were recorded return
        ``True`` so an older bundle keeps working; a recorded capability is
        always authoritative.
        """
        mapping = capability_map_by_dict(self.capabilities)
        if not mapping:
            return True
        return mapping.get(capability, False)

    def capability_reason(self, capability: str) -> str:
        for item in self.capabilities:
            if item.get("key") == capability:
                return str(item.get("reason") or "")
        return ""

    @property
    def mode(self) -> str:
        return str(self.metadata.get("mode", "full"))

    # -- convenience accessors used by the dashboard -----------------------
    def table(self, name: str) -> pd.DataFrame:
        return self.tables.get(name, pd.DataFrame())

    def analysis(self, name: str, default: Any = None) -> Any:
        return self.analyses.get(name, default)

    @property
    def ok(self) -> bool:
        return bool(self.kpis) and not self.errors

    def as_dict(self) -> Dict[str, Any]:
        return {
            "metadata": self.metadata,
            "kpis": self.kpis,
            "quality": self.quality,
            "validation": {
                k: (v if not isinstance(v, pd.DataFrame) else v.to_dict("records"))
                for k, v in self.validation.items()
            },
            "integration": self.integration,
            "stage_records": self.stage_records,
            "errors": self.errors,
        }


def _python_kpi_payload(
    kpis: Dict[str, Any], members: pd.DataFrame, validation_reports, fact_workout
) -> Dict[str, Any]:
    """Assemble every value needed by the Python↔SQL cross-validation."""
    payload = dict(kpis)
    if not members.empty:
        churned = members[members["is_churned"].astype(bool)]
        retained = members[~members["is_churned"].astype(bool)]
        payload.update(
            {
                "churned_avg_visits": round(float(pd.to_numeric(churned["visits_per_month"], errors="coerce").mean()), 6),
                "retained_avg_visits": round(float(pd.to_numeric(retained["visits_per_month"], errors="coerce").mean()), 6),
                "churned_avg_duration": round(
                    float(pd.to_numeric(churned["avg_workout_duration_min"], errors="coerce").mean()), 6
                ),
                "retained_avg_duration": round(
                    float(pd.to_numeric(retained["avg_workout_duration_min"], errors="coerce").mean()), 6
                ),
                "churned_avg_recency": round(float(pd.to_numeric(churned["recency_days"], errors="coerce").mean()), 6),
                "retained_avg_recency": round(float(pd.to_numeric(retained["recency_days"], errors="coerce").mean()), 6),
            }
        )
    if fact_workout is not None and not fact_workout.empty:
        payload.setdefault("platform_attended_sessions", int(fact_workout["is_present"].sum()))
    quality = summarize_quality(validation_reports)
    payload["quality_pass_rate"] = quality.get("pass_rate")
    payload["quality_failures"] = quality.get("failures")
    return payload


def run_pipeline(
    activity_path: Optional[Path] = None,
    membership_path: Optional[Path] = None,
    write_artifacts: bool = True,
    build_database: bool = True,
    source_frames: Optional[Dict[str, pd.DataFrame]] = None,
    source_labels: Optional[Dict[str, str]] = None,
    sources: Optional[Dict[str, LoadedSource]] = None,
) -> PipelineResult:
    """Run the FitPulse pipeline.

    The pipeline adapts to the datasets it is given. Either or both conceptual
    sources may be supplied; analyses that need a source that is not present are
    reported as unavailable instead of being estimated.

    Parameters
    ----------
    activity_path / membership_path:
        Optional overrides for the raw CSV locations.
    write_artifacts:
        Persist curated tables, JSON summaries and the markdown report.
    build_database:
        Build the SQLite warehouse and run the SQL analysis stage (both sources).
    source_frames:
        Pre-loaded, already-canonical sources keyed by role.
    source_labels:
        Friendly origin labels for uploaded files, recorded in provenance.
    sources:
        Mapped :class:`LoadedSource` objects keyed by role. This is the path used
        by the dashboard's schema-mapping upload workflow.
    """
    settings = get_settings()
    result = PipelineResult()
    result.metadata = {
        "settings": settings.as_dict(),
        "observation_date": None,
        "source_labels": source_labels or {},
    }

    # ------------------------------------------------------------ INGEST
    with StageLogger("INGESTION") as stage:
        if sources is None:
            sources = (
                dict(source_frames)
                if source_frames is not None
                else _load_reference_sources(activity_path, membership_path)
            )
        sources = {
            name: source
            for name, source in sources.items()
            if source is not None and len(source.frame) > 0
        }
        if not sources:
            raise IngestionError(
                "No usable dataset was supplied. Upload an activity and/or a membership dataset, "
                "or run the pipeline on the bundled reference sources."
            )
        has_activity = "activity" in sources
        has_membership = "membership" in sources
        total_rows = sum(source.rows for source in sources.values())
        result.metadata["mode"] = _mode_label(has_activity, has_membership)
        result.metadata["mode_label"] = MODE_LABELS[result.metadata["mode"]]
        stage.records(processed=total_rows).note(
            sources={name: source.rows for name, source in sources.items()},
            mode=result.metadata["mode"],
        )
        result.metadata["sources"] = {name: source.as_dict() for name, source in sources.items()}
        result.capabilities = merge_source_capabilities(sources)
        result.dataset_report = dataset_report(sources)
        result.metadata["capabilities"] = result.capabilities
        result.analyses = empty_analyses()
        stage.note(capabilities=[item["key"] for item in result.capabilities if item["available"]])

    # ------------------------------------------------------------ PROFILE
    with StageLogger("PROFILING") as stage:
        for name, source in sources.items():
            profile = profile_frame(
                source.frame,
                name=f"{name} ({source.dataset_label})",
                key_candidates=_key_candidates(source),
            )
            result.profiles[name] = profile
            result.tables[f"profile_{name}"] = profile_summary_frame(profile)
        stage.records(processed=sum(len(p.get("column_profile", [])) for p in result.profiles.values())).note(
            profiles=list(result.profiles)
        )

    # ----------------------------------------------------------- VALIDATE
    with StageLogger("VALIDATION") as stage:
        source_reports = validate_loaded_sources(sources)
        quality = summarize_quality(list(source_reports.values()))
        stage.records(processed=quality["total_checks"]).note(
            status=quality["status"], warnings=quality["warnings"], failures=quality["failures"]
        )
        if quality["failures"]:
            stage.warn(f"{quality['failures']} hard validation failure(s) detected in source data")

    # -------------------------------------------------------------- CLEAN
    activity_clean: Optional[CleaningResult] = None
    membership_clean: Optional[Dict[str, CleaningResult]] = None
    dim_member_result: Optional[CleaningResult] = None
    fact_membership_result: Optional[CleaningResult] = None
    with StageLogger("CLEANING") as stage:
        if has_activity:
            activity_clean = clean_activity_source(sources["activity"])
        if has_membership:
            membership_clean = clean_membership_source(sources["membership"])
            dim_member_result = membership_clean["dim_member"]
            fact_membership_result = membership_clean["fact_membership"]
        activity_rows = len(activity_clean.frame) if activity_clean else 0
        member_rows = len(dim_member_result.frame) if dim_member_result else 0
        removed = (activity_clean.duplicates_removed if activity_clean else 0) + (
            dim_member_result.duplicates_removed if dim_member_result else 0
        )
        stage.records(processed=activity_rows + member_rows, failed=removed).note(
            activity_rows=activity_rows, members=member_rows
        )
        result.metadata["cleaning"] = {
            key: value
            for key, value in {
                "activity": activity_clean.as_dict() if activity_clean else None,
                "dim_member": dim_member_result.as_dict() if dim_member_result else None,
                "fact_membership": fact_membership_result.as_dict() if fact_membership_result else None,
            }.items()
            if value is not None
        }

    # ------------------------------------- post-clean canonical validation
    with StageLogger("VALIDATION (canonical)") as stage:
        canonical_reports = []
        if activity_clean is not None:
            canonical_reports.append(validate_canonical_fact_workout(activity_clean.frame))
        if fact_membership_result is not None:
            canonical_reports.append(validate_canonical_membership(fact_membership_result.frame))
        stage.records(processed=sum(len(report.checks) for report in canonical_reports)).note(
            reports={report.dataset: report.status for report in canonical_reports}
        )
        all_reports = list(source_reports.values()) + canonical_reports
        quality = summarize_quality(all_reports)

    if activity_clean is not None:
        result.tables["fact_workout"] = activity_clean.frame
    if dim_member_result is not None:
        result.tables["dim_member"] = dim_member_result.frame
    if fact_membership_result is not None:
        result.tables["fact_membership"] = fact_membership_result.frame
    result.quality = {
        "summary": quality,
        "reports": [report.as_dict() for report in all_reports],
        "report_frames": {report.dataset: report.to_frame() for report in all_reports},
        "checks": pd.concat(
            [report.to_frame() for report in all_reports], ignore_index=True
        )
        if all_reports
        else pd.DataFrame(),
    }

    # ---------------------------------------------------------- INTEGRATE
    integration = None
    empty_activity = CleaningResult(name="activity", frame=pd.DataFrame())
    if has_membership:
        with StageLogger("INTEGRATION") as stage:
            integration = integrate_sources(
                sources["activity"].frame if has_activity else pd.DataFrame(),
                sources["membership"].frame,
                activity_clean if activity_clean is not None else empty_activity,
                dim_member_result,
                fact_membership_result,
                seed=settings.random_seed,
            )
            stage.records(processed=int(integration.synthetic_layer.rows if integration.synthetic_layer else 0))
            stage.note(
                verdict=integration.key_analysis.verdict if integration.key_analysis else None,
                synthetic_events=integration.synthetic_layer.rows if integration.synthetic_layer else 0,
            )
            if integration.status() == "WARNING":
                stage.warn(
                    "Sources share no legitimate member key; the documented synthetic integration "
                    "layer is used and clearly labelled."
                )
            result.integration = integration.as_dict()
            result.tables["fact_workout_synthetic"] = integration.fact_workout_synthetic
            result.tables["integration_quality"] = integration_summary_frame(integration)
            result.tables["key_candidates"] = (
                pd.DataFrame([integration.key_analysis.left.as_dict(), integration.key_analysis.right.as_dict()])
                if integration.key_analysis
                else pd.DataFrame()
            )
    else:
        result.integration = {
            "join_performed": False,
            "join_type": "none — no membership source loaded",
            "notes": [
                "Only an activity source was loaded, so there is nothing to integrate against. "
                "No member-level outcome can be derived from this dataset."
            ],
        }
        result.tables["fact_workout_synthetic"] = pd.DataFrame()

    # ----------------------------------------------------------- FEATURES
    if has_membership:
        observation_date = observation_date_from(sources["membership"])
    elif activity_clean is not None:
        observed = pd.to_datetime(activity_clean.frame["workout_date"], errors="coerce").dropna()
        observation_date = pd.Timestamp(observed.max()) if not observed.empty else pd.Timestamp("2025-12-31")
    else:  # pragma: no cover - defensive
        observation_date = pd.Timestamp("2025-12-31")
    result.metadata["observation_date"] = str(observation_date.date())

    real_features = pd.DataFrame()
    member_features = pd.DataFrame()
    member_activity_features = pd.DataFrame()
    feature_metadata: Dict[str, Any] = {
        "synthetic_feature_columns": [],
        "member_feature_columns": [],
        "feature_source": "none",
    }
    platform = {
        "daily": pd.DataFrame(),
        "monthly": pd.DataFrame(),
        "workout_type": pd.DataFrame(),
        "weekday": pd.DataFrame(),
        "hour": pd.DataFrame(),
    }

    with StageLogger("FEATURES") as stage:
        if has_membership:
            real_features = build_real_member_features(
                dim_member_result.frame, fact_membership_result.frame
            )
            member_features, feature_metadata = build_member_features(
                real_features, integration.fact_workout_synthetic, reference_date=observation_date
            )
            feature_metadata["feature_source"] = "membership_source_plus_synthetic_calendar"
        elif activity_clean is not None and activity_clean.frame["member_id"].notna().any():
            # A repeatable member key: per-member streaks come from *real* events.
            member_activity_features = streak_features_for_groups(
                activity_clean.frame[["member_id", "workout_date"]],
                reference_date=observation_date,
            )
            member_activity_features["feature_source"] = "real_activity_events"
            feature_metadata = {
                "synthetic_feature_columns": [],
                "member_feature_columns": list(member_activity_features.columns),
                "feature_source": "real_activity_events",
            }
        if activity_clean is not None:
            platform = build_platform_activity(activity_clean.frame)
        stage.records(processed=len(member_features) + len(member_activity_features)).note(
            feature_source=feature_metadata["feature_source"],
            feature_columns=int(member_features.shape[1]) if not member_features.empty else 0,
            synthetic_feature_columns=len(feature_metadata["synthetic_feature_columns"]),
        )
        result.tables.update(
            {
                "member_features": member_features,
                "member_real_features": real_features,
                "member_activity_features": member_activity_features,
                "platform_daily_activity": platform["daily"],
                "platform_monthly_activity": platform["monthly"],
                "platform_workout_type": platform["workout_type"],
                "platform_weekday": platform["weekday"],
                "platform_hour": platform["hour"],
            }
        )
        result.metadata["features"] = feature_metadata

    members = result.tables.get("member_features", pd.DataFrame())
    fact_workout = result.tables.get("fact_workout", pd.DataFrame())
    platform_daily = result.tables.get("platform_daily_activity", pd.DataFrame())
    platform_monthly = result.tables.get("platform_monthly_activity", pd.DataFrame())
    synthetic_events = result.tables.get("fact_workout_synthetic", pd.DataFrame())
    member_activity = result.tables.get("member_activity_features", pd.DataFrame())

    capabilities = capability_map_by_dict(result.capabilities)
    has_churn = capabilities.get("retention_analysis", False)
    has_platform_events = capabilities.get("activity_analysis", False)
    skipped_reasons = {
        item["key"]: item.get("reason", "") for item in result.capabilities if not item["available"]
    }

    # ------------------------------------------------------------ ANALYZE
    analyses: Dict[str, Any] = dict(result.analyses)
    unavailable: List[Dict[str, str]] = []

    def _try(label: str, compute, default):
        """Run an optional analysis, recording (never hiding) a failure."""
        try:
            return compute()
        except Exception as exc:  # noqa: BLE001 - reported and surfaced, never fatal
            logger.warning("Analysis '%s' could not be computed: %s", label, exc)
            unavailable.append({"analysis": label, "reason": str(exc)})
            return default

    with StageLogger("ANALYTICS") as stage:
        if not members.empty:
            kpis = headline_kpis(
                members,
                platform_daily=platform_daily,
                fact_workout=fact_workout,
                inactivity_threshold_days=settings.alert_thresholds.inactivity_days,
            )
            kpis["synthetic_events"] = int(len(synthetic_events))
            kpis["synthetic_members"] = (
                int(synthetic_events["member_id"].nunique()) if not synthetic_events.empty else 0
            )
        else:
            # Activity-only dataset: report platform activity, never implied retention.
            kpis = platform_kpis(platform_daily, fact_workout, member_activity)
        result.kpis = kpis

        # --- member / retention analytics (need a real churn outcome) ---------
        if not members.empty and has_churn:
            retention = analyse_retention(members)
            analyses["retention"] = retention
            analyses["segmentation"] = segmentation_report(members)
            analyses["cohorts"] = _try(
                "monthly_retention_cohorts", lambda: monthly_retention_cohorts(members), pd.DataFrame()
            )
            analyses["lifecycle_funnel"] = _try(
                "member_lifecycle_funnel", lambda: member_lifecycle_funnel(members), pd.DataFrame()
            )
            analyses["drop_off"] = _try(
                "behavioural_drop_off", lambda: behavioural_drop_off(members), {}
            )
            analyses["engagement_bands"] = _try(
                "engagement_vs_retention", lambda: engagement_vs_retention(members), pd.DataFrame()
            )
            analyses["correlations"] = {
                "pearson": _try(
                    "correlation_matrix(pearson)", lambda: correlation_matrix(members, method="pearson"), pd.DataFrame()
                ),
                "spearman": _try(
                    "correlation_matrix(spearman)", lambda: correlation_matrix(members, method="spearman"), pd.DataFrame()
                ),
                "churn": _try("churn_correlations", lambda: churn_correlations(members), pd.DataFrame()),
                "caveat": correlation_caveat(),
            }
            analyses["root_cause_chains"] = _try(
                "root_cause_analysis",
                lambda: root_cause_analysis(members, platform_monthly, retention.comparison),
                [],
            )
        else:
            reason = skipped_reasons.get("retention_analysis") or skipped_reasons.get(
                "churn_analysis", "requires a churn/retention outcome"
            )
            for key in (
                "retention",
                "segmentation",
                "cohorts",
                "lifecycle_funnel",
                "drop_off",
                "engagement_bands",
                "correlations",
                "root_cause_chains",
            ):
                unavailable.append({"analysis": key, "reason": reason})

        # --- engagement profiles (need member-level measures) ----------------
        if not members.empty:
            analyses["score_profile"] = _try(
                "engagement_score_profile", lambda: engagement_score_profile(members), pd.DataFrame()
            )
            analyses["streak_distribution"] = _try(
                "streak_distribution", lambda: streak_distribution(members), pd.DataFrame()
            )

        # --- platform analytics (need the activity source) -------------------
        if has_platform_events:
            analyses["daily_trend"] = platform_daily_trend(platform_daily)
            analyses["monthly_trend"] = platform_monthly_trend(platform_monthly)
            analyses["weekly_trend"] = platform_weekly_trend(platform_daily)
            analyses["trend_summary"] = time_series_summary(platform_daily, analyses["monthly_trend"])
            analyses["platform_funnel"] = platform_funnel(fact_workout)
            analyses["attendance_contrast"] = _try(
                "attendance_contrast", lambda: attendance_contrast(fact_workout), pd.DataFrame()
            )
            analyses["workout_type_mix"] = _try(
                "workout_type_mix",
                lambda: workout_type_mix(result.tables.get("platform_workout_type", pd.DataFrame())),
                pd.DataFrame(),
            )
        else:
            reason = skipped_reasons.get("activity_analysis", "no event-level activity records")
            for key in (
                "daily_trend",
                "monthly_trend",
                "weekly_trend",
                "trend_summary",
                "platform_funnel",
                "attendance_contrast",
                "workout_type_mix",
            ):
                unavailable.append({"analysis": key, "reason": reason})

        # --- cross-cutting -----------------------------------------------
        analyses["anomalies"] = _try(
            "detect_all_anomalies",
            lambda: detect_all_anomalies(platform_daily, analyses["monthly_trend"], members),
            pd.DataFrame(),
        )
        analyses["engagement"] = _try(
            "engagement_summary",
            lambda: engagement_summary(members, platform_daily, fact_workout),
            {},
        )
        analyses["funnel_insight"] = _try(
            "funnel_insight",
            lambda: funnel_insight(analyses["platform_funnel"], analyses["lifecycle_funnel"]),
            "",
        )

        distribution_series: Dict[str, pd.Series] = {}
        if not members.empty and "visits_per_month" in members.columns:
            distribution_series["visits_per_month"] = members["visits_per_month"]
        if not members.empty and "engagement_score" in members.columns:
            distribution_series["engagement_score"] = members["engagement_score"]
        if "duration_minutes" in fact_workout.columns:
            distribution_series["duration"] = fact_workout["duration_minutes"]
        if not members.empty and "longest_streak" in members.columns:
            distribution_series["longest_streak"] = members["longest_streak"]
        analyses["distributions"] = {
            name: numeric_distribution(series) for name, series in distribution_series.items()
        }
        analyses["distribution_stats"] = {
            name: describe_distribution(series) for name, series in distribution_series.items()
        }
        analyses["unavailable"] = unavailable

        stage.records(processed=int(len(members) + len(fact_workout))).note(
            anomalies=len(analyses["anomalies"]), unavailable_analyses=len(unavailable)
        )
        result.analyses = analyses

    # ----------------------------------------------------------- SQL LOAD
    db_path = settings.db_path or DB_PATH
    has_sql = capabilities.get("sql_validation", False)
    if build_database and has_sql:
        with StageLogger("SQL LOAD") as stage:
            connection = connect(db_path)
            try:
                apply_schema(connection)
                pending = {
                    table: result.tables.get(table, pd.DataFrame())
                    for table in (
                        "dim_member",
                        "fact_membership",
                        "fact_workout",
                        "fact_workout_synthetic",
                        "member_features",
                        "platform_daily_activity",
                        "platform_monthly_activity",
                    )
                }
                pending["data_quality_checks"] = result.quality["checks"]
                for table, frame in list(pending.items()):
                    if not frame.empty and "segment_order" in frame.columns:
                        pending[table] = frame.drop(columns=["segment_order"])
                reports = load_tables(connection, pending)
                apply_views(connection)
                stage.records(processed=sum(report.rows_loaded for report in reports)).note(
                    tables=len(reports)
                )
            finally:
                connection.close()
        result.db_path = db_path
    elif build_database:
        result.metadata["sql_skipped"] = (
            "The SQL warehouse is built when both an activity and a membership source are "
            "available. With a single source there is nothing to cross-validate without "
            "comparing unrelated tables."
        )
        logger.info("SQL stage skipped: %s", result.metadata["sql_skipped"])

    # ------------------------------------------------------------- ALERTS
    with StageLogger("ALERTS") as stage:
        alerts_frame = pd.DataFrame()
        if not members.empty or has_platform_events:
            try:
                alerts_frame = evaluate_alerts(
                    members=members,
                    segment_metrics=segment_metrics(members) if has_churn else pd.DataFrame(),
                    platform_daily=platform_daily,
                    platform_monthly=platform_monthly,
                    fact_workout=fact_workout,
                    validation_reports=all_reports,
                    anomalies=result.analyses["anomalies"],
                    thresholds=settings.alert_thresholds,
                )
            except Exception as exc:  # noqa: BLE001 - an absent outcome must not fail the run
                logger.warning("Alerts could not be evaluated on this dataset: %s", exc)
                stage.warn(f"Alert evaluation unavailable: {exc}")
                result.analyses.setdefault("unavailable", []).append(
                    {"analysis": "alerts", "reason": str(exc)}
                )
        result.alerts = alerts_frame
        summary = alert_summary(alerts_frame)
        stage.records(processed=len(alerts_frame)).note(
            **{key: summary[key] for key in ("high", "medium", "low")}
        )
        if summary["high"]:
            stage.warn(f"{summary['high']} high-severity alert(s) open")
        result.analyses["alert_summary"] = summary

    # Persist alerts so the SQL layer can validate them.
    if build_database:
        connection = connect(db_path)
        try:
            if not alerts_frame.empty:
                load_tables(connection, {"alerts": alerts_frame})
        finally:
            connection.close()

    # -------------------------------------------------- VALIDATE (py vs SQL)
    sql_results: Dict[str, pd.DataFrame] = {}
    crosscheck = pd.DataFrame()
    integrity = pd.DataFrame()
    with StageLogger("VALIDATION-SQL") as stage:
        if build_database and has_sql:
            connection = connect(db_path)
            try:
                kpi_payload = _python_kpi_payload(kpis, members, all_reports, fact_workout)
                crosscheck = compare_kpis(connection, kpi_payload)
                integrity = integrity_checks(connection)
                sql_results = run_script_library(connection, SQL_DIR)
            finally:
                connection.close()
        else:
            stage.note(skipped="SQL validation requires both sources")
        validation = validate_sql_stage(sql_results, crosscheck, integrity, result)
        stage.records(processed=len(crosscheck)).note(status=validation["summary"]["status"])
        result.validation = validation
        if not crosscheck.empty and (crosscheck["status"] == "FAIL").any():
            stage.fail(
                f"{int((crosscheck['status'] == 'FAIL').sum())} KPI(s) differ between Python and "
                "SQL beyond tolerance"
            )

    # ------------------------------------------------------------ ANSWERS
    retention_analysis = result.analyses.get("retention")
    if retention_analysis is not None and not members.empty:
        answers = answer_all_questions(
            members=members,
            comparison=retention_analysis.comparison,
            segments=result.analyses["segmentation"]["metrics"],
            platform_monthly=platform_monthly,
            trend_summary=result.analyses["trend_summary"],
            platform_funnel_table=result.analyses["platform_funnel"],
            alerts=result.alerts,
            thresholds=settings.alert_thresholds.as_dict(),
        )
    else:
        answers = []
        result.analyses.setdefault("unavailable", []).append(
            {
                "analysis": "analytical_questions",
                "reason": "the analytical questions compare member outcomes, which this dataset does not provide",
            }
        )
    result.answers = answers
    result.analyses["answers"] = answers_frame(answers) if answers else pd.DataFrame()

    # ------------------------------------------------------------- REPORT
    with StageLogger("REPORTING") as stage:
        try:
            context = build_report_context(result, sources, all_reports, crosscheck, integrity)
            report = generate_report(context, write=write_artifacts)
            markdown, path = report.markdown, report.path
        except Exception as exc:  # noqa: BLE001 - a partial dataset still deserves a report
            logger.warning("Full report unavailable (%s); generating the capability report.", exc)
            markdown, path = _partial_report(result), None
            if write_artifacts:
                write_text(ARTIFACTS_DIR / "fitpulse_executive_report.md", markdown)
        result.report_markdown = markdown
        stage.records(processed=len(markdown.splitlines())).note(
            chars=len(markdown), path=str(path) if path else None
        )

    # ------------------------------------------------------------ OUTPUTS
    # Collect the stage telemetry *before* persisting, so the stage log inside
    # the artifact bundle is the complete run log rather than an empty list.
    result.stage_records = [record.as_dict() for record in stage_records()]
    if write_artifacts:
        persisted = persist_outputs(result)
        result.metadata["artifacts"] = persisted
        write_stage_log(ARTIFACTS_DIR / "pipeline_stage_log.json")
    logger.info("Pipeline finished | members=%s | alerts=%s", f"{len(members):,}", len(result.alerts))
    return result


def validate_sql_stage(
    sql_results: Dict[str, pd.DataFrame],
    crosscheck: pd.DataFrame,
    integrity: pd.DataFrame,
    result: PipelineResult,
) -> Dict[str, Any]:
    """Assemble the Python↔SQL validation payload, including table comparisons."""
    table_checks: List[pd.DataFrame] = []

    members = result.tables.get("member_features", pd.DataFrame())
    sql_segments = sql_results.get("segment_metrics", pd.DataFrame())
    if not members.empty and not sql_segments.empty:
        table_checks.append(
            compare_tables(
                result.analyses["segmentation"]["metrics"],
                sql_segments,
                key_columns=["segment"],
                columns={
                    "members": "members",
                    "churned": "churned",
                    "retained": "retained",
                    "churn_rate": "churn_rate_pct",
                    "retention_rate": "retention_rate_pct",
                    "avg_visits_per_month": "avg_visits_per_month",
                    "avg_longest_streak": "avg_longest_streak",
                    "avg_consistency": "avg_consistency",
                },
                label="segment_metrics",
            )
        )

    sql_tiers = sql_results.get("churn_by_membership_type", pd.DataFrame())
    if not members.empty and not sql_tiers.empty:
        python_tiers = (
            members.groupby("membership_type")
            .agg(
                members=("member_id", "count"),
                churned=("is_churned", "sum"),
                avg_visits_per_month=("visits_per_month", "mean"),
            )
            .reset_index()
        )
        python_tiers["churn_rate_pct"] = (100.0 * python_tiers["churned"] / python_tiers["members"]).round(6)
        table_checks.append(
            compare_tables(
                python_tiers,
                sql_tiers,
                key_columns=["membership_type"],
                columns={
                    "members": "members",
                    "churned": "churned",
                    "churn_rate_pct": "churn_rate_pct",
                    "avg_visits_per_month": "avg_visits_per_month",
                },
                label="churn_by_membership_type",
            )
        )

    sql_types = sql_results.get("activity_by_workout_type", pd.DataFrame())
    python_types = result.tables.get("platform_workout_type", pd.DataFrame())
    if not python_types.empty and not sql_types.empty:
        python_types_local = python_types.copy()
        python_types_local["attendance_rate_pct"] = (100.0 * python_types_local["present_rate"]).round(6)
        table_checks.append(
            compare_tables(
                python_types_local,
                sql_types,
                key_columns=["workout_type"],
                columns={
                    "events": "sessions",
                    "present_count": "attended_sessions",
                    "attendance_rate_pct": "attendance_rate_pct",
                    "avg_duration": "avg_duration_minutes",
                },
                label="activity_by_workout_type",
            )
        )

    table_frame = pd.concat(table_checks, ignore_index=True) if table_checks else pd.DataFrame()

    # Pipeline-stage health is evaluated in Python (the stage log only becomes
    # complete after the SQL queries have run) and appended to the integrity table.
    stage_failures = [
        record.get("stage") for record in (result.stage_records or []) if record.get("status") == "FAIL"
    ]
    stage_row = pd.DataFrame(
        [
            {
                "check": "No failed pipeline stages",
                "check_id": "pipeline.stage_failures",
                "observed": len(stage_failures),
                "expected": 0,
                "status": "PASS" if not stage_failures else "FAIL",
                "detail": "" if not stage_failures else f"Failed stages: {stage_failures}",
            }
        ]
    )
    integrity = pd.concat([integrity, stage_row], ignore_index=True) if integrity is not None and not integrity.empty else stage_row

    return {
        "crosscheck": crosscheck,
        "integrity": integrity,
        "table_checks": table_frame,
        "summary": validation_summary(crosscheck, integrity),
    }


def build_report_context(
    result: PipelineResult,
    sources: Dict[str, Any],
    validation_reports: List[Any],
    crosscheck: pd.DataFrame,
    integrity: pd.DataFrame,
) -> ReportContext:
    """Gather everything the report renderer needs."""
    return ReportContext(
        kpis=result.kpis,
        retention=result.analyses["retention"].summary,
        retention_comparison=result.analyses["retention"].comparison,
        segment_metrics=result.analyses["segmentation"]["metrics"],
        segment_insight=result.analyses["segmentation"]["insight"],
        trend_summary=result.analyses["trend_summary"],
        monthly_trend=result.analyses["monthly_trend"],
        engagement=result.analyses["engagement"],
        anomalies=result.analyses["anomalies"],
        alerts=result.alerts,
        alert_summary=result.analyses["alert_summary"],
        quality=result.quality["summary"],
        quality_checks=result.quality["checks"],
        crosscheck=crosscheck,
        integrity=integrity,
        answers=result.answers,
        root_causes=result.analyses["root_cause_chains"],
        integration=result.integration,
        funnel=result.analyses["platform_funnel"],
        funnel_insight=result.analyses["funnel_insight"],
        sources={name: source.as_dict() for name, source in sources.items()},
        metadata=result.metadata,
        stage_records=result.stage_records,
    )


def persist_outputs(result: PipelineResult) -> Dict[str, Any]:
    """Write curated tables, JSON summaries and the report to disk."""
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    written: Dict[str, Any] = {"csv": [], "json": []}

    csv_tables = [
        "dim_member",
        "fact_membership",
        "fact_workout",
        "fact_workout_synthetic",
        "member_features",
        "platform_daily_activity",
        "platform_monthly_activity",
        "platform_workout_type",
        "platform_weekday",
        "platform_hour",
        "integration_quality",
        "key_candidates",
    ]
    for name in csv_tables:
        frame = result.tables.get(name)
        if frame is None or frame.empty:
            continue
        write_csv(PROCESSED_DIR / f"{name}.csv", frame)
        written["csv"].append(name)

    if not result.alerts.empty:
        write_csv(PROCESSED_DIR / "alerts.csv", result.alerts)
        written["csv"].append("alerts")

    if not result.quality["checks"].empty:
        write_csv(PROCESSED_DIR / "data_quality_checks.csv", result.quality["checks"])
        written["csv"].append("data_quality_checks")

    check_frame = result.validation.get("crosscheck", pd.DataFrame())
    if not check_frame.empty:
        write_csv(PROCESSED_DIR / "python_sql_validation.csv", check_frame)
        written["csv"].append("python_sql_validation")

    integrity = result.validation.get("integrity", pd.DataFrame())
    if not integrity.empty:
        write_csv(PROCESSED_DIR / "sql_integrity_checks.csv", integrity)
        written["csv"].append("sql_integrity_checks")

    table_checks = result.validation.get("table_checks", pd.DataFrame())
    if not table_checks.empty:
        write_csv(PROCESSED_DIR / "python_sql_table_validation.csv", table_checks)
        written["csv"].append("python_sql_table_validation")

    answers = result.analyses.get("answers", pd.DataFrame())
    if not answers.empty:
        write_csv(PROCESSED_DIR / "analytical_answers.csv", answers)
        written["csv"].append("analytical_answers")

    write_csv(PROCESSED_DIR / "data_dictionary.csv", dictionary_csv())
    written["csv"].append("data_dictionary")

    retention = result.analyses.get("retention")
    json_payloads = {
        "pipeline_metadata.json": result.metadata,
        "kpis.json": result.kpis,
        "capabilities.json": {
            "mode": result.mode,
            "mode_label": MODE_LABELS.get(result.mode, result.mode),
            "capabilities": result.capabilities,
            "datasets": result.dataset_report,
        },
        "quality_summary.json": result.quality["summary"],
        "validation_summary.json": result.validation.get("summary", {}),
        "integration_report.json": result.integration,
        "alert_summary.json": result.analyses.get("alert_summary", {}),
        "analytical_answers.json": [answer.as_dict() for answer in result.answers],
        "root_cause.json": [chain.as_dict() for chain in result.analyses.get("root_cause_chains") or []],
        "retention_summary.json": retention.summary if retention is not None else {},
        "engagement_summary.json": result.analyses.get("engagement", {}),
        "trend_summary.json": result.analyses.get("trend_summary", {}),
        "stage_log.json": result.stage_records,
    }
    for filename, payload in json_payloads.items():
        write_json(ARTIFACTS_DIR / filename, payload)
        written["json"].append(filename)

    if not result.alerts.empty:
        write_csv(ARTIFACTS_DIR / "alerts.csv", result.alerts)
        written["csv"].append("artifacts/alerts.csv")

    write_text(ARTIFACTS_DIR / "DATA_DICTIONARY.md", dictionary_markdown())
    written["markdown"] = ["DATA_DICTIONARY.md"]
    return written


# ---------------------------------------------------------------------------
# Artifact loading for the dashboard
# ---------------------------------------------------------------------------
def artifacts_available() -> bool:
    """Whether a completed pipeline run can be loaded from disk."""
    return (ARTIFACTS_DIR / "kpis.json").exists() and (PROCESSED_DIR / "member_features.csv").exists()


def load_artifacts() -> Optional[PipelineResult]:
    """Rehydrate a previous run for the dashboard (read-only)."""
    if not artifacts_available():
        return None

    def _json(name: str, default: Any) -> Any:
        path = ARTIFACTS_DIR / name
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))

    def _csv(name: str) -> pd.DataFrame:
        path = PROCESSED_DIR / f"{name}.csv"
        if not path.exists():
            return pd.DataFrame()
        frame = pd.read_csv(path)
        for column in ("workout_date", "activity_date", "join_date", "last_visit_date", "observation_date"):
            if column in frame.columns:
                frame[column] = pd.to_datetime(frame[column], errors="coerce")
        return frame

    result = PipelineResult()
    result.metadata = _json("pipeline_metadata.json", {})
    result.kpis = _json("kpis.json", {})
    capabilities = _json("capabilities.json", {})
    result.capabilities = capabilities.get("capabilities", []) or []
    result.dataset_report = capabilities.get("datasets", []) or []
    if capabilities.get("mode"):
        result.metadata.setdefault("mode", capabilities["mode"])
        result.metadata.setdefault("mode_label", capabilities.get("mode_label", capabilities["mode"]))
    result.alerts = _csv("alerts")
    result.integration = _json("integration_report.json", {})
    # ``stage_log.json`` is written inside the artifact bundle; older bundles
    # left it empty because telemetry was collected after persisting. Fall back
    # to the standalone stage log so the dashboard can always show the run log.
    result.stage_records = _json("stage_log.json", []) or _json("pipeline_stage_log.json", [])
    result.quality = {
        "summary": _json("quality_summary.json", {}),
        "checks": _csv("data_quality_checks"),
        "reports": [],
        "report_frames": {},
    }
    result.validation = {
        "summary": _json("validation_summary.json", {}),
        "crosscheck": _csv("python_sql_validation"),
        "integrity": _csv("sql_integrity_checks"),
        "table_checks": _csv("python_sql_table_validation"),
    }
    for name in (
        "dim_member",
        "fact_membership",
        "fact_workout",
        "fact_workout_synthetic",
        "member_features",
        "platform_daily_activity",
        "platform_monthly_activity",
        "platform_workout_type",
        "platform_weekday",
        "platform_hour",
        "integration_quality",
        "key_candidates",
    ):
        result.tables[name] = _csv(name)

    members = result.tables.get("member_features", pd.DataFrame())
    fact_workout = result.tables.get("fact_workout", pd.DataFrame())
    platform_daily = result.tables.get("platform_daily_activity", pd.DataFrame())
    platform_monthly = result.tables.get("platform_monthly_activity", pd.DataFrame())

    can_analyse_members = not members.empty and "is_churned" in members.columns and members[
        "is_churned"
    ].notna().any()
    if can_analyse_members:
        retention = analyse_retention(members)
        result.analyses = {
            "retention": retention,
            "segmentation": segmentation_report(members),
            "trend_summary": time_series_summary(platform_daily, platform_monthly_trend(platform_monthly)),
            "daily_trend": platform_daily_trend(platform_daily),
            "monthly_trend": platform_monthly_trend(platform_monthly),
            "weekly_trend": platform_weekly_trend(platform_daily),
            "cohorts": monthly_retention_cohorts(members),
            "platform_funnel": platform_funnel(fact_workout),
            "lifecycle_funnel": member_lifecycle_funnel(members),
            "drop_off": behavioural_drop_off(members),
            "anomalies": detect_all_anomalies(platform_daily, platform_monthly, members),
            "root_cause_chains": root_cause_analysis(members, platform_monthly, retention.comparison),
            "correlations": {
                "pearson": correlation_matrix(members, method="pearson"),
                "spearman": correlation_matrix(members, method="spearman"),
                "churn": churn_correlations(members),
                "caveat": correlation_caveat(),
            },
            "engagement": engagement_summary(members, platform_daily, fact_workout),
            "engagement_bands": engagement_vs_retention(members),
            "score_profile": engagement_score_profile(members),
            "workout_type_mix": workout_type_mix(result.tables.get("platform_workout_type", pd.DataFrame())),
            "attendance_contrast": attendance_contrast(fact_workout),
            "distributions": {
                "visits_per_month": numeric_distribution(members["visits_per_month"]),
                "engagement_score": numeric_distribution(members["engagement_score"]),
                "duration": numeric_distribution(fact_workout["duration_minutes"]),
                "longest_streak": numeric_distribution(members["longest_streak"]),
            },
            "distribution_stats": {
                "visits_per_month": describe_distribution(members["visits_per_month"]),
                "engagement_score": describe_distribution(members["engagement_score"]),
                "duration": describe_distribution(fact_workout["duration_minutes"]),
                "longest_streak": describe_distribution(members["longest_streak"]),
            },
            "streak_distribution": streak_distribution(members),
            "funnel_insight": funnel_insight(platform_funnel(fact_workout), member_lifecycle_funnel(members)),
            "alert_summary": alert_summary(result.alerts),
            "answers": pd.DataFrame(_json("analytical_answers.json", [])),
        }
    result.db_path = DB_PATH
    return result


def empty_analyses() -> Dict[str, Any]:
    """Empty analysis container so the UI can render a clean empty state."""
    return {
        "retention": None,
        "segmentation": {"metrics": pd.DataFrame(), "insight": "No data loaded."},
        "trend_summary": {},
        "daily_trend": pd.DataFrame(),
        "monthly_trend": pd.DataFrame(),
        "weekly_trend": pd.DataFrame(),
        "cohorts": pd.DataFrame(),
        "platform_funnel": pd.DataFrame(),
        "lifecycle_funnel": pd.DataFrame(),
        "drop_off": {},
        "anomalies": pd.DataFrame(),
        "root_cause_chains": [],
        "correlations": {"pearson": pd.DataFrame(), "spearman": pd.DataFrame(), "churn": pd.DataFrame(), "caveat": ""},
        "engagement": {},
        "engagement_bands": pd.DataFrame(),
        "score_profile": pd.DataFrame(),
        "workout_type_mix": pd.DataFrame(),
        "attendance_contrast": pd.DataFrame(),
        "distributions": {},
        "distribution_stats": {},
        "streak_distribution": pd.DataFrame(),
        "funnel_insight": "",
        "alert_summary": {"total": 0, "high": 0, "medium": 0, "low": 0, "status": "PASS", "headline": "No data loaded."},
        "answers": pd.DataFrame(),
        "unavailable": [],
    }


def _partial_report(result: PipelineResult) -> str:
    """Capability-aware report for a dataset that cannot support every section.

    Used when only one source is loaded: rather than printing empty sections or
    (worse) inventing numbers, the report states what was measured and what the
    loaded data cannot support.
    """
    kpis = result.kpis or {}
    mode_label = MODE_LABELS.get(result.mode, result.mode)
    lines: List[str] = [
        "# FitPulse — Data Capability Report",
        "",
        f"**Loaded data:** {mode_label}",
    ]
    observation = result.metadata.get("observation_date")
    if observation:
        lines.append(f"**Observation date:** {observation}")
    lines.append("")

    lines.append("## What was measured")
    measured = [
        ("Recorded sessions", kpis.get("platform_events")),
        ("Attendance rate (%)", kpis.get("platform_attendance_rate")),
        ("Total recorded hours", kpis.get("platform_total_recorded_hours")),
        ("Members", kpis.get("total_members")),
        ("Retention rate (%)", kpis.get("retention_rate")),
        ("Churn rate (%)", kpis.get("churn_rate")),
        ("Average visits per month", kpis.get("avg_visits_per_month")),
        ("Average engagement score", kpis.get("avg_engagement_score")),
        ("Average longest streak (days)", kpis.get("avg_longest_streak")),
    ]
    reported = [(label, value) for label, value in measured if value is not None]
    if reported:
        for label, value in reported:
            if isinstance(value, float):
                lines.append(f"- {label}: {value:,.2f}")
            else:
                lines.append(f"- {label}: {value:,}")
    else:
        lines.append("- No headline measures were available from the loaded data.")
    lines.append("")

    lines.append("## Available analyses")
    for item in result.capabilities:
        if item.get("available"):
            lines.append(f"- {item.get('label')}")
    lines.append("")

    unavailable = [item for item in result.capabilities if not item.get("available")]
    if unavailable:
        lines.append("## Not available with this dataset")
        for item in unavailable:
            reason = item.get("reason") or "not supported by the loaded data"
            lines.append(f"- {item.get('label')} — {reason}")
        lines.append("")

    quality = (result.quality or {}).get("summary", {})
    if quality:
        lines.append("## Data quality")
        lines.append(
            f"- Status: {quality.get('status', 'n/a')} — "
            f"{quality.get('passed', 0)} passed, {quality.get('warnings', 0)} warnings, "
            f"{quality.get('failures', 0)} failures across {quality.get('total_checks', 0)} checks."
        )
        lines.append("")

    lines.append("## Notes")
    for source in result.dataset_report:
        lines.append(
            f"- {source.get('label')}: {source.get('rows', 0):,} rows, "
            f"compatibility {source.get('compatibility_score', 'n/a')} "
            f"({source.get('compatibility_status', 'n/a')})."
        )
        for assumption in source.get("assumptions", []) or []:
            lines.append(f"  - Assumption: {assumption}")
    for note in kpis.get("notes", []) or []:
        lines.append(f"- {note}")
    lines.append("")
    lines.append(
        "_This report is generated from the loaded dataset only. Sections that need an "
        "activity source, a membership source or a churn outcome are listed above as "
        "unavailable rather than estimated._"
    )
    return "\n".join(lines)

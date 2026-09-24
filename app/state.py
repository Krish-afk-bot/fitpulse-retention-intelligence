"""Dashboard state and data access.

The UI never contains business logic. It loads either the artifacts produced by
``python scripts/pipeline.py`` or a run executed in-process from uploaded files,
and everything it renders comes from the analytical layer.

Session state (PRD §24) is initialised here so page modules stay declarative.
"""

from __future__ import annotations

import hashlib
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.alerts import alert_summary  # noqa: E402
from src.analytics import headline_kpis, retention_summary, segment_metrics  # noqa: E402
from src.common.config import get_settings, reload_settings  # noqa: E402
from src.ingestion import (  # noqa: E402
    ACTIVITY_SOURCE,
    MEMBERSHIP_SOURCE,
    ROLE_ACTIVITY,
    ROLE_MEMBERSHIP,
    ROLES,
    SUPPORTED_SUFFIXES,
    IngestionError,
    SchemaMismatchError,
    assess_compatibility,
    build_loaded_source,
    capability_map,
    detect_role,
    field_options_for_role,
    frame_from_upload,
    load_sources,
    reader_from_upload,
    suggest_mapping,
)
from src.pipeline import (  # noqa: E402
    PipelineResult,
    artifacts_available,
    empty_analyses,
    load_artifacts,
    run_pipeline,
)

SEGMENT_FILTER_OPTIONS = [
    "A - Highly Engaged",
    "B - Regular",
    "C - At Risk",
    "D - Dormant",
]

DEFAULT_FILTERS: Dict[str, Any] = {
    "membership_types": [],
    "genders": [],
    "age_groups": [],
    "segments": [],
    "member_status": ["Retained", "Churned"],
    "workout_types": [],
    "date_range": None,
    "inactivity_threshold": None,
    "churn_alert_threshold": None,
}


@dataclass
class PageContext:
    """Everything a page module needs, assembled once per rerun."""

    result: Optional[PipelineResult] = None
    view: DatasetView = field(default_factory=lambda: DatasetView())
    kpis: Dict[str, Any] = field(default_factory=dict)
    origin: Optional[str] = None

    @property
    def has_data(self) -> bool:
        return self.result is not None and not self.view.members.empty

    @property
    def capabilities(self) -> List[Dict[str, Any]]:
        return list(self.result.capabilities) if self.result is not None else []

    def supports(self, capability: str) -> bool:
        """Whether the loaded data can support an analysis."""
        if self.result is None:
            return False
        return self.result.supports(capability)

    def capability_reason(self, capability: str) -> str:
        if self.result is None:
            return "No dataset is loaded yet."
        return self.result.capability_reason(capability)

    @property
    def mode_label(self) -> str:
        if self.result is None:
            return "No data"
        return str(self.result.metadata.get("mode_label", self.result.mode))

    @property
    def datasets(self) -> List[Dict[str, Any]]:
        return list(self.result.dataset_report) if self.result is not None else []

    @property
    def available_capabilities(self) -> List[Dict[str, Any]]:
        return [item for item in self.capabilities if item.get("available")]

    @property
    def unavailable_capabilities(self) -> List[Dict[str, Any]]:
        return [item for item in self.capabilities if not item.get("available")]

    @property
    def is_activity_only(self) -> bool:
        return self.result is not None and self.result.mode == "activity_only"

    @property
    def has_outcome(self) -> bool:
        return self.supports("retention_analysis")


@dataclass
class DatasetView:
    """The analytical frames after global filters have been applied.

    Two filter domains are kept separate because the two sources are not
    joinable: member filters act on the membership model, activity filters act on
    the activity facts. Merging them would imply a relationship that does not
    exist in the data.
    """

    members_all: pd.DataFrame = field(default_factory=pd.DataFrame)
    members: pd.DataFrame = field(default_factory=pd.DataFrame)
    fact_workout_all: pd.DataFrame = field(default_factory=pd.DataFrame)
    fact_workout: pd.DataFrame = field(default_factory=pd.DataFrame)
    platform_daily: pd.DataFrame = field(default_factory=pd.DataFrame)
    member_filters_active: bool = False
    activity_filters_active: bool = False
    date_range_active: bool = False

    @property
    def empty(self) -> bool:
        return self.members.empty and self.fact_workout.empty


def init_session_state() -> None:
    """Initialise every piece of session state the app relies on."""
    st.session_state.setdefault("pipeline_result", None)
    st.session_state.setdefault("data_origin", None)
    st.session_state.setdefault("filters", dict(DEFAULT_FILTERS))
    st.session_state.setdefault("thresholds", None)
    st.session_state.setdefault("errors", [])
    st.session_state.setdefault("upload_processed", set())
    st.session_state.setdefault("report_email_note", None)
    # Upload drafts (file -> detected schema + suggested mapping) and the
    # mapping overrides the user has confirmed. Both are keyed by content hash so
    # two different files can never share a cached interpretation (PRD §34).
    st.session_state.setdefault("drafts", {})
    st.session_state.setdefault("draft_order", [])
    st.session_state.setdefault("mapping_overrides", {})
    st.session_state.setdefault("role_overrides", {})
    st.session_state.setdefault("dataset_signature", None)


# ---------------------------------------------------------------------------
# Dataset switching safety
# ---------------------------------------------------------------------------
def dataset_signature(sources: Dict[str, Any]) -> str:
    """Stable content signature of the loaded sources.

    Used as the cache/branch key so metrics, charts, alerts, SQL results and
    reports from one dataset can never be shown alongside another's.
    """
    digest = hashlib.sha1()
    for role in sorted(sources):
        source = sources[role]
        digest.update(role.encode("utf-8"))
        digest.update(str(source.rows).encode("utf-8"))
        digest.update("|".join(str(c) for c in source.source_columns or source.frame.columns).encode("utf-8"))
        try:
            digest.update(str(pd.util.hash_pandas_object(source.frame.head(500), index=False).sum()).encode("utf-8"))
        except Exception:  # noqa: BLE001 - hashing is best-effort
            pass
    return digest.hexdigest()[:16]


def clear_dataset_state() -> None:
    """Discard every dataset-derived value when the active dataset changes."""
    for key in (
        "pipeline_result",
        "data_origin",
        "active_alerts",
        "thresholds",
        "dataset_signature",
        "report_email_note",
    ):
        st.session_state.pop(key, None)
    st.session_state["filters"] = dict(DEFAULT_FILTERS)
    st.session_state["errors"] = []
    _cached_artifacts.clear()
    st.session_state.setdefault("thresholds", None)


def set_result(result: PipelineResult, origin: str, signature: str) -> None:
    """Install a result, clearing any previous dataset's derived state first."""
    previous = st.session_state.get("dataset_signature")
    if previous is not None and previous != signature:
        clear_dataset_state()
    st.session_state["pipeline_result"] = result
    st.session_state["data_origin"] = origin
    st.session_state["dataset_signature"] = signature
    st.session_state["errors"] = []


def settings_snapshot() -> Dict[str, Any]:
    settings = get_settings()
    return {
        "env": settings.env,
        "observation_date": settings.as_of_date,
        "random_seed": settings.random_seed,
        "engagement_weights": settings.engagement_weights.normalized().as_dict(),
        "segment_thresholds": settings.segment_thresholds.as_dict(),
        "alert_thresholds": settings.alert_thresholds.as_dict(),
        "db_path": str(settings.db_path),
    }


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def _cached_artifacts(_fingerprint: float) -> Optional[PipelineResult]:
    """Load pipeline artifacts (cached; invalidated by the artifact mtime)."""
    return load_artifacts()


def artifact_fingerprint() -> float:
    from src.common.config import ARTIFACTS_DIR

    path = ARTIFACTS_DIR / "kpis.json"
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def ensure_data(allow_autorun: bool = True) -> Tuple[Optional[PipelineResult], Optional[str]]:
    """Return the active pipeline result and an optional message for the UI.

    Order of preference: an in-session run (uploaded files) → artifacts on disk
    → (optionally) nothing, so the caller can render an empty state.
    """
    if st.session_state.get("pipeline_result") is not None:
        return st.session_state["pipeline_result"], st.session_state.get("data_origin")

    if artifacts_available():
        fingerprint = artifact_fingerprint()
        result = _cached_artifacts(fingerprint)
        if result is not None:
            set_result(
                result,
                "artifacts on disk (from the last pipeline run)",
                f"artifacts:{fingerprint}",
            )
            return result, st.session_state["data_origin"]
    return None, None


@dataclass
class DatasetDraft:
    """An uploaded file, detected, mapped and awaiting confirmation.

    Nothing is analysed until the user confirms the mapping, so an ambiguous
    column can never silently become a business metric.
    """

    key: str
    name: str
    frame: pd.DataFrame
    detected_role: str
    detection: Dict[str, Any]
    role: str
    mapping: Any = None
    report: Any = None

    @property
    def role_label(self) -> str:
        from src.ingestion import role_label

        return role_label(self.role)


# ---------------------------------------------------------------------------
# Upload drafts: detect -> map -> confirm
# ---------------------------------------------------------------------------
def _content_key(raw: bytes, name: str) -> str:
    return f"{name}:{len(raw)}:{hashlib.sha1(raw).hexdigest()[:12]}"


def _guess_role(frame: pd.DataFrame) -> str:
    """Detected role, falling back to the closer of the two conceptually."""
    detection = detect_role(frame)
    if detection.role in ROLES:
        return detection.role
    # Unknown file: pick the role whose required fields are at least present.
    return ROLE_MEMBERSHIP if _has_churn_like(frame) else ROLE_ACTIVITY


def _has_churn_like(frame: pd.DataFrame) -> bool:
    from src.ingestion import normalize_key

    keys = {normalize_key(column) for column in frame.columns}
    return bool(keys & {"churn", "churn_status", "is_churned", "churned", "cancelled", "active"})


def prepare_draft(uploaded_file: Any) -> DatasetDraft:
    """Read and interpret an uploaded file (cached by content hash)."""
    raw = uploaded_file.getvalue() if hasattr(uploaded_file, "getvalue") else uploaded_file.read()
    key = _content_key(raw, str(getattr(uploaded_file, "name", "upload")))
    cached = st.session_state["drafts"].get(key)
    if cached is not None:
        return cached

    frame, name = frame_from_upload(uploaded_file)
    role = _guess_role(frame)
    mapping = suggest_mapping(frame, role=role)
    report = assess_compatibility(frame, mapping)
    draft = DatasetDraft(
        key=key,
        name=name,
        frame=frame,
        detected_role=detect_role(frame).role,
        detection=detect_role(frame).as_dict(),
        role=role,
        mapping=mapping,
        report=report,
    )
    st.session_state["drafts"][key] = draft
    if key not in st.session_state["draft_order"]:
        st.session_state["draft_order"].append(key)
    return draft


def refresh_draft(draft: DatasetDraft, role: str, overrides: Dict[str, Optional[str]]) -> DatasetDraft:
    """Re-run detection/mapping/compatibility after a user correction."""
    mapping = suggest_mapping(draft.frame, role=role, overrides=overrides)
    report = assess_compatibility(draft.frame, mapping)
    draft.role = role
    draft.mapping = mapping
    draft.report = report
    st.session_state["drafts"][draft.key] = draft
    return draft


def clear_drafts() -> None:
    st.session_state["drafts"] = {}
    st.session_state["draft_order"] = []
    st.session_state["mapping_overrides"] = {}
    st.session_state["role_overrides"] = {}


def build_sources(
    drafts: List[DatasetDraft],
) -> Tuple[Dict[str, Any], List[str], List[str]]:
    """Turn confirmed drafts into pipeline sources.

    Returns ``(sources, warnings, blocking_errors)``. A dataset whose required
    fields are missing blocks the run rather than being forced through, because
    a forced mapping would produce analyses the data cannot support.
    """
    sources: Dict[str, Any] = {}
    warnings: List[str] = []
    blocking: List[str] = []

    for draft in drafts:
        overrides = st.session_state["mapping_overrides"].get(draft.key, {})
        role = st.session_state["role_overrides"].get(draft.key, draft.role)
        mapping = suggest_mapping(draft.frame, role=role, overrides=overrides)
        report = assess_compatibility(draft.frame, mapping)

        if report.missing_required:
            blocking.append(
                f"{draft.name}: required field(s) not matched "
                f"({', '.join(report.missing_required)}). Open the mapping editor and choose the "
                "correct column (or mark it unavailable)."
            )
            continue
        if mapping.role in sources:
            warnings.append(
                f"Only one {mapping.role} dataset can be active at a time; '{draft.name}' was ignored "
                f"in favour of the first {mapping.role} file."
            )
            continue

        source = build_loaded_source(
            draft.frame,
            mapping,
            report,
            label=draft.name,
            origin=f"uploaded file ({draft.name})",
        )
        sources[mapping.role] = source

    if not sources:
        blocking.append("No usable dataset was mapped. Review the detected schema and mapping.")
    return sources, warnings, blocking


def run_pipeline_in_session(
    activity_upload: Any = None,
    membership_upload: Any = None,
    write_artifacts: bool = False,
    build_database: bool = False,
    sources: Optional[Dict[str, Any]] = None,
    origin_label: Optional[str] = None,
) -> Tuple[Optional[PipelineResult], Optional[str]]:
    """Run the pipeline for mapped sources, uploaded files or the bundled files."""
    try:
        if sources is not None:
            if not sources:
                raise IngestionError("No dataset is available to run the pipeline on.")
            built = sources
            origin = origin_label or ", ".join(
                f"{role}: {source.dataset_label or role}" for role, source in built.items()
            )
        elif activity_upload is not None or membership_upload is not None:
            # Legacy two-slot upload: still routed through the mapping layer, so an
            # uploaded file no longer has to match the reference columns exactly.
            built = {}
            for role, upload in (
                (ROLE_ACTIVITY, activity_upload),
                (ROLE_MEMBERSHIP, membership_upload),
            ):
                if upload is None:
                    continue
                frame, _name = frame_from_upload(upload)
                mapping = suggest_mapping(frame, role=role)
                report = assess_compatibility(frame, mapping)
                if report.missing_required:
                    raise IngestionError(
                        f"The uploaded file does not match the expected schema for '{role}'. "
                        f"Missing required columns: {report.missing_required}. See Data Quality for details."
                    )
                built[role] = build_loaded_source(
                    frame,
                    mapping,
                    report,
                    label=getattr(upload, "name", role),
                    origin=f"uploaded file ({getattr(upload, 'name', role)})",
                )
                if role == ROLE_ACTIVITY:
                    built[role] = built[role]
            origin = "uploaded files (" + ", ".join(
                str(source.dataset_label) for source in built.values()
            ) + ")"
        else:
            built = None  # let the pipeline load the bundled reference sources
            origin = "bundled reference sources in data/raw"

        result = run_pipeline(
            write_artifacts=write_artifacts,
            build_database=build_database,
            sources=built,
        )
    except (IngestionError, SchemaMismatchError) as exc:
        st.session_state["errors"] = [str(exc)]
        return None, None
    except FileNotFoundError:
        st.session_state["errors"] = [
            "No dataset found in data/raw. Upload your own files, or run "
            "`python scripts/ingest.py` to download the public sources."
        ]
        return None, None
    except Exception as exc:  # noqa: BLE001 - the UI must never hard-crash
        st.session_state["errors"] = [f"Pipeline failed: {exc}"]
        return None, None

    signature = dataset_signature(built) if built else "reference"
    set_result(result, origin, signature)
    return result, origin


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------
def _in_filter(values: List[str], selection: List[str]) -> bool:
    return not selection or (values and any(v in selection for v in values))


def apply_filters(result: PipelineResult) -> DatasetView:
    """Apply the global filters, returning the filtered analytical frames."""
    filters = st.session_state.get("filters", dict(DEFAULT_FILTERS))
    members_all = result.table("member_features")
    fact_all = result.table("fact_workout")
    daily_all = result.table("platform_daily_activity")

    members = members_all.copy()
    member_active = False

    if not members.empty:
        if filters.get("membership_types"):
            members = members[members["membership_type"].isin(filters["membership_types"])]
            member_active = True
        if filters.get("genders"):
            members = members[members["gender"].isin(filters["genders"])]
            member_active = True
        if filters.get("age_groups"):
            members = members[members["age_group"].isin(filters["age_groups"])]
            member_active = True
        if filters.get("segments"):
            members = members[members["segment"].isin(filters["segments"])]
            member_active = True
        status = filters.get("member_status") or ["Retained", "Churned"]
        if set(status) != {"Retained", "Churned"}:
            member_active = True
            # ``is_churned`` is nullable: when the dataset has no churn outcome the
            # filter simply excludes those rows rather than asserting a value.
            outcome = members["is_churned"]
            if "Retained" in status and "Churned" not in status:
                members = members[outcome.eq(False)]
            elif "Churned" in status and "Retained" not in status:
                members = members[outcome.eq(True)]

    fact = fact_all.copy()
    daily = daily_all.copy()
    activity_active = False
    date_active = False

    # The date input starts on the full available range, so a selection equal to
    # the source bounds is not a filter and must not be reported as one.
    date_range = filters.get("date_range")
    bounds = _activity_bounds(daily_all)
    if date_range and len(date_range) == 2 and bounds:
        selected = (pd.Timestamp(date_range[0]).date(), pd.Timestamp(date_range[1]).date())
        date_active = selected != bounds

    if not fact.empty:
        if filters.get("workout_types"):
            fact = fact[fact["workout_type"].isin(filters["workout_types"])]
            activity_active = True
        if date_active:
            start, end = pd.Timestamp(date_range[0]), pd.Timestamp(date_range[1])
            fact = fact[(fact["workout_date"] >= start) & (fact["workout_date"] <= end)]
            activity_active = True

    if not daily.empty and date_active:
        start, end = pd.Timestamp(date_range[0]), pd.Timestamp(date_range[1])
        daily = daily[(daily["activity_date"] >= start) & (daily["activity_date"] <= end)]

    return DatasetView(
        members_all=members_all,
        members=members,
        fact_workout_all=fact_all,
        fact_workout=fact,
        platform_daily=daily,
        member_filters_active=member_active,
        activity_filters_active=activity_active,
        date_range_active=date_active,
    )


def _activity_bounds(daily: pd.DataFrame):
    """The full date window available in the activity source, as ``(start, end)``."""
    if daily is None or daily.empty or "activity_date" not in daily.columns:
        return None
    dates = pd.to_datetime(daily["activity_date"], errors="coerce").dropna()
    if dates.empty:
        return None
    return (dates.min().date(), dates.max().date())


def filtered_kpis(view: DatasetView, result: PipelineResult) -> Dict[str, Any]:
    """Recompute headline KPIs on the filtered population."""
    if view.members.empty:
        return result.kpis
    settings = get_settings()
    thresholds = st.session_state.get("thresholds") or settings.alert_thresholds
    kpis = headline_kpis(
        view.members,
        platform_daily=view.platform_daily,
        fact_workout=view.fact_workout,
        inactivity_threshold_days=thresholds.inactivity_days,
    )
    synthetic = result.table("fact_workout_synthetic")
    kpis["synthetic_events"] = int(len(synthetic)) if not synthetic.empty else 0
    kpis["synthetic_members"] = (
        int(synthetic["member_id"].nunique()) if not synthetic.empty else 0
    )
    return kpis


def filtered_retention(view: DatasetView):
    if view.members.empty:
        return None
    return retention_summary(view.members)


def filtered_segments(view: DatasetView) -> pd.DataFrame:
    if view.members.empty:
        return pd.DataFrame()
    return segment_metrics(view.members)


def filtered_alerts(view: DatasetView, result: PipelineResult) -> pd.DataFrame:
    """Re-evaluate alerts on the filtered population with the active thresholds."""
    from src.alerts import evaluate_alerts

    if view.members.empty:
        return result.alerts
    thresholds = st.session_state.get("thresholds") or get_settings().alert_thresholds
    anomalies = result.analysis("anomalies", pd.DataFrame())
    segment_table = filtered_segments(view)
    platform_monthly = result.table("platform_monthly_activity")
    return evaluate_alerts(
        members=view.members,
        segment_metrics=segment_table,
        platform_daily=view.platform_daily,
        platform_monthly=platform_monthly,
        fact_workout=view.fact_workout,
        validation_reports=[],
        anomalies=anomalies,
        thresholds=thresholds,
    )


def alert_counts(alerts: pd.DataFrame) -> Dict[str, Any]:
    return alert_summary(alerts)


def data_quality_status(result: PipelineResult) -> str:
    summary = (result.quality or {}).get("summary", {})
    return summary.get("status", "n/a")


def has_data(result: Optional[PipelineResult]) -> bool:
    return result is not None and not result.table("member_features").empty


def provenance_line(result: PipelineResult, key: str) -> str:
    integration = result.integration or {}
    if key == "synthetic":
        return (
            "Synthetic-dependent: consistency and streak metrics come from the documented "
            "synthetic activity calendar."
        )
    return "Real source data."


def reset_filters() -> None:
    st.session_state["filters"] = dict(DEFAULT_FILTERS)


def ensure_thresholds() -> Any:
    """Return active alert thresholds, initialised from configuration."""
    if st.session_state.get("thresholds") is None:
        st.session_state["thresholds"] = get_settings().alert_thresholds
    return st.session_state["thresholds"]


def reload_configuration() -> None:
    reload_settings()
    st.session_state["thresholds"] = None
    _cached_artifacts.clear()

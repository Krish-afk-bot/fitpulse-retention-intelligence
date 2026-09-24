"""Data sources: upload any compatible dataset, review the mapping, run FitPulse.

This page is the product's data-flexibility surface. It does not assume the
reference Kaggle files:

1. **Detect** — every uploaded file is classified (activity vs membership) with a
   confidence and the reasons behind it.
2. **Map** — headers are matched onto the canonical model with per-field
   confidence. Ambiguous or low-confidence matches are flagged, and the user can
   correct any field by hand or declare it unavailable.
3. **Assess** — a compatibility score plus the capability list states exactly
   which analyses the data can support.
4. **Run** — only then does the pipeline execute, and the dashboard adapts to the
   capabilities that were established here.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd
import streamlit as st

import state
from components import cards, layout
from src.ingestion import (
    CONFIDENCE_LABEL,
    ROLE_ACTIVITY,
    ROLE_MEMBERSHIP,
    SUPPORTED_SUFFIXES,
    assess_compatibility,
    capability_frame,
    field_options_for_role,
    role_label,
    suggest_mapping,
)
from styles.theme import COLORS

ROLE_OPTIONS: Dict[str, str] = {
    ROLE_ACTIVITY: "Activity / attendance (event rows)",
    ROLE_MEMBERSHIP: "Membership / member (one row per member)",
}


def _confidence_colour(confidence: str) -> str:
    return {
        "high": COLORS["success"],
        "medium": COLORS["warning"],
        "low": COLORS["danger"],
        "none": COLORS["muted"],
    }.get(str(confidence).lower(), COLORS["muted"])


def _current_dataset_panel(ctx) -> None:
    """What is loaded right now, and what it enables."""
    if ctx.result is None:
        layout.unavailable_state(
            "No dataset loaded",
            "FitPulse has no active dataset yet. Upload a fitness activity and/or membership "
            "export below, or run the pipeline on the bundled reference sources.",
            needs=[
                "Activity/attendance export with a date column (CSV, XLSX, XLS)",
                "Membership export with a member identifier and, for retention, a churn outcome",
            ],
            hint="Both are optional: an activity-only or membership-only dataset is analysed for "
            "what it can support.",
        )
        return

    rows = []
    for dataset in ctx.datasets:
        rows.append(
            {
                "source": dataset.get("label") or dataset.get("role"),
                "type": dataset.get("detected_type"),
                "rows": dataset.get("rows"),
                "columns": dataset.get("columns"),
                "compatibility": dataset.get("compatibility_score"),
                "status": dataset.get("compatibility_status"),
                "origin": dataset.get("origin"),
            }
        )
    columns = st.columns([2.1, 1.6, 1.1])
    with columns[0]:
        st.markdown(
            f'<p class="fp-eyebrow">Active dataset</p>'
            f'<p style="margin:0 0 .2rem;font-weight:600;font-size:1.05rem;">{ctx.mode_label}</p>'
            f'<p style="margin:0;font-size:.85rem;color:{COLORS["text_secondary"]};">'
            f"{ctx.origin or 'bundled sources'}</p>",
            unsafe_allow_html=True,
        )
    with columns[1]:
        total_sessions = int(len(ctx.result.table("fact_workout")))
        total_members = int(len(ctx.result.table("member_features")))
        st.markdown(
            f'<p class="fp-eyebrow">Volume</p>'
            f'<p style="margin:0;font-size:.9rem;color:{COLORS["text_secondary"]};">'
            f"{total_sessions:,} recorded sessions · {total_members:,} members with features</p>",
            unsafe_allow_html=True,
        )
    with columns[2]:
        available = len(ctx.available_capabilities)
        unavailable = len(ctx.unavailable_capabilities)
        st.markdown(
            f'<p class="fp-eyebrow">Capabilities</p>'
            f'<p style="margin:0;font-size:.9rem;color:{COLORS["text_secondary"]};">'
            f"{available} available · {unavailable} unavailable</p>",
            unsafe_allow_html=True,
        )

    if rows:
        with st.expander("Loaded files", expanded=False):
            st.dataframe(
                pd.DataFrame(rows),
                width="stretch",
                hide_index=True,
                column_config={
                    "compatibility": st.column_config.NumberColumn("Compatibility", format="%.0f%%"),
                },
            )

    layout.section(
        "Dataset capabilities",
        "Derived from the mapped columns — analyses that the data cannot support are listed as "
        "unavailable rather than estimated.",
        icon_name="shield-check",
    )
    _capability_matrix(ctx.result.capabilities)


def _capability_matrix(capabilities: List[Dict[str, Any]]) -> None:
    """Two columns: what is available, and what is not (with the reason)."""
    available = [item for item in capabilities if item.get("available")]
    unavailable = [
        item
        for item in capabilities
        if not item.get("available") and item.get("key") not in {"subscription_analysis", "revenue_analysis"}
    ]
    left, right = st.columns(2)
    with left:
        st.markdown(f'<p class="fp-eyebrow">Available</p>', unsafe_allow_html=True)
        layout.bullet_list(
            [f"{item.get('label')}" for item in available] or ["Nothing yet — load a dataset."],
            icon_name="circle-check",
            color=COLORS["success"],
        )
    with right:
        st.markdown(f'<p class="fp-eyebrow">Unavailable</p>', unsafe_allow_html=True)
        layout.bullet_list(
            [
                f"**{item.get('label')}** — {item.get('reason') or 'not supported by this data'}"
                for item in unavailable
            ]
            or ["Everything the product offers is supported by this data."],
            icon_name="circle-slash",
            color=COLORS["muted"],
        )


def _detection_card(draft, ctx) -> None:
    """One uploaded file: what it is, how well it maps, and how to fix it."""
    report = draft.report
    detection = draft.detection or {}
    st.markdown(
        "".join(
            [
                '<div class="fp-card">',
                f'<p class="fp-eyebrow">{draft.name}</p>',
                f'<p style="margin:.1rem 0 .35rem;font-weight:600;font-size:1rem;">'
                f"{role_label(draft.role)}</p>",
                f'<p style="margin:0;font-size:.85rem;color:{COLORS["text_secondary"]};">'
                f"{report.rows:,} rows × {report.columns} columns · compatibility "
                f'<span style="color:{COLORS["text"]};font-weight:600;">{report.score:.0f}%</span> '
                f"({report.status})</p>",
                '<div style="margin-top:.55rem;display:flex;gap:.4rem;flex-wrap:wrap;">',
                cards.chip(
                    "Detected",
                    role_label(detection.get("role", draft.role)),
                    icon_name="scan-search",
                    active=True,
                ),
                cards.chip(
                    "Confidence",
                    CONFIDENCE_LABEL.get(str(detection.get("confidence", "none")), "Not detected"),
                    icon_name="gauge",
                    color=_confidence_colour(str(detection.get("confidence", "none"))),
                ),
                cards.chip(
                    "Capabilities",
                    f"{len(report.available_capabilities)} available",
                    icon_name="shield-check",
                ),
                "</div>",
                "</div>",
            ]
        ),
        unsafe_allow_html=True,
    )

    if report.missing_required:
        st.error(
            "Required field(s) not matched: "
            + ", ".join(report.missing_required)
            + ". Choose the correct column in the mapping editor below."
        )
    for warning in report.warnings:
        st.warning(warning)
    for assumption in report.assumptions:
        st.caption(f"Assumption · {assumption}")

    with st.expander("Review mapping", expanded=bool(report.missing_required)):
        role_keys = list(ROLE_OPTIONS)
        role = st.selectbox(
            "Dataset role",
            options=role_keys,
            index=role_keys.index(draft.role) if draft.role in role_keys else 0,
            format_func=lambda value: ROLE_OPTIONS[value],
            key=f"role_{draft.key}",
        )

        overrides: Dict[str, Optional[str]] = dict(
            st.session_state["mapping_overrides"].get(draft.key, {})
        )
        mapping = suggest_mapping(draft.frame, role=role, overrides=overrides)

        column_options = ["(not available)"] + [str(column) for column in draft.frame.columns]
        edited = False
        for field in field_options_for_role(role):
            match = mapping.matches.get(field["name"])
            detected = match.column if match else None
            label = f"{field['label']}{' *' if field['required'] else ''}"
            default_index = column_options.index(detected) if detected in column_options else 0
            chosen = st.selectbox(
                label,
                options=column_options,
                index=default_index,
                help=(
                    f"{field['description']} "
                    f"{('Expected: ' + field['unit'] + '. ') if field['unit'] else ''}"
                    f"{field['business_meaning']}"
                ),
                key=f"map_{draft.key}_{field['name']}",
            )
            if chosen != "(not available)":
                if detected != chosen:
                    overrides[field["name"]] = chosen
                    edited = True
            elif detected is not None:
                overrides[field["name"]] = None
                edited = True

            if match and match.needs_confirmation:
                st.caption(
                    f"⚠ {match.label}: {match.confidence} confidence — "
                    + ("; ".join(match.notes) or "please confirm this column")
                )

        st.session_state["mapping_overrides"][draft.key] = overrides
        st.session_state["role_overrides"][draft.key] = role

        if edited:
            st.session_state["drafts"][draft.key] = state.refresh_draft(draft, role, overrides)
            st.rerun()

        reviewed = suggest_mapping(draft.frame, role=role, overrides=overrides)
        reviewed_report = assess_compatibility(draft.frame, reviewed)
        st.caption(
            f"This mapping gives a compatibility score of {reviewed_report.score:.0f}% "
            f"({reviewed_report.status}) and enables {len(reviewed_report.available_capabilities)} "
            f"capabilities."
        )
        with st.expander("Compatibility detail", expanded=False):
            st.dataframe(reviewed_report.as_frame(), width="stretch", hide_index=True)


def _upload_panel(ctx) -> None:
    st.markdown(
        f'<p style="margin:.2rem 0 .6rem;font-size:.88rem;color:{COLORS["text_secondary"]};">'
        "Upload your own fitness activity or membership export. Columns are detected and matched "
        "automatically — you confirm the mapping before anything is analysed. "
        f"Accepted formats: {', '.join(SUPPORTED_SUFFIXES)}.</p>",
        unsafe_allow_html=True,
    )
    files = st.file_uploader(
        "Add a data source",
        type=[suffix.lstrip(".") for suffix in SUPPORTED_SUFFIXES],
        accept_multiple_files=True,
        key="data_source_upload",
        help="Activity/attendance export, membership export, or both. One dataset per role.",
    )

    if not files:
        if st.session_state.get("drafts"):
            if st.button("Forget uploaded files", width="stretch"):
                state.clear_drafts()
                st.rerun()
        return

    drafts: List[Any] = []
    for uploaded in files:
        try:
            drafts.append(state.prepare_draft(uploaded))
        except Exception as exc:  # noqa: BLE001 - a bad file must not break the page
            st.error(f"{getattr(uploaded, 'name', 'file')}: {exc}")

    for draft in drafts:
        _detection_card(draft, ctx)

    if len(drafts) > 2:
        st.caption(
            "More than two files were uploaded. Only one activity dataset and one membership "
            "dataset can be active at a time."
        )

    st.markdown("")
    action_cols = st.columns([1.2, 1, 1])
    persist = st.checkbox(
        "Persist outputs to data/processed, artifacts and the SQL warehouse",
        value=False,
        help="Off by default, so an exploratory upload cannot overwrite the curated reference layer.",
    )
    with action_cols[0]:
        if st.button("Validate & run pipeline", type="primary", width="stretch"):
            sources, warnings, blocking = state.build_sources(drafts)
            for warning in warnings:
                st.warning(warning)
            if blocking:
                for error in blocking:
                    st.error(error)
                return
            with st.spinner("Mapping, validating, cleaning, integrating and analysing…"):
                result, origin = state.run_pipeline_in_session(
                    sources=sources,
                    write_artifacts=persist,
                    build_database=persist,
                    origin_label=", ".join(
                        f"{role}: {source.dataset_label}" for role, source in sources.items()
                    ),
                )
            if result is not None:
                st.success(f"Pipeline completed — {result.metadata.get('mode_label', result.mode)}.")
                st.rerun()
    with action_cols[1]:
        if st.button("Clear uploads", width="stretch"):
            state.clear_drafts()
            st.rerun()
    with action_cols[2]:
        if st.button("Use reference sources", width="stretch"):
            state.clear_drafts()
            with st.spinner("Running the pipeline on the bundled reference sources…"):
                state.run_pipeline_in_session(write_artifacts=False, build_database=False)
            st.rerun()

    for error in st.session_state.get("errors", []):
        st.error(error)


def render(ctx) -> None:
    layout.page_header(
        "Data sources",
        "FitPulse is not tied to one dataset. Any compatible fitness activity or membership export "
        "can be mapped onto the canonical model, and the dashboard adapts to what the data "
        "actually supports.",
        icon_name="database",
        eyebrow="Data",
    )
    layout.provenance_notes(ctx, expanded=False)

    _current_dataset_panel(ctx)
    layout.section(
        "Add a data source",
        "Detection, mapping and capability assessment run before any analysis.",
        icon_name="upload",
    )
    _upload_panel(ctx)

"""Sidebar filters and operational controls.

Filters are deliberately split into two domains, because the two sources share
no member key: member filters act on the membership model, activity filters act
on the activity facts. Merging them into one panel would imply a join that the
data does not support. The sidebar states this rather than quietly doing it.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd
import streamlit as st

from src.common.config import AlertThresholds, get_settings
from styles.theme import COLORS

from . import icons

import state


def _options(result, table: str, column: str) -> List[str]:
    frame = result.table(table) if result is not None else pd.DataFrame()
    if frame.empty or column not in frame.columns:
        return []
    return sorted(str(value) for value in frame[column].dropna().unique())


def active_filter_labels(filters: Dict[str, Any], date_range_active: bool = True) -> List[str]:
    """Human-readable list of the filters currently narrowing the population."""
    labels: List[str] = []
    for key, prefix in (
        ("membership_types", "membership"),
        ("genders", "gender"),
        ("age_groups", "age"),
        ("segments", "segment"),
        ("workout_types", "workout"),
    ):
        if filters.get(key):
            labels.append(f"{prefix}: {', '.join(filters[key])}")
    status = filters.get("member_status") or []
    if status and set(status) != {"Retained", "Churned"}:
        labels.append(f"outcome: {', '.join(status)}")
    if date_range_active and filters.get("date_range"):
        labels.append(f"dates: {filters['date_range'][0]} → {filters['date_range'][1]}")
    return labels


def render_global_filters(result, view=None) -> None:
    """Render the global filter controls, labelled with the active count."""
    filters = st.session_state.setdefault("filters", dict(state.DEFAULT_FILTERS))
    active = active_filter_labels(filters, date_range_active=getattr(view, "date_range_active", True))
    heading = "Filters" + (f" · {len(active)} active" if active else "")

    with st.sidebar.expander(heading, expanded=bool(active)):
        st.caption(
            "Member filters narrow the membership model. Activity filters narrow the activity "
            "source. They stay separate because the sources share no member key."
        )

        membership_types = _options(result, "member_features", "membership_type")
        genders = _options(result, "member_features", "gender")
        age_groups = _options(result, "member_features", "age_group")

        st.markdown(
            '<div class="fp-eyebrow" style="margin-top:.4rem;">Members</div>', unsafe_allow_html=True
        )
        filters["membership_types"] = st.multiselect(
            "Membership type",
            options=membership_types,
            default=filters.get("membership_types", []),
        )
        filters["genders"] = st.multiselect("Gender", options=genders, default=filters.get("genders", []))
        filters["age_groups"] = st.multiselect(
            "Age group", options=age_groups, default=filters.get("age_groups", [])
        )
        filters["segments"] = st.multiselect(
            "Engagement segment",
            options=state.SEGMENT_FILTER_OPTIONS,
            default=filters.get("segments", []),
        )
        filters["member_status"] = st.multiselect(
            "Outcome",
            options=["Retained", "Churned"],
            default=filters.get("member_status", ["Retained", "Churned"]),
        )

        workout_types = _options(result, "fact_workout", "workout_type")
        date_bounds = None
        daily = result.table("platform_daily_activity") if result is not None else pd.DataFrame()
        if not daily.empty and "activity_date" in daily.columns:
            dates = pd.to_datetime(daily["activity_date"], errors="coerce").dropna()
            if not dates.empty:
                date_bounds = (dates.min().date(), dates.max().date())

        st.markdown(
            '<div class="fp-eyebrow" style="margin-top:.8rem;">Activity</div>', unsafe_allow_html=True
        )
        if date_bounds:
            selection = st.date_input(
                "Session date range",
                value=(
                    filters["date_range"][0] if filters.get("date_range") else date_bounds[0],
                    filters["date_range"][1] if filters.get("date_range") else date_bounds[1],
                ),
                min_value=date_bounds[0],
                max_value=date_bounds[1],
            )
            if isinstance(selection, tuple) and len(selection) == 2:
                filters["date_range"] = selection
        else:
            st.caption("No activity date range available in the loaded data.")
        filters["workout_types"] = st.multiselect(
            "Workout type", options=workout_types, default=filters.get("workout_types", [])
        )

        if active:
            st.markdown(
                "".join(
                    f'<div style="font-size:.75rem;color:{COLORS["text_secondary"]};'
                    f'padding:.15rem 0;">· {label}</div>'
                    for label in active
                ),
                unsafe_allow_html=True,
            )

        if st.button("Clear all filters", width="stretch", disabled=not active):
            state.reset_filters()
            st.rerun()


def render_threshold_controls() -> AlertThresholds:
    """Configurable alert thresholds and score weights."""
    settings = get_settings()
    thresholds: AlertThresholds = state.ensure_thresholds()

    with st.sidebar.expander("Alert thresholds", expanded=False):
        st.caption(
            "Thresholds are product configuration, not statistically optimal cut points. Alerts "
            "re-evaluate immediately when these change."
        )
        thresholds.inactivity_days = st.slider(
            "Inactivity (days)", 1, 90, int(thresholds.inactivity_days)
        )
        thresholds.churn_rate_pct = st.slider(
            "Churn rate ceiling (%)", 1.0, 80.0, float(thresholds.churn_rate_pct), 1.0
        )
        thresholds.engagement_drop_pct = st.slider(
            "Engagement drop (%)", 5.0, 90.0, float(thresholds.engagement_drop_pct), 5.0
        )
        thresholds.activity_drop_pct = st.slider(
            "Activity drop (%)", 5.0, 90.0, float(thresholds.activity_drop_pct), 5.0
        )
        thresholds.missing_data_pct = st.slider(
            "Missing data (%)", 1.0, 60.0, float(thresholds.missing_data_pct), 1.0
        )
        st.caption(
            "Engagement-score weights come from configuration (.env) and are product-design "
            "assumptions, not validated causal weights: "
            + ", ".join(
                f"{key}={value:.2f}" for key, value in settings.engagement_weights.normalized().as_dict().items()
            )
        )
        if st.button("Reload configuration", width="stretch"):
            state.reload_configuration()
            st.rerun()
    return thresholds


def render_data_source_panel(result, origin: Optional[str]) -> None:
    """Compact data status. Uploading and schema mapping live on the Data sources page."""
    with st.sidebar.expander("Data source", expanded=result is None):
        if origin:
            st.markdown(
                "".join(
                    [
                        '<div style="display:flex;gap:.5rem;align-items:flex-start;">',
                        icons.icon("circle-check", size=15, color=COLORS["success"], extra_style="margin-top:.15rem;"),
                        f'<span style="font-size:.82rem;color:{COLORS["text_secondary"]};">'
                        f"{origin}</span>",
                        "</div>",
                    ]
                ),
                unsafe_allow_html=True,
            )
        if result is not None:
            available = sum(1 for item in result.capabilities if item.get("available"))
            unavailable = sum(
                1
                for item in result.capabilities
                if not item.get("available")
                and item.get("key") not in {"subscription_analysis", "revenue_analysis"}
            )
            st.caption(
                f"{result.metadata.get('mode_label', result.mode)} · Observation date "
                f"{result.metadata.get('observation_date', 'n/a')} · "
                f"{len(result.table('member_features')):,} members · "
                f"{len(result.table('fact_workout')):,} sessions · "
                f"{available} capabilities available"
                + (f", {unavailable} unavailable" if unavailable else "")
            )
        else:
            st.caption(
                "No dataset is loaded. Upload your own export on the **Data sources** page — "
                "columns are detected and mapped automatically — or run the bundled reference sources."
            )

        if st.button("Reload bundled reference sources", width="stretch"):
            with st.spinner("Running the pipeline on the bundled reference sources…"):
                state.run_pipeline_in_session(write_artifacts=False, build_database=False)
            st.rerun()

        for error in st.session_state.get("errors", []):
            st.error(error)

        st.caption("Upload, mapping review and capability checks: **Data sources** page (Data).")


# Backwards-compatible alias used by the previous shell.
def render_source_notes(result) -> None:
    from . import sidebar

    sidebar.render_source_notes(result)

"""Sidebar shell: brand lockup, data source panel, capability notes and footer.

The sidebar behaves like a SaaS product rail: brand at the top, navigation from
Streamlit's own router, then the operational controls (data source, filters,
thresholds), and finally a version footer. Anything that is *not* a control or
navigation lives in the main area.
"""

from __future__ import annotations

from typing import Any, Optional

import streamlit as st

from styles.theme import APP_NAME, APP_TAGLINE, APP_VERSION, COLORS

from . import icons


def render_brand() -> None:
    st.sidebar.markdown(
        "".join(
            [
                '<div class="fp-brand">',
                f'<span class="fp-brand-mark">{icons.icon("activity", size=20, color="#FFFFFF", stroke_width=2.4)}</span>',
                "<span>",
                f'<div class="fp-brand-name">{APP_NAME}</div>',
                f'<div class="fp-brand-tag">{APP_TAGLINE.upper()}</div>',
                "</span>",
                "</div>",
            ]
        ),
        unsafe_allow_html=True,
    )


def _status_colour(status: str) -> str:
    return {
        "PASS": COLORS["success"],
        "HEALTHY": COLORS["success"],
        "OK": COLORS["success"],
        "WARNING": COLORS["warning"],
        "FAIL": COLORS["danger"],
    }.get(str(status).upper(), COLORS["neutral"])


def render_footer(result: Any, origin: Optional[str], settings: dict) -> None:
    """Honest system state: pipeline health, observation date, version."""
    quality_status = "n/a"
    observation_date = settings.get("observation_date") or "n/a"
    if result is not None:
        quality_status = (result.quality or {}).get("summary", {}).get("status", "n/a")
        # The run records the observation date it actually used; the configured
        # default is only a fallback, so the footer always agrees with the analysis.
        observation_date = result.metadata.get("observation_date") or observation_date
    colour = _status_colour(quality_status)
    st.sidebar.markdown(
        "".join(
            [
                '<div class="fp-side-foot">',
                f'<span class="fp-name">{APP_NAME}</span> — {APP_TAGLINE}<br>',
                f'<span class="fp-dot" style="background:{colour};"></span>'
                f"Pipeline {quality_status if quality_status != 'n/a' else 'not run'}<br>",
                f"Observation date {observation_date}<br>",
                f"Source: {origin or 'none loaded'}<br>",
                f"{APP_VERSION} · prototype build",
                "</div>",
            ]
        ),
        unsafe_allow_html=True,
    )


def render_source_notes(result: Any) -> None:
    """State plainly what the loaded data can and cannot support."""
    if result is None:
        return
    members = result.table("member_features")
    fact = result.table("fact_workout")
    synthetic = result.table("fact_workout_synthetic")
    integration = result.integration or {}
    key = integration.get("key_analysis") or {}
    with st.sidebar.expander("What this data supports", expanded=False):
        st.markdown(
            f"- Membership source: **{len(members):,}** members with a real churn outcome\n"
            f"- Activity source: **{len(fact):,}** recorded sessions, **no member key**\n"
            f"- Synthetic bridge events: **{len(synthetic):,}**\n"
            "- Member-level streaks and consistency depend on the synthetic calendar\n"
            "- Renewal analysis is out of scope: no renewal event exists"
        )
        if key:
            st.caption(
                f"Integration verdict: **{str(key.get('verdict', 'n/a')).replace('_', ' ').lower()}**. "
                f"{key.get('recommendation', '')}"
            )

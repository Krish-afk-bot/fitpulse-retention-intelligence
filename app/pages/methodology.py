"""Methodology & data notes.

The evaluator-facing explanation of *how* FitPulse reaches its numbers: the
canonical model, the mapping and capability rules, the integration integrity
rules, the exact metric definitions, the synthetic-calendar disclosure and the
known limitations of the reference datasets. Everything here is read from the
code and configuration that actually produced the results, so it cannot drift
away from the implementation.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from components import layout
from src.common.config import get_settings
from src.features.engineer import SCORE_COMPONENTS, LIFECYCLE_CONFIG, score_reference_values
from src.ingestion import ACTIVITY_SOURCE, CANONICAL_FIELDS, MEMBERSHIP_SOURCE, ROLES
from styles.theme import COLORS, PROVENANCE

KAGGLE_SOURCES = (
    (
        "Dataset A — Activity / attendance",
        ACTIVITY_SOURCE.label,
        ACTIVITY_SOURCE.url,
        ACTIVITY_SOURCE.license,
        ACTIVITY_SOURCE.grain,
    ),
    (
        "Dataset B — Membership / churn",
        MEMBERSHIP_SOURCE.label,
        MEMBERSHIP_SOURCE.url,
        MEMBERSHIP_SOURCE.license,
        MEMBERSHIP_SOURCE.grain,
    ),
)


def _canonical_frame() -> pd.DataFrame:
    rows = []
    for field in CANONICAL_FIELDS:
        rows.append(
            {
                "canonical field": field.name,
                "label": field.label,
                "role": field.role,
                "expected shape": field.kind,
                "required": "required" if field.required else "optional",
                "unit": field.unit,
                "example aliases": ", ".join(field.aliases[:5]) + " …",
                "business meaning": field.business_meaning,
            }
        )
    return pd.DataFrame(rows)


def render(ctx) -> None:
    settings = get_settings()

    layout.page_header(
        "Methodology & data notes",
        "How FitPulse turns an arbitrary fitness dataset into retention intelligence — the "
        "canonical model, the integrity rules, the metric definitions and the limits of the data.",
        icon_name="book-open",
        eyebrow="Documentation",
    )

    layout.section(
        "The question FitPulse answers",
        "Which engagement behaviours are associated with members staying?",
        icon_name="target",
    )
    st.markdown(
        f'<p style="color:{COLORS["text_secondary"]};font-size:.92rem;">'
        "FitPulse joins workout/attendance activity with membership outcomes to describe the "
        "relationship between engagement and retention. Every statement in the product is "
        "descriptive: measures are reported as <em>associated with</em> outcomes, never as causal. "
        "Where the data cannot support a claim — no churn outcome, no renewal event, no repeatable "
        "member key — the capability is reported as unavailable instead of being estimated.</p>",
        unsafe_allow_html=True,
    )

    # ------------------------------------------------------------------ model
    layout.section(
        "Canonical data model",
        "Datasets are mapped onto these fields; the analytics layer only ever sees the canonical names.",
        icon_name="layers",
    )
    role_choice = st.radio(
        "Scope",
        options=["All fields"] + [f"{role} dataset" for role in ROLES],
        horizontal=True,
        key="methodology_role",
    )
    frame = _canonical_frame()
    if role_choice != "All fields":
        role = ROLES[[f"{r} dataset" for r in ROLES].index(role_choice)]
        frame = frame[frame["role"].isin([role, "shared"])]
    st.dataframe(frame, width="stretch", hide_index=True)

    # -------------------------------------------------------- detection rules
    layout.section(
        "Detection, mapping and capabilities",
        "A header is never trusted on its own — the values must also fit the field.",
        icon_name="scan-search",
    )
    st.markdown(
        """
- **Role detection** scores each file against the activity and membership field patterns
  (dates, attendance outcomes, churn, join/last-visit, visit frequency) and reports a
  confidence. An unrecognised file is labelled *unknown* and its role is chosen by the
  closest match, then flagged for review.
- **Header matching** is case-, space-, punctuation- and underscore-insensitive, so
  `Member ID`, `memberID` and `member_id` are the same field. Every canonical field carries
  an alias list, including `customer_id`/`user_id`/`client_id` for member identity and
  `churn`/`is_churned`/`cancelled` for the outcome.
- **Value plausibility** is checked before a match is accepted: a date field needs values
  that parse as dates, a numeric field needs numeric values, a flag needs two recognisable
  states. A well-named column with impossible values is penalised, not accepted.
- **Ambiguity is surfaced, not guessed.** If two columns compete for one field, or a flag's
  values cannot be interpreted confidently, the mapping is marked for confirmation and the
  user chooses in the Data sources page.
- **Two-state outcomes** (`churn`, `attended`, `active`, `no_show`, `cancelled`) are
  translated into an explicit Yes/No vocabulary, including when the header names the
  *opposite* state (an `active` flag is inverted to express churn).
- **Capabilities** are derived from the confirmed mapping. Missing fields remove
  capabilities — they never trigger invented data.
        """
    )

    # ------------------------------------------------------------- integrity
    layout.section(
        "Integration integrity",
        "Two sources are combined conceptually, never with a fabricated user-level join.",
        icon_name="shield-check",
    )
    st.markdown(
        """
- The two conceptual sources (**activity** and **membership**) are cleaned and modelled
  independently. No join is performed between them.
- Candidate keys are analysed before anything else: uniqueness, overlap and the row
  multiplication a naive join would produce. The verdict and its reasoning are recorded in
  the run metadata and shown on the Data Quality page.
- Member identifiers are **namespaced** (`M-…`, `A-…`) so a raw integer from one source can
  never silently match an unrelated integer in the other.
- A repeatable activity identifier is only used for member-level activity analysis when it
  genuinely repeats; a per-row sequence (as in the reference activity file) is treated as a
  record number, and member-level streaks are reported as unavailable from that source.
- Where the reference activity calendar is required, the **synthetic calendar** described
  below is used and labelled everywhere it appears.
        """
    )

    # ------------------------------------------------------------ provenance
    layout.section(
        "Provenance vocabulary",
        "Every measure carries one of three markers, with the definition available here.",
        icon_name="tag",
    )
    for key, spec in PROVENANCE.items():
        st.markdown(
            f'<p style="margin:.2rem 0;font-size:.9rem;">'
            f'<span style="color:{spec["color"]};font-weight:600;">{spec["label"]}</span> '
            f'<span style="color:{COLORS["text_secondary"]};">— {spec["detail"]}</span></p>',
            unsafe_allow_html=True,
        )

    # ------------------------------------------------------------- synthetic
    layout.section(
        "Synthetic analytical calendar",
        "What it is, why it exists, and what it does not change.",
        icon_name="calendar-clock",
    )
    st.markdown(
        """
The reference membership dataset publishes member-level aggregates (visit rate, average
duration, calories) but not the individual visits. To demonstrate multi-source integration
**and** to compute streak behaviour, FitPulse rebuilds an activity calendar for each member
from that member's *real* visit rate, deterministically (fixed seed from configuration).

- **Generated:** the dates of each member's visits.
- **Unchanged:** the visit rate that drives them, every duration/calorie measure, the
  membership attributes and the churn outcome.
- **Therefore:** consistency, streak and recency-derived-from-calendar columns depend on date
  placement and are labelled *Synthetic calendar*. They illustrate the method; they are not
  observed history.
- **Not used** anywhere an outcome claim is made: retention and churn come from the real
  churn label.
        """
    )

    # ---------------------------------------------------------- definitions
    layout.section(
        "Metric definitions",
        "The exact arithmetic behind the headline numbers.",
        icon_name="ruler",
    )
    weights = settings.engagement_weights.normalized().as_dict()
    st.markdown(
        f"""
- **Retention rate** = retained members ÷ members with a *recorded* churn outcome. Members
  without a recorded outcome are excluded from both numerator and denominator, and the
  coverage is stated.
- **Churn rate** = churned members ÷ members with a recorded churn outcome.
- **At-risk members** = members in the `At Risk` or `Dormant` engagement segments (thresholds
  below), not a churn prediction.
- **Platform attendance rate** = sessions with an attendance outcome of *Present* ÷ recorded
  sessions. Where the source records nominal duration for absent sessions, FitPulse also
  reports an attendance-gated *confirmed* measure beside every total.
- **Engagement score** (0-100, product-design weights — not validated causal weights):
  {' · '.join(f'{key} = {value:.2f}' for key, value in weights.items())}. Configured through
  environment variables.
        """
    )
    with st.expander("Engagement score components", expanded=False):
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "component": component.label,
                        "description": component.description,
                        "formula": component.formula,
                        "scaling reference": component.reference,
                    }
                    for component in SCORE_COMPONENTS
                ]
            ),
            width="stretch",
            hide_index=True,
        )
        st.caption(score_reference_values()["disclaimer"])

    with st.expander("Segmentation and alert thresholds", expanded=False):
        st.markdown(
            "**Behavioural segments** (engagement score bands, configurable):  \n"
            + " · ".join(f"`{k}` ≥ {v:g}" for k, v in settings.segment_thresholds.as_dict().items())
            + " · below the lowest threshold = `Dormant`."
        )
        st.markdown(
            "**Alert thresholds** (product configuration, not statistically optimal cut points):  \n"
            + " · ".join(f"`{k}` = {v:g}" for k, v in settings.alert_thresholds.as_dict().items())
        )
        st.markdown(
            "**Lifecycle stages** (activity-event count and consistency):  \n"
            + " · ".join(f"`{k}` = {v:g}" for k, v in LIFECYCLE_CONFIG.items())
        )

    # ------------------------------------------------------------ limits
    layout.section(
        "Known limitations of the reference data",
        "Stated by the sources themselves and surfaced throughout the product.",
        icon_name="triangle-alert",
    )
    st.markdown(f"**{ACTIVITY_SOURCE.label}**")
    for limitation in ACTIVITY_SOURCE.known_limitations:
        st.markdown(f"- {limitation}")
    st.markdown(f"**{MEMBERSHIP_SOURCE.label}**")
    for limitation in MEMBERSHIP_SOURCE.known_limitations:
        st.markdown(f"- {limitation}")
    st.markdown(
        "- **Subscription renewal** is out of scope for every supported dataset: renewal analysis "
        "requires renewal-event data, which the sources do not provide.\n"
        "- **Revenue** analysis is out of scope for the same reason: no payment field exists.\n"
        "- Results describe *associations* in the loaded data, not causal effects."
    )

    if ctx.result is not None:
        with st.expander("Assumptions applied to the currently loaded data", expanded=False):
            for dataset in ctx.datasets:
                st.markdown(f"**{dataset.get('label') or dataset.get('role')}**")
                for assumption in dataset.get("assumptions") or []:
                    st.markdown(f"- {assumption}")
                if not dataset.get("assumptions"):
                    st.markdown("- No dataset-specific assumptions were required.")

    # ----------------------------------------------------- attribution + run
    layout.section(
        "Dataset attribution",
        "FitPulse claims no ownership of the reference datasets.",
        icon_name="link",
    )
    for label, name, url, license_text, grain in KAGGLE_SOURCES:
        st.markdown(
            f"**{label}**  \n{name}  \n<{url}>  \n{grain}  \nLicense: {license_text}",
            unsafe_allow_html=True,
        )

    with st.expander("Running the pipeline yourself", expanded=False):
        st.code(
            "python scripts/ingest.py      # download the reference sources (optional)\n"
            "python scripts/pipeline.py    # full run: artifacts + SQL warehouse + report\n"
            "streamlit run app/streamlit_app.py\n"
            "pytest",
            language="bash",
        )
        st.caption(
            "The dashboard reads artifacts produced by the pipeline. Uploads run in-memory unless "
            "you tick *Persist outputs* on the Data sources page."
        )

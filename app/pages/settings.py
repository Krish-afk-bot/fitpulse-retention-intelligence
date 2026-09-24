"""Settings.

The effective configuration behind every score, segment and alert. Nothing here
is editable in the page itself — configuration lives in ``.env`` and the sidebar
controls — but everything that changes an analytical outcome is readable, so a
reviewer can see exactly which knobs were turned and to what.
"""

from __future__ import annotations

from typing import Any, Dict

import streamlit as st

from components import cards, layout, tables
from src.features import score_reference_values, segment_definition_frame

import state


def render(ctx) -> None:
    snapshot: Dict[str, Any] = state.settings_snapshot()

    layout.page_header(
        "Settings",
        "The effective configuration for this session: alert thresholds, engagement weights, "
        "segment cut points and runtime settings, all read from .env and the environment.",
        icon_name="settings",
        eyebrow="System",
    )

    _thresholds(snapshot)
    _weights(snapshot)
    _segments(snapshot)
    _runtime(snapshot)

    layout.section(
        "Reload configuration",
        "Configuration is read once per process. Reloading re-reads .env and clears cached artefacts.",
        icon_name="rotate-ccw",
    )
    if st.button("Reload configuration from .env", type="primary"):
        state.reload_configuration()
        st.caption("Configuration reloaded. Filter thresholds were reset to the configured values.")


# ---------------------------------------------------------------------------
def _thresholds(snapshot: Dict[str, Any]) -> None:
    layout.section(
        "Alert thresholds",
        "Product configuration, not statistically optimal cut points. These are the values the alert engine used for the current run.",
        icon_name="bell",
    )
    thresholds = snapshot.get("alert_thresholds") or {}
    if not thresholds:
        cards.empty_state(
            "No thresholds configured",
            "The alert engine has no thresholds to evaluate against.",
            icon_name="bell",
        )
        return
    labels = {
        "inactivity_days": "Inactivity (days)",
        "churn_rate_pct": "Churn rate ceiling (%)",
        "engagement_drop_pct": "Engagement drop (%)",
        "activity_drop_pct": "Activity drop (%)",
        "missing_data_pct": "Missing data (%)",
    }
    items = list(thresholds.items())
    for chunk in [items[index : index + 4] for index in range(0, len(items), 4)]:
        columns = st.columns(4)
        for column, (key, value) in zip(columns, chunk):
            with column:
                cards.stat_block(labels.get(key, key.replace("_", " ")), value)
    layout.action_hint(
        "Alerts re-evaluate immediately when the sidebar sliders move; the CLI pipeline uses the "
        "values configured in .env."
    )


def _weights(snapshot: Dict[str, Any]) -> None:
    layout.section(
        "Engagement score weights",
        "The composite score is a product-design construct. These weights are assumptions, not empirically validated causal weights.",
        icon_name="scale",
    )
    weights = snapshot.get("engagement_weights") or {}
    if weights:
        columns = st.columns(len(weights))
        for column, (key, value) in zip(columns, weights.items()):
            with column:
                cards.stat_block(key.title(), f"{float(value) * 100:.0f}%", detail="of the composite score")
    references = score_reference_values()
    if references:
        tables.key_value_table(
            [(key.replace("_", " "), value) for key, value in references.items()],
            caption="Component definitions as recorded by the pipeline for this run.",
        )


def _segments(snapshot: Dict[str, Any]) -> None:
    layout.section(
        "Segment cut points",
        "Score band boundaries that define the four behavioural segments.",
        icon_name="layers",
    )
    configured = snapshot.get("segment_thresholds") or {}
    if configured:
        columns = st.columns(len(configured))
        for column, (key, value) in zip(columns, configured.items()):
            with column:
                cards.stat_block(key.replace("_", " "), value)
    tables.render_table(
        segment_definition_frame(),
        caption="Segment definitions used to classify every member in the current run.",
    )


def _runtime(snapshot: Dict[str, Any]) -> None:
    layout.section(
        "Runtime configuration",
        "Where the pipeline reads from and writes to, and the reproducibility settings in force.",
        icon_name="server",
    )
    from src.common.config import ARTIFACTS_DIR, PROCESSED_DIR, SQL_DIR

    columns = st.columns(4)
    with columns[0]:
        cards.stat_block("Environment", snapshot.get("env"))
    with columns[1]:
        cards.stat_block("Observation date", snapshot.get("observation_date"))
    with columns[2]:
        cards.stat_block("Random seed", snapshot.get("random_seed"))
    with columns[3]:
        cards.stat_block("Database", "SQLite", detail=str(snapshot.get("db_path", "n/a")).split("\\")[-1].split("/")[-1])

    tables.key_value_table(
        [
            ("SQL warehouse", str(snapshot.get("db_path", "n/a"))),
            ("Artifacts directory", str(ARTIFACTS_DIR)),
            ("Processed data directory", str(PROCESSED_DIR)),
            ("SQL scripts", str(SQL_DIR)),
            ("Configuration source", ".env file plus process environment"),
            ("Secrets", "never rendered, never logged"),
        ],
        caption="Paths are shown for orientation; credentials are never displayed anywhere in the product.",
    )
    st.caption(
        "Report email delivery is configured with FITPULSE_SMTP_HOST, FITPULSE_REPORT_FROM and "
        "FITPULSE_REPORT_TO. The Reports page can check the delivery configuration without sending."
    )

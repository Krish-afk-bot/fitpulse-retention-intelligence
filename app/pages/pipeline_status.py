"""Pipeline Status.

Operational transparency: what ran, in what order, how long each stage took, how
many records it handled, and which artefacts exist on disk as a result. If a
number on another page looks wrong, this is where the run that produced it is
audited.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import streamlit as st

from components import cards, charts, layout, tables
from styles.theme import COLORS, STATUS_COLORS

STAGE_BLURB = {
    "INGESTION": "CSV loading, encoding detection, schema detection",
    "PROFILING": "Row/column counts, nulls, uniqueness, numeric statistics",
    "VALIDATION": "Schema, numeric, date, categorical, missing and duplicate rules",
    "CLEANING": "Type conversion, string normalisation, dates, PII removal",
    "INTEGRATION": "Key analysis and the documented synthetic bridge",
    "FEATURE_ENGINEERING": "Frequency, recency, duration, consistency, streaks, score",
    "SQL_LOAD": "SQLite warehouse build and view creation",
    "ANALYSIS": "KPIs, retention, segmentation, trends, funnels, diagnostics",
    "VALIDATION_SQL": "Python versus SQL cross-validation",
    "ALERTS": "Threshold evaluation across retention, engagement and quality",
    "REPORTING": "Markdown and HTML report generation",
}
STAGE_ORDER = list(STAGE_BLURB)


def render(ctx) -> None:
    result = ctx.result
    records = pd.DataFrame(result.stage_records)

    layout.page_header(
        "Pipeline Status",
        "Stage-by-stage telemetry for the run that produced every number in this dashboard, plus "
        "the artefacts it wrote.",
        icon_name="account_tree",
        eyebrow="System",
    )

    if records.empty:
        cards.empty_state(
            "No stage telemetry",
            "The last run recorded no stage log, so the pipeline cannot be audited from here.",
            icon_name="account_tree",
            hint="Run `python scripts/pipeline.py` to regenerate the pipeline artefacts.",
        )
        return

    _overview(records)
    _timeline(records)
    _configuration(result)
    _artifacts()


# ---------------------------------------------------------------------------
def _overview(records: pd.DataFrame) -> None:
    layout.section(
        "Run overview",
        "Totals across the whole pipeline run.",
        icon_name="gauge",
    )
    durations = pd.to_numeric(records.get("duration"), errors="coerce")
    processed = pd.to_numeric(records.get("records_processed"), errors="coerce")
    failed = pd.to_numeric(records.get("records_failed"), errors="coerce").fillna(0)
    worst = max(
        (str(value) for value in records.get("status", [])),
        key=lambda value: {"PASS": 0, "WARNING": 1, "FAIL": 2}.get(value, 0),
        default="n/a",
    )
    cards.kpi_row(
        [
            cards.Kpi(
                "Stages executed",
                len(records),
                icon="workflow",
                provenance="real",
                note="Ingest through report",
            ),
            cards.Kpi(
                "Total runtime",
                float(durations.sum()),
                icon="timer",
                provenance="real",
                decimals=2,
                note="Seconds, summed across every stage",
            ),
            cards.Kpi(
                "Records processed",
                int(processed.sum()) if processed.notna().any() else None,
                icon="table",
                provenance="real",
                note="Sum across stages (records, not rows)",
            ),
            cards.Kpi(
                "Worst stage status",
                icon="shield-check",
                provenance="real",
                status=worst,
                note=f"{int(failed.sum()):,} records failed in total",
            ),
        ],
        per_row=4,
    )


def _timeline(records: pd.DataFrame) -> None:
    layout.section(
        "Stage timeline",
        "Every stage in execution order, with its status, duration and record count.",
        icon_name="workflow",
    )
    ordered = records.copy()
    ordered["_order"] = ordered["stage"].astype(str).map(
        {stage: index for index, stage in enumerate(STAGE_ORDER)}
    ).fillna(99)
    ordered = ordered.sort_values("_order").drop(columns="_order")

    for index, row in enumerate(ordered.itertuples(), start=1):
        status = str(row.status)
        color = STATUS_COLORS.get(status, COLORS["neutral"])
        blurb = STAGE_BLURB.get(str(row.stage), "")
        detail = f"{row.records_processed:,} records" if pd.notna(row.records_processed) else "no record count"
        st.markdown(
            "".join(
                [
                    f'<div class="fp-card" style="border-left:3px solid {color};margin-bottom:.5rem;'
                    f'padding:.75rem 1rem;">',
                    '<div style="display:flex;align-items:center;justify-content:space-between;gap:.6rem;flex-wrap:wrap;">',
                    '<div style="display:flex;align-items:center;gap:.7rem;">',
                    f'<span style="color:{COLORS["muted"]};font-size:.78rem;font-weight:600;">{index:02d}</span>',
                    f'<span style="font-weight:650;color:{COLORS["text"]};">{str(row.stage).title()}</span>',
                    cards.status_badge(status),
                    "</div>",
                    f'<span style="font-size:.8rem;color:{COLORS["text_secondary"]};">'
                    f"{float(row.duration):,.2f}s · {detail}</span>",
                    "</div>",
                    f'<div style="font-size:.78rem;color:{COLORS["muted"]};margin-top:.3rem;">{blurb}</div>',
                    "</div>",
                ]
            ),
            unsafe_allow_html=True,
        )
        if row.message:
            st.caption(str(row.message))
        if row.error:
            st.caption(f"Error: {row.error}")

    charts.plot(
        charts.bar_chart(
            ordered,
            x="stage",
            y="duration",
            title="Feature engineering and analysis dominate the runtime",
            subtitle="Stage duration in seconds",
            x_title="Stage",
            y_title="Duration (seconds)",
            text_format="%{y:.2f}",
            horizontal=True,
            height=420,
        ),
        key="pipeline_durations",
    )
    tables.technical_table(
        "Raw stage log",
        ordered,
        columns=["stage", "status", "timestamp", "duration", "records_processed", "records_failed", "message", "error"],
        caption="Structured telemetry exactly as persisted by the pipeline.",
    )


def _configuration(result) -> None:
    layout.section(
        "Run configuration",
        "The settings that produced this run, so the result is reproducible.",
        icon_name="settings",
    )
    metadata = result.metadata or {}
    settings = metadata.get("settings", {}) or {}
    columns = st.columns(4)
    with columns[0]:
        cards.stat_block("Observation date", metadata.get("observation_date"))
    with columns[1]:
        cards.stat_block("Environment", settings.get("env"))
    with columns[2]:
        cards.stat_block("Random seed", settings.get("random_seed"))
    with columns[3]:
        cards.stat_block("Sources loaded", len(metadata.get("sources", {})))

    tables.technical_table(
        "Configuration snapshot",
        pd.DataFrame(
            [{"setting": key, "value": str(value)} for key, value in settings.items()]
        ),
        caption="Values that affect reproducibility. They come from .env and the environment.",
    )


def _artifacts() -> None:
    from src.common.config import ARTIFACTS_DIR, PROCESSED_DIR

    layout.section(
        "Artefacts on disk",
        "Everything the run wrote, so any figure can be traced back to a file.",
        icon_name="boxes",
    )
    rows = []
    for directory in (ARTIFACTS_DIR, PROCESSED_DIR):
        if not directory.exists():
            continue
        for path in sorted(directory.iterdir()):
            if not path.is_file():
                continue
            stat = path.stat()
            rows.append(
                {
                    "directory": directory.name,
                    "file": path.name,
                    "size_kb": round(stat.st_size / 1024, 1),
                    "modified": dt.datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
                }
            )
    if not rows:
        cards.empty_state(
            "No artefacts found",
            "The pipeline has not written any outputs yet.",
            icon_name="boxes",
            hint="Run `python scripts/pipeline.py`.",
        )
        return
    frame = pd.DataFrame(rows).sort_values(["directory", "file"])
    tables.render_table(
        frame.rename(columns={"size_kb": "size (KB)"}),
        caption=f"{len(frame)} files across {frame['directory'].nunique()} output directories.",
        height=340,
    )
    st.code(
        "python scripts/pipeline.py         # full run, writes artefacts and the SQLite warehouse\n"
        "python scripts/ingest.py          # download the public Kaggle sources into data/raw\n"
        "python scripts/generate_report.py --email   # regenerate and email the report\n"
        "python scripts/fetch_icons.py      # refresh the Lucide icon registry\n"
        "pytest                             # unit, data and integration tests",
        language="bash",
    )

"""Dataset Status.

What the product is actually built on: the two Kaggle sources, their real
schemas, their licences, their documented warnings, and the capability matrix
showing which features are real source fields and which depend on the synthetic
integration layer. This is the page an evaluator should read before trusting a
single number.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from components import cards, layout, tables
from styles.theme import COLORS

SOURCE_LABELS = {
    "activity": "Activity source",
    "membership": "Membership source",
}


def render(ctx) -> None:
    result = ctx.result
    sources = (result.metadata or {}).get("sources", {}) or {}
    features = ((result.metadata or {}).get("features") or {})
    integration = result.integration or {}

    layout.page_header(
        "Dataset Status",
        "Source provenance, real schemas, licences and limitations. FitPulse publishes both Kaggle "
        "sources verbatim and states exactly which derived fields depend on the synthetic calendar.",
        icon_name="dataset",
        eyebrow="Data",
    )

    if not sources:
        cards.empty_state(
            "No source metadata",
            "The last run recorded no source registry, so provenance cannot be shown.",
            icon_name="database",
            hint="Run `python scripts/pipeline.py` to regenerate the pipeline metadata.",
        )
        return

    _registry(result, sources)
    _capability(features)
    _warnings(sources)
    _integration(result, integration)


# ---------------------------------------------------------------------------
def _registry(result, sources) -> None:
    layout.section(
        "Source registry",
        "File, size, encoding and dataset attribution exactly as detected during ingestion.",
        icon_name="database",
    )
    columns = st.columns(len(sources))
    for column, (name, meta) in zip(columns, sources.items()):
        with column:
            warnings = len(meta.get("warnings") or [])
            st.markdown(
                "".join(
                    [
                        f'<div class="fp-card" style="border-top:3px solid {COLORS["primary"]};">',
                        f'<div class="fp-eyebrow">{SOURCE_LABELS.get(name, name)}</div>',
                        f'<div style="font-size:1rem;font-weight:650;color:{COLORS["text"]};">'
                        f'{meta.get("dataset_label", name)}</div>',
                        f'<div style="font-size:.8rem;color:{COLORS["text_secondary"]};margin-top:.4rem;">'
                        f'{int(meta.get("rows", 0)):,} rows · {int(meta.get("columns", 0))} columns<br>'
                        f'encoding {meta.get("encoding", "n/a")} · delimiter "{meta.get("delimiter", ",")}"<br>'
                        f'origin: {meta.get("origin", "n/a")}</div>',
                        f'<div style="font-size:.74rem;color:{COLORS["muted"]};margin-top:.5rem;">'
                        f'{warnings} documented source warnings</div>',
                        "</div>",
                    ]
                ),
                unsafe_allow_html=True,
            )
            st.caption(f"Licence: {meta.get('dataset_license', 'see dataset page')}")
            st.markdown(f"[Open the Kaggle dataset]({meta.get('dataset_url', '')})")

    for name, meta in sources.items():
        schema = (meta.get("schema") or {})
        types = schema.get("inferred_types") or {}
        if not types:
            continue
        expected = set(schema.get("present_expected") or [])
        frame = pd.DataFrame(
            [
                {
                    "column": column,
                    "inferred type": kind,
                    "expected by the contract": "yes" if column in expected else "extra",
                }
                for column, kind in types.items()
            ]
        )
        tables.technical_table(
            f"{SOURCE_LABELS.get(name, name)} — detected schema ({len(frame)} columns)",
            frame,
            caption="Types are inferred from the raw file. Validation re-checks them after cleaning.",
            height=340 if len(frame) > 10 else None,
        )


def _capability(features) -> None:
    layout.section(
        "Capability matrix",
        "Which analytical features come straight from source fields, and which depend on the documented synthetic activity calendar.",
        icon_name="clipboard-check",
    )
    real = [str(c) for c in (features.get("real_feature_columns") or [])]
    synthetic = [str(c) for c in (features.get("synthetic_feature_columns") or [])]
    if not real and not synthetic:
        cards.empty_state(
            "No capability metadata",
            "The last run did not record which features are real and which are synthetic-derived.",
            icon_name="clipboard-check",
        )
        return

    left, right = st.columns(2)
    with left:
        st.markdown(
            f'<div class="fp-card"><div style="display:flex;align-items:center;gap:.5rem;">'
            f'<span style="font-weight:650;color:{COLORS["text"]};">Real source fields</span>'
            f'{cards.provenance_badge("real")}</div>'
            f'<p style="font-size:.82rem;color:{COLORS["text_secondary"]};margin:.5rem 0 .6rem;">'
            "Straight from a Kaggle source column, or a direct calculation on one. No synthetic "
            "input is involved.</p></div>",
            unsafe_allow_html=True,
        )
        layout.bullet_list([f"`{column}`" for column in real], icon_name="circle-check")
    with right:
        st.markdown(
            f'<div class="fp-card"><div style="display:flex;align-items:center;gap:.5rem;">'
            f'<span style="font-weight:650;color:{COLORS["text"]};">Synthetic-calendar features</span>'
            f'{cards.provenance_badge("synthetic")}</div>'
            f'<p style="font-size:.82rem;color:{COLORS["text_secondary"]};margin:.5rem 0 .6rem;">'
            "Calculated from a generated activity calendar. Event dates are synthesised from each "
            "member's real visit rate; the visit rate, measures and the churn outcome stay real.</p></div>",
            unsafe_allow_html=True,
        )
        layout.bullet_list([f"`{column}`" for column in synthetic], icon_name="circle-alert", color=COLORS["warning"])

    note = features.get("note")
    if note:
        layout.footnote(note)


def _warnings(sources) -> None:
    layout.section(
        "Documented source warnings",
        "Each warning was detected during profiling and is carried through the pipeline rather than quietly handled.",
        icon_name="triangle-alert",
    )
    for name, meta in sources.items():
        items = meta.get("warnings") or []
        if not items:
            continue
        st.markdown(f"**{SOURCE_LABELS.get(name, name)}**")
        layout.bullet_list(items, icon_name="circle-dot", color=COLORS["warning"])


def _integration(result, integration) -> None:
    layout.section(
        "Integration statement",
        "The two sources were assessed for a legitimate shared key before anything was combined.",
        icon_name="git-branch",
    )
    key = integration.get("key_analysis") or {}
    if key:
        columns = st.columns(4)
        with columns[0]:
            cards.stat_block("Verdict", str(key.get("verdict", "n/a")).replace("_", " ").title())
        with columns[1]:
            cards.stat_block("Confidence", str(key.get("confidence", "n/a")).title())
        with columns[2]:
            cards.stat_block("Raw overlap", f"{key.get('overlap_count', 0):,} values")
        with columns[3]:
            cards.stat_block("Member-level join", "Not performed", detail="Key is not a member key")
        st.caption(str(key.get("recommendation", "")))
    else:
        cards.empty_state(
            "No integration report",
            "The last run did not record a key analysis for the two sources.",
            icon_name="git-branch",
        )

    tables.render_table(
        result.table("integration_quality"),
        caption="Integration quality checks as recorded by the pipeline.",
    )

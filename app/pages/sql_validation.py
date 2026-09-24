"""SQL Validation.

Proves the analytics are not an artefact of one implementation: every critical KPI
is computed twice — once in Python, once in SQL — and compared against a declared
tolerance. Structural integrity checks then confirm the warehouse is safe to
query. SQL itself is kept inside expanders so it never dominates the page.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from components import cards, charts, layout, tables
from styles.theme import COLORS, STATUS_COLORS

QUERY_LIBRARY = ("metrics.sql", "joins.sql", "windows.sql", "validation.sql")
VERIFY_CARDS = 8


@st.cache_data(show_spinner=False)
def _query_library(db_path: str, file_name: str, mtime: float) -> dict:
    from src.common.config import SQL_DIR
    from src.sql_layer import connect, parse_named_queries, read_script, run_query

    connection = connect(db_path)
    try:
        return {
            name: run_query(connection, sql).head(200)
            for name, sql in parse_named_queries(read_script(SQL_DIR / file_name)).items()
            if sql.strip().upper().startswith(("SELECT", "WITH"))
        }
    finally:
        connection.close()


@st.cache_data(show_spinner=False)
def _views(db_path: str, mtime: float) -> list:
    from src.sql_layer import connect

    connection = connect(db_path)
    try:
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'view' ORDER BY name"
        ).fetchall()
        return [row[0] for row in rows]
    finally:
        connection.close()


@st.cache_data(show_spinner=False)
def _tables(db_path: str, mtime: float) -> pd.DataFrame:
    from src.sql_layer import connect

    connection = connect(db_path)
    try:
        names = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
            ).fetchall()
        ]
        return pd.DataFrame(
            [
                {"table": name, "rows": connection.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]}
                for name in names
            ]
        )
    finally:
        connection.close()


def _fingerprint(path) -> float:
    """Cache key for the warehouse: its modification time, or 0 when missing."""
    try:
        return path.stat().st_mtime
    except (OSError, ValueError):
        return 0.0


def render(ctx) -> None:
    result = ctx.result
    validation = result.validation or {}
    crosscheck: pd.DataFrame = validation.get("crosscheck", pd.DataFrame())
    integrity: pd.DataFrame = validation.get("integrity", pd.DataFrame())
    table_checks: pd.DataFrame = validation.get("table_checks", pd.DataFrame())
    summary = validation.get("summary", {}) or {}

    layout.page_header(
        "SQL Validation",
        "Every critical KPI is recomputed in SQL and compared with the Python result against a "
        "declared tolerance, so a disagreement cannot hide behind a single implementation.",
        icon_name="terminal",
        eyebrow="Engineering",
    )

    if (crosscheck is None or crosscheck.empty) and not result.db_path:
        cards.empty_state(
            "No SQL validation results",
            "The SQLite warehouse has not been built for this run, so nothing can be verified.",
            icon_name="terminal",
            hint="Run `python scripts/pipeline.py` (the CLI builds the warehouse by default), or enable "
            "'Persist outputs' when running the pipeline from the sidebar.",
        )
        return

    _summary(summary, crosscheck, integrity)
    _verification_cards(crosscheck)
    _comparison(crosscheck, summary)
    _table_checks(table_checks)
    _integrity(integrity)
    _warehouse(result)
    _library(result)


# ---------------------------------------------------------------------------
def _summary(summary, crosscheck, integrity) -> None:
    layout.section(
        "Validation summary",
        "Worst outcome across the KPI comparison and the structural integrity checks.",
        icon_name="shield-check",
    )
    cards.kpi_row(
        [
            cards.Kpi(
                "Validation status",
                icon="shield-check",
                provenance="derived",
                status=str(summary.get("status", "n/a")),
                note="Worst outcome across every comparison",
            ),
            cards.Kpi(
                "KPI checks passed",
                summary.get("kpi_passed"),
                icon="terminal",
                provenance="derived",
                tone="success",
                note=f"of {summary.get('kpi_checks', 0)} compared KPIs",
            ),
            cards.Kpi(
                "KPI mismatches",
                summary.get("kpi_failed"),
                icon="circle-x",
                provenance="derived",
                tone="danger" if summary.get("kpi_failed") else "success",
                note="Differences beyond the declared tolerance",
            ),
            cards.Kpi(
                "Integrity failures",
                summary.get("integrity_failed"),
                icon="database",
                provenance="derived",
                tone="danger" if summary.get("integrity_failed") else "success",
                note=f"of {summary.get('integrity_checks', 0)} structural checks",
            ),
        ],
        per_row=4,
    )
    st.caption(summary.get("tolerance_policy", ""))


def _verification_cards(crosscheck) -> None:
    if crosscheck is None or crosscheck.empty:
        return
    layout.section(
        "Independent verification",
        "The Python value, the SQL value, the difference and the verdict — side by side.",
        icon_name="circle-check",
    )
    frame = crosscheck.head(VERIFY_CARDS)
    rows = [frame.iloc[i : i + 2] for i in range(0, len(frame), 2)]
    for row in rows:
        for column, (_, item) in zip(st.columns(2), row.iterrows()):
            with column:
                _verify_card(item)


def _verify_card(row: pd.Series) -> None:
    status = str(row.get("status", "")).upper()
    color = STATUS_COLORS.get(status, COLORS["neutral"])
    passed = status == "PASS"
    marker = "circle-check" if passed else "circle-x"  # noqa: F841
    python_value, python_unit = cards.format_value(row.get("python_value"), str(row.get("unit", "")))
    sql_value, sql_unit = cards.format_value(row.get("sql_value"), str(row.get("unit", "")))
    difference = row.get("difference")
    tolerance = row.get("tolerance")
    if difference is None or pd.isna(difference):
        difference = row.get("abs_difference")
    diff_text = "n/a" if difference is None or pd.isna(difference) else f"{abs(float(difference)):,.6f}"
    tolerance_text = "n/a" if tolerance is None or pd.isna(tolerance) else f"{float(tolerance):,.6f}"

    st.markdown(
        "".join(
            [
                f'<div class="fp-card" style="border-left:3px solid {color};">',
                '<div style="display:flex;align-items:center;justify-content:space-between;gap:.5rem;">',
                f'<span style="font-weight:650;color:{COLORS["text"]};">{row.get("kpi", "")}</span>',
                cards.status_badge(status, label="MATCH" if passed else status),
                "</div>",
                '<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:.6rem;margin-top:.7rem;">',
                f'<div class="fp-alert-cell">Python<strong>{python_value}{python_unit}</strong></div>',
                f'<div class="fp-alert-cell">SQL<strong>{sql_value}{sql_unit}</strong></div>',
                f'<div class="fp-alert-cell">Difference<strong>{diff_text}</strong></div>',
                "</div>",
                f'<div style="font-size:.76rem;color:{COLORS["muted"]};margin-top:.5rem;">'
                f'Tolerance {tolerance_text} · {row.get("note", "")}</div>',
                "</div>",
            ]
        ),
        unsafe_allow_html=True,
    )


def _comparison(crosscheck, summary) -> None:
    if crosscheck is None or crosscheck.empty:
        return
    layout.section(
        "Full KPI comparison",
        "All compared KPIs, with the differences ranked so any divergence is visible at a glance.",
        icon_name="scale",
    )
    display = crosscheck.copy()
    left, right = st.columns([1.3, 1])
    with left:
        plot_frame = (
            display.assign(_diff=display["abs_difference"] if "abs_difference" in display.columns else display["difference"])
            .dropna(subset=["_diff"])
            .sort_values("_diff", ascending=False)
        )
        charts.plot(
            charts.bar_chart(
                plot_frame,
                x="kpi",
                y="_diff",
                title="Differences are at or below the declared tolerance",
                subtitle="Absolute Python-versus-SQL difference per KPI, in each KPI's own units",
                x_title="KPI",
                y_title="Absolute difference",
                colour=COLORS["info"],
                text_format="%{y:.6f}",
            ),
            key="sql_diff",
        )
        layout.footnote(
            "Counts must agree exactly; rates and averages use the per-KPI absolute tolerance below."
        )
    with right:
        status_counts = display["status"].value_counts().reset_index()
        status_counts.columns = ["state", "kpis"]
        charts.plot(
            charts.status_bar(
                status_counts,
                "Comparison outcomes",
                x="state",
                y="kpis",
                colour_map=STATUS_COLORS,
                subtitle="Number of KPIs in each state",
            ),
            key="sql_status",
        )
    tables.render_table(
        display,
        columns=["kpi", "unit", "python_value", "sql_value", "difference", "tolerance", "status", "note"],
        caption=summary.get("tolerance_policy", ""),
    )


def _table_checks(table_checks) -> None:
    if table_checks is None or table_checks.empty:
        return
    layout.section(
        "Aggregate table comparisons",
        "Whole tables are compared row by row, not just headline scalars, so a localised divergence cannot hide behind an identical total.",
        icon_name="table-2",
    )
    statuses = table_checks["status"].value_counts().to_dict()
    layout.bullet_list(
        [f"{state}: {count:,} compared rows" for state, count in statuses.items()],
        icon_name="circle-dot",
    )
    only_issues = st.checkbox("Show only non-matching rows", value=False)
    shown = table_checks[table_checks["status"] != "PASS"] if only_issues else table_checks
    tables.render_table(
        shown,
        columns=["comparison", "key", "column", "python_value", "sql_value", "difference", "tolerance", "status"],
        height=380,
    )


def _integrity(integrity) -> None:
    if integrity is None or integrity.empty:
        return
    layout.section(
        "Structural integrity",
        "These checks guard the warehouse itself: key uniqueness, referential integrity, derived-value correctness and non-negative measures.",
        icon_name="lock",
    )
    tables.render_table(
        integrity,
        columns=["check", "observed", "expected", "status", "detail"],
    )


def _warehouse(result) -> None:
    if not result.db_path:
        return
    db_path = str(result.db_path)
    fingerprint = _fingerprint(result.db_path)

    layout.section(
        "Warehouse",
        f"SQLite warehouse at `{db_path}`. The same schema migrates to PostgreSQL without query changes because the SQL uses no dialect-specific features.",
        icon_name="database",
    )
    try:
        tables_frame = _tables(db_path, fingerprint)
        views = _views(db_path, fingerprint)
    except Exception as exc:  # noqa: BLE001 - the page must not crash
        st.caption(f"Warehouse inspection unavailable: {exc}")
        return

    left, right = st.columns([1.2, 1])
    with left:
        tables.render_table(tables_frame, caption="Base tables loaded by the pipeline.")
    with right:
        st.markdown("**Analytical views**")
        layout.bullet_list([f"`{view}`" for view in views], icon_name="layers")


def _library(result) -> None:
    if not result.db_path:
        return
    db_path = str(result.db_path)
    fingerprint = _fingerprint(result.db_path)

    layout.section(
        "SQL query library",
        "The analytical SQL executed by the pipeline on every run. Named queries demonstrate SELECT, WHERE, GROUP BY, HAVING, ORDER BY, CASE, JOIN, CTE, views and window functions.",
        icon_name="code",
    )
    library_file = st.selectbox("Script", options=QUERY_LIBRARY, key="sql_library_file")
    try:
        queries = _query_library(db_path, library_file, fingerprint)
        if not queries:
            cards.empty_state(
                "No named queries in this script",
                "This SQL file contains no standalone SELECT statements to display.",
                icon_name="code",
            )
            return
        selected = st.selectbox("Query", options=list(queries.keys()))
        frame = queries[selected]
        columns = st.columns(3)
        with columns[0]:
            cards.stat_block("Rows returned", len(frame))
        with columns[1]:
            cards.stat_block("Columns", len(frame.columns))
        with columns[2]:
            cards.stat_block("Source script", library_file)
        tables.render_table(frame, caption=f"`{selected}` from `{library_file}`.", height=380)
        with st.expander("View SQL"):
            from src.common.config import SQL_DIR
            from src.sql_layer import parse_named_queries, read_script

            st.code(parse_named_queries(read_script(SQL_DIR / library_file)).get(selected, ""), language="sql")
    except Exception as exc:  # noqa: BLE001
        st.caption(f"Query library unavailable: {exc}")

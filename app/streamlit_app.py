"""FitPulse — Fitness Retention Intelligence Platform (Streamlit entry point).

Run with::

    streamlit run app/streamlit_app.py

The dashboard is a presentation layer only. Every number it shows is produced by
the analytical layer in ``src``, so the app, the SQL warehouse and the CLI report
can never disagree. This shell owns navigation, the sidebar rail, filter context
and error handling; the pages own their storytelling.
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = APP_DIR.parent
for path in (str(PROJECT_ROOT), str(APP_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)

import streamlit as st  # noqa: E402

st.set_page_config(
    page_title="FitPulse — Fitness Retention Intelligence",
    page_icon=":material/monitor_heart:",
    layout="wide",
    initial_sidebar_state="expanded",
)

import state  # noqa: E402
from components import cards, filters as filter_components, layout, sidebar  # noqa: E402
from pages import (  # noqa: E402
    alerts as alerts_page,
    data_source as data_source_page,
    dataset_status as dataset_status_page,
    engagement as engagement_page,
    methodology as methodology_page,
    overview as overview_page,
    pipeline_status as pipeline_status_page,
    quality as quality_page,
    reports as reports_page,
    retention as retention_page,
    segmentation as segmentation_page,
    settings as settings_page,
    sql_validation as sql_validation_page,
)
from styles import theme  # noqa: E402

#: Navigation is grouped like a product rail: the analytical narrative first,
#: then the data/engineering surfaces, then system configuration.
NAVIGATION: dict[str, list[tuple[str, str, object]]] = {
    "": [
        ("Overview", ":material/space_dashboard:", overview_page),
        ("Engagement", ":material/monitor_heart:", engagement_page),
        ("Retention", ":material/trending_up:", retention_page),
        ("Segments", ":material/groups:", segmentation_page),
        ("Risk & Alerts", ":material/warning:", alerts_page),
    ],
    "Data": [
        ("Data Sources", ":material/database_upload:", data_source_page),
        ("Data Quality", ":material/database:", quality_page),
        ("Dataset Status", ":material/dataset:", dataset_status_page),
        ("SQL Validation", ":material/terminal:", sql_validation_page),
    ],
    "System": [
        ("Reports", ":material/description:", reports_page),
        ("Pipeline Status", ":material/account_tree:", pipeline_status_page),
        ("Methodology", ":material/menu_book:", methodology_page),
        ("Settings", ":material/settings:", settings_page),
    ],
}


def _render_logo() -> None:
    """Sidebar lockup above the navigation; falls back to a rendered block."""
    logo = APP_DIR / "assets" / "fitpulse_logo.svg"
    mark = APP_DIR / "assets" / "fitpulse_mark.svg"
    try:
        st.logo(str(logo), icon_image=str(mark), size="large")
    except Exception:  # noqa: BLE001 - branding must never break the app
        sidebar.render_brand()


def _slug(title: str) -> str:
    return (
        title.lower()
        .replace(" & ", "-")
        .replace(" ", "-")
    )


def _build_pages(ctx) -> dict[str, list]:
    sections: dict[str, list] = {}
    for section, entries in NAVIGATION.items():
        pages = []
        for index, (title, icon, module) in enumerate(entries):
            pages.append(
                st.Page(
                    lambda module=module: _render(module, ctx),
                    title=title,
                    icon=icon,
                    url_path=_slug(title),
                    default=(not section and index == 0),
                )
            )
        sections[section] = pages
    return sections


#: A page is only rendered when the loaded data can support it. These are the
#: analyses a page is built around; the shell states the reason when they are
#: unavailable instead of letting a page show empty or misleading output.
PAGE_REQUIREMENTS: dict[str, str] = {
    "retention": "retention_analysis",
    "segmentation": "segmentation",
    "sql_validation": "sql_validation",
}

#: Header and requirement wording for a page whose capability is unavailable.
PAGE_META: dict[str, dict] = {
    "retention_analysis": {
        "title": "Retention Intelligence",
        "subtitle": "Understand which engagement patterns are associated with members staying.",
        "icon": "trending-up",
        "needs": [
            "A membership dataset with one row per member",
            "A churn/retention outcome column (churn, is_churned, cancelled, active, …)",
        ],
    },
    "segmentation": {
        "title": "User Segments",
        "subtitle": "Behavioural segments ranked by engagement and their real churn outcome.",
        "icon": "groups",
        "needs": [
            "A membership dataset with a churn outcome",
            "An engagement measure (visit frequency, duration or calories)",
        ],
    },
    "sql_validation": {
        "title": "SQL Validation",
        "subtitle": "Verify analytical metrics independently with SQL.",
        "icon": "terminal",
        "needs": [
            "An activity dataset and a membership dataset loaded together",
            "The SQL warehouse built during the pipeline run",
        ],
    },
}


def _requirement_for(page_module) -> str | None:
    name = getattr(page_module, "__name__", "").rsplit(".", 1)[-1]
    return PAGE_REQUIREMENTS.get(name)


def _render(page_module, ctx) -> None:
    """Render one page inside the shared shell: context first, then content."""
    if ctx.result is None:
        cards.empty_state(
            "No dataset loaded yet",
            "FitPulse needs both source datasets before it can analyse engagement and retention.",
            icon_name="database",
            hint=(
                "Open **Data source** in the sidebar and run the pipeline on the bundled Kaggle "
                "sources, or upload the activity and membership CSVs."
            ),
        )
        return

    requirement = _requirement_for(page_module)
    if requirement and not ctx.supports(requirement):
        meta = PAGE_META.get(requirement, {})
        layout.page_header(
            meta.get("title", requirement.replace("_", " ").title()),
            meta.get("subtitle", "This analysis is not supported by the loaded data."),
            icon_name=meta.get("icon", "circle-slash"),
            eyebrow="Outcomes",
        )
        layout.unavailable_state(
            f"{meta.get('title', requirement.replace('_', ' ').title())} is unavailable for this dataset",
            ctx.capability_reason(requirement)
            or "The loaded data does not contain the fields this analysis needs.",
            needs=meta.get("needs", []),
            hint="Load a complementary dataset on the Data sources page, then return here. The rest "
            "of the dashboard keeps working on what the data does support.",
        )
        layout.provenance_notes(ctx)
        return

    layout.filter_context(ctx.view, st.session_state.get("filters", {}))
    try:
        page_module.render(ctx)
    except Exception:  # noqa: BLE001 - the dashboard degrades, it never crashes
        cards.error_state(
            "This page could not be rendered",
            "Something went wrong while building this view. The rest of the dashboard is "
            "unaffected — the most common causes are listed below.",
            causes=[
                "A required source column is missing from the uploaded data",
                "A date column could not be parsed",
                "The selected filter combination emptied the population",
            ],
            technical=traceback.format_exc(),
        )


def main() -> None:
    theme.apply()
    state.init_session_state()

    _render_logo()
    thresholds = filter_components.render_threshold_controls()

    result, origin = state.ensure_data()
    filter_components.render_data_source_panel(result, origin)

    view = state.apply_filters(result) if result is not None else state.DatasetView()
    kpis = state.filtered_kpis(view, result) if result is not None else {}
    filter_components.render_global_filters(result, view)
    sidebar.render_source_notes(result)

    if result is not None and not view.members.empty:
        st.session_state["active_alerts"] = state.filtered_alerts(view, result)

    ctx = state.PageContext(result=result, view=view, kpis=kpis, origin=origin)

    settings = state.settings_snapshot()
    st.session_state["thresholds"] = thresholds
    sidebar.render_footer(result, origin, settings)

    st.navigation(_build_pages(ctx)).run()


if __name__ == "__main__":
    main()

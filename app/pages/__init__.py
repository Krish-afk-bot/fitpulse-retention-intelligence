"""FitPulse dashboard pages.

Each module exposes ``render(ctx)`` where ``ctx`` is
:class:`app.state.PageContext`. Pages contain presentation logic only: every
number they show comes from the analytical layer, and every layout primitive
comes from :mod:`app.components`.

Navigation is grouped into four sections:

* the analytical narrative — overview, engagement, retention, segments, risk
* **Data** — data sources, quality, dataset provenance, SQL verification
* **System** — reporting, pipeline telemetry, methodology, configuration
"""

PAGE_MODULES = (
    # analytical narrative
    "overview",
    "engagement",
    "retention",
    "segmentation",
    "alerts",
    # data
    "data_source",
    "quality",
    "dataset_status",
    "sql_validation",
    # system
    "reports",
    "pipeline_status",
    "methodology",
    "settings",
)

__all__ = ["PAGE_MODULES"]

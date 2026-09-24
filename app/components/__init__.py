"""Reusable FitPulse UI components.

* :mod:`cards` — KPI, insight, segment, alert cards, badges and states
* :mod:`layout` — hero, page headers, sections, filter context
* :mod:`sidebar` — brand lockup, data panel, footer
* :mod:`charts` — the Plotly visual system
* :mod:`tables` — formatted, human-readable tables
* :mod:`filters` — sidebar filter and threshold controls
* :mod:`icons` — the Lucide icon registry
"""

from . import cards, charts, filters, icons, kpis, layout, sidebar, tables

__all__ = ["cards", "charts", "filters", "icons", "kpis", "layout", "sidebar", "tables"]

"""Compatibility shim.

KPI cards now live in :mod:`app.components.cards` alongside every other card
primitive. This module is kept so older imports keep working; new code should
import from ``components.cards`` directly.
"""

from __future__ import annotations

from .cards import (  # noqa: F401
    Insight,
    Kpi,
    insight_card,
    insight_row,
    kpi_card,
    kpi_row,
    provenance_badge,
    status_badge,
)
from .layout import provenance_legend  # noqa: F401

__all__ = [
    "Insight",
    "Kpi",
    "insight_card",
    "insight_row",
    "kpi_card",
    "kpi_row",
    "provenance_badge",
    "provenance_legend",
    "status_badge",
]

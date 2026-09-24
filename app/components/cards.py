"""Reusable presentation components.

Every visual element in FitPulse is built from one of these primitives, so all
eight pages look and behave the same. Components are pure presentation: they
receive already-computed values from the analytical layer and never calculate
business metrics themselves.

Colour is never the only signal — every status, severity and provenance state
also carries a text label, which keeps the interface readable for colour-blind
users and in greyscale print.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Iterable, List, Optional, Sequence

import pandas as pd
import streamlit as st

from styles import theme
from styles.theme import COLORS, PROVENANCE, SEGMENT_COLORS, SEGMENT_SHORT, SEVERITY_COLORS, STATUS_COLORS

from . import icons

# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------
_UNIT_SUFFIX = {
    "%": ("%", 2),
    "score": ("", 1),
    "days": (" d", 1),
    "minutes": (" min", 1),
    "hours": (" h", 1),
    "kg": (" kg", 1),
    "kcal": (" kcal", 0),
    "per_month": (" /mo", 1),
}


def format_value(value: Any, unit: str = "", decimals: Optional[int] = None) -> tuple[str, str]:
    """Return ``(number_text, unit_text)`` for display."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "n/a", ""
    if isinstance(value, bool):
        return ("Yes" if value else "No"), ""
    if isinstance(value, (int,)) and not isinstance(value, bool):
        return f"{value:,}", _UNIT_SUFFIX.get(unit, ("", 0))[0]
    if isinstance(value, float):
        suffix, default_decimals = _UNIT_SUFFIX.get(unit, ("", decimals if decimals is not None else 2))
        places = decimals if decimals is not None else default_decimals
        return f"{value:,.{places}f}", suffix
    return str(value), ""


def _delta_html(delta: float, label: str, suffix: str = "%") -> str:
    """Trend pill. Only ever called with a genuinely computed change value."""
    if delta is None or pd.isna(delta):
        return ""
    if delta > 0.05:
        css, glyph = "fp-delta--up", "arrow-up-right"
    elif delta < -0.05:
        css, glyph = "fp-delta--down", "arrow-down-right"
    else:
        css, glyph = "fp-delta--flat", "minus"
    icon = icons.icon(glyph, size=13, stroke_width=2.2, extra_style="vertical-align:-2px;")
    text = f"{abs(delta):,.1f}{suffix}"
    return (
        f'<span class="fp-delta {css}">{icon} {text}</span> '
        f'<span style="color:{COLORS["muted"]};">{label}</span>'
    )


# ---------------------------------------------------------------------------
# Badges
# ---------------------------------------------------------------------------
def badge(label: str, color: str, solid: bool = False, icon_name: Optional[str] = None) -> str:
    """A small pill badge. Text is always present, so colour is never the message."""
    markup = ""
    if icon_name:
        markup = icons.icon(icon_name, size=12, stroke_width=2.2, extra_style="vertical-align:-1px;")
    style = (
        f"background:{color};color:#FFFFFF;border-color:transparent;"
        if solid
        else f"color:{color};"
    )
    css = "fp-badge fp-badge--solid" if solid else "fp-badge"
    return f'<span class="{css}" style="{style}">{markup}{label}</span>'


def status_badge(status: str, label: Optional[str] = None) -> str:
    """PASS / WARNING / FAIL / NOT_APPLICABLE badge."""
    status = str(status or "n/a").upper()
    color = STATUS_COLORS.get(status, COLORS["neutral"])
    glyph = {
        "PASS": "circle-check",
        "OK": "circle-check",
        "HEALTHY": "circle-check",
        "WARNING": "circle-alert",
        "FAIL": "circle-x",
    }.get(status, "circle-dot")
    return badge(label or status.replace("_", " "), color, icon_name=glyph)


def severity_badge(severity: str) -> str:
    severity = str(severity or "").upper()
    color = SEVERITY_COLORS.get(severity, COLORS["neutral"])
    glyph = "triangle-alert" if severity in {"HIGH", "MEDIUM", "CRITICAL"} else "info"
    return badge(severity or "INFO", color, icon_name=glyph)


def provenance_badge(provenance: str) -> str:
    """The product's honesty marker: real / derived / synthetic-calendar.

    Used where provenance *is* the subject of the block (dataset status, legends).
    For metrics, prefer :func:`provenance_marker`, which stays quiet.
    """
    key = str(provenance or "real").lower()
    spec = PROVENANCE.get(key, PROVENANCE["real"])
    return (
        f'<span class="fp-badge" style="color:{spec["color"]};" title="{spec["detail"]}">'
        f'{spec["label"]}</span>'
    )


def provenance_marker(provenance: str) -> str:
    """A quiet provenance note for a metric, or nothing at all.

    Real source data is the default and needs no label, so a KPI that is simply a
    source field stays clean. Only computed measures, or measures that depend on a
    documented assumption, carry a marker — small and muted, never competing with
    the number itself. Full definitions live in the *Source & methodology* panel.
    """
    key = str(provenance or "real").lower()
    if key in ("", "real"):
        return ""
    spec = PROVENANCE.get(key, PROVENANCE["real"])
    return (
        f'<span class="fp-prov" style="color:{spec["color"]};" title="{spec["detail"]}">'
        f'{spec["label"]}</span>'
    )


def status_chip(label: str, status: str) -> str:
    """A chip whose colour encodes a validation/runtime state, with the state named."""
    key = str(status or "").upper()
    color = STATUS_COLORS.get(key, COLORS["neutral"])
    glyph = {
        "PASS": "circle-check",
        "HEALTHY": "circle-check",
        "OK": "circle-check",
        "WARNING": "circle-alert",
        "FAIL": "circle-x",
    }.get(key, "circle-dot")
    mark = icons.icon(glyph, size=13, stroke_width=2.2, extra_style="vertical-align:-2px;")
    return (
        f'<span class="fp-chip" style="border-color:{color}66;color:{color};">'
        f"{mark} {label}</span>"
    )


def chip(
    label: str,
    value: str = "",
    icon_name: Optional[str] = None,
    active: bool = False,
    color: Optional[str] = None,
) -> str:
    """An informational chip. ``color`` tints the label when it carries a state."""
    tint = color or COLORS["text_secondary"]
    markup = (
        icons.icon(icon_name, size=13, stroke_width=2.1, color=tint, extra_style="vertical-align:-2px;")
        if icon_name
        else ""
    )
    style = f' style="color:{tint};border-color:{tint}44;"' if color else ""
    css = "fp-chip fp-chip--active" if active else "fp-chip"
    body = f"<strong>{value}</strong>" if value else ""
    return f'<span class="{css}"{style}>{markup} {label} {body}</span>'


# ---------------------------------------------------------------------------
# KPI cards
# ---------------------------------------------------------------------------
@dataclass
class Kpi:
    """One KPI card. ``provenance`` drives the badge; ``value`` drives the number."""

    label: str
    value: Any = None
    unit: str = ""
    icon: str = "circle-dot"
    provenance: str = "real"
    note: str = ""
    help: str = ""
    delta: Optional[float] = None
    delta_label: str = "vs previous period"
    delta_suffix: str = "%"
    tone: Optional[str] = None
    status: Optional[str] = None
    decimals: Optional[int] = None
    #: ``primary`` gives the number real presence, ``quiet`` recedes it. Only the
    #: handful of measures that carry a page should be primary; if everything is
    #: emphasised, nothing is.
    emphasis: str = "secondary"


_TONE_COLOR = {
    "primary": COLORS["primary"],
    "success": COLORS["success"],
    "warning": COLORS["warning"],
    "danger": COLORS["danger"],
    "info": COLORS["info"],
    "neutral": COLORS["neutral"],
}


def _tone_color(tone: Optional[str], default: str = COLORS["primary"]) -> str:
    return _TONE_COLOR.get(str(tone), default) if tone else default


_EMPHASIS_CLASS = {
    "primary": "fp-kpi fp-kpi--primary",
    "secondary": "fp-kpi",
    "quiet": "fp-kpi fp-kpi--quiet",
}


def kpi_card(card: Kpi) -> None:
    """Render a single KPI card.

    ``emphasis`` drives the size of the number: the four measures that carry a
    page read large, supporting measures read smaller, so importance is legible
    before a single word is read.
    """
    card_class = _EMPHASIS_CLASS.get(str(card.emphasis).lower(), "fp-kpi")
    accent = _tone_color(card.tone)
    if card.status:
        accent = STATUS_COLORS.get(str(card.status).upper(), accent)

    body: List[str] = []
    if card.status:
        body.append(status_badge(card.status))
    else:
        number, suffix = format_value(card.value, card.unit, card.decimals)
        body.append(f'<div class="fp-kpi-value">{number}<span class="fp-kpi-unit">{suffix}</span></div>')

    foot = ""
    if card.delta is not None:
        foot = _delta_html(card.delta, card.delta_label, card.delta_suffix)
    elif card.note:
        foot = card.note
    elif card.help:
        foot = card.help

    title = card.help or card.note
    st.markdown(
        "".join(
            [
                f'<div class="{card_class}" style="--fp-accent:{accent};">',
                '<div class="fp-kpi-top">',
                icons.icon_chip(card.icon, color=accent),
                provenance_marker(card.provenance),
                "</div>",
                f'<div class="fp-kpi-label">{card.label}</div>',
                *body,
                f'<div class="fp-kpi-foot" title="{title}">{foot}</div>',
                "</div>",
            ]
        ),
        unsafe_allow_html=True,
    )


def kpi_row(cards: Sequence[Kpi], per_row: int = 4, emphasis: Optional[str] = None) -> None:
    """Render KPI cards in balanced rows.

    ``emphasis`` sets a row-level default (a page's headline row is ``primary``,
    its supporting row is ``secondary``) without overwriting a card that already
    declares its own emphasis.
    """
    items = [c for c in cards if c is not None]
    if not items:
        return
    if emphasis:
        items = [
            replace(card, emphasis=emphasis) if card.emphasis == "secondary" else card
            for card in items
        ]
    per_row = max(1, min(per_row, len(items)))
    for start in range(0, len(items), per_row):
        row = items[start:start + per_row]
        for column, card in zip(st.columns(len(row)), row):
            with column:
                kpi_card(card)


# ---------------------------------------------------------------------------
# Insight cards
# ---------------------------------------------------------------------------
@dataclass
class Insight:
    title: str
    body: str
    icon: str = "sparkles"
    eyebrow: str = "Insight"
    tone: str = "primary"
    provenance: str = ""


def insight_card(insight: Insight) -> None:
    """Convert a computed finding into a readable card.

    The body text is always produced by the analytical layer, never authored for
    presentation, so no finding can be invented in the UI.
    """
    accent = _tone_color(insight.tone)
    meta = provenance_marker(insight.provenance) if insight.provenance else ""
    eyebrow = f'{insight.eyebrow.upper()}' if insight.eyebrow else ""
    st.markdown(
        "".join(
            [
                f'<div class="fp-insight" style="--fp-accent:{accent};">',
                icons.icon_chip(insight.icon, color=accent),
                "<div style='flex:1 1 auto;'>",
                '<div style="display:flex;align-items:center;gap:.5rem;flex-wrap:wrap;">',
                f'<span class="fp-eyebrow">{eyebrow}</span>',
                meta,
                "</div>",
                f'<p class="fp-insight-title">{insight.title}</p>',
                f'<p class="fp-insight-body">{insight.body}</p>',
                "</div>",
                "</div>",
            ]
        ),
        unsafe_allow_html=True,
    )


def insight_row(insights: Sequence[Insight], per_row: int = 2) -> None:
    items = [i for i in insights if i is not None]
    if not items:
        return
    per_row = max(1, min(per_row, len(items)))
    for start in range(0, len(items), per_row):
        row = items[start:start + per_row]
        for column, item in zip(st.columns(len(row)), row):
            with column:
                insight_card(item)


# ---------------------------------------------------------------------------
# Segment cards
# ---------------------------------------------------------------------------
def segment_card(
    segment: str,
    members: int,
    share_pct: float,
    churn_rate: Optional[float] = None,
    retention_rate: Optional[float] = None,
    avg_visits: Optional[float] = None,
    avg_recency: Optional[float] = None,
    avg_streak: Optional[float] = None,
    max_members: Optional[int] = None,
) -> None:
    """A segment card with a data-driven size bar and its real churn outcome."""
    color = SEGMENT_COLORS.get(segment, COLORS["primary"])
    label = SEGMENT_SHORT.get(segment, segment)
    letter = segment.split(" - ")[0].strip() if " - " in segment else ""
    width = 100.0 * members / max_members if max_members else min(100.0, share_pct or 0.0)

    risk = ""
    if churn_rate is not None and not pd.isna(churn_rate):
        risk_color = (
            COLORS["danger"] if churn_rate >= 40 else COLORS["warning"] if churn_rate >= 20 else COLORS["success"]
        )
        risk = badge(f"{churn_rate:.0f}% churn", risk_color)

    metrics = [
        ("Avg visits/mo", avg_visits, "{:,.1f}"),
        ("Avg recency", avg_recency, "{:,.0f} d"),
        ("Avg streak", avg_streak, "{:,.1f} d"),
    ]
    metric_html = "".join(
        f'<div class="fp-seg-metric">{name}'
        f'<strong>{"n/a" if value is None or pd.isna(value) else fmt.format(value)}</strong></div>'
        for name, value, fmt in metrics
    )

    st.markdown(
        "".join(
            [
                f'<div class="fp-seg" style="--fp-accent:{color};">',
                '<div style="display:flex;align-items:center;justify-content:space-between;gap:.5rem;">',
                f'<span class="fp-seg-name">{letter} · {label}</span>',
                risk,
                "</div>",
                '<div style="display:flex;align-items:baseline;gap:.5rem;margin-top:.35rem;">',
                f'<span class="fp-seg-count">{members:,}</span>',
                f'<span class="fp-seg-share">{share_pct:,.1f}% of members</span>',
                "</div>",
                f'<div class="fp-bar" style="margin-top:.6rem;"><span style="width:{width:.1f}%;'
                f'background:{color};"></span></div>',
                f'<div class="fp-seg-metrics">{metric_html}</div>',
                "</div>",
            ]
        ),
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Alert cards
# ---------------------------------------------------------------------------
def _severity_dot(severity: str, color: str) -> str:
    """A small severity lamp beside the alert's badge.

    High-severity alerts pulse, gently and slowly, so a live risk reads as live at
    a glance. Everything below that stays perfectly still — motion that never
    stops becomes noise.
    """
    live = severity in {"HIGH", "CRITICAL"}
    modifier = " fp-dot--pulse" if live else ""
    return (
        f'<span class="fp-dot{modifier}" style="background:{color};color:{color};" '
        f'aria-hidden="true"></span>'
    )


def alert_card(row: pd.Series) -> None:
    """Render one alert with everything a responder needs to act on it."""
    severity = str(row.get("severity", "INFO")).upper()
    color = SEVERITY_COLORS.get(severity, COLORS["neutral"])
    cells = [
        ("Observed", row.get("observed_display", "n/a")),
        ("Threshold", row.get("threshold_display", "n/a")),
        ("Affected population", row.get("affected_population", "n/a")),
        ("Category", row.get("category", "n/a")),
        ("Evaluated at", row.get("triggered_at", "n/a")),
        ("Data source", row.get("data_source", "n/a")),
    ]
    grid = "".join(
        f'<div class="fp-alert-cell">{label}<strong>{value}</strong></div>' for label, value in cells
    )

    st.markdown(
        "".join(
            [
                f'<div class="fp-alert" style="--fp-accent:{color};">',
                '<div class="fp-alert-head">',
                _severity_dot(severity, color),
                icons.icon_chip("triangle-alert" if severity in {"HIGH", "MEDIUM", "CRITICAL"} else "info", color=color),
                severity_badge(severity),
                f'<span class="fp-alert-title">{row.get("metric", "")}</span>',
                "</div>",
                f'<div class="fp-alert-grid">{grid}</div>',
                f'<p class="fp-insight-body"><strong>Why it fired.</strong> {row.get("explanation", "")}</p>',
                "</div>",
            ]
        ),
        unsafe_allow_html=True,
    )
    if row.get("caveat"):
        st.caption(f"Caveat: {row['caveat']}")
    if row.get("recommended_action"):
        st.caption(f"Suggested action: {row['recommended_action']}")


# ---------------------------------------------------------------------------
# Progress / health
# ---------------------------------------------------------------------------
def health_ring(
    percent: Optional[float],
    caption: str = "Validation checks passed",
    color: Optional[str] = None,
    size: int = 168,
) -> str:
    """SVG progress ring. ``percent`` must come from a real measurement."""
    value = 0.0 if percent is None or pd.isna(percent) else max(0.0, min(100.0, float(percent)))
    ring = color or (COLORS["danger"] if value < 70 else COLORS["warning"] if value < 95 else COLORS["primary"])
    radius = (size / 2) - 14
    circumference = 2 * 3.141592653589793 * radius
    dash = circumference * value / 100.0
    center = size / 2
    return "".join(
        [
            f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}" role="img" '
            f'aria-label="{value:.1f} percent {caption}">',
            f'<circle cx="{center}" cy="{center}" r="{radius}" fill="none" '
            f'stroke="rgba(23,32,25,0.08)" stroke-width="11"/>',
            f'<circle cx="{center}" cy="{center}" r="{radius}" fill="none" stroke="{ring}" '
            f'stroke-width="11" stroke-linecap="round" stroke-dasharray="{dash:.1f} {circumference:.1f}" '
            f'transform="rotate(-90 {center} {center})"/>',
            f'<text x="{center}" y="{center - 2}" text-anchor="middle" fill="{COLORS["text"]}" '
            f'font-size="{size * 0.19:.0f}" font-weight="700" font-family="{theme.FONT_STACK.split(",")[0].strip(chr(39))}">'
            f"{value:,.1f}%</text>",
            f'<text x="{center}" y="{center + 20}" text-anchor="middle" fill="{COLORS["muted"]}" '
            f'font-size="11">{caption}</text>',
            "</svg>",
        ]
    )


def progress_line(label: str, percent: Optional[float], color: Optional[str] = None, detail: str = "") -> None:
    value = 0.0 if percent is None or pd.isna(percent) else max(0.0, min(100.0, float(percent)))
    tint = color or COLORS["primary"]
    st.markdown(
        "".join(
            [
                '<div style="margin-bottom:.7rem;">',
                '<div style="display:flex;justify-content:space-between;gap:.6rem;font-size:.83rem;">',
                f'<span style="color:{COLORS["text_secondary"]};">{label}</span>',
                f'<span style="color:{COLORS["text"]};font-weight:600;">{value:,.1f}%</span>',
                "</div>",
                f'<div class="fp-bar" style="margin-top:.3rem;"><span style="width:{value:.1f}%;background:{tint};"></span></div>',
                f'<div style="font-size:.74rem;color:{COLORS["muted"]};margin-top:.25rem;">{detail}</div>'
                if detail
                else "",
                "</div>",
            ]
        ),
        unsafe_allow_html=True,
    )


def check_row(label: str, status: str, detail: str = "") -> None:
    """One line of a checklist: label, then an explicit text status."""
    st.markdown(
        "".join(
            [
                '<div class="fp-check-row">',
                f'<span>{label}</span>',
                '<span style="display:flex;align-items:center;gap:.5rem;">',
                f'<span style="color:{COLORS["muted"]};font-size:.78rem;">{detail}</span>'
                if detail
                else "",
                status_badge(status),
                "</span>",
                "</div>",
            ]
        ),
        unsafe_allow_html=True,
    )


def stat_block(label: str, value: Any, unit: str = "", detail: str = "") -> None:
    """Compact label/value pair for dense comparison columns."""
    number, suffix = format_value(value, unit)
    st.markdown(
        "".join(
            [
                '<div style="margin-bottom:.85rem;">',
                f'<div class="fp-eyebrow">{label}</div>',
                f'<div style="font-size:1.35rem;font-weight:700;color:{COLORS["text"]};">'
                f'{number}<span class="fp-kpi-unit">{suffix}</span></div>',
                f'<div style="font-size:.76rem;color:{COLORS["muted"]};">{detail}</div>'
                if detail
                else "",
                "</div>",
            ]
        ),
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Empty and error states
# ---------------------------------------------------------------------------
def empty_state(title: str, body: str, icon_name: str = "database", hint: str = "") -> None:
    """A designed empty state, never a blank space or a naked chart."""
    st.markdown(
        "".join(
            [
                '<div class="fp-empty">',
                icons.icon_chip(icon_name, size=22, color=COLORS["neutral"], tile=COLORS["surface_muted"]),
                f'<p class="fp-empty-title">{title}</p>',
                f'<p class="fp-empty-body">{body}</p>',
                f'<p class="fp-empty-body" style="margin-top:.6rem;color:{COLORS["text_secondary"]};">{hint}</p>'
                if hint
                else "",
                "</div>",
            ]
        ),
        unsafe_allow_html=True,
    )


def error_state(title: str, body: str, causes: Optional[Iterable[str]] = None, technical: str = "") -> None:
    """A friendly failure panel that still exposes the traceback for debugging."""
    cause_html = ""
    if causes:
        items = "".join(f"<li>{c}</li>" for c in causes)
        cause_html = (
            '<div style="text-align:left;display:inline-block;margin-top:.7rem;">'
            f'<div class="fp-eyebrow">Possible causes</div><ul style="margin:.3rem 0 0 .2rem;">{items}</ul></div>'
        )
    st.markdown(
        "".join(
            [
                '<div class="fp-empty" style="border-style:solid;border-color:rgba(216,91,91,0.35);">',
                icons.icon_chip("circle-alert", size=22, color=COLORS["danger"]),
                f'<p class="fp-empty-title">{title}</p>',
                f'<p class="fp-empty-body">{body}</p>',
                cause_html,
                "</div>",
            ]
        ),
        unsafe_allow_html=True,
    )
    if technical:
        with st.expander("Technical details"):
            st.code(technical, language="text")


def loading(label: str) -> Any:
    """A specific, honest loading message instead of a generic 'please wait'."""
    return st.spinner(label)


# ---------------------------------------------------------------------------
# Small utilities used by pages
# ---------------------------------------------------------------------------
def segment_color_map() -> dict:
    return dict(SEGMENT_COLORS)


def as_frame(value: Any) -> pd.DataFrame:
    return value if isinstance(value, pd.DataFrame) else pd.DataFrame()

"""FitPulse design system: tokens, global CSS and the Plotly visual template.

Everything visual is defined here once and consumed by the components, so no raw
hex value is ever scattered through a page.

Design rules encoded below:

* **Light-first.** The page is bright (surfaces are white on a soft mineral
  background); colour is reserved for meaning. Roughly 80% of any screen is
  light, with dark used deliberately — the navigation rail, the hero banner and
  the sidebar footer — to create rhythm.
* **Green is the brand accent, not the interface.** It marks the primary series,
  the active navigation item and healthy states. A screen with green borders on
  every card communicates nothing.
* **One typographic scale** (Inter, system fallback) with generous whitespace,
  and a deliberate hierarchy: primary KPIs are visibly larger than secondary ones.
* **Motion is quiet.** Fade-and-rise on entry, elevation on hover, 150-300ms
  ease-out curves. Nothing loops, bounces or competes with the data.
* **Colour never carries meaning alone** — every state also carries a text label.
"""

from __future__ import annotations

from typing import Any, Dict, List

import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

APP_NAME = "FitPulse"
APP_TAGLINE = "Fitness Retention Intelligence"
APP_VERSION = "v1.0"
TEMPLATE_NAME = "fitpulse"

# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------
COLORS: Dict[str, str] = {
    # --- brand ------------------------------------------------------------
    "primary": "#1BAE70",
    "primary_dark": "#087A4A",
    "primary_light": "#DDF5E9",
    "primary_soft": "#EDF9F2",
    # --- light foundation -------------------------------------------------
    "background": "#F6F8F5",
    "surface": "#FFFFFF",
    "surface_elevated": "#FFFFFF",
    "surface_muted": "#EFF4EF",
    "border": "#DCE5DE",
    "border_strong": "#C3D1C8",
    # --- text -------------------------------------------------------------
    "text": "#172019",
    "text_secondary": "#66736B",
    "muted": "#8A968F",
    # --- dark accents (rail, hero, footer) --------------------------------
    "ink": "#0E1A14",
    "ink_elevated": "#16261D",
    "ink_border": "#24402F",
    "ink_text": "#F1F7F3",
    "ink_text_secondary": "#A9BDB1",
    "ink_muted": "#7B9184",
    # --- semantic ---------------------------------------------------------
    "success": "#19A974",
    "warning": "#D99A27",
    "danger": "#D85B5B",
    "info": "#4285C5",
    "neutral": "#7C8781",
}

#: Spatial rhythm. Sections breathe; cards do not crowd their own content.
SPACING: Dict[str, str] = {
    "xs": "0.35rem",
    "sm": "0.6rem",
    "md": "1rem",
    "lg": "1.6rem",
    "xl": "2.4rem",
    "section": "2.6rem",
}

RADIUS: Dict[str, str] = {
    "sm": "10px",
    "md": "14px",
    "lg": "18px",
    "pill": "999px",
}

#: Elevation is used to lift interactive surfaces, never as decoration.
SHADOWS: Dict[str, str] = {
    "flat": "none",
    "card": "0 1px 2px rgba(23, 32, 25, 0.04), 0 1px 3px rgba(23, 32, 25, 0.05)",
    "hover": "0 6px 16px rgba(23, 32, 25, 0.09), 0 2px 5px rgba(23, 32, 25, 0.05)",
    "ink": "0 10px 30px rgba(14, 26, 20, 0.18)",
}

#: Motion, in one place, so the whole product moves at the same tempo.
TRANSITIONS: Dict[str, str] = {
    "fast": "140ms cubic-bezier(0.2, 0.7, 0.3, 1)",
    "base": "220ms cubic-bezier(0.2, 0.7, 0.3, 1)",
    "slow": "300ms cubic-bezier(0.2, 0.7, 0.3, 1)",
}

FONT_STACK = (
    "'Inter', 'Segoe UI', -apple-system, BlinkMacSystemFont, 'Helvetica Neue', Arial, sans-serif"
)

#: Provenance vocabulary — the product's honesty layer. Rendered inline only for
#: measures that were computed or that rest on a documented assumption; real
#: source fields need no marker. Definitions live in the *Data & methodology*
#: panel rather than on every card.
PROVENANCE: Dict[str, Dict[str, str]] = {
    "real": {
        "label": "Real source",
        "color": COLORS["primary_dark"],
        "detail": "A field taken unchanged from the loaded source dataset.",
    },
    "derived": {
        "label": "Derived",
        "color": COLORS["info"],
        "detail": "Calculated from real source fields.",
    },
    "synthetic": {
        "label": "Synthetic analytical calendar",
        "color": COLORS["warning"],
        "detail": (
            "Depends on the documented synthetic activity calendar: event dates are generated "
            "from each member's real visit rate. Measures and the churn outcome stay real."
        ),
    },
}

STATUS_COLORS: Dict[str, str] = {
    "PASS": COLORS["success"],
    "WARNING": COLORS["warning"],
    "FAIL": COLORS["danger"],
    "NOT_APPLICABLE": COLORS["neutral"],
    "OK": COLORS["success"],
    "HEALTHY": COLORS["success"],
}

SEVERITY_COLORS: Dict[str, str] = {
    "CRITICAL": COLORS["danger"],
    "HIGH": COLORS["danger"],
    "MEDIUM": COLORS["warning"],
    "LOW": COLORS["info"],
    "INFO": COLORS["neutral"],
}

#: One colour per behavioural segment, used by both the cards and the charts so
#: a segment is the same colour everywhere it appears.
#:
#: Engagement quality is a single gradient from healthy to at-risk, not four
#: unrelated categories, so only the extremes are saturated: the two middle
#: segments stay neutral and the risk states carry the warning colours.
SEGMENT_COLORS: Dict[str, str] = {
    "A - Highly Engaged": COLORS["primary"],
    "B - Regular": COLORS["neutral"],
    "C - At Risk": COLORS["warning"],
    "D - Dormant": COLORS["danger"],
}

SEGMENT_SHORT: Dict[str, str] = {
    "A - Highly Engaged": "Highly Engaged",
    "B - Regular": "Regular",
    "C - At Risk": "At Risk",
    "D - Dormant": "Dormant",
}

CATEGORY_COLORS: Dict[str, str] = {
    "Retained": COLORS["primary"],
    "Churned": COLORS["danger"],
    "Present": COLORS["primary"],
    "Absent": COLORS["warning"],
}

#: A subtle ECG-style pulse line, used as the hero's decorative texture. Inlined
#: rather than fetched so the banner can never fail to load.
PULSE_PATTERN = (
    "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='140' height='64' "
    "viewBox='0 0 140 64'%3E%3Cpath d='M0 34h30l7-16 9 30 8-14h86' fill='none' "
    "stroke='%231BAE70' stroke-opacity='0.5' stroke-width='1.4'/%3E%3C/svg%3E\")"
)

# ---------------------------------------------------------------------------
# CSS custom properties
# ---------------------------------------------------------------------------


def _css_vars() -> str:
    lines: List[str] = []
    for name, value in COLORS.items():
        lines.append(f"  --fp-{name.replace('_', '-')}: {value};")
    for name, value in RADIUS.items():
        lines.append(f"  --fp-radius-{name}: {value};")
    for name, value in SHADOWS.items():
        lines.append(f"  --fp-shadow-{name}: {value};")
    for name, value in TRANSITIONS.items():
        lines.append(f"  --fp-t-{name}: {value};")
    for name, value in SPACING.items():
        lines.append(f"  --fp-space-{name}: {value};")
    return "\n".join(lines)


CSS_VARIABLES = _css_vars()

GLOBAL_CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

:root {{
{CSS_VARIABLES}
  --fp-font: {FONT_STACK};
  --fp-radius: var(--fp-radius-lg);
  --fp-radius-sm: var(--fp-radius-md);
  --fp-gap: var(--fp-space-md);
}}

html, body, [class*="css"] {{ font-family: var(--fp-font); }}

/* --- page canvas -------------------------------------------------------- */
/* A bright mineral background with two almost-invisible green glows, so large
   light areas still read as designed rather than empty. */
[data-testid="stAppViewContainer"] {{
  background:
    radial-gradient(900px 420px at 8% -6%, rgba(27, 174, 112, 0.07), transparent 60%),
    radial-gradient(760px 380px at 100% 0%, rgba(66, 133, 197, 0.05), transparent 58%),
    var(--fp-background);
}}
[data-testid="stHeader"] {{ background: transparent; }}
[data-testid="stToolbar"] {{ right: 0.5rem; }}
[data-testid="stDecoration"], #MainMenu, footer {{ display: none; }}
[data-testid="stStatusWidget"] {{ display: none; }}

.block-container {{ padding-top: 2.6rem; padding-bottom: 3.6rem; max-width: 1440px; }}

h1, h2, h3, h4 {{ color: var(--fp-text); letter-spacing: -0.015em; }}
p, li, label {{ color: var(--fp-text-secondary); }}

/* --- motion ------------------------------------------------------------- */
@keyframes fp-rise {{
  from {{ opacity: 0; transform: translateY(8px); }}
  to   {{ opacity: 1; transform: translateY(0); }}
}}
@keyframes fp-grow {{
  from {{ transform: scaleX(0); }}
  to   {{ transform: scaleX(1); }}
}}
@keyframes fp-pulse {{
  0%, 100% {{ box-shadow: 0 0 0 0 currentColor; opacity: 1; }}
  50%      {{ box-shadow: 0 0 0 4px rgba(0, 0, 0, 0); opacity: 0.72; }}
}}
@media (prefers-reduced-motion: reduce) {{
  *, *::before, *::after {{ animation: none !important; transition: none !important; }}
}}

/* --- sidebar: the product's dark anchor --------------------------------- */
[data-testid="stSidebar"] {{
  background: var(--fp-ink);
  border-right: 1px solid var(--fp-ink-border);
}}
[data-testid="stSidebar"] > div {{ padding-top: 0.9rem; }}
[data-testid="stSidebarHeader"] {{ padding-bottom: 0.3rem; }}
[data-testid="stLogo"] {{ margin: 0 0.35rem 0.35rem; }}
[data-testid="stSidebarNav"] {{ padding-top: 0.15rem; }}
[data-testid="stSidebarNav"] ul {{ padding-left: 0; }}
[data-testid="stSidebarNav"] a {{
  border-radius: var(--fp-radius-sm);
  margin: 2px 0;
  transition: background var(--fp-t-fast), color var(--fp-t-fast);
}}
[data-testid="stSidebarNav"] a span {{ font-size: 0.9rem; font-weight: 500; }}
[data-testid="stSidebarNav"] a span,
[data-testid="stSidebarNav"] a {{ color: var(--fp-ink-text-secondary); }}
[data-testid="stSidebarNav"] a:hover {{ background: rgba(255, 255, 255, 0.06); }}
[data-testid="stSidebarNav"] a:hover span {{ color: var(--fp-ink-text); }}
[data-testid="stSidebarNav"] a[aria-current="page"] {{
  background: rgba(27, 174, 112, 0.20);
  box-shadow: inset 2px 0 0 var(--fp-primary);
}}
[data-testid="stSidebarNav"] a[aria-current="page"] span {{
  color: var(--fp-ink-text); font-weight: 600;
}}
/* Safety net: everything else in the rail is a label, and the rail is dark. */
[data-testid="stSidebarNav"] span:not([data-testid]) {{ color: var(--fp-ink-text-secondary); }}
/* Group headers (DATA, SYSTEM) label the sections below them, so they read as
   small caps rather than as navigation items. */
[data-testid="stNavSectionHeader"], [data-testid="stNavSectionHeader"] * {{
  color: var(--fp-ink-muted) !important;
  font-size: 0.67rem !important;
  letter-spacing: 0.13em !important;
  text-transform: uppercase !important;
  font-weight: 600 !important;
}}
/* Sidebar text: the rail is dark, so its own copy needs its own colours. Kept
   narrowly scoped so widget internals (which stay light) are untouched. */
[data-testid="stSidebar"] .stMarkdown, [data-testid="stSidebar"] .stMarkdown p,
[data-testid="stSidebar"] .stMarkdown li, [data-testid="stSidebar"] .stMarkdown strong,
[data-testid="stSidebar"] .stMarkdown span, [data-testid="stSidebar"] .stCaption,
[data-testid="stSidebar"] [data-testid="stWidgetLabel"] *,
[data-testid="stSidebar"] [data-testid="stExpander"] summary,
[data-testid="stSidebar"] [data-testid="stExpander"] summary * {{
  color: var(--fp-ink-text-secondary);
}}
[data-testid="stSidebar"] .stMarkdown strong {{ color: var(--fp-ink-text); }}
[data-testid="stSidebar"] hr {{ border-color: var(--fp-ink-border); }}
[data-testid="stSidebar"] [data-testid="stExpander"] details {{
  background: var(--fp-ink-elevated);
  border: 1px solid var(--fp-ink-border);
  border-radius: var(--fp-radius-sm);
}}
[data-testid="stSidebar"] [data-testid="stExpander"] summary:hover,
[data-testid="stSidebar"] [data-testid="stExpander"] summary:hover * {{
  color: var(--fp-primary);
}}

/* --- brand lockup ------------------------------------------------------ */
.fp-brand {{ display: flex; align-items: center; gap: 0.7rem; padding: 0 0.35rem 0.5rem; }}
.fp-brand-mark {{
  width: 36px; height: 36px; border-radius: var(--fp-radius-sm); display: flex;
  align-items: center; justify-content: center; color: #FFFFFF;
  background: linear-gradient(150deg, var(--fp-primary) 0%, var(--fp-primary-dark) 100%);
  box-shadow: 0 4px 12px rgba(8, 122, 74, 0.28);
}}
.fp-brand-name {{ font-size: 1.06rem; font-weight: 700; color: var(--fp-ink-text); line-height: 1.1; }}
.fp-brand-tag {{ font-size: 0.72rem; color: var(--fp-ink-muted); letter-spacing: 0.04em; }}

/* --- hero: the one dark, high-contrast moment above the fold ----------- */
.fp-hero {{
  position: relative; overflow: hidden;
  border-radius: var(--fp-radius-lg);
  padding: 1.9rem 2.1rem 1.7rem;
  margin-bottom: var(--fp-space-lg);
  color: var(--fp-ink-text);
  background:
    radial-gradient(620px 300px at 88% -20%, rgba(27, 174, 112, 0.30), transparent 62%),
    linear-gradient(140deg, #10201A 0%, #0C1713 58%, #0A1310 100%);
  box-shadow: var(--fp-shadow-ink);
  animation: fp-rise var(--fp-t-slow) both;
}}
/* Decorative texture only — an activity pulse across the foot of the banner. */
.fp-hero::before {{
  content: ""; position: absolute; inset: auto 0 0 0; height: 64px;
  background-image: {PULSE_PATTERN};
  background-repeat: repeat-x; opacity: 0.16; pointer-events: none;
}}
.fp-hero-inner {{ position: relative; z-index: 1; }}
.fp-hero-grid {{ display: flex; align-items: center; gap: 1.4rem; }}
.fp-hero-copy {{ flex: 1 1 auto; min-width: 0; }}
.fp-hero-art {{ flex: 0 0 auto; opacity: 0.9; }}
.fp-hero-eyebrow {{
  font-size: 0.72rem; letter-spacing: 0.15em; text-transform: uppercase;
  color: var(--fp-primary); font-weight: 600; margin-bottom: 0.45rem;
}}
.fp-hero-title {{
  font-size: 1.95rem; font-weight: 700; color: var(--fp-ink-text);
  line-height: 1.16; margin: 0; letter-spacing: -0.02em;
}}
.fp-hero-sub {{
  margin: 0.6rem 0 0; color: var(--fp-ink-text-secondary);
  font-size: 0.95rem; max-width: 60ch; line-height: 1.55;
}}
.fp-hero-chips {{ display: flex; flex-wrap: wrap; gap: 0.5rem; margin-top: 1.25rem; }}
.fp-hero-foot {{ margin: 0.85rem 0 0; color: var(--fp-ink-muted); font-size: 0.76rem; }}

.fp-chip {{
  display: inline-flex; align-items: center; gap: 0.4rem;
  border: 1px solid var(--fp-border); border-radius: var(--fp-radius-pill);
  padding: 0.3rem 0.72rem; font-size: 0.76rem; color: var(--fp-text-secondary);
  background: var(--fp-surface);
}}
.fp-chip strong {{ color: var(--fp-text); font-weight: 600; }}
.fp-chip--active {{
  border-color: rgba(27, 174, 112, 0.45);
  background: var(--fp-primary-soft);
  color: var(--fp-primary-dark);
}}
/* Chips sitting on the dark hero invert: translucent glass over the banner. */
.fp-hero-chips .fp-chip {{
  background: rgba(255, 255, 255, 0.07);
  border-color: rgba(255, 255, 255, 0.16);
  color: var(--fp-ink-text-secondary);
  backdrop-filter: blur(6px);
}}
.fp-hero-chips .fp-chip strong {{ color: var(--fp-ink-text); }}

/* --- page header -------------------------------------------------------- */
.fp-page-head {{ margin: 0 0 var(--fp-space-lg); animation: fp-rise var(--fp-t-base) both; }}
.fp-page-title {{ font-size: 1.62rem; font-weight: 700; color: var(--fp-text); margin: 0.12rem 0 0.28rem; }}

/* --- section headers --------------------------------------------------- */
.fp-section {{
  display: flex; align-items: flex-start; gap: 0.7rem;
  margin: var(--fp-space-section) 0 var(--fp-space-md);
  animation: fp-rise var(--fp-t-base) both;
}}
.fp-section-title {{ font-size: 1.12rem; font-weight: 650; color: var(--fp-text); margin: 0; }}
.fp-section-sub {{ font-size: 0.84rem; color: var(--fp-muted); margin: 0.18rem 0 0; max-width: 90ch; }}
.fp-eyebrow {{
  font-size: 0.68rem; letter-spacing: 0.13em; text-transform: uppercase;
  color: var(--fp-muted); font-weight: 600;
}}

/* --- cards -------------------------------------------------------------- */
.fp-card {{
  background: var(--fp-surface); border: 1px solid var(--fp-border);
  border-radius: var(--fp-radius); padding: 1.2rem 1.3rem; height: 100%;
  box-shadow: var(--fp-shadow-card);
}}
.fp-card--flat {{ background: var(--fp-surface-muted); }}

/* --- KPI cards ---------------------------------------------------------- */
.fp-kpi {{
  position: relative;
  background: var(--fp-surface);
  border: 1px solid var(--fp-border);
  border-radius: var(--fp-radius);
  padding: 1.05rem 1.15rem 1rem; min-height: 132px;
  display: flex; flex-direction: column; gap: 0.45rem;
  box-shadow: var(--fp-shadow-card);
  transition: box-shadow var(--fp-t-base), transform var(--fp-t-base);
  animation: fp-rise var(--fp-t-base) both;
}}
.fp-kpi:hover {{ box-shadow: var(--fp-shadow-hover); transform: translateY(-2px); }}
/* Only a card that declares a tone earns an accent edge, so colour stays a
   signal rather than a decoration applied to everything. */
.fp-kpi::after {{
  content: ""; position: absolute; left: 0; top: 14px; bottom: 14px; width: 3px;
  border-radius: 0 3px 3px 0;
  background: var(--fp-accent, transparent);
}}
.fp-kpi-top {{ display: flex; align-items: center; justify-content: space-between; gap: 0.5rem; }}
.fp-kpi-label {{
  font-size: 0.69rem; letter-spacing: 0.11em; text-transform: uppercase;
  color: var(--fp-muted); font-weight: 600;
}}
.fp-kpi-value {{ font-size: 1.6rem; font-weight: 700; color: var(--fp-text); line-height: 1.05; }}
.fp-kpi-unit {{ font-size: 0.9rem; font-weight: 600; color: var(--fp-text-secondary); margin-left: 0.15rem; }}
.fp-kpi-foot {{ font-size: 0.74rem; color: var(--fp-muted); margin-top: auto; line-height: 1.4; }}
.fp-kpi-note {{ font-size: 0.74rem; color: var(--fp-text-secondary); line-height: 1.35; }}

/* The four numbers that carry the page get real presence; supporting measures
   stay deliberately quieter so the hierarchy is readable at a glance. */
.fp-kpi--primary {{ min-height: 164px; padding: 1.3rem 1.35rem 1.1rem; }}
.fp-kpi--primary .fp-kpi-value {{ font-size: 2.25rem; letter-spacing: -0.025em; }}
.fp-kpi--primary .fp-kpi-unit {{ font-size: 1.05rem; }}
.fp-kpi--primary .fp-kpi-label {{ color: var(--fp-text-secondary); }}
.fp-kpi--quiet {{ min-height: 116px; background: var(--fp-surface); padding: 0.9rem 1.05rem 0.85rem; }}
.fp-kpi--quiet .fp-kpi-value {{ font-size: 1.32rem; }}
.fp-kpi--quiet .fp-kpi-label {{ font-size: 0.66rem; }}

.fp-icon-tile {{
  display: inline-flex; align-items: center; justify-content: center;
  width: 34px; height: 34px; border-radius: var(--fp-radius-sm); flex: 0 0 auto;
}}

.fp-delta {{ font-weight: 600; }}
.fp-delta--up {{ color: var(--fp-primary-dark); }}
.fp-delta--down {{ color: var(--fp-danger); }}
.fp-delta--flat {{ color: var(--fp-muted); }}

/* --- badges & provenance markers --------------------------------------- */
.fp-badge {{
  display: inline-flex; align-items: center; gap: 0.3rem;
  padding: 0.14rem 0.5rem; border-radius: var(--fp-radius-pill);
  font-size: 0.66rem; font-weight: 500; letter-spacing: 0.02em;
  border: 1px solid currentColor; white-space: nowrap;
}}
.fp-badge--solid {{ color: #FFFFFF; border-color: transparent; }}
.fp-prov {{
  font-size: 0.63rem; letter-spacing: 0.02em; font-weight: 500;
  cursor: help; text-align: right; line-height: 1.2; opacity: 0.95;
}}

/* --- insight cards: the soft-green editorial band ---------------------- */
.fp-insight {{
  display: flex; gap: 0.85rem; align-items: flex-start;
  background: var(--fp-primary-soft); border: 1px solid var(--fp-primary-light);
  border-radius: var(--fp-radius-md); padding: 1.05rem 1.15rem; height: 100%;
  box-shadow: none;
  transition: box-shadow var(--fp-t-base), transform var(--fp-t-base);
  animation: fp-rise var(--fp-t-base) both;
}}
.fp-insight:hover {{ box-shadow: var(--fp-shadow-hover); transform: translateY(-2px); }}
.fp-insight-title {{ font-size: 0.95rem; font-weight: 650; color: var(--fp-text); margin: 0 0 0.25rem; }}
.fp-insight-body {{ font-size: 0.85rem; color: var(--fp-text-secondary); line-height: 1.55; margin: 0; }}
.fp-insight-body strong {{ color: var(--fp-text); }}
.fp-insight .fp-icon-tile {{ background: var(--fp-surface) !important; }}

/* --- segment cards ------------------------------------------------------ */
.fp-seg {{
  background: var(--fp-surface);
  border: 1px solid var(--fp-border);
  border-top: 3px solid var(--fp-accent, var(--fp-primary));
  border-radius: var(--fp-radius); padding: 1.05rem 1.1rem; height: 100%;
  box-shadow: var(--fp-shadow-card);
  transition: box-shadow var(--fp-t-base), transform var(--fp-t-base);
  animation: fp-rise var(--fp-t-base) both;
}}
.fp-seg:hover {{ box-shadow: var(--fp-shadow-hover); transform: translateY(-2px); }}
.fp-seg-name {{ font-size: 0.98rem; font-weight: 650; color: var(--fp-text); }}
.fp-seg-count {{ font-size: 1.55rem; font-weight: 700; color: var(--fp-text); letter-spacing: -0.02em; }}
.fp-seg-share {{ font-size: 0.76rem; color: var(--fp-muted); }}
.fp-seg-metrics {{ display: flex; justify-content: space-between; gap: 0.5rem; margin-top: 0.65rem; }}
.fp-seg-metric {{ font-size: 0.74rem; color: var(--fp-muted); }}
.fp-seg-metric strong {{ display: block; font-size: 0.92rem; color: var(--fp-text); font-weight: 650; }}
.fp-bar {{
  height: 6px; border-radius: var(--fp-radius-pill);
  background: var(--fp-surface-muted); overflow: hidden;
}}
.fp-bar > span {{
  display: block; height: 100%; border-radius: var(--fp-radius-pill);
  background: var(--fp-accent, var(--fp-primary));
  transform-origin: left center;
  animation: fp-grow 620ms cubic-bezier(0.2, 0.7, 0.3, 1) both;
}}

/* --- alerts ------------------------------------------------------------- */
.fp-alert {{
  border: 1px solid var(--fp-border); border-left: 3px solid var(--fp-accent, var(--fp-warning));
  background: var(--fp-surface); border-radius: var(--fp-radius-md);
  padding: 1.05rem 1.15rem;
  box-shadow: var(--fp-shadow-card);
  animation: fp-rise var(--fp-t-base) both;
}}
.fp-alert-head {{ display: flex; align-items: center; gap: 0.55rem; flex-wrap: wrap; }}
.fp-alert-title {{ font-size: 1rem; font-weight: 650; color: var(--fp-text); margin: 0; }}
.fp-alert-grid {{
  display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 0.55rem 1.1rem; margin: 0.75rem 0 0.5rem;
}}
.fp-alert-cell {{ font-size: 0.78rem; color: var(--fp-muted); }}
.fp-alert-cell strong {{ display: block; font-size: 0.9rem; color: var(--fp-text); }}

/* --- empty / error states ---------------------------------------------- */
.fp-empty {{
  border: 1px dashed var(--fp-border-strong); border-radius: var(--fp-radius);
  background: var(--fp-surface); padding: 2.2rem 1.5rem; text-align: center;
  animation: fp-rise var(--fp-t-base) both;
}}
.fp-empty-title {{ font-size: 1rem; font-weight: 600; color: var(--fp-text); margin: 0.75rem 0 0.25rem; }}
.fp-empty-body {{ font-size: 0.85rem; color: var(--fp-muted); margin: 0 auto; max-width: 58ch; }}

/* --- status list -------------------------------------------------------- */
.fp-check-row {{
  display: flex; align-items: center; justify-content: space-between; gap: 0.6rem;
  padding: 0.55rem 0; border-bottom: 1px solid var(--fp-border);
  font-size: 0.86rem; color: var(--fp-text-secondary);
}}
.fp-check-row:last-child {{ border-bottom: none; }}

/* --- streamlit widget restyling ---------------------------------------- */
[data-testid="stVerticalBlockBorderWrapper"] {{
  border-color: var(--fp-border) !important; border-radius: var(--fp-radius) !important;
  background: var(--fp-surface); box-shadow: var(--fp-shadow-card);
}}
.stButton button, .stDownloadButton button {{
  border-radius: var(--fp-radius-sm); border: 1px solid var(--fp-border-strong);
  background: var(--fp-surface); color: var(--fp-text);
  font-weight: 600;
  transition: background var(--fp-t-fast), color var(--fp-t-fast),
              border-color var(--fp-t-fast), transform var(--fp-t-fast),
              box-shadow var(--fp-t-fast);
}}
.stButton button:hover, .stDownloadButton button:hover {{
  border-color: var(--fp-primary);
  color: var(--fp-primary-dark);
  background: var(--fp-primary-soft);
  transform: translateY(-1px);
  box-shadow: var(--fp-shadow-card);
}}
.stButton button[kind="primary"], .stDownloadButton button[kind="primary"] {{
  background: var(--fp-primary); color: #FFFFFF; border-color: transparent;
  box-shadow: 0 1px 2px rgba(8, 122, 74, 0.22);
}}
.stButton button[kind="primary"]:hover {{
  background: var(--fp-primary-dark); color: #FFFFFF;
  box-shadow: 0 4px 12px rgba(8, 122, 74, 0.26);
}}

[data-testid="stExpander"] details {{
  border: 1px solid var(--fp-border) !important; border-radius: var(--fp-radius-md) !important;
  background: var(--fp-surface);
  transition: border-color var(--fp-t-fast);
}}
[data-testid="stExpander"] details:hover {{ border-color: var(--fp-border-strong) !important; }}
[data-testid="stExpander"] summary {{ font-weight: 600; color: var(--fp-text-secondary); }}
[data-testid="stExpander"] summary:hover {{ color: var(--fp-primary-dark); }}

[data-baseweb="select"] > div, [data-baseweb="input"] > div, .stDateInput input {{
  background: var(--fp-surface) !important;
  border-color: var(--fp-border) !important; border-radius: var(--fp-radius-sm) !important;
  transition: border-color var(--fp-t-fast), box-shadow var(--fp-t-fast);
}}
[data-baseweb="select"] > div:hover, [data-baseweb="input"] > div:hover {{
  border-color: var(--fp-border-strong) !important;
}}
[data-testid="stMultiSelect"] [data-baseweb="tag"] {{
  background: var(--fp-primary-soft) !important; color: var(--fp-primary-dark) !important;
  border-radius: 7px !important;
}}
[data-testid="stMultiSelect"] [data-baseweb="tag"] span {{ color: var(--fp-primary-dark) !important; }}
[data-testid="stSlider"] [data-baseweb="slider"] div[role="slider"] {{ background: var(--fp-primary); }}
[data-testid="stDataFrame"] {{ border-radius: var(--fp-radius-sm); overflow: hidden; border: 1px solid var(--fp-border); }}
[data-testid="stAlert"] {{ border-radius: var(--fp-radius-md); border-left-width: 3px; }}
.stTabs [data-baseweb="tab-list"] {{ gap: 0.25rem; border-bottom: 1px solid var(--fp-border); }}
.stTabs [data-baseweb="tab"] {{ font-weight: 600; color: var(--fp-muted); }}
.stTabs [aria-selected="true"] {{ color: var(--fp-text) !important; }}
code, pre {{ background: var(--fp-surface-muted) !important; border-radius: 8px;
  border: 1px solid var(--fp-border); }}
hr {{ border-color: var(--fp-border); }}
::selection {{ background: rgba(27, 174, 112, 0.22); }}

/* --- chart modebar ------------------------------------------------------ */
/* Plotly's own hover rule is inconsistent across versions, so the toolbar is
   hidden here and revealed on hover: no icons sit on top of a chart title. */
.js-plotly-plot .modebar {{
  transition: opacity var(--fp-t-base);
}}
.js-plotly-plot .modebar.modebar--hover {{ opacity: 0; }}
.js-plotly-plot:hover .modebar.modebar--hover,
.js-plotly-plot .modebar.modebar--hover:focus-within {{ opacity: 1; }}

/* --- sidebar footer ----------------------------------------------------- */
.fp-side-foot {{
  border-top: 1px solid var(--fp-ink-border); margin-top: var(--fp-space-md);
  padding: 0.9rem 0.35rem 0.4rem;
  font-size: 0.73rem; color: var(--fp-ink-text-secondary); line-height: 1.7;
  animation: fp-rise var(--fp-t-base) both;
}}
.fp-side-foot .fp-name {{ color: var(--fp-ink-text); font-weight: 600; }}
.fp-dot {{
  display: inline-block; width: 7px; height: 7px; border-radius: 50%;
  margin-right: 0.35rem; vertical-align: middle;
}}
/* A quiet pulse, only for live severity dots. */
.fp-dot--pulse {{ animation: fp-pulse 2.4s ease-in-out infinite; }}

/* --- responsive --------------------------------------------------------- */
@media (max-width: 1200px) {{
  .fp-hero-title {{ font-size: 1.6rem; }}
  .fp-hero-art {{ display: none; }}
  .fp-kpi--primary .fp-kpi-value {{ font-size: 1.95rem; }}
  .block-container {{ padding-left: 1.4rem; padding-right: 1.4rem; }}
}}
@media (max-width: 860px) {{
  .fp-kpi, .fp-kpi--primary, .fp-kpi--quiet {{ min-height: 0; padding: 1rem; }}
  .fp-kpi--primary .fp-kpi-value {{ font-size: 1.7rem; }}
  .fp-seg-metrics {{ flex-wrap: wrap; }}
  .fp-hero {{ padding: 1.4rem 1.3rem; }}
  .fp-hero-title {{ font-size: 1.35rem; }}
}}
</style>
"""


# ---------------------------------------------------------------------------
# Plotly theme
# ---------------------------------------------------------------------------
def _axis(title: str = "") -> Dict[str, Any]:
    return dict(
        title=dict(text=title, font=dict(size=12, color=COLORS["text_secondary"])),
        gridcolor="rgba(23, 32, 25, 0.07)",
        zeroline=False,
        linecolor=COLORS["border"],
        tickfont=dict(size=11, color=COLORS["muted"]),
        automargin=True,
    )


def build_template() -> go.layout.Template:
    """The single Plotly template every chart in the product inherits.

    Charts sit on white cards, so the plot canvas stays transparent and the
    typography is dark: a chart should look like part of the page, not a
    self-contained dark panel.
    """
    return go.layout.Template(
        layout=go.Layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(family=FONT_STACK, size=12, color=COLORS["text_secondary"]),
            title=dict(font=dict(size=14.5, color=COLORS["text"]), x=0, xanchor="left"),
            # A restrained series order: brand green first, then neutral and info,
            # with semantic colours reserved for their meaning. No rainbow palettes.
            colorway=[
                COLORS["primary"],
                COLORS["text_secondary"],
                COLORS["info"],
                COLORS["border_strong"],
                COLORS["warning"],
                COLORS["danger"],
            ],
            xaxis=_axis(),
            yaxis=_axis(),
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="left",
                x=0,
                bgcolor="rgba(0,0,0,0)",
                font=dict(size=11, color=COLORS["text_secondary"]),
            ),
            hoverlabel=dict(
                bgcolor=COLORS["surface"],
                bordercolor=COLORS["border_strong"],
                font=dict(color=COLORS["text"], size=12),
            ),
            margin=dict(l=8, r=8, t=54, b=8),
            colorscale=dict(
                sequential=[
                    [0, COLORS["primary_soft"]],
                    [0.5, COLORS["primary"]],
                    [1, COLORS["primary_dark"]],
                ],
                diverging=[
                    [0, COLORS["danger"]],
                    [0.5, COLORS["surface_muted"]],
                    [1, COLORS["primary"]],
                ],
            ),
            polar=dict(
                bgcolor="rgba(0,0,0,0)",
                radialaxis=dict(
                    gridcolor="rgba(23, 32, 25, 0.09)",
                    tickfont=dict(size=10, color=COLORS["muted"]),
                ),
                angularaxis=dict(
                    gridcolor="rgba(23, 32, 25, 0.09)",
                    tickfont=dict(size=11, color=COLORS["text_secondary"]),
                ),
            ),
            modebar=dict(
                bgcolor="rgba(0,0,0,0)",
                color=COLORS["muted"],
                activecolor=COLORS["primary_dark"],
            ),
            transition=dict(duration=180, easing="cubic-in-out"),
        )
    )


def register_template() -> None:
    """Register and activate the FitPulse Plotly template."""
    pio.templates[TEMPLATE_NAME] = build_template()
    pio.templates.default = TEMPLATE_NAME


CHART_HEIGHT = {"sm": 300, "md": 360, "lg": 420}


def apply() -> None:
    """Inject global styling. Call once per run, before any UI is rendered."""
    register_template()
    st.markdown(GLOBAL_CSS, unsafe_allow_html=True)


def chart_config(static: bool = False) -> Dict[str, Any]:
    """Shared Plotly config: minimal modebar, no distracting interactions.

    The modebar appears on hover rather than permanently: a pinned toolbar sits on
    top of the chart title in narrow columns, and a row of icons over every chart
    is exactly the visual noise this design is trying to remove. The download and
    fullscreen affordances are still there the moment a reader reaches for them.
    """
    return {
        "displaylogo": False,
        "displayModeBar": False if static else "hover",
        "modeBarButtonsToRemove": [
            "select2d",
            "lasso2d",
            "autoScale2d",
            "zoom2d",
            "pan2d",
            "zoomIn2d",
            "zoomOut2d",
        ],
        "responsive": True,
    }

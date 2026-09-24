"""Page-level layout primitives: hero, headers, sections and filter context.

Structure is the point of the redesign. Pages open with context (a hero or a
titled header that says what the page answers), then KPIs, then behaviour, then
outcomes, then risks and actions. These helpers are what enforce that rhythm so
it cannot drift page by page.
"""

from __future__ import annotations

from typing import Iterable, List, Optional, Sequence

import streamlit as st

from styles.theme import COLORS, PROVENANCE

from . import cards, icons


def _hero_art() -> str:
    """The hero's decorative graphic: concentric activity rings plus a pulse line.

    Built as inline SVG rather than a photograph so the banner can never fail to
    load, always matches the brand palette, and adds no request or dependency.
    Abstract fitness motion reads as "athletic" without stock-photo cliches.
    """
    return (
        '<svg class="fp-hero-art" width="168" height="132" viewBox="0 0 168 132" '
        'fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">'
        # three concentric "activity rings", each broken to imply progress
        '<circle cx="78" cy="66" r="58" stroke="#1BAE70" stroke-opacity="0.20" stroke-width="7" '
        'stroke-linecap="round" stroke-dasharray="250 115" transform="rotate(-90 78 66)"/>'
        '<circle cx="78" cy="66" r="45" stroke="#1BAE70" stroke-opacity="0.42" stroke-width="7" '
        'stroke-linecap="round" stroke-dasharray="205 78" transform="rotate(-38 78 66)"/>'
        '<circle cx="78" cy="66" r="32" stroke="#F1F7F3" stroke-opacity="0.34" stroke-width="7" '
        'stroke-linecap="round" stroke-dasharray="120 81" transform="rotate(24 78 66)"/>'
        # a heartbeat trace across the rings
        '<path d="M18 66h26l7-15 9 29 8-14h82" stroke="#F1F7F3" stroke-opacity="0.55" '
        'stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>'
        '<circle cx="150" cy="66" r="3.4" fill="#1BAE70"/>'
        "</svg>"
    )


def hero(
    title: str,
    subtitle: str,
    eyebrow: str = "Fitness retention intelligence",
    chips: Optional[Sequence[dict]] = None,
    icon_name: str = "heart-pulse",
    footnote: str = "",
    art: bool = True,
) -> None:
    """The dashboard entry point: what this product is, and its current state.

    The one deliberately dark surface above the fold. ``chips`` carry the four
    facts a reader needs first; anything else belongs in ``footnote``, a quiet
    line that does not compete with the headline.
    """
    chip_html = ""
    if chips:
        chip_html = '<div class="fp-hero-chips">' + "".join(
            cards.chip(
                chip.get("label", ""),
                chip.get("value", ""),
                icon_name=chip.get("icon"),
                active=bool(chip.get("active")),
                color=chip.get("color"),
            )
            for chip in chips
            if chip
        ) + "</div>"
    st.markdown(
        "".join(
            [
                '<div class="fp-hero">',
                '<div class="fp-hero-inner">',
                '<div class="fp-hero-grid">',
                '<div class="fp-hero-copy">',
                f'<div class="fp-hero-eyebrow">{eyebrow}</div>',
                f'<h1 class="fp-hero-title">{title}</h1>',
                f'<p class="fp-hero-sub">{subtitle}</p>',
                chip_html,
                f'<p class="fp-hero-foot">{footnote}</p>' if footnote else "",
                "</div>",
                _hero_art() if art else "",
                "</div>",
                "</div>",
                "</div>",
            ]
        ),
        unsafe_allow_html=True,
    )


def page_header(
    title: str,
    subtitle: str,
    icon_name: str = "activity",
    eyebrow: str = "",
) -> None:
    """Standard header for a focused analytical page."""
    st.markdown(
        "".join(
            [
                '<div class="fp-page-head" style="display:flex;gap:.85rem;align-items:flex-start;">',
                icons.icon_chip(icon_name, size=20, color=COLORS["primary"]),
                "<div>",
                f'<div class="fp-eyebrow">{eyebrow}</div>' if eyebrow else "",
                f'<h1 class="fp-page-title">{title}</h1>',
                f'<p style="margin:0;max-width:92ch;color:{COLORS["text_secondary"]};font-size:.93rem;">'
                f"{subtitle}</p>",
                "</div>",
                "</div>",
            ]
        ),
        unsafe_allow_html=True,
    )


def section(title: str, subtitle: str = "", icon_name: Optional[str] = None) -> None:
    """A section break with a clear hierarchy — used instead of bare subheaders."""
    mark = (
        icons.icon(icon_name, size=16, color=COLORS["primary"], extra_style="margin-top:.25rem;")
        if icon_name
        else f'<span style="width:3px;height:18px;border-radius:2px;background:{COLORS["primary"]};'
        f'display:inline-block;margin-top:.28rem;"></span>'
    )
    st.markdown(
        "".join(
            [
                '<div class="fp-section">',
                mark,
                "<div>",
                f'<p class="fp-section-title">{title}</p>',
                f'<p class="fp-section-sub">{subtitle}</p>' if subtitle else "",
                "</div>",
                "</div>",
            ]
        ),
        unsafe_allow_html=True,
    )


def card(body_html: str, accent: Optional[str] = None) -> None:
    """A generic surface for composed content."""
    style = f' style="--fp-accent:{accent};"' if accent else ""
    st.markdown(f'<div class="fp-card"{style}>{body_html}</div>', unsafe_allow_html=True)


def provenance_legend(compact: bool = True) -> None:
    """Explain the provenance vocabulary once per page, from the tokens."""
    entries = " · ".join(
        f'<span style="color:{spec["color"]};font-weight:600;">{spec["label"]}</span> '
        f'<span style="color:{COLORS["muted"]};">— {spec["detail"].split(".")[0].lower()}</span>'
        for spec in PROVENANCE.values()
    )
    st.markdown(
        f'<p style="font-size:.76rem;color:{COLORS["muted"]};margin:0 0 .9rem;">{entries}</p>',
        unsafe_allow_html=True,
    )


def provenance_notes(ctx=None, expanded: bool = False) -> None:
    """A single collapsed home for provenance, methodology and assumptions.

    Provenance matters for data integrity, but repeating the full explanation on
    every card is visual noise. Each metric still carries a short marker; the
    definitions and the dataset's documented assumptions live here.
    """
    with st.expander("Source & methodology", expanded=expanded):
        st.markdown(
            " ".join(
                f'<p style="margin:.1rem 0;font-size:.83rem;">'
                f'<span style="color:{spec["color"]};font-weight:600;">{spec["label"]}</span> '
                f'<span style="color:{COLORS["text_secondary"]};">{spec["detail"]}</span></p>'
                for spec in PROVENANCE.values()
            ),
            unsafe_allow_html=True,
        )
        if ctx is None:
            return
        datasets = getattr(ctx, "datasets", []) or []
        if datasets:
            st.markdown("**Loaded data**")
            for dataset in datasets:
                st.markdown(
                    f"- **{dataset.get('label') or dataset.get('role')}** — "
                    f"{dataset.get('detected_type')}, {dataset.get('rows', 0):,} rows × "
                    f"{dataset.get('columns', 0)} columns, compatibility "
                    f"{dataset.get('compatibility_score', 'n/a')} "
                    f"({dataset.get('compatibility_status', 'n/a')})"
                    + (" — reference dataset" if dataset.get("is_reference") else "")
                )
        assumptions = [
            assumption
            for dataset in datasets
            for assumption in (dataset.get("assumptions") or [])
        ]
        if assumptions:
            st.markdown("**Documented assumptions**")
            for assumption in dict.fromkeys(assumptions):
                st.markdown(f"- {assumption}")
        unavailable = getattr(ctx, "unavailable_capabilities", None)
        if unavailable:
            st.markdown("**Not available with the loaded data**")
            for item in unavailable:
                if item.get("key") in {"subscription_analysis", "revenue_analysis"}:
                    continue
                st.markdown(f"- {item.get('label')} — {item.get('reason') or 'not supported'}")


def unavailable_state(
    title: str,
    reason: str,
    needs: Optional[Sequence[str]] = None,
    hint: str = "",
) -> None:
    """Explain why an analysis cannot run, instead of drawing an empty chart."""
    requirement_rows = "".join(
        '<div style="display:flex;gap:.5rem;align-items:flex-start;padding:.15rem 0;">'
        + icons.icon("circle-dot", size=13, color=COLORS["muted"], extra_style="margin-top:.2rem;")
        + f'<span style="font-size:.85rem;color:{COLORS["text_secondary"]};">{item}</span></div>'
        for item in (needs or [])
    )
    body = (
        '<div class="fp-card" style="border-style:dashed;">'
        '<div style="display:flex;gap:.8rem;align-items:flex-start;">'
        + icons.icon_chip("circle-slash", size=18, color=COLORS["muted"])
        + "<div>"
        + f'<p style="margin:0 0 .25rem;font-weight:600;font-size:.98rem;">{title}</p>'
        + f'<p style="margin:0;font-size:.87rem;color:{COLORS["text_secondary"]};">{reason}</p>'
        + (f'<div style="margin-top:.6rem;">{requirement_rows}</div>' if requirement_rows else "")
        + (f'<p style="margin:.7rem 0 0;font-size:.82rem;color:{COLORS["muted"]};">{hint}</p>' if hint else "")
        + "</div></div></div>"
    )
    st.markdown(body, unsafe_allow_html=True)


def filter_context(view, filters: dict) -> None:
    """Make it unmistakable that filters are active and what they are doing."""
    if not (getattr(view, "member_filters_active", False) or getattr(view, "activity_filters_active", False)):
        return
    date_active = bool(getattr(view, "date_range_active", False))
    labels: List[str] = []
    if filters.get("membership_types"):
        labels.append(f"membership: {', '.join(filters['membership_types'])}")
    if filters.get("genders"):
        labels.append(f"gender: {', '.join(filters['genders'])}")
    if filters.get("age_groups"):
        labels.append(f"age: {', '.join(filters['age_groups'])}")
    if filters.get("segments"):
        labels.append(f"segment: {', '.join(filters['segments'])}")
    status = filters.get("member_status") or []
    if status and set(status) != {"Retained", "Churned"}:
        labels.append(f"outcome: {', '.join(status)}")
    if filters.get("workout_types"):
        labels.append(f"workout: {', '.join(filters['workout_types'])}")
    if date_active and filters.get("date_range"):
        labels.append(f"dates: {filters['date_range'][0]} → {filters['date_range'][1]}")

    chips = "".join(
        cards.chip("", label, icon_name="filter", active=True) for label in labels
    )
    st.markdown(
        "".join(
            [
                '<div style="display:flex;flex-wrap:wrap;gap:.4rem;align-items:center;margin:.2rem 0 .9rem;">',
                '<span class="fp-eyebrow" style="margin-right:.3rem;">Filters active</span>',
                chips,
                "</div>",
            ]
        ),
        unsafe_allow_html=True,
    )


def columns(*ratios: float):
    """``st.columns`` with a minimum usable width, so layouts survive resizing."""
    return st.columns(list(ratios) if ratios else 2)


def footnote(text: str) -> None:
    """Small provenance or caveat line under a chart or table."""
    st.markdown(
        f'<p style="font-size:.76rem;color:{COLORS["muted"]};margin:.35rem 0 0;">{text}</p>',
        unsafe_allow_html=True,
    )


def action_hint(text: str) -> None:
    """A single recommended next step, stated as an action rather than a claim."""
    st.markdown(
        "".join(
            [
                '<div style="display:flex;gap:.6rem;align-items:flex-start;margin-top:.6rem;">',
                icons.icon("lightbulb", size=15, color=COLORS["warning"], extra_style="margin-top:.15rem;"),
                f'<span style="font-size:.85rem;color:{COLORS["text_secondary"]};">{text}</span>',
                "</div>",
            ]
        ),
        unsafe_allow_html=True,
    )


def bullet_list(items: Iterable[str], icon_name: str = "chevron-right", color: Optional[str] = None) -> None:
    tint = color or COLORS["primary"]
    rows = "".join(
        '<div style="display:flex;gap:.5rem;align-items:flex-start;padding:.22rem 0;">'
        + icons.icon(icon_name, size=14, color=tint, extra_style="margin-top:.22rem;")
        + f'<span style="font-size:.87rem;color:{COLORS["text_secondary"]};">{item}</span></div>'
        for item in items
    )
    st.markdown(rows, unsafe_allow_html=True)

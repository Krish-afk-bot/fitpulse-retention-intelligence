"""Plotly chart library for FitPulse.

One visual system for every chart: a transparent canvas that sits on the white
card behind it, hairline gridlines, a single brand green as the default series
colour, semantic colours only where a state is being communicated, and
*insight-style* titles — a chart title states what the data shows, with the plain
metric name as a subtitle.

No chart is decorative: each one answers a question posed by its section header.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Sequence

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from styles.theme import COLORS, SEGMENT_COLORS

PRIMARY = COLORS["primary"]
SECONDARY = COLORS["info"]
ACCENT = COLORS["warning"]
DANGER = COLORS["danger"]
NEUTRAL = COLORS["muted"]

# Backwards-compatible aliases for any code that imported these.
SEGMENT_COLOURS = SEGMENT_COLORS
SEGMENT_COLORS_MAP = SEGMENT_COLORS

_BASE: Dict[str, Any] = {
    "margin": dict(l=8, r=8, t=64, b=8),
    "height": 360,
    "font": dict(size=12, color=COLORS["text_secondary"]),
}


def _finalise(
    figure: go.Figure,
    title: str,
    subtitle: str = "",
    x_title: str = "",
    y_title: str = "",
    height: Optional[int] = None,
    legend: bool = True,
) -> go.Figure:
    """Apply the shared layout, title/subtitle pair and axis labels."""
    heading = title
    if subtitle:
        heading = (
            f"{title}<br><span style='font-size:11.5px;color:{COLORS['muted']};font-weight:400;'>"
            f"{subtitle}</span>"
        )
    figure.update_layout(**_BASE)
    figure.update_layout(
        title=dict(text=heading, font=dict(size=14.5, color=COLORS["text"]), x=0, xanchor="left"),
        showlegend=legend and figure_has_multi_series(figure),
    )
    if height:
        figure.update_layout(height=height)
    if x_title:
        figure.update_xaxes(title_text=x_title)
    if y_title:
        figure.update_yaxes(title_text=y_title)
    try:  # rounded bar corners where the installed Plotly supports it
        figure.update_layout(barcornerradius=6)
    except Exception:  # noqa: BLE001 - purely decorative, never fatal
        pass
    return figure


def figure_has_multi_series(figure: go.Figure) -> bool:
    named = [trace for trace in figure.data if getattr(trace, "showlegend", True) is not False]
    kinds = {type(trace).__name__ for trace in named}
    return len(named) > 1 and not ({"Pie", "Funnel"} & kinds)


def empty_chart(message: str, height: int = 280, icon_hint: str = "") -> go.Figure:
    """An intentional in-chart empty state, so a layout never collapses."""
    figure = go.Figure()
    figure.add_annotation(
        text=f"<b>{message}</b>" + (f"<br><span style='font-size:11px;'>{icon_hint}</span>" if icon_hint else ""),
        showarrow=False,
        font=dict(size=13, color=COLORS["muted"]),
        x=0.5,
        y=0.5,
        xref="paper",
        yref="paper",
    )
    figure.update_xaxes(visible=False)
    figure.update_yaxes(visible=False)
    figure.update_layout(**_BASE, height=height, title=None, showlegend=False)
    return figure


# ---------------------------------------------------------------------------
# Trends
# ---------------------------------------------------------------------------
def line_trend(
    frame: pd.DataFrame,
    x: str,
    y: str,
    title: str,
    subtitle: str = "",
    y_title: str = "",
    x_title: str = "",
    rolling: Optional[Sequence[str]] = None,
    rolling_labels: Optional[Sequence[str]] = None,
    height: int = 360,
    colour: str = PRIMARY,
    markers: bool = False,
    fill: bool = True,
    dense: bool = False,
) -> go.Figure:
    """A single-series trend with optional rolling-average overlays.

    ``dense=True`` is for daily series with hundreds of points: the raw line is
    drawn thinner and slightly transparent so the rolling averages — which are
    the actual signal — stay legible on top of it.
    """
    if frame is None or frame.empty or x not in frame.columns or y not in frame.columns:
        return empty_chart(f"No data available for {title.lower()}.", height=height)

    has_rolling = bool([c for c in (rolling or []) if c in frame.columns])
    figure = go.Figure()
    figure.add_trace(
        go.Scatter(
            x=frame[x],
            y=frame[y],
            mode="lines+markers" if markers else "lines",
            name=y.replace("_", " "),
            line=dict(color=_rgba(colour, 0.55) if dense else colour, width=1.1 if dense else 2.1),
            opacity=0.9 if dense else 1.0,
            marker=dict(size=5, color=colour),
            fill="tozeroy" if (fill and not has_rolling) else None,
            fillcolor=_rgba(colour, 0.16) if (fill and not has_rolling) else None,
            hovertemplate="%{x|%d %b %Y}<br>%{y:,.2f}<extra></extra>",
        )
    )
    for index, column in enumerate(rolling or []):
        if column not in frame.columns:
            continue
        label = (rolling_labels or [])[index] if rolling_labels and index < len(rolling_labels) else column
        figure.add_trace(
            go.Scatter(
                x=frame[x],
                y=frame[column],
                mode="lines",
                name=label,
                line=dict(color=COLORS["text_secondary"] if index else SECONDARY, width=1.7, dash="dot"),
                hovertemplate="%{x|%d %b %Y}<br>%{y:,.2f}<extra>" + label + "</extra>",
            )
        )
    return _finalise(figure, title, subtitle, x_title or x, y_title or y.replace("_", " "), height)


def bar_chart(
    frame: pd.DataFrame,
    x: str,
    y: str,
    title: str,
    subtitle: str = "",
    x_title: str = "",
    y_title: str = "",
    colour: str = PRIMARY,
    colour_column: Optional[str] = None,
    colour_map: Optional[Dict[str, str]] = None,
    text_format: Optional[str] = "%{y:,.1f}",
    orientation: str = "v",
    height: int = 360,
    horizontal: bool = False,
) -> go.Figure:
    if frame is None or frame.empty or x not in frame.columns or y not in frame.columns:
        return empty_chart(f"No data available for {title.lower()}.", height=height)
    kwargs: Dict[str, Any] = {}
    if colour_column and colour_column in frame.columns:
        kwargs["color"] = colour_column
        if colour_map:
            kwargs["color_discrete_map"] = colour_map
    figure = px.bar(frame, x=x, y=y, orientation="h" if horizontal else "v", **kwargs)
    figure.update_traces(marker_line_width=0, cliponaxis=False)
    if text_format:
        # "auto" keeps labels inside tall bars and pushes them outside short ones,
        # which also avoids Plotly's out-of-range text placements.
        figure.update_traces(texttemplate=text_format, textposition="outside" if horizontal else "auto")
    if not kwargs.get("color"):
        figure.update_traces(marker_color=colour)
    if horizontal:
        figure.update_yaxes(categoryorder="total ascending")
    return _finalise(figure, title, subtitle, x_title or x, y_title or y.replace("_", " "), height)


def grouped_bar(
    frame: pd.DataFrame,
    x: str,
    y: str,
    colour: str,
    title: str,
    subtitle: str = "",
    x_title: str = "",
    y_title: str = "",
    barmode: str = "group",
    colour_map: Optional[Dict[str, str]] = None,
    height: int = 380,
) -> go.Figure:
    if frame is None or frame.empty:
        return empty_chart(f"No data available for {title.lower()}.", height=height)
    missing = [c for c in (x, y, colour) if c not in frame.columns]
    if missing:
        return empty_chart(f"Required columns missing: {', '.join(missing)}", height=height)
    figure = px.bar(frame, x=x, y=y, color=colour, barmode=barmode, color_discrete_map=colour_map)
    figure.update_traces(marker_line_width=0)
    return _finalise(figure, title, subtitle, x_title or x, y_title or y.replace("_", " "), height)


def histogram(
    frame: pd.DataFrame,
    column: str,
    title: str,
    subtitle: str = "",
    x_title: str = "",
    y_title: str = "Members",
    bins: int = 20,
    colour: str = PRIMARY,
    height: int = 340,
) -> go.Figure:
    if frame is None or frame.empty or column not in frame.columns:
        return empty_chart(f"No data available for {title.lower()}.", height=height)
    figure = px.histogram(frame, x=column, nbins=bins)
    figure.update_traces(
        marker_color=colour,
        marker_line_width=1,
        marker_line_color=COLORS["surface"],
        opacity=0.92,
    )
    return _finalise(
        figure, title, subtitle, x_title or column.replace("_", " "), y_title, height, legend=False
    )


def box_distribution(
    frame: pd.DataFrame,
    x: str,
    y: str,
    title: str,
    subtitle: str = "",
    x_title: str = "",
    y_title: str = "",
    colour_map: Optional[Dict[str, str]] = None,
    height: int = 360,
) -> go.Figure:
    if frame is None or frame.empty or x not in frame.columns or y not in frame.columns:
        return empty_chart(f"No data available for {title.lower()}.", height=height)
    figure = px.box(frame, x=x, y=y, color=x, color_discrete_map=colour_map, points="outliers")
    figure.update_traces(marker_size=4, line_width=1.6)
    figure.update_layout(boxgap=0.35)
    return _finalise(figure, title, subtitle, x_title or x, y_title or y.replace("_", " "), height, legend=False)


# ---------------------------------------------------------------------------
# Retention and outcomes
# ---------------------------------------------------------------------------
def retention_gradient(
    frame: pd.DataFrame,
    label_column: str,
    title: str,
    subtitle: str = "",
    value_column: str = "retention_rate",
    x_title: str = "",
    y_title: str = "Retention rate (%)",
    error_low: Optional[str] = None,
    error_high: Optional[str] = None,
    height: int = 380,
) -> go.Figure:
    """Retention by an ordered band, with Wilson interval error bars."""
    if frame is None or frame.empty or label_column not in frame.columns or value_column not in frame.columns:
        return empty_chart(f"No data available for {title.lower()}.", height=height)

    error_y = None
    if error_low in frame.columns and error_high in frame.columns and value_column == "retention_rate":
        low = 100.0 - frame[error_high]
        high = 100.0 - frame[error_low]
        error_y = dict(
            type="data",
            symmetric=False,
            array=(high - frame[value_column]).clip(lower=0),
            arrayminus=(frame[value_column] - low).clip(lower=0),
            color=COLORS["border_strong"],
            thickness=1.2,
            width=3,
        )

    values = pd.to_numeric(frame[value_column], errors="coerce")
    figure = go.Figure(
        go.Bar(
            x=frame[label_column].astype(str),
            y=values,
            marker=dict(
                color=values,
                colorscale=[
                    [0, COLORS["primary_soft"]],
                    [0.55, COLORS["primary"]],
                    [1, COLORS["primary_dark"]],
                ],
                line=dict(width=0),
            ),
            error_y=error_y,
            text=[f"{v:,.1f}%" if pd.notna(v) else "" for v in values],
            textposition="outside",
            textfont=dict(size=11, color=COLORS["text_secondary"]),
            hovertemplate="%{x}<br>Retention %{y:.2f}%<extra></extra>",
            name="Retention rate",
        )
    )
    figure.update_layout(bargap=0.42)
    return _finalise(figure, title, subtitle, x_title or label_column.replace("_", " "), y_title, height, legend=False)


def churn_by_category(
    frame: pd.DataFrame,
    label_column: str,
    title: str,
    subtitle: str = "",
    value_column: str = "churn_rate",
    x_title: str = "",
    y_title: str = "Churn rate (%)",
    height: int = 360,
    colour: str = DANGER,
) -> go.Figure:
    if frame is None or frame.empty or value_column not in frame.columns:
        return empty_chart(f"No data available for {title.lower()}.", height=height)
    ordered = frame.sort_values(value_column, ascending=False)
    values = pd.to_numeric(ordered[value_column], errors="coerce")
    figure = go.Figure(
        go.Bar(
            x=ordered[label_column].astype(str),
            y=values,
            marker=dict(color=colour, opacity=0.88, line=dict(width=0)),
            text=[f"{v:,.1f}%" if pd.notna(v) else "" for v in values],
            textposition="outside",
            textfont=dict(size=11, color=COLORS["text_secondary"]),
            hovertemplate="%{x}<br>Churn %{y:.2f}%<extra></extra>",
            name="Churn rate",
        )
    )
    figure.update_layout(bargap=0.45)
    return _finalise(figure, title, subtitle, x_title or label_column.replace("_", " "), y_title, height, legend=False)


def segment_donut(
    metrics: pd.DataFrame,
    title: str = "Member mix across behavioural segments",
    subtitle: str = "",
    height: int = 340,
    hole: float = 0.62,
) -> go.Figure:
    if metrics is None or metrics.empty or "segment" not in metrics.columns or "members" not in metrics.columns:
        return empty_chart("Segment distribution unavailable.", height=height)
    figure = px.pie(
        metrics,
        names="segment",
        values="members",
        hole=hole,
        color="segment",
        color_discrete_map=SEGMENT_COLORS,
    )
    figure.update_traces(
        textinfo="percent",
        textposition="inside",
        textfont=dict(size=11, color="#FFFFFF"),
        marker=dict(line=dict(color=COLORS["surface"], width=2)),
        hovertemplate="%{label}<br>%{value:,.0f} members (%{percent})<extra></extra>",
    )
    return _finalise(figure, title, subtitle, height=height, legend=True)


def segment_metric_bar(
    metrics: pd.DataFrame,
    metric: str,
    title: str,
    subtitle: str = "",
    y_title: str = "",
    text_format: str = "%{y:,.1f}",
    height: int = 340,
) -> go.Figure:
    if metrics is None or metrics.empty or metric not in metrics.columns:
        return empty_chart(f"{title} unavailable.", height=height)
    return bar_chart(
        metrics,
        x="segment",
        y=metric,
        title=title,
        subtitle=subtitle,
        x_title="Behavioural segment",
        y_title=y_title or metric.replace("_", " "),
        colour_column="segment",
        colour_map=SEGMENT_COLORS,
        text_format=text_format,
        height=height,
    )


# ---------------------------------------------------------------------------
# Operational diagnostics
# ---------------------------------------------------------------------------
def funnel_chart(
    frame: pd.DataFrame,
    title: str,
    subtitle: str = "",
    height: int = 380,
) -> go.Figure:
    if frame is None or frame.empty or "stage" not in frame.columns or "records" not in frame.columns:
        return empty_chart("Funnel unavailable.", height=height)
    # An intentional progression from brand green through neutral to warm, not a
    # rainbow: a funnel's stages are ordered stages, not unrelated categories.
    palette = [PRIMARY, ACCENT, SECONDARY, ACCENT, DANGER, NEUTRAL]
    figure = go.Figure(
        go.Funnel(
            y=frame["stage"],
            x=frame["records"],
            textinfo="value+percent initial",
            textfont=dict(color=COLORS["text"], size=11),
            marker=dict(color=palette[: len(frame)], line=dict(width=0)),
            connector=dict(line=dict(color=COLORS["border"], width=1)),
            hovertemplate="%{y}<br>%{x:,.0f} records<extra></extra>",
        )
    )
    return _finalise(figure, title, subtitle, height=height, legend=False)


def status_bar(
    frame: pd.DataFrame,
    title: str,
    x: str,
    y: str,
    colour_map: Dict[str, str],
    subtitle: str = "",
    height: int = 320,
) -> go.Figure:
    if frame is None or frame.empty or x not in frame.columns or y not in frame.columns:
        return empty_chart(f"{title} unavailable.", height=height)
    figure = px.bar(frame, x=x, y=y, color=x, color_discrete_map=colour_map)
    figure.update_traces(
        marker_line_width=0,
        texttemplate="%{y:,}",
        textposition="auto",
        insidetextfont=dict(size=11, color="#FFFFFF"),
        textfont=dict(size=11, color=COLORS["text_secondary"]),
    )
    figure.update_layout(bargap=0.5)
    return _finalise(figure, title, subtitle, x, y.replace("_", " "), height, legend=False)


def monthly_dual_axis(
    frame: pd.DataFrame,
    title: str = "Session volume is stable across the year",
    subtitle: str = "",
    height: int = 380,
) -> go.Figure:
    """Session volume (bars) with the 3-month average and attendance rate."""
    if frame is None or frame.empty or "month" not in frame.columns:
        return empty_chart("Monthly activity unavailable.", height=height)
    figure = go.Figure()
    figure.add_trace(
        go.Bar(
            x=frame["month"],
            y=frame["events"],
            name="Recorded sessions",
            marker=dict(color=PRIMARY, opacity=0.85, line=dict(width=0)),
            hovertemplate="%{x}<br>%{y:,.0f} sessions<extra></extra>",
        )
    )
    average = "events_rolling_3m" if "events_rolling_3m" in frame.columns else None
    if average:
        figure.add_trace(
            go.Scatter(
                x=frame["month"],
                y=frame[average],
                name="3-month average",
                mode="lines",
                line=dict(color=SECONDARY, width=2.1),
                hovertemplate="%{x}<br>%{y:,.1f} sessions<extra>3-month average</extra>",
            )
        )
    if "present_rate" in frame.columns:
        figure.add_trace(
            go.Scatter(
                x=frame["month"],
                y=(pd.to_numeric(frame["present_rate"], errors="coerce") * 100),
                name="Attendance rate (%)",
                mode="lines+markers",
                line=dict(color=ACCENT, width=2.1, dash="dot"),
                marker=dict(size=5),
                yaxis="y2",
                hovertemplate="%{x}<br>%{y:.1f}% attended<extra></extra>",
            )
        )
    figure.update_layout(
        yaxis=dict(
            title=dict(text="Recorded sessions"),
            gridcolor="rgba(23, 32, 25, 0.07)",
            zeroline=False,
        ),
        yaxis2=dict(
            title=dict(text="Attendance rate (%)"),
            overlaying="y",
            side="right",
            range=[0, 100],
            showgrid=False,
            tickfont=dict(color=COLORS["muted"]),
        ),
    )
    return _finalise(figure, title, subtitle, height=height)


def heatmap(
    matrix: pd.DataFrame,
    title: str,
    subtitle: str = "",
    height: int = 460,
    value_range: Optional[tuple] = None,
) -> go.Figure:
    if matrix is None or matrix.empty:
        return empty_chart(f"{title} unavailable.", height=height)
    figure = go.Figure(
        go.Heatmap(
            z=matrix.values,
            x=[str(c).replace("_", " ") for c in matrix.columns],
            y=[str(i).replace("_", " ") for i in matrix.index],
            colorscale=[[0, DANGER], [0.5, COLORS["surface_muted"]], [1, PRIMARY]],
            zmin=value_range[0] if value_range else -1,
            zmax=value_range[1] if value_range else 1,
            text=matrix.round(2).values,
            texttemplate="%{text}",
            textfont=dict(size=10),
            colorbar=dict(title="r", outlinewidth=0, thickness=12),
            hovertemplate="%{y} × %{x}<br>r = %{z:.2f}<extra></extra>",
        )
    )
    figure.update_xaxes(tickangle=-35)
    return _finalise(figure, title, subtitle, height=height, legend=False)


def score_radar(
    profile: pd.DataFrame,
    title: str = "What drives each segment's engagement score",
    subtitle: str = "",
    height: int = 390,
) -> go.Figure:
    """Component-score profile per segment (0-100 each)."""
    if profile is None or profile.empty or "segment" not in profile.columns:
        return empty_chart("Engagement component profile unavailable.", height=height)
    components = [c for c in profile.columns if c.endswith("_score") and c != "engagement_score"]
    if not components:
        return empty_chart("Component scores unavailable.", height=height)
    labels = [c.replace("_score", "").title() for c in components]
    figure = go.Figure()
    for row in profile.itertuples():
        segment = str(getattr(row, "segment"))
        values = [float(getattr(row, column) or 0.0) for column in components]
        colour = SEGMENT_COLORS.get(segment, PRIMARY)
        figure.add_trace(
            go.Scatterpolar(
                r=values + [values[0]],
                theta=labels + [labels[0]],
                fill="toself",
                name=segment,
                line=dict(color=colour, width=1.8),
                fillcolor=_rgba(colour, 0.18),
                hovertemplate="%{theta}<br>%{r:.1f}/100<extra>" + segment + "</extra>",
            )
        )
    figure.update_layout(
        polar=dict(
            radialaxis=dict(visible=True, range=[0, 100], gridcolor="rgba(23, 32, 25, 0.10)")
        )
    )
    return _finalise(figure, title, subtitle, height=height)


def effect_size_bars(
    frame: pd.DataFrame,
    label_column: str = "measure",
    value_column: str = "cohens_d",
    title: str = "",
    subtitle: str = "",
    x_title: str = "Measure",
    y_title: str = "Cohen's d (standardised difference)",
    height: int = 380,
) -> go.Figure:
    """Standardised retained-vs-churned differences.

    Effect sizes are plotted instead of raw means because the measures live on
    very different scales; a standardised difference is the only honest way to
    rank them against each other.
    """
    if frame is None or frame.empty or value_column not in frame.columns:
        return empty_chart(f"{title or 'Effect sizes'} unavailable.", height=height)
    ordered = frame.dropna(subset=[value_column]).copy()
    ordered["_abs"] = ordered[value_column].astype(float).abs()
    ordered = ordered.sort_values("_abs", ascending=True)
    ordered["direction"] = ordered[value_column].apply(
        lambda value: "Retained members higher" if value < 0 else "Churned members higher"
    )
    figure = go.Figure(
        go.Bar(
            x=ordered[value_column],
            y=ordered[label_column].astype(str).str.replace("_", " ", regex=False),
            orientation="h",
            marker=dict(
                color=[
                    PRIMARY if value < 0 else DANGER for value in ordered[value_column]
                ],
                line=dict(width=0),
            ),
            customdata=ordered[["direction", "effect_size"]].values if "effect_size" in ordered.columns else None,
            text=[f"{value:+.2f}" for value in ordered[value_column]],
            textposition="outside",
            textfont=dict(size=11, color=COLORS["text_secondary"]),
            hovertemplate="%{y}<br>d = %{x:.2f}<extra></extra>",
            name="Effect size",
        )
    )
    figure.update_layout(bargap=0.4)
    figure.add_vline(x=0, line_width=1, line_color=COLORS["border_strong"])
    return _finalise(figure, title, subtitle, x_title, y_title, height, legend=False)


def _rgba(hex_colour: str, alpha: float) -> str:
    value = hex_colour.lstrip("#")
    if len(value) != 6:
        return "rgba(27,174,112,0.15)"
    red, green, blue = (int(value[i : i + 2], 16) for i in (0, 2, 4))
    return f"rgba({red},{green},{blue},{alpha})"


def plot(figure: go.Figure, key: str, height: Optional[int] = None) -> None:
    """Render a chart with the shared config so pages stay one-liners."""
    import streamlit as st

    from styles.theme import chart_config

    if height:
        figure.update_layout(height=height)
    st.plotly_chart(
        figure,
        width="stretch",
        key=key,
        config=chart_config(),
        # ``theme=None`` keeps Streamlit's own Plotly theming out of the way so the
        # FitPulse template is what actually renders: transparent canvas on the
        # card behind it, brand-green series, hairline gridlines.
        theme=None,
    )

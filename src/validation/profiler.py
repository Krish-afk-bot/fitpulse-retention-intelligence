"""Data profiling: the deterministic \"what is in this file\" report."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd


def _coerce_numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def profile_columns(frame: pd.DataFrame, sample_limit: int = 5) -> pd.DataFrame:
    """Return one row of profile statistics per column.

    Columns: ``column, dtype, inferred_type, non_null, null_count,
    null_pct, unique_count, unique_pct, duplicate_values, min, max, mean,
    median, std, sample_values``.
    """
    rows: List[Dict[str, Any]] = []
    total = len(frame)

    for column in frame.columns:
        series = frame[column]
        null_count = int(series.isna().sum())
        non_null = total - null_count
        unique_count = int(series.nunique(dropna=True))
        numeric = _coerce_numeric(series)
        numeric_valid = numeric.dropna()
        is_numeric = len(series.dropna()) > 0 and numeric.notna().sum() >= 0.8 * max(non_null, 1)

        samples = series.dropna().astype(str).unique()[:sample_limit].tolist()

        rows.append(
            {
                "column": column,
                "dtype": str(series.dtype),
                "non_null": non_null,
                "null_count": null_count,
                "null_pct": round(100.0 * null_count / total, 4) if total else 0.0,
                "unique_count": unique_count,
                "unique_pct": round(100.0 * unique_count / max(non_null, 1), 4) if non_null else 0.0,
                "duplicate_values": int(non_null - unique_count),
                "min": float(numeric_valid.min()) if is_numeric and not numeric_valid.empty else None,
                "max": float(numeric_valid.max()) if is_numeric and not numeric_valid.empty else None,
                "mean": float(round(numeric_valid.mean(), 4)) if is_numeric and not numeric_valid.empty else None,
                "median": float(numeric_valid.median()) if is_numeric and not numeric_valid.empty else None,
                "std": float(round(numeric_valid.std(), 4)) if is_numeric and len(numeric_valid) > 1 else None,
                "sample_values": " | ".join(samples),
            }
        )
    return pd.DataFrame(rows)


def duplicate_summary(frame: pd.DataFrame, subset: Optional[List[str]] = None) -> Dict[str, Any]:
    """Exact-duplicate statistics for the whole frame or a key subset."""
    keys = subset or list(frame.columns)
    usable = [c for c in keys if c in frame.columns]
    if not usable:
        return {"subset": [], "duplicate_rows": 0, "duplicate_pct": 0.0, "total_rows": len(frame)}
    mask = frame.duplicated(subset=usable, keep="first")
    count = int(mask.sum())
    return {
        "subset": usable,
        "duplicate_rows": count,
        "duplicate_pct": round(100.0 * count / len(frame), 4) if len(frame) else 0.0,
        "total_rows": int(len(frame)),
    }


def profile_frame(
    frame: pd.DataFrame,
    name: str,
    key_candidates: Optional[List[str]] = None,
    sample_limit: int = 5,
) -> Dict[str, Any]:
    """Full profiling payload for one dataset.

    Includes the row/column counts, per-column statistics, duplicate
    statistics (both whole-row and per candidate key) and numeric summaries.
    """
    columns_profile = profile_columns(frame, sample_limit=sample_limit)
    numeric_cols = [
        row["column"]
        for _, row in columns_profile.iterrows()
        if row["mean"] is not None and row["unique_count"] > 2
    ]

    numeric_stats: Dict[str, Dict[str, float]] = {}
    if numeric_cols:
        described = frame[numeric_cols].apply(_coerce_numeric).describe().to_dict()
        for column, stats in described.items():
            # ``describe`` can return None for a fully-empty column, and NaN for
            # undefined statistics; both are dropped rather than coerced.
            numeric_stats[column] = {
                key: float(value)
                for key, value in stats.items()
                if value is not None and value == value
            }

    key_report: Dict[str, Any] = {}
    for key in key_candidates or []:
        if key not in frame.columns:
            continue
        series = frame[key]
        key_report[key] = {
            "unique_values": int(series.nunique(dropna=True)),
            "rows": int(len(frame)),
            "is_unique": bool(series.nunique(dropna=True) == len(frame)),
            "null_count": int(series.isna().sum()),
            "repeats": int(len(frame) - series.nunique(dropna=True)),
        }

    payload = {
        "name": name,
        "rows": int(frame.shape[0]),
        "columns": int(frame.shape[1]),
        "memory_mb": round(float(frame.memory_usage(deep=True).sum()) / 1e6, 4),
        "total_cells": int(frame.shape[0] * frame.shape[1]),
        "total_nulls": int(frame.isna().sum().sum()),
        "overall_null_pct": round(
            100.0 * float(frame.isna().sum().sum()) / max(frame.shape[0] * frame.shape[1], 1), 4
        ),
        "duplicate_rows_exact": int(frame.duplicated().sum()),
        "column_profile": columns_profile,
        "numeric_summary": numeric_stats,
        "key_candidates": key_report,
        "id_like_columns": [
            c
            for c in frame.columns
            if columns_profile.set_index("column").loc[c, "unique_count"] == len(frame)
        ],
    }
    return payload


def profile_summary_frame(profile: Dict[str, Any]) -> pd.DataFrame:
    """Compact human-readable profile used by the dashboard and reports."""
    columns_profile: pd.DataFrame = profile.get("column_profile", pd.DataFrame())
    if columns_profile.empty:
        return columns_profile
    keep = [
        "column",
        "dtype",
        "non_null",
        "null_count",
        "null_pct",
        "unique_count",
        "duplicate_values",
        "min",
        "max",
        "mean",
        "median",
        "std",
    ]
    present = [c for c in keep if c in columns_profile.columns]
    return columns_profile[present].copy()


def profile_report_markdown(profile: Dict[str, Any]) -> str:
    """Render a profiling payload as markdown (used in documentation)."""
    lines = [
        f"### Profile — {profile['name']}",
        "",
        f"- Rows: **{profile['rows']:,}**",
        f"- Columns: **{profile['columns']}**",
        f"- Cells: {profile['total_cells']:,}",
        f"- Missing cells: {profile['total_nulls']:,} ({profile['overall_null_pct']}%)",
        f"- Exact duplicate rows: {profile['duplicate_rows_exact']:,}",
        "",
    ]
    frame = profile_summary_frame(profile)
    if not frame.empty:
        with_header = frame.copy()
        lines.append(with_header.to_markdown(index=False))
        lines.append("")
    return "\n".join(lines)


def numeric_range(frame: pd.DataFrame, column: str) -> Dict[str, float]:
    """Min/max/mean/median/std for one column, NaN-safe."""
    if column not in frame.columns:
        return {}
    series = _coerce_numeric(frame[column]).dropna()
    if series.empty:
        return {}
    return {
        "min": float(series.min()),
        "max": float(series.max()),
        "mean": float(round(series.mean(), 6)),
        "median": float(series.median()),
        "std": float(round(series.std(), 6)) if len(series) > 1 else 0.0,
    }


def zscore_flags(series: pd.Series, threshold: float = 3.0) -> pd.Series:
    """Boolean mask of ``|z| > threshold`` using population-free sample std."""
    numeric = _coerce_numeric(series)
    std = numeric.std()
    if not std or np.isnan(std):
        return pd.Series(False, index=series.index)
    return ((numeric - numeric.mean()).abs() / std) > threshold

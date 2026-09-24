"""Small IO helpers shared by every layer (JSON, CSV, text, DataFrames)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, List, Optional, Union

import pandas as pd

PathLike = Union[str, Path]


def _prepare(path: PathLike) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def write_json(path: PathLike, payload: Any) -> Path:
    """Write JSON (UTF-8, indented, NaN-safe) and return the resolved path."""
    target = _prepare(path)

    def _default(obj: Any) -> Any:
        if hasattr(obj, "isoformat"):
            return obj.isoformat()
        if hasattr(obj, "item"):
            return obj.item()
        return str(obj)

    target.write_text(
        json.dumps(payload, indent=2, default=_default, allow_nan=False),
        encoding="utf-8",
    )
    return target


def read_json(path: PathLike) -> Any:
    target = Path(path)
    if not target.exists():
        return None
    return json.loads(target.read_text(encoding="utf-8"))


def write_text(path: PathLike, text: str) -> Path:
    target = _prepare(path)
    target.write_text(text, encoding="utf-8")
    return target


def read_text(path: PathLike) -> Optional[str]:
    target = Path(path)
    if not target.exists():
        return None
    return target.read_text(encoding="utf-8")


def write_csv(path: PathLike, frame: pd.DataFrame, index: bool = False) -> Path:
    """Write a DataFrame to CSV, creating parent directories as needed."""
    target = _prepare(path)
    frame.to_csv(target, index=index)
    return target


def read_csv(path: PathLike, **kwargs: Any) -> pd.DataFrame:
    return pd.read_csv(path, **kwargs)


def frame_records(frame: Optional[pd.DataFrame], limit: Optional[int] = None) -> List[dict]:
    """JSON-safe list-of-dicts for embedding DataFrames in reports."""
    if frame is None or frame.empty:
        return []
    subset = frame.head(limit) if limit else frame
    return json.loads(subset.to_json(orient="records", date_format="iso"))

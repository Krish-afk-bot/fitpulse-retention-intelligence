"""SQL warehouse engine.

Responsibilities
----------------
* create the physical schema from ``sql/schema.sql``
* load curated DataFrames into their tables with a column-contract audit
* apply the analytical views from ``sql/views.sql``
* execute the named query library (``metrics.sql``, ``joins.sql``,
  ``windows.sql``, ``validation.sql``)

The layer is deliberately thin and standard SQL. SQLite is used locally; the DDL
avoids vendor-specific syntax beyond ``strftime``/``julianday`` so a PostgreSQL
migration only requires type substitutions.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

import numpy as np
import pandas as pd

from ..common.config import DB_PATH, SQL_DIR
from ..common.logging_utils import get_logger

logger = get_logger("sql_layer")

#: Named-query marker understood by :func:`parse_named_queries`.
QUERY_MARKER = re.compile(r"^\s*--\s*@query:\s*([A-Za-z0-9_]+)\s*$", re.MULTILINE)


@dataclass
class TableLoadReport:
    """Audit trail for one table load."""

    table: str
    rows_loaded: int
    columns_loaded: List[str] = field(default_factory=list)
    columns_dropped: List[str] = field(default_factory=list)
    columns_missing: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "table": self.table,
            "rows_loaded": self.rows_loaded,
            "columns_loaded": len(self.columns_loaded),
            "columns_dropped": self.columns_dropped,
            "columns_missing": self.columns_missing,
        }


# ---------------------------------------------------------------------------
# Connection + schema
# ---------------------------------------------------------------------------
def connect(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """Open (creating if needed) the SQLite database."""
    path = Path(db_path or DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON;")
    logger.info("SQLite connection opened: %s", path)
    return connection


def read_script(path: Path) -> str:
    target = Path(path)
    if not target.exists():
        raise FileNotFoundError(f"SQL script not found: {target}")
    return target.read_text(encoding="utf-8")


def apply_schema(connection: sqlite3.Connection, schema_path: Optional[Path] = None) -> None:
    """Create tables and indexes from ``sql/schema.sql``."""
    script = read_script(schema_path or (SQL_DIR / "schema.sql"))
    connection.executescript(script)
    connection.commit()
    logger.info("Schema applied from %s", schema_path or SQL_DIR / "schema.sql")


def apply_views(connection: sqlite3.Connection, views_path: Optional[Path] = None) -> None:
    """Create the analytical views."""
    script = read_script(views_path or (SQL_DIR / "views.sql"))
    # executescript issues an implicit COMMIT first, so views land in the same db.
    connection.executescript(script)
    connection.commit()
    logger.info("Views applied from %s", views_path or SQL_DIR / "views.sql")


def table_columns(connection: sqlite3.Connection, table: str) -> List[str]:
    rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
    return [row["name"] for row in rows]


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------
def _to_sql_value(value: Any) -> Any:
    """Convert pandas/numpy scalars into values SQLite can bind.

    Handles the full set of missing-value sentinels pandas can emit
    (``None``, ``NaN``, ``pd.NA``, ``NaT``, numpy ``nan``) so a nullable column
    never aborts a load.
    """
    import math

    # --- missing-value sentinels -----------------------------------------
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if type(value).__name__ in {"NAType", "NaTType"}:
        return None

    # --- booleans before numeric (numpy bool is an integer subclass) ------
    if isinstance(value, (bool, np.bool_)):
        return int(bool(value))

    # --- numeric ---------------------------------------------------------
    if isinstance(value, (float, np.floating)):
        numeric = float(value)
        return None if math.isnan(numeric) or math.isinf(numeric) else numeric
    if isinstance(value, (int, np.integer)):
        return int(value)

    # --- temporal ----------------------------------------------------------
    if isinstance(value, pd.Timestamp):
        return value.isoformat(sep=" ")
    if isinstance(value, (pd.Period, pd.Timedelta)):
        return str(value)
    if hasattr(value, "to_pydatetime"):
        try:
            return value.to_pydatetime().isoformat(sep=" ")
        except (ValueError, TypeError):
            return str(value)

    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        try:
            return _to_sql_value(value.item())
        except (ValueError, AttributeError):
            return str(value)
    return value


def load_frame(
    connection: sqlite3.Connection, frame: pd.DataFrame, table: str
) -> TableLoadReport:
    """Insert a DataFrame into an existing table, honouring the table's columns.

    Columns in the frame that the table does not define are dropped and
    reported; table columns the frame does not provide are left NULL and
    reported. Nothing is silently lost.
    """
    if frame is None or frame.empty:
        return TableLoadReport(table=table, rows_loaded=0, columns_missing=table_columns(connection, table))

    schema_columns = table_columns(connection, table)
    if not schema_columns:
        raise ValueError(f"Table '{table}' does not exist; apply the schema first.")

    provided = [c for c in schema_columns if c in frame.columns]
    dropped = [c for c in frame.columns if c not in schema_columns]
    missing = [c for c in schema_columns if c not in frame.columns]

    subset = frame[provided].copy()

    # Booleans (including pandas nullable "boolean" and object columns holding
    # real bools) are stored as 0/1 integers for portability.
    bool_like = {
        column
        for column in provided
        if pd.api.types.is_bool_dtype(frame[column].dtype)
        or frame[column].map(lambda value: isinstance(value, bool)).any()
    }
    for column in bool_like:
        subset[column] = subset[column].map(lambda v: None if pd.isna(v) else int(bool(v)))

    records = [
        tuple(_to_sql_value(value) for value in row) for row in subset.itertuples(index=False, name=None)
    ]
    placeholders = ", ".join(["?"] * len(provided))
    quoted = ", ".join(f'"{c}"' for c in provided)
    connection.executemany(
        f'INSERT OR REPLACE INTO "{table}" ({quoted}) VALUES ({placeholders})', records
    )
    connection.commit()

    report = TableLoadReport(
        table=table,
        rows_loaded=len(records),
        columns_loaded=provided,
        columns_dropped=dropped,
        columns_missing=missing,
    )
    if dropped:
        preview = ", ".join(dropped[:5]) + (" …" if len(dropped) > 5 else "")
        logger.warning(
            "Table %s: %s non-schema column(s) not loaded (%s). These remain available in the "
            "curated CSV layer.",
            table,
            len(dropped),
            preview,
        )
    if missing:
        logger.warning("Table %s: unfilled schema columns %s", table, missing)
    logger.info("Loaded %s rows into %s", f"{report.rows_loaded:,}", table)
    return report


def load_tables(
    connection: sqlite3.Connection, frames: Dict[str, pd.DataFrame]
) -> List[TableLoadReport]:
    """Load several named DataFrames into their matching tables."""
    reports: List[TableLoadReport] = []
    for table, frame in frames.items():
        if frame is None:
            continue
        reports.append(load_frame(connection, frame, table))
    return reports


# ---------------------------------------------------------------------------
# Query parsing + execution
# ---------------------------------------------------------------------------
def parse_named_queries(script: str) -> Dict[str, str]:
    """Split a script into ``{name: sql}`` using the ``-- @query:`` marker."""
    matches = list(QUERY_MARKER.finditer(script))
    queries: Dict[str, str] = {}
    for index, match in enumerate(matches):
        name = match.group(1)
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(script)
        body = script[start:end]
        # Strip documentation comments that belong to the block header.
        lines = [line for line in body.splitlines() if not line.strip().startswith("-- @description")]
        sql = "\n".join(lines).strip().rstrip(";").strip()
        if sql:
            queries[name] = sql
    return queries


def run_query(connection: sqlite3.Connection, sql: str, params: Optional[Sequence[Any]] = None) -> pd.DataFrame:
    """Execute one SQL statement and return a DataFrame."""
    return pd.read_sql_query(sql, connection, params=params)


def run_named_queries(
    connection: sqlite3.Connection, script_path: Path
) -> Dict[str, pd.DataFrame]:
    """Execute every named query in a script file."""
    queries = parse_named_queries(read_script(script_path))
    results: Dict[str, pd.DataFrame] = {}
    for name, sql in queries.items():
        try:
            results[name] = run_query(connection, sql)
        except Exception as exc:  # noqa: BLE001 - reported, not fatal
            logger.error("Query '%s' failed: %s", name, exc)
            results[name] = pd.DataFrame({"error": [str(exc)]})
    logger.info("Executed %s named queries from %s", len(results), Path(script_path).name)
    return results


def run_script_library(connection: sqlite3.Connection, directory: Optional[Path] = None) -> Dict[str, pd.DataFrame]:
    """Execute every named query across all SQL library files."""
    directory = Path(directory or SQL_DIR)
    results: Dict[str, pd.DataFrame] = {}
    for filename in ("metrics.sql", "joins.sql", "windows.sql", "validation.sql"):
        path = directory / filename
        if not path.exists():
            continue
        for name, frame in run_named_queries(connection, path).items():
            results[name] = frame
    return results


def scalar(connection: sqlite3.Connection, sql: str) -> Any:
    """Return the first column of the first row, or ``None``."""
    row = connection.execute(sql).fetchone()
    if row is None:
        return None
    return row[0]


def dataframe_to_sql_table(connection: sqlite3.Connection, frame: pd.DataFrame, table: str) -> int:
    """Replace a table's contents with a DataFrame (used for ad-hoc loads)."""
    if frame is None:
        return 0
    connection.execute(f'DELETE FROM "{table}"')
    report = load_frame(connection, frame, table)
    return report.rows_loaded

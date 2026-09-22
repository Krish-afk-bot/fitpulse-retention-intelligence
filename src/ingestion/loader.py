"""Ingestion layer: robust CSV loading, file validation, schema detection.

The ingestion layer is deliberately independent of Streamlit and of any
analysis code. It can be driven from the CLI, from tests, or from the
dashboard's upload workflow.

Responsibilities
----------------
1. Validate a candidate file (exists, non-empty, CSV, within size limit).
2. Resolve the file encoding (UTF-8 with BOM, UTF-8, Latin-1, CP1252).
3. Sniff the delimiter.
4. Load into a DataFrame with everything read as string for a lossless
   first look, then report the *inferred* dtypes.
5. Inspect the schema against a :class:`SourceSchema` contract.
6. Map source columns onto the canonical model.
"""

from __future__ import annotations

import csv
import io
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union

import numpy as np
import pandas as pd

from ..common.config import (
    ACTIVITY_RAW_FILENAME,
    MEMBERSHIP_RAW_FILENAME,
    RAW_DIR,
    get_settings,
)
from ..common.logging_utils import get_logger
from .schema import ACTIVITY_SOURCE, MEMBERSHIP_SOURCE, SourceSchema

logger = get_logger("ingestion")

#: Refuse files above this size (100 MB) — a reasonable local/dashboard guard.
MAX_FILE_BYTES = 100 * 1024 * 1024

#: Encodings attempted, in order.
ENCODING_CANDIDATES: Tuple[str, ...] = ("utf-8-sig", "utf-8", "latin-1", "cp1252")

#: Accepted upload formats. Excel support uses openpyxl / xlrd when installed.
SUPPORTED_SUFFIXES: Tuple[str, ...] = (".csv", ".txt", ".xlsx", ".xls")
EXCEL_SUFFIXES: Tuple[str, ...] = (".xlsx", ".xls")

PathLike = Union[str, Path]


class IngestionError(RuntimeError):
    """Raised when a source file cannot be read at all."""


class SchemaMismatchError(IngestionError):
    """Raised when required columns are absent from a source file."""


# ---------------------------------------------------------------------------
# Result containers
# ---------------------------------------------------------------------------
@dataclass
class SchemaReport:
    """Outcome of comparing a DataFrame to a source contract."""

    source: str
    present_expected: List[str] = field(default_factory=list)
    missing_required: List[str] = field(default_factory=list)
    missing_optional: List[str] = field(default_factory=list)
    unexpected: List[str] = field(default_factory=list)
    inferred_types: Dict[str, str] = field(default_factory=dict)
    status: str = "PASS"

    def as_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "status": self.status,
            "present_expected": self.present_expected,
            "missing_required": self.missing_required,
            "missing_optional": self.missing_optional,
            "unexpected": self.unexpected,
            "inferred_types": self.inferred_types,
        }


@dataclass
class LoadedSource:
    """A successfully ingested source file plus its provenance metadata."""

    name: str
    path: Optional[Path]
    frame: pd.DataFrame
    schema_report: SchemaReport
    encoding: str = "utf-8"
    delimiter: str = ","
    dataset_label: str = ""
    dataset_url: str = ""
    dataset_license: str = ""
    origin: str = "local file"
    warnings: List[str] = field(default_factory=list)
    #: Which conceptual source this file plays (``activity`` / ``membership``).
    role: str = ""
    #: The confirmed column mapping, when the file arrived through the schema
    #: mapping layer rather than the reference contract.
    mapping: Optional[Dict[str, Any]] = None
    #: Capabilities the mapping enables for this file.
    capabilities: List[Dict[str, Any]] = field(default_factory=list)
    #: Compatibility assessment, when available.
    compatibility: Optional[Dict[str, Any]] = None
    #: Documented conventions applied because an optional field was absent.
    assumptions: List[str] = field(default_factory=list)
    #: ``True`` when the identifier repeats across rows (a real member key).
    #: ``None`` means "not assessed — use the reference contract's behaviour".
    member_key_repeatable: Optional[bool] = None
    #: Original header names, kept for provenance/display.
    source_columns: List[str] = field(default_factory=list)
    rows_in_source: int = 0
    #: True when this source came from the documented reference datasets.
    is_reference: bool = False

    @property
    def rows(self) -> int:
        return int(self.frame.shape[0])

    @property
    def columns(self) -> int:
        return int(self.frame.shape[1])

    def as_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "path": str(self.path) if self.path else None,
            "rows": self.rows,
            "columns": self.columns,
            "encoding": self.encoding,
            "delimiter": self.delimiter,
            "dataset_label": self.dataset_label,
            "dataset_url": self.dataset_url,
            "dataset_license": self.dataset_license,
            "origin": self.origin,
            "warnings": self.warnings,
            "schema": self.schema_report.as_dict(),
        }


# ---------------------------------------------------------------------------
# File validation + encoding
# ---------------------------------------------------------------------------
def validate_file(path: PathLike, max_bytes: int = MAX_FILE_BYTES) -> Path:
    """Validate that ``path`` is a readable, non-empty, in-budget CSV file."""
    target = Path(path)
    if not target.exists():
        raise IngestionError(f"Dataset not found: {target}. Please upload a valid dataset to begin.")
    if not target.is_file():
        raise IngestionError(f"Not a file: {target}")
    if target.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise IngestionError(
            f"Unsupported file type '{target.suffix}'. Accepted formats: "
            f"{', '.join(sorted(SUPPORTED_SUFFIXES))}."
        )
    size = target.stat().st_size
    if size == 0:
        raise IngestionError(f"File is empty: {target.name}")
    if size > max_bytes:
        raise IngestionError(
            f"File {target.name} is {size / 1e6:.1f} MB, above the "
            f"{max_bytes / 1e6:.0f} MB limit."
        )
    return target


def detect_encoding(path: PathLike, sample_bytes: int = 65536) -> str:
    """Return the first encoding from the candidate list that decodes cleanly."""
    raw = Path(path).read_bytes()[:sample_bytes]
    for encoding in ENCODING_CANDIDATES:
        try:
            raw.decode(encoding)
            return encoding
        except (UnicodeDecodeError, LookupError):
            continue
    logger.warning("No clean encoding found for %s; falling back to latin-1.", path)
    return "latin-1"


def _detect_delimiter(text: str) -> str:
    sample = text[:8192]
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        return ","


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------
def load_csv_robust(
    path: PathLike,
    *,
    as_str: bool = False,
    nrows: Optional[int] = None,
) -> Tuple[pd.DataFrame, str, str]:
    """Load a CSV handling encoding + delimiter quirks.

    Parameters
    ----------
    as_str:
        When ``True`` every column is read as string, giving a lossless first
        look used for profiling and schema detection.
    nrows:
        Optionally limit the number of rows (used for fast previews).

    Returns
    -------
    ``(frame, encoding, delimiter)``
    """
    target = validate_file(path)
    encoding = detect_encoding(target)
    text_sample = target.read_text(encoding=encoding, errors="replace")[:8192]
    delimiter = _detect_delimiter(text_sample)

    frame = pd.read_csv(
        target,
        encoding=encoding,
        sep=delimiter,
        dtype=str if as_str else None,
        nrows=nrows,
        skipinitialspace=True,
        keep_default_na=True,
    )
    frame.columns = [str(col).strip() for col in frame.columns]
    logger.info(
        "Loaded %s | rows=%s cols=%s | encoding=%s delimiter=%r",
        target.name,
        f"{frame.shape[0]:,}",
        frame.shape[1],
        encoding,
        delimiter,
    )
    return frame, encoding, delimiter


def preview(path: PathLike, n: int = 10) -> pd.DataFrame:
    """Return the first ``n`` rows for dashboard previews."""
    frame, _, _ = load_csv_robust(path, nrows=n)
    return frame


# ---------------------------------------------------------------------------
# Schema inspection
# ---------------------------------------------------------------------------
def _infer_column_type(series: pd.Series) -> str:
    """Best-effort semantic type of a raw (string-inferred) column."""
    non_null = series.dropna()
    if non_null.empty:
        return "empty"
    numeric = pd.to_numeric(non_null, errors="coerce")
    if numeric.notna().mean() >= 0.95:
        unique_numeric = numeric.dropna()
        if np.all(np.mod(unique_numeric, 1) == 0) and unique_numeric.between(-9e15, 9e15).all():
            return "integer"
        return "float"
    if pd.api.types.is_bool_dtype(non_null):
        return "boolean"
    if set(non_null.astype(str).str.strip().str.lower().unique()) <= {"true", "false", "yes", "no", "0", "1"}:
        return "boolean"
    sample_text = non_null.astype(str).str.strip()
    if sample_text.str.match(r"^\d{1,2}:\d{2}(:\d{2})?$").mean() >= 0.9:
        return "time"
    parsed = pd.to_datetime(non_null, errors="coerce", format="mixed")
    if parsed.notna().mean() >= 0.9:
        return "date"
    if non_null.nunique() <= max(50, int(0.05 * len(series))):
        return "categorical"
    return "text"


def inspect_source_schema(frame: pd.DataFrame, source: SourceSchema) -> SchemaReport:
    """Compare a loaded frame against a source contract."""
    columns = list(frame.columns)
    expected = set(source.expected_columns)
    present = [c for c in source.expected_columns if c in columns]
    missing_required = [c for c in source.required_columns if c not in columns]
    missing_optional = [c for c in source.expected_columns if c not in columns and c not in missing_required]
    unexpected = [c for c in columns if c not in expected]

    inferred = {col: _infer_column_type(frame[col]) for col in columns}

    if missing_required:
        status = "FAIL"
    elif missing_optional or unexpected:
        status = "WARNING"
    else:
        status = "PASS"

    report = SchemaReport(
        source=source.name,
        present_expected=present,
        missing_required=missing_required,
        missing_optional=missing_optional,
        unexpected=unexpected,
        inferred_types=inferred,
        status=status,
    )
    if missing_required:
        logger.error(
            "Schema FAIL for %s: missing required columns %s", source.name, missing_required
        )
    elif status == "WARNING":
        logger.warning(
            "Schema WARNING for %s: missing optional=%s unexpected=%s",
            source.name,
            missing_optional,
            unexpected,
        )
    return report


# ---------------------------------------------------------------------------
# Canonical mapping
# ---------------------------------------------------------------------------
def _normalize_header(name: str) -> str:
    """Case/space/underscore-insensitive header key used for fuzzy matching."""
    decomposed = unicodedata.normalize("NFKD", str(name))
    ascii_only = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return ascii_only.strip().lower().replace(" ", "_").replace("-", "_")


def resolve_column(frame: pd.DataFrame, wanted: str) -> Optional[str]:
    """Find the actual column in ``frame`` matching a logical name."""
    if wanted in frame.columns:
        return wanted
    lookup = {_normalize_header(c): c for c in frame.columns}
    return lookup.get(_normalize_header(wanted))


def map_to_canonical(frame: pd.DataFrame, source: SourceSchema) -> Dict[str, pd.Series]:
    """Return canonical columns extracted from a raw source frame.

    Missing optional source columns are returned as ``None`` so downstream code
    can degrade gracefully instead of crashing.
    """
    resolved: Dict[str, Any] = {}
    # ``column_map`` is keyed by *source* column and valued by canonical name.
    for source_column, canonical in source.column_map.items():
        actual = resolve_column(frame, source_column)
        resolved[canonical] = frame[actual] if actual is not None else None
    return resolved


# ---------------------------------------------------------------------------
# Convenience loaders
# ---------------------------------------------------------------------------
def _load_one(
    source: SourceSchema,
    path: PathLike,
    *,
    enforce_required: bool = True,
) -> LoadedSource:
    frame, encoding, delimiter = load_csv_robust(path, as_str=True)
    report = inspect_source_schema(frame, source)
    warnings: List[str] = []
    if report.missing_required and enforce_required:
        raise SchemaMismatchError(
            f"The uploaded file does not match the expected schema for '{source.name}'. "
            f"Missing required columns: {report.missing_required}. See Data Quality for details."
        )
    if report.missing_optional:
        warnings.append(f"Missing optional columns: {report.missing_optional}")
    if report.unexpected:
        warnings.append(f"Unexpected columns ignored: {report.unexpected}")
    warnings.extend(source.known_limitations)

    return LoadedSource(
        name=source.name,
        path=Path(path),
        frame=frame,
        schema_report=report,
        encoding=encoding,
        delimiter=delimiter,
        dataset_label=source.label,
        dataset_url=source.url,
        dataset_license=source.license,
        warnings=warnings,
    )


def load_activity_source(
    path: Optional[PathLike] = None, enforce_required: bool = True
) -> LoadedSource:
    """Load the activity/attendance source."""
    resolved = Path(path) if path else RAW_DIR / ACTIVITY_RAW_FILENAME
    return _load_one(ACTIVITY_SOURCE, resolved, enforce_required=enforce_required)


def load_membership_source(
    path: Optional[PathLike] = None, enforce_required: bool = True
) -> LoadedSource:
    """Load the membership/churn source."""
    resolved = Path(path) if path else RAW_DIR / MEMBERSHIP_RAW_FILENAME
    return _load_one(MEMBERSHIP_SOURCE, resolved, enforce_required=enforce_required)


def load_sources(
    activity_path: Optional[PathLike] = None,
    membership_path: Optional[PathLike] = None,
    enforce_required: bool = True,
) -> Dict[str, LoadedSource]:
    """Load both sources into a name-keyed mapping."""
    return {
        "activity": load_activity_source(activity_path, enforce_required),
        "membership": load_membership_source(membership_path, enforce_required),
    }


def reader_from_upload(uploaded_file: Any, source: SourceSchema) -> LoadedSource:
    """Ingest a Streamlit ``UploadedFile`` without writing it to disk first."""
    if uploaded_file is None:
        raise IngestionError("Please upload a valid dataset to begin.")
    name = getattr(uploaded_file, "name", "upload.csv")
    if not str(name).lower().endswith(".csv"):
        raise IngestionError(
            f"Unsupported file type for '{name}'. Please upload a .csv file."
        )
    raw = uploaded_file.getvalue() if hasattr(uploaded_file, "getvalue") else uploaded_file.read()
    if not raw:
        raise IngestionError(f"Uploaded file '{name}' is empty.")

    decoded = None
    for encoding in ENCODING_CANDIDATES:
        try:
            decoded = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if decoded is None:
        raise IngestionError(f"Could not decode '{name}' with any supported encoding.")

    delimiter = _detect_delimiter(decoded)
    frame = pd.read_csv(
        io.StringIO(decoded),
        sep=delimiter,
        dtype=str,
        skipinitialspace=True,
        keep_default_na=True,
    )
    frame.columns = [str(col).strip() for col in frame.columns]
    report = inspect_source_schema(frame, source)

    if report.missing_required:
        raise SchemaMismatchError(
            f"The uploaded file does not match the expected schema for '{source.name}'. "
            f"Missing required columns: {report.missing_required}. See Data Quality for details."
        )

    return LoadedSource(
        name=source.name,
        path=None,
        frame=frame,
        schema_report=report,
        encoding=encoding,
        delimiter=delimiter,
        dataset_label=source.label,
        dataset_url=source.url,
        dataset_license=source.license,
        origin=f"dashboard upload ({name})",
        warnings=list(source.known_limitations),
    )


# ---------------------------------------------------------------------------
# Generic ingestion: any compatible CSV/Excel export
# ---------------------------------------------------------------------------
def read_tabular_bytes(raw: bytes, filename: str) -> Tuple[pd.DataFrame, str, str]:
    """Read CSV/TXT/Excel bytes into a raw ``dtype=str`` frame.

    Everything is read as text so the mapping layer sees the file exactly as the
    user stored it; type conversion belongs to the cleaning stage.
    """
    if not raw:
        raise IngestionError(f"Uploaded file '{filename}' is empty.")
    suffix = Path(str(filename)).suffix.lower()

    if suffix in EXCEL_SUFFIXES:
        try:
            frame = pd.read_excel(io.BytesIO(raw), dtype=str, sheet_name=0)
        except ImportError as exc:  # pragma: no cover - depends on environment
            raise IngestionError(
                f"Excel support for '{filename}' needs a reader library. "
                "Install it with: pip install openpyxl xlrd"
            ) from exc
        except Exception as exc:  # noqa: BLE001 - surfaced as a friendly error
            raise IngestionError(f"Could not read the Excel file '{filename}': {exc}") from exc
        frame.columns = [str(col).strip() for col in frame.columns]
        return frame, "excel", ","

    decoded = None
    for encoding in ENCODING_CANDIDATES:
        try:
            decoded = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if decoded is None:
        raise IngestionError(
            f"Could not decode '{filename}' with any supported encoding "
            f"({', '.join(ENCODING_CANDIDATES)})."
        )

    delimiter = _detect_delimiter(decoded)
    frame = pd.read_csv(
        io.StringIO(decoded),
        sep=delimiter,
        dtype=str,
        skipinitialspace=True,
        keep_default_na=True,
    )
    frame.columns = [str(col).strip() for col in frame.columns]
    return frame, encoding, delimiter


def frame_from_upload(uploaded_file: Any) -> Tuple[pd.DataFrame, str]:
    """Read a Streamlit ``UploadedFile`` into a raw frame without touching disk."""
    if uploaded_file is None:
        raise IngestionError("Please upload a valid dataset to begin.")
    name = str(getattr(uploaded_file, "name", "upload"))
    raw = uploaded_file.getvalue() if hasattr(uploaded_file, "getvalue") else uploaded_file.read()
    frame, encoding, _delimiter = read_tabular_bytes(raw, name)
    logger.info("Read %s | rows=%s cols=%s | encoding=%s", name, f"{len(frame):,}", frame.shape[1], encoding)
    return frame, name


def ingest_mapped_frame(
    frame: pd.DataFrame,
    *,
    role: Optional[str] = None,
    overrides: Optional[Dict[str, Optional[str]]] = None,
    label: str = "",
    origin: str = "uploaded file",
    url: str = "",
    license: str = "",
) -> Tuple["LoadedSource", Any, Any]:
    """Map an arbitrary dataset onto the canonical model.

    Returns ``(loaded_source, mapping, compatibility_report)`` — the source is
    already renamed onto the contract columns the cleaning layer expects.
    """
    from .mapping import assess_compatibility, build_loaded_source, member_key_repeatable, suggest_mapping

    mapping = suggest_mapping(frame, role=role, overrides=overrides)
    report = assess_compatibility(frame, mapping)
    source = build_loaded_source(
        frame,
        mapping,
        report,
        label=label or f"uploaded {len(frame):,}-row dataset",
        origin=origin,
        url=url,
        license=license,
    )
    return source, mapping, report


def load_dataset_path(
    path: PathLike,
    role: Optional[str] = None,
    overrides: Optional[Dict[str, Optional[str]]] = None,
) -> Tuple["LoadedSource", Any, Any]:
    """Ingest any compatible file from disk through the mapping layer."""
    target = validate_file(path)
    frame, _encoding, _delimiter = read_tabular_bytes(target.read_bytes(), target.name)
    return ingest_mapped_frame(
        frame,
        role=role,
        overrides=overrides,
        label=target.name,
        origin=f"local file ({target.name})",
    )


def reference_source(role: str) -> LoadedSource:
    """Load one of the documented reference datasets through the mapping layer.

    The bundled Kaggle files still run through the same mapping engine as any
    other upload, so the reference path exercises the generic code.
    """
    if role == "activity":
        loaded = load_activity_source()
    elif role == "membership":
        loaded = load_membership_source()
    else:  # pragma: no cover - defensive
        raise IngestionError(f"Unknown source role '{role}'.")

    # The reference files still pass through the mapping engine, so the reference
    # path reports the same detection, compatibility and capability metadata as
    # any other dataset — and the generic code is exercised on every run.
    from .mapping import assess_compatibility, member_key_repeatable, suggest_mapping

    mapping = suggest_mapping(loaded.frame, role=role)
    report = assess_compatibility(loaded.frame, mapping)

    loaded.is_reference = True
    loaded.role = role
    loaded.mapping = mapping.as_dict()
    loaded.compatibility = report.as_dict()
    loaded.capabilities = [item.as_dict() for item in report.capabilities]
    loaded.source_columns = [str(column) for column in loaded.frame.columns]
    loaded.rows_in_source = int(len(loaded.frame))
    loaded.member_key_repeatable = member_key_repeatable(loaded.frame, mapping.column_for("member_id"))
    loaded.assumptions = list(report.assumptions)
    if role == "activity":
        loaded.assumptions.append(
            "Reference activity source: its member_id is unique per row, so it is treated as a "
            "record sequence rather than a member key."
        )
    loaded.warnings = list(loaded.warnings) + list(report.warnings)
    return loaded


# ---------------------------------------------------------------------------
# Optional: download the public sources (used by scripts/ingest.py)
# ---------------------------------------------------------------------------
def download_kaggle_source(source: SourceSchema, dest_dir: PathLike = RAW_DIR) -> Path:
    """Download a public Kaggle dataset archive without the Kaggle CLI.

    Only the two documented public sources are supported. No credentials are
    used and nothing is uploaded anywhere.
    """
    import urllib.request
    import zipfile

    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    slug = source.url.rstrip("/").split("/datasets/")[-1]
    archive = dest_dir / f"{source.name}_raw.zip"
    api_url = f"https://www.kaggle.com/api/v1/datasets/download/{slug}"

    logger.info("Downloading %s", api_url)
    with urllib.request.urlopen(api_url, timeout=120) as response:  # noqa: S310 (fixed host)
        archive.write_bytes(response.read())

    with zipfile.ZipFile(archive) as zf:
        zf.extractall(dest_dir)
    logger.info("Extracted %s into %s", archive.name, dest_dir)
    return dest_dir / source.filename


def missing_source_files() -> List[Path]:
    """Return the expected raw files that are not on disk yet."""
    expected = [
        RAW_DIR / ACTIVITY_SOURCE.filename,
        RAW_DIR / MEMBERSHIP_SOURCE.filename,
    ]
    return [path for path in expected if not path.exists()]


def attempt_source_download() -> List[Path]:
    """Download any missing expected source file. Returns the paths attempted."""
    attempted: List[Path] = []
    for path, source in (
        (RAW_DIR / ACTIVITY_SOURCE.filename, ACTIVITY_SOURCE),
        (RAW_DIR / MEMBERSHIP_SOURCE.filename, MEMBERSHIP_SOURCE),
    ):
        if path.exists():
            continue
        try:
            download_kaggle_source(source)
            attempted.append(path)
        except Exception as exc:  # noqa: BLE001 - reported, never fatal
            logger.warning("Automatic download of '%s' failed: %s", source.name, exc)
    return attempted


__all__ = [
    "IngestionError",
    "SchemaMismatchError",
    "SchemaReport",
    "LoadedSource",
    "MAX_FILE_BYTES",
    "ENCODING_CANDIDATES",
    "validate_file",
    "detect_encoding",
    "load_csv_robust",
    "read_tabular_bytes",
    "frame_from_upload",
    "ingest_mapped_frame",
    "load_dataset_path",
    "reference_source",
    "SUPPORTED_SUFFIXES",
    "EXCEL_SUFFIXES",
    "preview",
    "inspect_source_schema",
    "resolve_column",
    "map_to_canonical",
    "load_activity_source",
    "load_membership_source",
    "load_sources",
    "reader_from_upload",
    "download_kaggle_source",
    "missing_source_files",
    "attempt_source_download",
]

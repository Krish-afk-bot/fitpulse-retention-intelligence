"""Structured logging for pipeline stages.

Produces both:

* human-readable console lines in the PRD format
  ``[10:21:04] INGESTION     PASS  12,400 rows``
* machine-readable JSON records persisted per pipeline run, with the fields
  ``timestamp``, ``stage``, ``status``, ``records_processed``,
  ``records_failed``, ``duration`` and ``error``.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import LOGS_DIR, get_settings

_LOGGER_NAME = "fitpulse"
_configured = False


def configure_console_encoding() -> None:
    """Make stdout/stderr tolerant of non-ASCII output.

    Windows consoles default to a legacy code page, which would crash on the
    typographic characters used in a few stage labels and report titles. Falling
    back to ``errors='replace'`` keeps the CLI working everywhere.
    """
    import sys

    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):  # pragma: no cover - stream may be redirected
            pass


def setup_logging(level: Optional[str] = None, log_file: Optional[Path] = None) -> logging.Logger:
    """Configure the package logger once, writing to console and a log file."""
    global _configured
    logger = logging.getLogger(_LOGGER_NAME)
    if _configured:
        return logger

    configure_console_encoding()

    settings = get_settings()
    resolved_level = getattr(logging, (level or settings.log_level).upper(), logging.INFO)
    logger.setLevel(resolved_level)
    logger.propagate = False

    fmt = logging.Formatter(
        fmt="[%(asctime)s] %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    logger.addHandler(console)

    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(log_file or LOGS_DIR / "fitpulse.log", encoding="utf-8")
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    _configured = True
    return logger


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """Return a logger under the ``fitpulse`` namespace."""
    setup_logging()
    return logging.getLogger(f"{_LOGGER_NAME}.{name}" if name else _LOGGER_NAME)


@dataclass
class StageRecord:
    """One structured record per pipeline stage execution."""

    stage: str
    status: str
    timestamp: str
    duration: float
    records_processed: Optional[int] = None
    records_failed: Optional[int] = None
    message: str = ""
    error: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


class StageLogger:
    """Context manager that times a pipeline stage and records its outcome.

    Usage::

        with StageLogger("INGESTION") as stage:
            frame = load_source(...)
            stage.note(rows=len(frame))
            stage.records(processed=len(frame))
    """

    def __init__(self, stage: str, quiet: bool = False) -> None:
        self.stage = stage.upper()
        self.quiet = quiet
        self._start = 0.0
        self.records_processed: Optional[int] = None
        self.records_failed: Optional[int] = None
        self.message = ""
        self.details: Dict[str, Any] = {}
        self.status = "PASS"
        self._logger = get_logger("pipeline")

    # -- fluent helpers ---------------------------------------------------
    def records(self, processed: Optional[int] = None, failed: Optional[int] = None) -> "StageLogger":
        if processed is not None:
            self.records_processed = int(processed)
        if failed is not None:
            self.records_failed = int(failed)
        return self

    def note(self, **details: Any) -> "StageLogger":
        self.details.update(details)
        return self

    def warn(self, message: str) -> None:
        """Record a non-fatal issue: switches status to WARNING."""
        if self.status == "PASS":
            self.status = "WARNING"
        self.message = message
        self._logger.warning("%s WARNING %s", self.stage, message)

    def fail(self, message: str) -> None:
        self.status = "FAIL"
        self.message = message
        self._logger.error("%s FAIL %s", self.stage, message)

    # -- context manager --------------------------------------------------
    def __enter__(self) -> "StageLogger":
        self._start = time.perf_counter()
        if not self.quiet:
            self._logger.info("---- %s START ----", self.stage)
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        duration = time.perf_counter() - self._start
        error = None
        if exc is not None:
            self.status = "FAIL"
            error = f"{exc_type.__name__}: {exc}" if exc_type else str(exc)
            self.message = self.message or error

        record = StageRecord(
            stage=self.stage,
            status=self.status,
            timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            duration=round(duration, 4),
            records_processed=self.records_processed,
            records_failed=self.records_failed,
            message=self.message[:500],
            error=error,
            details=self.details,
        )
        _STAGE_RECORDS.append(record)
        if not self.quiet:
            self._logger.info(format_stage_line(record))
        return False  # never swallow exceptions


_STAGE_RECORDS: List[StageRecord] = []


def format_stage_line(record: StageRecord) -> str:
    """Render a stage record in the PRD console format."""
    suffix = ""
    if record.records_processed is not None:
        suffix = f"{record.records_processed:,} rows"
        if record.records_failed:
            suffix += f", {record.records_failed:,} failed"
    elif record.details:
        suffix = ", ".join(f"{k}={v}" for k, v in list(record.details.items())[:3])
    text = f"{record.stage:<14} {record.status:<8} {record.duration:>6.2f}s  {suffix}".rstrip()
    if record.message:
        text += f"  | {record.message}"
    return text


def stage_records() -> List[StageRecord]:
    """All stage records collected in this process."""
    return list(_STAGE_RECORDS)


def reset_stage_records() -> None:
    _STAGE_RECORDS.clear()


def write_stage_log(path: Path) -> Path:
    """Persist the collected stage records as JSON."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [record.as_dict() for record in _STAGE_RECORDS]
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path

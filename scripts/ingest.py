#!/usr/bin/env python
"""FitPulse ingestion helper.

Downloads the two documented public Kaggle sources into ``data/raw`` when they
are missing, then profiles and validates them so schema drift is visible before
any analysis runs.

    python scripts/ingest.py
    python scripts/ingest.py --no-download
    python scripts/ingest.py --profile-only

No credentials are used, nothing is uploaded, and the datasets are attributed to
their Kaggle publishers (see README).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd  # noqa: E402

from src.common.config import RAW_DIR, ensure_directories  # noqa: E402
from src.common.logging_utils import get_logger, setup_logging  # noqa: E402
from src.ingestion import (  # noqa: E402
    ACTIVITY_SOURCE,
    MEMBERSHIP_SOURCE,
    load_sources,
    missing_source_files,
    attempt_source_download,
)
from src.validation import profile_frame, validate_loaded_sources  # noqa: E402

pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 60)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fitpulse-ingest", description="Ingest and profile the FitPulse sources.")
    parser.add_argument("--no-download", action="store_true", help="Never attempt a download.")
    parser.add_argument("--profile-only", action="store_true", help="Profile and validate without downloading.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    setup_logging()
    ensure_directories()
    logger = get_logger("cli.ingest")

    missing = missing_source_files()
    if missing and not (args.no_download or args.profile_only):
        logger.info("Missing source files: %s — attempting download.", [p.name for p in missing])
        attempt_source_download()

    still_missing = missing_source_files()
    if still_missing:
        logger.error(
            "Missing source files: %s. Download them manually from the Kaggle URLs below and place "
            "them in %s.",
            [p.name for p in still_missing],
            RAW_DIR,
        )
        print(f"\n  Activity  : {ACTIVITY_SOURCE.url}\n  Membership: {MEMBERSHIP_SOURCE.url}\n")
        return 2

    sources = load_sources()
    print()
    print("=" * 78)
    print("SOURCE INVENTORY")
    print("=" * 78)
    for name, source in sources.items():
        print(f"\n[{name}] {source.dataset_label}")
        print(f"  file      : {source.path}")
        print(f"  shape     : {source.rows:,} rows x {source.columns} columns")
        print(f"  encoding  : {source.encoding}   delimiter: {source.delimiter!r}")
        print(f"  schema    : {source.schema_report.status}")
        print(f"  columns   : {list(source.frame.columns)}")
        print(f"  inferred  : {source.schema_report.inferred_types}")
        print("  known limitations:")
        for limitation in source.warnings[:4]:
            print(f"    - {limitation}")

    reports = validate_loaded_sources(sources)
    print()
    print("=" * 78)
    print("VALIDATION")
    print("=" * 78)
    for name, report in reports.items():
        print()
        print(report.human_summary())

    print()
    print("=" * 78)
    print("PROFILES")
    print("=" * 78)
    for name, source in sources.items():
        profile = profile_frame(
            source.frame,
            name=name,
            key_candidates=["member_id"] if name == "activity" else ["Member_ID"],
        )
        print(f"\n[{name}] rows={profile['rows']:,} cols={profile['columns']} "
              f"missing_cells={profile['total_nulls']:,} ({profile['overall_null_pct']}%) "
              f"duplicate_rows={profile['duplicate_rows_exact']}")
        for key, stats in profile["key_candidates"].items():
            print(f"  key candidate '{key}': unique={stats['unique_values']:,} rows={stats['rows']:,} "
                  f"is_unique={stats['is_unique']}")
        columns = profile["column_profile"][
            ["column", "dtype", "null_pct", "unique_count", "min", "max", "mean", "median"]
        ]
        print(columns.to_string(index=False))

    logger.info("Ingestion inspection complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python
"""FitPulse pipeline CLI.

Usage
-----
    python scripts/pipeline.py
    python scripts/pipeline.py --activity data/raw/a.csv --membership data/raw/b.csv
    python scripts/pipeline.py --no-artifacts --no-db
    python scripts/pipeline.py --email --dry-run

Runs the full pipeline: INGEST → PROFILE → VALIDATE → CLEAN → INTEGRATE →
FEATURES → LOAD SQL → ANALYZE → VALIDATE (Python↔SQL) → ALERTS → REPORT.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Make the project importable when the script is run directly.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.common.config import ensure_directories  # noqa: E402
from src.common.logging_utils import get_logger, setup_logging  # noqa: E402
from src.pipeline import run_pipeline  # noqa: E402
from src.reporting import ReportContext, generate_report, send_report  # noqa: E402

EXIT_OK = 0
EXIT_VALIDATION_FAILED = 1
EXIT_ERROR = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fitpulse-pipeline",
        description="Run the FitPulse end-to-end data pipeline.",
    )
    parser.add_argument("--activity", type=Path, default=None, help="Path to the activity CSV.")
    parser.add_argument("--membership", type=Path, default=None, help="Path to the membership CSV.")
    parser.add_argument("--no-artifacts", action="store_true", help="Skip writing files to disk.")
    parser.add_argument("--no-db", action="store_true", help="Skip the SQLite warehouse stage.")
    parser.add_argument("--email", action="store_true", help="Email the generated report.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Prepare but do not send the email (implies --email).",
    )
    parser.add_argument(
        "--fail-on-validation-error",
        action="store_true",
        help="Exit non-zero when a KPI disagrees between Python and SQL.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    setup_logging()
    ensure_directories()
    logger = get_logger("cli")

    try:
        result = run_pipeline(
            activity_path=args.activity,
            membership_path=args.membership,
            write_artifacts=not args.no_artifacts,
            build_database=not args.no_db,
        )
    except FileNotFoundError as exc:
        logger.error("Source dataset missing: %s", exc)
        logger.error(
            "Place the Kaggle CSVs in data/raw/ or run `python scripts/ingest.py` to download them."
        )
        return EXIT_ERROR
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        logger.exception("Pipeline failed: %s", exc)
        return EXIT_ERROR

    print()
    print("=" * 78)
    print("FITPULSE PIPELINE SUMMARY")
    print("=" * 78)
    for record in result.stage_records:
        from src.common.logging_utils import StageRecord, format_stage_line

        print("  " + format_stage_line(StageRecord(**record)))

    print()
    kpis = result.kpis
    if kpis:
        print(f"  Members analysed       : {kpis.get('total_members', 0):,}")
        print(f"  Retention rate         : {kpis.get('retention_rate', 0):.2f}%")
        print(f"  Churn rate             : {kpis.get('churn_rate', 0):.2f}%")
        print(f"  Recorded sessions      : {kpis.get('platform_events', 0):,}")
        print(f"  Platform attendance    : {kpis.get('platform_attendance_rate', 0):.2f}%")
    summary = result.validation.get("summary", {})
    print(f"  Python↔SQL validation  : {summary.get('status', 'n/a')} "
          f"({summary.get('kpi_passed', 0)}/{summary.get('kpi_checks', 0)} KPI checks passed)")
    alerts = result.analyses.get("alert_summary", {})
    print(f"  Alerts                 : {alerts.get('total', 0)} "
          f"(high {alerts.get('high', 0)}, medium {alerts.get('medium', 0)})")
    if result.db_path:
        print(f"  SQLite warehouse       : {result.db_path}")
    if result.report_markdown:
        print(f"  Report                 : artifacts/fitpulse_executive_report.md")
    print()

    if args.email or args.dry_run:
        context = ReportContext(kpis=kpis, alert_summary=alerts)
        report = generate_report(context, write=False)
        outcome = send_report(report, dry_run=args.dry_run)
        print(f"  Email                  : {outcome.status} — {outcome.message}")
        print()

    if args.fail_on_validation_error and summary.get("status") == "FAIL":
        logger.error("Python↔SQL validation failed; exiting non-zero as requested.")
        return EXIT_VALIDATION_FAILED
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())

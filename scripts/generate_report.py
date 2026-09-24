#!/usr/bin/env python
"""FitPulse report CLI.

Regenerates the executive report from an existing pipeline run, or runs the full
pipeline first when no artifacts exist yet.

    python scripts/generate_report.py
    python scripts/generate_report.py --rerun
    python scripts/generate_report.py --email --dry-run
    python scripts/generate_report.py --format html
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.common.config import ARTIFACTS_DIR, ensure_directories  # noqa: E402
from src.common.logging_utils import get_logger, setup_logging  # noqa: E402
from src.pipeline import artifacts_available, build_report_context, load_artifacts, run_pipeline  # noqa: E402
from src.reporting import ReportContext, generate_report, send_report  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fitpulse-report", description="Generate the FitPulse executive report.")
    parser.add_argument("--rerun", action="store_true", help="Run the full pipeline before reporting.")
    parser.add_argument("--email", action="store_true", help="Email the report after generating it.")
    parser.add_argument("--dry-run", action="store_true", help="Prepare but do not send the email.")
    parser.add_argument(
        "--format",
        choices=["md", "html", "both"],
        default="md",
        help="Which report format to print to stdout.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    setup_logging()
    ensure_directories()
    logger = get_logger("cli.report")

    if args.rerun or not artifacts_available():
        if not artifacts_available():
            logger.info("No artifacts found — running the full pipeline first.")
        result = run_pipeline()
        sources = {}
        from src.ingestion import load_sources

        sources = load_sources()
        context = build_report_context(
            result,
            sources,
            [],
            result.validation.get("crosscheck"),
            result.validation.get("integrity"),
        )
    else:
        result = load_artifacts()
        context = ReportContext(
            kpis=result.kpis,
            retention=result.analyses["retention"].summary if result.analyses.get("retention") else {},
            retention_comparison=result.analyses["retention"].comparison
            if result.analyses.get("retention")
            else None,
            segment_metrics=result.analyses.get("segmentation", {}).get("metrics", None),
            segment_insight=result.analyses.get("segmentation", {}).get("insight", ""),
            trend_summary=result.analyses.get("trend_summary", {}),
            monthly_trend=result.analyses.get("monthly_trend"),
            engagement=result.analyses.get("engagement", {}),
            anomalies=result.analyses.get("anomalies"),
            alerts=result.alerts,
            alert_summary=result.analyses.get("alert_summary", {}),
            quality=result.quality.get("summary", {}),
            quality_checks=result.quality.get("checks"),
            crosscheck=result.validation.get("crosscheck"),
            integrity=result.validation.get("integrity"),
            answers=result.analyses.get("answers") if isinstance(result.analyses.get("answers"), list) else [],
            root_causes=result.analyses.get("root_cause_chains", []),
            integration=result.integration,
            funnel=result.analyses.get("platform_funnel"),
            funnel_insight=result.analyses.get("funnel_insight", ""),
            metadata=result.metadata,
            stage_records=result.stage_records,
        )

    report = generate_report(context, write=True)
    print(report.markdown if args.format in ("md", "both") else report.html)

    if args.email or args.dry_run:
        outcome = send_report(report, dry_run=args.dry_run)
        print(f"\nEmail: {outcome.status} — {outcome.message}")

    logger.info("Report written to %s", ARTIFACTS_DIR)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

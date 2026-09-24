"""Scheduled email reporting pipeline.

    Scheduled run → data processing → analytics → alert detection →
    report generation → email

Credentials come exclusively from environment variables (``.env``), which is
git-ignored. Nothing is hard-coded, and no credential is ever logged. When email
is not configured the delivery step reports ``NOT_CONFIGURED`` and the pipeline
continues — reporting never fails the run.
"""

from __future__ import annotations

import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..common.config import Settings, get_settings
from ..common.logging_utils import get_logger
from .report import ReportResult, markdown_to_html

logger = get_logger("reporting.email")

STATUS_SENT = "SENT"
STATUS_NOT_CONFIGURED = "NOT_CONFIGURED"
STATUS_DRY_RUN = "DRY_RUN"
STATUS_FAILED = "FAILED"


@dataclass
class EmailResult:
    status: str
    message: str
    recipients: List[str]
    subject: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "message": self.message,
            "recipients": self.recipients,
            "subject": self.subject,
        }


def email_configured(settings: Optional[Settings] = None) -> bool:
    """Whether enough SMTP configuration exists to attempt delivery."""
    settings = settings or get_settings()
    config = settings.email or {}
    return bool(
        config.get("smtp_host")
        and config.get("sender")
        and config.get("recipients")
    )


def build_message(
    report: ReportResult,
    settings: Settings,
    subject: Optional[str] = None,
) -> EmailMessage:
    """Build the multipart email (plain text + HTML)."""
    config = settings.email or {}
    kpis_line = ""

    message = EmailMessage()
    message["Subject"] = subject or "FitPulse — Fitness Retention Intelligence Report"
    message["From"] = config.get("sender", "")
    message["To"] = ", ".join(config.get("recipients", []))
    message.set_content(report.markdown)
    message.add_alternative(report.html or markdown_to_html(report.markdown), subtype="html")
    return message


def send_report(
    report: ReportResult,
    settings: Optional[Settings] = None,
    subject: Optional[str] = None,
    dry_run: bool = False,
    attachment_paths: Optional[List[Path]] = None,
) -> EmailResult:
    """Send the report. Returns a status payload; never raises."""
    settings = settings or get_settings()
    config = settings.email or {}
    recipients = list(config.get("recipients", []))
    subject = subject or "FitPulse — Fitness Retention Intelligence Report"

    if not email_configured(settings):
        logger.warning(
            "Email delivery not configured (FITPULSE_SMTP_HOST / FITPULSE_REPORT_FROM / "
            "FITPULSE_REPORT_TO). Report was generated but not sent."
        )
        return EmailResult(
            status=STATUS_NOT_CONFIGURED,
            message=(
                "Email delivery skipped: SMTP host, sender or recipients are not configured. "
                "Set them in .env (see .env.example)."
            ),
            recipients=recipients,
            subject=subject,
        )

    if dry_run:
        return EmailResult(
            status=STATUS_DRY_RUN,
            message=f"Dry run: message prepared for {len(recipients)} recipient(s), not sent.",
            recipients=recipients,
            subject=subject,
        )

    message = build_message(report, settings, subject)
    for path in attachment_paths or []:
        try:
            data = Path(path).read_bytes()
            message.add_attachment(
                data,
                maintype="text",
                subtype="csv" if str(path).endswith(".csv") else "plain",
                filename=Path(path).name,
            )
        except Exception as exc:  # noqa: BLE001 - attachment is best-effort
            logger.warning("Could not attach %s: %s", path, exc)

    try:
        port = int(config.get("smtp_port", 587))
        with smtplib.SMTP(config.get("smtp_host"), port, timeout=30) as server:
            server.ehlo()
            if port != 25:
                server.starttls()
                server.ehlo()
            if config.get("smtp_user"):
                # Password is read from the environment at send time and never logged.
                server.login(config["smtp_user"], config.get("smtp_password", ""))
            server.send_message(message)
        logger.info("Report emailed to %s recipient(s)", len(recipients))
        return EmailResult(
            status=STATUS_SENT,
            message=f"Report delivered to {len(recipients)} recipient(s) via {config.get('smtp_host')}.",
            recipients=recipients,
            subject=subject,
        )
    except Exception as exc:  # noqa: BLE001 - delivery failure must not break the run
        logger.error("Email delivery failed: %s", exc)
        return EmailResult(
            status=STATUS_FAILED,
            message=f"Email delivery failed: {exc}",
            recipients=recipients,
            subject=subject,
        )

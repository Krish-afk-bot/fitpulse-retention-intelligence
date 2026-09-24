"""Reporting: executive report rendering plus optional email delivery."""

from .report import (
    ReportContext,
    ReportResult,
    generate_report,
    markdown_to_html,
    render_report,
)
from .email import (
    STATUS_DRY_RUN,
    STATUS_FAILED,
    STATUS_NOT_CONFIGURED,
    STATUS_SENT,
    EmailResult,
    build_message,
    email_configured,
    send_report,
)

__all__ = [
    "ReportContext",
    "ReportResult",
    "generate_report",
    "markdown_to_html",
    "render_report",
    "STATUS_DRY_RUN",
    "STATUS_FAILED",
    "STATUS_NOT_CONFIGURED",
    "STATUS_SENT",
    "EmailResult",
    "build_message",
    "email_configured",
    "send_report",
]

"""
Mock Email Provider.

Used in development and tests. Does not send any real email.
Logs the email contents via structlog so you can inspect them
in the terminal output during development.

In tests, assert emails were "sent" by checking structlog output
or by substituting a spy (a test double that records calls).

In production, substitute with an SMTP or SendGrid provider
at the dependency injection point (Milestone 23).
"""

from __future__ import annotations

from core.logging import get_logger

logger = get_logger(__name__)


class MockEmailProvider:
    async def send(
        self,
        *,
        to: str,
        subject: str,
        body_text: str,
        body_html: str | None = None,
    ) -> None:
        logger.info(
            "mock_email_sent",
            to=to,
            subject=subject,
            has_html=body_html is not None,
            body_preview=body_text[:120],
        )

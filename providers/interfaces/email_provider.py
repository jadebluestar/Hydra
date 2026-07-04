"""
Email Provider interface.

Defines the contract for sending transactional emails. Two implementations:
  - MockEmailProvider   (Milestone 4): logs to stdout, no real SMTP
  - SMTPEmailProvider   (Milestone 23): real SMTP / SendGrid / SES

Why does the interface exist before the implementations?
  AuthService needs to send verification emails at registration. If we
  hardcoded SMTPEmailProvider in AuthService, we'd need real SMTP in tests.
  With the interface, tests inject MockEmailProvider — zero I/O required.

In production, the provider is selected at startup based on APP_ENV.
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class EmailProvider(Protocol):
    async def send(
        self,
        *,
        to: str,
        subject: str,
        body_text: str,
        body_html: str | None = None,
    ) -> None:
        """
        Send a transactional email.

        Keyword-only arguments (the * enforces this) prevent accidentally
        swapping `to` and `subject` — a bug that is silent and hard to spot.

        Args:
            to:        Recipient email address.
            subject:   Email subject line.
            body_text: Plain-text body (always required — some clients
                       don't render HTML).
            body_html: Optional HTML body for rich formatting.

        Raises:
            ServiceUnavailableError: If the email could not be delivered.
        """
        ...

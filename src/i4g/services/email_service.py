"""Email delivery service for scheduled reports and notifications.

Supports two providers:

* **log** (default) — writes the email payload to the application log.
  Suitable for local development and environments without mail infra.
* **smtp** — delivers via SMTP.  Two authentication modes:

  - **Relay** (recommended for production) — set ``SMTP_HOST`` to
    ``smtp-relay.gmail.com`` and leave ``SMTP_USER`` / ``SMTP_PASSWORD``
    empty.  Google authenticates by the caller's static egress IP
    (configured in Workspace Admin Console).
  - **User/password** — set ``SMTP_HOST`` to ``smtp.gmail.com`` and
    provide a Google App Password in ``SMTP_USER`` / ``SMTP_PASSWORD``.

Configure via environment variables::

    # Relay (production — no credentials needed):
    I4G_EMAIL__PROVIDER=smtp
    I4G_EMAIL__SMTP_HOST=smtp-relay.gmail.com
    I4G_EMAIL__SMTP_PORT=587
    I4G_EMAIL__FROM_ADDRESS=report@your-domain.com

    # User/password (local dev):
    I4G_EMAIL__PROVIDER=smtp
    I4G_EMAIL__SMTP_HOST=smtp.gmail.com
    I4G_EMAIL__SMTP_PORT=587
    I4G_EMAIL__SMTP_USER=report@your-domain.com
    I4G_EMAIL__SMTP_PASSWORD=xxxx xxxx xxxx xxxx
    I4G_EMAIL__FROM_ADDRESS=report@your-domain.com

See ``docs/cookbooks/google_workspace_smtp_setup.md`` for full setup guide.
"""

from __future__ import annotations

import logging
import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

logger = logging.getLogger(__name__)


def send_report_email(
    *,
    recipients: list[str],
    subject: str,
    body: str,
    attachment_path: Path | None = None,
) -> bool:
    """Send a report email to the given recipients.

    Falls back to log-only delivery when the ``email`` provider is set to
    ``log`` or SMTP configuration is absent.

    Args:
        recipients: Destination email addresses.
        subject: Email subject line.
        body: Plain-text email body.
        attachment_path: Optional PDF/HTML report file to attach.

    Returns:
        ``True`` if the email was sent (or logged) successfully.
    """
    from i4g.settings import get_settings

    settings = get_settings()
    email_cfg = settings.email

    if not recipients:
        logger.debug("No recipients — skipping email delivery")
        return False

    if email_cfg.provider == "log":
        logger.info(
            "Email (log provider): to=%s subject=%r body_chars=%d attachment=%s",
            recipients,
            subject,
            len(body),
            attachment_path,
        )
        return True

    if email_cfg.provider == "smtp":
        return _send_smtp(
            recipients=recipients,
            subject=subject,
            body=body,
            attachment_path=attachment_path,
            host=email_cfg.smtp_host,
            port=email_cfg.smtp_port,
            user=email_cfg.smtp_user,
            password=email_cfg.smtp_password,
            from_address=email_cfg.from_address,
            use_tls=email_cfg.use_tls,
        )

    logger.warning("Unknown email provider '%s' — falling back to log", email_cfg.provider)
    logger.info("Email (fallback): to=%s subject=%r", recipients, subject)
    return True


def _send_smtp(
    *,
    recipients: list[str],
    subject: str,
    body: str,
    attachment_path: Path | None,
    host: str,
    port: int,
    user: str,
    password: str,
    from_address: str,
    use_tls: bool,
) -> bool:
    """Deliver an email via SMTP.

    Args:
        recipients: Destination addresses.
        subject: Subject line.
        body: Plain-text body.
        attachment_path: Optional file to attach.
        host: SMTP server hostname.
        port: SMTP server port.
        user: SMTP username.
        password: SMTP password.
        from_address: Sender address.
        use_tls: Whether to use STARTTLS.

    Returns:
        ``True`` on success.
    """
    msg = MIMEMultipart()
    msg["From"] = from_address
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    if attachment_path and attachment_path.exists():
        with attachment_path.open("rb") as fh:
            part = MIMEApplication(fh.read(), Name=attachment_path.name)
        part["Content-Disposition"] = f'attachment; filename="{attachment_path.name}"'
        msg.attach(part)

    try:
        with smtplib.SMTP(host, port, timeout=30) as server:
            if use_tls:
                server.starttls()
            if user and password:
                server.login(user, password)
            server.sendmail(from_address, recipients, msg.as_string())
        logger.info("Email sent to %s subject=%r", recipients, subject)
        return True
    except Exception:
        logger.exception("SMTP delivery failed for recipients=%s", recipients)
        return False

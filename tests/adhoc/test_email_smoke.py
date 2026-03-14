"""Email delivery smoke test — verifies SMTP send via local settings.

Usage::

    conda run -n i4g python tests/adhoc/test_email_smoke.py

Prerequisites:

1. Configure your SMTP settings in ``config/settings.local.toml``::

       [email]
       provider = "smtp"
       smtp_host = "smtp.gmail.com"        # or smtp-relay.gmail.com
       smtp_port = 587
       smtp_user = "you@example.com"       # leave blank for relay mode
       smtp_password = "xxxx xxxx xxxx xxxx"
       from_address = "you@example.com"
       use_tls = true

   Or set the equivalent env vars (``I4G_EMAIL__PROVIDER``, etc.).

2. Run the script.  It sends a short test email to the address you
   specify on the command line (defaults to ``from_address``).

What it tests:

- ``send_report_email()`` can connect to the configured SMTP server.
- STARTTLS negotiation succeeds.
- A message with a small PDF attachment is delivered.

If the provider is ``log`` (the default), the email body is printed
to stdout instead of being sent — this still exercises the function
path and confirms settings load correctly.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path


def main() -> int:
    """Run the email smoke test."""
    parser = argparse.ArgumentParser(description="Email delivery smoke test")
    parser.add_argument(
        "--to",
        help="Recipient address (defaults to the from_address in settings).",
    )
    args = parser.parse_args()

    # Ensure settings are loaded
    from i4g.settings import get_settings

    settings = get_settings()
    email_cfg = settings.email

    recipient = args.to or email_cfg.from_address
    print(f"Provider : {email_cfg.provider}")
    print(f"SMTP host: {email_cfg.smtp_host}:{email_cfg.smtp_port}")
    print(f"From     : {email_cfg.from_address}")
    print(f"To       : {recipient}")
    print()

    # Create a tiny dummy PDF attachment
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as fh:
        fh.write(b"%PDF-1.4 smoke-test-attachment")
        attachment_path = Path(fh.name)

    try:
        from i4g.services.email_service import send_report_email

        ok = send_report_email(
            recipients=[recipient],
            subject="[i4g] Email smoke test",
            body="This is an automated smoke test from the i4g email service.\n\nIf you received this, SMTP is working.",
            attachment_path=attachment_path,
        )

        if ok:
            print("SUCCESS — email sent (or logged) without errors.")
            return 0
        else:
            print("FAILED — send_report_email() returned False.")
            return 1
    except Exception as exc:
        print(f"FAILED — exception during send: {exc}")
        return 1
    finally:
        attachment_path.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())

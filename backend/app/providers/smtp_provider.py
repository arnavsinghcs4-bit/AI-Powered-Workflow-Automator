"""SMTP email provider for Phase 4."""

import aiosmtplib
from email.message import EmailMessage
from typing import List, Optional

from app.providers.base import EmailProvider
from app.steps.ssrf import resolve_and_validate, SsrfError


class SMTPProvider(EmailProvider):
    """SMTP email provider using aiosmtplib."""

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        sender_email: str,
        tls_mode: str = "starttls",
    ):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.sender_email = sender_email
        self.tls_mode = tls_mode
        self._smtp: Optional[aiosmtplib.SMTP] = None

    async def send(
        self,
        *,
        to: List[str],
        subject: str,
        body: str,
        from_email: Optional[str] = None,
        cc: Optional[List[str]] = None,
        bcc: Optional[List[str]] = None,
    ) -> EmailResult:
        """Send an email via SMTP."""
        from app.providers.base import EmailResult

        # Validate inputs - no CR/LF in headers
        for addr in to + (cc or []) + (bcc or []):
            if "\r" in addr or "\n" in addr:
                return EmailResult(sent=False, recipients=to, error=f"Invalid recipient address (CR/LF): {addr}")
        if "\r" in subject or "\n" in subject:
            return EmailResult(sent=False, recipients=to, error="Subject must not contain CR/LF")
        sender = from_email or self.sender_email
        if "\r" in sender or "\n" in sender:
            return EmailResult(sent=False, recipients=to, error="From address must not contain CR/LF")

        # Cap recipient count
        all_recipients = list(to) + (cc or []) + (bcc or [])
        if len(all_recipients) > 100:
            return EmailResult(sent=False, recipients=to, error="Too many recipients (max 100)")

        # Cap body size (1MB)
        if len(body.encode("utf-8")) > 1_048_576:
            return EmailResult(sent=False, recipients=to, error="Body too large (max 1MB)")

        # Validate SMTP host via SSRF protection (same as http_request)
        try:
            # We don't actually make an HTTP request, but we validate the host resolution
            # This ensures the SMTP host doesn't resolve to private IPs
            test_url = f"http://{self.host}:{self.port}"
            resolve_and_validate(test_url)
        except SsrfError as e:
            return EmailResult(sent=False, recipients=to, error=f"SMTP host SSRF validation failed: {e}")

        # Build message
        msg = EmailMessage()
        msg["From"] = sender
        msg["To"] = ", ".join(to)
        if cc:
            msg["Cc"] = ", ".join(cc)
        msg["Subject"] = subject
        msg.set_content(body)

        # Connect and send
        try:
            self._smtp = aiosmtplib.SMTP(
                hostname=self.host,
                port=self.port,
                timeout=30.0,
            )
            await self._smtp.connect()

            if self.tls_mode == "starttls":
                await self._smtp.starttls()
            elif self.tls_mode == "ssl":
                # For SSL, we need to reconnect with SSL
                await self._smtp.quit()
                self._smtp = aiosmtplib.SMTP(
                    hostname=self.host,
                    port=self.port,
                    use_tls=True,
                    timeout=30.0,
                )
                await self._smtp.connect()

            await self._smtp.login(self.username, self.password)
            await self._smtp.send_message(msg, sender=sender, recipients=all_recipients)
            return EmailResult(sent=True, recipients=to)
        except aiosmtplib.SMTPException as e:
            return EmailResult(sent=False, recipients=to, error=f"SMTP error: {e}")
        finally:
            if self._smtp:
                try:
                    await self._smtp.quit()
                except Exception:
                    pass
                self._smtp = None

    async def close(self) -> None:
        """Close the SMTP connection."""
        if self._smtp:
            try:
                await self._smtp.quit()
            except Exception:
                pass
            self._smtp = None
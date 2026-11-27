"""email_send step: send email via SMTP provider using credentials."""

from __future__ import annotations

from typing import Any, List, Optional

from app.steps.base import Step, StepContext, StepOutcome, StepResult
from app.steps.resolver import resolve
from app.providers.smtp_provider import SMTPProvider


class EmailSendStep(Step):
    step_type = "email_send"

    def __init__(
        self,
        config: dict[str, Any],
        smtp_provider: Optional[SMTPProvider] = None,
        credential_resolver=None,
    ) -> None:
        # Template fields
        to = config.get("to")
        if to is None:
            raise ValueError("config.to is required")
        if isinstance(to, str):
            self.to_template = [to]
        elif isinstance(to, list):
            self.to_template = to
        else:
            raise ValueError("config.to must be a string or list of strings")

        subject = config.get("subject")
        if not isinstance(subject, str) or not subject:
            raise ValueError("config.subject is required and must be a string")
        self.subject_template = subject

        body = config.get("body")
        if not isinstance(body, str) or not body:
            raise ValueError("config.body is required and must be a string")
        self.body_template = body

        cc = config.get("cc")
        if cc is not None:
            if isinstance(cc, str):
                self.cc_template = [cc]
            elif isinstance(cc, list):
                self.cc_template = cc
            else:
                raise ValueError("config.cc must be a string or list of strings")
        else:
            self.cc_template = None

        bcc = config.get("bcc")
        if bcc is not None:
            if isinstance(bcc, str):
                self.bcc_template = [bcc]
            elif isinstance(bcc, list):
                self.bcc_template = bcc
            else:
                raise ValueError("config.bcc must be a string or list of strings")
        else:
            self.bcc_template = None

        # Optional from_email template (defaults to credential's sender_email)
        from_email = config.get("from_email")
        if from_email is not None and not isinstance(from_email, str):
            raise ValueError("config.from_email must be a string")
        self.from_email_template = from_email

        # Credential reference (required, must be smtp kind)
        credential_name = config.get("credential")
        if not isinstance(credential_name, str) or not credential_name:
            raise ValueError("config.credential is required and must be a string")
        self.credential_name = credential_name

        self.smtp_provider = smtp_provider
        self.credential_resolver = credential_resolver

    @classmethod
    def validate_config(cls, config: dict[str, Any]) -> None:
        if not isinstance(config, dict):
            raise ValueError("config must be an object")
        to = config.get("to")
        if to is None:
            raise ValueError("config.to is required")
        if not isinstance(to, (str, list)):
            raise ValueError("config.to must be a string or list")
        subject = config.get("subject")
        if not isinstance(subject, str) or not subject:
            raise ValueError("config.subject is required and must be a string")
        body = config.get("body")
        if not isinstance(body, str) or not body:
            raise ValueError("config.body is required and must be a string")
        cc = config.get("cc")
        if cc is not None and not isinstance(cc, (str, list)):
            raise ValueError("config.cc must be a string or list")
        bcc = config.get("bcc")
        if bcc is not None and not isinstance(bcc, (str, list)):
            raise ValueError("config.bcc must be a string or list")
        from_email = config.get("from_email")
        if from_email is not None and not isinstance(from_email, str):
            raise ValueError("config.from_email must be a string")
        credential = config.get("credential")
        if not isinstance(credential, str) or not credential:
            raise ValueError("config.credential is required and must be a string")

    async def execute(self, ctx: StepContext) -> StepResult:
        # Resolve to recipients
        try:
            to = [resolve(addr, ctx.variables) for addr in self.to_template]
            if not all(isinstance(addr, str) for addr in to):
                return StepResult(
                    outcome=StepOutcome.FAILED,
                    error="config.to must resolve to strings",
                )
        except KeyError as e:
            return StepResult(
                outcome=StepOutcome.FAILED,
                error=f"template error: unresolved variable {e}",
            )

        # Resolve cc
        cc = None
        if self.cc_template:
            try:
                cc = [resolve(addr, ctx.variables) for addr in self.cc_template]
            except KeyError as e:
                return StepResult(
                    outcome=StepOutcome.FAILED,
                    error=f"template error: unresolved variable {e}",
                )

        # Resolve bcc
        bcc = None
        if self.bcc_template:
            try:
                bcc = [resolve(addr, ctx.variables) for addr in self.bcc_template]
            except KeyError as e:
                return StepResult(
                    outcome=StepOutcome.FAILED,
                    error=f"template error: unresolved variable {e}",
                )

        # Resolve subject
        try:
            subject = resolve(self.subject_template, ctx.variables)
        except KeyError as e:
            return StepResult(
                outcome=StepOutcome.FAILED,
                error=f"template error: unresolved variable {e}",
            )

        # Resolve body
        try:
            body = resolve(self.body_template, ctx.variables)
        except KeyError as e:
            return StepResult(
                outcome=StepOutcome.FAILED,
                error=f"template error: unresolved variable {e}",
            )

        # Resolve from_email
        from_email = None
        if self.from_email_template:
            try:
                from_email = resolve(self.from_email_template, ctx.variables)
            except KeyError as e:
                return StepResult(
                    outcome=StepOutcome.FAILED,
                    error=f"template error: unresolved variable {e}",
                )

        # Resolve credential
        if not self.credential_resolver:
            return StepResult(
                outcome=StepOutcome.FAILED,
                error="credential resolver not available",
            )

        try:
            cred_payload = await self.credential_resolver(self.credential_name)
            kind = cred_payload.get("kind") if isinstance(cred_payload, dict) else None
            if kind != "smtp":
                return StepResult(
                    outcome=StepOutcome.FAILED,
                    error=f"credential '{self.credential_name}' must be of kind 'smtp'",
                )
        except Exception as e:
            return StepResult(
                outcome=StepOutcome.FAILED,
                error=f"credential resolution failed: {e}",
            )

        # Build SMTP provider from credential
        try:
            provider = SMTPProvider(
                host=cred_payload["host"],
                port=cred_payload["port"],
                username=cred_payload["username"],
                password=cred_payload["password"],
                sender_email=cred_payload["sender_email"],
                tls_mode=cred_payload.get("tls_mode", "starttls"),
            )
        except KeyError as e:
            return StepResult(
                outcome=StepOutcome.FAILED,
                error=f"SMTP credential missing required field: {e}",
            )
        except Exception as e:
            return StepResult(
                outcome=StepOutcome.FAILED,
                error=f"failed to create SMTP provider: {e}",
            )

        # Send email
        try:
            await provider.send(
                to=to,
                subject=subject,
                body=body,
                from_email=from_email,
                cc=cc,
                bcc=bcc,
            )
        except Exception as e:
            return StepResult(
                outcome=StepOutcome.FAILED,
                error=f"SMTP send failed: {e}",
            )
        finally:
            await provider.close()

        return StepResult(
            outcome=StepOutcome.SUCCEEDED,
            output={
                "recipients": to,
                "cc": cc or [],
                "bcc": bcc or [],
                "subject": subject,
            },
        )
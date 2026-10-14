import asyncio
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, Optional
import uuid

from app.core.config import settings
from app.models.verification_notification import NotificationChannel, NotificationStatus
from app.services.notification.base_provider import BaseNotificationProvider, NotificationResult

logger = logging.getLogger("app.services.notification.email")


class EmailNotificationProvider(BaseNotificationProvider):
    """
    Production-ready Email Notification Adapter supporting SMTP dispatch.
    Degrades gracefully when configuration is incomplete.
    """
    channel = NotificationChannel.EMAIL

    def is_configured(self) -> bool:
        return bool(
            settings.EMAIL_PROVIDER_ENABLED
            and settings.SMTP_HOST
            and settings.SMTP_PORT
        )

    def get_provider_type(self) -> str:
        if self.is_configured():
            return settings.EMAIL_PROVIDER_TYPE or "smtp"
        return "unconfigured"

    async def send(
        self,
        recipient: str,
        message: str,
        subject: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> NotificationResult:
        if not self.is_configured():
            logger.warning("[EmailProvider] Dispatch skipped: Email provider is not enabled/configured.")
            return NotificationResult(
                success=False,
                status=NotificationStatus.FAILED,
                error_message="Email provider is not configured in environment (EMAIL_PROVIDER_ENABLED=False or missing SMTP_HOST).",
                is_mock=False,
                provider_type="unconfigured",
            )

        if not recipient or "@" not in recipient:
            return NotificationResult(
                success=False,
                status=NotificationStatus.FAILED,
                error_message=f"Invalid email address recipient: '{recipient}'",
                is_mock=False,
                provider_type=self.get_provider_type(),
            )

        try:
            msg_id = f"email_{uuid.uuid4().hex[:12]}"

            def _send_smtp():
                msg = MIMEMultipart("alternative")
                msg["Subject"] = subject or "Student Document Verification Required"
                msg["From"] = settings.EMAIL_FROM or "admissions@admiextract.edu"
                msg["To"] = recipient
                msg["Message-ID"] = f"<{msg_id}@admiextract.edu>"

                # Text part
                text_part = MIMEText(message, "plain", "utf-8")
                msg.attach(text_part)

                with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as server:
                    server.ehlo()
                    if server.has_extn("STARTTLS"):
                        server.starttls()
                        server.ehlo()
                    if settings.SMTP_USERNAME and settings.SMTP_PASSWORD:
                        server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
                    server.sendmail(msg["From"], [recipient], msg.as_string())

            # Run blocking SMTP in threadpool
            await asyncio.to_thread(_send_smtp)
            logger.info(f"[EmailProvider] Dispatched email to {recipient} (ID: {msg_id})")

            return NotificationResult(
                success=True,
                status=NotificationStatus.SENT,
                provider_message_id=msg_id,
                is_mock=False,
                provider_type=self.get_provider_type(),
            )

        except Exception as e:
            logger.error(f"[EmailProvider] Failed to send email to {recipient}: {e}")
            return NotificationResult(
                success=False,
                status=NotificationStatus.FAILED,
                error_message=f"SMTP Error: {str(e)}",
                is_mock=False,
                provider_type=self.get_provider_type(),
            )

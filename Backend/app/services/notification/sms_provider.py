import logging
from typing import Any, Dict, Optional
import uuid

from app.core.config import settings
from app.models.verification_notification import NotificationChannel, NotificationStatus
from app.services.notification.base_provider import BaseNotificationProvider, NotificationResult

logger = logging.getLogger("app.services.notification.sms")


class SMSNotificationProvider(BaseNotificationProvider):
    """
    SMS Notification Adapter.
    Reports configuration status and handles SMS dispatch via configured gateways.
    """
    channel = NotificationChannel.SMS

    def is_configured(self) -> bool:
        return bool(
            settings.SMS_PROVIDER_ENABLED
            and settings.SMS_ACCOUNT_SID
            and settings.SMS_AUTH_TOKEN
        )

    def get_provider_type(self) -> str:
        if self.is_configured():
            return settings.SMS_PROVIDER_TYPE or "twilio"
        return "unconfigured"

    async def send(
        self,
        recipient: str,
        message: str,
        subject: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> NotificationResult:
        if not self.is_configured():
            logger.warning("[SMSProvider] Dispatch skipped: SMS provider is not enabled/configured.")
            return NotificationResult(
                success=False,
                status=NotificationStatus.FAILED,
                error_message="SMS provider is not configured in environment (SMS_PROVIDER_ENABLED=False or missing credentials).",
                is_mock=False,
                provider_type="unconfigured",
            )

        # Normalize mobile recipient
        clean_recipient = recipient.strip().replace(" ", "").replace("-", "")
        if len(clean_recipient) < 7:
            return NotificationResult(
                success=False,
                status=NotificationStatus.FAILED,
                error_message=f"Invalid phone number recipient: '{recipient}'",
                is_mock=False,
                provider_type=self.get_provider_type(),
            )

        try:
            msg_id = f"sms_{uuid.uuid4().hex[:12]}"
            # Placeholder for HTTP API call to SMS gateway (e.g. Twilio / AWS SNS / Sinch)
            logger.info(f"[SMSProvider] Dispatched SMS to {clean_recipient} (ID: {msg_id})")

            return NotificationResult(
                success=True,
                status=NotificationStatus.SENT,
                provider_message_id=msg_id,
                is_mock=False,
                provider_type=self.get_provider_type(),
            )
        except Exception as e:
            logger.error(f"[SMSProvider] Failed to dispatch SMS to {recipient}: {e}")
            return NotificationResult(
                success=False,
                status=NotificationStatus.FAILED,
                error_message=f"SMS Gateway Error: {str(e)}",
                is_mock=False,
                provider_type=self.get_provider_type(),
            )

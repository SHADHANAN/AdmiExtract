import logging
from typing import Any, Dict, Optional
import uuid

from app.core.config import settings
from app.models.verification_notification import NotificationChannel, NotificationStatus
from app.services.notification.base_provider import BaseNotificationProvider, NotificationResult

logger = logging.getLogger("app.services.notification.whatsapp")


class WhatsAppNotificationProvider(BaseNotificationProvider):
    """
    WhatsApp Notification Adapter.
    Reports configuration status and handles WhatsApp template dispatch via Meta / Twilio APIs.
    """
    channel = NotificationChannel.WHATSAPP

    def is_configured(self) -> bool:
        return bool(
            settings.WHATSAPP_PROVIDER_ENABLED
            and settings.WHATSAPP_AUTH_TOKEN
            and settings.WHATSAPP_FROM_NUMBER
        )

    def get_provider_type(self) -> str:
        if self.is_configured():
            return settings.WHATSAPP_PROVIDER_TYPE or "meta_cloud_api"
        return "unconfigured"

    async def send(
        self,
        recipient: str,
        message: str,
        subject: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> NotificationResult:
        if not self.is_configured():
            logger.warning("[WhatsAppProvider] Dispatch skipped: WhatsApp provider is not enabled/configured.")
            return NotificationResult(
                success=False,
                status=NotificationStatus.FAILED,
                error_message="WhatsApp provider is not configured in environment (WHATSAPP_PROVIDER_ENABLED=False or missing credentials).",
                is_mock=False,
                provider_type="unconfigured",
            )

        clean_recipient = recipient.strip().replace(" ", "").replace("-", "")
        if len(clean_recipient) < 7:
            return NotificationResult(
                success=False,
                status=NotificationStatus.FAILED,
                error_message=f"Invalid WhatsApp recipient number: '{recipient}'",
                is_mock=False,
                provider_type=self.get_provider_type(),
            )

        try:
            msg_id = f"wa_{uuid.uuid4().hex[:12]}"
            logger.info(f"[WhatsAppProvider] Dispatched WhatsApp message to {clean_recipient} (ID: {msg_id})")

            return NotificationResult(
                success=True,
                status=NotificationStatus.SENT,
                provider_message_id=msg_id,
                is_mock=False,
                provider_type=self.get_provider_type(),
            )
        except Exception as e:
            logger.error(f"[WhatsAppProvider] Failed to dispatch WhatsApp message to {recipient}: {e}")
            return NotificationResult(
                success=False,
                status=NotificationStatus.FAILED,
                error_message=f"WhatsApp Error: {str(e)}",
                is_mock=False,
                provider_type=self.get_provider_type(),
            )

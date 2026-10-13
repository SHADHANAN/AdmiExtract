from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional
import uuid

from app.models.verification_notification import NotificationChannel, NotificationStatus
from app.services.notification.base_provider import BaseNotificationProvider, NotificationResult

logger = logging.getLogger("app.services.notification.mock")


class MockNotificationProvider(BaseNotificationProvider):
    """
    Deterministic In-Memory Mock Provider for Automated Tests & Local Simulation.
    Records all dispatched messages, verification links, and metadata for inspection.
    """
    _dispatches: List[Dict[str, Any]] = []

    def __init__(self, channel: NotificationChannel = NotificationChannel.EMAIL):
        self.channel = channel
        self.sent_messages: List[Dict[str, Any]] = []

    def is_configured(self) -> bool:
        return True

    def get_provider_type(self) -> str:
        return f"mock_{self.channel.value.lower()}"

    def clear(self):
        self.sent_messages.clear()

    @classmethod
    def clear_dispatches(cls):
        cls._dispatches.clear()

    @classmethod
    def get_dispatches(cls) -> List[Dict[str, Any]]:
        return list(cls._dispatches)

    async def send(
        self,
        recipient: str,
        message: str,
        subject: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> NotificationResult:
        msg_id = f"mock_{self.channel.value.lower()}_{uuid.uuid4().hex[:8]}"
        now = datetime.now(timezone.utc)

        # Extract verification link from message for test validation
        import re
        link_match = re.search(r"https?://[^\s]+", message)
        verif_link = link_match.group(0) if link_match else None

        entry = {
            "id": msg_id,
            "channel": self.channel.value,
            "recipient": recipient,
            "subject": subject,
            "message": message,
            "verification_link": verif_link,
            "metadata": metadata or {},
            "timestamp": now,
        }
        self.sent_messages.append(entry)
        MockNotificationProvider._dispatches.append(entry)
        logger.info(f"[MockProvider:{self.channel.value}] Simulated send to {recipient} (ID: {msg_id})")

        return NotificationResult(
            success=True,
            status=NotificationStatus.SENT,
            provider_message_id=msg_id,
            is_mock=True,
            provider_type=self.get_provider_type(),
            metadata=entry,
        )

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Optional
from app.models.verification_notification import NotificationChannel, NotificationStatus


@dataclass
class NotificationResult:
    success: bool
    status: NotificationStatus
    provider_message_id: Optional[str] = None
    error_message: Optional[str] = None
    is_mock: bool = False
    provider_type: str = "mock"
    metadata: Optional[Dict[str, Any]] = None


class BaseNotificationProvider(ABC):
    """
    Abstract Base Class defining the contract for all communication channel adapters.
    """
    channel: NotificationChannel

    @abstractmethod
    def is_configured(self) -> bool:
        """Return True if real production credentials and configuration are supplied."""
        pass

    @abstractmethod
    def get_provider_type(self) -> str:
        """Return provider implementation identifier (e.g. 'smtp', 'twilio', 'meta', 'mock')."""
        pass

    @abstractmethod
    async def send(
        self,
        recipient: str,
        message: str,
        subject: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> NotificationResult:
        """
        Dispatch the notification message to the recipient.
        Must return NotificationResult and never raise unhandled network exceptions.
        """
        pass

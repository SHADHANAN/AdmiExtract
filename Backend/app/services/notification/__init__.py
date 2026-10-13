from typing import Dict
from app.models.verification_notification import NotificationChannel
from app.services.notification.base_provider import BaseNotificationProvider, NotificationResult
from app.services.notification.email_provider import EmailNotificationProvider
from app.services.notification.sms_provider import SMSNotificationProvider
from app.services.notification.whatsapp_provider import WhatsAppNotificationProvider
from app.services.notification.mock_provider import MockNotificationProvider
from app.services.notification.template_service import NotificationTemplateService

_mock_providers: Dict[NotificationChannel, MockNotificationProvider] = {
    NotificationChannel.EMAIL: MockNotificationProvider(NotificationChannel.EMAIL),
    NotificationChannel.SMS: MockNotificationProvider(NotificationChannel.SMS),
    NotificationChannel.WHATSAPP: MockNotificationProvider(NotificationChannel.WHATSAPP),
}

_real_providers: Dict[NotificationChannel, BaseNotificationProvider] = {
    NotificationChannel.EMAIL: EmailNotificationProvider(),
    NotificationChannel.SMS: SMSNotificationProvider(),
    NotificationChannel.WHATSAPP: WhatsAppNotificationProvider(),
}


def get_notification_provider(
    channel: NotificationChannel,
    force_mock: bool = False,
) -> BaseNotificationProvider:
    """
    Factory resolving the appropriate notification adapter.
    If force_mock is True, returns the deterministic mock provider for testing.
    """
    if force_mock:
        return _mock_providers[channel]
    return _real_providers[channel]


def get_mock_provider(channel: NotificationChannel) -> MockNotificationProvider:
    """Retrieve mock provider singleton for test assertions."""
    return _mock_providers[channel]


__all__ = [
    "NotificationChannel",
    "BaseNotificationProvider",
    "NotificationResult",
    "EmailNotificationProvider",
    "SMSNotificationProvider",
    "WhatsAppNotificationProvider",
    "MockNotificationProvider",
    "NotificationTemplateService",
    "get_notification_provider",
    "get_mock_provider",
]

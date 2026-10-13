from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Optional, Dict, Any
from beanie import Document, Indexed, PydanticObjectId
from pydantic import BaseModel, Field


class NotificationChannel(str, Enum):
    EMAIL = "EMAIL"
    SMS = "SMS"
    WHATSAPP = "WHATSAPP"


class NotificationStatus(str, Enum):
    PENDING = "PENDING"
    QUEUED = "QUEUED"
    SENT = "SENT"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class VerificationNotification(Document):
    """
    Persistent communication record for student verification link delivery.
    Decoupled from extraction and verification state machines.
    """
    id: PydanticObjectId = Field(default_factory=PydanticObjectId)
    extraction_request_id: Annotated[str, Indexed()]
    student_id: Annotated[str, Indexed()]
    submission_id: Optional[str] = None
    batch_id: Annotated[Optional[str], Indexed()] = None
    department_id: Optional[str] = None
    class_id: Optional[str] = None

    # Reference to verification token without exposing raw secret in clear text
    verification_token_id: Optional[str] = None
    token_str_masked: Optional[str] = None  # e.g. "xw7O...GUkf"

    channel: NotificationChannel = NotificationChannel.EMAIL
    recipient: str  # Email address or phone number (E.164)
    message_template_id: str = "default_verification_request"
    subject: Optional[str] = None
    message_body: Optional[str] = None

    status: NotificationStatus = NotificationStatus.PENDING
    provider_type: str = "mock"  # "mock", "smtp", "twilio", etc.
    provider_message_id: Optional[str] = None
    is_mock: bool = False

    retry_count: int = 0
    max_retries: int = 3
    failure_reason: Optional[str] = None

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    sent_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    failed_at: Optional[datetime] = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "verification_notifications"
        indexes = [
            "extraction_request_id",
            "student_id",
            "batch_id",
            "status",
            "channel",
            [
                ("extraction_request_id", 1),
                ("student_id", 1),
                ("channel", 1),
            ],
            [
                ("extraction_request_id", 1),
                ("status", 1),
            ],
        ]

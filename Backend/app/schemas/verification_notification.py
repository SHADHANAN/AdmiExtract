from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from app.models.verification_notification import NotificationChannel, NotificationStatus


class SendNotificationRequest(BaseModel):
    student_id: str
    channel: NotificationChannel = NotificationChannel.EMAIL
    force_resend: bool = False
    custom_message: Optional[str] = None


class SendBulkNotificationRequest(BaseModel):
    channel: NotificationChannel = NotificationChannel.EMAIL
    student_ids: Optional[List[str]] = None  # None = send to all eligible students
    force_resend: bool = False
    filter_status: Optional[str] = "ALL"  # "ALL", "PENDING_ONLY", "FAILED_ONLY"


class NotificationResponse(BaseModel):
    id: str
    extraction_request_id: str
    student_id: str
    student_name: Optional[str] = None
    channel: str
    recipient: str
    subject: Optional[str] = None
    message_preview: Optional[str] = None
    status: str
    is_mock: bool = False
    provider_type: str = "mock"
    failure_reason: Optional[str] = None
    retry_count: int = 0
    created_at: datetime
    sent_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None


class BulkNotificationSummaryResponse(BaseModel):
    extraction_request_id: str
    total_eligible: int
    total_attempted: int
    total_sent: int
    total_failed: int
    total_skipped_idempotent: int
    channel: str
    notifications: List[NotificationResponse]


class ProviderStatusItem(BaseModel):
    channel: str
    enabled: bool
    provider_type: str
    is_configured: bool
    status_display: str  # "Configured (Active)", "Mock / Test Mode", "Not Configured"
    description: str


class ProviderStatusResponse(BaseModel):
    providers: List[ProviderStatusItem]


class StudentNotificationStatusRow(BaseModel):
    student_id: str
    student_name: str
    register_number: str
    email: Optional[str] = None
    mobile_number: Optional[str] = None
    verification_status: str = "PENDING_VERIFICATION"
    has_token: bool = False
    has_valid_email: bool = False
    has_valid_mobile: bool = False
    notification_status: Optional[str] = "NOT_SENT"
    latest_notification_status: Optional[str] = None
    latest_notification_channel: Optional[str] = None
    latest_sent_at: Optional[datetime] = None
    latest_failure_reason: Optional[str] = None
    notification_count: int = 0

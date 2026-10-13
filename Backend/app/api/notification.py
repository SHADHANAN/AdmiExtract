from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.dependencies import get_current_user, RoleChecker
from app.models.user import User, UserRole
from app.models.verification_notification import NotificationChannel
from app.schemas.verification_notification import (
    SendNotificationRequest,
    SendBulkNotificationRequest,
    NotificationResponse,
    BulkNotificationSummaryResponse,
    ProviderStatusResponse,
    StudentNotificationStatusRow,
)
from app.services.notification_service import NotificationService

router = APIRouter(
    prefix="/data-extractions",
    tags=["Student Verification Notifications"],
    dependencies=[
        Depends(
            RoleChecker(
                [
                    UserRole.SUPER_ADMIN,
                    UserRole.DEPARTMENT_ADMIN,
                ]
            )
        )
    ],
)

service = NotificationService()


@router.get(
    "/notifications/providers/status",
    response_model=ProviderStatusResponse,
)
async def get_provider_status(
    current_user: User = Depends(get_current_user),
):
    """
    Retrieve real configuration status of all notification channels (Email, SMS, WhatsApp).
    Staff UI uses this to display accurate active/inactive provider badges.
    """
    return await service.get_provider_status()


@router.get(
    "/{extraction_request_id}/notifications",
    response_model=List[NotificationResponse],
)
async def list_extraction_notifications(
    extraction_request_id: str,
    current_user: User = Depends(get_current_user),
):
    """
    Retrieve notification delivery history logs for an extraction request.
    Token references are masked to prevent leakage in administrative logs.
    """
    return await service.get_extraction_notifications(
        extraction_request_id=extraction_request_id,
        actor=current_user,
    )


@router.get(
    "/{extraction_request_id}/notifications/students",
    response_model=List[StudentNotificationStatusRow],
)
async def get_student_notification_status_table(
    extraction_request_id: str,
    current_user: User = Depends(get_current_user),
):
    """
    Retrieve aggregated candidate rows displaying student details, verification progress,
    active token status, and latest communication delivery outcome.
    """
    return await service.get_student_notification_status_table(
        extraction_request_id=extraction_request_id,
        actor=current_user,
    )


@router.post(
    "/{extraction_request_id}/notifications/send",
    response_model=NotificationResponse,
)
async def send_single_student_notification(
    extraction_request_id: str,
    req: SendNotificationRequest,
    force_mock: bool = Query(False, description="Use deterministic mock provider for testing"),
    current_user: User = Depends(get_current_user),
):
    """
    Dispatch a verification link notification to an individual candidate.
    Enforces idempotency unless force_resend is set to True.
    """
    notif_doc, _ = await service.send_student_verification_notification(
        extraction_request_id=extraction_request_id,
        student_id=req.student_id,
        channel=req.channel,
        actor=current_user,
        force_resend=req.force_resend,
        force_mock=force_mock,
        custom_message=req.custom_message,
    )
    # Lookup student name
    return service._to_response(notif_doc)


@router.post(
    "/{extraction_request_id}/notifications/send-bulk",
    response_model=BulkNotificationSummaryResponse,
)
async def send_bulk_student_notifications(
    extraction_request_id: str,
    req: SendBulkNotificationRequest,
    force_mock: bool = Query(False, description="Use deterministic mock provider for testing"),
    current_user: User = Depends(get_current_user),
):
    """
    Bulk dispatch verification link notifications to all or selected candidates in an extraction batch.
    """
    return await service.send_bulk_verification_notifications(
        extraction_request_id=extraction_request_id,
        channel=req.channel,
        actor=current_user,
        student_ids=req.student_ids,
        force_resend=req.force_resend,
        force_mock=force_mock,
        filter_status=req.filter_status,
    )


@router.post(
    "/notifications/{notification_id}/retry",
    response_model=NotificationResponse,
)
async def retry_notification_delivery(
    notification_id: str,
    force_mock: bool = Query(False, description="Use deterministic mock provider for testing"),
    current_user: User = Depends(get_current_user),
):
    """
    Retry a failed or pending notification delivery without regenerating the student's verification token.
    """
    return await service.retry_notification(
        notification_id=notification_id,
        actor=current_user,
        force_mock=force_mock,
    )

from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional, Tuple
from fastapi import HTTPException, status
from beanie import PydanticObjectId

from app.core.config import settings
from app.models.user import User, UserRole
from app.models.batch import AdmissionBatch
from app.models.student_submission import StudentSubmission
from app.models.batch_extraction import BatchExtractionRequest
from app.models.verification_token import VerificationToken, VerificationTokenStatus
from app.models.verification_notification import (
    VerificationNotification,
    NotificationChannel,
    NotificationStatus,
)
from app.models.document_verification import DocumentFieldVerification
from app.repositories.batch_extraction_repository import BatchExtractionRepository
from app.repositories.batch_repository import BatchRepository
from app.services.verification_token_service import VerificationTokenService
from app.services.notification import (
    get_notification_provider,
    NotificationTemplateService,
    NotificationResult,
)
from app.schemas.verification_notification import (
    NotificationResponse,
    BulkNotificationSummaryResponse,
    ProviderStatusItem,
    ProviderStatusResponse,
    StudentNotificationStatusRow,
)

logger = logging.getLogger("app.services.notification_service")


class NotificationService:
    """
    Orchestrates the communication layer for student verification link distribution.
    Enforces idempotency, tenant isolation, recipient resolution, and multi-channel provider dispatch.
    """

    def __init__(
        self,
        batch_repository: Optional[BatchRepository] = None,
        extraction_repository: Optional[BatchExtractionRepository] = None,
        token_service: Optional[VerificationTokenService] = None,
        template_service: Optional[NotificationTemplateService] = None,
    ):
        self.batch_repo = batch_repository or BatchRepository()
        self.extraction_repo = extraction_repository or BatchExtractionRepository()
        self.token_service = token_service or VerificationTokenService()
        self.template_service = template_service or NotificationTemplateService()

    def _verify_batch_access(self, batch: AdmissionBatch, actor: User) -> None:
        """Enforce strict RBAC and department tenancy on admission batch."""
        if actor.role == UserRole.SUPER_ADMIN:
            return
        if actor.role == UserRole.DEPARTMENT_ADMIN:
            user_dept = getattr(actor, "department_code", None) or getattr(actor, "department_id", None)
            if not user_dept or batch.department_id != user_dept:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Forbidden: You do not have permission to access another department's notifications.",
                )
            return
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Unauthorized notification access.",
        )

    def _mask_token(self, token_str: str) -> str:
        """Return masked token string for safe logging and display."""
        if not token_str or len(token_str) < 8:
            return "****"
        return f"{token_str[:4]}...{token_str[-4:]}"

    def _to_response(self, n: VerificationNotification, student_name: Optional[str] = None) -> NotificationResponse:
        return NotificationResponse(
            id=str(n.id),
            extraction_request_id=n.extraction_request_id,
            student_id=n.student_id,
            student_name=student_name,
            channel=n.channel.value if isinstance(n.channel, NotificationChannel) else str(n.channel),
            recipient=n.recipient,
            subject=n.subject,
            message_preview=n.message_body[:120] + "..." if n.message_body and len(n.message_body) > 120 else n.message_body,
            status=n.status.value if isinstance(n.status, NotificationStatus) else str(n.status),
            is_mock=n.is_mock,
            provider_type=n.provider_type,
            failure_reason=n.failure_reason,
            retry_count=n.retry_count,
            created_at=n.created_at,
            sent_at=n.sent_at,
            delivered_at=n.delivered_at,
        )

    async def get_provider_status(self) -> ProviderStatusResponse:
        """Retrieve real configuration status of Email, SMS, and WhatsApp providers."""
        email_p = get_notification_provider(NotificationChannel.EMAIL)
        sms_p = get_notification_provider(NotificationChannel.SMS)
        wa_p = get_notification_provider(NotificationChannel.WHATSAPP)

        items = [
            ProviderStatusItem(
                channel=NotificationChannel.EMAIL.value,
                enabled=settings.EMAIL_PROVIDER_ENABLED,
                provider_type=email_p.get_provider_type(),
                is_configured=email_p.is_configured(),
                status_display="Configured (Active)" if email_p.is_configured() else "Not Configured (SMTP disabled/missing)",
                description="Sends verification portal URLs via SMTP/Email gateway to student email addresses.",
            ),
            ProviderStatusItem(
                channel=NotificationChannel.SMS.value,
                enabled=settings.SMS_PROVIDER_ENABLED,
                provider_type=sms_p.get_provider_type(),
                is_configured=sms_p.is_configured(),
                status_display="Configured (Active)" if sms_p.is_configured() else "Not Configured (SMS gateway missing)",
                description="Sends short verification links via SMS gateway to candidate mobile phone numbers.",
            ),
            ProviderStatusItem(
                channel=NotificationChannel.WHATSAPP.value,
                enabled=settings.WHATSAPP_PROVIDER_ENABLED,
                provider_type=wa_p.get_provider_type(),
                is_configured=wa_p.is_configured(),
                status_display="Configured (Active)" if wa_p.is_configured() else "Not Configured (WhatsApp API missing)",
                description="Sends formatted template messages with verification links via WhatsApp Business Cloud API.",
            ),
        ]
        return ProviderStatusResponse(providers=items)

    async def send_student_verification_notification(
        self,
        extraction_request_id: str,
        student_id: str,
        channel: NotificationChannel,
        actor: User,
        force_resend: bool = False,
        force_mock: bool = False,
        custom_message: Optional[str] = None,
    ) -> Tuple[VerificationNotification, bool]:
        """
        Send a verification link notification to an individual student.
        Returns (notification_record, was_newly_sent).
        """
        req = await self.extraction_repo.get_by_request_id(extraction_request_id)
        if not req:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Extraction request '{extraction_request_id}' not found.",
            )

        batch = await self.batch_repo.get_batch_by_id(req.batch_id)
        if not batch:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Batch '{req.batch_id}' not found.",
            )
        self._verify_batch_access(batch, actor)

        # Retrieve student submission to obtain contact coordinates
        sub = await StudentSubmission.find_one(
            StudentSubmission.batch_id == batch.id,
            StudentSubmission.register_number == student_id,
        )
        if not sub:
            # Fallback by student_id or _id
            sub = await StudentSubmission.find_one(
                StudentSubmission.batch_id == batch.id,
                StudentSubmission.id == student_id,
            )

        student_name = sub.student_name if sub else student_id
        student_reg = sub.register_number if sub else student_id
        submission_id = str(sub.id) if sub else None

        # Resolve contact info based on selected channel
        recipient = None
        if channel == NotificationChannel.EMAIL:
            recipient = sub.email.strip() if (sub and sub.email) else None
        elif channel in (NotificationChannel.SMS, NotificationChannel.WHATSAPP):
            recipient = sub.mobile_number.strip() if (sub and sub.mobile_number) else None

        base_url = settings.PUBLIC_APP_URL.rstrip("/")
        verification_url = f"{base_url}/student-verification?batch_id={batch.id}&extraction_id={req.extraction_request_id}"
        token_id_val = None
        masked_tok = "COMMON_LINK"

        # Check for recipient contact availability
        if not recipient:
            contact_label = "Email address" if channel == NotificationChannel.EMAIL else "Mobile phone number"
            reason = f"{contact_label} is unavailable in student submission records."

            notif = VerificationNotification(
                extraction_request_id=req.extraction_request_id,
                student_id=student_reg,
                submission_id=submission_id,
                batch_id=batch.id,
                department_id=batch.department_id,
                class_id=req.class_id,
                verification_token_id=token_id_val,
                token_str_masked=masked_tok,
                channel=channel,
                recipient="<UNAVAILABLE>",
                status=NotificationStatus.FAILED,
                failure_reason=reason,
                is_mock=force_mock,
                failed_at=datetime.now(timezone.utc),
            )
            await notif.insert()
            return notif, True

        # Idempotency Check: Avoid duplicate sends unless force_resend is explicitly requested
        if not force_resend:
            existing_active = await VerificationNotification.find_one(
                VerificationNotification.extraction_request_id == req.extraction_request_id,
                VerificationNotification.student_id == student_reg,
                VerificationNotification.channel == channel,
                {"status": {"$in": [NotificationStatus.SENT.value, NotificationStatus.DELIVERED.value, NotificationStatus.QUEUED.value]}},
            )
            if existing_active:
                logger.info(f"[NotificationService] Idempotency: Skipped re-send for student {student_reg} on channel {channel.value}")
                return existing_active, False

        # Render message content using Template Service
        rendered = self.template_service.render(
            channel=channel,
            student_name=student_name,
            verification_link=verification_url,
            batch_name=batch.name,
            register_number=student_reg,
            institution_name=settings.INSTITUTION_NAME,
            custom_body=custom_message,
        )

        provider = get_notification_provider(channel, force_mock=force_mock)
        provider_type = provider.get_provider_type()

        notif = VerificationNotification(
            extraction_request_id=req.extraction_request_id,
            student_id=student_reg,
            submission_id=submission_id,
            batch_id=batch.id,
            department_id=batch.department_id,
            class_id=req.class_id,
            verification_token_id=token_id_val,
            token_str_masked=masked_tok,
            channel=channel,
            recipient=recipient,
            subject=rendered.get("subject"),
            message_body=rendered.get("body"),
            status=NotificationStatus.PENDING,
            provider_type=provider_type,
            is_mock=force_mock,
        )
        await notif.insert()

        # Dispatch via communication adapter
        dispatch_res: NotificationResult = await provider.send(
            recipient=recipient,
            message=rendered["body"],
            subject=rendered.get("subject"),
            metadata={
                "extraction_request_id": req.extraction_request_id,
                "student_id": student_reg,
                "batch_id": batch.id,
                "notification_id": str(notif.id),
            },
        )

        now = datetime.now(timezone.utc)
        if dispatch_res.success:
            notif.status = dispatch_res.status
            notif.sent_at = now
            notif.provider_message_id = dispatch_res.provider_message_id
            notif.is_mock = dispatch_res.is_mock
            notif.failure_reason = None
        else:
            notif.status = NotificationStatus.FAILED
            notif.failed_at = now
            notif.failure_reason = dispatch_res.error_message or "Provider dispatch failed."

        await notif.save()
        return notif, True

    async def send_bulk_verification_notifications(
        self,
        extraction_request_id: str,
        channel: NotificationChannel,
        actor: User,
        student_ids: Optional[List[str]] = None,
        force_resend: bool = False,
        force_mock: bool = False,
        filter_status: Optional[str] = "ALL",
    ) -> BulkNotificationSummaryResponse:
        """
        Bulk dispatch verification link notifications to eligible students in an extraction batch.
        """
        req = await self.extraction_repo.get_by_request_id(extraction_request_id)
        if not req:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Extraction request '{extraction_request_id}' not found.",
            )

        batch = await self.batch_repo.get_batch_by_id(req.batch_id)
        if not batch:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Batch '{req.batch_id}' not found.",
            )
        self._verify_batch_access(batch, actor)

        # Query all student verification records associated with this extraction request
        verifs = await DocumentFieldVerification.find(
            DocumentFieldVerification.extraction_request_id == req.extraction_request_id
        ).to_list()

        all_candidate_ids = sorted(list(set(v.student_id for v in verifs if v.student_id)))
        if not all_candidate_ids:
            # Fallback: Query submissions under this batch
            sub_query = {"batch_id": batch.id}
            if req.class_id:
                sub_query["class_id"] = req.class_id
            subs = await StudentSubmission.find(sub_query).to_list()
            all_candidate_ids = [s.register_number for s in subs if s.register_number]

        # Filter target student IDs
        target_ids = all_candidate_ids
        if student_ids and len(student_ids) > 0:
            filter_set = set(student_ids)
            target_ids = [s for s in target_ids if s in filter_set]

        total_eligible = len(target_ids)
        total_attempted = 0
        total_sent = 0
        total_failed = 0
        total_skipped = 0
        notif_responses: List[NotificationResponse] = []

        for stud_id in target_ids:
            total_attempted += 1
            try:
                notif_doc, was_new = await self.send_student_verification_notification(
                    extraction_request_id=extraction_request_id,
                    student_id=stud_id,
                    channel=channel,
                    actor=actor,
                    force_resend=force_resend,
                    force_mock=force_mock,
                )
                if not was_new and not force_resend:
                    total_skipped += 1
                elif notif_doc.status in (NotificationStatus.SENT, NotificationStatus.DELIVERED):
                    total_sent += 1
                else:
                    total_failed += 1

                # Lookup student name
                sub = await StudentSubmission.find_one(StudentSubmission.register_number == stud_id)
                s_name = sub.student_name if sub else stud_id
                notif_responses.append(self._to_response(notif_doc, student_name=s_name))

            except Exception as e:
                logger.error(f"[NotificationService] Error sending bulk notification to {stud_id}: {e}")
                total_failed += 1

        return BulkNotificationSummaryResponse(
            extraction_request_id=req.extraction_request_id,
            total_eligible=total_eligible,
            total_attempted=total_attempted,
            total_sent=total_sent,
            total_failed=total_failed,
            total_skipped_idempotent=total_skipped,
            channel=channel.value,
            notifications=notif_responses,
        )

    async def retry_notification(
        self,
        notification_id: str,
        actor: User,
        force_mock: bool = False,
    ) -> NotificationResponse:
        """Retry a failed or pending notification delivery attempt."""
        try:
            p_id = PydanticObjectId(notification_id)
            notif = await VerificationNotification.get(p_id)
        except Exception:
            notif = None

        if not notif:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Notification record '{notification_id}' not found.",
            )

        batch = await self.batch_repo.get_batch_by_id(notif.batch_id) if notif.batch_id else None
        if batch:
            self._verify_batch_access(batch, actor)

        notif.retry_count += 1
        now = datetime.now(timezone.utc)

        # Check if student contact is valid
        if not notif.recipient or notif.recipient == "<UNAVAILABLE>":
            notif.status = NotificationStatus.FAILED
            notif.failure_reason = f"Cannot retry: {notif.channel.value} recipient contact is unavailable."
            notif.failed_at = now
            await notif.save()
            return self._to_response(notif)

        provider = get_notification_provider(notif.channel, force_mock=force_mock)
        dispatch_res: NotificationResult = await provider.send(
            recipient=notif.recipient,
            message=notif.message_body or "Student Data Verification Required",
            subject=notif.subject,
            metadata={
                "extraction_request_id": notif.extraction_request_id,
                "student_id": notif.student_id,
                "notification_id": str(notif.id),
                "retry_count": notif.retry_count,
            },
        )

        if dispatch_res.success:
            notif.status = dispatch_res.status
            notif.sent_at = now
            notif.provider_message_id = dispatch_res.provider_message_id
            notif.is_mock = dispatch_res.is_mock
            notif.failure_reason = None
        else:
            notif.status = NotificationStatus.FAILED
            notif.failed_at = now
            notif.failure_reason = dispatch_res.error_message or "Retry delivery failed."

        await notif.save()
        return self._to_response(notif)

    async def get_extraction_notifications(
        self,
        extraction_request_id: str,
        actor: User,
    ) -> List[NotificationResponse]:
        """List all delivery history records for an extraction request without leaking tokens."""
        req = await self.extraction_repo.get_by_request_id(extraction_request_id)
        if not req:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Extraction request '{extraction_request_id}' not found.",
            )

        batch = await self.batch_repo.get_batch_by_id(req.batch_id)
        if batch:
            self._verify_batch_access(batch, actor)

        records = await VerificationNotification.find(
            VerificationNotification.extraction_request_id == req.extraction_request_id
        ).sort("-created_at").to_list()

        # Build student name lookup
        student_ids = list(set(r.student_id for r in records))
        subs = await StudentSubmission.find({"register_number": {"$in": student_ids}}).to_list()
        name_map = {s.register_number: s.student_name for s in subs}

        return [self._to_response(r, student_name=name_map.get(r.student_id)) for r in records]

    async def get_student_notification_status_table(
        self,
        extraction_request_id: str,
        actor: User,
    ) -> List[StudentNotificationStatusRow]:
        """
        Build aggregated student rows combining candidate profile, verification status,
        active token flag, and latest notification delivery outcome.
        """
        req = await self.extraction_repo.get_by_request_id(extraction_request_id)
        if not req:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Extraction request '{extraction_request_id}' not found.",
            )

        batch = await self.batch_repo.get_batch_by_id(req.batch_id)
        if batch:
            self._verify_batch_access(batch, actor)

        # Get field verification records for this extraction
        verif_records = await DocumentFieldVerification.find(
            DocumentFieldVerification.extraction_request_id == req.extraction_request_id
        ).to_list()

        student_verifs: Dict[str, List[DocumentFieldVerification]] = {}
        for vr in verif_records:
            student_verifs.setdefault(vr.student_id, []).append(vr)

        # Get all notifications for this extraction
        notifications = await VerificationNotification.find(
            VerificationNotification.extraction_request_id == req.extraction_request_id
        ).sort("-created_at").to_list()

        student_notifs: Dict[str, List[VerificationNotification]] = {}
        for n in notifications:
            student_notifs.setdefault(n.student_id, []).append(n)

        # Get all verification tokens
        tokens = await VerificationToken.find(
            {"$or": [
                {"extraction_request_id": req.extraction_request_id},
                {"batch_id": req.batch_id},
            ]}
        ).to_list()
        tokens_map = {t.student_id: t for t in tokens if t.is_valid}
        completed_token_ids = {
            t.student_id.strip().upper()
            for t in tokens
            if t.status == VerificationTokenStatus.COMPLETED.value
        }

        # Query student submissions for this batch
        sub_query = {"batch_id": batch.id}
        if req.class_id:
            sub_query["class_id"] = req.class_id
        submissions = await StudentSubmission.find(sub_query).to_list()
        sub_map = {s.register_number: s for s in submissions if s.register_number}

        all_student_ids = sorted(list(set(student_verifs.keys()) | set(sub_map.keys())))

        rows: List[StudentNotificationStatusRow] = []
        for s_id in all_student_ids:
            sub = sub_map.get(s_id)
            s_name = sub.student_name if sub else s_id
            s_reg = sub.register_number if sub else s_id
            s_email = sub.email if sub else None
            s_mobile = sub.mobile_number if sub else None

            # Calculate verification status
            v_list = student_verifs.get(s_id, [])
            is_token_completed = (
                s_id.strip().upper() in completed_token_ids
                or (sub and sub.register_number and sub.register_number.strip().upper() in completed_token_ids)
            )
            has_student_sub = any(
                bool(v.student_updated_at)
                or getattr(v, "student_value", None) is not None
                or any(
                    h.action in ("STUDENT_CONFIRM", "STUDENT_EDIT", "STUDENT_CORRECTION")
                    or h.actor_role in ("student", "STUDENT_PUBLIC")
                    for h in (v.history or [])
                )
                for v in v_list
            ) or (sub and getattr(sub, "submission_status", None) in ("Student Verified", "STUDENT_VERIFIED")) or is_token_completed

            all_staff_approved = bool(v_list) and all(v.status in ("STAFF_APPROVED", "STAFF_REJECTED") for v in v_list)
            all_finalized = bool(v_list) and all(
                v.status in ("STUDENT_VERIFIED", "STUDENT_CONFIRMED", "STAFF_APPROVED", "STAFF_REJECTED")
                for v in v_list
            )

            is_student_verified = (
                (all_finalized and has_student_sub)
                or (is_token_completed and not any(v.status == "CORRECTION_REQUESTED" for v in v_list))
                or (sub and getattr(sub, "submission_status", None) in ("Student Verified", "STUDENT_VERIFIED") and not any(v.status == "CORRECTION_REQUESTED" for v in v_list))
                or (has_student_sub and not any(v.status == "CORRECTION_REQUESTED" for v in v_list) and bool(v_list) and any(v.status in ("STUDENT_CONFIRMED", "STUDENT_VERIFIED") for v in v_list))
            )

            if any(v.status == "CORRECTION_REQUESTED" for v in v_list):
                v_status = "CORRECTION_REQUESTED"
            elif all_staff_approved:
                v_status = "VERIFIED"
            elif is_student_verified:
                v_status = "STUDENT_VERIFIED"
            else:
                v_status = "PENDING_VERIFICATION"

            # Latest notification
            n_list = student_notifs.get(s_id, [])
            latest_n = n_list[0] if n_list else None

            notif_status_val = latest_n.status.value if latest_n else "NOT_SENT"
            rows.append(
                StudentNotificationStatusRow(
                    student_id=s_id,
                    student_name=s_name,
                    register_number=s_reg,
                    email=s_email,
                    mobile_number=s_mobile,
                    verification_status=v_status,
                    has_token=bool(s_id in tokens_map or is_token_completed),
                    has_valid_email=bool(s_email and "@" in s_email),
                    has_valid_mobile=bool(s_mobile and len(s_mobile.strip()) >= 10),
                    notification_status=notif_status_val,
                    latest_notification_status=notif_status_val if latest_n else None,
                    latest_notification_channel=latest_n.channel.value if latest_n else None,
                    latest_sent_at=latest_n.sent_at if latest_n else None,
                    latest_failure_reason=latest_n.failure_reason if latest_n else None,
                    notification_count=len(n_list),
                )
            )

        return rows

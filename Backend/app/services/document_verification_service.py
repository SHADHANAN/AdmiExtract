import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from fastapi import HTTPException, status
from beanie import PydanticObjectId

from app.models.document_verification import (
    DocumentFieldVerification,
    VerificationFieldStatus,
    VerificationHistoryEntry,
)
from app.models.student_document import StudentDocument
from app.models.document_extraction_result import DocumentExtractionResult
from app.models.document_extraction_request import DocumentExtractionRequest
from app.models.user import User, UserRole
from app.models.audit_log import AuditLog
from app.repositories.document_verification_repository import (
    DocumentVerificationRepository,
)
from app.schemas.document_verification import (
    StudentVerificationSubmitRequest,
)

logger = logging.getLogger("app.services.document_verification_service")


class DocumentVerificationService:
    """
    Service layer orchestrating the post-extraction verification loop:
    Student confirmation/correction -> Staff review/approval -> Final verified data.
    """

    def __init__(
        self,
        repository: Optional[DocumentVerificationRepository] = None,
    ):
        self.repository = repository or DocumentVerificationRepository()

    async def initialize_verification_from_extraction(
        self,
        extraction_result: DocumentExtractionResult,
        student_doc: StudentDocument,
        extraction_req: Optional[DocumentExtractionRequest] = None,
    ) -> List[DocumentFieldVerification]:
        """
        Create initial DocumentFieldVerification records with status AI_EXTRACTED
        for every extracted field from an extraction result snapshot.
        """
        now = datetime.now(timezone.utc)
        existing = await self.repository.get_by_extraction_result(
            str(extraction_result.id)
        )
        existing_fields = {r.field_name for r in existing}

        records_to_create: List[DocumentFieldVerification] = []
        for field_name, val in extraction_result.extracted_data.items():
            if field_name in existing_fields:
                continue

            init_history = [
                VerificationHistoryEntry(
                    actor="AI_ENGINE",
                    actor_role="SYSTEM",
                    action="AI_EXTRACTION",
                    old_value=None,
                    new_value=val,
                    document_version_id=extraction_result.document_version_id,
                    timestamp=now,
                )
            ]

            rec = DocumentFieldVerification(
                extraction_result_id=str(extraction_result.id),
                extraction_request_id=str(extraction_req.id) if extraction_req else extraction_result.extraction_request_id,
                student_id=student_doc.student_id,
                document_id=str(student_doc.id),
                document_version_id=extraction_result.document_version_id,
                department_id=student_doc.department_id,
                batch_id=student_doc.batch_id,
                class_id=student_doc.class_id or student_doc.section_id,
                document_type=student_doc.document_type,
                field_name=field_name,
                ai_value=val,
                student_value=None,
                final_value=None,
                status=VerificationFieldStatus.AI_EXTRACTED,
                field_state="FIELD_NOT_FOUND" if val is None else "EXTRACTED",
                history=init_history,
                created_at=now,
                updated_at=now,
            )
            records_to_create.append(rec)

        if records_to_create:
            await self.repository.bulk_create(records_to_create)
            logger.info(
                f"[VerificationService] Initialized {len(records_to_create)} verification records for extraction {extraction_result.id}"
            )

        return existing + records_to_create

    def verify_student_ownership(self, student_id: str, actor: User) -> None:
        """Enforce that student user can only access/modify their own verification records."""
        if actor.role in (UserRole.SUPER_ADMIN, UserRole.DEPARTMENT_ADMIN):
            return

        if actor.role == UserRole.STUDENT:
            user_reg = actor.register_number or actor.username
            user_id_str = str(actor.id)
            if (
                student_id != user_id_str
                and student_id != user_reg
                and student_id != actor.username
            ):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Forbidden: Students are only permitted to access their own verification records.",
                )
            return

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Unauthorized verification access.",
        )

    async def get_student_verifications(
        self,
        student_id: str,
        actor: User,
        document_id: Optional[str] = None,
        batch_id: Optional[str] = None,
        extraction_request_id: Optional[str] = None,
    ) -> List[DocumentFieldVerification]:
        """
        Retrieve verification records for a student scoped to the latest or requested extraction run.
        Enforces:
        - Student identity ownership.
        - Resolving the latest completed extraction request when batch_id is present and extraction_request_id is omitted.
        - Deterministic deduplication by canonical field key.
        """
        self.verify_student_ownership(student_id, actor)

        from app.services.document_extraction_service import resolve_canonical_field_key

        clean_sid = (student_id or "").strip()
        stud_variants = {clean_sid, clean_sid.upper(), clean_sid.lower()}
        from app.models.student_submission import StudentSubmission
        sub_lookup = await StudentSubmission.find_one(
            {"$or": [
                {"register_number": clean_sid.upper()},
                {"register_number": clean_sid},
                {"student_id": clean_sid},
            ]}
        )
        if sub_lookup:
            if sub_lookup.register_number:
                stud_variants.update({sub_lookup.register_number.strip(), sub_lookup.register_number.strip().upper(), sub_lookup.register_number.strip().lower()})
            s_id = getattr(sub_lookup, "student_id", None)
            if s_id:
                stud_variants.update({s_id.strip(), s_id.strip().upper(), s_id.strip().lower()})
            stud_variants.add(str(sub_lookup.id))
            if not batch_id and sub_lookup.batch_id:
                batch_id = sub_lookup.batch_id

        target_ext_id = extraction_request_id
        if not target_ext_id and batch_id:
            from app.services.verification_token_service import VerificationTokenService
            v_svc = VerificationTokenService()
            latest_req = await v_svc.resolve_latest_successful_batch_extraction(
                batch_id=batch_id, student_id=clean_sid
            )
            if latest_req:
                target_ext_id = latest_req.extraction_request_id

        student_query_clause = {
            "$or": [
                {"student_id": {"$in": list(stud_variants)}},
                {"student_submission_id": {"$in": list(stud_variants)}},
            ]
        }

        if document_id:
            all_doc_records = await self.repository.get_by_document_id(document_id)
            records = [r for r in all_doc_records if r.student_id in stud_variants or r.student_submission_id in stud_variants]
        elif target_ext_id:
            records = await DocumentFieldVerification.find(
                student_query_clause,
                DocumentFieldVerification.extraction_request_id == target_ext_id,
            ).sort("-created_at").to_list()
        else:
            records = await DocumentFieldVerification.find(
                student_query_clause
            ).sort("-created_at").to_list()

        # Deduplicate fields deterministically by canonical key
        deduped: Dict[str, DocumentFieldVerification] = {}
        for r in records:
            canon_k = resolve_canonical_field_key(r.field_name) or r.field_name.strip().lower().replace(" ", "_")
            if canon_k not in deduped:
                deduped[canon_k] = r
            else:
                existing_r = deduped[canon_k]
                def _score(item: DocumentFieldVerification) -> Tuple[int, float, int, int]:
                    ext_match = 1 if (target_ext_id and item.extraction_request_id == target_ext_id) else 0
                    ts = (item.updated_at or item.created_at or datetime.min.replace(tzinfo=timezone.utc)).timestamp()
                    verif_pri = 2 if item.status in (
                        VerificationFieldStatus.STUDENT_VERIFIED,
                        VerificationFieldStatus.STUDENT_CONFIRMED,
                        VerificationFieldStatus.STAFF_APPROVED,
                    ) else (1 if item.status == VerificationFieldStatus.CORRECTION_REQUESTED else 0)
                    has_val = 1 if item.final_value or item.student_value or (item.ai_value and item.ai_value not in ("NOT_AVAILABLE", "NOT_FOUND")) else 0
                    return (ext_match, ts, verif_pri, has_val)

                if _score(r) > _score(existing_r):
                    deduped[canon_k] = r

        return list(deduped.values())

    async def submit_student_verification(
        self,
        student_id: str,
        submit_req: StudentVerificationSubmitRequest,
        actor: User,
    ) -> List[DocumentFieldVerification]:
        """
        Process student verification responses:
        - Confirmed fields -> status = STUDENT_CONFIRMED, final_value = ai_value
        - Edited fields -> status = CORRECTION_REQUESTED, final_value = None (pending staff approval)
        - ai_value is NEVER mutated or destroyed.
        """
        self.verify_student_ownership(student_id, actor)
        now = datetime.now(timezone.utc)
        if not submit_req.fields:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Verification submission must contain at least one field.",
            )

        # Pre-validate all records and ownership before making any database mutations
        validated_items = []
        for item in submit_req.fields:
            rec = await self.repository.get_by_id(item.verification_id)
            if not rec:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Verification record '{item.verification_id}' not found.",
                )

            if rec.student_id != student_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Forbidden: Cannot modify another student's verification records.",
                )

            comment_text = item.comment or submit_req.general_comment
            is_confirmed = item.is_confirmed or (
                item.corrected_value is not None and str(item.corrected_value).strip() == str(rec.ai_value or "").strip()
            )
            validated_items.append((rec, item, is_confirmed, comment_text))

        updated_records: List[DocumentFieldVerification] = []
        for rec, item, is_confirmed, comment_text in validated_items:
            if is_confirmed:
                rec.status = VerificationFieldStatus.STUDENT_CONFIRMED
                rec.student_value = rec.ai_value
                rec.final_value = rec.ai_value
                rec.student_updated_at = now
                rec.student_comment = comment_text

                rec.history.append(
                    VerificationHistoryEntry(
                        actor=actor.username,
                        actor_role="student",
                        action="STUDENT_CONFIRM",
                        old_value=rec.ai_value,
                        new_value=rec.ai_value,
                        comment=comment_text,
                        document_version_id=rec.document_version_id,
                        timestamp=now,
                    )
                )
            else:
                # Student submitted an edit - saved directly as final verified value
                new_val = item.corrected_value
                rec.status = VerificationFieldStatus.STUDENT_VERIFIED
                rec.student_value = new_val
                rec.final_value = new_val
                rec.student_updated_at = now
                rec.student_comment = comment_text
                rec.field_state = "MANUALLY_ENTERED"
                rec.updated_at = now

                rec.history.append(
                    VerificationHistoryEntry(
                        actor=actor.username,
                        actor_role="student",
                        action="STUDENT_EDIT",
                        old_value=rec.ai_value,
                        new_value=new_val,
                        comment=comment_text or "Edited by student via verification",
                        document_version_id=rec.document_version_id,
                        timestamp=now,
                    )
                )

            saved = await self.repository.save_record(rec)
            updated_records.append(saved)

        # Update StudentSubmission submission_status if student record exists
        try:
            from app.models.student_submission import StudentSubmission
            sub = await StudentSubmission.find_one(
                {"$or": [{"register_number": student_id}, {"student_id": student_id}]}
            )
            if sub:
                sub.submission_status = "Student Verified"
                await sub.save()
        except Exception as sub_err:
            logger.debug(f"[submit_student_verification] Could not update StudentSubmission: {sub_err}")

        return updated_records

    async def list_pending_corrections(
        self,
        actor: User,
        batch_id: Optional[str] = None,
        class_id: Optional[str] = None,
    ) -> List[DocumentFieldVerification]:
        """Staff endpoint to list pending corrections with RBAC & department isolation."""
        if actor.role not in (UserRole.SUPER_ADMIN, UserRole.DEPARTMENT_ADMIN):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only staff administrators can view pending corrections.",
            )

        dept_id = None
        if actor.role == UserRole.DEPARTMENT_ADMIN:
            dept_id = getattr(actor, "department_code", None) or getattr(actor, "department_id", None)

        return await self.repository.get_pending_corrections(
            department_id=dept_id,
            batch_id=batch_id,
            class_id=class_id,
        )

    async def review_correction(
        self,
        verification_id: str,
        action: str,
        actor: User,
        staff_comment: Optional[str] = None,
    ) -> DocumentFieldVerification:
        """
        Staff reviews a pending correction:
        - APPROVE -> final_value = student_value, status = STAFF_APPROVED
        - REJECT  -> final_value = ai_value, status = STAFF_REJECTED
        """
        if actor.role not in (UserRole.SUPER_ADMIN, UserRole.DEPARTMENT_ADMIN):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only staff administrators can review student corrections.",
            )

        rec = await self.repository.get_by_id(verification_id)
        if not rec:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Verification record '{verification_id}' not found.",
            )

        # Department isolation check
        if actor.role == UserRole.DEPARTMENT_ADMIN:
            user_dept = getattr(actor, "department_code", None) or getattr(actor, "department_id", None)
            if user_dept and rec.department_id and user_dept != rec.department_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Cross-department correction review is forbidden.",
                )

        if rec.status in (VerificationFieldStatus.STAFF_APPROVED, VerificationFieldStatus.STAFF_REJECTED):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Verification field '{rec.field_name}' has already been reviewed by staff ({rec.status.value if hasattr(rec.status, 'value') else rec.status}).",
            )

        now = datetime.now(timezone.utc)
        act_upper = action.strip().upper()

        if act_upper == "APPROVE":
            rec.status = VerificationFieldStatus.STAFF_APPROVED
            rec.final_value = rec.student_value
            rec.staff_reviewed_at = now
            rec.reviewed_by = actor.username
            rec.staff_comment = staff_comment

            rec.history.append(
                VerificationHistoryEntry(
                    actor=actor.username,
                    actor_role=actor.role.value if hasattr(actor.role, "value") else str(actor.role),
                    action="STAFF_APPROVE",
                    old_value=rec.ai_value,
                    new_value=rec.student_value,
                    comment=staff_comment,
                    document_version_id=rec.document_version_id,
                    timestamp=now,
                )
            )

        elif act_upper == "REJECT":
            rec.status = VerificationFieldStatus.STAFF_REJECTED
            rec.final_value = rec.ai_value
            rec.staff_reviewed_at = now
            rec.reviewed_by = actor.username
            rec.staff_comment = staff_comment

            rec.history.append(
                VerificationHistoryEntry(
                    actor=actor.username,
                    actor_role=actor.role.value if hasattr(actor.role, "value") else str(actor.role),
                    action="STAFF_REJECT",
                    old_value=rec.student_value,
                    new_value=rec.ai_value,
                    comment=staff_comment,
                    document_version_id=rec.document_version_id,
                    timestamp=now,
                )
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid review action: '{action}'. Must be APPROVE or REJECT.",
            )

        saved = await self.repository.save_record(rec)

        # Audit Log
        actor_id = str(actor.id) if hasattr(actor, "id") and actor.id else "staff"
        try:
            audit = AuditLog(
                action=f"STAFF_REVIEW_CORRECTION_{act_upper}",
                actor_user_id=actor_id,
                actor_username=actor.username,
                actor_role=actor.role.value if hasattr(actor.role, "value") else str(actor.role),
                submission_id=str(rec.document_id or rec.student_id),
                student_name=f"Student_{rec.student_id}",
                register_number=str(rec.student_id),
                batch_id=rec.batch_id,
                class_id=rec.class_id,
                documents_count=1,
                result="SUCCESS",
                failure_info=f"Field: {rec.field_name} | Action: {act_upper} | Final: {rec.final_value}",
            )
            await audit.insert()
        except Exception:
            pass

        return saved

    async def get_final_verified_data_for_student(
        self, student_id: str
    ) -> Dict[str, Any]:
        """
        Retrieve final verified values for export/reporting:
        - STAFF_APPROVED: final_value = student_value
        - STUDENT_CONFIRMED: final_value = ai_value
        - STAFF_REJECTED: final_value = ai_value
        - CORRECTION_REQUESTED / AI_EXTRACTED: omitted from final approved data
        """
        records = await self.repository.get_verified_fields_for_student(student_id)
        verified_data: Dict[str, Any] = {}
        for r in records:
            if r.status in (
                VerificationFieldStatus.STAFF_APPROVED,
                VerificationFieldStatus.STUDENT_CONFIRMED,
                VerificationFieldStatus.STUDENT_VERIFIED,
                VerificationFieldStatus.STAFF_REJECTED,
            ) and r.final_value is not None:
                # Most recent updated record per field_name wins
                if r.field_name not in verified_data:
                    verified_data[r.field_name] = r.final_value

        return verified_data

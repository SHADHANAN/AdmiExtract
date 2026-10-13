from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.dependencies import get_current_user, RoleChecker
from app.models.user import User, UserRole
from app.models.document_verification import (
    DocumentFieldVerification,
    VerificationFieldStatus,
    VerificationHistoryEntry,
)
from app.schemas.document_verification import (
    DocumentFieldVerificationResponse,
    VerificationHistoryEntryResponse,
    StudentVerificationSubmitRequest,
    StaffReviewCorrectionRequest,
)
from app.services.document_verification_service import DocumentVerificationService

router = APIRouter(tags=["Document Verification & Approval"])
service = DocumentVerificationService()


def _to_history_response(h: VerificationHistoryEntry) -> VerificationHistoryEntryResponse:
    return VerificationHistoryEntryResponse(
        entry_id=h.entry_id,
        actor=h.actor,
        actor_role=h.actor_role,
        action=h.action,
        old_value=h.old_value,
        new_value=h.new_value,
        comment=h.comment,
        document_version_id=h.document_version_id,
        timestamp=h.timestamp,
    )


def _to_verification_response(r: DocumentFieldVerification) -> DocumentFieldVerificationResponse:
    display_ai = None if r.ai_value in ("NOT_AVAILABLE", "NOT_FOUND", None) else r.ai_value
    display_raw = None if r.raw_value in ("NOT_AVAILABLE", "NOT_FOUND", None) else r.raw_value
    display_state = r.field_state
    if display_state == "EXTRACTED" and display_ai is None:
        display_state = "NOT_FOUND"

    return DocumentFieldVerificationResponse(
        id=str(r.id),
        extraction_result_id=r.extraction_result_id,
        extraction_request_id=r.extraction_request_id,
        student_id=r.student_id,
        document_id=r.document_id,
        document_version_id=r.document_version_id,
        department_id=r.department_id,
        batch_id=r.batch_id,
        class_id=r.class_id,
        document_type=r.document_type,
        source_document_name=r.source_document_name,
        field_name=r.field_name,
        ai_value=display_ai,
        raw_value=display_raw,
        student_value=r.student_value,
        final_value=r.final_value,
        status=r.status.value if isinstance(r.status, VerificationFieldStatus) else str(r.status),
        confidence=r.confidence,
        confidence_score=r.confidence_score,
        field_state=display_state,
        evidence_snippet=r.evidence_snippet,
        page_number=r.page_number,
        reason=r.reason,
        student_updated_at=r.student_updated_at,
        staff_reviewed_at=r.staff_reviewed_at,
        reviewed_by=r.reviewed_by,
        staff_comment=r.staff_comment,
        student_comment=r.student_comment,
        history=[_to_history_response(h) for h in r.history],
        created_at=r.created_at,
        updated_at=r.updated_at,
    )


# ==========================================
# STUDENT VERIFICATION ENDPOINTS
# ==========================================

@router.get(
    "/student/verifications",
    response_model=List[DocumentFieldVerificationResponse],
    dependencies=[
        Depends(
            RoleChecker(
                [
                    UserRole.STUDENT,
                    UserRole.SUPER_ADMIN,
                    UserRole.DEPARTMENT_ADMIN,
                ]
            )
        )
    ],
)
async def get_student_verifications(
    student_id: Optional[str] = None,
    batch_id: Optional[str] = Query(None),
    extraction_request_id: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
):
    """
    Retrieve verification records for the current student.
    Students can only view their own records; Staff may supply student_id.
    """
    eff_student_id = student_id if (student_id and current_user.role != UserRole.STUDENT) else (current_user.register_number or current_user.username)
    records = await service.get_student_verifications(
        student_id=eff_student_id,
        actor=current_user,
        batch_id=batch_id,
        extraction_request_id=extraction_request_id,
    )
    return [_to_verification_response(r) for r in records]


@router.get(
    "/student/verifications/{document_id}",
    response_model=List[DocumentFieldVerificationResponse],
    dependencies=[
        Depends(
            RoleChecker(
                [
                    UserRole.STUDENT,
                    UserRole.SUPER_ADMIN,
                    UserRole.DEPARTMENT_ADMIN,
                ]
            )
        )
    ],
)
async def get_student_document_verifications(
    document_id: str,
    student_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
):
    """
    Retrieve verification records for a specific document belonging to the student.
    """
    eff_student_id = student_id if (student_id and current_user.role != UserRole.STUDENT) else (current_user.register_number or current_user.username)
    records = await service.get_student_verifications(
        student_id=eff_student_id,
        actor=current_user,
        document_id=document_id,
    )
    return [_to_verification_response(r) for r in records]


@router.post(
    "/student/verifications",
    response_model=List[DocumentFieldVerificationResponse],
    dependencies=[
        Depends(
            RoleChecker(
                [
                    UserRole.STUDENT,
                    UserRole.SUPER_ADMIN,
                    UserRole.DEPARTMENT_ADMIN,
                ]
            )
        )
    ],
)
async def submit_student_verification(
    req: StudentVerificationSubmitRequest,
    student_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
):
    """
    Submit student verification responses:
    - Confirmed fields become STUDENT_CONFIRMED (final_value = ai_value)
    - Corrected fields become CORRECTION_REQUESTED (pending staff review)
    - ai_value is never destroyed.
    """
    eff_student_id = student_id if (student_id and current_user.role != UserRole.STUDENT) else (current_user.register_number or current_user.username)
    updated = await service.submit_student_verification(
        student_id=eff_student_id,
        submit_req=req,
        actor=current_user,
    )
    return [_to_verification_response(r) for r in updated]


# ==========================================
# PUBLIC VERIFICATION TOKEN ENDPOINTS
# ==========================================
from app.schemas.verification_token import (
    PublicVerificationTokenResponse,
    PublicVerificationSubmitRequest,
    PublicVerificationSessionResponse,
    ValidateStudentIdentityRequest,
    GenerateVerificationTokenRequest,
    GenerateVerificationTokenResponse,
    CommonStudentIdentifyRequest,
    CommonStudentIdentifyResponse,
    CommonStudentVerifyCodeRequest,
    CommonStudentSubmitRequest,
    CommonStudentResendCodeRequest,
    CommonStudentResendCodeResponse,
)
from app.services.verification_token_service import VerificationTokenService

token_service = VerificationTokenService()


# ==========================================
# COMMON PUBLIC STUDENT VERIFICATION ENDPOINTS
# ==========================================

@router.post(
    "/public/student-verification/identify",
    response_model=CommonStudentIdentifyResponse,
)
async def identify_common_student(req: CommonStudentIdentifyRequest):
    """
    Public endpoint: Identify student using Student Name + Register Number on the Common Verification URL.
    Safely resolves duplicates across batches, applies brute-force rate limits, and issues a 6-digit one-time code.
    """
    return await token_service.identify_common_student(req)


@router.post(
    "/public/student-verification/resend-code",
    response_model=CommonStudentResendCodeResponse,
)
async def resend_common_code(req: CommonStudentResendCodeRequest):
    """
    Public endpoint: Resend a 6-digit verification code with cooldown and rate-limiting enforcement.
    """
    return await token_service.resend_common_code(req)


@router.post(
    "/public/student-verification/verify-code",
    response_model=PublicVerificationTokenResponse,
)
async def verify_common_code(req: CommonStudentVerifyCodeRequest):
    """
    Public endpoint: Verify 6-digit one-time code and return only the authenticated student's extraction fields.
    """
    return await token_service.verify_common_code(req)


@router.post(
    "/public/student-verification/submit",
    response_model=PublicVerificationTokenResponse,
)
async def submit_common_verification(req: CommonStudentSubmitRequest):
    """
    Public endpoint: Submit confirmations and corrections for the verified student session.
    """
    return await token_service.submit_common_verification(req)


@router.get(
    "/public/verification/{token}/session",
    response_model=PublicVerificationSessionResponse,
)
async def get_public_verification_session(token: str):
    """
    Public endpoint: Retrieve session metadata (validity, expiry, batch name)
    without exposing student identity or extraction results.
    """
    return await token_service.get_session_info(token)


@router.post(
    "/public/verification/{token}/validate-identity",
    response_model=PublicVerificationTokenResponse,
)
async def validate_public_verification_identity(
    token: str,
    req: ValidateStudentIdentityRequest,
):
    """
    Public endpoint: Authenticate student identity using full name and register number
    under rate limiting and brute force protection before revealing extraction records.
    """
    return await token_service.validate_student_identity(
        token_str=token,
        student_name=req.student_name,
        register_number=req.register_number,
    )


@router.get(
    "/public/verification/{token}",
    response_model=PublicVerificationTokenResponse,
)
async def get_public_verification(
    token: str,
    student_name: Optional[str] = Query(None),
    register_number: Optional[str] = Query(None),
):
    """
    Public endpoint: Retrieve document extraction verification records for a student
    using a secure, time-limited verification token.
    If student_name and register_number are provided, identity validation is applied.
    """
    if student_name is not None and register_number is not None:
        return await token_service.validate_student_identity(
            token_str=token,
            student_name=student_name,
            register_number=register_number,
        )
    return await token_service.get_public_verification_data(token)


@router.post(
    "/public/verification/{token}/submit",
    response_model=PublicVerificationTokenResponse,
)
async def submit_public_verification(
    token: str,
    req: PublicVerificationSubmitRequest,
):
    """
    Public endpoint: Submit student confirmations and corrections via verification token.
    Enforces strict token scoping and records immutable audit history.
    """
    return await token_service.submit_public_verification(token, req)


@router.post(
    "/public/verification/{token}/confirm",
    response_model=PublicVerificationTokenResponse,
)
async def confirm_public_verification(
    token: str,
    req: PublicVerificationSubmitRequest,
):
    """
    Public endpoint alias: Confirm student verification data via verification token.
    """
    return await token_service.submit_public_verification(token, req)


@router.post(
    "/public/verification/{token}/correction",
    response_model=PublicVerificationTokenResponse,
)
async def correction_public_verification(
    token: str,
    req: PublicVerificationSubmitRequest,
):
    """
    Public endpoint alias: Submit corrections via verification token.
    """
    return await token_service.submit_public_verification(token, req)


# ==========================================
# STAFF REVIEW & APPROVAL ENDPOINTS
# ==========================================

@router.post(
    "/staff/verifications/generate-token",
    response_model=GenerateVerificationTokenResponse,
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
async def generate_verification_token(
    req: GenerateVerificationTokenRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Staff endpoint to generate or retrieve a shareable verification link for a student.
    """
    token_doc = await token_service.create_or_get_token(
        student_id=req.student_id,
        batch_id=req.batch_id,
        student_name=req.student_name,
        extraction_request_id=req.extraction_request_id,
        class_id=req.class_id,
        department_id=req.department_id,
        expires_in_days=req.expires_in_days or 7,
        force_refresh=req.force_refresh,
    )
    return GenerateVerificationTokenResponse(
        token=token_doc.token,
        student_id=token_doc.student_id,
        student_name=token_doc.student_name,
        batch_id=token_doc.batch_id,
        extraction_request_id=token_doc.extraction_request_id,
        verification_url=f"/verify-session/{token_doc.token}",
        status=token_doc.status,
        expires_at=token_doc.expires_at,
    )



@router.get(
    "/staff/verifications/pending",
    response_model=List[DocumentFieldVerificationResponse],
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
async def list_pending_corrections(
    batch_id: Optional[str] = Query(None),
    class_id: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
):
    """
    List all pending student corrections (status == CORRECTION_REQUESTED)
    subject to department and section isolation.
    """
    records = await service.list_pending_corrections(
        actor=current_user,
        batch_id=batch_id,
        class_id=class_id,
    )
    return [_to_verification_response(r) for r in records]


@router.get(
    "/staff/verifications/{student_id}",
    response_model=List[DocumentFieldVerificationResponse],
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
async def get_student_verification_history(
    student_id: str,
    current_user: User = Depends(get_current_user),
):
    """
    Retrieve full verification history for a student.
    """
    records = await service.get_student_verifications(
        student_id=student_id,
        actor=current_user,
    )
    return [_to_verification_response(r) for r in records]


@router.post(
    "/staff/verifications/{verification_id}/review",
    response_model=DocumentFieldVerificationResponse,
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
async def review_correction(
    verification_id: str,
    req: StaffReviewCorrectionRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Approve or reject a student correction request:
    - APPROVE -> final_value = student_value, status = STAFF_APPROVED
    - REJECT  -> final_value = ai_value, status = STAFF_REJECTED
    """
    updated = await service.review_correction(
        verification_id=verification_id,
        action=req.action,
        actor=current_user,
        staff_comment=req.staff_comment,
    )
    return _to_verification_response(updated)

import io
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form, status, Response
from fastapi.responses import StreamingResponse

from app.core.dependencies import get_current_user, RoleChecker
from app.models.user import User, UserRole
from app.schemas.batch_extraction import (
    TemplatePreviewResponse,
    CreateBatchExtractionRequest,
    BatchExtractionSummaryResponse,
    BatchExtractionStatsResponse,
    BatchExtractionDetailResponse,
    StudentExtractionRowResponse,
    CorrectionQueueItem,
)
from app.schemas.document_verification import (
    StudentVerificationSubmitRequest,
    StaffReviewCorrectionRequest,
    DocumentFieldVerificationResponse,
)
from app.services.batch_extraction_service import BatchExtractionService
from app.services.document_verification_service import DocumentVerificationService
from app.services.document_extraction_service import resolve_canonical_field_key

router = APIRouter(prefix="/data-extractions", tags=["Data Extraction Module"])
service = BatchExtractionService()
verif_service = DocumentVerificationService()


@router.get(
    "/batches",
    response_model=List[BatchExtractionStatsResponse],
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
async def list_authorized_batches(
    current_user: User = Depends(get_current_user),
):
    """
    List all admission batches authorized for the staff user with high-level
    data extraction statistics.
    """
    return await service.list_authorized_batches(actor=current_user)


@router.get(
    "/batches/{batch_id}",
    response_model=BatchExtractionStatsResponse,
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
async def get_batch_extraction_overview(
    batch_id: str,
    current_user: User = Depends(get_current_user),
):
    """
    Get extraction stats and overview for a specific admission batch.
    """
    return await service.get_batch_extraction_overview(batch_id=batch_id, actor=current_user)


@router.get(
    "/batches/{batch_id}/history",
    response_model=List[BatchExtractionSummaryResponse],
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
async def list_batch_extractions_history(
    batch_id: str,
    current_user: User = Depends(get_current_user),
):
    """
    List all historical extraction requests for a specific batch in reverse chronological order.
    """
    return await service.list_batch_extractions_history(batch_id=batch_id, actor=current_user)


@router.post(
    "/template-preview",
    response_model=TemplatePreviewResponse,
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
async def preview_excel_template(
    file: UploadFile = File(...),
    batch_id: Optional[str] = Form(None),
    class_id: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
):
    """
    Upload and parse an Excel field template to preview required output columns.
    If batch_id is provided, permanently saves the template and persists column metadata.
    """
    content = await file.read()
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty.",
        )
    return await service.parse_and_store_excel_template(
        file_content=content,
        filename=file.filename or "template.xlsx",
        batch_id=batch_id,
        class_id=class_id,
        department_id=current_user.department_code,
        uploaded_by=current_user.username,
    )


@router.get(
    "/batches/{batch_id}/template",
    response_model=Optional[TemplatePreviewResponse],
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
async def get_batch_template(
    batch_id: str,
    class_id: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
):
    """
    Retrieve the active Excel template configuration for an admission batch.
    """
    tmpl = await service.excel_template_service.get_template_by_batch(batch_id, class_id)
    if not tmpl:
        return None

    canonical_fields: List[str] = []
    column_mapping: Dict[str, str] = {}
    seen = set()
    for h in tmpl.headers:
        c_key = resolve_canonical_field_key(h) or h.strip().lower().replace(" ", "_")
        column_mapping[h] = c_key
        if c_key not in seen:
            canonical_fields.append(c_key)
            seen.add(c_key)

    return TemplatePreviewResponse(
        template_id=str(tmpl.id),
        template_filename=tmpl.template_filename,
        sheet_name=tmpl.sheet_name,
        sheet_names=tmpl.sheet_names or [tmpl.sheet_name],
        header_row_index=tmpl.header_row_index,
        requested_columns=tmpl.headers,
        canonical_fields=canonical_fields,
        column_mapping=column_mapping,
        column_indices=tmpl.column_indices or {h: idx for idx, h in enumerate(tmpl.headers, 1)},
        detected_students_count=tmpl.total_rows,
        sample_rows=[],
    )


@router.delete(
    "/batches/{batch_id}/template",
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
async def delete_batch_template(
    batch_id: str,
    class_id: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
):
    """
    Delete the active Excel template for a batch.
    """
    deleted = await service.excel_template_service.delete_template(batch_id, class_id)
    return {"deleted": deleted}


@router.post(
    "/batches/{batch_id}/extract",
    response_model=BatchExtractionSummaryResponse,
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
async def create_batch_extraction(
    batch_id: str,
    req: CreateBatchExtractionRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Trigger a new on-demand data extraction for a batch reusing stored documents.
    Does NOT require students to re-upload documents.
    """
    return await service.create_and_run_batch_extraction(
        batch_id=batch_id,
        requested_columns=req.requested_columns,
        requested_fields=req.requested_fields,
        actor=current_user,
        column_mapping=req.column_mapping,
        template_filename=req.template_filename,
        class_id=req.class_id,
    )


@router.get(
    "/requests/{extraction_request_id}",
    response_model=BatchExtractionDetailResponse,
    dependencies=[
        Depends(
            RoleChecker(
                [
                    UserRole.SUPER_ADMIN,
                    UserRole.DEPARTMENT_ADMIN,
                    UserRole.STUDENT,
                ]
            )
        )
    ],
)
async def get_extraction_details(
    extraction_request_id: str,
    status_filter: Optional[str] = Query("ALL", alias="status_filter"),
    search: Optional[str] = Query(None, alias="search"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    current_user: User = Depends(get_current_user),
):
    """
    Retrieve full details of an extraction request, including per-student extraction rows
    and verification progress. Supports status filtering, search by name/reg no, and pagination.
    """
    return await service.get_extraction_details(
        extraction_request_id=extraction_request_id,
        actor=current_user,
        status_filter=status_filter,
        search=search,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/requests/{extraction_request_id}/retry-student/{student_id}",
    response_model=StudentExtractionRowResponse,
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
async def retry_student_extraction(
    extraction_request_id: str,
    student_id: str,
    current_user: User = Depends(get_current_user),
):
    """
    Retry extraction for a specific student without creating duplicate results or deleting stored documents.
    """
    return await service.retry_student_extraction(
        extraction_request_id=extraction_request_id,
        student_id=student_id,
        actor=current_user,
    )


@router.post(
    "/requests/{extraction_request_id}/cancel",
    response_model=BatchExtractionSummaryResponse,
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
async def cancel_batch_extraction(
    extraction_request_id: str,
    current_user: User = Depends(get_current_user),
):
    """
    Safely cancel a batch extraction request. Source documents and previous extractions remain untouched.
    """
    return await service.cancel_batch_extraction(
        extraction_request_id=extraction_request_id,
        actor=current_user,
    )


@router.get(
    "/requests/{extraction_request_id}/corrections",
    response_model=List[CorrectionQueueItem],
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
async def get_extraction_corrections_queue(
    extraction_request_id: str,
    current_user: User = Depends(get_current_user),
):
    """
    Get all pending corrections requested by students for this extraction request.
    """
    return await service.get_corrections_queue(
        extraction_request_id=extraction_request_id,
        actor=current_user,
    )


@router.get(
    "/requests/{extraction_request_id}/student/{student_id}",
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
async def get_student_extraction_verification(
    extraction_request_id: str,
    student_id: str,
    current_user: User = Depends(get_current_user),
):
    """
    Student verification view: retrieves extracted field values for the student to confirm or correct.
    """
    verif_service.verify_student_ownership(student_id, current_user)

    req = await service.repository.get_by_request_id(extraction_request_id)
    if not req:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Extraction request '{extraction_request_id}' not found.",
        )

    records = await verif_service.repository.get_by_student_id(student_id)
    req_records = [r for r in records if r.extraction_request_id == extraction_request_id]

    return {
        "extraction_request_id": req.extraction_request_id,
        "batch_name": req.batch_name,
        "academic_year": req.academic_year,
        "title": f"Batch {req.batch_name or req.batch_id} — Student Data Verification",
        "student_id": student_id,
        "fields": [
            {
                "verification_id": str(r.id),
                "field_name": r.field_name,
                "display_label": r.field_name.replace("_", " ").title(),
                "ai_value": r.ai_value,
                "student_value": r.student_value,
                "final_value": r.final_value,
                "status": r.status.value if hasattr(r.status, "value") else str(r.status),
                "is_available": (r.ai_value != "NOT_AVAILABLE"),
            }
            for r in req_records
        ],
    }


@router.post(
    "/requests/{extraction_request_id}/student/{student_id}/verify",
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
async def submit_student_extraction_verification(
    extraction_request_id: str,
    student_id: str,
    submit_req: StudentVerificationSubmitRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Submit student confirmation or requested corrections for an extraction request.
    - Confirmed fields become STUDENT_CONFIRMED.
    - Edited fields become CORRECTION_REQUESTED (AI value is strictly preserved).
    """
    verif_service.verify_student_ownership(student_id, current_user)
    updated = await verif_service.submit_student_verification(
        student_id=student_id,
        submit_req=submit_req,
        actor=current_user,
    )
    return {"message": "Verification submitted successfully", "updated_count": len(updated)}


@router.post(
    "/requests/{extraction_request_id}/review/{verification_id}",
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
async def review_student_correction(
    extraction_request_id: str,
    verification_id: str,
    req: StaffReviewCorrectionRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Staff review of student correction:
    - APPROVE -> final_value = student_value, status = STAFF_APPROVED
    - REJECT  -> final_value = ai_value, status = STAFF_REJECTED
    """
    updated = await verif_service.review_correction(
        verification_id=verification_id,
        action=req.action,
        actor=current_user,
        staff_comment=req.staff_comment,
    )
    return DocumentFieldVerificationResponse(
        id=str(updated.id),
        extraction_result_id=updated.extraction_result_id,
        extraction_request_id=updated.extraction_request_id,
        student_id=updated.student_id,
        document_id=updated.document_id,
        document_version_id=updated.document_version_id,
        department_id=updated.department_id,
        batch_id=updated.batch_id,
        class_id=updated.class_id,
        document_type=updated.document_type,
        source_document_name=updated.source_document_name,
        field_name=updated.field_name,
        ai_value=None if updated.ai_value in ("NOT_AVAILABLE", "NOT_FOUND", None) else updated.ai_value,
        raw_value=None if updated.raw_value in ("NOT_AVAILABLE", "NOT_FOUND", None) else updated.raw_value,
        student_value=updated.student_value,
        final_value=updated.final_value,
        status=updated.status.value if hasattr(updated.status, "value") else str(updated.status),
        confidence=updated.confidence,
        confidence_score=updated.confidence_score,
        field_state=updated.field_state,
        evidence_snippet=updated.evidence_snippet,
        page_number=updated.page_number,
        reason=updated.reason,
        student_updated_at=updated.student_updated_at,
        staff_reviewed_at=updated.staff_reviewed_at,
        reviewed_by=updated.reviewed_by,
        staff_comment=updated.staff_comment,
        student_comment=updated.student_comment,
        history=[],
        created_at=updated.created_at,
        updated_at=updated.updated_at,
    )


@router.get(
    "/requests/{extraction_request_id}/export",
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
async def export_verified_excel(
    extraction_request_id: str,
    enforce_all_verified: bool = Query(True),
    current_user: User = Depends(get_current_user),
):
    """
    Download Excel of FINAL VERIFIED DATA preserving the exact requested column structure.
    Downloading does NOT delete or consume stored source documents.
    """
    # Direct API requests must not bypass the all-students-verification requirement
    stream, filename = await service.export_verified_excel(
        extraction_request_id=extraction_request_id,
        actor=current_user,
        enforce_all_verified=True,
    )
    content = stream.getvalue() if hasattr(stream, "getvalue") else stream.read()
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(content)),
            "Access-Control-Expose-Headers": "Content-Disposition",
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@router.get(
    "/diagnostics",
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
async def get_extraction_diagnostics(
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Staff-only diagnostic endpoint showing provider readiness and health without exposing secrets.
    """
    import os
    from app.core.config import settings
    from app.services.gemini_service import GeminiService

    mistral_key_configured = bool(os.getenv("MISTRAL_API_KEY") or getattr(settings, "MISTRAL_API_KEY", None))
    gemini_key_configured = bool(os.getenv("GEMINI_API_KEY") or getattr(settings, "GEMINI_API_KEY", None))

    # Real Gemini availability check
    gemini_svc = GeminiService()
    gemini_is_available = gemini_svc.is_available()
    gemini_unavailability_reason = gemini_svc.get_unavailability_reason()

    if gemini_is_available:
        gemini_status = "READY"
    elif not gemini_key_configured:
        gemini_status = "FAILED_NO_KEY"
    elif getattr(gemini_svc, "_genai_package_missing", False):
        gemini_status = "FAILED_PACKAGE_NOT_INSTALLED"
    else:
        gemini_status = "FAILED_INIT_ERROR"

    # Real Mistral/OCR package check
    mistral_package_ok = False
    try:
        import mistralai  # noqa: F401
        mistral_package_ok = True
    except ImportError:
        pass

    if mistral_key_configured and mistral_package_ok:
        ocr_status = "READY"
    elif not mistral_key_configured:
        ocr_status = "FALLBACK_LOCAL_ONLY"
    else:
        ocr_status = "FAILED_PACKAGE_NOT_INSTALLED"

    upload_dir = str(getattr(settings, "UPLOAD_DIR", "uploads"))
    upload_dir_abs = upload_dir if os.path.isabs(upload_dir) else os.path.join(os.getcwd(), upload_dir)

    return {
        "ocr_provider": {
            "name": "Mistral OCR + Local High-Accuracy Fallback",
            "api_key_configured": mistral_key_configured,
            "package_installed": mistral_package_ok,
            "status": ocr_status,
            "supported_formats": [".pdf", ".png", ".jpg", ".jpeg"],
            "fallback_available": True,
        },
        "gemini_provider": {
            "name": "Google Gemini Multimodal AI",
            "api_key_configured": gemini_key_configured,
            "package_installed": not getattr(gemini_svc, "_genai_package_missing", False),
            "client_initialized": gemini_is_available,
            "status": gemini_status,
            "unavailability_reason": gemini_unavailability_reason,
            "primary_model": getattr(settings, "GEMINI_MODEL", "gemini-flash-lite-latest"),
            "fallback_models": ["gemini-3.1-flash-lite", "gemini-flash-lite-latest", "gemini-2.0-flash"],
        },
        "storage": {
            "upload_dir": upload_dir_abs,
            "upload_dir_exists": os.path.isdir(upload_dir_abs),
        },
    }

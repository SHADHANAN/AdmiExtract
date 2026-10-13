from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from app.core.dependencies import get_current_user, RoleChecker
from app.models.user import User, UserRole
from app.schemas.student_document import (
    StudentDocumentResponse,
    DocumentClassificationResponse,
    ReclassifyDocumentRequest,
    BatchDocumentValidationResponse,
)
from app.api.student_document import get_document_classification, reclassify_student_document
from app.api.batch import get_batch_document_validation, get_batch_service
from app.services.batch_service import BatchService

router = APIRouter(
    prefix="/staff",
    tags=["Staff Document Operations"],
    dependencies=[Depends(RoleChecker([UserRole.SUPER_ADMIN, UserRole.DEPARTMENT_ADMIN]))],
)


@router.get(
    "/documents/{document_id}/classification",
    response_model=DocumentClassificationResponse,
)
async def staff_get_document_classification(
    document_id: str,
    current_user: User = Depends(get_current_user),
):
    """Staff route to retrieve document classification diagnostic details."""
    return await get_document_classification(student_document_id=document_id, current_user=current_user)


@router.post(
    "/documents/{document_id}/reclassify",
    response_model=StudentDocumentResponse,
)
async def staff_reclassify_document(
    document_id: str,
    req: ReclassifyDocumentRequest,
    current_user: User = Depends(get_current_user),
):
    """Staff route to reclassify document with audit history."""
    return await reclassify_student_document(student_document_id=document_id, req=req, current_user=current_user)


@router.get(
    "/batches/{batch_id}/document-validation",
    response_model=BatchDocumentValidationResponse,
)
async def staff_get_batch_document_validation(
    batch_id: str,
    classId: Optional[str] = None,
    class_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    service: BatchService = Depends(get_batch_service),
):
    """Staff route to retrieve batch-level document validation overview and stats."""
    return await get_batch_document_validation(
        batchId=batch_id,
        classId=classId,
        class_id=class_id,
        current_user=current_user,
        service=service,
    )

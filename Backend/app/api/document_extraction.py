from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status

from app.core.dependencies import get_current_user, RoleChecker
from app.models.user import User, UserRole
from app.models.document_extraction_request import (
    DocumentExtractionRequest,
    ExtractionRequestStatus,
)
from app.models.document_extraction_result import DocumentExtractionResult
from app.schemas.document_extraction import (
    ExtractDocumentRequest,
    DocumentExtractionRequestResponse,
    DocumentExtractionResultResponse,
)
from app.services.document_extraction_service import DocumentExtractionService

router = APIRouter(prefix="/document-extractions", tags=["Document Extractions"])
service = DocumentExtractionService()


def to_extraction_response(
    req: DocumentExtractionRequest,
    result: Optional[DocumentExtractionResult] = None,
) -> DocumentExtractionRequestResponse:
    extracted_data = result.extracted_data if result else None
    return DocumentExtractionRequestResponse(
        extraction_request_id=str(req.id),
        student_document_id=req.student_document_id,
        document_version_id=req.document_version_id,
        student_id=req.student_id,
        document_type=req.document_type,
        requested_fields=req.requested_fields,
        status=req.status.value if isinstance(req.status, ExtractionRequestStatus) else str(req.status),
        requested_by=req.requested_by,
        requested_at=req.requested_at,
        started_at=req.started_at,
        completed_at=req.completed_at,
        failed_at=req.failed_at,
        error_message=req.error_message,
        extraction_result_id=req.extraction_result_id,
        extracted_data=extracted_data,
        provenance=result.provenance if result else None,
        ocr_status=result.ocr_status if result else None,
        ai_provider=result.ai_provider if result else None,
    )


@router.get(
    "/{extraction_request_id}",
    response_model=DocumentExtractionRequestResponse,
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
async def get_extraction_result(
    extraction_request_id: str,
    current_user: User = Depends(get_current_user),
):
    """
    Retrieve full details and result of a specific extraction request.
    """
    req, result = await service.get_extraction_details(
        extraction_request_id=extraction_request_id,
        actor=current_user,
    )
    return to_extraction_response(req, result)

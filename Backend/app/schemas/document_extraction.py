from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ExtractDocumentRequest(BaseModel):
    version_id: Optional[str] = Field(
        None,
        description="Specific document version ID to extract from. If omitted, the active version is used.",
    )
    requested_fields: List[str] = Field(
        ...,
        min_length=1,
        description="List of fields requested for extraction from the stored document.",
    )


class DocumentExtractionRequestResponse(BaseModel):
    extraction_request_id: str
    student_document_id: str
    document_version_id: str
    student_id: str
    document_type: str
    requested_fields: List[str]
    status: str
    requested_by: str
    requested_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    failed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    extraction_result_id: Optional[str] = None
    extracted_data: Optional[Dict[str, Any]] = None
    provenance: Optional[str] = None
    ocr_status: Optional[str] = None
    ai_provider: Optional[str] = None


class DocumentExtractionResultResponse(BaseModel):
    id: str
    extraction_request_id: str
    student_document_id: str
    document_version_id: str
    requested_fields: List[str]
    extracted_data: Dict[str, Any]
    validation_results: Optional[Dict[str, Any]] = None
    confidence: Optional[float] = None
    provenance: Optional[str] = None
    ocr_status: Optional[str] = None
    ai_provider: Optional[str] = None
    created_at: datetime

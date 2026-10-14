from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from beanie import Document, PydanticObjectId
from pydantic import Field


class DocumentExtractionResult(Document):
    id: PydanticObjectId = Field(default_factory=PydanticObjectId)
    extraction_request_id: str
    student_submission_id: Optional[str] = None
    student_id: Optional[str] = None
    student_document_id: str
    document_version_id: str
    requested_fields: List[str]
    extracted_data: Dict[str, Any]
    validation_results: Optional[Dict[str, Any]] = None
    confidence: Optional[float] = None
    provenance: Optional[str] = None
    ocr_status: Optional[str] = None
    ai_provider: Optional[str] = None
    pipeline_metadata: Optional[Dict[str, Any]] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "document_extraction_results"
        indexes = [
            "extraction_request_id",
            "student_document_id",
            "document_version_id",
            "student_submission_id",
            "student_id",
            [
                ("extraction_request_id", 1),
                ("student_submission_id", 1),
            ],
            [
                ("extraction_request_id", 1),
                ("student_id", 1),
            ],
        ]

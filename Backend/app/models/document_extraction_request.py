from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional
from beanie import Document, PydanticObjectId
from pydantic import Field


class ExtractionRequestStatus(str, Enum):
    REQUESTED = "REQUESTED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class DocumentExtractionRequest(Document):
    id: PydanticObjectId = Field(default_factory=PydanticObjectId)
    student_document_id: str
    document_version_id: str
    student_id: str
    document_type: str
    requested_fields: List[str]
    status: ExtractionRequestStatus = ExtractionRequestStatus.REQUESTED
    requested_by: str
    requested_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    failed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    extraction_result_id: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "document_extraction_requests"
        indexes = [
            "student_document_id",
            "document_version_id",
            "student_id",
            "status",
            "extraction_result_id",
            [
                ("student_id", 1),
                ("document_type", 1),
            ],
        ]

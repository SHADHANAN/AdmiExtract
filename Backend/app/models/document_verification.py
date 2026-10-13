from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from beanie import Document, PydanticObjectId
from pydantic import BaseModel, Field


class VerificationFieldStatus(str, Enum):
    AI_EXTRACTED = "AI_EXTRACTED"
    STUDENT_CONFIRMED = "STUDENT_CONFIRMED"
    STUDENT_VERIFIED = "STUDENT_VERIFIED"
    CORRECTION_REQUESTED = "CORRECTION_REQUESTED"
    STAFF_APPROVED = "STAFF_APPROVED"
    STAFF_REJECTED = "STAFF_REJECTED"


class VerificationHistoryEntry(BaseModel):
    entry_id: str = Field(default_factory=lambda: PydanticObjectId().__str__())
    actor: str
    actor_role: str
    action: str  # "AI_EXTRACTION", "STUDENT_CONFIRM", "STUDENT_CORRECTION", "STAFF_APPROVE", "STAFF_REJECT"
    old_value: Optional[Any] = None
    new_value: Optional[Any] = None
    comment: Optional[str] = None
    document_version_id: Optional[str] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DocumentFieldVerification(Document):
    id: PydanticObjectId = Field(default_factory=PydanticObjectId)
    extraction_result_id: str = Field(default_factory=lambda: f"res_{PydanticObjectId().__str__()}")
    extraction_request_id: Optional[str] = None
    student_id: str
    student_submission_id: Optional[str] = None
    document_id: str = Field(default="doc_default")
    document_version_id: str = Field(default="v1")
    department_id: Optional[str] = None
    batch_id: Optional[str] = None
    class_id: Optional[str] = None
    document_type: str = "OTHER"
    source_document_name: Optional[str] = None
    field_name: str
    ai_value: Optional[Any] = None
    raw_value: Optional[Any] = None
    student_value: Optional[Any] = None
    final_value: Optional[Any] = None
    status: VerificationFieldStatus = VerificationFieldStatus.AI_EXTRACTED
    confidence: str = "HIGH"
    confidence_score: float = 1.0
    field_state: str = "EXTRACTED"
    evidence_snippet: Optional[str] = None
    page_number: Optional[int] = None
    reason: Optional[str] = None
    conflicts: Optional[List[Dict[str, Any]]] = None
    student_updated_at: Optional[datetime] = None
    staff_reviewed_at: Optional[datetime] = None
    reviewed_by: Optional[str] = None
    staff_comment: Optional[str] = None
    student_comment: Optional[str] = None
    history: List[VerificationHistoryEntry] = []
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "document_field_verifications"
        indexes = [
            "extraction_result_id",
            "extraction_request_id",
            "student_id",
            "student_submission_id",
            "document_id",
            "document_version_id",
            "status",
            "department_id",
            "batch_id",
            "class_id",
            [
                ("extraction_request_id", 1),
                ("student_id", 1),
                ("field_name", 1),
            ],
            [
                ("extraction_request_id", 1),
                ("student_submission_id", 1),
                ("field_name", 1),
            ],
            [
                ("student_id", 1),
                ("field_name", 1),
            ],
            [
                ("status", 1),
                ("department_id", 1),
            ],
            [
                ("document_id", 1),
                ("document_version_id", 1),
            ],
        ]

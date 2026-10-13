from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class VerificationHistoryEntryResponse(BaseModel):
    entry_id: str
    actor: str
    actor_role: str
    action: str
    old_value: Optional[Any] = None
    new_value: Optional[Any] = None
    comment: Optional[str] = None
    document_version_id: Optional[str] = None
    timestamp: datetime


class DocumentFieldVerificationResponse(BaseModel):
    id: str
    extraction_result_id: str
    extraction_request_id: Optional[str] = None
    student_id: str
    document_id: str
    document_version_id: str
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
    status: str
    confidence: Optional[str] = None
    confidence_score: Optional[float] = None
    field_state: Optional[str] = None
    evidence_snippet: Optional[str] = None
    page_number: Optional[int] = None
    reason: Optional[str] = None
    student_updated_at: Optional[datetime] = None
    staff_reviewed_at: Optional[datetime] = None
    reviewed_by: Optional[str] = None
    staff_comment: Optional[str] = None
    student_comment: Optional[str] = None
    history: List[VerificationHistoryEntryResponse] = []
    created_at: datetime
    updated_at: datetime


class StudentFieldVerificationItem(BaseModel):
    verification_id: str
    is_confirmed: bool = False
    corrected_value: Optional[Any] = None
    comment: Optional[str] = None


class StudentVerificationSubmitRequest(BaseModel):
    fields: List[StudentFieldVerificationItem] = Field(
        ..., min_length=1, description="List of field verification responses from student"
    )
    general_comment: Optional[str] = None


class StaffReviewCorrectionRequest(BaseModel):
    action: str = Field(..., pattern="^(APPROVE|REJECT)$", description="Review action: APPROVE or REJECT")
    staff_comment: Optional[str] = None

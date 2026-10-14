from datetime import datetime
from typing import Any, List, Optional
from pydantic import BaseModel, Field


class DocumentVersionResponse(BaseModel):
    version_id: str
    version_number: int
    file_path: str
    original_filename: str
    file_size_bytes: int = 0
    mime_type: str = "application/pdf"
    uploaded_at: datetime
    uploaded_by: Optional[str] = None
    validation_status: str = "PENDING"
    validation_reason: Optional[str] = None
    expected_document_type: Optional[str] = None
    detected_document_type: Optional[str] = None
    classification_confidence: float = 0.0
    classification_evidence: List[str] = Field(default_factory=list)
    classifier_version: Optional[str] = "v2.0-ai-hybrid"
    classified_at: Optional[datetime] = None
    reclassification_history: List[Any] = Field(default_factory=list)
    is_active: bool = True
    extraction_reference: Optional[Any] = None
    created_at: datetime


class StudentDocumentResponse(BaseModel):
    id: str
    student_id: str
    batch_id: str
    class_id: Optional[str] = None
    section_id: Optional[str] = None
    department_id: Optional[str] = None
    document_type: str
    document_name: str
    expected_document_type: Optional[str] = None
    detected_document_type: Optional[str] = None
    classification_confidence: float = 0.0
    classification_evidence: List[str] = Field(default_factory=list)
    reclassification_history: List[Any] = Field(default_factory=list)
    current_version: int = 1
    active_version_id: Optional[str] = None
    status: str = "UPLOADED"
    active_version: Optional[DocumentVersionResponse] = None
    versions: List[DocumentVersionResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class CreateDocumentVersionRequest(BaseModel):
    file_path: str
    original_filename: str
    file_size_bytes: int = 0
    mime_type: str = "application/pdf"
    validation_status: str = "PENDING"
    validation_reason: Optional[str] = None
    expected_document_type: Optional[str] = None
    detected_document_type: Optional[str] = None
    classification_confidence: float = 0.0
    classification_evidence: List[str] = Field(default_factory=list)
    set_active: bool = True
    extraction_reference: Optional[Any] = None


class ReclassifyDocumentRequest(BaseModel):
    document_type: str
    reason: Optional[str] = "Manual staff reclassification"
    version_id: Optional[str] = None


class DocumentClassificationResponse(BaseModel):
    document_id: str
    student_id: str
    student_name: Optional[str] = None
    register_number: Optional[str] = None
    batch_id: Optional[str] = None
    class_id: Optional[str] = None
    department_id: Optional[str] = None
    document_type: str
    document_name: str
    expected_document_type: Optional[str] = None
    detected_document_type: Optional[str] = None
    classification_confidence: float = 0.0
    validation_status: str = "PENDING"
    validation_reason: Optional[str] = None
    classification_evidence: List[str] = Field(default_factory=list)
    classifier_version: Optional[str] = "v2.0-ai-hybrid"
    classified_at: Optional[datetime] = None
    reclassification_history: List[Any] = Field(default_factory=list)
    current_version: int = 1
    active_version_id: Optional[str] = None
    original_filename: Optional[str] = None
    file_path: Optional[str] = None
    file_size_bytes: Optional[int] = 0
    uploaded_at: Optional[datetime] = None


class BatchDocumentValidationItem(BaseModel):
    document_id: str
    student_id: str
    student_name: Optional[str] = None
    register_number: Optional[str] = None
    batch_id: Optional[str] = None
    class_id: Optional[str] = None
    department_id: Optional[str] = None
    document_type: str
    document_name: str
    expected_document_type: Optional[str] = None
    detected_document_type: Optional[str] = None
    classification_confidence: float = 0.0
    validation_status: str = "PENDING"
    validation_reason: Optional[str] = None
    classification_evidence: List[str] = Field(default_factory=list)
    reclassification_history: List[Any] = Field(default_factory=list)
    version_number: int = 1
    active_version_id: Optional[str] = None
    original_filename: Optional[str] = None
    file_path: Optional[str] = None
    uploaded_at: Optional[datetime] = None


class BatchDocumentValidationSummary(BaseModel):
    total_documents: int = 0
    valid: int = 0
    wrong_documents: int = 0
    needs_review: int = 0
    classification_failed: int = 0
    unknown: int = 0


class BatchDocumentValidationResponse(BaseModel):
    batch_id: str
    summary: BatchDocumentValidationSummary
    documents: List[BatchDocumentValidationItem] = Field(default_factory=list)

from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Any, Dict, List, Optional
import uuid


from beanie import Document, Indexed, before_event, Replace, Save
from pydantic import BaseModel, Field


class DocumentStatus(str, Enum):
    UPLOADED = "UPLOADED"
    VALIDATING = "VALIDATING"
    VALID = "VALID"
    INVALID = "INVALID"
    REUPLOAD_REQUESTED = "REUPLOAD_REQUESTED"
    REUPLOADED = "REUPLOADED"
    VERIFIED = "VERIFIED"


class DocumentValidationStatus(str, Enum):
    PENDING = "PENDING"
    VALID = "VALID"
    INVALID = "INVALID"
    WRONG_DOCUMENT = "WRONG_DOCUMENT"
    UNKNOWN = "UNKNOWN"
    CLASSIFICATION_FAILED = "CLASSIFICATION_FAILED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    REQUIRES_REVIEW = "REQUIRES_REVIEW"


class DocumentVersion(BaseModel):
    """
    Immutable version sub-document representing an individual uploaded iteration of a StudentDocument.
    """
    version_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    version_number: int = Field(ge=1)
    file_path: str
    original_filename: str
    file_size_bytes: int = Field(default=0, ge=0)
    mime_type: str = "application/pdf"
    uploaded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    uploaded_by: Optional[str] = None  # Username or ID of the uploader/staff

    # Validation & Classification metadata
    validation_status: str = Field(default=DocumentValidationStatus.PENDING.value)
    validation_reason: Optional[str] = None
    expected_document_type: Optional[str] = None
    detected_document_type: Optional[str] = None
    classification_confidence: float = 0.0
    classification_evidence: List[str] = Field(default_factory=list)
    classifier_version: Optional[str] = "v2.0-ai-hybrid"
    classified_at: Optional[datetime] = None
    reclassification_history: List[Dict[str, Any]] = Field(default_factory=list)

    # OCR metadata
    ocr_text: Optional[str] = None
    ocr_provider: Optional[str] = None
    ocr_status: Optional[str] = None
    ocr_confidence: Optional[float] = None
    ocr_completed_at: Optional[datetime] = None

    is_active: bool = True
    extraction_reference: Optional[Any] = None  # Reference ID or metadata to extraction result if available
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class StudentDocument(Document):
    """
    Independent Beanie Document model representing a student's managed document record
    with immutable multi-version history.
    """
    student_id: Annotated[str, Indexed()]
    submission_id: Annotated[Optional[str], Indexed()] = None
    batch_id: Annotated[str, Indexed()]
    class_id: Annotated[Optional[str], Indexed()] = None
    section_id: Optional[str] = None  # Alias / section identifier
    department_id: Optional[str] = None
    document_type: Annotated[str, Indexed()]  # Canonical type: AADHAAR, SSLC, etc.
    document_name: str  # Display name, e.g. "Aadhaar Card"

    # Document classification state
    expected_document_type: Optional[str] = None
    detected_document_type: Optional[str] = None
    classification_confidence: float = 0.0
    classification_evidence: List[str] = Field(default_factory=list)
    reclassification_history: List[Dict[str, Any]] = Field(default_factory=list)

    current_version: int = Field(default=1, ge=1)
    active_version_id: Optional[str] = None
    status: str = Field(default=DocumentStatus.UPLOADED.value)

    # Immutable historical versions
    versions: List[DocumentVersion] = Field(default_factory=list)

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @before_event(Replace, Save)
    def update_timestamp(self):
        """Automatically update updated_at timestamp on save."""
        self.updated_at = datetime.now(timezone.utc)

    @property
    def active_version(self) -> Optional[DocumentVersion]:
        """Convenience property to access the currently active version."""
        if not self.versions:
            return None
        if self.active_version_id:
            for v in self.versions:
                if v.version_id == self.active_version_id and v.is_active:
                    return v
        # Fallback to the latest version marked is_active
        for v in reversed(self.versions):
            if v.is_active:
                return v
        return self.versions[-1] if self.versions else None

    class Settings:
        name = "student_documents"
        indexes = [
            [
                ("student_id", 1),
                ("document_type", 1),
            ],
            [
                ("submission_id", 1),
                ("document_type", 1),
            ],
            [
                ("batch_id", 1),
                ("class_id", 1),
            ],
            [
                ("student_id", 1),
                ("status", 1),
            ],
        ]

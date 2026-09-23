from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Any
from beanie import Document, Indexed
from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    FAILED = "FAILED"
    RETRY_PENDING = "RETRY_PENDING"


class SubmissionProcessingStatus(str, Enum):
    UPLOADING = "UPLOADING"
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    READY_FOR_VERIFICATION = "READY_FOR_VERIFICATION"
    FAILED = "FAILED"


class DocumentProcessingJob(Document):
    """
    Persistent document extraction job model stored in MongoDB.
    Survives backend restarts and allows atomic state transitions by workers.
    """
    job_id: Annotated[str, Indexed(unique=True)]
    submission_id: Annotated[str, Indexed()]
    document_id: str
    document_name: str
    document_type: str = "UNKNOWN"
    file_path: str
    file_size_bytes: int = 0
    mime_type: str = "application/pdf"
    
    status: Annotated[JobStatus, Indexed()] = JobStatus.QUEUED
    attempt_count: int = 0
    max_attempts: int = 3
    
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_info: str | None = None
    
    # Isolated extraction results for this specific document
    doc_extracted: dict[str, Any] = Field(default_factory=dict)
    raw_ocr: str = ""
    ai_response_status: str = ""
    timing_metrics: dict[str, Any] = Field(default_factory=dict)

    class Settings:
        name = "document_processing_jobs"


class SubmissionSession(Document):
    """
    High-level submission session tracking overall multi-document extraction
    lifecycle for a student upload session.
    """
    submission_id: Annotated[str, Indexed(unique=True)]
    batch_id: Annotated[str, Indexed()]
    register_number: Annotated[str, Indexed()]
    student_name: str
    mobile_number: str | None = None
    email: str | None = None
    
    status: Annotated[SubmissionProcessingStatus, Indexed()] = SubmissionProcessingStatus.QUEUED
    total_documents: int = 0
    completed_documents: int = 0
    failed_documents: int = 0
    
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_info: str | None = None
    
    # Fused results ready for verification (order-independent cross-document merge)
    verification_fields: dict[str, Any] = Field(default_factory=dict)
    detected_documents: list[str] = Field(default_factory=list)
    excel_headers: list[str] = Field(default_factory=list)

    class Settings:
        name = "submission_sessions"

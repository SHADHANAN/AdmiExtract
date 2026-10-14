import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Any, Dict, List, Optional
from beanie import Document, Indexed, PydanticObjectId, before_event, Replace, Save
from pydantic import BaseModel, Field


class BatchExtractionStatus(str, Enum):
    DRAFT = "DRAFT"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    VERIFICATION_PENDING = "VERIFICATION_PENDING"
    VERIFIED = "VERIFIED"
    EXPORTED = "EXPORTED"
    CANCELLED = "CANCELLED"


class BatchVerificationStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING = "PENDING"
    PARTIALLY_VERIFIED = "PARTIALLY_VERIFIED"
    VERIFIED = "VERIFIED"


class BatchExportStatus(str, Enum):
    NOT_READY = "NOT_READY"
    PARTIALLY_VERIFIED = "PARTIALLY_VERIFIED"
    READY = "READY"
    EXPORTED = "EXPORTED"


class BatchDownloadStatus(str, Enum):
    NOT_DOWNLOADED = "NOT_DOWNLOADED"
    DOWNLOADED = "DOWNLOADED"


class BatchExtractionRequest(Document):
    """
    Persistent entity representing a batch-level data extraction request.
    Maintains an immutable historical record of requested fields, template mappings,
    source document versions, verification status, metrics, and export history.
    """
    id: PydanticObjectId = Field(default_factory=PydanticObjectId)
    extraction_request_id: Annotated[str, Indexed(unique=True)] = Field(
        default_factory=lambda: f"ext_{uuid.uuid4().hex[:12]}"
    )
    batch_id: Annotated[str, Indexed()]
    batch_name: Optional[str] = None
    academic_year: Optional[str] = None
    department_id: Annotated[Optional[str], Indexed()] = None
    class_id: Optional[str] = None

    template_id: Optional[str] = None
    template_filename: Optional[str] = None
    template_file_path: Optional[str] = None
    template_sheet_name: Optional[str] = None
    header_row_index: int = 1
    template_headers: List[str] = Field(default_factory=list)
    header_to_column_index: Dict[str, int] = Field(default_factory=dict)
    field_mappings: List[Dict[str, Any]] = Field(default_factory=list)

    requested_fields: List[str] = Field(default_factory=list)  # Canonical snake_case field keys
    requested_columns: List[str] = Field(default_factory=list)  # Original display column headers
    column_mapping: Dict[str, str] = Field(default_factory=dict)  # column_header -> canonical_key

    # Snapshot summary of source document versions processed
    source_document_versions: List[Dict[str, Any]] = Field(default_factory=list)

    status: str = Field(default=BatchExtractionStatus.PROCESSING.value)
    result_count: int = Field(default=0, ge=0)
    total_students: int = Field(default=0, ge=0)

    # Progress and breakdown metrics
    processed_count: int = Field(default=0, ge=0)
    successful_count: int = Field(default=0, ge=0)
    partial_count: int = Field(default=0, ge=0)
    missing_docs_count: int = Field(default=0, ge=0)
    failed_count: int = Field(default=0, ge=0)
    verified_count: int = Field(default=0, ge=0)
    correction_requested_count: int = Field(default=0, ge=0)
    pending_verification_count: int = Field(default=0, ge=0)

    verification_status: str = Field(default=BatchVerificationStatus.PENDING.value)
    export_status: str = Field(default=BatchExportStatus.NOT_READY.value)
    download_status: str = Field(default=BatchDownloadStatus.NOT_DOWNLOADED.value)
    download_count: int = Field(default=0, ge=0)
    last_downloaded_at: Optional[datetime] = None
    exported_file_path: Optional[str] = None
    exported_filename: Optional[str] = None

    created_by: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    failed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @before_event(Replace, Save)
    def update_timestamp(self):
        self.updated_at = datetime.now(timezone.utc)

    class Settings:
        name = "batch_extraction_requests"
        indexes = [
            "extraction_request_id",
            "batch_id",
            "department_id",
            "status",
            "export_status",
            "created_at",
            [
                ("batch_id", 1),
                ("created_at", -1),
            ],
        ]

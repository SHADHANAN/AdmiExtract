from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class TemplatePreviewResponse(BaseModel):
    template_id: Optional[str] = Field(None, description="Database ID of saved template if persisted.")
    template_filename: Optional[str] = Field(None, description="Original filename of uploaded template.")
    sheet_name: Optional[str] = Field(None, description="Active or configured sheet name.")
    sheet_names: List[str] = Field(default_factory=list, description="All sheet names present in workbook.")
    header_row_index: int = Field(default=1, description="1-based index of the detected header row.")
    requested_columns: List[str] = Field(..., description="Original Excel header columns detected.")
    canonical_fields: List[str] = Field(..., description="Normalized snake_case canonical field names.")
    column_mapping: Dict[str, str] = Field(..., description="Map of Excel column header -> canonical field key.")
    column_indices: Dict[str, int] = Field(default_factory=dict, description="Map of Excel column header -> 1-based column index.")
    detected_students_count: int = Field(default=0, description="Count of student rows identified in template if any.")
    sample_rows: List[Dict[str, Any]] = Field(default_factory=list, description="Sample preview rows from template.")


class CreateBatchExtractionRequest(BaseModel):
    template_id: Optional[str] = Field(None, description="Specific template ID to use.")
    template_filename: Optional[str] = Field(
        None, description="Name of the template file if uploaded."
    )
    sheet_name: Optional[str] = Field(
        None, description="Configured output worksheet name."
    )
    requested_fields: Optional[List[str]] = Field(
        None, description="Explicit canonical field names to extract."
    )
    requested_columns: Optional[List[str]] = Field(
        None, description="Custom column header display names."
    )
    column_mapping: Optional[Dict[str, str]] = Field(
        None, description="Mapping between display column header and canonical field name."
    )
    field_mappings: Optional[List[Dict[str, Any]]] = Field(
        None, description="Detailed field mapping configuration snapshots."
    )
    class_id: Optional[str] = Field(
        None, description="Optional class or section filter within the batch."
    )


class BatchExtractionProgressSummary(BaseModel):
    total_students: int = 0
    processed_count: int = 0
    successful_count: int = 0
    partial_count: int = 0
    missing_docs_count: int = 0
    failed_count: int = 0
    verified_count: int = 0
    correction_requested_count: int = 0
    pending_verification_count: int = 0
    percent_complete: float = 0.0
    export_status: str = "NOT_READY"


class BatchExtractionSummaryResponse(BaseModel):
    extraction_request_id: str
    batch_id: str
    batch_name: Optional[str] = None
    academic_year: Optional[str] = None
    department_id: Optional[str] = None
    template_filename: Optional[str] = None
    requested_fields: List[str] = Field(default_factory=list)
    requested_columns: List[str] = Field(default_factory=list)
    status: str
    result_count: int = 0
    total_students: int = 0
    processed_count: int = 0
    successful_count: int = 0
    partial_count: int = 0
    missing_docs_count: int = 0
    failed_count: int = 0
    verified_count: int = 0
    correction_requested_count: int = 0
    pending_verification_count: int = 0
    verification_status: str
    export_status: str = "NOT_READY"
    download_status: str
    download_count: int = 0
    last_downloaded_at: Optional[datetime] = None
    exported_filename: Optional[str] = None
    created_by: str
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    failed_at: Optional[datetime] = None
    error_message: Optional[str] = None


class BatchExtractionStatsResponse(BaseModel):
    batch_id: str
    batch_name: str
    academic_year: str
    department_id: str
    students_count: int = 0
    stored_documents_count: int = 0
    extractions_count: int = 0
    latest_extraction: Optional[BatchExtractionSummaryResponse] = None
    verification_status: str = "PENDING"
    download_history_count: int = 0


class StudentExtractionFieldItem(BaseModel):
    field_name: str
    column_label: str
    ai_value: Optional[Any] = None
    raw_value: Optional[Any] = None
    student_value: Optional[Any] = None
    final_value: Optional[Any] = None
    verification_status: str = "AI_EXTRACTED"
    verification_id: Optional[str] = None
    is_available: bool = True
    document_type: Optional[str] = None
    source_document_type: Optional[str] = None
    source_document_name: Optional[str] = None
    source_document_version: Optional[str] = None
    confidence: str = "HIGH"
    confidence_score: float = 1.0
    field_state: str = "EXTRACTED"
    evidence_snippet: Optional[str] = None
    page_number: Optional[int] = None
    reason: Optional[str] = None
    conflicts: Optional[List[Dict[str, Any]]] = None


class StudentExtractionRowResponse(BaseModel):
    student_id: str
    student_name: Optional[str] = None
    register_number: str
    document_status: str = "Ready"  # e.g. "Ready", "Missing Aadhaar", "Missing Community"
    extraction_status: str = "COMPLETED"  # "COMPLETED", "PARTIAL", "FAILED", "NOT_PROCESSED"
    verification_status: str = "AI_EXTRACTED"  # "VERIFIED", "CORRECTION_REQUESTED", "PENDING_VERIFICATION", "AI_EXTRACTED"
    final_status: str = "PENDING_VERIFICATION"
    missing_documents: List[str] = Field(default_factory=list)
    failure_reason: Optional[str] = None
    fields: Dict[str, StudentExtractionFieldItem]
    has_corrections_pending: bool = False
    verification_token: Optional[str] = None
    verification_link: Optional[str] = None
    verification_token_status: Optional[str] = None
    verification_link_expires_at: Optional[datetime] = None


class CorrectionQueueItem(BaseModel):
    verification_id: str
    extraction_request_id: str
    student_id: str
    student_name: Optional[str] = None
    register_number: str
    document_type: str
    field_name: str
    field_label: str
    ai_value: Optional[Any] = None
    student_value: Optional[Any] = None
    student_comment: Optional[str] = None
    submitted_at: Optional[datetime] = None


class BatchExtractionDetailResponse(BaseModel):
    summary: BatchExtractionSummaryResponse
    students: List[StudentExtractionRowResponse] = Field(default_factory=list)
    total_matching_students: int = 0
    page: int = 1
    page_size: int = 50
    verification_progress: Dict[str, int] = Field(default_factory=dict)
    corrections_queue: List[CorrectionQueueItem] = Field(default_factory=list)

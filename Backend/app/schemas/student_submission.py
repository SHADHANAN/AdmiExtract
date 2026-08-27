from datetime import datetime
from pydantic import BaseModel, Field


class StudentDocumentMetaCreate(BaseModel):
    document_name: str
    status: str = "Pending"
    file_path: str | None = None
    file_size_mb: float | None = None
    file_type: str | None = None
    uploaded_at: datetime | None = None


class StudentDocumentMetaResponse(BaseModel):
    document_name: str
    status: str
    file_path: str | None = None
    file_size_mb: float | None = None
    file_type: str | None = None
    uploaded_at: datetime | None = None


class StudentSubmissionCreate(BaseModel):
    batch_id: str
    batch_name: str | None = None
    class_id: str | None = None
    class_name: str | None = None
    student_name: str
    register_number: str
    mobile_number: str
    email: str | None = None
    submission_status: str = "Submitted"
    documents: list[StudentDocumentMetaCreate] = Field(default_factory=list)
    extracted_data: dict[str, str | None] = Field(default_factory=dict)


class StudentSubmissionStatusUpdate(BaseModel):
    submission_status: str


class StudentSubmissionResponse(BaseModel):
    id: str
    batch_id: str
    batch_name: str | None = None
    class_id: str | None = None
    class_name: str | None = None
    student_name: str
    register_number: str
    mobile_number: str
    email: str | None = None
    submission_status: str
    ai_status: str = "Processing"
    document_version: int = 1
    document_version_id: str | None = None
    document_requirements_snapshot: list[dict] = Field(default_factory=list)
    extracted_data: dict[str, str | None] = Field(default_factory=dict)
    submitted_at: datetime
    updated_at: datetime
    documents: list[StudentDocumentMetaResponse] = Field(default_factory=list)

    class Config:
        from_attributes = True


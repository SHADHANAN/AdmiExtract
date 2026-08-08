from datetime import datetime, timezone
from typing import Annotated
from beanie import Document, Indexed, PydanticObjectId, before_event, Replace, Save
from pydantic import BaseModel, Field


class StudentDocumentMeta(BaseModel):
    """Sub-document representing uploaded or waived document metadata."""
    document_name: str
    status: str = "Pending"  # "Uploaded", "Not Available", "Pending"
    file_path: str | None = None
    file_size_mb: float | None = None
    file_type: str | None = None
    uploaded_at: datetime | None = None


class StudentSubmission(Document):
    """
    Beanie Document model representing a student application submission.
    """
    batch_id: Annotated[str, Indexed()]
    batch_name: str | None = None
    department_id: str | None = None
    student_name: str
    register_number: Annotated[str, Indexed()]
    mobile_number: str
    email: str | None = None
    submission_status: str = Field(default="Submitted")  # "Submitted", "AI Processing", "Verification Pending", "Verified", "Rejected"
    ai_status: str = Field(default="Processing")  # "Processing", "Complete", "Requires Review"
    
    # Document version tracking & snapshot assigned upon student creation/portal initialization
    document_version: int = Field(default=1)
    document_version_id: str | None = None
    document_requirements_snapshot: list[dict] = Field(default_factory=list)
    
    # Store dynamic AI extracted / verified student information
    extracted_data: dict[str, str | None] = Field(default_factory=dict)

    submitted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    documents: list[StudentDocumentMeta] = Field(default_factory=list)

    @before_event(Replace, Save)
    def update_timestamp(self):
        """Automatically update the updated_at timestamp before saving changes."""
        self.updated_at = datetime.now(timezone.utc)

    class Settings:
        name = "student_submissions"


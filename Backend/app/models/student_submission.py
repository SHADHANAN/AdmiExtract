from datetime import datetime, timezone
from typing import Annotated
from beanie import Document, Indexed, PydanticObjectId, before_event, Replace, Save, Insert
from pydantic import BaseModel, Field, model_validator
from pymongo import IndexModel, ASCENDING
from app.utils.normalization import normalize_register_number


class StudentDocumentMeta(BaseModel):
    """Sub-document representing uploaded or waived document metadata."""
    document_name: str
    document_type: str | None = None
    status: str = "Pending"  # "Uploaded", "Not Available", "Pending"
    file_path: str | None = None
    file_size_mb: float | None = None
    file_type: str | None = None
    version: int = 1
    uploaded_at: datetime | None = None



class StudentSubmission(Document):
    """
    Beanie Document model representing a student application submission.
    """
    batch_id: Annotated[str, Indexed()]
    batch_name: str | None = None
    class_id: Annotated[str | None, Indexed()] = None
    class_name: str | None = None
    department_id: str | None = None
    upload_link_id: Annotated[str | None, Indexed()] = None
    student_name: str
    register_number: Annotated[str, Indexed()]
    normalized_register_number: str = Field(default="")
    has_duplicate_conflict: bool = Field(default=False)
    student_id: str | None = None
    mobile_number: str = Field(default="")
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

    @model_validator(mode="after")
    def sync_normalized_register_number(self):
        if self.register_number:
            if self.has_duplicate_conflict:
                if not self.normalized_register_number or "-CONFLICT-" not in self.normalized_register_number:
                    import secrets
                    self.normalized_register_number = f"{normalize_register_number(self.register_number)}-CONFLICT-{secrets.token_hex(4)}"
            elif not self.normalized_register_number:
                self.normalized_register_number = normalize_register_number(self.register_number)
        return self

    @before_event(Replace, Save, Insert)
    def update_timestamp_and_normalized_reg(self):
        """Automatically update the updated_at timestamp and normalized_register_number before saving changes."""
        self.updated_at = datetime.now(timezone.utc)
        if self.register_number:
            if self.has_duplicate_conflict:
                if not self.normalized_register_number or "-CONFLICT-" not in self.normalized_register_number:
                    import secrets
                    self.normalized_register_number = f"{normalize_register_number(self.register_number)}-CONFLICT-{secrets.token_hex(4)}"
            else:
                self.normalized_register_number = normalize_register_number(self.register_number)

    class Settings:
        name = "student_submissions"
        indexes = [
            IndexModel(
                [("normalized_register_number", ASCENDING)],
                unique=True,
                name="idx_unique_normalized_register_number",
            ),
            [
                ("batch_id", 1),
                ("register_number", 1),
            ],
            [
                ("department_id", 1),
                ("submission_status", 1),
            ],
            [
                ("batch_id", 1),
                ("class_id", 1),
            ],
        ]

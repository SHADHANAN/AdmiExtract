from datetime import datetime, timezone
from typing import Annotated
from beanie import Document, Indexed
from pydantic import BaseModel, Field


def get_default_extraction_fields(doc_name: str) -> list[str]:
    """Helper returning default entity extraction fields based on document requirement name."""
    if not doc_name:
        return []
    lower = doc_name.lower().strip()
    if "aadhaar" in lower or "aadhar" in lower:
        return ["Aadhaar Number"]
    if "community" in lower or "caste" in lower:
        return ["Community Category"]
    if "birth" in lower or "dob" in lower:
        return ["Date of Birth"]
    if "income" in lower:
        return ["Annual Family Income"]
    if "sslc" in lower:
        return ["SSLC Mark Percentage"]
    if "hsc" in lower:
        return ["HSC Mark Percentage"]
    if "transfer" in lower or "tc" in lower:
        return ["Transfer Certificate Number", "School Name", "Admission Number", "Issue Date", "Leaving Date"]
    if "migration" in lower:
        return ["Migration Number", "University", "Year"]
    if "nativity" in lower:
        return ["Nativity"]
    return [doc_name]


class DocumentRequirementItem(BaseModel):
    """Sub-document representing an individual document requirement definition."""
    id: str
    name: str
    required: bool = True
    allowed_types: list[str] = Field(default_factory=lambda: ["PDF", "JPG", "PNG"])
    max_size_mb: float = 5.0
    description: str | None = None
    type: str = "MANDATORY"  # MANDATORY, OPTIONAL, DISABLED
    extraction_fields: list[str] = Field(default_factory=list)


class DocumentConfigurationVersion(Document):
    """
    Beanie Document model representing a specific document configuration version
    for an Admission Batch.
    """
    batch_id: Annotated[str, Indexed()]
    department_id: str | None = None
    version: int = Field(default=1, ge=1)
    documents: list[DocumentRequirementItem] = Field(default_factory=list)
    is_current: bool = Field(default=True)
    change_summary: str | None = None
    created_by: str = Field(default="Staff")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "doc_config_versions"

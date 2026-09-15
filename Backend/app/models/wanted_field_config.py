from datetime import datetime, timezone
from typing import Annotated, List, Optional
# pyrefly: ignore [missing-import]
from beanie import Document, Indexed
from pydantic import BaseModel, Field


class WantedFieldItem(BaseModel):
    """
    Sub-document representing an individual wanted field configuration for a document type.
    """
    field: str  # Canonical or label AI field name, e.g. "Aadhaar Number", "Date of Birth"
    enabled: bool = True  # Whether this field should be extracted from this document
    excel_header: Optional[str] = None  # Excel template column header mapped to this field


class DocumentFieldConfiguration(Document):
    """
    Beanie Document model representing document-specific wanted fields and Excel column mappings
    for an Admission Batch (and optional Class).
    """
    batch_id: Annotated[str, Indexed()]
    class_id: Annotated[Optional[str], Indexed()] = None
    document_type: Annotated[str, Indexed()]  # Normalized canonical document type: AADHAAR, TRANSFER_CERTIFICATE, etc.
    display_name: str = ""  # Human-readable name, e.g. "Aadhaar Card", "Residence Certificate"
    description: Optional[str] = None  # Optional staff description or instructions
    requirement_status: str = "REQUIRED"  # "REQUIRED", "OPTIONAL", "DISABLED"
    allowed_types: List[str] = Field(default_factory=lambda: ["PDF", "JPG", "PNG"])
    max_size_mb: float = 5.0
    fields: List[WantedFieldItem] = Field(default_factory=list)
    available_fields: List[str] = Field(default_factory=list)  # Catalog and custom available fields for this document
    is_archived: bool = False  # Soft archive flag to preserve auditability of uploaded student documents
    version: int = Field(default=1, ge=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "document_field_configurations"

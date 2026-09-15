from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field


class WantedFieldItemSchema(BaseModel):
    field: str
    enabled: bool = True
    excel_header: Optional[str] = None


class CreateDocumentTypePayload(BaseModel):
    name: str = Field(..., description="Document Name, e.g. Aadhaar Card, Residence Certificate")
    code: str = Field(..., description="Document Code, e.g. AADHAAR, RESIDENCE_CERTIFICATE")
    description: Optional[str] = None
    requirement_status: str = Field(default="REQUIRED", description="REQUIRED, OPTIONAL, DISABLED")
    allowed_types: Optional[List[str]] = Field(default=None)
    max_size_mb: Optional[float] = Field(default=None)
    initial_fields: Optional[List[str]] = Field(default=None, description="Optional initial available fields")


class AddFieldPayload(BaseModel):
    field_name: str = Field(..., description="Field name to add to document's available fields")


class SaveDocumentWantedFieldsPayload(BaseModel):
    fields: List[WantedFieldItemSchema] = Field(default_factory=list)
    requirement_status: Optional[str] = None
    allowed_types: Optional[List[str]] = None
    max_size_mb: Optional[float] = None
    display_name: Optional[str] = None
    description: Optional[str] = None


class DocumentFieldConfigurationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: Optional[str] = None
    batch_id: str
    class_id: Optional[str] = None
    document_type: str
    display_name: str = ""
    description: Optional[str] = None
    requirement_status: str = "REQUIRED"
    allowed_types: List[str] = Field(default_factory=lambda: ["PDF", "JPG", "PNG"])
    max_size_mb: float = 5.0
    fields: List[WantedFieldItemSchema] = Field(default_factory=list)
    available_fields: List[str] = Field(default_factory=list)
    is_archived: bool = False
    version: int = 1
    created_at: datetime
    updated_at: datetime


class DocumentTypeOverviewItem(BaseModel):
    document_type: str
    display_name: str
    description: Optional[str] = None
    requirement_status: str = "REQUIRED"
    allowed_types: List[str] = Field(default_factory=lambda: ["PDF", "JPG", "PNG"])
    max_size_mb: float = 5.0
    wanted_count: int
    mapped_count: int
    unmapped_count: int
    status: str  # CONFIGURED, INCOMPLETE, NO_WANTED_FIELDS
    version: int
    fields: List[WantedFieldItemSchema] = Field(default_factory=list)
    available_fields: List[str] = Field(default_factory=list)
    template_headers: List[str] = Field(default_factory=list)

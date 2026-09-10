from datetime import datetime
from pydantic import BaseModel, Field


class DocRequirementSchema(BaseModel):
    id: str
    name: str
    required: bool = True
    allowed_types: list[str] = Field(default_factory=lambda: ["PDF", "JPG", "PNG"])
    max_size_mb: float = 5.0
    description: str | None = None
    type: str = "MANDATORY"
    extraction_fields: list[str] = Field(default_factory=list)


class DocConfigVersionCreate(BaseModel):
    documents: list[DocRequirementSchema]
    change_summary: str | None = None
    created_by: str = "Staff"


class DocConfigVersionResponse(BaseModel):
    id: str
    batch_id: str
    version: int
    documents: list[DocRequirementSchema]
    is_current: bool
    change_summary: str | None = None
    created_by: str
    created_at: datetime

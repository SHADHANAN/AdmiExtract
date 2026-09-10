from datetime import datetime
from pydantic import BaseModel, Field


class ExcelMappingUpdate(BaseModel):
    field_mappings: dict[str, str] = Field(default_factory=dict)
    lookup_column: str | None = None


class ExcelTemplateResponse(BaseModel):
    id: str
    batch_id: str
    class_id: str | None = None
    template_filename: str
    file_path: str
    headers: list[str] = Field(default_factory=list)
    field_mappings: dict[str, str] = Field(default_factory=dict)
    lookup_column: str | None = None
    total_rows: int = 0
    updated_count: int = 0
    remaining_students: int = 0
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class StudentRowUpdatePayload(BaseModel):
    register_number: str
    class_id: str | None = None
    extracted_fields: dict[str, str | int | float | None] = Field(default_factory=dict)

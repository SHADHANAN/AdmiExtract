from datetime import datetime, timezone
from typing import Annotated
# pyrefly: ignore [missing-import]
from beanie import Document, Indexed
from pydantic import Field


class ExcelBatchTemplate(Document):
    """
    Beanie Document model representing an Excel template (.xlsx) associated with an Admission Batch.
    """
    batch_id: Annotated[str, Indexed(unique=True)]
    department_id: str | None = None
    template_filename: str
    file_path: str
    headers: list[str] = Field(default_factory=list)
    field_mappings: dict[str, str] = Field(default_factory=dict)  # Maps AI field -> Excel column header
    lookup_column: str | None = Field(default=None)  # Optional column name for Register Number matching
    total_rows: int = Field(default=0)
    updated_count: int = Field(default=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "excel_batch_templates"

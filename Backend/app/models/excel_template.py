import uuid
from datetime import datetime, timezone
from typing import Annotated, Dict, List, Optional
from beanie import Document, Indexed, PydanticObjectId, before_event, Replace, Save
from pydantic import Field


class ExcelBatchTemplate(Document):
    """
    Persistent record representing an uploaded Excel output template for an Admission Batch.
    Preserves the exact uploaded file, sheets, header row, column positions, and headers.
    """
    id: PydanticObjectId = Field(default_factory=PydanticObjectId)
    batch_id: Annotated[str, Indexed()]
    class_id: Annotated[Optional[str], Indexed()] = None
    department_id: Optional[str] = None

    template_filename: str
    file_path: str
    sheet_name: str = "Sheet1"
    sheet_names: List[str] = Field(default_factory=list)
    header_row_index: int = 1  # 1-based index of header row
    headers: List[str] = Field(default_factory=list)  # Exact headers in column order
    column_indices: Dict[str, int] = Field(default_factory=dict)  # Header name -> 1-based column index

    total_columns: int = 0
    total_rows: int = 0
    lookup_column: Optional[str] = "Register Number"
    field_mappings: Dict[str, str] = Field(default_factory=dict)

    uploaded_by: str = "system"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @before_event(Replace, Save)
    def update_timestamp(self):
        self.updated_at = datetime.now(timezone.utc)

    class Settings:
        name = "excel_batch_templates"
        indexes = [
            "batch_id",
            "class_id",
            "department_id",
            [
                ("batch_id", 1),
                ("class_id", 1),
            ],
            [
                ("batch_id", 1),
                ("created_at", -1),
            ],
        ]

from datetime import datetime, timezone
from beanie import Document, Indexed
from pydantic import Field


class AdmissionBatch(Document):
    id: str  # We override ID to use custom string IDs like 'batch_1', 'batch_2', or generated uuid strings
    name: str
    department_id: Indexed(str)  # Stores the department code, e.g. "AIML", "CSE", "ECE"
    academic_year: str
    description: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    status: str = "active"  # "active", "closed", "archived"
    created_by: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "admission_batches"

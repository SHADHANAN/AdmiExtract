from datetime import datetime, timezone
from typing import Annotated
from beanie import Document, Indexed, before_event, Replace, Save
from pydantic import Field


class BatchClass(Document):
    """
    Beanie Document model representing a Class within an Admission Batch.
    One Batch can have multiple Classes.
    """
    id: str  # Custom ID e.g. "class_1", "class_bsc_cs_a" or UUID string
    batch_id: Annotated[str, Indexed()]
    class_name: str
    department: str
    section: str
    academic_year: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @before_event(Replace, Save)
    def update_timestamp(self):
        """Automatically update updated_at before saving."""
        self.updated_at = datetime.now(timezone.utc)

    class Settings:
        name = "batch_classes"

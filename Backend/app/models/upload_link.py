from datetime import datetime, timezone
from typing import Annotated
from beanie import Document, Indexed, PydanticObjectId, before_event, Replace, Save
from pydantic import Field


class UploadLink(Document):
    """
    Beanie Document model representing a public, secure, tokenized link
    associated with a Department. Allows students to submit documents without accounts.
    """
    department_id: Annotated[PydanticObjectId, Indexed()]
    batch_id: str | None = None  # The admission batch this link is associated with
    token: Annotated[str, Indexed(unique=True)]
    slug: Annotated[str, Indexed(unique=True)]
    title: str | None = None
    description: str | None = None
    is_active: bool = True
    expires_at: datetime | None = None
    max_submissions: int | None = None
    submission_count: int = Field(default=0, ge=0)
    created_by: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @before_event(Replace, Save)
    def update_timestamp(self):
        """Automatically update the updated_at timestamp before saving changes."""
        self.updated_at = datetime.now(timezone.utc)

    class Settings:
        name = "upload_links"

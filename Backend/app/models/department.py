from datetime import datetime, timezone
from beanie import Document, Indexed
from pydantic import Field


class Department(Document):
    name: str
    code: Indexed(str, unique=True)  # type: ignore
    description: str | None = None
    created_by: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    is_active: bool = True

    class Settings:
        name = "departments"



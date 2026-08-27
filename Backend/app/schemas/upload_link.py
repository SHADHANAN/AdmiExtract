from datetime import datetime, timezone
from pydantic import BaseModel, Field, ConfigDict, field_validator
from beanie import PydanticObjectId


class UploadLinkCreate(BaseModel):
    """
    Schema used when staff creates a new upload link.
    """
    department_id: PydanticObjectId = Field(
        ...,
        description="The ID of the department this upload link belongs to"
    )
    batch_id: str | None = Field(
        default=None,
        description="The admission batch ID this upload link is associated with"
    )
    class_id: str | None = Field(
        default=None,
        description="The specific class ID this upload link is associated with"
    )
    title: str = Field(
        ...,
        max_length=100,
        description="Title/Name of the upload link"
    )
    description: str | None = Field(
        default=None,
        max_length=500,
        description="Optional description of the upload link"
    )
    expires_at: datetime | None = Field(
        default=None,
        description="Optional expiration datetime for the upload link"
    )
    max_submissions: int | None = Field(
        default=None,
        gt=0,
        description="Optional limit on the number of submissions allowed"
    )

    model_config = ConfigDict(
        str_strip_whitespace=True
    )

    @field_validator("title")
    @classmethod
    def validate_title_not_empty(cls, v: str) -> str:
        """Ensure title is not empty or just whitespace."""
        if not v.strip():
            raise ValueError("title cannot be empty or only whitespace")
        return v

    @field_validator("expires_at")
    @classmethod
    def validate_expires_at(cls, v: datetime | None) -> datetime | None:
        """Ensure expires_at is in the future if provided."""
        if v is not None:
            now = datetime.now(timezone.utc) if v.tzinfo else datetime.now()
            if v <= now:
                raise ValueError("expires_at must be in the future")
        return v


class UploadLinkUpdate(BaseModel):
    """
    Schema used for updating upload link settings.
    """
    title: str | None = Field(
        default=None,
        max_length=100,
        description="Updated title of the upload link"
    )
    description: str | None = Field(
        default=None,
        max_length=500,
        description="Updated description of the upload link"
    )
    is_active: bool | None = Field(
        default=None,
        description="Updated status of the upload link"
    )
    expires_at: datetime | None = Field(
        default=None,
        description="Updated expiration datetime for the upload link"
    )
    max_submissions: int | None = Field(
        default=None,
        gt=0,
        description="Updated maximum submissions limit"
    )

    model_config = ConfigDict(
        str_strip_whitespace=True
    )

    @field_validator("title")
    @classmethod
    def validate_title_not_empty(cls, v: str | None) -> str | None:
        """Ensure title is not empty or just whitespace if provided."""
        if v is not None and not v.strip():
            raise ValueError("title cannot be empty or only whitespace")
        return v

    @field_validator("expires_at")
    @classmethod
    def validate_expires_at(cls, v: datetime | None) -> datetime | None:
        """Ensure expires_at is in the future if provided."""
        if v is not None:
            now = datetime.now(timezone.utc) if v.tzinfo else datetime.now()
            if v <= now:
                raise ValueError("expires_at must be in the future")
        return v


class UploadLinkResponse(BaseModel):
    """
    Schema returned for upload link details.
    """
    id: PydanticObjectId
    department_id: PydanticObjectId
    batch_id: str | None = None
    class_id: str | None = None
    token: str
    slug: str
    title: str | None = None
    description: str | None = None
    is_active: bool
    expires_at: datetime | None = None
    max_submissions: int | None = None
    submission_count: int
    created_by: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(
        from_attributes=True
    )


# Alias for compatibility with code structures expecting Out suffix
UploadLinkOut = UploadLinkResponse

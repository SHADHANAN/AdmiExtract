from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict, field_validator
from beanie import PydanticObjectId


class DepartmentCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    code: str = Field(..., min_length=2, max_length=20)
    description: str | None = Field(default=None, max_length=500)

    model_config = ConfigDict(
        str_strip_whitespace=True
    )

    @field_validator("name", "code")
    @classmethod
    def validate_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("field cannot be empty or only whitespace")
        return v.strip().upper() if len(v) <= 10 else v.strip()


class DepartmentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=100)
    code: str | None = Field(default=None, min_length=2, max_length=20)
    description: str | None = Field(default=None, max_length=500)
    is_active: bool | None = None

    model_config = ConfigDict(
        str_strip_whitespace=True
    )


class DepartmentResponse(BaseModel):
    id: PydanticObjectId
    name: str
    code: str
    description: str | None = None
    created_by: str
    created_at: datetime
    is_active: bool

    model_config = ConfigDict(
        from_attributes=True
    )


# Alias for backward compatibility
DepartmentOut = DepartmentResponse


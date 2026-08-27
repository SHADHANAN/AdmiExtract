from datetime import datetime
from pydantic import BaseModel, Field


class ClassCreate(BaseModel):
    class_name: str = Field(..., min_length=1, description="Name of the class e.g. B.Sc Computer Science - A")
    department: str = Field(..., min_length=1, description="Department name or code e.g. CSE")
    section: str = Field(..., min_length=1, description="Section e.g. A, B")
    academic_year: str = Field(..., min_length=1, description="Academic Year e.g. 2025-2026")


class ClassUpdate(BaseModel):
    class_name: str | None = Field(default=None, min_length=1)
    department: str | None = Field(default=None, min_length=1)
    section: str | None = Field(default=None, min_length=1)
    academic_year: str | None = Field(default=None, min_length=1)


class ClassResponse(BaseModel):
    id: str
    batch_id: str
    class_name: str
    department: str
    section: str
    academic_year: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

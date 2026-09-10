from datetime import datetime
from pydantic import BaseModel, Field


class BatchCreate(BaseModel):
    id: str | None = None
    name: str
    department_id: str
    academic_year: str
    description: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    status: str = "active"


class BatchUpdate(BaseModel):
    name: str | None = None
    academic_year: str | None = None
    description: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    status: str | None = None


class BatchResponse(BaseModel):
    id: str
    name: str
    department_id: str
    academic_year: str
    description: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    status: str
    created_by: str
    created_at: datetime

    model_config = {
        "from_attributes": True
    }

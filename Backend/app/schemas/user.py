from pydantic import BaseModel, EmailStr
from beanie import PydanticObjectId

from app.models.user import UserRole


class UserCreate(BaseModel):
    username: str
    name: str
    password: str
    email: EmailStr | None = None
    role: UserRole = UserRole.DEPARTMENT_ADMIN
    department_code: str | None = None
    register_number: str | None = None
    mobile_number: str | None = None


class UserResponse(BaseModel):
    id: PydanticObjectId
    username: str
    name: str
    email: str | None = None
    role: UserRole
    department_code: str | None = None
    register_number: str | None = None
    mobile_number: str | None = None
    is_active: bool = True

    model_config = {
        "from_attributes": True
    }


UserOut = UserResponse  # Alias for backward compatibility


class StudentProfileResponse(BaseModel):
    student_name: str
    register_number: str
    mobile_number: str
    email: str | None = None


class UserUpdate(BaseModel):
    name: str | None = None
    email: EmailStr | None = None
    password: str | None = None
    role: UserRole | None = None
    department_code: str | None = None
    register_number: str | None = None
    mobile_number: str | None = None
    is_active: bool | None = None


class ResetPasswordSchema(BaseModel):
    new_password: str


class ToggleUserStatusSchema(BaseModel):
    is_active: bool






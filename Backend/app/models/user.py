from enum import Enum
from beanie import Document, Indexed
from pydantic import EmailStr


class UserRole(str, Enum):
    SUPER_ADMIN = "super_admin"
    DEPARTMENT_ADMIN = "department_admin"
    STUDENT = "student"


class User(Document):
    username: Indexed(str, unique=True)  # type: ignore
    name: str
    email: EmailStr | None = None
    password: str
    role: UserRole = UserRole.DEPARTMENT_ADMIN
    department_code: str | None = None
    register_number: str | None = None
    mobile_number: str | None = None
    is_active: bool = True

    class Settings:
        name = "users"




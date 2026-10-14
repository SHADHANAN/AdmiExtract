from datetime import datetime
from typing import Any, List, Optional
from pydantic import BaseModel, Field
from app.schemas.document_verification import DocumentFieldVerificationResponse, StudentFieldVerificationItem

PublicFieldVerificationSubmitItem = StudentFieldVerificationItem


class PublicVerificationFieldItem(BaseModel):
    id: str
    field_name: str
    document_type: str = "OTHER"
    ai_value: Optional[Any] = None
    student_value: Optional[Any] = None
    final_value: Optional[Any] = None
    status: str
    student_comment: Optional[str] = None
    staff_comment: Optional[str] = None


class PublicVerificationTokenResponse(BaseModel):
    valid: bool
    token: str
    student_id: str
    student_name: str
    batch_id: str
    batch_name: Optional[str] = None
    class_id: Optional[str] = None
    department_id: Optional[str] = None
    extraction_request_id: Optional[str] = None
    status: str
    expires_at: datetime
    extracted_at: Optional[datetime] = None
    fields: List[DocumentFieldVerificationResponse] = []


class PublicVerificationSubmitRequest(BaseModel):
    fields: List[StudentFieldVerificationItem] = Field(
        ..., min_length=1, description="List of field verification responses from student"
    )
    general_comment: Optional[str] = None


class PublicVerificationSessionResponse(BaseModel):
    valid: bool
    token: str
    status: str
    batch_name: Optional[str] = None
    department_id: Optional[str] = None
    expires_at: datetime
    is_completed: bool = False
    requires_identity_verification: bool = True
    extraction_request_id: Optional[str] = None


class ValidateStudentIdentityRequest(BaseModel):
    student_name: str
    register_number: str


class GenerateVerificationTokenRequest(BaseModel):
    student_id: str
    batch_id: str
    student_name: Optional[str] = None
    extraction_request_id: Optional[str] = None
    class_id: Optional[str] = None
    department_id: Optional[str] = None
    expires_in_days: int = 7
    force_refresh: bool = False


class GenerateVerificationTokenResponse(BaseModel):
    token: str
    student_id: str
    student_name: str
    batch_id: str
    extraction_request_id: Optional[str] = None
    verification_url: str
    status: str = "ACTIVE"
    expires_at: datetime


class CommonStudentIdentifyRequest(BaseModel):
    student_name: str
    register_number: str
    batch_id: Optional[str] = None
    batch_name: Optional[str] = None
    extraction_request_id: Optional[str] = None


class CommonStudentIdentifyResponse(BaseModel):
    session_token: str
    requires_code: bool = False
    contact_hint: Optional[str] = None
    dev_code: Optional[str] = None
    batch_name: Optional[str] = None
    expires_at: datetime


class CommonStudentVerifyCodeRequest(BaseModel):
    session_token: str
    code: Optional[str] = None


class CommonStudentSubmitRequest(BaseModel):
    session_token: str
    fields: List[StudentFieldVerificationItem] = Field(
        ..., min_length=1, description="List of field verification responses from student"
    )
    general_comment: Optional[str] = None


class CommonStudentResendCodeRequest(BaseModel):
    session_token: str


class CommonStudentResendCodeResponse(BaseModel):
    success: bool = True
    message: str = "A new verification code has been sent."
    contact_hint: Optional[str] = None
    dev_code: Optional[str] = None
    expires_at: Optional[datetime] = None
    cooldown_seconds: int = 30

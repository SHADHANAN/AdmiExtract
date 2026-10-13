from datetime import datetime, timezone, timedelta
from enum import Enum
import secrets
from typing import Annotated, Optional
from beanie import Document, Indexed, before_event, Replace, Save
from pydantic import BaseModel, Field


class VerificationTokenStatus(str, Enum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class VerificationToken(Document):
    """
    Cryptographically secure token granting public, scoped access for a student
    to verify and correct their document extraction data without requiring a user account.
    """
    token: Annotated[str, Indexed(unique=True)] = Field(
        default_factory=lambda: secrets.token_urlsafe(32)
    )
    student_id: Annotated[str, Indexed()]  # Student register number or student identifier
    student_name: str
    batch_id: Annotated[str, Indexed()]
    batch_name: Optional[str] = None
    class_id: Optional[str] = None
    department_id: Optional[str] = None
    extraction_request_id: Optional[str] = None
    submission_id: Optional[str] = None

    status: str = Field(default=VerificationTokenStatus.ACTIVE.value)
    verification_code: Optional[str] = None
    code_attempts: int = 0
    is_verified: bool = False
    expires_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc) + timedelta(days=7)
    )

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
    last_accessed_at: Optional[datetime] = None
    last_code_sent_at: Optional[datetime] = None
    resend_count: int = 0

    @before_event(Replace, Save)
    def update_timestamp(self):
        self.updated_at = datetime.now(timezone.utc)

    @property
    def is_valid(self) -> bool:
        if self.status != VerificationTokenStatus.ACTIVE.value:
            return False
        now = datetime.now(timezone.utc)
        exp = self.expires_at.replace(tzinfo=timezone.utc) if self.expires_at.tzinfo is None else self.expires_at
        return exp > now

    class Settings:
        name = "verification_tokens"
        indexes = [
            "token",
            "student_id",
            "batch_id",
            "extraction_request_id",
            [
                ("student_id", 1),
                ("batch_id", 1),
                ("status", 1),
            ],
        ]

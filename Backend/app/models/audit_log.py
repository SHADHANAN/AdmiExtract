from datetime import datetime, timezone
from typing import Annotated
from beanie import Document, Indexed
from pydantic import Field


class AuditLog(Document):
    """
    Immutable audit trail for critical system actions (such as student deletion).
    Never logs passwords, tokens, API keys, full Aadhaar numbers, or sensitive document contents.
    """
    action: Annotated[str, Indexed()] = "DELETE_STUDENT"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    
    # Actor performing the action
    actor_user_id: Annotated[str, Indexed()]
    actor_username: str
    actor_role: str
    
    # Target resource information
    submission_id: Annotated[str, Indexed()]
    student_name: str
    register_number: Annotated[str, Indexed()]
    batch_id: Annotated[str | None, Indexed()] = None
    class_id: Annotated[str | None, Indexed()] = None
    
    # Quantitative and impact metrics
    documents_count: int = 0
    files_deleted_count: int = 0
    files_preserved_count: int = 0
    
    # Operation outcome
    result: str = "SUCCESS"  # "SUCCESS", "PARTIAL_FAILURE", "FAILED"
    failure_info: str | None = None

    class Settings:
        name = "audit_logs"

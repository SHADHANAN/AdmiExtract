from pydantic import BaseModel


class StudentIdentityVerifyRequest(BaseModel):
    """
    Payload sent by the student from the public upload identification form.
    The token identifies which upload link they are accessing.
    """
    token: str
    student_name: str
    register_number: str
    mobile_number: str


class StudentIdentityVerifyResponse(BaseModel):
    """
    Returned to the frontend after successful identity verification.
    Contains enough context to build the document upload session.
    No JWT or authentication token is issued.
    """
    batch_id: str
    batch_name: str
    class_id: str | None = None
    class_name: str | None = None

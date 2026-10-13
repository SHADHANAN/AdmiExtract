import os
from typing import Any, cast
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from motor.motor_asyncio import AsyncIOMotorClient
from beanie import init_beanie, PydanticObjectId
from fastapi import HTTPException

from app.main import app
from app.models.user import User, UserRole
from app.models.student_submission import StudentSubmission, StudentDocumentMeta
from app.core.config import settings
from app.core.security import get_password_hash, create_access_token
from app.core.dependencies import get_current_user
from app.api.student_submission import _to_public_response
from app.services.student_document_service import StudentDocumentService
from app.models.student_document import StudentDocument
from app.utils.logger_masking import mask_sensitive_value


from app.models.verification_token import VerificationToken, VerificationTokenStatus
from app.models.upload_link import UploadLink


@pytest_asyncio.fixture(scope="function", autouse=True)
async def setup_test_db():
    if not hasattr(AsyncIOMotorClient, "append_metadata"):
        AsyncIOMotorClient.append_metadata = lambda *args, **kwargs: None

    test_client = AsyncIOMotorClient(settings.MONGODB_URI)
    test_db = test_client["automate_security_test_db"]

    import app.db.database
    app.db.database.client = test_client
    app.db.database.db = test_db
    app.db.database._is_connected = True

    await init_beanie(
        database=cast(Any, test_db),
        document_models=[User, StudentSubmission, VerificationToken, UploadLink]
    )
    await User.find_all().delete()
    await StudentSubmission.find_all().delete()
    await VerificationToken.find_all().delete()
    await UploadLink.find_all().delete()

    yield

    await test_client.drop_database("automate_security_test_db")
    test_client.close()


@pytest_asyncio.fixture
async def client_async():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_super_admin_registration_blocked(client_async: AsyncClient):
    """Fix 1: Anonymous registration cannot create a super_admin account."""
    res = await client_async.post(
        "/auth/register",
        json={
            "username": "rogue_super",
            "name": "Rogue Admin",
            "email": "rogue@example.com",
            "password": "Password123!",
            "role": "super_admin",
        },
    )
    assert res.status_code == 403
    assert "Super Admin accounts cannot be created" in res.json()["detail"]


@pytest.mark.asyncio
async def test_authorized_staff_provisioning_via_admin(client_async: AsyncClient):
    """Fix 1: Authorized administration flow can still provision legitimate staff accounts."""
    admin = User(
        username="superadmin_test",
        name="Super Admin User",
        email="superadmin@test.com",
        password=get_password_hash("AdminPass123!"),
        role=UserRole.SUPER_ADMIN,
        is_active=True,
    )
    await admin.insert()

    token = create_access_token({"sub": str(admin.id)})

    res = await client_async.post(
        "/users",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "username": "dept_staff_01",
            "name": "Department Staff",
            "email": "dept_staff@example.com",
            "password": "StaffPassword123!",
            "role": "department_admin",
            "department_code": "AIML",
        },
    )
    assert res.status_code == 201
    data = res.json()
    assert data["username"] == "dept_staff_01"
    assert data["role"] == "department_admin"


@pytest.mark.asyncio
async def test_unauthorized_student_submission_access_blocked(client_async: AsyncClient):
    """Fix 2: Unauthorized requests without token or credentials cannot retrieve student submissions."""
    submission = StudentSubmission(
        batch_id="batch_sec_2026",
        student_name="Protected Student",
        register_number="26CSE100",
        mobile_number="9876543210",
        email="protected@example.com",
        department_id="CSE",
        documents=[
            StudentDocumentMeta(
                document_name="Aadhaar Card",
                document_type="AADHAAR",
                file_path="/internal/server/disk/aadhaar.pdf",
                status="Uploaded",
            )
        ],
    )
    await submission.insert()

    # 1. Accessing without any credentials or token must return 401 Unauthorized
    res_sub = await client_async.get(f"/student-submissions/public/{submission.id}")
    assert res_sub.status_code == 401
    assert "Unauthorized" in res_sub.json()["detail"]

    # 2. Accessing alias route /submissions/public/{id} must also return 401 Unauthorized
    res_alias = await client_async.get(f"/submissions/public/{submission.id}")
    assert res_alias.status_code == 401


@pytest.mark.asyncio
async def test_scoped_student_session_can_access_own_submission(client_async: AsyncClient):
    """Fix 2: A valid scoped student verification or upload session can access its permitted data."""
    submission = StudentSubmission(
        batch_id="batch_sec_2026",
        student_name="Legitimate Student",
        register_number="26CSE200",
        mobile_number="9876543210",
        email="legit@example.com",
        department_id="CSE",
        documents=[
            StudentDocumentMeta(
                document_name="Community Certificate",
                document_type="COMMUNITY",
                file_path="/var/app/internal_storage/community.pdf",
                status="Uploaded",
            )
        ],
    )
    await submission.insert()

    # Create scoped VerificationToken for this student
    v_token = VerificationToken(
        token="valid-scoped-session-token-12345",
        student_id="26CSE200",
        student_name="Legitimate Student",
        batch_id="batch_sec_2026",
        submission_id=str(submission.id),
        status=VerificationTokenStatus.ACTIVE.value,
        is_verified=True,
    )
    await v_token.insert()

    # Accessing with valid scoped token returns sanitized response (200 OK)
    res = await client_async.get(
        f"/student-submissions/public/{submission.id}",
        params={"token": "valid-scoped-session-token-12345"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["register_number"] == "26CSE200"
    assert len(data["documents"]) == 1
    # Filesystem path is stripped
    assert data["documents"][0]["file_path"] is None
    assert data["documents"][0]["document_name"] == "Community Certificate"
    # Extracted data is not leaked
    assert data["extracted_data"] == {}


@pytest.mark.asyncio
async def test_otp_dev_code_suppressed_in_production(client_async: AsyncClient, monkeypatch):
    """Fix 3: Public API responses never expose dev_code in production."""
    monkeypatch.setattr(settings, "APP_ENV", "production")

    v_token = VerificationToken(
        token="session-token-otp-prod-test",
        student_id="26CSE300",
        student_name="Priya Sharma",
        batch_id="batch_sec_2026",
        status=VerificationTokenStatus.ACTIVE.value,
        is_verified=False,
    )
    await v_token.insert()

    res = await client_async.post(
        "/public/student-verification/resend-code",
        json={"session_token": "session-token-otp-prod-test"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    # dev_code MUST be None in production
    assert data["dev_code"] is None


@pytest.mark.asyncio
async def test_deactivated_account_rejected_on_authenticated_endpoints():
    """Confirm that deactivated user accounts cannot authenticate via get_current_user."""
    user = User(
        username="deactivated_staff",
        name="Deactivated Staff",
        email="deactivated@example.com",
        password=get_password_hash("StaffPass123!"),
        role=UserRole.DEPARTMENT_ADMIN,
        department_code="CSE",
        is_active=False,
    )
    await user.insert()

    token = create_access_token({"sub": str(user.id)})
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(token)

    assert exc_info.value.status_code == 401
    assert "deactivated" in exc_info.value.detail.lower()


def test_public_submission_response_sanitizes_pii_and_disk_paths():
    """Verify _to_public_response strips internal filesystem paths and raw extracted data."""
    submission = StudentSubmission(
        batch_id="batch_123",
        student_name="Test Student",
        register_number="REG999",
        extracted_data={"aadhaar_number": "1234 5678 9012", "phone": "9876543210"},
        documents=[
            StudentDocumentMeta(
                document_name="10th_marks.pdf",
                document_type="10TH_MARKSHEET",
                file_path="/var/app/uploads/internal_server_disk/10th_marks.pdf",
                file_size_mb=1.2,
                file_type="application/pdf",
                status="Uploaded",
            )
        ],
    )

    public_resp = _to_public_response(submission)
    assert public_resp.extracted_data == {}
    assert len(public_resp.documents) == 1
    assert public_resp.documents[0].file_path is None
    assert public_resp.documents[0].document_name == "10th_marks.pdf"


@pytest.mark.asyncio
async def test_cors_rejects_arbitrary_untrusted_origins(client_async: AsyncClient):
    """Verify CORS middleware allows trusted production & local origins, but rejects arbitrary pages.dev / trycloudflare subdomains."""
    # 1. Allowed origin: production frontend
    res_allowed = await client_async.options(
        "/auth/login",
        headers={
            "Origin": "https://admiextract.pages.dev",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert res_allowed.headers.get("access-control-allow-origin") == "https://admiextract.pages.dev"

    # 2. Allowed origin: localhost dev server
    res_local = await client_async.options(
        "/auth/login",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert res_local.headers.get("access-control-allow-origin") == "http://localhost:5173"

    # 3. Disallowed origin: untrusted third-party pages.dev site
    res_blocked = await client_async.options(
        "/auth/login",
        headers={
            "Origin": "https://malicious-attacker.pages.dev",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert res_blocked.headers.get("access-control-allow-origin") is None


def test_department_admin_access_authorization():
    """Verify department admin cannot access resources belonging to a different department."""
    service = StudentDocumentService()
    dept_user = User(
        id=PydanticObjectId(),
        username="ece_staff",
        name="ECE Staff",
        email="ece@example.com",
        password="hash",
        role=UserRole.DEPARTMENT_ADMIN,
        department_code="ECE",
        is_active=True,
    )

    # Document belonging to CSE
    doc_cse = StudentDocument(
        batch_id="batch_001",
        document_name="marksheet.pdf",
        student_id="REG001",
        document_type="10TH_MARKSHEET",
        department_id="CSE",
    )

    with pytest.raises(HTTPException) as exc_info:
        service._verify_user_access(doc_cse, dept_user)

    assert exc_info.value.status_code == 403
    assert "Forbidden" in exc_info.value.detail

    # Document belonging to ECE should succeed
    doc_ece = StudentDocument(
        batch_id="batch_001",
        document_name="marksheet.pdf",
        student_id="REG001",
        document_type="10TH_MARKSHEET",
        department_id="ECE",
    )
    service._verify_user_access(doc_ece, dept_user)  # No exception raised


def test_sensitive_value_masking_for_logs():
    """Verify logger masking protects Aadhaar, bank numbers, and secrets in extraction logs."""
    assert mask_sensitive_value("1234 5678 9012") == "XXXX XXXX 9012"
    assert mask_sensitive_value("123456789012") == "XXXXXXXX9012"
    assert mask_sensitive_value("9876543210") == "XXXXXX3210"
    assert mask_sensitive_value("NOT_AVAILABLE") == "NOT_AVAILABLE"
    assert mask_sensitive_value(None) == "None"

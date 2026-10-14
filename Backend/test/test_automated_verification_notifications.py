import os
import uuid
from datetime import datetime, timezone, timedelta
from typing import Dict, Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from motor.motor_asyncio import AsyncIOMotorClient

from app.core.config import settings
from app.core.security import create_access_token, get_password_hash
from app.main import app
from app.models.batch import AdmissionBatch
from app.models.batch_extraction import (
    BatchExtractionRequest,
    BatchExtractionStatus,
)
from app.models.student_submission import StudentSubmission
from app.models.user import User, UserRole
from app.models.verification_notification import (
    VerificationNotification,
    NotificationChannel,
    NotificationStatus,
)
from app.models.verification_token import (
    VerificationToken,
    VerificationTokenStatus,
)
from app.services.notification.mock_provider import MockNotificationProvider
from app.services.notification.template_service import NotificationTemplateService
from app.services.notification_service import NotificationService


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    import app.db.database as db_mod

    db_mod.client = AsyncIOMotorClient(
        settings.MONGODB_URI, serverSelectionTimeoutMS=2000
    )
    db_mod.db = db_mod.client[settings.DATABASE_NAME]
    await db_mod._run_db_setup()


@pytest_asyncio.fixture
async def client_async():
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", timeout=30.0
    ) as ac:
        yield ac


@pytest_asyncio.fixture
async def super_admin_user() -> User:
    user = await User.find_one(User.username == "notif_superadmin")
    if not user:
        user = User(
            username="notif_superadmin",
            email="notif_superadmin@test.com",
            name="Super Admin",
            password=get_password_hash("password123"),
            role=UserRole.SUPER_ADMIN,
            is_active=True,
        )
        await user.insert()
    return user


@pytest_asyncio.fixture
async def dept_admin_user() -> User:
    user = await User.find_one(User.username == "notif_deptadmin")
    if not user:
        user = User(
            username="notif_deptadmin",
            email="notif_deptadmin@test.com",
            name="Dept Admin",
            password=get_password_hash("password123"),
            role=UserRole.DEPARTMENT_ADMIN,
            department_code="dept-cse-01",
            is_active=True,
        )
        await user.insert()
    return user


@pytest_asyncio.fixture
def auth_headers(super_admin_user: User) -> Dict[str, str]:
    token = create_access_token(
        data={"sub": str(super_admin_user.id), "role": super_admin_user.role.value}
    )
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def sample_extraction_fixture(super_admin_user: User):
    """Creates a complete batch, submission, extraction request, and verification token fixture."""
    unique_suffix = uuid.uuid4().hex[:6]
    batch_id = f"batch-notif-{unique_suffix}"
    extraction_id = f"ext-req-{unique_suffix}"
    reg_no = f"REG_{unique_suffix.upper()}"
    student_id = reg_no

    # 1. Admission Batch
    batch = AdmissionBatch(
        id=batch_id,
        name=f"Batch {unique_suffix}",
        academic_year="2026-2027",
        department_id="dept-cse-01",
        created_by=str(super_admin_user.id),
    )
    await batch.insert()

    # 2. Student Submission with contact info
    submission = StudentSubmission(
        submission_id=f"sub-{unique_suffix}",
        batch_id=batch_id,
        register_number=reg_no,
        student_name=f"Ananya Sharma {unique_suffix}",
        email=f"ananya.{unique_suffix}@example.com",
        mobile_number="9876543210",
        department_id="dept-cse-01",
        status="ACTIVE",
    )
    await submission.insert()

    # 3. Extraction Request
    extraction_req = BatchExtractionRequest(
        extraction_request_id=extraction_id,
        batch_id=batch_id,
        academic_year="2026-2027",
        department_id="dept-cse-01",
        requested_fields=["student_name", "aadhaar_number"],
        requested_columns=["Name", "Aadhaar"],
        status=BatchExtractionStatus.COMPLETED.value,
        total_students=1,
        processed_count=1,
        successful_count=1,
        created_by=str(super_admin_user.id),
    )
    await extraction_req.insert()

    # 4. Verification Token
    token_str = f"test_verif_token_{unique_suffix}"
    verif_token = VerificationToken(
        token=token_str,
        extraction_request_id=extraction_id,
        student_id=student_id,
        student_name=f"Ananya Sharma {unique_suffix}",
        batch_id=batch_id,
        status=VerificationTokenStatus.ACTIVE.value,
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )
    await verif_token.insert()

    return {
        "batch_id": batch_id,
        "extraction_id": extraction_id,
        "student_id": student_id,
        "reg_no": reg_no,
        "token_str": token_str,
        "verif_token": verif_token,
        "submission": submission,
        "extraction_req": extraction_req,
    }


@pytest.mark.asyncio
async def test_template_rendering():
    """Verify dynamic placeholder rendering for Email, SMS, and WhatsApp."""
    tpl = NotificationTemplateService()
    rendered = tpl.render(
        channel=NotificationChannel.EMAIL,
        student_name="Ananya Sharma",
        verification_link="https://app.example.com/verify?token=abc123xyz",
        institution_name="Demo Engineering College",
    )
    assert "Verify Your Extracted Admission Data" in rendered["subject"]
    assert "Dear Ananya Sharma," in rendered["body"]
    assert "https://app.example.com/verify?token=abc123xyz" in rendered["body"]
    assert "Demo Engineering College" in rendered["body"]

    # SMS Template
    sms_rendered = tpl.render(
        channel=NotificationChannel.SMS,
        student_name="Ananya Sharma",
        verification_link="https://app.example.com/verify?token=abc123xyz",
    )
    assert "Dear Ananya Sharma" in sms_rendered["body"]
    assert "https://app.example.com/verify?token=abc123xyz" in sms_rendered["body"]


@pytest.mark.asyncio
async def test_single_email_mock_notification(
    client_async: AsyncClient,
    auth_headers: Dict[str, str],
    sample_extraction_fixture: Dict[str, Any],
):
    """Test 1: Verification token exists -> Notification dispatched via Mock Email -> Verification URL delivered."""
    fix = sample_extraction_fixture
    ext_id = fix["extraction_id"]
    stu_id = fix["student_id"]

    MockNotificationProvider.clear_dispatches()

    resp = await client_async.post(
        f"/data-extractions/{ext_id}/notifications/send?force_mock=true",
        json={
            "student_id": stu_id,
            "channel": "EMAIL",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["extraction_request_id"] == ext_id
    assert data["student_id"] == stu_id
    assert data["channel"] == "EMAIL"
    assert data["status"] == "SENT"
    assert "ananya" in data["recipient"]
    assert data["is_mock"] is True
    assert "mock" in data["provider_type"]

    # Verify underlying database record has token safely masked
    notif_doc = await VerificationNotification.get(data["id"])
    assert notif_doc is not None
    assert "..." in notif_doc.token_str_masked or notif_doc.token_str_masked == "COMMON_LINK"
    assert fix["token_str"] != notif_doc.token_str_masked

    # Mock provider recorded the dispatch
    dispatches = MockNotificationProvider.get_dispatches()
    assert len(dispatches) == 1
    assert dispatches[0]["recipient"] == fix["submission"].email
    assert fix["token_str"] in dispatches[0]["verification_link"] or fix["batch_id"] in dispatches[0]["verification_link"]


@pytest.mark.asyncio
async def test_single_sms_mock_notification(
    client_async: AsyncClient,
    auth_headers: Dict[str, str],
    sample_extraction_fixture: Dict[str, Any],
):
    """Test 2: SMS notification dispatch creates valid record and sends correct link."""
    fix = sample_extraction_fixture
    ext_id = fix["extraction_id"]
    stu_id = fix["student_id"]

    MockNotificationProvider.clear_dispatches()

    resp = await client_async.post(
        f"/data-extractions/{ext_id}/notifications/send?force_mock=true",
        json={
            "student_id": stu_id,
            "channel": "SMS",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["channel"] == "SMS"
    assert data["recipient"] == "9876543210"
    assert data["status"] == "SENT"


@pytest.mark.asyncio
async def test_single_whatsapp_mock_notification(
    client_async: AsyncClient,
    auth_headers: Dict[str, str],
    sample_extraction_fixture: Dict[str, Any],
):
    """Test 3: WhatsApp notification dispatch creates valid record and sends correct link."""
    fix = sample_extraction_fixture
    ext_id = fix["extraction_id"]
    stu_id = fix["student_id"]

    MockNotificationProvider.clear_dispatches()

    resp = await client_async.post(
        f"/data-extractions/{ext_id}/notifications/send?force_mock=true",
        json={
            "student_id": stu_id,
            "channel": "WHATSAPP",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["channel"] == "WHATSAPP"
    assert data["status"] == "SENT"


@pytest.mark.asyncio
async def test_missing_contact_handling(
    client_async: AsyncClient,
    auth_headers: Dict[str, str],
    sample_extraction_fixture: Dict[str, Any],
):
    """Test 4: Missing email/mobile is handled safely (marked as FAILED with failure reason without crashing)."""
    fix = sample_extraction_fixture
    submission = fix["submission"]
    submission.email = ""
    submission.mobile_number = ""
    await submission.save()

    resp = await client_async.post(
        f"/data-extractions/{fix['extraction_id']}/notifications/send?force_mock=true",
        json={
            "student_id": fix["student_id"],
            "channel": "EMAIL",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "FAILED"
    assert "unavailable" in data["failure_reason"].lower() or "email" in data["failure_reason"].lower()


@pytest.mark.asyncio
async def test_provider_not_configured_handling(
    client_async: AsyncClient,
    auth_headers: Dict[str, str],
    sample_extraction_fixture: Dict[str, Any],
):
    """Test 5: When real provider is disabled and force_mock=False, notification is recorded as FAILED with unconfigured status."""
    fix = sample_extraction_fixture

    # Ensure SMS is disabled
    settings.SMS_PROVIDER_ENABLED = False

    resp = await client_async.post(
        f"/data-extractions/{fix['extraction_id']}/notifications/send?force_mock=false",
        json={
            "student_id": fix["student_id"],
            "channel": "SMS",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "FAILED"
    assert "unconfigured" in data["failure_reason"].lower() or "disabled" in data["failure_reason"].lower() or "provider" in data["failure_reason"].lower()


@pytest.mark.asyncio
async def test_idempotency_prevents_duplicate_sends(
    client_async: AsyncClient,
    auth_headers: Dict[str, str],
    sample_extraction_fixture: Dict[str, Any],
):
    """Test 6: Multiple send requests return existing notification without sending duplicate messages."""
    fix = sample_extraction_fixture
    ext_id = fix["extraction_id"]
    stu_id = fix["student_id"]

    MockNotificationProvider.clear_dispatches()

    # First send
    resp1 = await client_async.post(
        f"/data-extractions/{ext_id}/notifications/send?force_mock=true",
        json={"student_id": stu_id, "channel": "EMAIL"},
        headers=auth_headers,
    )
    assert resp1.status_code == 200
    notif1 = resp1.json()

    # Second send without force_resend -> Should return same notification ID and not dispatch again
    resp2 = await client_async.post(
        f"/data-extractions/{ext_id}/notifications/send?force_mock=true",
        json={"student_id": stu_id, "channel": "EMAIL", "force_resend": False},
        headers=auth_headers,
    )
    assert resp2.status_code == 200
    notif2 = resp2.json()

    assert notif1["id"] == notif2["id"]
    assert len(MockNotificationProvider.get_dispatches()) == 1


@pytest.mark.asyncio
async def test_send_again_creates_new_attempt(
    client_async: AsyncClient,
    auth_headers: Dict[str, str],
    sample_extraction_fixture: Dict[str, Any],
):
    """Test 7: Explicit 'Send Again' (force_resend=True) creates a new delivery attempt while reusing the same token."""
    fix = sample_extraction_fixture
    ext_id = fix["extraction_id"]
    stu_id = fix["student_id"]

    MockNotificationProvider.clear_dispatches()

    # 1. Initial send
    resp1 = await client_async.post(
        f"/data-extractions/{ext_id}/notifications/send?force_mock=true",
        json={"student_id": stu_id, "channel": "EMAIL"},
        headers=auth_headers,
    )
    notif1 = resp1.json()

    # 2. Explicit Send Again
    resp2 = await client_async.post(
        f"/data-extractions/{ext_id}/notifications/send?force_mock=true",
        json={"student_id": stu_id, "channel": "EMAIL", "force_resend": True},
        headers=auth_headers,
    )
    notif2 = resp2.json()

    # Different notification record IDs
    assert notif1["id"] != notif2["id"]
    # Reuses the exact same verification token
    doc1 = await VerificationNotification.get(notif1["id"])
    doc2 = await VerificationNotification.get(notif2["id"])
    assert doc1.verification_token_id == doc2.verification_token_id
    # Two separate dispatches recorded
    assert len(MockNotificationProvider.get_dispatches()) == 2


@pytest.mark.asyncio
async def test_bulk_notification_dispatch(
    client_async: AsyncClient,
    auth_headers: Dict[str, str],
    sample_extraction_fixture: Dict[str, Any],
):
    """Test 8: Bulk send dispatches to all candidates and reports metrics."""
    fix = sample_extraction_fixture
    ext_id = fix["extraction_id"]

    MockNotificationProvider.clear_dispatches()

    resp = await client_async.post(
        f"/data-extractions/{ext_id}/notifications/send-bulk?force_mock=true",
        json={"channel": "EMAIL", "force_resend": True},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()

    assert data["total_eligible"] == 1
    assert data["total_sent"] == 1
    assert data["total_failed"] == 0
    assert len(data["notifications"]) == 1


@pytest.mark.asyncio
async def test_retry_failed_notification(
    client_async: AsyncClient,
    auth_headers: Dict[str, str],
    sample_extraction_fixture: Dict[str, Any],
):
    """Test 9: Retry notification updates retry_count and status without regenerating the verification token."""
    fix = sample_extraction_fixture
    ext_id = fix["extraction_id"]
    stu_id = fix["student_id"]

    # 1. Create a failed notification
    failed_notif = VerificationNotification(
        extraction_request_id=ext_id,
        student_id=stu_id,
        verification_token_id=str(fix["verif_token"].id),
        channel=NotificationChannel.EMAIL,
        recipient="ananya@test.com",
        template_identifier="VERIFICATION_EMAIL_V1",
        status=NotificationStatus.FAILED,
        provider_name="MockNotificationProvider",
        failure_reason="SMTP connection timeout",
        retry_count=0,
        token_str_masked="test...ix",
    )
    await failed_notif.insert()

    # 2. Retry delivery
    resp = await client_async.post(
        f"/data-extractions/notifications/{str(failed_notif.id)}/retry?force_mock=true",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()

    assert data["status"] == "SENT"
    assert data["retry_count"] == 1
    assert data["failure_reason"] is None


@pytest.mark.asyncio
async def test_provider_status_api(
    client_async: AsyncClient,
    auth_headers: Dict[str, str],
):
    """Test 10: Provider status API clearly indicates configuration states."""
    resp = await client_async.get(
        "/data-extractions/notifications/providers/status",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "providers" in data
    channels = [p["channel"] for p in data["providers"]]
    assert "EMAIL" in channels
    assert "SMS" in channels
    assert "WHATSAPP" in channels


@pytest.mark.asyncio
async def test_student_notification_status_table_api(
    client_async: AsyncClient,
    auth_headers: Dict[str, str],
    sample_extraction_fixture: Dict[str, Any],
):
    """Test 11: Candidate status table returns aggregated verification and communication progress."""
    fix = sample_extraction_fixture
    ext_id = fix["extraction_id"]

    resp = await client_async.get(
        f"/data-extractions/{ext_id}/notifications/students",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["student_id"] == fix["student_id"]
    assert rows[0]["has_token"] is True
    assert rows[0]["verification_status"] is not None


@pytest.mark.asyncio
async def test_authorization_enforced(
    client_async: AsyncClient,
    sample_extraction_fixture: Dict[str, Any],
):
    """Test 12: Unauthenticated requests and students cannot access notification endpoints."""
    ext_id = sample_extraction_fixture["extraction_id"]

    # 1. No auth headers -> 401
    resp_no_auth = await client_async.post(
        f"/data-extractions/{ext_id}/notifications/send",
        json={"student_id": "STU1", "channel": "EMAIL"},
    )
    assert resp_no_auth.status_code == 401

    # 2. Public verification token cannot access staff notification API -> 401
    resp_token_auth = await client_async.get(
        f"/data-extractions/{ext_id}/notifications",
        headers={"Authorization": f"Bearer {sample_extraction_fixture['token_str']}"},
    )
    assert resp_token_auth.status_code == 401


@pytest.mark.asyncio
async def test_extraction_request_immutability(
    client_async: AsyncClient,
    auth_headers: Dict[str, str],
    sample_extraction_fixture: Dict[str, Any],
):
    """Test 13: Notification dispatch does not alter or corrupt the underlying extraction request data."""
    fix = sample_extraction_fixture
    ext_id = fix["extraction_id"]

    # Check extraction before
    before_req = await BatchExtractionRequest.find_one(
        BatchExtractionRequest.extraction_request_id == ext_id
    )
    fields_before = before_req.requested_fields

    # Send notification
    await client_async.post(
        f"/data-extractions/{ext_id}/notifications/send?force_mock=true",
        json={"student_id": fix["student_id"], "channel": "EMAIL"},
        headers=auth_headers,
    )

    # Check extraction after
    after_req = await BatchExtractionRequest.find_one(
        BatchExtractionRequest.extraction_request_id == ext_id
    )
    assert after_req.requested_fields == fields_before
    assert after_req.status == BatchExtractionStatus.COMPLETED.value

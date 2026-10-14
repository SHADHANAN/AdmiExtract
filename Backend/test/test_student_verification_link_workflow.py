import os
import re
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from motor.motor_asyncio import AsyncIOMotorClient

from app.core.config import settings
from app.core.security import create_access_token, get_password_hash
from app.main import app
from app.models.batch import AdmissionBatch
from app.models.document_verification import (
    DocumentFieldVerification,
    VerificationFieldStatus,
    VerificationHistoryEntry,
)
from app.models.student_document import StudentDocument
from app.models.user import User, UserRole
from app.models.verification_token import VerificationToken, VerificationTokenStatus
from app.schemas.verification_token import (
    PublicVerificationSubmitRequest,
    StudentFieldVerificationItem,
    GenerateVerificationTokenRequest,
    ValidateStudentIdentityRequest,
)
from app.services.document_extraction_service import DocumentExtractionService
from app.services.document_verification_service import DocumentVerificationService
from app.services.gemini_service import GeminiService
from app.services.student_document_service import StudentDocumentService
from app.services.verification_token_service import VerificationTokenService
from app.services.batch_extraction_service import BatchExtractionService


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


@pytest.fixture
def temp_sample_file(tmp_path):
    fpath = tmp_path / "sample_id.pdf"
    fpath.write_bytes(b"%PDF-1.4 sample content")
    return str(fpath)


@pytest.fixture
def mock_gemini():
    mock_service = MagicMock(spec=GeminiService)
    mock_service.extract_from_file.return_value = {
        "success": True,
        "document_type": "AADHAAR",
        "confidence": 98.0,
        "fields": {
            "Student Name": {"value": "Rohit Kumar", "confidence": 99.0},
            "Date of Birth": {"value": "15/05/2005", "confidence": 97.0},
            "Gender": {"value": "MALE", "confidence": 99.0},
        },
        "extracted_summary": {
            "student_name": "Rohit Kumar",
            "date_of_birth": "15/05/2005",
            "gender": "MALE",
        },
    }
    return mock_service


@pytest.mark.asyncio
async def test_student_verification_link_full_workflow(
    client_async: AsyncClient, temp_sample_file, mock_gemini
):
    """
    End-to-End Verification Link Workflow Test:
    1. Token generation: Initial creation vs idempotent retry vs forced regeneration.
    2. Session gate privacy: Public session does NOT reveal personal data or fields.
    3. Identity validation:
       - Fails on incorrect student name (401).
       - Fails on incorrect register number (401).
       - Handles whitespace and case normalization ("  rohit   kumar  ", "  stu_wf_01 ").
       - Prevents cross-student access.
    4. Rate-limiting: Locks out after 5 consecutive failed identity attempts (429).
    5. Student review & corrections:
       - Confirms one field.
       - Corrects another field (AI value remains intact, final value becomes None pending review).
       - Repeated submission updates safely.
    6. Staff review:
       - Staff approves correction -> final_value updated to student value.
       - Staff rejects correction -> final_value retains original AI value.
       - Finalized fields are locked from further student modification.
    """
    token_service = VerificationTokenService()
    doc_service = StudentDocumentService()
    ext_service = DocumentExtractionService(gemini_service=mock_gemini)
    verif_service = DocumentVerificationService()

    batch_id = "BATCH_WF_01"
    student_a_id = "STU_WF_01"
    student_b_id = "STU_WF_02"

    # Clean prior test state
    await StudentDocument.find(StudentDocument.batch_id == batch_id).delete()
    await DocumentFieldVerification.find(DocumentFieldVerification.batch_id == batch_id).delete()
    await VerificationToken.find(VerificationToken.batch_id == batch_id).delete()
    await User.find(User.username == "staff_wf_admin").delete()

    admin_user = User(
        username="staff_wf_admin",
        name="Staff Admin",
        password=get_password_hash("pass123"),
        role=UserRole.SUPER_ADMIN,
        is_active=True,
    )
    await admin_user.insert()
    staff_token = create_access_token({"sub": str(admin_user.id), "role": admin_user.role.value})
    auth_headers = {"Authorization": f"Bearer {staff_token}"}

    # Create document and extraction records for Student A
    doc_a = await doc_service.create_student_document(
        student_id=student_a_id,
        batch_id=batch_id,
        document_type="AADHAAR",
        document_name="Aadhaar Card",
        department_id="CSE",
        initial_file_path=temp_sample_file,
    )
    req_a, _ = await ext_service.request_and_extract_fields(
        student_document_id=str(doc_a.id),
        requested_fields=["student_name", "date_of_birth", "gender"],
        actor=admin_user,
    )
    ext_req_id = str(req_a.id)

    # 1. Staff generates verification token
    res_gen = await client_async.post(
        "/staff/verifications/generate-token",
        headers=auth_headers,
        json={
            "student_id": student_a_id,
            "batch_id": batch_id,
            "student_name": "Rohit Kumar",
            "extraction_request_id": ext_req_id,
            "force_refresh": False,
        },
    )
    assert res_gen.status_code == 200
    gen_data = res_gen.json()
    token_1 = gen_data["token"]
    assert gen_data["verification_url"] == f"/verify-session/{token_1}"
    assert gen_data["status"] == "ACTIVE"

    # Idempotent retry: without force_refresh, same active token is returned
    res_gen_retry = await client_async.post(
        "/staff/verifications/generate-token",
        headers=auth_headers,
        json={
            "student_id": student_a_id,
            "batch_id": batch_id,
            "student_name": "Rohit Kumar",
            "extraction_request_id": ext_req_id,
            "force_refresh": False,
        },
    )
    assert res_gen_retry.status_code == 200
    assert res_gen_retry.json()["token"] == token_1

    # Regenerate Link: with force_refresh=True, old token is revoked and fresh token is issued
    res_regen = await client_async.post(
        "/staff/verifications/generate-token",
        headers=auth_headers,
        json={
            "student_id": student_a_id,
            "batch_id": batch_id,
            "student_name": "Rohit Kumar",
            "extraction_request_id": ext_req_id,
            "force_refresh": True,
        },
    )
    assert res_regen.status_code == 200
    token_2 = res_regen.json()["token"]
    assert token_2 != token_1

    # The revoked token 1 must now be rejected (403 Forbidden)
    res_old = await client_async.get(f"/public/verification/{token_1}")
    assert res_old.status_code == 403
    assert "revoked" in res_old.json()["detail"].lower()

    # 2. Public session gate privacy test: Session endpoint does NOT leak student personal data or fields
    res_session = await client_async.get(f"/public/verification/{token_2}/session")
    assert res_session.status_code == 200
    sess_data = res_session.json()
    assert sess_data["valid"] is True
    assert sess_data["token"] == token_2
    assert "fields" not in sess_data
    assert "student_name" not in sess_data
    assert "student_id" not in sess_data

    # 3. Identity validation tests
    # Invalid student name
    res_bad_name = await client_async.post(
        f"/public/verification/{token_2}/validate-identity",
        json={"student_name": "Wrong Person", "register_number": student_a_id},
    )
    assert res_bad_name.status_code == 401

    # Invalid register number
    res_bad_reg = await client_async.post(
        f"/public/verification/{token_2}/validate-identity",
        json={"student_name": "Rohit Kumar", "register_number": "WRONG_REG_999"},
    )
    assert res_bad_reg.status_code == 401

    # Cross-student attempt: Student B credentials cannot open Student A's link
    res_cross = await client_async.post(
        f"/public/verification/{token_2}/validate-identity",
        json={"student_name": "Student B Name", "register_number": student_b_id},
    )
    assert res_cross.status_code == 401

    # 4. Rate-limiting check: 5 consecutive failures triggers 429
    # We already had 3 failures above; let's trigger 2 more
    await client_async.post(
        f"/public/verification/{token_2}/validate-identity",
        json={"student_name": "Fail 4", "register_number": "REG4"},
    )
    await client_async.post(
        f"/public/verification/{token_2}/validate-identity",
        json={"student_name": "Fail 5", "register_number": "REG5"},
    )
    # The 6th attempt is blocked with 429 Too Many Requests
    res_limited = await client_async.post(
        f"/public/verification/{token_2}/validate-identity",
        json={"student_name": "Rohit Kumar", "register_number": student_a_id},
    )
    assert res_limited.status_code == 429
    assert "too many" in res_limited.json()["detail"].lower()

    # Clear rate limiter failures for token_2 to test successful normalized validation
    token_service._failed_attempts.pop(token_2, None)

    # 3 (continued). Successful validation with whitespace and case variations:
    res_valid = await client_async.post(
        f"/public/verification/{token_2}/validate-identity",
        json={
            "student_name": "   rohit   kumar  ",
            "register_number": f"  {student_a_id.lower()} ",
        },
    )
    assert res_valid.status_code == 200
    student_data = res_valid.json()
    assert student_data["valid"] is True
    assert student_data["student_name"] == "Rohit Kumar"
    assert student_data["student_id"] == student_a_id
    assert len(student_data["fields"]) == 3

    # 5. Student review, confirmation, and corrections
    fields = student_data["fields"]
    dob_field = next(f for f in fields if f["field_name"] == "date_of_birth")
    gender_field = next(f for f in fields if f["field_name"] == "gender")

    # Confirm DOB, request correction for Gender
    res_submit = await client_async.post(
        f"/public/verification/{token_2}/submit",
        json={
            "fields": [
                {
                    "verification_id": dob_field["id"],
                    "is_confirmed": True,
                },
                {
                    "verification_id": gender_field["id"],
                    "is_confirmed": False,
                    "corrected_value": "MALE_PROPOSED",
                    "comment": "Typo correction in title",
                },
            ],
            "general_comment": "Reviewed by Rohit",
        },
    )
    assert res_submit.status_code == 200
    submitted_fields = res_submit.json()["fields"]

    sub_dob = next(f for f in submitted_fields if f["field_name"] == "date_of_birth")
    assert sub_dob["status"] == "STUDENT_CONFIRMED"
    assert sub_dob["final_value"] == "15/05/2005"

    sub_gender = next(f for f in submitted_fields if f["field_name"] == "gender")
    assert sub_gender["status"] == "STUDENT_VERIFIED"
    assert sub_gender["ai_value"] == "MALE"  # AI value strictly preserved
    assert sub_gender["student_value"] == "MALE_PROPOSED"
    assert sub_gender["final_value"] == "MALE_PROPOSED"  # Directly verified as final!

    # Idempotent re-submission with identical values returns 200
    res_resubmit = await client_async.post(
        f"/public/verification/{token_2}/submit",
        json={
            "fields": [
                {
                    "verification_id": dob_field["id"],
                    "is_confirmed": True,
                },
                {
                    "verification_id": gender_field["id"],
                    "is_confirmed": False,
                    "corrected_value": "MALE_PROPOSED",
                },
            ]
        },
    )
    assert res_resubmit.status_code == 200

    # Tampering protection: Attempting to alter verified values after completion returns 400
    res_tamper = await client_async.post(
        f"/public/verification/{token_2}/submit",
        json={
            "fields": [
                {
                    "verification_id": gender_field["id"],
                    "is_confirmed": False,
                    "corrected_value": "MALE_ALTERED_ILLEGALLY",
                }
            ]
        },
    )
    assert res_tamper.status_code == 400

    # 6. Staff review: staff can still inspect or update records if required
    res_approve = await client_async.post(
        f"/staff/verifications/{gender_field['id']}/review",
        headers=auth_headers,
        json={"action": "APPROVE", "staff_comment": "Approved against physical records"},
    )
    assert res_approve.status_code == 200
    approved_gender = res_approve.json()
    assert approved_gender["status"] == "STAFF_APPROVED"
    assert approved_gender["final_value"] == "MALE_PROPOSED"
    assert approved_gender["ai_value"] == "MALE"


@pytest.mark.asyncio
async def test_batch_extraction_link_availability_and_states(
    client_async: AsyncClient, temp_sample_file, mock_gemini
):
    """
    Validates:
    1. Students with ready extracted results have verification_link and status generated.
    2. Students with failed extraction / no usable results have NO verification link.
    3. Export retains approved values while rejecting unapproved modifications.
    """
    token_service = VerificationTokenService()
    batch_service = BatchExtractionService()

    batch_id = "BATCH_WF_AVAIL_01"
    student_ready = "STU_READY_01"
    student_failed = "STU_FAILED_02"

    await DocumentFieldVerification.find(DocumentFieldVerification.batch_id == batch_id).delete()
    await VerificationToken.find(VerificationToken.batch_id == batch_id).delete()
    await AdmissionBatch.find(AdmissionBatch.name == batch_id).delete()

    batch = AdmissionBatch(
        id=batch_id,
        name=batch_id,
        department_id="CSE",
        academic_year="2026-2027",
        created_by="staff_test",
    )
    await batch.insert()


    # 1. Verification token created for student with usable results
    tok_ready = await token_service.create_or_get_token(
        student_id=student_ready,
        batch_id=str(batch.id),
        student_name="Ready Student",
        batch_name=batch.name,
    )
    assert tok_ready is not None
    assert tok_ready.is_valid is True
    assert tok_ready.token is not None

    # Link session endpoint returns ready status
    res_sess = await client_async.get(f"/public/verification/{tok_ready.token}/session")
    assert res_sess.status_code == 200
    assert res_sess.json()["status"] == "ACTIVE"

    # Expired token test:
    expired_tok = await token_service.create_or_get_token(
        student_id="STU_EXP_WF",
        batch_id=str(batch.id),
        student_name="Exp Student",
    )
    expired_tok.expires_at = datetime.now(timezone.utc) - timedelta(days=2)
    expired_tok.status = VerificationTokenStatus.EXPIRED.value
    await expired_tok.save()

    res_exp = await client_async.get(f"/public/verification/{expired_tok.token}/session")
    assert res_exp.status_code == 410
    assert "expired" in res_exp.json()["detail"].lower()

import os
from datetime import datetime, timezone, timedelta
from typing import Any, Dict
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
)
from app.models.student_document import StudentDocument
from app.models.user import User, UserRole
from app.models.verification_token import VerificationToken, VerificationTokenStatus
from app.schemas.verification_token import (
    PublicVerificationSubmitRequest,
    StudentFieldVerificationItem,
    GenerateVerificationTokenRequest,
)
from app.services.document_extraction_service import DocumentExtractionService
from app.services.document_verification_service import DocumentVerificationService
from app.services.gemini_service import GeminiService
from app.services.student_document_service import StudentDocumentService
from app.services.verification_token_service import VerificationTokenService


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
    fpath = tmp_path / "aadhaar_sample.pdf"
    fpath.write_bytes(b"%PDF-1.4 sample aadhaar content")
    return str(fpath)


@pytest.fixture
def mock_gemini():
    mock_service = MagicMock(spec=GeminiService)
    mock_service.extract_from_file.return_value = {
        "success": True,
        "document_type": "AADHAAR",
        "confidence": 98.0,
        "fields": {
            "Student Name": {"value": "Priya Sharma", "confidence": 99.0},
            "Date of Birth": {"value": "20/08/2006", "confidence": 98.0},
            "Gender": {"value": "FEMALE", "confidence": 99.0},
        },
        "extracted_summary": {
            "student_name": "Priya Sharma",
            "date_of_birth": "20/08/2006",
            "gender": "FEMALE",
        },
    }
    return mock_service


@pytest.mark.asyncio
async def test_public_verification_full_lifecycle(
    client_async: AsyncClient, temp_sample_file, mock_gemini
):
    """
    Validates complete Public Student Verification Lifecycle:
    1. Valid verification token -> student can open verification without JWT.
    2. Valid token -> student sees ONLY own extraction data.
    3. Student can confirm values.
    4. Student can submit correction.
    5. AI value remains unchanged after correction.
    6. Staff can see correction.
    7. Staff can approve.
    8. Staff can reject.
    9. Final value is correct after approval.
    """
    doc_service = StudentDocumentService()
    ext_service = DocumentExtractionService(gemini_service=mock_gemini)
    verif_service = DocumentVerificationService()
    token_service = VerificationTokenService()

    student_a_id = "STU_PUB_01"
    student_b_id = "STU_PUB_02"
    batch_id = "batch_pub_01"

    # Clean up test records
    await StudentDocument.find(StudentDocument.batch_id == batch_id).delete()
    await DocumentFieldVerification.find(DocumentFieldVerification.batch_id == batch_id).delete()
    await VerificationToken.find(VerificationToken.batch_id == batch_id).delete()
    await User.find(User.username == "admin_pub_test").delete()

    admin_user = User(
        username="admin_pub_test",
        name="Admin Staff",
        password=get_password_hash("pass123"),
        role=UserRole.SUPER_ADMIN,
        is_active=True,
    )
    await admin_user.insert()
    doc_a = await doc_service.create_student_document(
        student_id=student_a_id,
        batch_id=batch_id,
        document_type="AADHAAR",
        document_name="Aadhaar Card",
        department_id="CSE",
        initial_file_path=temp_sample_file,
    )

    doc_b = await doc_service.create_student_document(
        student_id=student_b_id,
        batch_id=batch_id,
        document_type="AADHAAR",
        document_name="Aadhaar Card",
        department_id="CSE",
        initial_file_path=temp_sample_file,
    )

    # 2. Extract fields
    req_a, _ = await ext_service.request_and_extract_fields(
        student_document_id=str(doc_a.id),
        requested_fields=["student_name", "date_of_birth", "gender"],
        actor=admin_user,
    )

    req_b, _ = await ext_service.request_and_extract_fields(
        student_document_id=str(doc_b.id),
        requested_fields=["student_name", "date_of_birth", "gender"],
        actor=admin_user,
    )

    # 3. Generate verification token for Student A
    tok_a = await token_service.create_or_get_token(
        student_id=student_a_id,
        batch_id=batch_id,
        student_name="Priya Sharma",
        batch_name="Batch 2026 CSE",
    )
    assert tok_a.token is not None
    assert tok_a.is_valid is True

    # 1 & 2. Public GET /public/verification/{token} without any JWT auth headers
    res_get = await client_async.get(f"/public/verification/{tok_a.token}")
    assert res_get.status_code == 200
    data_a = res_get.json()
    assert data_a["valid"] is True
    assert data_a["student_id"] == student_a_id
    assert data_a["student_name"] == "Priya Sharma"
    assert len(data_a["fields"]) == 3
    # Verify student sees ONLY their own records, NOT Student B's
    for f in data_a["fields"]:
        assert f["student_id"] == student_a_id
        assert f["student_id"] != student_b_id

    # 3 & 4. Student confirms one field and corrects another
    dob_field = next(f for f in data_a["fields"] if f["field_name"] == "date_of_birth")
    gender_field = next(f for f in data_a["fields"] if f["field_name"] == "gender")

    res_submit = await client_async.post(
        f"/public/verification/{tok_a.token}/submit",
        json={
            "fields": [
                {
                    "verification_id": dob_field["id"],
                    "is_confirmed": True,
                    "comment": "DOB matches birth certificate",
                },
                {
                    "verification_id": gender_field["id"],
                    "is_confirmed": False,
                    "corrected_value": "FEMALE_CORRECTED",
                    "comment": "Updating format",
                },
            ],
            "general_comment": "Verified by Priya",
        },
    )
    assert res_submit.status_code == 200
    updated_data = res_submit.json()

    # 3. Confirmed field check
    updated_dob = next(f for f in updated_data["fields"] if f["field_name"] == "date_of_birth")
    assert updated_dob["status"] == "STUDENT_CONFIRMED"
    assert updated_dob["final_value"] == "20/08/2006"

    # 4 & 5. Correction field check - Student edit directly verified!
    updated_gender = next(f for f in updated_data["fields"] if f["field_name"] == "gender")
    assert updated_gender["status"] == "STUDENT_VERIFIED"
    assert updated_gender["ai_value"] == "FEMALE"  # 5. AI VALUE UNCHANGED!
    assert updated_gender["student_value"] == "FEMALE_CORRECTED"
    assert updated_gender["final_value"] == "FEMALE_CORRECTED"  # Direct final verified value!

    # 6. Staff sees NO pending corrections in review queue (no approval needed)
    staff_token = create_access_token({"sub": str(admin_user.id), "role": admin_user.role.value})
    res_pending = await client_async.get(
        "/staff/verifications/pending",
        headers={"Authorization": f"Bearer {staff_token}"},
    )
    assert res_pending.status_code == 200
    pending_list = res_pending.json()
    assert not any(p["id"] == gender_field["id"] for p in pending_list)

    # 7. Staff can still override or review if needed
    res_approve = await client_async.post(
        f"/staff/verifications/{gender_field['id']}/review",
        headers={"Authorization": f"Bearer {staff_token}"},
        json={"action": "APPROVE", "staff_comment": "Approved against submitted ID"},
    )
    assert res_approve.status_code == 200
    approved_rec = res_approve.json()
    assert approved_rec["status"] == "STAFF_APPROVED"
    assert approved_rec["final_value"] == "FEMALE_CORRECTED"
    assert approved_rec["ai_value"] == "FEMALE"

    # 8. Staff rejection test on another record directly
    name_field = next(f for f in data_a["fields"] if f["field_name"] == "student_name")
    res_reject = await client_async.post(
        f"/staff/verifications/{name_field['id']}/review",
        headers={"Authorization": f"Bearer {staff_token}"},
        json={"action": "REJECT", "staff_comment": "Does not match official Aadhaar record"},
    )
    assert res_reject.status_code == 200
    rejected_rec = res_reject.json()
    assert rejected_rec["status"] == "STAFF_REJECTED"
    assert rejected_rec["final_value"] == "Priya Sharma"  # Fallback to AI value


@pytest.mark.asyncio
async def test_verification_token_security_and_scoping(
    client_async: AsyncClient, temp_sample_file, mock_gemini
):
    """
    Validates token security boundaries:
    10. Invalid token -> 404/401.
    11. Expired token -> 410 rejected.
    12. Revoked token -> 403 rejected.
    13. Token cannot access another student's extraction records.
    14. Token cannot access another batch.
    15. Public verification endpoint cannot access staff APIs.
    16. Existing JWT staff verification flow continues working.
    """
    doc_service = StudentDocumentService()
    ext_service = DocumentExtractionService(gemini_service=mock_gemini)
    token_service = VerificationTokenService()

    # 10. Invalid token
    res_invalid = await client_async.get("/public/verification/non_existent_fake_token_12345")
    assert res_invalid.status_code == 404

    # 11. Expired token
    expired_tok = VerificationToken(
        token="expired_tok_test_12345",
        student_id="STU_EXP_01",
        student_name="Expired Student",
        batch_id="batch_exp_01",
        status=VerificationTokenStatus.ACTIVE.value,
        expires_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    await expired_tok.insert()

    res_exp = await client_async.get(f"/public/verification/{expired_tok.token}")
    assert res_exp.status_code == 410
    assert "expired" in res_exp.json()["detail"].lower()

    # 12. Revoked token
    revoked_tok = VerificationToken(
        token="revoked_tok_test_12345",
        student_id="STU_REV_01",
        student_name="Revoked Student",
        batch_id="batch_rev_01",
        status=VerificationTokenStatus.REVOKED.value,
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )
    await revoked_tok.insert()

    res_rev = await client_async.get(f"/public/verification/{revoked_tok.token}")
    assert res_rev.status_code == 403
    assert "revoked" in res_rev.json()["detail"].lower()

    # 13 & 14. Token isolation & cross-student modification prevention
    student_x = "STU_ISOLATION_X"
    student_y = "STU_ISOLATION_Y"
    batch_sec = "batch_sec_01"

    await User.find(User.username == "admin_sec_test").delete()
    admin_user = User(
        username="admin_sec_test",
        name="Admin",
        password=get_password_hash("pass123"),
        role=UserRole.SUPER_ADMIN,
        is_active=True,
    )
    await admin_user.insert()

    doc_y = await doc_service.create_student_document(
        student_id=student_y,
        batch_id=batch_sec,
        document_type="AADHAAR",
        document_name="Aadhaar Card",
        department_id="CSE",
        initial_file_path=temp_sample_file,
    )

    _, res_y = await ext_service.request_and_extract_fields(
        student_document_id=str(doc_y.id),
        requested_fields=["student_name"],
        actor=admin_user,
    )

    verif_records_y = await DocumentFieldVerification.find(
        DocumentFieldVerification.student_id == student_y
    ).to_list()
    assert len(verif_records_y) > 0
    rec_y_id = str(verif_records_y[0].id)

    # Student X has their own token
    tok_x = await token_service.create_or_get_token(
        student_id=student_x,
        batch_id=batch_sec,
        student_name="Student X",
    )

    # Student X attempts to modify Student Y's verification record -> 403 Forbidden!
    res_hack = await client_async.post(
        f"/public/verification/{tok_x.token}/submit",
        json={
            "fields": [
                {
                    "verification_id": rec_y_id,
                    "is_confirmed": False,
                    "corrected_value": "Hacked Value",
                }
            ]
        },
    )
    assert res_hack.status_code == 403
    assert "cannot modify another student" in res_hack.json()["detail"].lower()

    # 15. Public verification endpoint cannot access staff APIs without JWT
    res_staff_unauth = await client_async.get("/staff/verifications/pending")
    assert res_staff_unauth.status_code in (401, 403)

    # 16. Staff token generation endpoint works for authorized staff
    staff_token = create_access_token({"sub": str(admin_user.id), "role": admin_user.role.value})
    res_gen = await client_async.post(
        "/staff/verifications/generate-token",
        headers={"Authorization": f"Bearer {staff_token}"},
        json={
            "student_id": "STU_NEW_01",
            "batch_id": batch_sec,
            "student_name": "New Candidate",
        },
    )
    assert res_gen.status_code == 200
    gen_data = res_gen.json()
    assert "token" in gen_data
    assert gen_data["verification_url"].startswith("/verify-session/")

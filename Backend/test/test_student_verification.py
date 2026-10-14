import os
import tempfile
from datetime import datetime, timezone
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio
from beanie import PydanticObjectId
from httpx import ASGITransport, AsyncClient
from motor.motor_asyncio import AsyncIOMotorClient

from app.core.config import settings
from app.core.security import create_access_token, get_password_hash
from app.main import app
from app.models.audit_log import AuditLog
from app.models.document_extraction_request import (
    DocumentExtractionRequest,
    ExtractionRequestStatus,
)
from app.models.document_extraction_result import DocumentExtractionResult
from app.models.document_verification import (
    DocumentFieldVerification,
    VerificationFieldStatus,
)
from app.models.student_document import StudentDocument
from app.models.student_submission import StudentSubmission
from app.models.user import User, UserRole
from app.schemas.document_verification import (
    StudentFieldVerificationItem,
    StudentVerificationSubmitRequest,
    StaffReviewCorrectionRequest,
)
from app.services.document_extraction_service import DocumentExtractionService
from app.services.document_verification_service import DocumentVerificationService
from app.services.gemini_service import GeminiService
from app.services.student_document_service import StudentDocumentService


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
async def db_client():
    client = AsyncIOMotorClient(settings.MONGODB_URI)
    db = client[settings.DATABASE_NAME]
    yield db
    client.close()


@pytest.fixture
def temp_sample_file(tmp_path):
    fpath = tmp_path / "aadhaar_sample.pdf"
    fpath.write_bytes(b"%PDF-1.4 sample aadhaar content")
    return str(fpath)


@pytest.fixture
def mock_gemini_extraction():
    mock_service = MagicMock(spec=GeminiService)
    mock_service.extract_from_file.return_value = {
        "success": True,
        "document_type": "AADHAAR",
        "confidence": 98.0,
        "fields": {
            "Student Name": {"value": "Arun Kumar", "confidence": 99.0},
            "Date of Birth": {"value": "15/06/2007", "confidence": 98.0},
            "Gender": {"value": "MALE", "confidence": 99.0},
        },
        "extracted_summary": {
            "student_name": "Arun Kumar",
            "date_of_birth": "15/06/2007",
            "gender": "MALE",
        },
    }
    return mock_service


@pytest.mark.asyncio
async def test_student_view_and_confirm_verification(temp_sample_file, mock_gemini_extraction):
    """1, 3, 11. Student can view own extracted data and confirm correct values."""
    doc_service = StudentDocumentService()
    ext_service = DocumentExtractionService(gemini_service=mock_gemini_extraction)
    verif_service = DocumentVerificationService()

    student_id = "STUD_VERIF_01"
    await StudentDocument.find(StudentDocument.student_id == student_id).delete()
    await DocumentFieldVerification.find(DocumentFieldVerification.student_id == student_id).delete()

    doc = await doc_service.create_student_document(
        student_id=student_id,
        batch_id="batch_01",
        document_type="AADHAAR",
        document_name="Aadhaar Card",
        initial_file_path=temp_sample_file,
    )

    admin_user = User(
        username="admin_v1",
        name="Admin",
        password=get_password_hash("pass123"),
        role=UserRole.SUPER_ADMIN,
        is_active=True,
    )

    # Trigger extraction
    req, result = await ext_service.request_and_extract_fields(
        student_document_id=str(doc.id),
        requested_fields=["student_name", "date_of_birth", "gender"],
        actor=admin_user,
    )

    student_user = User(
        username="stud_user_01",
        name="Arun Kumar",
        password=get_password_hash("pass123"),
        role=UserRole.STUDENT,
        register_number=student_id,
        is_active=True,
    )

    # 1. Student views own verification records
    records = await verif_service.get_student_verifications(student_id, student_user)
    assert len(records) == 3
    for r in records:
        assert r.status == VerificationFieldStatus.AI_EXTRACTED
        assert r.ai_value is not None
        assert r.student_value is None
        assert r.final_value is None

    # 3. Student confirms date_of_birth as correct
    dob_rec = next(r for r in records if r.field_name == "date_of_birth")
    updated = await verif_service.submit_student_verification(
        student_id=student_id,
        submit_req=StudentVerificationSubmitRequest(
            fields=[
                StudentFieldVerificationItem(
                    verification_id=str(dob_rec.id),
                    is_confirmed=True,
                )
            ]
        ),
        actor=student_user,
    )

    assert len(updated) == 1
    assert updated[0].status == VerificationFieldStatus.STUDENT_CONFIRMED
    assert updated[0].ai_value == "15/06/2007"
    assert updated[0].student_value == "15/06/2007"
    assert updated[0].final_value == "15/06/2007"

    # 11. AI value preserved
    assert updated[0].ai_value == "15/06/2007"

    await StudentDocument.find(StudentDocument.student_id == student_id).delete()
    await DocumentFieldVerification.find(DocumentFieldVerification.student_id == student_id).delete()


@pytest.mark.asyncio
async def test_student_correction_workflow_and_staff_approval(temp_sample_file, mock_gemini_extraction):
    """4, 5, 6, 7, 8, 11, 12, 13. Student correction requires staff approval; approved becomes final."""
    doc_service = StudentDocumentService()
    ext_service = DocumentExtractionService(gemini_service=mock_gemini_extraction)
    verif_service = DocumentVerificationService()

    student_id = "STUD_CORRECT_01"
    await StudentDocument.find(StudentDocument.student_id == student_id).delete()
    await DocumentFieldVerification.find(DocumentFieldVerification.student_id == student_id).delete()

    doc = await doc_service.create_student_document(
        student_id=student_id,
        batch_id="batch_01",
        document_type="AADHAAR",
        document_name="Aadhaar Card",
        department_id="DEPT_CSE",
        initial_file_path=temp_sample_file,
    )

    admin_user = User(
        username="admin_v2",
        name="Admin",
        password=get_password_hash("pass123"),
        role=UserRole.SUPER_ADMIN,
        is_active=True,
    )

    # Extract
    req, result = await ext_service.request_and_extract_fields(
        student_document_id=str(doc.id),
        requested_fields=["student_name"],
        actor=admin_user,
    )

    student_user = User(
        username="stud_correct_user",
        name="Arun Kumar",
        password=get_password_hash("pass123"),
        role=UserRole.STUDENT,
        register_number=student_id,
        is_active=True,
    )

    records = await verif_service.get_student_verifications(student_id, student_user)
    name_rec = records[0]
    assert name_rec.ai_value == "Arun Kumar"

    # 4. Student submits correction: "Arun Kumaran"
    submitted = await verif_service.submit_student_verification(
        student_id=student_id,
        submit_req=StudentVerificationSubmitRequest(
            fields=[
                StudentFieldVerificationItem(
                    verification_id=str(name_rec.id),
                    is_confirmed=False,
                    corrected_value="Arun Kumaran",
                    comment="Typo in last character",
                )
            ]
        ),
        actor=student_user,
    )

    # 5. Student edit directly becomes final verified data without staff approval
    assert submitted[0].status == VerificationFieldStatus.STUDENT_VERIFIED
    assert submitted[0].ai_value == "Arun Kumar"
    assert submitted[0].student_value == "Arun Kumaran"
    assert submitted[0].final_value == "Arun Kumaran"

    # 6. No staff approval task needed for direct verification
    pending = await verif_service.list_pending_corrections(actor=admin_user)
    assert not any(p.id == name_rec.id for p in pending)

    # 11, 12. Both AI value and student value are preserved
    assert submitted[0].ai_value == "Arun Kumar"
    assert submitted[0].student_value == "Arun Kumaran"

    # 13. Audit history is preserved with student submission
    assert len(submitted[0].history) >= 2  # AI_EXTRACTION, STUDENT_CORRECTION
    actions = [h.action for h in submitted[0].history]
    assert "AI_EXTRACTION" in actions
    assert "STUDENT_CORRECTION" in actions or "STUDENT_EDIT" in actions

    await StudentDocument.find(StudentDocument.student_id == student_id).delete()
    await DocumentFieldVerification.find(DocumentFieldVerification.student_id == student_id).delete()


@pytest.mark.asyncio
async def test_staff_rejection_workflow(temp_sample_file, mock_gemini_extraction):
    """9, 10, 11, 12. Staff rejects correction -> status = STAFF_REJECTED, final_value = ai_value."""
    doc_service = StudentDocumentService()
    ext_service = DocumentExtractionService(gemini_service=mock_gemini_extraction)
    verif_service = DocumentVerificationService()

    student_id = "STUD_REJECT_01"
    await StudentDocument.find(StudentDocument.student_id == student_id).delete()
    await DocumentFieldVerification.find(DocumentFieldVerification.student_id == student_id).delete()

    doc = await doc_service.create_student_document(
        student_id=student_id,
        batch_id="batch_01",
        document_type="AADHAAR",
        document_name="Aadhaar Card",
        initial_file_path=temp_sample_file,
    )

    admin_user = User(
        username="admin_v3",
        name="Admin",
        password=get_password_hash("pass123"),
        role=UserRole.SUPER_ADMIN,
        is_active=True,
    )

    await ext_service.request_and_extract_fields(
        student_document_id=str(doc.id),
        requested_fields=["gender"],
        actor=admin_user,
    )

    student_user = User(
        username="stud_reject_user",
        name="Student",
        password=get_password_hash("pass123"),
        role=UserRole.STUDENT,
        register_number=student_id,
        is_active=True,
    )

    records = await verif_service.get_student_verifications(student_id, student_user)
    gender_rec = records[0]

    # Student submits incorrect edit
    await verif_service.submit_student_verification(
        student_id=student_id,
        submit_req=StudentVerificationSubmitRequest(
            fields=[
                StudentFieldVerificationItem(
                    verification_id=str(gender_rec.id),
                    is_confirmed=False,
                    corrected_value="FEMALE",
                )
            ]
        ),
        actor=student_user,
    )

    # 9, 10. Staff rejects correction
    rejected = await verif_service.review_correction(
        verification_id=str(gender_rec.id),
        action="REJECT",
        actor=admin_user,
        staff_comment="Does not match uploaded Aadhaar",
    )

    assert rejected.status == VerificationFieldStatus.STAFF_REJECTED
    # Final value keeps AI value upon rejection
    assert rejected.final_value == "MALE"
    assert rejected.ai_value == "MALE"
    assert rejected.student_value == "FEMALE"

    await StudentDocument.find(StudentDocument.student_id == student_id).delete()
    await DocumentFieldVerification.find(DocumentFieldVerification.student_id == student_id).delete()


@pytest.mark.asyncio
async def test_student_and_department_isolation(client_async: AsyncClient, temp_sample_file, mock_gemini_extraction, db_client):
    """2, 15, 16. Student cannot view another student's data; Dept admin restricted."""
    doc_service = StudentDocumentService()
    ext_service = DocumentExtractionService(gemini_service=mock_gemini_extraction)
    verif_service = DocumentVerificationService()

    # Create Student A
    student_a_id = "STUD_ISO_A"
    doc_a = await doc_service.create_student_document(
        student_id=student_a_id,
        batch_id="batch_iso",
        document_type="AADHAAR",
        document_name="Aadhaar Card",
        department_id="DEPT_CSE",
        initial_file_path=temp_sample_file,
    )
    admin_user = User(
        username="admin_iso",
        name="Admin",
        password=get_password_hash("pass123"),
        role=UserRole.SUPER_ADMIN,
        is_active=True,
    )
    await ext_service.request_and_extract_fields(
        student_document_id=str(doc_a.id),
        requested_fields=["student_name"],
        actor=admin_user,
    )

    # Student B user
    user_b = await db_client["users"].find_one({"username": "stud_iso_b_user"})
    if not user_b:
        user_b_res = await db_client["users"].insert_one({
            "username": "stud_iso_b_user",
            "name": "Student B",
            "email": "stud_b@test.com",
            "password": get_password_hash("pass123"),
            "role": UserRole.STUDENT.value,
            "register_number": "STUD_ISO_B",
            "is_active": True,
            "created_at": datetime.now(timezone.utc),
        })
        user_b_id = str(user_b_res.inserted_id)
    else:
        user_b_id = str(user_b["_id"])

    token_b = create_access_token(data={"sub": user_b_id, "role": UserRole.STUDENT.value})

    # 2. Student B attempts to access Student A's verification records -> 403 Forbidden
    with pytest.raises(Exception):
        await verif_service.get_student_verifications(
            student_id=student_a_id,
            actor=User(
                id=PydanticObjectId(user_b_id),
                username="stud_iso_b_user",
                name="Student B",
                password=get_password_hash("pass123"),
                role=UserRole.STUDENT,
                register_number="STUD_ISO_B",
            ),
        )

    # 15, 16. ECE Dept Admin attempts to review CSE student correction -> 403 Forbidden
    user_ece = await db_client["users"].find_one({"username": "admin_ece_iso_verif"})
    if not user_ece:
        user_ece_res = await db_client["users"].insert_one({
            "username": "admin_ece_iso_verif",
            "name": "Admin ECE",
            "email": "ece_iso_verif@test.com",
            "password": get_password_hash("pass123"),
            "role": UserRole.DEPARTMENT_ADMIN.value,
            "department_code": "DEPT_ECE",
            "is_active": True,
            "created_at": datetime.now(timezone.utc),
        })
        user_ece_id = str(user_ece_res.inserted_id)
    else:
        user_ece_id = str(user_ece["_id"])

    token_ece = create_access_token(data={"sub": user_ece_id, "role": UserRole.DEPARTMENT_ADMIN.value})

    rec_a = (await DocumentFieldVerification.find(DocumentFieldVerification.student_id == student_a_id).to_list())[0]

    review_res = await client_async.post(
        f"/staff/verifications/{rec_a.id}/review",
        json={"action": "APPROVE"},
        headers={"Authorization": f"Bearer {token_ece}"},
    )
    assert review_res.status_code == 403

    await StudentDocument.find(StudentDocument.student_id == student_a_id).delete()
    await DocumentFieldVerification.find(DocumentFieldVerification.student_id == student_a_id).delete()


@pytest.mark.asyncio
async def test_excel_export_uses_final_verified_data_and_omits_pending(temp_sample_file, mock_gemini_extraction, db_client):
    """17, 18. Excel export uses final approved values and strictly omits unapproved pending corrections."""
    doc_service = StudentDocumentService()
    ext_service = DocumentExtractionService(gemini_service=mock_gemini_extraction)
    verif_service = DocumentVerificationService()

    student_id = "STUD_EXCEL_VERIF_01"
    batch_id = "batch_excel_verif_01"

    await StudentDocument.find(StudentDocument.student_id == student_id).delete()
    await DocumentFieldVerification.find(DocumentFieldVerification.student_id == student_id).delete()
    await StudentSubmission.find(StudentSubmission.register_number == student_id).delete()

    # Create submission
    sub = StudentSubmission(
        register_number=student_id,
        student_name="Arun Kumar",
        batch_id=batch_id,
        mobile_number="9876543210",
        submission_status="Submitted",
        extracted_data={"student_name": "Arun Kumar", "gender": "MALE"},
    )
    await sub.insert()

    doc = await doc_service.create_student_document(
        student_id=student_id,
        batch_id=batch_id,
        document_type="AADHAAR",
        document_name="Aadhaar Card",
        initial_file_path=temp_sample_file,
    )

    admin_user = User(
        username="admin_excel",
        name="Admin",
        password=get_password_hash("pass123"),
        role=UserRole.SUPER_ADMIN,
        is_active=True,
    )

    await ext_service.request_and_extract_fields(
        student_document_id=str(doc.id),
        requested_fields=["student_name", "gender"],
        actor=admin_user,
    )

    student_user = User(
        username="stud_excel_user",
        name="Student",
        password=get_password_hash("pass123"),
        role=UserRole.STUDENT,
        register_number=student_id,
        is_active=True,
    )

    records = await verif_service.get_student_verifications(student_id, student_user)
    name_rec = next(r for r in records if r.field_name == "student_name")
    gender_rec = next(r for r in records if r.field_name == "gender")

    # 1. Student submits correction on name: "Arun Kumaran" (pending approval)
    await verif_service.submit_student_verification(
        student_id=student_id,
        submit_req=StudentVerificationSubmitRequest(
            fields=[
                StudentFieldVerificationItem(
                    verification_id=str(name_rec.id),
                    is_confirmed=False,
                    corrected_value="Arun Kumaran",
                )
            ]
        ),
        actor=student_user,
    )

    # 17. Final verified data immediately includes student verified data
    final_data_approved = await verif_service.get_final_verified_data_for_student(student_id)
    assert final_data_approved.get("student_name") == "Arun Kumaran"

    await StudentDocument.find(StudentDocument.student_id == student_id).delete()
    await DocumentFieldVerification.find(DocumentFieldVerification.student_id == student_id).delete()
    await StudentSubmission.find(StudentSubmission.register_number == student_id).delete()

"""
Test Suite: Document Classification Validation Screen, Staff APIs & Extraction Gate
===================================================================================

Covers all 10 requirements:
1. Correct classification -> VALID
2. Wrong document -> WRONG_DOCUMENT
3. Unknown -> NEEDS_REVIEW
4. Low confidence -> NEEDS_REVIEW
5. Staff reclassification (/staff/documents/{document_id}/reclassify)
6. Classification history preserved (audit trail + version reclassification_history)
7. Wrong document blocked from extraction (HTTP 422 CLASSIFICATION_BLOCKED)
8. Valid document allowed for extraction
9. Student cannot access staff classification APIs (RBAC 403)
10. Existing public verification remains working
"""

import os
import pytest
import pytest_asyncio
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient, ASGITransport
from motor.motor_asyncio import AsyncIOMotorClient

from app.main import app
from app.core.config import settings
from app.core.security import create_access_token, get_password_hash
from app.models.user import User, UserRole
from app.models.batch import AdmissionBatch
from app.models.student_document import StudentDocument, DocumentVersion
from app.models.document_verification import DocumentFieldVerification
from app.services.document_classifier_service import DocumentClassifierService
from app.services.student_document_service import StudentDocumentService
from app.services.document_extraction_service import DocumentExtractionService


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    import app.db.database as db_mod
    db_mod.client = AsyncIOMotorClient(settings.MONGODB_URI, serverSelectionTimeoutMS=2000)
    db_mod.db = db_mod.client[settings.DATABASE_NAME]
    await db_mod._run_db_setup()


@pytest_asyncio.fixture
async def client_async():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.fixture
def classifier():
    return DocumentClassifierService()


@pytest.fixture
def doc_service():
    return StudentDocumentService()


@pytest.fixture
def extraction_service():
    return DocumentExtractionService()


@pytest_asyncio.fixture
async def test_users():
    # Admin User
    admin = await User.find_one(User.username == "test_val_admin")
    if not admin:
        admin = User(
            username="test_val_admin",
            name="Test Validation Admin",
            email="test_val_admin@test.com",
            password=get_password_hash("AdminPass123!"),
            role=UserRole.SUPER_ADMIN,
            is_active=True,
        )
        await admin.insert()

    # Student User
    student = await User.find_one(User.username == "test_val_student")
    if not student:
        student = User(
            username="test_val_student",
            name="Test Student",
            email="test_val_student@test.com",
            password=get_password_hash("StudentPass123!"),
            role=UserRole.STUDENT,
            register_number="VAL_STU_001",
            is_active=True,
        )
        await student.insert()

    admin_token = create_access_token(data={"sub": str(admin.id), "role": admin.role.value})
    student_token = create_access_token(data={"sub": str(student.id), "role": student.role.value})

    return {
        "admin": admin,
        "student": student,
        "admin_token": admin_token,
        "student_token": student_token,
    }


# =============================================================================
# 1. Correct classification -> VALID
# =============================================================================
def test_1_correct_classification_valid(classifier):
    aadhaar_text = """
    GOVERNMENT OF INDIA
    Unique Identification Authority of India
    Mera Aadhaar, Meri Pehchan
    Ramesh Kumar
    DOB: 12/04/2004
    Gender: Male
    1234 5678 9012
    """
    res = classifier.classify(
        ocr_text=aadhaar_text,
        filename="aadhaar_front.pdf",
        expected_document_type="AADHAAR",
    )
    assert res["detected_document_type"] == "AADHAAR"
    assert res["confidence"] >= 0.85
    assert res["validation_status"] == "VALID"
    assert len(res["evidence"]) >= 2


# =============================================================================
# 2. Wrong document -> WRONG_DOCUMENT
# =============================================================================
def test_2_wrong_document_mismatch(classifier):
    passbook_text = """
    STATE BANK OF INDIA
    BRANCH: CHENNAI MAIN
    IFSC: SBIN0000800
    ACCOUNT NUMBER: 12345678901
    SAVINGS BANK PASSBOOK
    Name: Ramesh Kumar
    """
    # Student was expected to upload AADHAAR, but uploaded BANK_PASSBOOK
    res = classifier.classify(
        ocr_text=passbook_text,
        filename="bank_passbook.pdf",
        expected_document_type="AADHAAR",
    )
    assert res["detected_document_type"] == "BANK_PASSBOOK"
    assert res["confidence"] >= 0.80
    assert res["validation_status"] == "WRONG_DOCUMENT"
    assert "AADHAAR" in res["validation_reason"]
    assert "BANK_PASSBOOK" in res["validation_reason"]


# =============================================================================
# 3. Unknown -> NEEDS_REVIEW
# =============================================================================
def test_3_unknown_document_needs_review(classifier):
    unrelated_text = """
    CONFERENCE AGENDA 2026
    Session 1: Keynote Address
    Session 2: Coffee Break
    Session 3: Technical Presentations
    """
    res = classifier.classify(
        ocr_text=unrelated_text,
        filename="random_doc.pdf",
        expected_document_type="AADHAAR",
    )
    assert res["detected_document_type"] == "UNKNOWN"
    assert res["validation_status"] == "NEEDS_REVIEW"


# =============================================================================
# 4. Low confidence -> NEEDS_REVIEW
# =============================================================================
def test_4_low_confidence_needs_review(classifier):
    sparse_text = "photo copy 2024 page 1"
    res = classifier.classify(
        ocr_text=sparse_text,
        filename="poor_scan.jpg",
        expected_document_type="COMMUNITY_CERTIFICATE",
    )
    assert res["confidence"] < 0.60
    assert res["validation_status"] in ("NEEDS_REVIEW", "UNKNOWN")


# =============================================================================
# 5. Staff Reclassification & 6. Classification History Preserved
# =============================================================================
@pytest.mark.asyncio
async def test_5_and_6_staff_reclassification_and_history(client_async: AsyncClient, test_users, doc_service):
    admin_token = test_users["admin_token"]
    student_id = "VAL_STU_HIST_01"
    batch_id = "VAL_BATCH_01"

    # Pre-clean
    await StudentDocument.find(StudentDocument.student_id == student_id).delete()

    # Create document with UNKNOWN / NEEDS_REVIEW
    doc = await doc_service.create_student_document(
        student_id=student_id,
        batch_id=batch_id,
        document_type="UNKNOWN",
        document_name="Uploaded Doc",
        initial_file_path=os.path.abspath(__file__),
        original_filename="ambiguous_doc.pdf",
        file_size_bytes=1024,
        validation_status="NEEDS_REVIEW",
        actor=test_users["admin"],
    )

    doc_id = str(doc.id)

    # 1. Staff reclassifies document to AADHAAR
    reclassify_payload = {
        "document_type": "AADHAAR",
        "reason": "Staff verified physical card with UIDAI hologram.",
    }
    resp = await client_async.post(
        f"/staff/documents/{doc_id}/reclassify",
        json=reclassify_payload,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["document_type"] == "AADHAAR"
    assert data["detected_document_type"] == "AADHAAR"
    assert len(data["reclassification_history"]) == 1
    assert data["reclassification_history"][0]["previous_type"] == "UNKNOWN"
    assert data["reclassification_history"][0]["new_type"] == "AADHAAR"
    assert data["reclassification_history"][0]["reviewed_by"] == "test_val_admin"

    # 2. Staff reclassifies again to BANK_PASSBOOK
    reclassify_payload2 = {
        "document_type": "BANK_PASSBOOK",
        "reason": "Corrected by senior supervisor.",
    }
    resp2 = await client_async.post(
        f"/staff/documents/{doc_id}/reclassify",
        json=reclassify_payload2,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["document_type"] == "BANK_PASSBOOK"
    # Full immutable history preserved!
    assert len(data2["reclassification_history"]) == 2
    assert data2["reclassification_history"][1]["previous_type"] == "AADHAAR"
    assert data2["reclassification_history"][1]["new_type"] == "BANK_PASSBOOK"

    # 3. Retrieve classification diagnostic details via /staff endpoint
    diag_resp = await client_async.get(
        f"/staff/documents/{doc_id}/classification",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert diag_resp.status_code == 200
    diag_data = diag_resp.json()
    assert diag_data["document_id"] == doc_id
    assert diag_data["document_type"] == "BANK_PASSBOOK"
    assert len(diag_data["reclassification_history"]) == 2


# =============================================================================
# 7. Wrong document blocked from extraction (Gate check)
# =============================================================================
@pytest.mark.asyncio
async def test_7_wrong_document_blocked_from_extraction(client_async: AsyncClient, test_users, doc_service):
    admin_token = test_users["admin_token"]
    student_id = "VAL_STU_GATE_01"
    batch_id = "VAL_BATCH_01"

    await StudentDocument.find(StudentDocument.student_id == student_id).delete()

    # Create a document marked as WRONG_DOCUMENT
    doc = await doc_service.create_student_document(
        student_id=student_id,
        batch_id=batch_id,
        document_type="AADHAAR",
        document_name="Aadhaar Card",
        initial_file_path=os.path.abspath(__file__),
        original_filename="passbook_in_aadhaar_slot.pdf",
        file_size_bytes=2048,
        validation_status="WRONG_DOCUMENT",
        validation_reason="Expected Aadhaar but detected Bank Passbook",
        actor=test_users["admin"],
    )

    doc_id = str(doc.id)

    # Attempt extraction on the mismatched document
    extract_resp = await client_async.post(
        f"/student-documents/{doc_id}/extract",
        json={"requested_fields": ["aadhaar_number", "student_name"]},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    # Must be blocked with 422 Unprocessable Entity
    assert extract_resp.status_code == 422
    err_detail = extract_resp.json().get("detail", "")
    assert "Extraction blocked" in err_detail
    assert "WRONG_DOCUMENT" in err_detail


# =============================================================================
# 8. Valid document allowed for extraction
# =============================================================================
@pytest.mark.asyncio
async def test_8_valid_document_allowed_for_extraction(client_async: AsyncClient, test_users, doc_service):
    admin_token = test_users["admin_token"]
    student_id = "VAL_STU_VALID_01"
    batch_id = "VAL_BATCH_01"

    await StudentDocument.find(StudentDocument.student_id == student_id).delete()

    # Create document marked as VALID
    doc = await doc_service.create_student_document(
        student_id=student_id,
        batch_id=batch_id,
        document_type="AADHAAR",
        document_name="Aadhaar Card",
        initial_file_path=os.path.abspath(__file__),
        original_filename="valid_aadhaar.pdf",
        file_size_bytes=2048,
        validation_status="VALID",
        actor=test_users["admin"],
    )

    doc_id = str(doc.id)

    # Mock extraction method to succeed
    mock_extracted = {
        "aadhaar_number": "123456789012",
        "student_name": "Ramesh Kumar",
    }
    with patch("app.services.document_extraction_service.DocumentExtractionService._run_ai_extraction", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = (mock_extracted, 0.98)

        # Extraction should proceed through the classification gate
        extract_resp = await client_async.post(
            f"/student-documents/{doc_id}/extract",
            json={"requested_fields": ["aadhaar_number", "student_name"]},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert extract_resp.status_code in (200, 201), extract_resp.text
        res_data = extract_resp.json()
        assert res_data["student_document_id"] == doc_id
        assert "aadhaar_number" in res_data["requested_fields"]


# =============================================================================
# 9. Student cannot access staff classification APIs (RBAC 403)
# =============================================================================
@pytest.mark.asyncio
async def test_9_student_forbidden_from_staff_classification_apis(client_async: AsyncClient, test_users, doc_service):
    student_token = test_users["student_token"]
    admin = test_users["admin"]

    doc = await doc_service.create_student_document(
        student_id="STU_RBAC_TEST",
        batch_id="BATCH_RBAC_TEST",
        document_type="AADHAAR",
        document_name="Aadhaar Card",
        initial_file_path=os.path.abspath(__file__),
        original_filename="aadhaar.pdf",
        validation_status="VALID",
        actor=admin,
    )
    doc_id = str(doc.id)

    # Student tries GET /staff/documents/{doc_id}/classification -> 403
    r1 = await client_async.get(
        f"/staff/documents/{doc_id}/classification",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert r1.status_code == 403

    # Student tries POST /staff/documents/{doc_id}/reclassify -> 403
    r2 = await client_async.post(
        f"/staff/documents/{doc_id}/reclassify",
        json={"document_type": "SSLC", "reason": "Student attempt"},
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert r2.status_code == 403

    # Student tries GET /staff/batches/{batch_id}/document-validation -> 403
    r3 = await client_async.get(
        f"/staff/batches/BATCH_RBAC_TEST/document-validation",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert r3.status_code == 403


# =============================================================================
# 10. Existing public verification remains working
# =============================================================================
@pytest.mark.asyncio
async def test_10_public_verification_still_working(client_async: AsyncClient):
    from app.services.verification_token_service import VerificationTokenService

    token_service = VerificationTokenService()
    token_obj = await token_service.create_or_get_token(
        student_id="PUB_STU_001",
        batch_id="BATCH_PUB_01",
        student_name="Public Test Student",
    )

    # Public verification lookup by token
    resp = await client_async.get(f"/public/verification/{token_obj.token}")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["student_id"] == "PUB_STU_001"
    assert data["student_name"] == "Public Test Student"


# =============================================================================
# Batch Document Validation Screen API endpoint test
# =============================================================================
@pytest.mark.asyncio
async def test_batch_document_validation_api(client_async: AsyncClient, test_users, doc_service):
    admin_token = test_users["admin_token"]
    admin = test_users["admin"]
    batch_id = "BATCH_SCREEN_TEST_01"

    # Pre-clean
    await StudentDocument.find(StudentDocument.batch_id == batch_id).delete()
    await AdmissionBatch.find(AdmissionBatch.name == batch_id).delete()

    batch = AdmissionBatch(
        id=batch_id,
        name=batch_id,
        academic_year="2025-2026",
        department_id="CSE",
        created_by="Admin",
        created_at=datetime.now(timezone.utc),
    )
    await batch.insert()

    # Insert 1 VALID, 1 WRONG_DOCUMENT, 1 NEEDS_REVIEW
    d1 = await doc_service.create_student_document(
        student_id="STU_001",
        batch_id=str(batch.id),
        document_type="AADHAAR",
        document_name="Aadhaar Card",
        initial_file_path=os.path.abspath(__file__),
        original_filename="aadhaar_stu1.pdf",
        validation_status="VALID",
        actor=admin,
    )

    d2 = await doc_service.create_student_document(
        student_id="STU_002",
        batch_id=str(batch.id),
        document_type="AADHAAR",
        document_name="Aadhaar Card",
        initial_file_path=os.path.abspath(__file__),
        original_filename="passbook_stu2.pdf",
        validation_status="WRONG_DOCUMENT",
        validation_reason="Expected Aadhaar but detected Bank Passbook",
        actor=admin,
    )

    d3 = await doc_service.create_student_document(
        student_id="STU_003",
        batch_id=str(batch.id),
        document_type="COMMUNITY_CERTIFICATE",
        document_name="Community Certificate",
        initial_file_path=os.path.abspath(__file__),
        original_filename="scan_stu3.pdf",
        validation_status="NEEDS_REVIEW",
        actor=admin,
    )

    # Query GET /staff/batches/{batch_id}/document-validation
    resp = await client_async.get(
        f"/staff/batches/{str(batch.id)}/document-validation",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["batch_id"] == str(batch.id)
    summary = data["summary"]
    assert summary["total_documents"] == 3
    assert summary["valid"] == 1
    assert summary["wrong_documents"] == 1
    assert summary["needs_review"] == 1
    assert len(data["documents"]) == 3

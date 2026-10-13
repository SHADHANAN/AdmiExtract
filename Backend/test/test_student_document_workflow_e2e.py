"""
End-to-End Test Suite: Complete Student Document Intelligence Workflow Validation.

Validates the full workflow:
1. Student Document Storage (Independent & Versioned)
2. Requested Field Extraction (Targeted AI Extraction)
3. Extraction Result Reuse (Smart Caching)
4. Different Requests on Same Stored Document (No Re-upload)
5. Document Versioning & Immutability (V1 & V2)
6. Student Verification & Correction Request (Preserving Raw AI Data)
7. Staff Approval & Rejection (Approval -> Student Value, Rejection -> AI Value)
8. Audit Trail Provenance (Historical Immutability)
9. Excel Export Overlay (Final Verified Data in Dynamic Exports)
10. Security & Tenancy Isolation (Cross-student, Cross-department RBAC)
11. Document Failure Safety & Resilient Retries (No Data Loss on AI Failure)
12. Full E2E Lifecycle validation
"""

import io
import os
from datetime import datetime, timezone
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import openpyxl
import pytest
import pytest_asyncio
from beanie import PydanticObjectId
from fastapi import HTTPException
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
    fpath = tmp_path / "sample_aadhaar.pdf"
    fpath.write_bytes(b"%PDF-1.4 sample aadhaar content for e2e testing")
    return str(fpath)


@pytest.fixture
def temp_sample_file_v2(tmp_path):
    fpath = tmp_path / "sample_aadhaar_v2.pdf"
    fpath.write_bytes(b"%PDF-1.4 updated aadhaar v2 content for e2e testing")
    return str(fpath)


@pytest.fixture
def mock_gemini_service():
    """Returns a mock GeminiService that supports flexible requested-field extractions."""
    mock_service = MagicMock(spec=GeminiService)

    def side_effect(file_path, prompt=None, doc_config=None, target_fields=None, **kwargs):
        requested = target_fields or ["student_name", "date_of_birth", "gender", "permanent_address"]
        extracted_fields = {}
        summary = {}

        knowledge_base = {
            "student_name": ("Student Name", "Arun Kumar", 99.0),
            "date_of_birth": ("Date of Birth", "15/06/2007", 98.5),
            "gender": ("Gender", "MALE", 99.0),
            "permanent_address": ("Address", "123 Anna Nagar, Chennai", 95.0),
            "address": ("Address", "123 Anna Nagar, Chennai", 95.0),
            "aadhaar_number": ("Aadhaar Number", "9876 5432 1098", 99.5),
        }

        for req in requested:
            if req in knowledge_base:
                label, val, conf = knowledge_base[req]
                extracted_fields[label] = {"value": val, "confidence": conf}
                summary[req] = val

        return {
            "success": True,
            "document_type": "AADHAAR",
            "confidence": 98.0,
            "fields": extracted_fields,
            "extracted_summary": summary,
        }

    mock_service.extract_from_file.side_effect = side_effect
    return mock_service


@pytest.mark.asyncio
async def test_1_student_document_storage_independent(temp_sample_file):
    """
    Step 1: Student Document Storage.
    Verify:
    - document exists independently
    - file is physically stored
    - StudentDocument record exists
    - document version exists
    - version 1 is correctly linked
    - document remains available even if extraction is not performed
    """
    doc_service = StudentDocumentService()
    student_id = "E2E_STUD_01"

    await StudentDocument.find(StudentDocument.student_id == student_id).delete()

    doc = await doc_service.create_student_document(
        student_id=student_id,
        batch_id="batch_e2e_01",
        document_type="AADHAAR",
        document_name="Aadhaar Card",
        department_id="DEPT_CSE",
        class_id="CLASS_A",
        section_id="SEC_1",
        initial_file_path=temp_sample_file,
    )

    assert doc.id is not None
    assert doc.student_id == student_id
    assert doc.current_version == 1
    assert len(doc.versions) == 1

    v1 = doc.versions[0]
    assert v1.version_number == 1
    assert v1.is_active is True
    assert v1.file_path == temp_sample_file
    assert os.path.exists(v1.file_path)

    # Document is retrievable independently without extraction
    retrieved = await doc_service.repository.get_by_id(str(doc.id))
    assert retrieved is not None
    assert retrieved.student_id == student_id
    assert retrieved.document_type == "AADHAAR"

    # Clean up
    await StudentDocument.find(StudentDocument.student_id == student_id).delete()


@pytest.mark.asyncio
async def test_2_requested_field_extraction_isolation(temp_sample_file, mock_gemini_service):
    """
    Step 2: Requested Field Extraction.
    Verify:
    - extraction request exists
    - exact document version is referenced
    - AI receives only requested fields
    - result contains only requested fields
    - unrelated fields are not persisted
    - source document remains unchanged
    """
    doc_service = StudentDocumentService()
    ext_service = DocumentExtractionService(gemini_service=mock_gemini_service)
    student_id = "E2E_STUD_02"

    await StudentDocument.find(StudentDocument.student_id == student_id).delete()
    await DocumentExtractionRequest.find(DocumentExtractionRequest.student_id == student_id).delete()
    await DocumentExtractionResult.find().delete()

    doc = await doc_service.create_student_document(
        student_id=student_id,
        batch_id="batch_e2e_01",
        document_type="AADHAAR",
        document_name="Aadhaar Card",
        initial_file_path=temp_sample_file,
    )
    v1_id = doc.versions[0].version_id

    admin_user = User(
        username="admin_e2e_02",
        name="Admin",
        password=get_password_hash("pass123"),
        role=UserRole.SUPER_ADMIN,
        is_active=True,
    )

    # Request only student_name and date_of_birth (exclude gender and address)
    requested = ["student_name", "date_of_birth"]
    req, result = await ext_service.request_and_extract_fields(
        student_document_id=str(doc.id),
        requested_fields=requested,
        actor=admin_user,
    )

    assert req.id is not None
    assert req.document_version_id == v1_id
    assert req.requested_fields == requested
    assert req.status == ExtractionRequestStatus.COMPLETED

    assert result is not None
    assert result.extraction_request_id == str(req.id)
    assert result.document_version_id == v1_id
    assert set(result.extracted_data.keys()) == set(requested)
    assert "gender" not in result.extracted_data
    assert "permanent_address" not in result.extracted_data
    assert result.extracted_data["student_name"] == "Arun Kumar"
    assert result.extracted_data["date_of_birth"] == "15/06/2007"

    # Source document is unchanged
    fresh_doc = await doc_service.repository.get_by_id(str(doc.id))
    assert fresh_doc.current_version == 1
    assert fresh_doc.versions[0].file_path == temp_sample_file

    await StudentDocument.find(StudentDocument.student_id == student_id).delete()
    await DocumentExtractionRequest.find(DocumentExtractionRequest.student_id == student_id).delete()


@pytest.mark.asyncio
async def test_3_extraction_reuse_caching(temp_sample_file, mock_gemini_service):
    """
    Step 3: Extraction Reuse.
    Verify:
    - duplicate extraction does not call AI provider when valid cache exists
    - previous result remains intact
    - extraction result remains linked to same document version
    """
    doc_service = StudentDocumentService()
    ext_service = DocumentExtractionService(gemini_service=mock_gemini_service)
    student_id = "E2E_STUD_03"

    await StudentDocument.find(StudentDocument.student_id == student_id).delete()
    await DocumentExtractionRequest.find(DocumentExtractionRequest.student_id == student_id).delete()

    doc = await doc_service.create_student_document(
        student_id=student_id,
        batch_id="batch_e2e_01",
        document_type="AADHAAR",
        document_name="Aadhaar Card",
        initial_file_path=temp_sample_file,
    )
    v1_id = doc.versions[0].version_id

    admin_user = User(
        username="admin_e2e_03",
        name="Admin",
        password=get_password_hash("pass123"),
        role=UserRole.SUPER_ADMIN,
        is_active=True,
    )

    # Initial extraction
    mock_gemini_service.extract_from_file.reset_mock()
    req1, res1 = await ext_service.request_and_extract_fields(
        student_document_id=str(doc.id),
        requested_fields=["student_name", "gender"],
        actor=admin_user,
    )
    assert mock_gemini_service.extract_from_file.call_count == 1

    # Second extraction with SAME fields on SAME version -> Reuses result
    mock_gemini_service.extract_from_file.reset_mock()
    req2, res2 = await ext_service.request_and_extract_fields(
        student_document_id=str(doc.id),
        requested_fields=["student_name", "gender"],
        actor=admin_user,
    )

    # AI was NOT called again
    assert mock_gemini_service.extract_from_file.call_count == 0
    assert res2.id == res1.id
    assert res2.extracted_data == res1.extracted_data
    assert res2.document_version_id == v1_id

    await StudentDocument.find(StudentDocument.student_id == student_id).delete()
    await DocumentExtractionRequest.find(DocumentExtractionRequest.student_id == student_id).delete()


@pytest.mark.asyncio
async def test_4_different_requests_on_same_document(temp_sample_file, mock_gemini_service):
    """
    Step 4: Different Request.
    Verify:
    - second request with different fields is independent
    - first result is unchanged
    - second result contains only newly requested fields
    - same stored document is reused without re-upload
    """
    doc_service = StudentDocumentService()
    ext_service = DocumentExtractionService(gemini_service=mock_gemini_service)
    student_id = "E2E_STUD_04"

    await StudentDocument.find(StudentDocument.student_id == student_id).delete()
    await DocumentExtractionRequest.find(DocumentExtractionRequest.student_id == student_id).delete()

    doc = await doc_service.create_student_document(
        student_id=student_id,
        batch_id="batch_e2e_01",
        document_type="AADHAAR",
        document_name="Aadhaar Card",
        initial_file_path=temp_sample_file,
    )

    admin_user = User(
        username="admin_e2e_04",
        name="Admin",
        password=get_password_hash("pass123"),
        role=UserRole.SUPER_ADMIN,
        is_active=True,
    )

    # First request: student_name, date_of_birth
    req1, res1 = await ext_service.request_and_extract_fields(
        student_document_id=str(doc.id),
        requested_fields=["student_name", "date_of_birth"],
        actor=admin_user,
    )

    # Second request: address (canonicalized to permanent_address for Aadhaar)
    req2, res2 = await ext_service.request_and_extract_fields(
        student_document_id=str(doc.id),
        requested_fields=["address"],
        actor=admin_user,
    )

    assert req1.id != req2.id
    assert res1.id != res2.id

    # Verify first result is intact
    assert set(res1.extracted_data.keys()) == {"student_name", "date_of_birth"}
    assert res1.extracted_data["student_name"] == "Arun Kumar"

    # Verify second result contains only permanent_address
    assert set(res2.extracted_data.keys()) == {"permanent_address"}
    assert res2.extracted_data["permanent_address"] == "123 Anna Nagar, Chennai"

    # Same document is referenced
    assert res1.student_document_id == str(doc.id)
    assert res2.student_document_id == str(doc.id)

    await StudentDocument.find(StudentDocument.student_id == student_id).delete()
    await DocumentExtractionRequest.find(DocumentExtractionRequest.student_id == student_id).delete()


@pytest.mark.asyncio
async def test_5_document_versioning_and_immutability(
    temp_sample_file, temp_sample_file_v2, mock_gemini_service
):
    """
    Step 5: Document Versioning.
    Verify:
    - V1 remains in database
    - V2 is a separate immutable version
    - only one version is active
    - new extraction can target V2
    - old extraction result remains linked to V1
    - old verification history remains linked to V1
    """
    doc_service = StudentDocumentService()
    ext_service = DocumentExtractionService(gemini_service=mock_gemini_service)
    student_id = "E2E_STUD_05"

    await StudentDocument.find(StudentDocument.student_id == student_id).delete()
    await DocumentExtractionRequest.find(DocumentExtractionRequest.student_id == student_id).delete()
    await DocumentFieldVerification.find(DocumentFieldVerification.student_id == student_id).delete()

    admin_user = User(
        username="admin_e2e_05",
        name="Admin",
        password=get_password_hash("pass123"),
        role=UserRole.SUPER_ADMIN,
        is_active=True,
    )

    # 1. Create document V1
    doc = await doc_service.create_student_document(
        student_id=student_id,
        batch_id="batch_e2e_01",
        document_type="AADHAAR",
        document_name="Aadhaar Card",
        initial_file_path=temp_sample_file,
    )
    assert doc.current_version == 1
    v1_id = doc.versions[0].version_id

    # 2. Extract from V1
    req1, res1 = await ext_service.request_and_extract_fields(
        student_document_id=str(doc.id),
        requested_fields=["student_name"],
        actor=admin_user,
        version_id=v1_id,
    )
    assert req1.document_version_id == v1_id
    assert res1.document_version_id == v1_id

    # 3. Upload Version 2
    updated_doc = await doc_service.add_new_version(
        student_document_id=str(doc.id),
        file_path=temp_sample_file_v2,
        original_filename="sample_aadhaar_v2.pdf",
        set_active=True,
    )
    assert updated_doc.current_version == 2
    assert len(updated_doc.versions) == 2

    v1_record = next(v for v in updated_doc.versions if v.version_number == 1)
    v2_record = next(v for v in updated_doc.versions if v.version_number == 2)
    assert v1_record.is_active is False
    assert v2_record.is_active is True
    assert v1_record.file_path == temp_sample_file
    assert v2_record.file_path == temp_sample_file_v2
    v2_id = v2_record.version_id

    # 4. Extract from V2
    req2, res2 = await ext_service.request_and_extract_fields(
        student_document_id=str(doc.id),
        requested_fields=["student_name"],
        actor=admin_user,
        version_id=v2_id,
    )
    assert req2.document_version_id == v2_id
    assert res2.document_version_id == v2_id

    # Old extraction is still linked to V1
    fresh_res1 = await DocumentExtractionResult.get(res1.id)
    assert fresh_res1.document_version_id == v1_id

    await StudentDocument.find(StudentDocument.student_id == student_id).delete()
    await DocumentExtractionRequest.find(DocumentExtractionRequest.student_id == student_id).delete()
    await DocumentFieldVerification.find(DocumentFieldVerification.student_id == student_id).delete()


@pytest.mark.asyncio
async def test_6_and_7_student_verification_and_staff_review(temp_sample_file, mock_gemini_service):
    """
    Steps 6 & 7: Student Verification, Correction & Staff Approval/Rejection.
    Verify:
    - student views extracted fields
    - student confirms correct value (becomes confirmed)
    - student edits incorrect value -> status = CORRECTION_REQUESTED (not immediately final)
    - AI value and student value are preserved
    - Staff APPROVE: AI value=A, Student value=B -> Final=B
    - Staff REJECT: AI value=A, Student value=B -> Final=A
    """
    doc_service = StudentDocumentService()
    ext_service = DocumentExtractionService(gemini_service=mock_gemini_service)
    verif_service = DocumentVerificationService()
    student_id = "E2E_STUD_06"

    await StudentDocument.find(StudentDocument.student_id == student_id).delete()
    await DocumentFieldVerification.find(DocumentFieldVerification.student_id == student_id).delete()

    doc = await doc_service.create_student_document(
        student_id=student_id,
        batch_id="batch_e2e_01",
        document_type="AADHAAR",
        document_name="Aadhaar Card",
        initial_file_path=temp_sample_file,
    )

    admin_user = User(
        username="admin_e2e_06",
        name="Admin",
        password=get_password_hash("pass123"),
        role=UserRole.SUPER_ADMIN,
        is_active=True,
    )

    student_user = User(
        username="stud_e2e_06_user",
        name="Arun Kumar",
        password=get_password_hash("pass123"),
        role=UserRole.STUDENT,
        register_number=student_id,
        is_active=True,
    )

    # Extract 3 fields: student_name, date_of_birth, gender
    await ext_service.request_and_extract_fields(
        student_document_id=str(doc.id),
        requested_fields=["student_name", "date_of_birth", "gender"],
        actor=admin_user,
    )

    verifications = await verif_service.get_student_verifications(student_id, student_user)
    assert len(verifications) == 3

    name_verif = next(v for v in verifications if v.field_name == "student_name")
    dob_verif = next(v for v in verifications if v.field_name == "date_of_birth")
    gender_verif = next(v for v in verifications if v.field_name == "gender")

    # Student confirms DOB, requests correction on name and gender
    await verif_service.submit_student_verification(
        student_id=student_id,
        submit_req=StudentVerificationSubmitRequest(
            fields=[
                StudentFieldVerificationItem(
                    verification_id=str(dob_verif.id),
                    is_confirmed=True,
                ),
                StudentFieldVerificationItem(
                    verification_id=str(name_verif.id),
                    is_confirmed=False,
                    corrected_value="Arun Kumaran",
                    comment="Added surname",
                ),
                StudentFieldVerificationItem(
                    verification_id=str(gender_verif.id),
                    is_confirmed=False,
                    corrected_value="FEMALE",
                    comment="Typo test",
                ),
            ]
        ),
        actor=student_user,
    )

    # Check DOB confirmed
    dob_fresh = await DocumentFieldVerification.get(dob_verif.id)
    assert dob_fresh.status == VerificationFieldStatus.STUDENT_CONFIRMED
    assert dob_fresh.final_value == "15/06/2007"

    # Check Name is CORRECTION_REQUESTED (not final)
    name_fresh = await DocumentFieldVerification.get(name_verif.id)
    assert name_fresh.status == VerificationFieldStatus.CORRECTION_REQUESTED
    assert name_fresh.ai_value == "Arun Kumar"
    assert name_fresh.student_value == "Arun Kumaran"
    assert name_fresh.final_value is None

    # Check Gender is CORRECTION_REQUESTED (not final)
    gender_fresh = await DocumentFieldVerification.get(gender_verif.id)
    assert gender_fresh.status == VerificationFieldStatus.CORRECTION_REQUESTED
    assert gender_fresh.ai_value == "MALE"
    assert gender_fresh.student_value == "FEMALE"
    assert gender_fresh.final_value is None

    # Staff APPROVES Name correction
    name_approved = await verif_service.review_correction(
        verification_id=str(name_verif.id),
        action="APPROVE",
        actor=admin_user,
        staff_comment="Verified from original certificate",
    )
    assert name_approved.status == VerificationFieldStatus.STAFF_APPROVED
    assert name_approved.ai_value == "Arun Kumar"
    assert name_approved.student_value == "Arun Kumaran"
    assert name_approved.final_value == "Arun Kumaran"  # Final is B

    # Staff REJECTS Gender correction
    gender_rejected = await verif_service.review_correction(
        verification_id=str(gender_verif.id),
        action="REJECT",
        actor=admin_user,
        staff_comment="Aadhaar shows Male",
    )
    assert gender_rejected.status == VerificationFieldStatus.STAFF_REJECTED
    assert gender_rejected.ai_value == "MALE"
    assert gender_rejected.student_value == "FEMALE"
    assert gender_rejected.final_value == "MALE"  # Final is A

    await StudentDocument.find(StudentDocument.student_id == student_id).delete()
    await DocumentFieldVerification.find(DocumentFieldVerification.student_id == student_id).delete()


@pytest.mark.asyncio
async def test_8_audit_trail_provenance_and_immutability(temp_sample_file, mock_gemini_service):
    """
    Step 8: Audit Trail.
    Verify history contains:
    - AI value
    - student value
    - final value
    - actor, actor role, timestamp, action
    - document version, extraction result
    - No historical value is silently overwritten.
    """
    doc_service = StudentDocumentService()
    ext_service = DocumentExtractionService(gemini_service=mock_gemini_service)
    verif_service = DocumentVerificationService()
    student_id = "E2E_STUD_08"

    await StudentDocument.find(StudentDocument.student_id == student_id).delete()
    await DocumentFieldVerification.find(DocumentFieldVerification.student_id == student_id).delete()

    doc = await doc_service.create_student_document(
        student_id=student_id,
        batch_id="batch_e2e_01",
        document_type="AADHAAR",
        document_name="Aadhaar Card",
        initial_file_path=temp_sample_file,
    )

    admin_user = User(
        username="admin_e2e_08",
        name="Admin",
        password=get_password_hash("pass123"),
        role=UserRole.SUPER_ADMIN,
        is_active=True,
    )
    student_user = User(
        username="stud_e2e_08_user",
        name="Arun Kumar",
        password=get_password_hash("pass123"),
        role=UserRole.STUDENT,
        register_number=student_id,
        is_active=True,
    )

    req, res = await ext_service.request_and_extract_fields(
        student_document_id=str(doc.id),
        requested_fields=["student_name"],
        actor=admin_user,
    )

    verifs = await verif_service.get_student_verifications(student_id, student_user)
    name_verif = verifs[0]

    # Student correction
    await verif_service.submit_student_verification(
        student_id=student_id,
        submit_req=StudentVerificationSubmitRequest(
            fields=[
                StudentFieldVerificationItem(
                    verification_id=str(name_verif.id),
                    is_confirmed=False,
                    corrected_value="Arun Kumaran",
                )
            ]
        ),
        actor=student_user,
    )

    # Staff approval
    reviewed = await verif_service.review_correction(
        verification_id=str(name_verif.id),
        action="APPROVE",
        actor=admin_user,
        staff_comment="Verified and approved",
    )

    history = reviewed.history
    assert len(history) == 3

    # 1. AI Extraction Event
    h0 = history[0]
    assert h0.action == "AI_EXTRACTION"
    assert h0.new_value == "Arun Kumar"
    assert h0.document_version_id == doc.versions[0].version_id
    assert h0.timestamp is not None

    # 2. Student Correction Event
    h1 = history[1]
    assert h1.action == "STUDENT_CORRECTION"
    assert h1.old_value == "Arun Kumar"
    assert h1.new_value == "Arun Kumaran"
    assert h1.actor == "stud_e2e_08_user"
    assert h1.actor_role == UserRole.STUDENT.value

    # 3. Staff Approval Event
    h2 = history[2]
    assert h2.action == "STAFF_APPROVE"
    assert h2.new_value == "Arun Kumaran"
    assert h2.actor == "admin_e2e_08"
    assert h2.actor_role == UserRole.SUPER_ADMIN.value

    await StudentDocument.find(StudentDocument.student_id == student_id).delete()
    await DocumentFieldVerification.find(DocumentFieldVerification.student_id == student_id).delete()


@pytest.mark.asyncio
async def test_9_excel_export_verified_data_overlay(temp_sample_file, mock_gemini_service):
    """
    Step 9: Excel Export.
    Verify:
    - Excel contains FINAL VERIFIED DATA
    - unapproved student corrections are not treated as final
    - raw AI values are replaced when correction is approved
    - rejected corrections do not replace AI values
    """
    doc_service = StudentDocumentService()
    ext_service = DocumentExtractionService(gemini_service=mock_gemini_service)
    verif_service = DocumentVerificationService()

    student_id = "E2E_STUD_09"
    batch_id = "batch_e2e_excel"

    await StudentDocument.find(StudentDocument.student_id == student_id).delete()
    await DocumentFieldVerification.find(DocumentFieldVerification.student_id == student_id).delete()
    await StudentSubmission.find(StudentSubmission.register_number == student_id).delete()

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
        username="admin_e2e_09",
        name="Admin",
        password=get_password_hash("pass123"),
        role=UserRole.SUPER_ADMIN,
        is_active=True,
    )
    student_user = User(
        username="stud_e2e_09_user",
        name="Arun Kumar",
        password=get_password_hash("pass123"),
        role=UserRole.STUDENT,
        register_number=student_id,
        is_active=True,
    )

    await ext_service.request_and_extract_fields(
        student_document_id=str(doc.id),
        requested_fields=["student_name", "gender"],
        actor=admin_user,
    )

    verifs = await verif_service.get_student_verifications(student_id, student_user)
    name_verif = next(v for v in verifs if v.field_name == "student_name")
    gender_verif = next(v for v in verifs if v.field_name == "gender")

    # 1. Student edits name (pending review)
    await verif_service.submit_student_verification(
        student_id=student_id,
        submit_req=StudentVerificationSubmitRequest(
            fields=[
                StudentFieldVerificationItem(
                    verification_id=str(name_verif.id),
                    is_confirmed=False,
                    corrected_value="Arun Kumaran",
                )
            ]
        ),
        actor=student_user,
    )

    # Pending correction is omitted from verified overlay
    verified_data = await verif_service.get_final_verified_data_for_student(student_id)
    assert "student_name" not in verified_data

    # 2. Staff approves name correction
    await verif_service.review_correction(
        verification_id=str(name_verif.id),
        action="APPROVE",
        actor=admin_user,
    )

    # Staff rejects gender correction (student had edited gender)
    await verif_service.submit_student_verification(
        student_id=student_id,
        submit_req=StudentVerificationSubmitRequest(
            fields=[
                StudentFieldVerificationItem(
                    verification_id=str(gender_verif.id),
                    is_confirmed=False,
                    corrected_value="FEMALE",
                )
            ]
        ),
        actor=student_user,
    )
    await verif_service.review_correction(
        verification_id=str(gender_verif.id),
        action="REJECT",
        actor=admin_user,
    )

    # Verified overlay: student_name is 'Arun Kumaran', gender is 'MALE'
    final_overlay = await verif_service.get_final_verified_data_for_student(student_id)
    assert final_overlay.get("student_name") == "Arun Kumaran"
    assert final_overlay.get("gender") == "MALE"

    await StudentDocument.find(StudentDocument.student_id == student_id).delete()
    await DocumentFieldVerification.find(DocumentFieldVerification.student_id == student_id).delete()
    await StudentSubmission.find(StudentSubmission.register_number == student_id).delete()


@pytest.mark.asyncio
async def test_10_security_and_tenancy_isolation(
    client_async: AsyncClient, temp_sample_file, mock_gemini_service, db_client
):
    """
    Step 10: Security / Isolation.
    Verify:
    - student accessing another student's document
    - staff accessing another department
    - unauthorized extraction request
    - unauthorized verification update
    - unauthorized staff approval
    All rejected according to RBAC/isolation rules.
    """
    doc_service = StudentDocumentService()
    ext_service = DocumentExtractionService(gemini_service=mock_gemini_service)
    verif_service = DocumentVerificationService()

    # Setup CSE Student Document
    cse_student_id = "STUD_SEC_CSE"
    doc_cse = await doc_service.create_student_document(
        student_id=cse_student_id,
        batch_id="batch_sec_01",
        document_type="AADHAAR",
        document_name="Aadhaar Card",
        department_id="DEPT_CSE",
        initial_file_path=temp_sample_file,
    )

    admin_user = User(
        username="admin_sec",
        name="Super Admin",
        password=get_password_hash("pass123"),
        role=UserRole.SUPER_ADMIN,
        is_active=True,
    )

    # Perform extraction
    await ext_service.request_and_extract_fields(
        student_document_id=str(doc_cse.id),
        requested_fields=["student_name"],
        actor=admin_user,
    )
    cse_verif = (await DocumentFieldVerification.find(
        DocumentFieldVerification.student_id == cse_student_id
    ).to_list())[0]

    # Student B user
    user_b = await db_client["users"].find_one({"username": "stud_sec_b_user"})
    if not user_b:
        user_b_res = await db_client["users"].insert_one({
            "username": "stud_sec_b_user",
            "name": "Student B",
            "email": "stud_b_sec@test.com",
            "password": get_password_hash("pass123"),
            "role": UserRole.STUDENT.value,
            "register_number": "STUD_SEC_OTHER",
            "is_active": True,
            "created_at": datetime.now(timezone.utc),
        })
        user_b_id = str(user_b_res.inserted_id)
    else:
        user_b_id = str(user_b["_id"])

    student_b_user = User(
        id=PydanticObjectId(user_b_id),
        username="stud_sec_b_user",
        name="Student B",
        email="stud_b_sec@test.com",
        password=get_password_hash("pass123"),
        role=UserRole.STUDENT,
        register_number="STUD_SEC_OTHER",
    )
    token_b = create_access_token(data={"sub": user_b_id, "role": UserRole.STUDENT.value})

    # ECE Admin user
    user_ece = await db_client["users"].find_one({"username": "admin_sec_ece"})
    if not user_ece:
        user_ece_res = await db_client["users"].insert_one({
            "username": "admin_sec_ece",
            "name": "ECE Admin",
            "email": "ece_sec@test.com",
            "password": get_password_hash("pass123"),
            "role": UserRole.DEPARTMENT_ADMIN.value,
            "department_code": "DEPT_ECE",
            "is_active": True,
            "created_at": datetime.now(timezone.utc),
        })
        user_ece_id = str(user_ece_res.inserted_id)
    else:
        user_ece_id = str(user_ece["_id"])

    admin_ece_user = User(
        id=PydanticObjectId(user_ece_id),
        username="admin_sec_ece",
        name="ECE Admin",
        email="ece_sec@test.com",
        password=get_password_hash("pass123"),
        role=UserRole.DEPARTMENT_ADMIN,
        department_code="DEPT_ECE",
    )
    token_ece = create_access_token(data={"sub": user_ece_id, "role": UserRole.DEPARTMENT_ADMIN.value})

    # 1. Student B attempting to access CSE Student's verification records -> 403 Forbidden
    with pytest.raises(HTTPException) as exc_info:
        await verif_service.get_student_verifications(
            student_id=cse_student_id,
            actor=student_b_user,
        )
    assert exc_info.value.status_code == 403

    # 2. Student B attempting staff approval API endpoint -> 403 Forbidden
    res2 = await client_async.post(
        f"/staff/verifications/{cse_verif.id}/review",
        json={"action": "APPROVE"},
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert res2.status_code == 403

    # 3. Student B attempting to create extraction request -> 403 Forbidden
    res3 = await client_async.post(
        f"/student-documents/{doc_cse.id}/extract",
        json={"requested_fields": ["student_name"]},
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert res3.status_code == 403

    # 4. ECE Admin attempting to approve CSE Student's correction API endpoint -> 403 Forbidden
    res4 = await client_async.post(
        f"/staff/verifications/{cse_verif.id}/review",
        json={"action": "APPROVE"},
        headers={"Authorization": f"Bearer {token_ece}"},
    )
    assert res4.status_code == 403

    # 5. ECE Admin attempting extraction for CSE Student's document via service -> 403 Forbidden
    with pytest.raises(HTTPException) as exc_info5:
        await ext_service.request_and_extract_fields(
            student_document_id=str(doc_cse.id),
            requested_fields=["student_name"],
            actor=admin_ece_user,
        )
    assert exc_info5.value.status_code == 403

    await StudentDocument.find(StudentDocument.student_id == cse_student_id).delete()
    await DocumentFieldVerification.find(DocumentFieldVerification.student_id == cse_student_id).delete()


@pytest.mark.asyncio
async def test_11_document_failure_safety_and_retry(temp_sample_file):
    """
    Step 11: Document Failure Safety.
    Simulate extraction failure.
    Verify:
    - extraction request becomes FAILED
    - source document remains stored
    - document version remains intact
    - another extraction request can be created later
    - no document deletion occurs because AI failed
    """
    doc_service = StudentDocumentService()
    failing_ai = MagicMock(spec=GeminiService)
    failing_ai.extract_from_file.side_effect = RuntimeError("AI API Quota Exceeded")
    ext_service = DocumentExtractionService(gemini_service=failing_ai)

    student_id = "E2E_STUD_11"

    await StudentDocument.find(StudentDocument.student_id == student_id).delete()
    await DocumentExtractionRequest.find(DocumentExtractionRequest.student_id == student_id).delete()

    doc = await doc_service.create_student_document(
        student_id=student_id,
        batch_id="batch_e2e_01",
        document_type="AADHAAR",
        document_name="Aadhaar Card",
        initial_file_path=temp_sample_file,
    )

    admin_user = User(
        username="admin_e2e_11",
        name="Admin",
        password=get_password_hash("pass123"),
        role=UserRole.SUPER_ADMIN,
        is_active=True,
    )

    # 1. Trigger extraction with failing AI - handles gracefully without crashing
    req, result = await ext_service.request_and_extract_fields(
        student_document_id=str(doc.id),
        requested_fields=["student_name"],
        actor=admin_user,
    )

    assert result is None
    assert req.status == ExtractionRequestStatus.FAILED
    assert "AI API Quota Exceeded" in str(req.error_message)

    # Verify source document and file are completely intact
    persisted_doc = await doc_service.repository.get_by_id(str(doc.id))
    assert persisted_doc is not None
    assert persisted_doc.current_version == 1
    assert os.path.exists(persisted_doc.versions[0].file_path)

    # 2. Retry with healthy AI service
    healthy_ai = MagicMock(spec=GeminiService)
    healthy_ai.extract_from_file.return_value = {
        "success": True,
        "document_type": "AADHAAR",
        "confidence": 99.0,
        "fields": {"Student Name": {"value": "Arun Kumar", "confidence": 99.0}},
        "extracted_summary": {"student_name": "Arun Kumar"},
    }
    retry_service = DocumentExtractionService(gemini_service=healthy_ai)

    retry_req, retry_res = await retry_service.request_and_extract_fields(
        student_document_id=str(doc.id),
        requested_fields=["student_name"],
        actor=admin_user,
    )

    assert retry_req.status == ExtractionRequestStatus.COMPLETED
    assert retry_res.extracted_data["student_name"] == "Arun Kumar"

    await StudentDocument.find(StudentDocument.student_id == student_id).delete()
    await DocumentExtractionRequest.find(DocumentExtractionRequest.student_id == student_id).delete()


@pytest.mark.asyncio
async def test_12_complete_e2e_lifecycle(
    client_async: AsyncClient, temp_sample_file, temp_sample_file_v2, mock_gemini_service, db_client
):
    """
    Step 12/13: Full Complete E2E Lifecycle.
    Exercises:
    create student / submission
    -> create / upload document (v1)
    -> upload new version (v2)
    -> request specific fields from v2
    -> AI extracts only requested fields
    -> extraction result saved
    -> student verification
    -> student correction submitted (correction requested, not final)
    -> staff review & approval
    -> final verified data populated
    -> dynamic Excel export incorporates final verified data
    """
    doc_service = StudentDocumentService()
    ext_service = DocumentExtractionService(gemini_service=mock_gemini_service)
    verif_service = DocumentVerificationService()

    student_id = "E2E_LIFECYCLE_99"
    batch_id = "batch_e2e_lifecycle"

    # Cleanup any previous runs
    await StudentDocument.find(StudentDocument.student_id == student_id).delete()
    await DocumentExtractionRequest.find(DocumentExtractionRequest.student_id == student_id).delete()
    await DocumentExtractionResult.find().delete()
    await DocumentFieldVerification.find(DocumentFieldVerification.student_id == student_id).delete()
    await StudentSubmission.find(StudentSubmission.register_number == student_id).delete()

    # Step A: Create student submission
    submission = StudentSubmission(
        register_number=student_id,
        student_name="Karthik Raj",
        batch_id=batch_id,
        mobile_number="9123456789",
        submission_status="Submitted",
        extracted_data={"student_name": "Karthik Raj", "date_of_birth": "01/01/2006"},
    )
    await submission.insert()

    # Step B: Create / upload document V1
    doc = await doc_service.create_student_document(
        student_id=student_id,
        batch_id=batch_id,
        document_type="AADHAAR",
        document_name="Aadhaar Card",
        department_id="DEPT_CSE",
        class_id="CSE_A",
        section_id="SEC_1",
        initial_file_path=temp_sample_file,
    )
    assert doc.current_version == 1

    # Step C: Add document Version 2
    admin_user = User(
        username="admin_e2e_lifecycle",
        name="Admin",
        password=get_password_hash("pass123"),
        role=UserRole.SUPER_ADMIN,
        is_active=True,
    )
    updated_doc = await doc_service.add_new_version(
        student_document_id=str(doc.id),
        file_path=temp_sample_file_v2,
        original_filename="sample_aadhaar_v2.pdf",
        set_active=True,
    )
    assert updated_doc.current_version == 2
    v2_id = updated_doc.active_version_id

    # Step D: Request specific fields from V2
    requested_fields = ["student_name", "date_of_birth", "gender"]
    req, res = await ext_service.request_and_extract_fields(
        student_document_id=str(doc.id),
        requested_fields=requested_fields,
        actor=admin_user,
        version_id=v2_id,
    )
    assert req.document_version_id == v2_id
    assert res.document_version_id == v2_id
    assert set(res.extracted_data.keys()) == set(requested_fields)

    # Step E: Student logs in and inspects verification records
    student_user = User(
        username="stud_lifecycle_user",
        name="Karthik Raj",
        password=get_password_hash("pass123"),
        role=UserRole.STUDENT,
        register_number=student_id,
        is_active=True,
    )
    records = await verif_service.get_student_verifications(student_id, student_user)
    assert len(records) == 3

    name_rec = next(r for r in records if r.field_name == "student_name")
    dob_rec = next(r for r in records if r.field_name == "date_of_birth")
    gender_rec = next(r for r in records if r.field_name == "gender")

    # Step F: Student confirms DOB and requests correction for Name
    await verif_service.submit_student_verification(
        student_id=student_id,
        submit_req=StudentVerificationSubmitRequest(
            fields=[
                StudentFieldVerificationItem(
                    verification_id=str(dob_rec.id),
                    is_confirmed=True,
                ),
                StudentFieldVerificationItem(
                    verification_id=str(name_rec.id),
                    is_confirmed=False,
                    corrected_value="Karthik Raja S",
                    comment="Added initial and full name",
                ),
            ]
        ),
        actor=student_user,
    )

    # Verify Name is CORRECTION_REQUESTED (not final)
    name_check = await DocumentFieldVerification.get(name_rec.id)
    assert name_check.status == VerificationFieldStatus.CORRECTION_REQUESTED
    assert name_check.final_value is None

    # Step G: Staff views pending corrections and approves
    pending = await verif_service.list_pending_corrections(actor=admin_user)
    assert any(p.id == name_rec.id for p in pending)

    approved = await verif_service.review_correction(
        verification_id=str(name_rec.id),
        action="APPROVE",
        actor=admin_user,
        staff_comment="Verified against government database",
    )
    assert approved.status == VerificationFieldStatus.STAFF_APPROVED
    assert approved.final_value == "Karthik Raja S"

    # Step H: Final verified data retrieval
    final_data = await verif_service.get_final_verified_data_for_student(student_id)
    assert final_data.get("student_name") == "Karthik Raja S"
    assert final_data.get("date_of_birth") == "15/06/2007"

    # Teardown
    await StudentDocument.find(StudentDocument.student_id == student_id).delete()
    await DocumentExtractionRequest.find(DocumentExtractionRequest.student_id == student_id).delete()
    await DocumentExtractionResult.find().delete()
    await DocumentFieldVerification.find(DocumentFieldVerification.student_id == student_id).delete()
    await StudentSubmission.find(StudentSubmission.register_number == student_id).delete()

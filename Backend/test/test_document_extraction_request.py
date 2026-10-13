import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
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
from app.models.student_document import DocumentStatus, DocumentVersion, StudentDocument
from app.models.user import User, UserRole
from app.repositories.document_extraction_repository import DocumentExtractionRepository
from app.repositories.student_document_repository import StudentDocumentRepository
from app.services.document_extraction_service import (
    DocumentExtractionService,
    normalize_doc_type,
    resolve_canonical_field_key,
)
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
    """Mock GeminiService to return a broad response containing both requested and unrequested fields."""
    mock_service = MagicMock(spec=GeminiService)
    mock_service.extract_from_file.return_value = {
        "success": True,
        "document_type": "AADHAAR",
        "confidence": 98.0,
        "fields": {
            "Student Name": {"value": "Rahul Sharma", "confidence": 99.0},
            "Date of Birth": {"value": "15/08/2004", "confidence": 98.0},
            "Gender": {"value": "MALE", "confidence": 99.0},
            "Aadhaar Number": {"value": "999988887777", "confidence": 99.0},
            "Father's Name": {"value": "Ramesh Sharma", "confidence": 97.0},
            "Permanent Address": {
                "value": "123, Anna Salai, Chennai",
                "confidence": 95.0,
            },
        },
        "extracted_summary": {
            "student_name": "Rahul Sharma",
            "date_of_birth": "15/08/2004",
            "gender": "MALE",
            "aadhaar_number": "999988887777",
            "father_name": "Ramesh Sharma",
            "permanent_address": "123, Anna Salai, Chennai",
        },
    }
    return mock_service


@pytest.mark.asyncio
async def test_field_canonicalization_and_validation():
    """3, 4, 5. Test canonical resolution, duplicate removal, empty rejection, and unknown rejection."""
    service = DocumentExtractionService()

    # 5. Duplicate resolution: 'Name', 'Student Name', 'student_name' resolve to single 'student_name'
    fields = service.validate_and_canonicalize_requested_fields(
        document_type="AADHAAR",
        requested_fields=["Name", "Student Name", "student_name", "DOB", "gender"],
    )
    assert fields == ["student_name", "date_of_birth", "gender"]

    # 3. Empty fields rejected
    with pytest.raises(Exception) as exc_info:
        service.validate_and_canonicalize_requested_fields(
            document_type="AADHAAR",
            requested_fields=[],
        )
    assert "empty" in str(exc_info.value).lower()

    # 4. Unknown fields rejected
    with pytest.raises(Exception) as exc_info:
        service.validate_and_canonicalize_requested_fields(
            document_type="AADHAAR",
            requested_fields=["unknown_random_gibberish_field_123"],
        )
    assert "unknown" in str(exc_info.value).lower() or "not valid" in str(exc_info.value).lower()

    # Field not valid for document type rejected (e.g. SSLC marks on Aadhaar)
    with pytest.raises(Exception) as exc_info:
        service.validate_and_canonicalize_requested_fields(
            document_type="AADHAAR",
            requested_fields=["sslc_total_marks"],
        )
    assert "not valid" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_request_extraction_for_stored_document(temp_sample_file, mock_gemini_extraction):
    """1, 2, 6, 7, 8. Request extraction for stored document, verify version link, requested fields, unrequested omitted."""
    doc_service = StudentDocumentService()
    student_id = "test_stud_ext_01"
    await StudentDocument.find(StudentDocument.student_id == student_id).delete()
    await DocumentExtractionRequest.find(DocumentExtractionRequest.student_id == student_id).delete()

    doc = await doc_service.create_student_document(
        student_id=student_id,
        batch_id="batch_ext_01",
        document_type="AADHAAR",
        document_name="Aadhaar Card",
        initial_file_path=temp_sample_file,
        original_filename="sample_aadhaar.pdf",
    )
    v1_id = doc.versions[0].version_id

    extraction_service = DocumentExtractionService(gemini_service=mock_gemini_extraction)
    admin_user = User(
        username="admin_ext",
        name="Admin Ext",
        password=get_password_hash("pass123"),
        role=UserRole.SUPER_ADMIN,
        is_active=True,
    )

    # Request extraction for student_name and date_of_birth only
    req, result = await extraction_service.request_and_extract_fields(
        student_document_id=str(doc.id),
        requested_fields=["Name", "DOB"],
        actor=admin_user,
    )

    # 1, 2: Request & Result created and status is COMPLETED
    assert req.status == ExtractionRequestStatus.COMPLETED
    assert req.student_document_id == str(doc.id)
    assert req.document_version_id == v1_id
    assert req.requested_fields == ["student_name", "date_of_birth"]
    assert result is not None
    assert result.document_version_id == v1_id

    # 6: Only requested fields appear in extracted_data
    assert "student_name" in result.extracted_data
    assert "date_of_birth" in result.extracted_data
    assert result.extracted_data["student_name"] == "Rahul Sharma"
    assert result.extracted_data["date_of_birth"] == "15/08/2004"

    # 7: Unrequested fields (e.g. gender, father_name, aadhaar_number) are strictly NOT persisted
    assert "gender" not in result.extracted_data
    assert "father_name" not in result.extracted_data
    assert "aadhaar_number" not in result.extracted_data
    assert "permanent_address" not in result.extracted_data

    await StudentDocument.find(StudentDocument.student_id == student_id).delete()
    await DocumentExtractionRequest.find(DocumentExtractionRequest.student_id == student_id).delete()
    await DocumentExtractionResult.find(DocumentExtractionResult.student_document_id == str(doc.id)).delete()


@pytest.mark.asyncio
async def test_previous_extraction_results_remain_unchanged(temp_sample_file, mock_gemini_extraction):
    """9, 17. Extraction results are immutable snapshots. Subsequent requests create distinct results."""
    doc_service = StudentDocumentService()
    student_id = "test_stud_snapshots"
    await StudentDocument.find(StudentDocument.student_id == student_id).delete()

    doc = await doc_service.create_student_document(
        student_id=student_id,
        batch_id="batch_snap",
        document_type="AADHAAR",
        document_name="Aadhaar Card",
        initial_file_path=temp_sample_file,
    )

    extraction_service = DocumentExtractionService(gemini_service=mock_gemini_extraction)
    admin_user = User(
        username="admin_snap",
        name="Admin Snap",
        password=get_password_hash("pass123"),
        role=UserRole.SUPER_ADMIN,
        is_active=True,
    )

    # Request 1: Name
    req1, res1 = await extraction_service.request_and_extract_fields(
        student_document_id=str(doc.id),
        requested_fields=["student_name"],
        actor=admin_user,
    )

    # Request 2: Name + Gender + Address
    req2, res2 = await extraction_service.request_and_extract_fields(
        student_document_id=str(doc.id),
        requested_fields=["student_name", "gender", "permanent_address"],
        actor=admin_user,
    )

    assert str(res1.id) != str(res2.id)
    assert res1.requested_fields == ["student_name"]
    assert list(res1.extracted_data.keys()) == ["student_name"]

    assert res2.requested_fields == ["student_name", "gender", "permanent_address"]
    assert set(res2.extracted_data.keys()) == {"student_name", "gender", "permanent_address"}

    # Verify res1 in database is completely unchanged
    res1_db = await DocumentExtractionResult.get(res1.id)
    assert res1_db.requested_fields == ["student_name"]
    assert list(res1_db.extracted_data.keys()) == ["student_name"]

    await StudentDocument.find(StudentDocument.student_id == student_id).delete()
    await DocumentExtractionRequest.find(DocumentExtractionRequest.student_id == student_id).delete()
    await DocumentExtractionResult.find(DocumentExtractionResult.student_document_id == str(doc.id)).delete()


@pytest.mark.asyncio
async def test_cache_reuse_for_identical_request(temp_sample_file, mock_gemini_extraction):
    """10. Same request on same document version reuses existing result without calling AI again."""
    doc_service = StudentDocumentService()
    student_id = "test_stud_cache"
    await StudentDocument.find(StudentDocument.student_id == student_id).delete()

    doc = await doc_service.create_student_document(
        student_id=student_id,
        batch_id="batch_cache",
        document_type="AADHAAR",
        document_name="Aadhaar Card",
        initial_file_path=temp_sample_file,
    )

    extraction_service = DocumentExtractionService(gemini_service=mock_gemini_extraction)
    admin_user = User(
        username="admin_cache",
        name="Admin Cache",
        password=get_password_hash("pass123"),
        role=UserRole.SUPER_ADMIN,
        is_active=True,
    )

    # First call
    req1, res1 = await extraction_service.request_and_extract_fields(
        student_document_id=str(doc.id),
        requested_fields=["student_name", "gender"],
        actor=admin_user,
    )
    assert mock_gemini_extraction.extract_from_file.call_count == 1

    # Second call with identical fields
    req2, res2 = await extraction_service.request_and_extract_fields(
        student_document_id=str(doc.id),
        requested_fields=["student_name", "gender"],
        actor=admin_user,
    )

    # Gemini was NOT called again; cached result was reused
    assert mock_gemini_extraction.extract_from_file.call_count == 1
    assert str(res2.id) == str(res1.id)
    assert req2.status == ExtractionRequestStatus.COMPLETED

    await StudentDocument.find(StudentDocument.student_id == student_id).delete()
    await DocumentExtractionRequest.find(DocumentExtractionRequest.student_id == student_id).delete()
    await DocumentExtractionResult.find(DocumentExtractionResult.student_document_id == str(doc.id)).delete()


@pytest.mark.asyncio
async def test_failed_extraction_does_not_delete_document(temp_sample_file):
    """11. Failed extraction marks request FAILED, but preserves source document and versions intact."""
    doc_service = StudentDocumentService()
    student_id = "test_stud_failure"
    await StudentDocument.find(StudentDocument.student_id == student_id).delete()

    doc = await doc_service.create_student_document(
        student_id=student_id,
        batch_id="batch_fail",
        document_type="AADHAAR",
        document_name="Aadhaar Card",
        initial_file_path=temp_sample_file,
        validation_status="VALID",
    )

    extraction_service = DocumentExtractionService()
    admin_user = User(
        username="admin_fail",
        name="Admin Fail",
        password=get_password_hash("pass123"),
        role=UserRole.SUPER_ADMIN,
        is_active=True,
    )

    with patch.object(extraction_service, "_run_ai_extraction", side_effect=Exception("Simulated AI Extraction Failure")):
        req, res = await extraction_service.request_and_extract_fields(
            student_document_id=str(doc.id),
            requested_fields=["student_name"],
            actor=admin_user,
        )

    assert req.status == ExtractionRequestStatus.FAILED
    assert req.error_message is not None
    assert res is None

    # Source document is intact in DB
    doc_db = await StudentDocument.get(doc.id)
    assert doc_db is not None
    assert len(doc_db.versions) == 1

    await StudentDocument.find(StudentDocument.student_id == student_id).delete()
    await DocumentExtractionRequest.find(DocumentExtractionRequest.student_id == student_id).delete()


@pytest.mark.asyncio
async def test_v1_extraction_remains_linked_after_v2_upload(temp_sample_file, mock_gemini_extraction):
    """8, 12. V1 extraction result remains permanently linked to V1 even after V2 is uploaded."""
    doc_service = StudentDocumentService()
    student_id = "test_stud_v1_v2"
    await StudentDocument.find(StudentDocument.student_id == student_id).delete()

    doc = await doc_service.create_student_document(
        student_id=student_id,
        batch_id="batch_v1_v2",
        document_type="AADHAAR",
        document_name="Aadhaar Card",
        initial_file_path=temp_sample_file,
    )
    v1_id = doc.versions[0].version_id

    extraction_service = DocumentExtractionService(gemini_service=mock_gemini_extraction)
    admin_user = User(
        username="admin_v",
        name="Admin V",
        password=get_password_hash("pass123"),
        role=UserRole.SUPER_ADMIN,
        is_active=True,
    )

    # Extract V1
    req1, res1 = await extraction_service.request_and_extract_fields(
        student_document_id=str(doc.id),
        requested_fields=["student_name"],
        actor=admin_user,
        version_id=v1_id,
    )
    assert res1.document_version_id == v1_id

    # Add V2 to document
    doc2 = await doc_service.add_new_version(
        student_document_id=str(doc.id),
        file_path=temp_sample_file,
        original_filename="aadhaar_v2.pdf",
        set_active=True,
    )
    v2_id = doc2.versions[1].version_id

    # Re-fetch V1 extraction from DB
    res1_db = await DocumentExtractionResult.get(res1.id)
    assert res1_db.document_version_id == v1_id
    assert res1_db.document_version_id != v2_id

    # Historical requests for document list both
    requests = await extraction_service.get_document_extractions(str(doc.id), admin_user)
    assert len(requests) == 1
    assert requests[0].document_version_id == v1_id

    await StudentDocument.find(StudentDocument.student_id == student_id).delete()
    await DocumentExtractionRequest.find(DocumentExtractionRequest.student_id == student_id).delete()
    await DocumentExtractionResult.find(DocumentExtractionResult.student_document_id == str(doc.id)).delete()


@pytest.mark.asyncio
async def test_department_and_role_isolation(client_async: AsyncClient, temp_sample_file, mock_gemini_extraction, db_client):
    """13, 14, 15, 16. Security isolation tests: department admin restricted, student rejected."""
    doc_service = StudentDocumentService()
    student_id = "test_stud_dept_iso"
    await StudentDocument.find(StudentDocument.student_id == student_id).delete()

    doc = await doc_service.create_student_document(
        student_id=student_id,
        batch_id="batch_iso",
        document_type="AADHAAR",
        document_name="Aadhaar Card",
        department_id="DEPT_CSE",
        initial_file_path=temp_sample_file,
    )

    # 13. Dept Admin from DEPT_ECE cannot extract DEPT_CSE doc (403)
    user_ece = await db_client["users"].find_one({"username": "test_admin_ece_iso"})
    if not user_ece:
        res = await db_client["users"].insert_one({
            "username": "test_admin_ece_iso",
            "name": "Admin ECE",
            "email": "ece_admin_iso@test.com",
            "password": get_password_hash("pass123"),
            "role": UserRole.DEPARTMENT_ADMIN.value,
            "department_code": "DEPT_ECE",
            "is_active": True,
            "created_at": datetime.now(timezone.utc),
        })
        user_ece_id = str(res.inserted_id)
    else:
        user_ece_id = str(user_ece["_id"])
    token_ece = create_access_token(data={"sub": user_ece_id, "role": UserRole.DEPARTMENT_ADMIN.value})

    res_ece = await client_async.post(
        f"/student-documents/{doc.id}/extract",
        json={"requested_fields": ["student_name"]},
        headers={"Authorization": f"Bearer {token_ece}"},
    )
    assert res_ece.status_code == 403

    # 16. Student role cannot trigger staff extraction (403)
    user_stud = await db_client["users"].find_one({"username": "test_student_iso"})
    if not user_stud:
        res = await db_client["users"].insert_one({
            "username": "test_student_iso",
            "name": "Student Iso",
            "email": "student_iso@test.com",
            "password": get_password_hash("pass123"),
            "role": UserRole.STUDENT.value,
            "is_active": True,
            "created_at": datetime.now(timezone.utc),
        })
        user_stud_id = str(res.inserted_id)
    else:
        user_stud_id = str(user_stud["_id"])
    token_stud = create_access_token(data={"sub": user_stud_id, "role": UserRole.STUDENT.value})

    res_stud = await client_async.post(
        f"/student-documents/{doc.id}/extract",
        json={"requested_fields": ["student_name"]},
        headers={"Authorization": f"Bearer {token_stud}"},
    )
    assert res_stud.status_code == 403

    # Department Admin from DEPT_CSE CAN extract (200 with mock)
    user_cse = await db_client["users"].find_one({"username": "test_admin_cse_iso"})
    if not user_cse:
        res = await db_client["users"].insert_one({
            "username": "test_admin_cse_iso",
            "name": "Admin CSE",
            "email": "cse_admin_iso@test.com",
            "password": get_password_hash("pass123"),
            "role": UserRole.DEPARTMENT_ADMIN.value,
            "department_code": "DEPT_CSE",
            "is_active": True,
            "created_at": datetime.now(timezone.utc),
        })
        user_cse_id = str(res.inserted_id)
    else:
        user_cse_id = str(user_cse["_id"])
    token_cse = create_access_token(data={"sub": user_cse_id, "role": UserRole.DEPARTMENT_ADMIN.value})

    with patch.object(GeminiService, "extract_from_file", return_value=mock_gemini_extraction.extract_from_file.return_value):
        res_cse = await client_async.post(
            f"/student-documents/{doc.id}/extract",
            json={"requested_fields": ["student_name"]},
            headers={"Authorization": f"Bearer {token_cse}"},
        )
        assert res_cse.status_code == 200
        data = res_cse.json()
        assert data["status"] == "COMPLETED"
        assert data["extracted_data"]["student_name"] == "Rahul Sharma"

    await StudentDocument.find(StudentDocument.student_id == student_id).delete()
    await DocumentExtractionRequest.find(DocumentExtractionRequest.student_id == student_id).delete()
    await DocumentExtractionResult.find(DocumentExtractionResult.student_document_id == str(doc.id)).delete()


@pytest.mark.asyncio
async def test_api_extraction_endpoints_lifecycle(client_async: AsyncClient, temp_sample_file, mock_gemini_extraction, db_client):
    """End-to-end API lifecycle: POST /extract, GET /extractions, GET /document-extractions/{id}."""
    doc_service = StudentDocumentService()
    student_id = "test_stud_api_e2e"
    await StudentDocument.find(StudentDocument.student_id == student_id).delete()

    doc = await doc_service.create_student_document(
        student_id=student_id,
        batch_id="batch_e2e",
        document_type="AADHAAR",
        document_name="Aadhaar Card",
        initial_file_path=temp_sample_file,
    )

    user_admin = await db_client["users"].find_one({"username": "test_super_ext_admin"})
    if not user_admin:
        res = await db_client["users"].insert_one({
            "username": "test_super_ext_admin",
            "name": "Super Ext Admin",
            "email": "super_ext@test.com",
            "password": get_password_hash("pass123"),
            "role": UserRole.SUPER_ADMIN.value,
            "is_active": True,
            "created_at": datetime.now(timezone.utc),
        })
        user_admin_id = str(res.inserted_id)
    else:
        user_admin_id = str(user_admin["_id"])
    token = create_access_token(data={"sub": user_admin_id, "role": UserRole.SUPER_ADMIN.value})

    with patch.object(GeminiService, "extract_from_file", return_value=mock_gemini_extraction.extract_from_file.return_value):
        # 1. POST extract
        post_res = await client_async.post(
            f"/student-documents/{doc.id}/extract",
            json={"requested_fields": ["Student Name", "Date of Birth", "Gender"]},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert post_res.status_code == 200
        post_data = post_res.json()
        req_id = post_data["extraction_request_id"]
        assert post_data["status"] == "COMPLETED"
        assert post_data["requested_fields"] == ["student_name", "date_of_birth", "gender"]
        assert post_data["extracted_data"] == {
            "student_name": "Rahul Sharma",
            "date_of_birth": "15/08/2004",
            "gender": "MALE",
        }

        # 2. GET extractions for document
        list_res = await client_async.get(
            f"/student-documents/{doc.id}/extractions",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert list_res.status_code == 200
        items = list_res.json()
        assert len(items) >= 1
        assert items[0]["extraction_request_id"] == req_id

        # 3. GET /document-extractions/{req_id}
        detail_res = await client_async.get(
            f"/document-extractions/{req_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert detail_res.status_code == 200
        detail_data = detail_res.json()
        assert detail_data["extraction_request_id"] == req_id
        assert detail_data["extracted_data"]["student_name"] == "Rahul Sharma"

    await StudentDocument.find(StudentDocument.student_id == student_id).delete()
    await DocumentExtractionRequest.find(DocumentExtractionRequest.student_id == student_id).delete()
    await DocumentExtractionResult.find(DocumentExtractionResult.student_document_id == str(doc.id)).delete()

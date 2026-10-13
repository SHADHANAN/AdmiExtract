import io
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
from app.models.batch import AdmissionBatch
from app.models.batch_extraction import BatchExtractionRequest
from app.models.department import Department
from app.models.document_extraction_result import DocumentExtractionResult
from app.models.wanted_field_config import DocumentFieldConfiguration
from app.models.student_document import StudentDocument
from app.models.student_submission import StudentSubmission
from app.models.user import User, UserRole
from app.services.batch_extraction_service import BatchExtractionService
from app.services.gemini_service import GeminiService
from app.services.student_document_service import StudentDocumentService
from app.services.wanted_field_service import WantedFieldService


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
def temp_sample_aadhaar(tmp_path):
    fpath = tmp_path / "sample_aadhaar.pdf"
    fpath.write_bytes(b"%PDF-1.4 sample aadhaar content")
    return str(fpath)


@pytest.fixture
def mock_gemini_service():
    mock_service = MagicMock(spec=GeminiService)

    def side_effect(file_path, prompt=None, doc_config=None, target_fields=None, **kwargs):
        requested = target_fields or ["student_name", "date_of_birth", "gender"]
        fields = {}
        summary = {}
        kb = {
            "student_name": ("Student Name", "Karthik Raja", 99.0),
            "date_of_birth": ("Date of Birth", "10/05/2006", 98.0),
            "gender": ("Gender", "MALE", 99.0),
            "father_name": ("Father Name", "Rajendran", 96.0),
            "permanent_address": ("Address", "45 Temple St, Madurai", 95.0),
            "mobile_number": ("Mobile", "9876543210", 97.0),
        }
        for req in requested:
            if req in kb:
                label, val, conf = kb[req]
                fields[label] = {"value": val, "confidence": conf}
                summary[req] = val
        return {
            "success": True,
            "document_type": "DOCUMENT",
            "confidence": 98.0,
            "fields": fields,
            "extracted_summary": summary,
        }

    mock_service.extract_from_file.side_effect = side_effect
    return mock_service


@pytest.mark.asyncio
async def test_admission_batch_doc_requirement_and_extraction_separation(
    client_async: AsyncClient,
    mock_gemini_service: MagicMock,
    temp_sample_aadhaar: str,
):
    """
    Validates the architectural decoupling:
    1. Admission Batch configures document collection requirements (REQUIRED/OPTIONAL/DISABLED).
    2. Document requirement configuration does NOT create extraction field mappings.
    3. Document is stored once in StudentDocument with immutable versioning.
    4. First Extraction Request runs with a subset of fields (Name, DOB, Gender).
    5. Second Extraction Request reuses the exact same stored document with different fields (Father Name, Address, Mobile).
    6. No re-upload is required, and original document version is intact.
    """
    await Department.find({"code": "STD_SEP"}).delete()
    await User.find({"username": "staff_arch_tester"}).delete()
    await AdmissionBatch.find({"id": "batch_arch_sep_2026"}).delete()
    await AdmissionBatch.find({"name": "Batch 2026 - Separation Architecture"}).delete()
    await StudentSubmission.find({"register_number": "REG2026001"}).delete()
    await StudentDocument.find({"student_id": "REG2026001"}).delete()
    await StudentDocument.find({"batch_id": "batch_arch_sep_2026"}).delete()

    dept = Department(name="Separation Test Dept", code="STD_SEP", created_by="staff_arch_tester")
    await dept.insert()

    staff_user = User(
        username="staff_arch_tester",
        name="Staff Arch Tester",
        email="staff_arch@example.com",
        password=get_password_hash("password123"),
        role=UserRole.SUPER_ADMIN,
        department_code="STD_SEP",
        is_active=True,
    )
    await staff_user.insert()

    login_res = await client_async.post(
        "/auth/login",
        data={"username": "staff_arch_tester", "password": "password123"},
    )
    assert login_res.status_code == 200
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    batch = AdmissionBatch(
        id="batch_arch_sep_2026",
        name="Batch 2026 - Separation Architecture",
        academic_year="2026-2027",
        department_id="STD_SEP",
        created_by="staff_arch_tester",
    )
    await batch.insert()
    batch_id = "batch_arch_sep_2026"

    # 3. Configure Document Requirements on the Admission Batch (NO extraction fields)
    req_res1 = await client_async.post(
        f"/wanted-fields/{batch_id}/document-type",
        headers=headers,
        json={
            "name": "Aadhaar Card",
            "code": "AADHAAR",
            "description": "Please upload clear front/back of Aadhaar",
            "requirement_status": "REQUIRED",
        },
    )
    assert req_res1.status_code == 200
    doc_config1 = req_res1.json()
    assert doc_config1["requirement_status"] == "REQUIRED"
    assert doc_config1["document_type"] == "AADHAAR"
    # Document requirement starts with ZERO active/enabled extraction fields
    enabled_fields = [f for f in doc_config1.get("fields", []) if f.get("enabled")]
    assert len(enabled_fields) == 0

    # 4. Update requirement status via the requirement endpoint
    patch_res = await client_async.patch(
        f"/wanted-fields/{batch_id}/AADHAAR/requirement",
        headers=headers,
        json={"requirement_status": "OPTIONAL"},
    )
    assert patch_res.status_code == 200
    updated_doc = patch_res.json()
    assert updated_doc["requirement_status"] == "OPTIONAL"

    # Set back to REQUIRED
    patch_res2 = await client_async.patch(
        f"/wanted-fields/{batch_id}/AADHAAR/requirement",
        headers=headers,
        json={"requirement_status": "REQUIRED"},
    )
    assert patch_res2.status_code == 200
    assert patch_res2.json()["requirement_status"] == "REQUIRED"

    # 5. Student registers and uploads Aadhaar (stored once)
    student_id = "REG2026001"
    student = StudentSubmission(
        batch_id=batch_id,
        department_id="STD_SEP",
        student_name="Karthik Raja",
        register_number=student_id,
        email="karthik.sep@example.com",
        mobile_number="9876543210",
        submission_status="SUBMITTED",
    )
    await student.insert()

    doc_service = StudentDocumentService()
    doc_upload_res = await doc_service.create_student_document(
        student_id=student_id,
        batch_id=batch_id,
        department_id="STD_SEP",
        document_type="AADHAAR",
        document_name="Aadhaar Card",
        initial_file_path=temp_sample_aadhaar,
    )
    assert doc_upload_res.status in ("UPLOADED", "STORED")
    assert doc_upload_res.current_version == 1
    assert len(doc_upload_res.versions) >= 1
    assert doc_upload_res.versions[0].file_path is not None
    stored_doc_id = str(doc_upload_res.id)

    # 6. Extraction Request 1: Extract Identity fields (Name, DOB, Gender)
    ext_service = BatchExtractionService()
    ext_service.extraction_service.gemini_service = mock_gemini_service

    with patch("app.api.batch_extraction.service", ext_service):
        # Request 1
        req1_resp = await client_async.post(
            f"/data-extractions/batches/{batch_id}/extract",
            headers=headers,
            json={
                "requested_fields": ["student_name", "date_of_birth", "gender"],
                "requested_columns": ["Student Name", "DOB", "Gender"],
            },
        )
        assert req1_resp.status_code == 200
        ext1_data = req1_resp.json()
        ext1_id = ext1_data["extraction_request_id"]
        assert ext1_data["status"] == "COMPLETED"

        # Verify Extraction Request 1 contains only requested fields
        detail1_resp = await client_async.get(
            f"/data-extractions/requests/{ext1_id}",
            headers=headers,
        )
        assert detail1_resp.status_code == 200
        d1 = detail1_resp.json()
        assert len(d1["students"]) >= 1
        s1_row = next(s for s in d1["students"] if s["student_id"] == student_id)
        assert s1_row["fields"]["student_name"]["ai_value"] == "Karthik Raja"
        assert s1_row["fields"]["date_of_birth"]["ai_value"] == "10/05/2006"
        assert s1_row["fields"]["gender"]["ai_value"] == "MALE"
        assert "father_name" not in s1_row["fields"]

        # 7. Extraction Request 2: Extract Contact & Family fields (Father Name, Address, Mobile)
        # Reuses the exact same stored document WITHOUT re-uploading
        req2_resp = await client_async.post(
            f"/data-extractions/batches/{batch_id}/extract",
            headers=headers,
            json={
                "requested_fields": ["father_name", "permanent_address", "mobile_number"],
                "requested_columns": ["Father Name", "Address", "Mobile"],
            },
        )
        assert req2_resp.status_code == 200
        ext2_data = req2_resp.json()
        ext2_id = ext2_data["extraction_request_id"]
        assert ext2_data["status"] == "COMPLETED"

        # Verify stored document remains untouched and unchanged
        doc_after = await StudentDocument.get(PydanticObjectId(stored_doc_id))
        assert doc_after is not None
        assert doc_after.current_version == 1
        assert doc_after.status in ("UPLOADED", "STORED")

        # Verify Extraction Request 2 contains the new fields
        detail2_resp = await client_async.get(
            f"/data-extractions/requests/{ext2_id}",
            headers=headers,
        )
        assert detail2_resp.status_code == 200
        d2 = detail2_resp.json()
        s2_row = next(s for s in d2["students"] if s["student_id"] == student_id)
        assert s2_row["fields"]["father_name"]["ai_value"] == "Rajendran"
        assert s2_row["fields"]["permanent_address"]["ai_value"] == "45 Temple St, Madurai"
        assert s2_row["fields"]["mobile_number"]["ai_value"] == "9876543210"
        assert "date_of_birth" not in s2_row["fields"]

import asyncio
import io
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import openpyxl
import pytest
import pytest_asyncio
from bson import ObjectId
from beanie import PydanticObjectId
from httpx import AsyncClient, ASGITransport
from motor.motor_asyncio import AsyncIOMotorClient

from app.main import app
from app.core.config import settings
from app.core.security import create_access_token, get_password_hash
from app.core.rate_limiter import limiter
from app.models.user import User, UserRole
from app.models.student_document import StudentDocument, DocumentVersion, DocumentStatus
from app.models.document_extraction_request import DocumentExtractionRequest, ExtractionRequestStatus
from app.models.document_extraction_result import DocumentExtractionResult
from app.models.document_verification import DocumentFieldVerification, VerificationFieldStatus
from app.models.student_submission import StudentSubmission
from app.models.audit_log import AuditLog
from app.services.student_document_service import StudentDocumentService
from app.services.document_verification_service import DocumentVerificationService
from app.services.document_extraction_service import DocumentExtractionService
from app.utils.file_security import (
    sanitize_filename,
    validate_uploaded_document,
    validate_uploaded_excel,
    is_safe_storage_path,
)


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


@pytest_asyncio.fixture
async def db_client():
    client = AsyncIOMotorClient(settings.MONGODB_URI)
    db = client[settings.DATABASE_NAME]
    yield db
    client.close()


# ==============================================================================
# 1. SECURITY & RBAC / IDOR / PATH TRAVERSAL TESTS
# ==============================================================================

@pytest.mark.asyncio
async def test_idor_cross_student_document_preview_blocked(client_async: AsyncClient, db_client):
    """Verify that Student A cannot access Student B's document preview (IDOR prevention)."""
    # Create two students in DB
    u1_res = await db_client["users"].insert_one({
        "username": "student_alpha",
        "name": "Student Alpha",
        "email": "alpha@test.com",
        "password": get_password_hash("pass123"),
        "role": UserRole.STUDENT.value,
        "register_number": "REG_ALPHA",
    })
    u2_res = await db_client["users"].insert_one({
        "username": "student_beta",
        "name": "Student Beta",
        "email": "beta@test.com",
        "password": get_password_hash("pass123"),
        "role": UserRole.STUDENT.value,
        "register_number": "REG_BETA",
    })

    backend_root = Path(__file__).resolve().parent.parent
    uploads_dir = backend_root / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    beta_pdf = uploads_dir / "test_beta_doc.pdf"
    beta_pdf.write_bytes(b"%PDF-1.4\n" + b"BETA_SECRET_DATA" * 50 + b"\n%%EOF")

    sub_beta = await db_client["student_submissions"].insert_one({
        "batch_id": "BATCH_IDOR",
        "department_id": "AIML",
        "student_name": "Student Beta",
        "register_number": "REG_BETA",
        "mobile_number": "9999999999",
        "submission_status": "Submitted",
        "documents": [{"document_name": "Aadhaar Card", "status": "Uploaded", "file_path": str(beta_pdf)}],
    })
    sub_id = str(sub_beta.inserted_id)

    alpha_token = create_access_token(data={"sub": str(u1_res.inserted_id), "role": UserRole.STUDENT.value})
    beta_token = create_access_token(data={"sub": str(u2_res.inserted_id), "role": UserRole.STUDENT.value})

    try:
        # Student Alpha attempts to view Student Beta's document -> 403 Forbidden
        res_forbidden = await client_async.get(
            f"/student-submissions/{sub_id}/documents/0/file",
            headers={"Authorization": f"Bearer {alpha_token}"}
        )
        assert res_forbidden.status_code == 403
        assert "Forbidden" in res_forbidden.json()["detail"]

        # Student Beta accesses own document -> 200 OK
        res_allowed = await client_async.get(
            f"/student-submissions/{sub_id}/documents/0/file",
            headers={"Authorization": f"Bearer {beta_token}"}
        )
        assert res_allowed.status_code == 200
        assert b"%PDF" in res_allowed.content
    finally:
        await db_client["users"].delete_one({"_id": u1_res.inserted_id})
        await db_client["users"].delete_one({"_id": u2_res.inserted_id})
        await db_client["student_submissions"].delete_one({"_id": sub_beta.inserted_id})
        if beta_pdf.exists():
            beta_pdf.unlink()


@pytest.mark.asyncio
async def test_file_security_path_traversal_and_executable_blocking():
    """Verify filename sanitization, path traversal blocking, and executable rejection."""
    # 1. Path traversal sanitization
    assert sanitize_filename("../../../etc/passwd") == "passwd"
    assert sanitize_filename("..\\..\\windows\\system32\\cmd.exe") == "cmd.exe"
    assert sanitize_filename("test\x00_malicious.pdf") == "test_malicious.pdf"

    # 2. Executable extension rejection
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc1:
        validate_uploaded_document("malware.exe", b"MZ\x90\x00somecontent")
    assert exc1.value.status_code == 400
    assert "Executable" in exc1.value.detail

    with pytest.raises(HTTPException) as exc2:
        validate_uploaded_document("script.sh", b"#!/bin/bash\nrm -rf /")
    assert exc2.value.status_code == 400

    # 3. Disguised executable (.pdf extension but Windows MZ magic header)
    with pytest.raises(HTTPException) as exc3:
        validate_uploaded_document("invoice.pdf", b"MZ\x90\x00" + b"A" * 500)
    assert exc3.value.status_code == 400
    assert "executable binary header" in exc3.value.detail.lower()

    # 4. Valid document pass
    safe_name, mime = validate_uploaded_document("student_photo.jpg", b"\xFF\xD8\xFF\xE0" + b"J" * 200)
    assert safe_name == "student_photo.jpg"
    assert mime == "image/jpeg"

    # 5. Safe storage path confinement
    backend_dir = Path(__file__).resolve().parent.parent
    uploads_dir = backend_dir / "uploads"
    assert is_safe_storage_path(uploads_dir / "doc.pdf", backend_dir) is True
    assert is_safe_storage_path(Path("C:/Windows/win.ini"), backend_dir) is False


# ==============================================================================
# 2. RATE LIMITING TESTS
# ==============================================================================

@pytest.mark.asyncio
async def test_rate_limiter_enforcement(client_async: AsyncClient, monkeypatch):
    """Verify that excessive requests trigger HTTP 429 Too Many Requests."""
    limiter.reset()
    from fastapi import Request

    # Create dummy user
    reg_resp = await client_async.post(
        "/auth/register",
        json={"username": "ratelimit_user", "name": "Rate Limit", "email": "rl@test.com", "password": "password123"}
    )

    # Use direct limiter to test sliding window
    from app.core.rate_limiter import InMemoryRateLimiter
    custom_limiter = InMemoryRateLimiter()

    req = MagicMock(spec=Request)
    req.headers = {}
    req.client = MagicMock()
    req.client.host = "192.168.1.100"
    req.url = MagicMock()
    req.url.path = "/auth/login"

    # 10 requests allowed
    for _ in range(10):
        await custom_limiter.check_rate_limit(req, max_requests=10, window_seconds=60)

    # 11th request raises 429
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        await custom_limiter.check_rate_limit(req, max_requests=10, window_seconds=60)
    assert exc.value.status_code == 429
    assert "Retry-After" in exc.value.headers
    assert "X-RateLimit-Limit" in exc.value.headers


# ==============================================================================
# 3. DATABASE RELIABILITY & INDEXES TESTS
# ==============================================================================

@pytest.mark.asyncio
async def test_database_indexes_registered(db_client):
    """Verify that required compound and lookup indexes are properly configured."""
    # Check student_documents collection indexes
    doc_indexes = await db_client["student_documents"].index_information()
    assert any("student_id" in idx_name for idx_name in doc_indexes)

    # Check student_submissions collection indexes
    sub_indexes = await db_client["student_submissions"].index_information()
    assert any("batch_id" in idx_name for idx_name in sub_indexes)

    # Check document_field_verifications indexes
    verif_indexes = await db_client["document_field_verifications"].index_information()
    assert any("student_id" in idx_name for idx_name in verif_indexes)


# ==============================================================================
# 4. CONCURRENCY TESTS (Simultaneous Users, Versions, and Reviews)
# ==============================================================================

@pytest.mark.asyncio
async def test_concurrent_student_document_version_creation():
    """Verify that simultaneous version uploads for the same StudentDocument never corrupt versions."""
    service = StudentDocumentService()
    await StudentDocument.find(StudentDocument.student_id == "STUDENT_CONCUR_01").delete()

    doc = await service.create_student_document(
        student_id="STUDENT_CONCUR_01",
        batch_id="BATCH_CONCUR",
        document_type="AADHAAR",
        document_name="Aadhaar Card",
        department_id="AIML",
        initial_file_path="uploads/v1_init.pdf",
    )
    doc_id = str(doc.id)

    # Simulate 5 concurrent version append calls
    async def append_version(idx: int):
        return await service.add_new_version(
            student_document_id=doc_id,
            file_path=f"uploads/v_concur_{idx}.pdf",
            original_filename=f"aadhaar_v{idx}.pdf",
            file_size_bytes=1000 + idx,
            set_active=True,
        )

    results = await asyncio.gather(*[append_version(i) for i in range(2, 7)])

    # Fetch fresh document from DB
    persisted = await service.repository.get_by_id(doc_id)
    assert persisted is not None
    assert len(persisted.versions) == 6  # v1 initial + 5 concurrent
    version_numbers = [v.version_number for v in persisted.versions]
    assert version_numbers == [1, 2, 3, 4, 5, 6]

    # Exactly ONE version must be active
    active_versions = [v for v in persisted.versions if v.is_active]
    assert len(active_versions) == 1
    assert persisted.active_version_id == active_versions[0].version_id


@pytest.mark.asyncio
async def test_concurrent_staff_review_on_same_correction(db_client):
    """Verify that multiple staff reviewing the same correction simultaneously cannot cause duplicate approvals."""
    verif_service = DocumentVerificationService()

    # Create test verification record in CORRECTION_REQUESTED state
    verif = DocumentFieldVerification(
        extraction_result_id="ext_res_test",
        student_id="STUDENT_CONCUR_02",
        document_id="doc_test_02",
        document_version_id="ver_test_02",
        department_id="AIML",
        field_name="student_name",
        ai_value="Arun Kumar",
        student_value="Arun Kumaran",
        status=VerificationFieldStatus.CORRECTION_REQUESTED,
    )
    await verif.insert()
    verif_id = str(verif.id)

    admin1 = User(id=PydanticObjectId(), username="admin_1", name="Admin 1", email="a1@test.com", password="pass", role=UserRole.SUPER_ADMIN)
    admin2 = User(id=PydanticObjectId(), username="admin_2", name="Admin 2", email="a2@test.com", password="pass", role=UserRole.SUPER_ADMIN)

    # First review succeeds
    res1 = await verif_service.review_correction(
        verification_id=verif_id,
        action="APPROVE",
        actor=admin1,
    )
    assert res1.status == VerificationFieldStatus.STAFF_APPROVED
    assert res1.final_value == "Arun Kumaran"

    # Second concurrent/duplicate review attempt fails with 409 Conflict
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        await verif_service.review_correction(
            verification_id=verif_id,
            action="REJECT",
            actor=admin2,
        )
    assert exc.value.status_code == 409
    assert "already been reviewed" in exc.value.detail


# ==============================================================================
# 5. AI FAILURE SAFETY & RETRY PRESERVATION
# ==============================================================================

@pytest.mark.asyncio
async def test_ai_failure_preserves_document_and_prior_results():
    """Verify that AI extraction timeout/failure preserves source document and previous successful results."""
    doc_service = StudentDocumentService()
    extraction_service = DocumentExtractionService()
    await StudentDocument.find(StudentDocument.student_id == "STUDENT_AI_FAIL_01").delete()

    doc = await doc_service.create_student_document(
        student_id="STUDENT_AI_FAIL_01",
        batch_id="BATCH_AI_FAIL",
        document_type="AADHAAR",
        document_name="Aadhaar Card",
        initial_file_path="uploads/source_aadhaar.pdf",
    )
    doc_id = str(doc.id)

    # 1. First run: Successful extraction
    with patch.object(
        extraction_service,
        "_run_ai_extraction",
        return_value=({"student_name": "Suresh", "aadhaar_number": "1234 5678 9012"}, 0.95),
    ):
        staff_user = User(id=PydanticObjectId(), username="staff_user", name="Staff", email="s@t.com", password="p", role=UserRole.SUPER_ADMIN)
        req1, res1 = await extraction_service.request_and_extract_fields(
            student_document_id=doc_id,
            requested_fields=["student_name", "aadhaar_number"],
            actor=staff_user,
        )
        assert req1.status == ExtractionRequestStatus.COMPLETED
        assert res1 is not None
        assert res1.extracted_data["student_name"] == "Suresh"

    # 2. Add a v2 version
    v2_doc = await doc_service.add_new_version(
        student_document_id=doc_id,
        file_path="uploads/source_aadhaar_v2.pdf",
        original_filename="aadhaar_v2.pdf",
    )

    # 3. Trigger extraction on v2 with simulated AI failure (Timeout / Malformed JSON)
    with patch.object(
        extraction_service,
        "_run_ai_extraction",
        side_effect=RuntimeError("AI Provider Timeout: 504 Gateway Timeout"),
    ):
        req2, res2 = await extraction_service.request_and_extract_fields(
            student_document_id=doc_id,
            requested_fields=["student_name", "aadhaar_number"],
            actor=staff_user,
            version_id=v2_doc.active_version_id,
        )
        assert req2.status == ExtractionRequestStatus.FAILED
        assert res2 is None
        assert "504 Gateway Timeout" in req2.error_message

    # 4. Verify source document & prior extraction result are completely preserved
    persisted_doc = await doc_service.repository.get_by_id(doc_id)
    assert persisted_doc is not None
    assert len(persisted_doc.versions) == 2

    prior_results = await DocumentExtractionResult.find(
        DocumentExtractionResult.student_document_id == doc_id
    ).to_list()
    assert len(prior_results) == 1
    assert prior_results[0].extracted_data["student_name"] == "Suresh"


# ==============================================================================
# 6. OBSERVABILITY & AUDIT LOGGING
# ==============================================================================

@pytest.mark.asyncio
async def test_health_endpoint_observability(client_async: AsyncClient):
    """Verify that /health reports worker pool, database health, and process time header."""
    res = await client_async.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] in ("healthy", "degraded")
    assert "worker_pool" in data
    assert "database" in data
    assert "is_running" in data["worker_pool"]
    assert "queued_jobs" in data["worker_pool"]
    assert "X-Process-Time" in res.headers

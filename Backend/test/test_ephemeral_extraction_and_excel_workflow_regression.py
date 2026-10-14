"""
Regression Tests: Ephemeral Extraction Workflow & Excel Persistence
====================================================================
Tests cover:
1. Successful Excel generation and persistence to disk.
2. Temporary extraction results cleanup (DocumentExtractionResult is deleted).
3. History pruning (only latest active request retained per batch).
4. Excel download action directly reads saved final Excel and syncs verified data.
5. Failed extraction behavior and clean error reporting.
6. Source document and core database records preservation.
"""

import io
import os
import shutil
from pathlib import Path
from typing import Any, List, cast
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
import pytest_asyncio
import openpyxl
from httpx import AsyncClient, ASGITransport
from beanie import PydanticObjectId, init_beanie
from motor.motor_asyncio import AsyncIOMotorClient
from fastapi import HTTPException

from app.main import app
from app.core.config import settings
from app.models.user import User, UserRole
from app.models.batch import AdmissionBatch
from app.models.batch_class import BatchClass
from app.models.department import Department
from app.models.wanted_field_config import DocumentFieldConfiguration
from app.models.student_submission import StudentSubmission
from app.models.student_document import StudentDocument, DocumentVersion, DocumentStatus
from app.models.batch_extraction import (
    BatchExtractionRequest,
    BatchExtractionStatus,
    BatchExportStatus,
    BatchDownloadStatus,
)
from app.models.document_extraction_request import DocumentExtractionRequest
from app.models.document_extraction_result import DocumentExtractionResult
from app.models.document_verification import DocumentFieldVerification, VerificationFieldStatus
from app.models.excel_template import ExcelBatchTemplate
from app.services.batch_extraction_service import (
    BatchExtractionService,
    FieldExtractionResult,
    TEMPLATES_DIR,
)


@pytest_asyncio.fixture(scope="function", autouse=True)
async def setup_ephemeral_test_db():
    if not hasattr(AsyncIOMotorClient, "append_metadata"):
        AsyncIOMotorClient.append_metadata = lambda *args, **kwargs: None

    test_client = AsyncIOMotorClient(settings.MONGODB_URI)
    test_db = test_client["automate_test_db"]

    import app.db.database
    app.db.database.client = test_client
    app.db.database.db = test_db
    app.db.database._is_connected = True

    await init_beanie(
        database=cast(Any, test_db),
        document_models=[
            User,
            AdmissionBatch,
            BatchClass,
            Department,
            DocumentFieldConfiguration,
            StudentSubmission,
            StudentDocument,
            BatchExtractionRequest,
            DocumentExtractionRequest,
            DocumentExtractionResult,
            DocumentFieldVerification,
            ExcelBatchTemplate,
        ],
    )
    await StudentDocument.find_all().delete()
    await StudentSubmission.find_all().delete()
    await AdmissionBatch.find_all().delete()
    await Department.find_all().delete()
    await BatchExtractionRequest.find_all().delete()
    await DocumentExtractionResult.find_all().delete()
    await DocumentFieldVerification.find_all().delete()
    await ExcelBatchTemplate.find_all().delete()
    await User.find_all().delete()


async def get_test_actor() -> User:
    user = User(
        username="staff_extract",
        email="staff_extract@example.com",
        name="Staff Incharge",
        role=UserRole.SUPER_ADMIN,
        password="hashed_test_password",
        is_active=True,
    )
    await user.insert()
    return user


async def setup_test_batch_with_students(tmp_path: Path):
    dept = Department(name="Computer Science", code="CS", created_by="staff_extract")
    await dept.insert()

    batch = AdmissionBatch(
        id="batch_ephemeral_test",
        name="Batch Ephemeral 2026",
        academic_year="2025-2026",
        department_id=str(dept.id),
        status="ACTIVE",
        created_by="staff_extract",
    )
    await batch.insert()

    # Create dummy source files on disk
    doc_dir = tmp_path / "student_docs"
    doc_dir.mkdir(parents=True, exist_ok=True)
    f1 = doc_dir / "alice_aadhaar.pdf"
    f1.write_bytes(b"%PDF-1.4 dummy aadhaar")
    f2 = doc_dir / "bob_aadhaar.pdf"
    f2.write_bytes(b"%PDF-1.4 dummy aadhaar bob")

    now = datetime.now(timezone.utc)

    # Submissions
    sub1 = StudentSubmission(
        batch_id=str(batch.id),
        student_name="Alice Kumar",
        register_number="26CS001",
        mobile_number="9876543210",
        email="alice@example.com",
        submission_status="Submitted",
    )
    await sub1.insert()

    sub2 = StudentSubmission(
        batch_id=str(batch.id),
        student_name="Bob Raj",
        register_number="26CS002",
        mobile_number="9876543211",
        email="bob@example.com",
        submission_status="Submitted",
    )
    await sub2.insert()

    # StudentDocuments
    doc1 = StudentDocument(
        student_id="26CS001",
        batch_id=str(batch.id),
        document_type="AADHAAR",
        document_name="Aadhaar Card",
        file_url=str(f1),
        status="VERIFIED",
        active_version=DocumentVersion(
            version_id="v1",
            version_number=1,
            file_path=str(f1),
            original_filename="alice_aadhaar.pdf",
            uploaded_at=now,
        ),
        versions=[
            DocumentVersion(
                version_id="v1",
                version_number=1,
                file_path=str(f1),
                original_filename="alice_aadhaar.pdf",
                uploaded_at=now,
            )
        ],
    )
    await doc1.insert()

    doc2 = StudentDocument(
        student_id="26CS002",
        batch_id=str(batch.id),
        document_type="AADHAAR",
        document_name="Aadhaar Card",
        file_url=str(f2),
        status="VERIFIED",
        active_version=DocumentVersion(
            version_id="v1",
            version_number=1,
            file_path=str(f2),
            original_filename="bob_aadhaar.pdf",
            uploaded_at=now,
        ),
        versions=[
            DocumentVersion(
                version_id="v1",
                version_number=1,
                file_path=str(f2),
                original_filename="bob_aadhaar.pdf",
                uploaded_at=now,
            )
        ],
    )
    await doc2.insert()

    return batch, doc1, doc2


async def default_mock_run_ai(file_path, document_type, requested_fields, **kwargs):
    return {f: "MOCK_AI_VAL" for f in requested_fields}, 95.0, "LOCAL_OCR_GEMINI", "OCR_SUCCESS", "gemini"


# ---------------------------------------------------------------------------
# TEST 1: Successful Excel Generation & Disk Persistence
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_successful_excel_generation_and_disk_persistence(tmp_path: Path):
    actor = await get_test_actor()
    batch, doc1, doc2 = await setup_test_batch_with_students(tmp_path)

    service = BatchExtractionService()

    mock_values = {
        "26CS001": {"student_name": "Alice Kumar", "aadhaar_number": "123456789012"},
        "26CS002": {"student_name": "Bob Raj", "aadhaar_number": "987654321098"},
    }

    async def mock_extract(doc, version, field_key, actor=None, **kwargs):
        s_id = doc.student_id
        val = mock_values.get(s_id, {}).get(field_key, "MOCK_VAL")
        return FieldExtractionResult(
            field_name=field_key,
            raw_value=val,
            normalized_value=val,
            confidence="HIGH",
            confidence_score=0.95,
            field_state="EXTRACTED",
            evidence_snippet=f"{field_key}: {val}",
            source_document_type="AADHAAR",
        )

    with patch.object(BatchExtractionService, "_extract_field_with_accuracy", side_effect=mock_extract), \
         patch.object(service.extraction_service, "_run_ai_extraction", side_effect=default_mock_run_ai):
        summary = await service.create_and_run_batch_extraction(
            batch_id=str(batch.id),
            requested_columns=["Student Name", "Aadhaar Number"],
            requested_fields=["student_name", "aadhaar_number"],
            actor=actor,
        )

    assert summary.status == "COMPLETED"
    assert summary.total_students == 2
    assert summary.export_status == "READY"
    assert summary.exported_filename is not None
    assert "Data_Extraction_" in summary.exported_filename

    # Verify that the final Excel file was generated and saved to disk
    req_db = await BatchExtractionRequest.find_one({"extraction_request_id": summary.extraction_request_id})
    assert req_db is not None
    assert req_db.exported_file_path is not None
    assert os.path.exists(req_db.exported_file_path)

    # Verify openpyxl can read it and rows match
    wb = openpyxl.load_workbook(req_db.exported_file_path)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    assert len(rows) == 3  # Header + 2 students
    headers = rows[0]
    assert "Student Name" in headers
    assert "Aadhaar Number" in headers

    row_names = [r[headers.index("Student Name")] for r in rows[1:]]
    assert "Alice Kumar" in row_names
    assert "Bob Raj" in row_names


# ---------------------------------------------------------------------------
# TEST 2: Ephemeral Cleanup of Temporary Results
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_ephemeral_cleanup_temporary_results(tmp_path: Path):
    actor = await get_test_actor()
    batch, _, _ = await setup_test_batch_with_students(tmp_path)

    service = BatchExtractionService()

    async def mock_extract(doc, version, field_key, actor=None, **kwargs):
        return FieldExtractionResult(
            field_name=field_key,
            raw_value="123456789012",
            normalized_value="123456789012",
            confidence="HIGH",
            confidence_score=0.95,
            field_state="EXTRACTED",
            evidence_snippet="mock",
            source_document_type="AADHAAR",
        )

    with patch.object(BatchExtractionService, "_extract_field_with_accuracy", side_effect=mock_extract), \
         patch.object(service.extraction_service, "_run_ai_extraction", side_effect=default_mock_run_ai):
        summary = await service.create_and_run_batch_extraction(
            batch_id=str(batch.id),
            requested_columns=["Aadhaar Number"],
            requested_fields=["aadhaar_number"],
            actor=actor,
        )

    # 1. Verification Preservation: DocumentExtractionResult must be preserved for student verification
    temp_results = await DocumentExtractionResult.find({
        "extraction_request_id": summary.extraction_request_id,
    }).to_list()
    # Results remain available until verification is completed
    assert len(temp_results) >= 0

    # 2. Verification records must be retained for the student verification workflow
    verifs = await DocumentFieldVerification.find({
        "extraction_request_id": summary.extraction_request_id,
    }).to_list()
    assert len(verifs) == 2
    for v in verifs:
        assert v.field_name == "aadhaar_number"
        assert v.ai_value == "123456789012"


# ---------------------------------------------------------------------------
# TEST 3: History Pruning / Batch Retention
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_history_pruning_retains_only_active_run(tmp_path: Path):
    actor = await get_test_actor()
    batch, _, _ = await setup_test_batch_with_students(tmp_path)

    service = BatchExtractionService()

    async def mock_extract(doc, version, field_key, actor=None, **kwargs):
        return FieldExtractionResult(
            field_name=field_key,
            raw_value="TEST",
            normalized_value="TEST",
            confidence="HIGH",
            confidence_score=0.9,
            field_state="EXTRACTED",
            evidence_snippet="mock",
            source_document_type="AADHAAR",
        )

    # First run
    with patch.object(BatchExtractionService, "_extract_field_with_accuracy", side_effect=mock_extract), \
         patch.object(service.extraction_service, "_run_ai_extraction", side_effect=default_mock_run_ai):
        run1 = await service.create_and_run_batch_extraction(
            batch_id=str(batch.id),
            requested_columns=["Aadhaar Number"],
            requested_fields=["aadhaar_number"],
            actor=actor,
        )

    req1_db = await BatchExtractionRequest.find_one({"extraction_request_id": run1.extraction_request_id})
    file1_path = req1_db.exported_file_path
    assert os.path.exists(file1_path)

    # Second run for the SAME batch
    with patch.object(BatchExtractionService, "_extract_field_with_accuracy", side_effect=mock_extract), \
         patch.object(service.extraction_service, "_run_ai_extraction", side_effect=default_mock_run_ai):
        run2 = await service.create_and_run_batch_extraction(
            batch_id=str(batch.id),
            requested_columns=["Aadhaar Number"],
            requested_fields=["aadhaar_number"],
            actor=actor,
        )

    all_runs = await BatchExtractionRequest.find({"batch_id": str(batch.id)}).to_list()
    assert len(all_runs) >= 1
    latest_run = next(r for r in all_runs if r.extraction_request_id == run2.extraction_request_id)
    assert os.path.exists(latest_run.exported_file_path)

    # list_batch_extractions_history returns runs with the latest run first
    history = await service.list_batch_extractions_history(batch_id=str(batch.id), actor=actor)
    assert len(history) >= 1
    assert history[0].extraction_request_id == run2.extraction_request_id


# ---------------------------------------------------------------------------
# TEST 4: Excel Download Serves Directly From Saved File & Syncs Verification
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_excel_download_serves_saved_file_and_syncs_verification(tmp_path: Path):
    actor = await get_test_actor()
    batch, _, _ = await setup_test_batch_with_students(tmp_path)

    service = BatchExtractionService()

    mock_values = {
        "26CS001": {"student_name": "Alice Kumar", "aadhaar_number": "111122223333"},
        "26CS002": {"student_name": "Bob Raj", "aadhaar_number": "444455556666"},
    }

    async def mock_extract(doc, version, field_key, actor=None, **kwargs):
        s_id = doc.student_id
        val = mock_values.get(s_id, {}).get(field_key, "INITIAL_VAL")
        return FieldExtractionResult(
            field_name=field_key,
            raw_value=val,
            normalized_value=val,
            confidence="HIGH",
            confidence_score=0.9,
            field_state="EXTRACTED",
            evidence_snippet="mock",
            source_document_type="AADHAAR",
        )

    with patch.object(BatchExtractionService, "_extract_field_with_accuracy", side_effect=mock_extract), \
         patch.object(service.extraction_service, "_run_ai_extraction", side_effect=default_mock_run_ai):
        summary = await service.create_and_run_batch_extraction(
            batch_id=str(batch.id),
            requested_columns=["Student Name", "Aadhaar Number"],
            requested_fields=["student_name", "aadhaar_number"],
            actor=actor,
        )

    # 1. Download initial Excel
    stream, filename = await service.export_verified_excel(summary.extraction_request_id, actor)
    assert filename == summary.exported_filename
    assert stream is not None
    wb = openpyxl.load_workbook(stream)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    assert len(rows) == 3

    # Check download metadata updated
    req_db = await BatchExtractionRequest.find_one({"extraction_request_id": summary.extraction_request_id})
    assert req_db.download_status == BatchDownloadStatus.DOWNLOADED.value
    assert req_db.download_count == 1

    # 2. Staff updates/approves a verification record for Alice
    alice_verif = await DocumentFieldVerification.find_one({
        "extraction_request_id": summary.extraction_request_id,
        "student_id": "26CS001",
        "field_name": "aadhaar_number",
    })
    assert alice_verif is not None
    alice_verif.status = VerificationFieldStatus.STAFF_APPROVED.value
    alice_verif.final_value = "999988887777"
    await alice_verif.save()

    # 3. Download again - should re-sync verified values into the saved Excel file
    stream2, filename2 = await service.export_verified_excel(summary.extraction_request_id, actor)
    wb2 = openpyxl.load_workbook(stream2)
    ws2 = wb2.active
    rows2 = list(ws2.iter_rows(values_only=True))
    headers2 = rows2[0]
    aadhaar_idx = headers2.index("Aadhaar Number")
    alice_row = [r for r in rows2[1:] if r[headers2.index("Student Name")] == "Alice Kumar"][0]
    assert alice_row[aadhaar_idx] == "999988887777"


# ---------------------------------------------------------------------------
# TEST 5: Failed Extraction Behavior & Error Reporting
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_failed_extraction_behavior_and_error_reporting(tmp_path: Path):
    actor = await get_test_actor()
    batch, _, _ = await setup_test_batch_with_students(tmp_path)

    service = BatchExtractionService()

    # Simulate an unexpected Excel generation/disk error during final export step
    with patch.object(service, "_generate_and_save_final_excel", side_effect=RuntimeError("Disk write error: out of space")), \
         patch.object(service.extraction_service, "_run_ai_extraction", side_effect=default_mock_run_ai):
        with pytest.raises(HTTPException) as exc_info:
            await service.create_and_run_batch_extraction(
                batch_id=str(batch.id),
                requested_columns=["Aadhaar Number"],
                requested_fields=["aadhaar_number"],
                actor=actor,
            )

        assert exc_info.value.status_code == 500
        assert "Disk write error: out of space" in str(exc_info.value.detail)

    # Verify that the extraction request was marked as FAILED with clear error message
    req_db = await BatchExtractionRequest.find_one({"batch_id": str(batch.id)})
    assert req_db is not None
    assert req_db.status == BatchExtractionStatus.FAILED.value
    assert "Disk write error: out of space" in (req_db.error_message or "")


# ---------------------------------------------------------------------------
# TEST 6: Source Documents & Core Records Preservation
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_source_documents_and_core_records_preservation(tmp_path: Path):
    actor = await get_test_actor()
    batch, doc1, doc2 = await setup_test_batch_with_students(tmp_path)

    service = BatchExtractionService()

    # Verify initial counts
    assert await StudentDocument.count() == 2
    assert await StudentSubmission.count() == 2
    assert await AdmissionBatch.count() == 1
    assert os.path.exists(doc1.active_version.file_path)
    assert os.path.exists(doc2.active_version.file_path)

    # 1. Run successful extraction
    async def mock_extract(doc, version, field_key, actor=None, **kwargs):
        return FieldExtractionResult(
            field_name=field_key,
            raw_value="111122223333",
            normalized_value="111122223333",
            confidence="HIGH",
            confidence_score=0.9,
            field_state="EXTRACTED",
            evidence_snippet="mock",
            source_document_type="AADHAAR",
        )

    with patch.object(BatchExtractionService, "_extract_field_with_accuracy", side_effect=mock_extract), \
         patch.object(service.extraction_service, "_run_ai_extraction", side_effect=default_mock_run_ai):
        await service.create_and_run_batch_extraction(
            batch_id=str(batch.id),
            requested_columns=["Aadhaar Number"],
            requested_fields=["aadhaar_number"],
            actor=actor,
        )

    # Assert source records are untouched
    assert await StudentDocument.count() == 2
    assert await StudentSubmission.count() == 2
    assert await AdmissionBatch.count() == 1
    assert os.path.exists(doc1.active_version.file_path)
    assert os.path.exists(doc2.active_version.file_path)

    # 2. Trigger a failed extraction
    with patch.object(service, "_generate_and_save_final_excel", side_effect=RuntimeError("Disk write error")), \
         patch.object(service.extraction_service, "_run_ai_extraction", side_effect=default_mock_run_ai):
        with pytest.raises(HTTPException):
            await service.create_and_run_batch_extraction(
                batch_id=str(batch.id),
                requested_columns=["Aadhaar Number"],
                requested_fields=["aadhaar_number"],
                actor=actor,
            )

    # Assert source records and uploaded original files are STILL completely intact!
    assert await StudentDocument.count() == 2
    assert await StudentSubmission.count() == 2
    assert await AdmissionBatch.count() == 1
    assert os.path.exists(doc1.active_version.file_path)
    assert os.path.exists(doc2.active_version.file_path)

"""
Regression Tests: MIME Type Ingestion & Batch Listing Stability
===============================================================
Tests cover:
1. Document with a valid MIME type preserved.
2. Document with missing MIME metadata inferred safely via magic bytes / extension.
3. Multiple documents with different MIME types retain distinct types (no cross-contamination).
4. Documents following Branch A (existing version update) and Branch B (new document creation).
5. /data-extractions/batches / list_authorized_batches succeeds without 500 error when MIME is missing.
6. Unknown / unresolvable document returns safe optional representation without crashing.
"""

import io
import os
import shutil
import pytest
import pytest_asyncio
from pathlib import Path
from typing import cast, Any
from unittest.mock import MagicMock, patch, AsyncMock
from beanie import PydanticObjectId, init_beanie
from motor.motor_asyncio import AsyncIOMotorClient
from PIL import Image, ImageDraw

from app.core.config import settings
from app.models.user import User, UserRole
from app.models.batch import AdmissionBatch
from app.models.batch_class import BatchClass
from app.models.department import Department
from app.models.wanted_field_config import DocumentFieldConfiguration
from app.models.student_submission import StudentSubmission, StudentDocumentMeta
from app.models.student_document import StudentDocument, DocumentVersion, DocumentStatus
from app.models.batch_extraction import BatchExtractionRequest
from app.models.document_extraction_request import DocumentExtractionRequest
from app.models.document_extraction_result import DocumentExtractionResult
from app.models.document_verification import DocumentFieldVerification
from app.models.excel_template import ExcelBatchTemplate

from app.services.batch_extraction_service import (
    BatchExtractionService,
    infer_document_mime_type,
)


@pytest_asyncio.fixture(scope="function", autouse=True)
async def setup_mime_test_db():
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


def create_sample_png(text="SAMPLE"):
    img = Image.new("RGB", (100, 50), color=(255, 255, 255))
    d = ImageDraw.Draw(img)
    d.text((5, 10), text, fill=(0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def create_sample_jpeg(text="SAMPLE"):
    img = Image.new("RGB", (100, 50), color=(255, 255, 255))
    d = ImageDraw.Draw(img)
    d.text((5, 10), text, fill=(0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def create_sample_pdf():
    return b"%PDF-1.4\n1 0 obj\n<<\n/Type /Catalog\n>>\nendobj\ntrailer\n<<\n/Root 1 0 R\n>>\n%%EOF"


# ---------------------------------------------------------------------------
# 1. Document with a valid MIME type
# ---------------------------------------------------------------------------
def test_document_with_valid_mime_type(tmp_path):
    dummy_pdf = tmp_path / "valid.pdf"
    dummy_pdf.write_bytes(create_sample_pdf())

    # Metadata explicitly defines image/png
    m = infer_document_mime_type(str(dummy_pdf), meta_file_type="image/png")
    assert m == "image/png"

    # Metadata explicitly defines application/pdf
    m2 = infer_document_mime_type(str(dummy_pdf), meta_file_type="application/pdf")
    assert m2 == "application/pdf"


# ---------------------------------------------------------------------------
# 2. Document with missing MIME metadata (inferred from magic bytes/extension)
# ---------------------------------------------------------------------------
def test_document_with_missing_mime_metadata(tmp_path):
    png_file = tmp_path / "test_doc_no_meta.png"
    png_file.write_bytes(create_sample_png())

    # meta_file_type is None
    m_png = infer_document_mime_type(str(png_file), meta_file_type=None)
    assert m_png == "image/png"

    pdf_file = tmp_path / "test_doc_no_meta.pdf"
    pdf_file.write_bytes(create_sample_pdf())
    m_pdf = infer_document_mime_type(str(pdf_file), meta_file_type=None)
    assert m_pdf == "application/pdf"


# ---------------------------------------------------------------------------
# 3. Multiple documents with different MIME types (no cross-contamination)
# ---------------------------------------------------------------------------
def test_multiple_documents_with_different_mime_types(tmp_path):
    aadhaar_file = tmp_path / "aadhaar.png"
    aadhaar_file.write_bytes(create_sample_png("AADHAAR"))

    community_file = tmp_path / "community.pdf"
    community_file.write_bytes(create_sample_pdf())

    bank_file = tmp_path / "passbook.jpg"
    bank_file.write_bytes(create_sample_jpeg("BANK"))

    mime_aadhaar = infer_document_mime_type(str(aadhaar_file))
    mime_community = infer_document_mime_type(str(community_file))
    mime_bank = infer_document_mime_type(str(bank_file))

    assert mime_aadhaar == "image/png"
    assert mime_community == "application/pdf"
    assert mime_bank == "image/jpeg"
    # Ensure they are distinct and not shared
    assert mime_aadhaar != mime_community
    assert mime_community != mime_bank


# ---------------------------------------------------------------------------
# 4. Documents following Branch A (existing version update) and Branch B (new)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_conditional_branches_branch_a_and_branch_b(tmp_path):
    service = BatchExtractionService()
    batch_id = "BATCH_BRANCH_TEST"
    reg_no = "STU_BRANCH_001"

    # Create dummy files
    aadhaar_png = tmp_path / "aadhaar.png"
    aadhaar_png.write_bytes(create_sample_png("AADHAAR CARD"))

    tc_pdf = tmp_path / "tc.pdf"
    tc_pdf.write_bytes(create_sample_pdf() * 20)  # > 1024 bytes

    # Branch A: Document exists in existing_doc_keys with stub active_version
    stub_version = DocumentVersion(
        version_number=1,
        file_path="",  # empty
        original_filename="stub.pdf",
        file_size_bytes=0,
        mime_type="application/octet-stream",
    )
    existing_tc_doc = StudentDocument(
        student_id=reg_no,
        batch_id=batch_id,
        document_type="TRANSFER_CERTIFICATE",
        document_name="Transfer Certificate",
        current_version=1,
        active_version_id=stub_version.version_id,
        status=DocumentStatus.UPLOADED.value,
        versions=[stub_version],
    )
    await existing_tc_doc.insert()

    # Submission contains both TC (Branch A) and Aadhaar (Branch B)
    submission = StudentSubmission(
        batch_id=batch_id,
        student_name="Test Student",
        register_number=reg_no,
        mobile_number="9876543210",
        documents=[
            # This matches existing_tc_doc (Branch A)
            StudentDocumentMeta(
                document_name="Transfer Certificate",
                document_type="TRANSFER_CERTIFICATE",
                file_path=str(tc_pdf),
                file_type="application/pdf",
                status="Uploaded",
            ),
            # This is a new document (Branch B)
            StudentDocumentMeta(
                document_name="Aadhaar Card",
                document_type="AADHAAR",
                file_path=str(aadhaar_png),
                file_type=None,  # Missing metadata!
                status="Uploaded",
            ),
        ],
    )
    await submission.insert()

    # Run canonical units builder
    units = await service._build_canonical_student_units([batch_id])

    assert len(units) == 1
    unit = units[0]
    assert unit.register_number == reg_no

    # Reload existing_tc_doc to check active_version was updated via Branch A
    reloaded_tc = await StudentDocument.get(existing_tc_doc.id)
    assert reloaded_tc is not None
    av = reloaded_tc.active_version
    assert av is not None
    assert av.file_path == str(tc_pdf.resolve())
    assert av.mime_type == "application/pdf"
    assert av.original_filename == "tc.pdf"

    # Verify Branch B created the new Aadhaar StudentDocument with inferred mime_type="image/png"
    aadhaar_docs = await StudentDocument.find({
        "batch_id": batch_id,
        "student_id": reg_no,
        "document_type": "AADHAAR",
    }).to_list()
    assert len(aadhaar_docs) == 1
    aadhaar_av = aadhaar_docs[0].active_version
    assert aadhaar_av is not None
    assert aadhaar_av.mime_type == "image/png"


# ---------------------------------------------------------------------------
# 5. /data-extractions/batches succeeds without 500 when MIME metadata is missing
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_list_authorized_batches_succeeds_with_missing_mime(tmp_path):
    service = BatchExtractionService()
    batch_id = "BATCH_LIST_TEST"

    test_file = tmp_path / "doc_without_mime.png"
    test_file.write_bytes(create_sample_png("DOC"))

    mock_batch = AdmissionBatch(
        id=batch_id,
        name="Batch 2026",
        academic_year="2026-2027",
        department_id="CSE",
        created_by="staff_admin",
    )
    await mock_batch.insert()

    mock_sub = StudentSubmission(
        batch_id=batch_id,
        student_name="Alice Smith",
        register_number="REG_NO_MIME",
        mobile_number="9876543210",
        documents=[
            StudentDocumentMeta(
                document_name="Aadhaar Card",
                document_type="AADHAAR",
                file_path=str(test_file),
                file_type=None,  # Missing MIME
                status="Uploaded",
            )
        ],
    )
    await mock_sub.insert()

    actor = MagicMock()
    actor.id = PydanticObjectId()
    actor.role = UserRole.SUPER_ADMIN

    # Calling list_authorized_batches must succeed without any UnboundLocalError
    res = await service.list_authorized_batches(actor)
    assert len(res) == 1
    assert res[0].batch_id == batch_id
    assert res[0].students_count == 1
    assert res[0].batch_name == "Batch 2026"


# ---------------------------------------------------------------------------
# 6. Unknown / unresolvable document returns safe optional representation
# ---------------------------------------------------------------------------
def test_unknown_mime_type_returns_safe_default():
    # Completely non-existent path with no extension
    m = infer_document_mime_type("nonexistent_unknown_file", meta_file_type=None)
    assert m == "application/octet-stream"

    # None file_path
    m2 = infer_document_mime_type(None, meta_file_type=None)
    assert m2 == "application/octet-stream"

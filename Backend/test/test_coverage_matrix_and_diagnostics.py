"""
ADMIEXTRACT - Full Extraction Coverage Matrix & Diagnostic Test Suite
======================================================================
Tests:
1. Field Coverage Matrix internal diagnostic record generation
2. Source document routing (Aadhaar, TC, Community, Bank Passbook)
3. 431-byte empty placeholder PDF returning DOCUMENT_INVALID
4. OCR low quality (< 100 characters) triggering OCR_LOW_QUALITY
5. Document-evidence-based YES / NO / NOT_FOUND logic (never convert missing to NO)
6. Cross-document fusion by canonical field key (null does not overwrite valid value)
7. Excel key-based mapping: missing field does not shift subsequent columns
"""

import io
import os
import pytest
import pytest_asyncio
import openpyxl
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorClient
from unittest.mock import patch, MagicMock

from app.core.config import settings
from app.models.user import User, UserRole
from app.models.batch import AdmissionBatch
from app.models.student_submission import StudentSubmission, StudentDocumentMeta
from app.models.student_document import StudentDocument, DocumentVersion
from app.models.document_extraction_result import DocumentExtractionResult
from app.services.batch_extraction_service import BatchExtractionService
from app.services.accuracy_extraction_engine import (
    AccuracyExtractionEngine,
    FieldExtractionResult,
    evaluate_evidence_based_yes_no,
)
from app.services.field_source_rules import (
    FIELD_SOURCE_RULES,
    resolve_canonical_document_type,
)
from app.services.ocr_service import OCRService
from PIL import Image


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    import app.db.database as db_mod

    db_mod.client = AsyncIOMotorClient(
        settings.MONGODB_URI, serverSelectionTimeoutMS=2000
    )
    db_mod.db = db_mod.client[settings.DATABASE_NAME]
    await db_mod._run_db_setup()


def test_document_source_routing_priority():
    """Verify explicit source document routing rules and priority."""
    # Aadhaar priority for Aadhaar number, student name, dob, gender
    assert FIELD_SOURCE_RULES["aadhaar_number"]["sources"][0]["document_type"] == "AADHAAR"
    assert FIELD_SOURCE_RULES["dob"]["sources"][0]["document_type"] == "AADHAAR"

    # Community certificate priority for community, caste, father_name
    assert FIELD_SOURCE_RULES["community_category"]["sources"][0]["document_type"] == "COMMUNITY"
    assert FIELD_SOURCE_RULES["father_name"]["sources"][0]["document_type"] == "COMMUNITY"

    # TC priority for emis_id, mother_name
    assert FIELD_SOURCE_RULES["emis_id"]["sources"][0]["document_type"] == "TRANSFER_CERTIFICATE"
    assert FIELD_SOURCE_RULES["mother_name"]["sources"][0]["document_type"] == "TRANSFER_CERTIFICATE"

    # Bank passbook priority for bank fields
    assert FIELD_SOURCE_RULES["ifsc_code"]["sources"][0]["document_type"] == "BANK_PASSBOOK"
    assert FIELD_SOURCE_RULES["account_number"]["sources"][0]["document_type"] == "BANK_PASSBOOK"
    assert FIELD_SOURCE_RULES["bank_name"]["sources"][0]["document_type"] == "BANK_PASSBOOK"


def test_tiny_corrupted_pdf_detection_document_invalid(tmp_path):
    """Confirm tiny/empty placeholder PDF (< 1024 bytes) returns DOCUMENT_INVALID, not FIELD_NOT_FOUND."""
    engine = AccuracyExtractionEngine()

    # Create a 431-byte empty PDF stub
    stub_pdf = tmp_path / "tc_stub.pdf"
    stub_content = (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [] /Count 0 >>\nendobj\n"
        b"xref\n0 3\n0000000000 65535 f \n0000000009 00000 n \n0000000058 00000 n \n"
        b"trailer\n<< /Size 3 /Root 1 0 R >>\nstartxref\n115\n%%EOF\n"
    )
    # Pad to 431 bytes
    stub_content = stub_content + b" " * (431 - len(stub_content))
    stub_pdf.write_bytes(stub_content)

    quality = engine.inspect_document_quality(str(stub_pdf))
    assert quality["is_usable"] is False
    assert quality["is_invalid"] is True
    assert "DOCUMENT_INVALID" in quality["reason"]


def test_ocr_low_quality_detection(tmp_path):
    """Verify that OCR text under 100 characters triggers OCR_LOW_QUALITY status."""
    ocr_service = OCRService()

    # Create a dummy image file
    dummy_img = tmp_path / "short.png"
    Image.new("RGB", (100, 100), color=(255, 255, 255)).save(dummy_img)

    short_text = "Digitally signed by Officer. Date: 12-05-2024"
    assert len(short_text) < 100

    # Mock engine return with short text
    mock_engine = MagicMock(return_value=([[None, short_text, 0.95]], None))
    with patch("app.services.ocr_service.get_rapidocr_engine", return_value=mock_engine):
        res = ocr_service.extract_text(str(dummy_img), prefer_local=True)
        assert res["status"] == "OCR_LOW_QUALITY"
        assert res["success"] is False


def test_yes_no_evidence_logic():
    """Verify strict YES / NO / NOT_FOUND evidence logic (never convert missing to NO)."""
    # 1. EMIS ID Available
    ans_emis_present = evaluate_evidence_based_yes_no(
        field_key="is_emis_id_available",
        raw_val=None,
        document_text="EMIS ID: 2015743426\nStudent Name: Shadhanan",
        document_type="TRANSFER_CERTIFICATE",
    )
    assert ans_emis_present["value"] == "YES"

    ans_emis_missing = evaluate_evidence_based_yes_no(
        field_key="is_emis_id_available",
        raw_val=None,
        document_text="Student Name: Shadhanan\nAdmission No: 1234",
        document_type="TRANSFER_CERTIFICATE",
    )
    assert ans_emis_missing["value"] == "NOT_FOUND"

    # 2. First Graduate
    ans_fg_yes = evaluate_evidence_based_yes_no(
        field_key="is_first_graduate",
        raw_val=None,
        document_text="First Graduate: Yes, eligible for fee concession",
        document_type="TRANSFER_CERTIFICATE",
    )
    assert ans_fg_yes["value"] == "YES"

    ans_fg_no = evaluate_evidence_based_yes_no(
        field_key="is_first_graduate",
        raw_val=None,
        document_text="First Graduate: No",
        document_type="TRANSFER_CERTIFICATE",
    )
    assert ans_fg_no["value"] == "NO"

    ans_fg_none = evaluate_evidence_based_yes_no(
        field_key="is_first_graduate",
        raw_val=None,
        document_text="Marks: Maths 90, Physics 85",
        document_type="HSC",
    )
    assert ans_fg_none["value"] == "NOT_FOUND"


def test_cross_document_fusion_null_does_not_overwrite():
    """Verify cross-document fusion merges by canonical key and does not overwrite valid data with null."""
    engine = AccuracyExtractionEngine()

    aadhaar_extractions = {
        "student_name": FieldExtractionResult(
            field_name="student_name",
            raw_value="Shadhanan S",
            normalized_value="Shadhanan S",
            confidence="HIGH",
            field_state="HIGH_CONFIDENCE",
            source_document_type="AADHAAR",
        ),
        "mother_name": FieldExtractionResult(
            field_name="mother_name",
            raw_value=None,
            normalized_value="NOT_AVAILABLE",
            confidence="LOW",
            field_state="NOT_FOUND",
            source_document_type="AADHAAR",
        ),
    }

    tc_extractions = {
        "mother_name": FieldExtractionResult(
            field_name="mother_name",
            raw_value="PRIYA G",
            normalized_value="PRIYA G",
            confidence="HIGH",
            field_state="HIGH_CONFIDENCE",
            source_document_type="TRANSFER_CERTIFICATE",
        ),
        "student_name": FieldExtractionResult(
            field_name="student_name",
            raw_value="SHADHANAN S",
            normalized_value="SHADHANAN S",
            confidence="HIGH",
            field_state="HIGH_CONFIDENCE",
            source_document_type="TRANSFER_CERTIFICATE",
        ),
    }

    fused = engine.detect_cross_document_conflicts(
        extractions_by_doc_type={
            "AADHAAR": aadhaar_extractions,
            "TRANSFER_CERTIFICATE": tc_extractions,
        }
    )

    # Mother name must come from TC (not erased by Aadhaar's null)
    assert fused["mother_name"].normalized_value == "PRIYA G"
    assert fused["mother_name"].source_document_type == "TRANSFER_CERTIFICATE"
    assert fused["mother_name"].field_state == "HIGH_CONFIDENCE"

    # Student name is preserved
    assert fused["student_name"].normalized_value in ("Shadhanan S", "SHADHANAN S")


@pytest.mark.asyncio
async def test_excel_export_column_mapping_no_shift(tmp_path):
    """
    Verify Excel export writes strictly to canonical columns.
    A missing IFSC code must produce a blank / NOT_FOUND cell and NOT shift Bank Name into IFSC.
    """
    service = BatchExtractionService()
    batch_id = "test_excel_noshift_batch"
    reg_no = "24REG777"
    actor = User(name="Admin", password="pw", username="admin_excel", role=UserRole.SUPER_ADMIN, email="excel@test.com")

    batch = AdmissionBatch(
        id=batch_id,
        name="Excel No Shift Batch",
        academic_year="2026-2027",
        department_id="CSE",
        created_by="admin_excel",
    )
    await batch.save()

    img_path = tmp_path / "bank.png"
    Image.new("RGB", (200, 200), color=(255, 255, 255)).save(img_path)

    doc = StudentDocument(
        student_id=reg_no,
        batch_id=batch_id,
        document_type="BANK_PASSBOOK",
        document_name="Bank Passbook",
        versions=[
            DocumentVersion(
                version_number=1,
                file_path=str(img_path),
                original_filename="bank.png",
                file_size_bytes=len(img_path.read_bytes()),
            )
        ],
    )
    await doc.save()

    sub = StudentSubmission(
        batch_id=batch_id,
        register_number=reg_no,
        student_name="Test Student",
        mobile_number="9876543210",
        submission_status="Submitted",
        documents=[
            StudentDocumentMeta(document_name="Bank Passbook", document_type="BANK_PASSBOOK", file_path=str(img_path), status="Uploaded"),
        ],
    )
    await sub.save()

    # Passbook has bank_name and account_number, but IFSC is missing
    def mock_gemini(*args, **kwargs):
        return {
            "success": True,
            "fields": {
                "bank_name": {"value": "The Karur Vysya Bank Limited", "confidence": 98},
                "account_number": {"value": "1718155000062336", "confidence": 98},
                "ifsc_code": {"value": None, "confidence": 0},
            },
            "extracted_summary": {
                "bank_name": "The Karur Vysya Bank Limited",
                "account_number": "1718155000062336",
                "ifsc_code": None,
            },
            "confidence": 95.0,
        }

    requested_fields = ["ifsc_code", "bank_name", "account_number"]
    requested_columns = ["IFSC Code", "Bank Name", "Account Number"]

    with patch("app.services.gemini_service.GeminiService.extract_from_file", side_effect=mock_gemini):
        summary = await service.create_and_run_batch_extraction(
            batch_id=batch_id,
            requested_columns=requested_columns,
            requested_fields=requested_fields,
            actor=actor,
        )

    # Export Excel and inspect column contents
    excel_stream, fname = await service.export_verified_excel(summary.extraction_request_id, actor)
    wb = openpyxl.load_workbook(excel_stream)
    ws = wb.active

    headers = [cell.value for cell in ws[1]]
    data_row = [cell.value for cell in ws[2]]

    header_to_val = dict(zip(headers, data_row))

    # IFSC Code must be empty / NOT_FOUND / NOT_AVAILABLE
    assert header_to_val.get("IFSC Code") in ("", None, "NOT_AVAILABLE", "NOT_FOUND")

    # Bank Name must NOT shift into IFSC
    assert header_to_val.get("Bank Name") == "The Karur Vysya Bank Limited"

    # Account Number must be correct
    assert str(header_to_val.get("Account Number")) == "1718155000062336"

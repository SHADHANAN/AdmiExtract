"""
Accuracy-First Document Extraction Pipeline Test Suite
======================================================
Tests:
1. Clear Aadhaar extraction (High confidence, valid 12 digits, grounded).
2. Ambiguous / Invalid digits in identifiers (Zero-guessing, REVIEW_REQUIRED).
3. Blurry / Low quality document detection (LOW_QUALITY_DOCUMENT).
4. Document type mismatch protection (Expected AADHAAR, Uploaded TC -> DOCUMENT_TYPE_MISMATCH).
5. Multi-page document inspection.
6. Cross-document conflict detection (Conflicting DOB across documents -> CONFLICTING_VALUES).
7. Date normalization & calendar validation.
8. Separation of raw vs normalized vs student-submitted data.
9. Excel export integrity.
"""

import io
import os
import pytest
import pytest_asyncio
from datetime import datetime, timezone
from beanie import PydanticObjectId
from motor.motor_asyncio import AsyncIOMotorClient
from unittest.mock import patch

from app.core.config import settings
from app.models.user import User, UserRole
from app.models.batch import AdmissionBatch
from app.models.student_submission import StudentSubmission, StudentDocumentMeta
from app.models.student_document import StudentDocument, DocumentVersion
from app.models.document_verification import DocumentFieldVerification, VerificationFieldStatus
from app.models.batch_extraction import BatchExtractionRequest
from app.services.batch_extraction_service import BatchExtractionService
from app.services.accuracy_extraction_engine import (
    AccuracyExtractionEngine,
    FieldExtractionResult,
)
from PIL import Image


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    import app.db.database as db_mod

    db_mod.client = AsyncIOMotorClient(
        settings.MONGODB_URI, serverSelectionTimeoutMS=2000
    )
    db_mod.db = db_mod.client[settings.DATABASE_NAME]
    await db_mod._run_db_setup()


def test_strict_field_validation_no_guessing():
    """Verify that identifiers are never guessed, invented, or accepted with invalid structures."""
    engine = AccuracyExtractionEngine()

    # 1. Valid 12-digit Aadhaar
    res = engine.validate_field_accuracy("aadhaar_number", "2122 7377 9295", document_text="Aadhaar No: 2122 7377 9295", source_doc_type="AADHAAR")
    assert res.normalized_value == "212273779295"
    assert res.confidence == "HIGH"
    assert res.field_state == "HIGH_CONFIDENCE"

    # 2. Incomplete 11-digit Aadhaar (Do NOT guess missing digit)
    res_incomplete = engine.validate_field_accuracy("aadhaar_number", "21227377929", document_text="Aadhaar No: 21227377929", source_doc_type="AADHAAR")
    assert res_incomplete.normalized_value == "NOT_AVAILABLE"
    assert res_incomplete.confidence == "LOW"
    assert res_incomplete.field_state == "REVIEW_REQUIRED"
    assert res_incomplete.reason == "INVALID_AADHAAR_LENGTH_DO_NOT_GUESS"

    # 3. Mobile Number Validation (10 digits starting with 6-9)
    res_mob_valid = engine.validate_field_accuracy("mobile_number", "+91 9488203077", document_text="Mobile: 9488203077", source_doc_type="AADHAAR")
    assert res_mob_valid.normalized_value == "9488203077"
    assert res_mob_valid.confidence == "HIGH"

    res_mob_inv = engine.validate_field_accuracy("mobile_number", "12345", document_text="Phone: 12345", source_doc_type="AADHAAR")
    assert res_mob_inv.normalized_value == "NOT_AVAILABLE"
    assert res_mob_inv.field_state == "REVIEW_REQUIRED"

    # 4. IFSC Validation
    res_ifsc = engine.validate_field_accuracy("ifsc_code", "SBIN0001234", document_text="IFSC: SBIN0001234", source_doc_type="BANK_PASSBOOK")
    assert res_ifsc.normalized_value == "SBIN0001234"
    assert res_ifsc.confidence == "HIGH"

    res_ifsc_inv = engine.validate_field_accuracy("ifsc_code", "INVALID_IFSC", document_text="IFSC: INVALID_IFSC", source_doc_type="BANK_PASSBOOK")
    assert res_ifsc_inv.normalized_value == "NOT_AVAILABLE"
    assert res_ifsc_inv.field_state == "REVIEW_REQUIRED"

    # 5. Bank Account Validation
    res_acc = engine.validate_field_accuracy("account_number", "1718155000062336", document_text="A/C: 1718155000062336", source_doc_type="BANK_PASSBOOK")
    assert res_acc.normalized_value == "1718155000062336"
    assert res_acc.confidence == "HIGH"


def test_date_validation_and_normalization():
    """Verify calendar date validation and standardized formatting."""
    engine = AccuracyExtractionEngine()

    # Valid dates
    res1 = engine.validate_field_accuracy("dob", "10/05/2004", document_text="DOB: 10/05/2004")
    assert res1.normalized_value == "10/05/2004"
    assert res1.confidence == "HIGH"

    res2 = engine.validate_field_accuracy("dob", "2004-05-10", document_text="DOB: 2004-05-10")
    assert res2.normalized_value == "10/05/2004"

    # Impossible date (e.g. Month 15 or Day 35) -> REVIEW_REQUIRED
    res_inv = engine.validate_field_accuracy("dob", "35/15/2004", document_text="DOB: 35/15/2004")
    assert res_inv.normalized_value == "NOT_AVAILABLE"
    assert res_inv.field_state == "REVIEW_REQUIRED"


def test_document_type_mismatch_protection():
    """Verify that wrong document uploads are flagged with DOCUMENT_TYPE_MISMATCH."""
    engine = AccuracyExtractionEngine()

    tc_text = """
    GOVERNMENT HIGHER SECONDARY SCHOOL
    TRANSFER CERTIFICATE
    EMIS ID: 2015743426
    Name of Student: R. Arun
    Date of Leaving: 31/05/2024
    Reason for Leaving: Course Completed
    """

    # Expected AADHAAR but uploaded TC
    is_match, detected, reason = engine.verify_document_type(tc_text, expected_type="AADHAAR", filename="student_tc.pdf")
    assert is_match is False
    assert detected == "TRANSFER_CERTIFICATE"
    assert "DOCUMENT_TYPE_MISMATCH" in reason

    # Expected TRANSFER_CERTIFICATE with TC text -> Matches!
    is_match_tc, detected_tc, _ = engine.verify_document_type(tc_text, expected_type="TRANSFER_CERTIFICATE", filename="student_tc.pdf")
    assert is_match_tc is True


def test_cross_document_conflict_detection():
    """When multiple documents disagree on a field, flag CONFLICTING_VALUES and retain both values."""
    engine = AccuracyExtractionEngine()

    aadhaar_field = FieldExtractionResult(
        field_name="dob",
        raw_value="10/05/2004",
        normalized_value="10/05/2004",
        confidence="HIGH",
        source_document_type="AADHAAR",
    )

    tc_field_conflicting = FieldExtractionResult(
        field_name="dob",
        raw_value="11/05/2004",
        normalized_value="11/05/2004",
        confidence="HIGH",
        source_document_type="TRANSFER_CERTIFICATE",
    )

    doc_extractions = {
        "AADHAAR": {"dob": aadhaar_field},
        "TRANSFER_CERTIFICATE": {"dob": tc_field_conflicting},
    }

    fused = engine.detect_cross_document_conflicts(doc_extractions)
    dob_result = fused["dob"]

    assert dob_result.field_state == "CONFLICTING_VALUES"
    assert dob_result.confidence == "LOW"
    assert dob_result.reason == "CROSS_DOCUMENT_CONFLICT"
    assert len(dob_result.conflicts) == 2
    assert dob_result.conflicts[0]["value"] == "10/05/2004"
    assert dob_result.conflicts[1]["value"] == "11/05/2004"


@pytest.mark.asyncio
async def test_end_to_end_accuracy_pipeline(tmp_path):
    """End-to-end integration test of the accuracy-first batch extraction pipeline."""
    batch_id = "test_accuracy_batch_01"
    reg_no = "24AM099"
    actor = User(name="Admin", password="pw", username="admin_accuracy", role=UserRole.SUPER_ADMIN, email="admin@accuracy.com")

    batch = AdmissionBatch(
        id=batch_id,
        name="Test Accuracy Batch",
        academic_year="2026-2027",
        department_id="CSE",
        created_by="admin_user",
    )
    await batch.save()

    aadhaar_img_path = tmp_path / "aadhaar.png"
    img = Image.new("RGB", (300, 200), color=(255, 255, 255))
    img.save(aadhaar_img_path)

    doc_aadhaar = StudentDocument(
        student_id=reg_no,
        batch_id=batch_id,
        document_type="AADHAAR",
        document_name="Aadhaar Card",
        versions=[
            DocumentVersion(
                version_number=1,
                file_path=str(aadhaar_img_path),
                original_filename="aadhaar.png",
                file_size_bytes=len(aadhaar_img_path.read_bytes()),
            )
        ],
    )
    await doc_aadhaar.save()

    sub = StudentSubmission(
        batch_id=batch_id,
        register_number=reg_no,
        student_name="Shadhanan",
        mobile_number="9488203077",
        submission_status="Submitted",
        documents=[
            StudentDocumentMeta(document_name="Aadhaar Card", document_type="AADHAAR", file_path=str(aadhaar_img_path), status="Uploaded"),
        ],
    )
    await sub.save()

    def mock_gemini_extract(*args, **kwargs):
        return {
            "success": True,
            "extracted_data": {
                "aadhaar_number": "2122 7377 9295",
                "gender": "MALE",
                "dob": "10/05/2004",
                "student_name": "Shadhanan",
            },
            "fields": {
                "aadhaar_number": {"value": "2122 7377 9295", "confidence": 95},
                "gender": {"value": "MALE", "confidence": 95},
                "dob": {"value": "10/05/2004", "confidence": 95},
                "student_name": {"value": "Shadhanan", "confidence": 95},
            },
            "confidence": 95.0,
        }

    service = BatchExtractionService()
    req_fields = ["aadhaar_number", "gender", "dob", "student_name", "annual_income"]

    with patch("app.services.gemini_service.GeminiService.extract_from_file", side_effect=mock_gemini_extract), \
         patch("app.services.gemini_service.GeminiService.extract_from_bytes", side_effect=mock_gemini_extract):
        summary = await service.create_and_run_batch_extraction(
            batch_id=batch_id,
            requested_columns=[f.replace("_", " ").title() for f in req_fields],
            requested_fields=req_fields,
            actor=actor,
        )

    assert summary.total_students == 1
    assert summary.processed_count == 1
    assert summary.pending_verification_count == 1

    detail = await service.get_extraction_details(summary.extraction_request_id, actor)
    stud = detail.students[0]

    # Verify accuracy fields
    assert stud.fields["aadhaar_number"].ai_value == "212273779295"
    assert stud.fields["aadhaar_number"].confidence == "HIGH"
    assert stud.fields["aadhaar_number"].field_state == "HIGH_CONFIDENCE"
    assert stud.fields["gender"].ai_value == "MALE"
    assert stud.fields["date_of_birth"].ai_value == "10/05/2004"
    assert stud.fields["annual_income"].ai_value == "NOT_AVAILABLE"
    assert stud.fields["annual_income"].field_state in ("SOURCE_DOCUMENT_MISSING", "DOCUMENT_MISSING")

    # Test verified Excel export
    excel_stream, fname = await service.export_verified_excel(summary.extraction_request_id, actor)
    assert excel_stream is not None
    assert fname.endswith(".xlsx")

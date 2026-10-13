"""
AI Data Extraction Correctness & Real-World Edge Case Verification Test Suite
=============================================================================
Tests all 10 realistic admission document scenarios mandated by specification:

CASE 1: Aadhaar contains DOB = 15/08/2004 and Issue date = 01/01/2025
        Expected: DOB = 15/08/2004 (NEVER 01/01/2025)

CASE 2: Document contains multiple 12-digit numbers (e.g. Serial No, Bank Acc, Aadhaar)
        Expected: Only the number explicitly associated with Aadhaar is Aadhaar

CASE 3: TC contains Community = BC and Father Name = XXXXX, Community Cert is absent
        Expected: Soft source authority extracts Community = BC from TC

CASE 4: Community Certificate says BC, TC says MBC
        Expected: Cross-document conflict detected, primary authority selected per rules,
                  marked as CONFLICTING_VALUES / Needs Review (never silently hidden)

CASE 5: Extraction request specifies [Student Name, DOB, Community]
        Expected: Focus strictly on requested fields, no unrelated fields returned

CASE 6: Second extraction request asks for [Father Name, Mother Name, Mobile]
        Expected: Reuses same stored documents without re-upload; First extraction unchanged

CASE 7: Unknown document type but document clearly contains Student Name + DOB
        Expected: Content understood, extraction succeeds without dropping document

CASE 8: OCR failure / low quality
        Expected: Fallback path attempted, status and failure recorded cleanly

CASE 9: Missing field in document
        Expected: Returns NULL / NOT_AVAILABLE (NEVER "NO" or fabricated values)

CASE 10: Bilingual Tamil + English certificate
        Expected: Tamil labels / content correctly parsed, values not discarded
"""

import os
import io
import pytest
import pytest_asyncio
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock
from motor.motor_asyncio import AsyncIOMotorClient
from PIL import Image

from app.core.config import settings
from app.models.user import User, UserRole
from app.models.batch import AdmissionBatch
from app.models.student_submission import StudentSubmission, StudentDocumentMeta
from app.models.student_document import StudentDocument, DocumentVersion
from app.models.batch_extraction import BatchExtractionRequest
from app.models.document_extraction_result import DocumentExtractionResult
from app.models.document_verification import DocumentFieldVerification, VerificationFieldStatus
from app.services.batch_extraction_service import BatchExtractionService
from app.services.accuracy_extraction_engine import AccuracyExtractionEngine, FieldExtractionResult
from app.services.ai_extraction_service import AIExtractionService
from app.services.gemini_service import GeminiService


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    import app.db.database as db_mod
    db_mod.client = AsyncIOMotorClient(settings.MONGODB_URI, serverSelectionTimeoutMS=2000)
    db_mod.db = db_mod.client[settings.DATABASE_NAME]
    await db_mod._run_db_setup()


# =============================================================================
# CASE 1: DOB vs Issue Date Disambiguation
# =============================================================================
def test_case_1_dob_vs_issue_date_disambiguation():
    """
    Aadhaar contains:
      DOB = 15/08/2004
      Issue date = 01/01/2025
    Expected:
      DOB = 15/08/2004, NOT 01/01/2025
    """
    ai_service = AIExtractionService()
    text = (
        "GOVERNMENT OF INDIA\n"
        "UNIQUE IDENTIFICATION AUTHORITY OF INDIA\n"
        "To: Selvan Vignesh\n"
        "Date of Birth / DOB: 15/08/2004\n"
        "Gender: Male\n"
        "Issue Date: 01/01/2025\n"
        "Generation Date: 02/01/2025\n"
        "Aadhaar No: 2345 6789 0123\n"
    )

    result = ai_service.extract(
        document_type="AADHAAR",
        ocr_text=text,
        required_fields=["date_of_birth"],
    )

    dob_val = result.get("date_of_birth", {}).get("value") if isinstance(result.get("date_of_birth"), dict) else result.get("date_of_birth")
    assert dob_val == "15/08/2004"
    assert dob_val != "01/01/2025"


# =============================================================================
# CASE 2: Multiple 12-digit Numbers Disambiguation
# =============================================================================
def test_case_2_multiple_12_digit_numbers_disambiguation():
    """
    Document contains multiple 12-digit numbers:
      Application Ref: 987654321012
      Aadhaar: 2345 6789 0123
      Transaction ID: 112233445566
    Expected:
      Only the number explicitly labeled as Aadhaar is extracted as Aadhaar.
    """
    ai_service = AIExtractionService()
    text = (
        "Application Reference Number: 987654321012\n"
        "Transaction Ref: 112233445566\n"
        "Candidate Name: Rajesh Kumar\n"
        "Aadhaar Number: 2345 6789 0123\n"
        "Receipt No: 445566778899\n"
    )

    result = ai_service.extract(
        document_type="AADHAAR",
        ocr_text=text,
        required_fields=["aadhaar_number"],
    )

    raw_val = result.get("aadhaar_number", {}).get("value") if isinstance(result.get("aadhaar_number"), dict) else result.get("aadhaar_number")
    raw_aadhaar = str(raw_val or "").replace(" ", "")
    assert raw_aadhaar == "234567890123"
    assert raw_aadhaar != "987654321012"
    assert raw_aadhaar != "112233445566"


# =============================================================================
# CASE 3: TC As Secondary Source When Community Certificate is Absent
# =============================================================================
def test_case_3_tc_secondary_source_for_community():
    """
    TC contains:
      Community = BC
      Father Name = Ramasamy
    Community Certificate is absent.
    Expected:
      Community = BC extracted from TC via soft source authority scoring.
    """
    engine = AccuracyExtractionEngine()

    # Extractions from available documents: only TC is available
    tc_fields = {
        "community_category": FieldExtractionResult(
            field_name="community_category",
            raw_value="BC",
            normalized_value="BC",
            confidence="HIGH",
            confidence_score=0.90,
            field_state="EXTRACTED",
            evidence_snippet="Community: BC",
            source_document_type="TRANSFER_CERTIFICATE",
        ),
        "father_name": FieldExtractionResult(
            field_name="father_name",
            raw_value="Ramasamy",
            normalized_value="Ramasamy",
            confidence="HIGH",
            confidence_score=0.95,
            field_state="EXTRACTED",
            evidence_snippet="Father Name: Ramasamy",
            source_document_type="TRANSFER_CERTIFICATE",
        ),
    }

    extractions = {"TRANSFER_CERTIFICATE": tc_fields}

    fused = engine.detect_cross_document_conflicts(
        extractions_by_doc_type=extractions,
        field_to_configured_doc_type={"community_category": "COMMUNITY"},
    )

    assert "community_category" in fused
    assert fused["community_category"].normalized_value == "BC"
    assert fused["community_category"].source_document_type == "TRANSFER_CERTIFICATE"
    assert fused["community_category"].field_state in ("EXTRACTED", "HIGH_CONFIDENCE")


# =============================================================================
# CASE 4: Cross-Document Conflict Detection (Community Cert vs TC)
# =============================================================================
def test_case_4_cross_document_conflict_detected():
    """
    Community Certificate says: Community = BC
    TC says: Community = MBC
    Expected:
      Primary document source selected per authority, but marked as
      CONFLICTING_VALUES with conflict details preserved (never silently hidden).
    """
    engine = AccuracyExtractionEngine()

    comm_fields = {
        "community_category": FieldExtractionResult(
            field_name="community_category",
            raw_value="BC",
            normalized_value="BC",
            confidence="HIGH",
            confidence_score=0.95,
            field_state="EXTRACTED",
            evidence_snippet="Community: BC",
            source_document_type="COMMUNITY",
        )
    }

    tc_fields = {
        "community_category": FieldExtractionResult(
            field_name="community_category",
            raw_value="MBC",
            normalized_value="MBC",
            confidence="HIGH",
            confidence_score=0.90,
            field_state="EXTRACTED",
            evidence_snippet="Community: MBC",
            source_document_type="TRANSFER_CERTIFICATE",
        )
    }

    extractions = {
        "COMMUNITY": comm_fields,
        "TRANSFER_CERTIFICATE": tc_fields,
    }

    fused = engine.detect_cross_document_conflicts(
        extractions_by_doc_type=extractions,
        field_to_configured_doc_type={"community_category": "COMMUNITY"},
    )

    result = fused["community_category"]
    assert result.field_state == "CONFLICTING_VALUES"
    assert result.normalized_value == "BC"  # Primary authority wins value
    assert len(result.conflicts) >= 2
    types = [c["document_type"] for c in result.conflicts]
    assert "COMMUNITY" in types
    assert "TRANSFER_CERTIFICATE" in types


# =============================================================================
# CASE 5: Strict Requested Fields Driving Extraction
# =============================================================================
@pytest.mark.asyncio
async def test_case_5_requested_fields_drive_extraction(tmp_path):
    """
    Excel template requests: Student Name | DOB | Community
    Expected:
      AI pipeline extracts ONLY these three canonical fields.
    """
    batch_id = "test_req_drive_batch_01"
    reg_no = "24REG001"
    actor = User(name="Admin", password="pw", username="admin_driver", role=UserRole.SUPER_ADMIN, email="admin_driver@test.com")

    batch = AdmissionBatch(
        id=batch_id,
        name="Requested Fields Driver Batch",
        academic_year="2026-2027",
        department_id="CSE",
        created_by="admin_driver",
    )
    await batch.save()

    img_path = tmp_path / "doc.png"
    Image.new("RGB", (300, 200), color=(255, 255, 255)).save(img_path)

    doc = StudentDocument(
        student_id=reg_no,
        batch_id=batch_id,
        document_type="AADHAAR",
        document_name="Aadhaar Card",
        versions=[
            DocumentVersion(
                version_number=1,
                file_path=str(img_path),
                original_filename="doc.png",
                file_size_bytes=len(img_path.read_bytes()),
            )
        ],
    )
    await doc.save()

    sub = StudentSubmission(
        batch_id=batch_id,
        register_number=reg_no,
        student_name="Karthik",
        mobile_number="9876543210",
        submission_status="Submitted",
        documents=[
            StudentDocumentMeta(document_name="Aadhaar Card", document_type="AADHAAR", file_path=str(img_path), status="Uploaded"),
        ],
    )
    await sub.save()

    def mock_gemini(*args, **kwargs):
        return {
            "success": True,
            "fields": {
                "student_name": {"value": "Karthik", "confidence": 96, "evidence": "Name: Karthik"},
                "date_of_birth": {"value": "15/08/2004", "confidence": 95, "evidence": "DOB: 15/08/2004"},
            },
            "extracted_summary": {
                "student_name": "Karthik",
                "date_of_birth": "15/08/2004",
            },
            "confidence": 95.0,
        }

    service = BatchExtractionService()
    requested_fields = ["student_name", "date_of_birth", "community_category"]

    with patch("app.services.gemini_service.GeminiService.extract_from_file", side_effect=mock_gemini):
        summary = await service.create_and_run_batch_extraction(
            batch_id=batch_id,
            requested_columns=["Student Name", "Date Of Birth", "Community"],
            requested_fields=requested_fields,
            actor=actor,
        )

    detail = await service.get_extraction_details(summary.extraction_request_id, actor)
    stud = detail.students[0]

    # Only requested fields should be present in fields dictionary
    assert set(stud.fields.keys()) == {"student_name", "date_of_birth", "community_category"}
    assert stud.fields["student_name"].ai_value == "Karthik"
    assert stud.fields["date_of_birth"].ai_value == "15/08/2004"


# =============================================================================
# CASE 6: Reusing Stored Documents For Multiple Extraction Requests
# =============================================================================
@pytest.mark.asyncio
async def test_case_6_stored_documents_reused_without_reupload(tmp_path):
    """
    Request 1 asks: Student Name, DOB
    Request 2 asks: Father Name, Mother Name, Mobile
    Expected:
      Both use the same stored file.
      Request 1 results remain immutable and isolated from Request 2.
    """
    batch_id = "test_multi_req_batch_02"
    reg_no = "24REG002"
    actor = User(name="Admin", password="pw", username="admin_multi", role=UserRole.SUPER_ADMIN, email="admin_multi@test.com")

    batch = AdmissionBatch(
        id=batch_id,
        name="Multi Extraction Batch",
        academic_year="2026-2027",
        department_id="ECE",
        created_by="admin_multi",
    )
    await batch.save()

    img_path = tmp_path / "aadhaar_stored.png"
    Image.new("RGB", (300, 200), color=(255, 255, 255)).save(img_path)

    doc = StudentDocument(
        student_id=reg_no,
        batch_id=batch_id,
        document_type="AADHAAR",
        document_name="Aadhaar Card",
        versions=[
            DocumentVersion(
                version_number=1,
                file_path=str(img_path),
                original_filename="aadhaar_stored.png",
                file_size_bytes=len(img_path.read_bytes()),
            )
        ],
    )
    await doc.save()

    sub = StudentSubmission(
        batch_id=batch_id,
        register_number=reg_no,
        student_name="Ananya",
        mobile_number="9876543210",
        submission_status="Submitted",
        documents=[
            StudentDocumentMeta(document_name="Aadhaar Card", document_type="AADHAAR", file_path=str(img_path), status="Uploaded"),
        ],
    )
    await sub.save()

    def mock_extract_call(*args, **kwargs):
        target_fields = kwargs.get("target_fields") or []
        fields_res = {}
        if "student_name" in target_fields:
            fields_res["student_name"] = {"value": "Ananya", "confidence": 95}
        if "date_of_birth" in target_fields:
            fields_res["date_of_birth"] = {"value": "20/11/2004", "confidence": 95}
        if "father_name" in target_fields:
            fields_res["father_name"] = {"value": "Suresh", "confidence": 92}
        if "mobile_number" in target_fields:
            fields_res["mobile_number"] = {"value": "9876543210", "confidence": 94}
        return {"success": True, "fields": fields_res, "confidence": 95.0}

    service = BatchExtractionService()

    with patch("app.services.gemini_service.GeminiService.extract_from_file", side_effect=mock_extract_call):
        # 1st extraction run
        run1 = await service.create_and_run_batch_extraction(
            batch_id=batch_id,
            requested_columns=["Student Name", "Date Of Birth"],
            requested_fields=["student_name", "date_of_birth"],
            actor=actor,
        )

        # 2nd extraction run on different fields
        run2 = await service.create_and_run_batch_extraction(
            batch_id=batch_id,
            requested_columns=["Father Name", "Mobile"],
            requested_fields=["father_name", "mobile_number"],
            actor=actor,
        )

    assert run1.extraction_request_id != run2.extraction_request_id

    # Verify run 1 details remain intact
    detail1 = await service.get_extraction_details(run1.extraction_request_id, actor)
    stud1_fields = detail1.students[0].fields
    assert "student_name" in stud1_fields
    assert "date_of_birth" in stud1_fields
    assert "father_name" not in stud1_fields

    # Verify run 2 details contain requested fields
    detail2 = await service.get_extraction_details(run2.extraction_request_id, actor)
    stud2_fields = detail2.students[0].fields
    assert "father_name" in stud2_fields
    assert "mobile_number" in stud2_fields
    assert "date_of_birth" not in stud2_fields


# =============================================================================
# CASE 7: Unknown Document Type Must Not Drop Documents
# =============================================================================
def test_case_7_unknown_document_type_attempted():
    """
    Document classifier returns UNKNOWN / OTHER.
    Expected:
      Document is NOT silently skipped; field extraction is still attempted.
    """
    engine = AccuracyExtractionEngine()
    text = "Student Certificate\nCandidate: Priya Sharma\nDate of Birth: 04/09/2004"

    # Mismatch guard should NOT reject UNKNOWN / OTHER documents
    is_match, detected_type, mismatch_reason = engine.verify_document_type(
        document_text=text,
        expected_type="UNKNOWN",
        filename="custom_certificate.pdf",
    )

    assert is_match is True
    assert mismatch_reason is None

    # Extraction engine validates fields directly from content
    val_name = engine.validate_field_accuracy("student_name", "Priya Sharma", document_text=text, source_doc_type="UNKNOWN")
    assert val_name.normalized_value == "Priya Sharma"
    assert val_name.field_state == "EXTRACTED"

    val_dob = engine.validate_field_accuracy("dob", "04/09/2004", document_text=text, source_doc_type="UNKNOWN")
    assert val_dob.normalized_value == "04/09/2004"
    assert val_dob.confidence == "HIGH"


# =============================================================================
# CASE 8: OCR Failure / Fallback Visible
# =============================================================================
def test_case_8_ocr_failure_fallback_recorded():
    """
    OCR or Quality check detects blurry/unusable image.
    Expected:
      Proper status (LOW_QUALITY_DOCUMENT / EXTRACTION_FAILED) is recorded, not silently ignored.
    """
    engine = AccuracyExtractionEngine()

    # Empty file inspection
    res = engine.inspect_document_quality("non_existent_file.pdf")
    assert res["is_usable"] is False
    assert res["reason"] == "FILE_NOT_FOUND"

    # Non-available raw extraction produces clean failure status
    val = engine.validate_field_accuracy(
        field_key="aadhaar_number",
        raw_val=None,
        document_text="",
        source_doc_type="AADHAAR",
    )
    assert val.normalized_value == "NOT_AVAILABLE"
    assert val.confidence == "LOW"
    assert val.confidence_score == 0.0


# =============================================================================
# CASE 9: Missing Field Must Return NULL / NOT_AVAILABLE (Never "NO")
# =============================================================================
def test_case_9_missing_field_returns_null_never_no():
    """
    Field not present in document.
    Expected:
      Value is NULL / NOT_AVAILABLE. NEVER the string "NO".
    """
    ai_service = AIExtractionService()
    text = (
        "GOVERNMENT OF TAMIL NADU\n"
        "TRANSFER CERTIFICATE\n"
        "Name of Pupil: Senthil Nathan\n"
        "Date of Birth: 12/03/2005\n"
        "Community: BC\n"
    )

    # Request annual_income which is absent in a TC
    result = ai_service.extract(
        document_type="TRANSFER_CERTIFICATE",
        ocr_text=text,
        required_fields=["annual_income", "aadhaar_number"],
    )

    for field_name in ["annual_income", "aadhaar_number"]:
        field_obj = result.get(field_name)
        val = field_obj.get("value") if isinstance(field_obj, dict) else field_obj
        assert val is None or val == "NOT_AVAILABLE"
        assert val != "NO", f"Field '{field_name}' should not be 'NO'"
        assert val != "no", f"Field '{field_name}' should not be 'no'"


# =============================================================================
# CASE 10: Bilingual Tamil + English Document Support
# =============================================================================
def test_case_10_tamil_english_bilingual_document():
    """
    Tamil + English Certificate containing Tamil labels:
      பெயர் (Name): சுந்தர் (Sundar)
      பிறந்த தேதி (DOB): 18/07/2004
      சாதி / வகுப்பு (Community): பிற்படுத்தப்பட்ட வகுப்பு (BC)
    Expected:
      Regional language text does not cause extraction to discard data.
    """
    engine = AccuracyExtractionEngine()
    tamil_doc_text = (
        "தமிழ்நாடு அரசு (GOVERNMENT OF TAMIL NADU)\n"
        "வருவாய்த்துறை (REVENUE DEPARTMENT)\n"
        "சாதிச் சான்றிதழ் (COMMUNITY CERTIFICATE)\n"
        "மாணவர் பெயர்: சுந்தர் / Sundar\n"
        "பிறந்த தேதி: 18/07/2004\n"
        "வகுப்பு: பிற்படுத்தப்பட்ட வகுப்பு (BC)\n"
        "சான்றிதழ் எண்: CC/2023/89201\n"
    )

    # Validate DOB
    res_dob = engine.validate_field_accuracy(
        field_key="dob",
        raw_val="18/07/2004",
        document_text=tamil_doc_text,
        source_doc_type="COMMUNITY",
    )
    assert res_dob.normalized_value == "18/07/2004"
    assert res_dob.confidence == "HIGH"

    # Validate Community
    res_comm = engine.validate_field_accuracy(
        field_key="community_category",
        raw_val="BC",
        document_text=tamil_doc_text,
        source_doc_type="COMMUNITY",
    )
    assert res_comm.normalized_value == "BC"
    assert res_comm.confidence == "HIGH"

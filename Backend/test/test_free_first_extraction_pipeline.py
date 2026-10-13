"""
Free-First Document Extraction Pipeline Test Suite
=================================================

Comprehensive test suite verifying:
1. Student upload does NOT call Gemini.
2. Student upload does NOT call Mistral.
3. Student upload does NOT call OCR.
4. Local OCR success -> Gemini extraction.
5. Local OCR unavailable -> Gemini multimodal.
6. Mistral 429 -> fallback works.
7. Gemini multimodal successfully extracts passbook fields.
8. Gemini multimodal successfully extracts TC fields.
9. Gemini multimodal successfully extracts Aadhaar fields.
10. Community extraction continues working.
11. Genuine missing field -> FIELD_NOT_FOUND.
12. OCR/API failure != FIELD_NOT_FOUND.
13. Extraction uses stored document.
14. No re-upload required.
15. Existing verification flow remains unchanged.
16. Existing extraction history remains immutable.
"""

import io
import os
import json
import pytest
import pytest_asyncio
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import MagicMock, AsyncMock, patch
from PIL import Image, ImageDraw

from beanie import PydanticObjectId, init_beanie
from motor.motor_asyncio import AsyncIOMotorClient

from app.core.config import settings
from app.models.user import User, UserRole
from app.models.department import Department
from app.models.batch import AdmissionBatch
from app.models.student_submission import StudentSubmission
from app.models.student_document import StudentDocument, DocumentVersion, DocumentValidationStatus
from app.models.document_extraction_request import DocumentExtractionRequest, ExtractionRequestStatus
from app.models.document_extraction_result import DocumentExtractionResult
from app.models.document_verification import (
    DocumentFieldVerification,
    VerificationFieldStatus,
    VerificationHistoryEntry,
)
from app.services.ocr_service import perform_local_ocr, OCRService, MistralOCRException
from app.services.gemini_service import GeminiService
from app.services.student_document_service import StudentDocumentService
from app.services.document_extraction_service import DocumentExtractionService
from app.services.document_verification_service import DocumentVerificationService


@pytest_asyncio.fixture(autouse=True)
async def setup_test_db():
    if not hasattr(AsyncIOMotorClient, "append_metadata"):
        AsyncIOMotorClient.append_metadata = lambda *args, **kwargs: None

    test_client = AsyncIOMotorClient(settings.MONGODB_URI)
    await test_client.drop_database("free_first_test_db")
    test_db = test_client["free_first_test_db"]

    import app.db.database as db_mod
    db_mod.client = test_client
    db_mod.db = test_db
    db_mod._is_connected = True

    await init_beanie(
        database=test_db,
        document_models=[
            User,
            Department,
            AdmissionBatch,
            StudentSubmission,
            StudentDocument,
            DocumentExtractionRequest,
            DocumentExtractionResult,
            DocumentFieldVerification,
        ],
    )

    yield

    try:
        await test_client.drop_database("free_first_test_db")
    finally:
        test_client.close()


@pytest.fixture
def sample_test_image(tmp_path):
    """Creates a tiny real test image on disk."""
    img_file = tmp_path / "test_doc.png"
    img = Image.new("RGB", (300, 100), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.text((10, 10), "GOVERNMENT OF TAMIL NADU", fill=(0, 0, 0))
    img.save(str(img_file))
    return str(img_file)


# =========================================================================
# 1, 2, 3: Student upload does NOT call Gemini, Mistral, or OCR
# =========================================================================

@pytest.mark.asyncio
async def test_student_upload_does_not_call_gemini_mistral_or_ocr(sample_test_image):
    """
    ARCHITECTURE RULE:
    Student upload must strictly store original file, StudentDocument, and DocumentVersion (v1).
    It must NEVER invoke Gemini, Mistral, or any OCR service.
    """
    doc_service = StudentDocumentService()

    with patch("app.services.gemini_service.GeminiService.extract_from_file", side_effect=AssertionError("Gemini must not be called")), \
         patch("app.services.gemini_service.GeminiService.extract_from_bytes", side_effect=AssertionError("Gemini must not be called")), \
         patch("app.services.ocr_service.perform_mistral_ocr", side_effect=AssertionError("Mistral must not be called")), \
         patch("app.services.ocr_service.perform_local_ocr", side_effect=AssertionError("Local OCR must not be called")):

        doc = await doc_service.create_student_document(
            student_id="26TEST001",
            batch_id="batch_free_first",
            document_type="AADHAAR",
            document_name="Aadhaar Card",
            initial_file_path=sample_test_image,
            original_filename="test_doc.png",
            file_size_bytes=os.path.getsize(sample_test_image),
            mime_type="image/png",
        )

        assert doc is not None
        assert doc.student_id == "26TEST001"
        assert doc.document_type == "AADHAAR"
        assert len(doc.versions) == 1
        assert doc.versions[0].version_number == 1
        assert doc.versions[0].file_path == sample_test_image


# =========================================================================
# 4: Local OCR success -> Gemini extraction with OCR text
# =========================================================================

@pytest.mark.asyncio
async def test_local_ocr_success_leads_to_gemini_extraction(sample_test_image):
    """When Local OCR succeeds, Gemini receives OCR text + document context, provenance is LOCAL_OCR_GEMINI."""
    doc_service = StudentDocumentService()
    ext_service = DocumentExtractionService()

    doc = await doc_service.create_student_document(
        student_id="26TEST002",
        batch_id="batch_free_first",
        document_type="AADHAAR",
        document_name="Aadhaar Card",
        initial_file_path=sample_test_image,
    )

    mock_gemini_return = {
        "success": True,
        "confidence": 97.0,
        "fields": {
            "aadhaar_number": {"value": "9999 8888 7777", "confidence": 98.0, "evidence": "UID: 9999 8888 7777"},
            "student_name": {"value": "John Doe", "confidence": 96.0, "evidence": "John Doe"},
        },
        "extracted_summary": {
            "aadhaar_number": "9999 8888 7777",
            "student_name": "John Doe",
        },
    }

    mock_ocr_return = {
        "success": True,
        "status": "OCR_SUCCESS",
        "text": "Aadhaar UID: 9999 8888 7777 Name: John Doe",
        "pages": [{"page_number": 1, "text": "Aadhaar UID: 9999 8888 7777 Name: John Doe"}],
        "confidence": 95.0,
        "provider": "LOCAL_RAPIDOCR",
    }

    staff_user = User(
        username="staff_tester1",
        name="Staff Tester 1",
        email="staff1@example.com",
        password="hash",
        role=UserRole.SUPER_ADMIN,
    )

    with patch("app.services.ocr_service.OCRService.extract_text", return_value=mock_ocr_return), \
         patch.object(ext_service.gemini_service, "extract_from_file", return_value=mock_gemini_return) as mock_gem:

        req, res = await ext_service.request_and_extract_fields(
            student_document_id=str(doc.id),
            requested_fields=["Aadhaar Number", "Student Name"],
            actor=staff_user,
        )

        assert req.status == ExtractionRequestStatus.COMPLETED
        assert res is not None
        assert res.provenance == "LOCAL_OCR_GEMINI"
        assert res.ocr_status == "OCR_SUCCESS"
        assert res.ai_provider == "gemini"
        assert res.extracted_data["aadhaar_number"] == "9999 8888 7777"
        assert res.extracted_data["student_name"] == "John Doe"

        # Verify Gemini was invoked with OCR text provided
        mock_gem.assert_called_once()
        _, kwargs = mock_gem.call_args
        assert kwargs.get("ocr_text") == "Aadhaar UID: 9999 8888 7777 Name: John Doe"


# =========================================================================
# 5: Local OCR unavailable/fails -> Gemini multimodal directly
# =========================================================================

@pytest.mark.asyncio
async def test_local_ocr_unavailable_leads_to_gemini_multimodal(sample_test_image):
    """When Local OCR fails or is unavailable, pipeline automatically engages Gemini Multimodal directly."""
    doc_service = StudentDocumentService()
    ext_service = DocumentExtractionService()

    doc = await doc_service.create_student_document(
        student_id="26TEST003",
        batch_id="batch_free_first",
        document_type="BANK_PASSBOOK",
        document_name="Bank Passbook",
        initial_file_path=sample_test_image,
    )

    mock_ocr_failed = {
        "success": False,
        "status": "OCR_UNAVAILABLE",
        "text": "",
        "pages": [],
        "confidence": 0.0,
        "provider": "LOCAL_RAPIDOCR",
        "message": "Local OCR engine not available",
    }

    mock_gemini_return = {
        "success": True,
        "confidence": 96.0,
        "fields": {
            "ifsc_code": {"value": "KVBL0001234", "confidence": 0.96, "evidence": "IFSC: KVBL0001234"},
            "bank_name": {"value": "Karur Vysya Bank", "confidence": 0.98, "evidence": "Karur Vysya Bank"},
        },
        "extracted_summary": {
            "ifsc_code": "KVBL0001234",
            "bank_name": "Karur Vysya Bank",
        },
    }

    staff_user = User(
        username="staff_tester2",
        name="Staff Tester 2",
        email="staff2@example.com",
        password="hash",
        role=UserRole.SUPER_ADMIN,
    )

    with patch("app.services.ocr_service.OCRService.extract_text", return_value=mock_ocr_failed), \
         patch.object(ext_service.gemini_service, "extract_from_file", return_value=mock_gemini_return) as mock_gem:

        req, res = await ext_service.request_and_extract_fields(
            student_document_id=str(doc.id),
            requested_fields=["ifsc_code", "bank_name"],
            actor=staff_user,
        )

        assert req.status == ExtractionRequestStatus.COMPLETED
        assert res is not None
        assert res.provenance == "GEMINI_MULTIMODAL"
        assert res.ocr_status == "OCR_UNAVAILABLE"
        assert res.extracted_data["ifsc_code"] == "KVBL0001234"
        assert res.extracted_data["bank_name"] == "Karur Vysya Bank"

        # Verify Gemini Multimodal was invoked with ocr_text=None (pure multimodal vision)
        mock_gem.assert_called_once()
        _, kwargs = mock_gem.call_args
        assert kwargs.get("ocr_text") is None


# =========================================================================
# 6: Mistral 429 -> Fallback works without breaking extraction
# =========================================================================

@pytest.mark.asyncio
async def test_mistral_429_immediately_falls_back_without_breaking_extraction(sample_test_image):
    """When Mistral returns 429 / rate_limited 1300, it does not fail the extraction; Gemini Multimodal extracts successfully."""
    doc_service = StudentDocumentService()
    ext_service = DocumentExtractionService()

    doc = await doc_service.create_student_document(
        student_id="26TEST004",
        batch_id="batch_free_first",
        document_type="COMMUNITY",
        document_name="Community Certificate",
        initial_file_path=sample_test_image,
    )

    # Simulate Mistral 429 rate limit error
    mock_ocr_429 = {
        "success": False,
        "status": "OCR_RATE_LIMITED",
        "text": "",
        "pages": [],
        "confidence": 0.0,
        "provider": "MISTRAL",
        "message": "Mistral OCR rate limited (429 code 1300)",
    }

    mock_gemini_return = {
        "success": True,
        "confidence": 95.0,
        "fields": {
            "community_category": {"value": "BC", "confidence": 0.95, "evidence": "Category: BC"},
            "caste": {"value": "Kongu Vellalar", "confidence": 0.94, "evidence": "Caste: Kongu Vellalar"},
        },
        "extracted_summary": {
            "community_category": "BC",
            "caste": "Kongu Vellalar",
        },
    }

    staff_user = User(
        username="staff_tester3",
        name="Staff Tester 3",
        email="staff3@example.com",
        password="hash",
        role=UserRole.SUPER_ADMIN,
    )

    with patch("app.services.ocr_service.OCRService.extract_text", return_value=mock_ocr_429), \
         patch.object(ext_service.gemini_service, "extract_from_file", return_value=mock_gemini_return):

        req, res = await ext_service.request_and_extract_fields(
            student_document_id=str(doc.id),
            requested_fields=["community_category", "caste"],
            actor=staff_user,
        )

        assert req.status == ExtractionRequestStatus.COMPLETED
        assert res is not None
        assert res.provenance == "GEMINI_MULTIMODAL"
        assert res.ocr_status == "OCR_RATE_LIMITED"
        assert res.extracted_data["community_category"] == "BC"
        assert res.extracted_data["caste"] == "Kongu Vellalar"


# =========================================================================
# 7, 8, 9, 10: Multimodal extraction of Passbook, TC, Aadhaar, Community
# =========================================================================

@pytest.mark.asyncio
async def test_gemini_multimodal_extracts_passbook_fields(sample_test_image):
    """Gemini multimodal extracts bank passbook requested fields: account_number, ifsc_code, bank_name, branch."""
    ext_service = DocumentExtractionService()
    doc_service = StudentDocumentService()

    doc = await doc_service.create_student_document(
        student_id="26TEST005",
        batch_id="batch_free_first",
        document_type="BANK_PASSBOOK",
        document_name="Passbook",
        initial_file_path=sample_test_image,
    )

    mock_passbook_res = {
        "success": True,
        "confidence": 98.0,
        "fields": {
            "account_number": {"value": "123456789012", "confidence": 0.98, "evidence": "A/C: 123456789012"},
            "ifsc_code": {"value": "KVBL0001234", "confidence": 0.97, "evidence": "IFSC: KVBL0001234"},
            "bank_name": {"value": "Karur Vysya Bank", "confidence": 0.99, "evidence": "Karur Vysya Bank"},
            "branch": {"value": "Coimbatore Main", "confidence": 0.95, "evidence": "Branch: Coimbatore Main"},
        },
        "extracted_summary": {
            "account_number": "123456789012",
            "ifsc_code": "KVBL0001234",
            "bank_name": "Karur Vysya Bank",
            "branch": "Coimbatore Main",
        },
    }

    staff_user = User(username="staff4", name="Staff 4", email="s4@test.com", password="h", role=UserRole.SUPER_ADMIN)
    with patch("app.services.ocr_service.OCRService.extract_text", return_value={"success": False, "status": "OCR_FAILED"}), \
         patch.object(ext_service.gemini_service, "extract_from_file", return_value=mock_passbook_res):

        req, res = await ext_service.request_and_extract_fields(
            student_document_id=str(doc.id),
            requested_fields=["account_number", "ifsc_code", "bank_name", "branch"],
            actor=staff_user,
        )

        assert res.extracted_data["account_number"] == "123456789012"
        assert res.extracted_data["ifsc_code"] == "KVBL0001234"
        assert res.extracted_data["bank_name"] == "Karur Vysya Bank"
        assert res.extracted_data["branch"] == "Coimbatore Main"


@pytest.mark.asyncio
async def test_gemini_multimodal_extracts_transfer_certificate_fields(sample_test_image):
    """Gemini multimodal extracts TC fields: mother_name, emis_id."""
    ext_service = DocumentExtractionService()
    doc_service = StudentDocumentService()

    doc = await doc_service.create_student_document(
        student_id="26TEST006",
        batch_id="batch_free_first",
        document_type="TRANSFER_CERTIFICATE",
        document_name="Transfer Certificate",
        initial_file_path=sample_test_image,
    )

    mock_tc_res = {
        "success": True,
        "confidence": 95.0,
        "fields": {
            "mother_name": {"value": "Lakshmi Devi", "confidence": 0.95, "evidence": "Mother: Lakshmi Devi"},
            "emis_id": {"value": "33020401502", "confidence": 0.98, "evidence": "EMIS: 33020401502"},
        },
        "extracted_summary": {
            "mother_name": "Lakshmi Devi",
            "emis_id": "33020401502",
        },
    }

    staff_user = User(username="staff5", name="Staff 5", email="s5@test.com", password="h", role=UserRole.SUPER_ADMIN)
    with patch("app.services.ocr_service.OCRService.extract_text", return_value={"success": False, "status": "OCR_FAILED"}), \
         patch.object(ext_service.gemini_service, "extract_from_file", return_value=mock_tc_res):

        req, res = await ext_service.request_and_extract_fields(
            student_document_id=str(doc.id),
            requested_fields=["mother_name", "emis_id"],
            actor=staff_user,
        )

        assert res.extracted_data["mother_name"] == "Lakshmi Devi"
        assert res.extracted_data["emis_id"] == "33020401502"


@pytest.mark.asyncio
async def test_gemini_multimodal_extracts_aadhaar_fields(sample_test_image):
    """Gemini multimodal extracts Aadhaar fields: aadhaar_number, student_name, date_of_birth, gender."""
    ext_service = DocumentExtractionService()
    doc_service = StudentDocumentService()

    doc = await doc_service.create_student_document(
        student_id="26TEST011",
        batch_id="batch_free_first",
        document_type="AADHAAR",
        document_name="Aadhaar Card",
        initial_file_path=sample_test_image,
    )

    mock_aadhaar_res = {
        "success": True,
        "confidence": 98.0,
        "fields": {
            "aadhaar_number": {"value": "9999 8888 7777", "confidence": 0.98, "evidence": "UID: 9999 8888 7777"},
            "student_name": {"value": "Arun Kumar", "confidence": 0.97, "evidence": "Name: Arun Kumar"},
            "date_of_birth": {"value": "2005-06-15", "confidence": 0.95, "evidence": "DOB: 15/06/2005"},
            "gender": {"value": "MALE", "confidence": 0.99, "evidence": "Gender: Male"},
        },
        "extracted_summary": {
            "aadhaar_number": "9999 8888 7777",
            "student_name": "Arun Kumar",
            "date_of_birth": "2005-06-15",
            "gender": "MALE",
        },
    }

    staff_user = User(username="staff_aadhaar", name="Staff Aadhaar", email="saadhaar@test.com", password="h", role=UserRole.SUPER_ADMIN)
    with patch("app.services.ocr_service.OCRService.extract_text", return_value={"success": False, "status": "OCR_FAILED"}), \
         patch.object(ext_service.gemini_service, "extract_from_file", return_value=mock_aadhaar_res):

        req, res = await ext_service.request_and_extract_fields(
            student_document_id=str(doc.id),
            requested_fields=["aadhaar_number", "student_name", "date_of_birth", "gender"],
            actor=staff_user,
        )

        assert res.extracted_data["aadhaar_number"] == "9999 8888 7777"
        assert res.extracted_data["student_name"] == "Arun Kumar"
        assert res.extracted_data["date_of_birth"] == "2005-06-15"
        assert res.extracted_data["gender"] == "MALE"
        assert res.provenance == "GEMINI_MULTIMODAL"


@pytest.mark.asyncio
async def test_community_extraction_continues_working(sample_test_image):
    """Community Certificate extraction continues working via Gemini multimodal."""
    ext_service = DocumentExtractionService()
    doc_service = StudentDocumentService()

    doc = await doc_service.create_student_document(
        student_id="26TEST012",
        batch_id="batch_free_first",
        document_type="COMMUNITY",
        document_name="Community Certificate",
        initial_file_path=sample_test_image,
    )

    mock_community_res = {
        "success": True,
        "confidence": 96.0,
        "fields": {
            "community_category": {"value": "MBC", "confidence": 0.96, "evidence": "Community: Most Backward Classes (MBC)"},
            "caste": {"value": "Vanniyar", "confidence": 0.95, "evidence": "Caste: Vanniyar"},
        },
        "extracted_summary": {
            "community_category": "MBC",
            "caste": "Vanniyar",
        },
    }

    staff_user = User(username="staff_comm", name="Staff Comm", email="scomm@test.com", password="h", role=UserRole.SUPER_ADMIN)
    with patch("app.services.ocr_service.OCRService.extract_text", return_value={"success": False, "status": "OCR_FAILED"}), \
         patch.object(ext_service.gemini_service, "extract_from_file", return_value=mock_community_res):

        req, res = await ext_service.request_and_extract_fields(
            student_document_id=str(doc.id),
            requested_fields=["community_category", "caste"],
            actor=staff_user,
        )

        assert res.extracted_data["community_category"] == "MBC"
        assert res.extracted_data["caste"] == "Vanniyar"
        assert res.provenance == "GEMINI_MULTIMODAL"


# =========================================================================
# 11, 12: Genuine missing field vs Infrastructure failure
# =========================================================================

@pytest.mark.asyncio
async def test_genuine_missing_field_results_in_field_not_found(sample_test_image):
    """When AI analyzes document and a field genuinely does not exist, value is None and verification is marked FIELD_NOT_FOUND."""
    ext_service = DocumentExtractionService()
    doc_service = StudentDocumentService()

    doc = await doc_service.create_student_document(
        student_id="26TEST007",
        batch_id="batch_free_first",
        document_type="TRANSFER_CERTIFICATE",
        document_name="Transfer Certificate",
        initial_file_path=sample_test_image,
    )

    # Document contains mother_name, but emis_id is genuinely absent
    mock_tc_res = {
        "success": True,
        "confidence": 94.0,
        "fields": {
            "mother_name": {"value": "Lakshmi Devi", "confidence": 0.95, "evidence": "Mother: Lakshmi Devi"},
            "emis_id": {"value": None, "confidence": 0.0, "evidence": None},
        },
        "extracted_summary": {
            "mother_name": "Lakshmi Devi",
            "emis_id": None,
        },
    }

    staff_user = User(username="staff6", name="Staff 6", email="s6@test.com", password="h", role=UserRole.SUPER_ADMIN)
    with patch("app.services.ocr_service.OCRService.extract_text", return_value={"success": False, "status": "OCR_FAILED"}), \
         patch.object(ext_service.gemini_service, "extract_from_file", return_value=mock_tc_res):

        req, res = await ext_service.request_and_extract_fields(
            student_document_id=str(doc.id),
            requested_fields=["mother_name", "emis_id"],
            actor=staff_user,
        )

        assert res.extracted_data["mother_name"] == "Lakshmi Devi"
        assert res.extracted_data["emis_id"] is None

        # Check verification records
        verif_records = await DocumentFieldVerification.find(
            DocumentFieldVerification.extraction_result_id == str(res.id)
        ).to_list()
        emis_verif = next(r for r in verif_records if r.field_name == "emis_id")
        assert emis_verif.ai_value is None
        assert emis_verif.field_state == "FIELD_NOT_FOUND"


@pytest.mark.asyncio
async def test_infrastructure_failure_does_not_convert_to_field_not_found(sample_test_image):
    """When OCR and AI infrastructure fails, request fails explicitly with error code; it NEVER converts into Field Not Found."""
    ext_service = DocumentExtractionService()
    doc_service = StudentDocumentService()

    doc = await doc_service.create_student_document(
        student_id="26TEST008",
        batch_id="batch_free_first",
        document_type="BANK_PASSBOOK",
        document_name="Passbook",
        initial_file_path=sample_test_image,
    )

    # OCR fails AND Gemini quota exhausted (429)
    mock_ocr_fail = {"success": False, "status": "OCR_FAILED", "message": "OCR failed"}
    mock_gemini_quota_error = {
        "success": False,
        "error": "ResourceExhausted: 429 Resource has been exhausted (e.g. check quota)",
        "error_type": "QUOTA_EXCEEDED",
    }

    staff_user = User(username="staff7", name="Staff 7", email="s7@test.com", password="h", role=UserRole.SUPER_ADMIN)
    with patch("app.services.ocr_service.OCRService.extract_text", return_value=mock_ocr_fail), \
         patch.object(ext_service.gemini_service, "extract_from_file", return_value=mock_gemini_quota_error):

        req, res = await ext_service.request_and_extract_fields(
            student_document_id=str(doc.id),
            requested_fields=["ifsc_code", "bank_name"],
            actor=staff_user,
        )

        assert req.status == ExtractionRequestStatus.FAILED
        assert res is None
        assert "AI_RATE_LIMITED" in req.error_message or "429" in req.error_message

        # No verification record fabricated as "Not Found"
        verif_records = await DocumentFieldVerification.find(
            DocumentFieldVerification.document_id == str(doc.id)
        ).to_list()
        assert len(verif_records) == 0


# =========================================================================
# 13, 14: Extraction uses stored document, No re-upload required
# =========================================================================

@pytest.mark.asyncio
async def test_extraction_uses_stored_document_without_reupload(sample_test_image):
    """Staff requests extraction on stored document; pipeline directly reads stored version file without re-upload."""
    doc_service = StudentDocumentService()
    ext_service = DocumentExtractionService()

    doc = await doc_service.create_student_document(
        student_id="26TEST009",
        batch_id="batch_free_first",
        document_type="AADHAAR",
        document_name="Aadhaar Card",
        initial_file_path=sample_test_image,
    )

    mock_gemini_return = {
        "success": True,
        "confidence": 98.0,
        "fields": {"aadhaar_number": {"value": "1111 2222 3333", "confidence": 0.98}},
        "extracted_summary": {"aadhaar_number": "1111 2222 3333"},
    }

    staff_user = User(username="staff8", name="Staff 8", email="s8@test.com", password="h", role=UserRole.SUPER_ADMIN)
    with patch("app.services.ocr_service.OCRService.extract_text", return_value={"success": False, "status": "OCR_FAILED"}), \
         patch.object(ext_service.gemini_service, "extract_from_file", return_value=mock_gemini_return) as mock_gem:

        req, res = await ext_service.request_and_extract_fields(
            student_document_id=str(doc.id),
            requested_fields=["aadhaar_number"],
            actor=staff_user,
        )

        assert res.extracted_data["aadhaar_number"] == "1111 2222 3333"
        # Confirm it used the stored file path on disk directly
        mock_gem.assert_called_once()
        _, kwargs = mock_gem.call_args
        assert kwargs["file_path"] == sample_test_image


# =========================================================================
# 15, 16: Verification workflow & History immutability
# =========================================================================

@pytest.mark.asyncio
async def test_verification_workflow_and_immutability(sample_test_image):
    """
    Verification lifecycle:
    1. AI value is populated and immutable.
    2. Student submits correction -> status = CORRECTION_REQUESTED, final_value is None.
    3. Staff approves correction -> final_value = student_value, status = STAFF_APPROVED.
    4. AI value never mutates.
    """
    verif_service = DocumentVerificationService()

    # Create dummy extraction result
    ext_result = DocumentExtractionResult(
        extraction_request_id="req_test_1",
        student_document_id="doc_test_1",
        document_version_id="v1_test",
        requested_fields=["student_name"],
        extracted_data={"student_name": "Siddharth N"},
        confidence=96.0,
        provenance="GEMINI_MULTIMODAL",
        ocr_status="OCR_SUCCESS",
        ai_provider="gemini",
    )
    await ext_result.insert()

    student_doc = StudentDocument(
        student_id="26TEST010",
        batch_id="batch_1",
        document_type="AADHAAR",
        document_name="Aadhaar",
        expected_document_type="AADHAAR",
        current_version=1,
    )
    await student_doc.insert()

    # 1. Initialize verification
    records = await verif_service.initialize_verification_from_extraction(ext_result, student_doc)
    assert len(records) == 1
    rec = records[0]
    assert rec.ai_value == "Siddharth N"
    assert rec.final_value is None
    assert rec.status == VerificationFieldStatus.AI_EXTRACTED

    # 2. Student submits correction
    from app.schemas.document_verification import StudentVerificationSubmitRequest, StudentFieldVerificationItem
    student_user = User(username="26TEST010", name="Student Ten", register_number="26TEST010", role=UserRole.STUDENT, email="s10@test.com", password="h")

    submit_req = StudentVerificationSubmitRequest(
        fields=[
            StudentFieldVerificationItem(
                verification_id=str(rec.id),
                is_confirmed=False,
                corrected_value="Siddharth Natarajan",
                comment="Spelled out full initial",
            )
        ]
    )

    updated = await verif_service.submit_student_verification("26TEST010", submit_req, student_user)
    assert len(updated) == 1
    u_rec = updated[0]
    assert u_rec.ai_value == "Siddharth N"  # IMMUTABLE!
    assert u_rec.student_value == "Siddharth Natarajan"
    assert u_rec.final_value is None
    assert u_rec.status == VerificationFieldStatus.CORRECTION_REQUESTED

    # 3. Staff approves correction
    staff_user = User(username="admin_staff", name="Admin Staff", role=UserRole.SUPER_ADMIN, email="admin@test.com", password="h")

    reviewed = await verif_service.review_correction(
        verification_id=str(u_rec.id),
        action="APPROVE",
        actor=staff_user,
        staff_comment="Approved against physical TC",
    )
    assert reviewed.ai_value == "Siddharth N"  # AI value STILL immutable!
    assert reviewed.final_value == "Siddharth Natarajan"
    assert reviewed.status == VerificationFieldStatus.STAFF_APPROVED

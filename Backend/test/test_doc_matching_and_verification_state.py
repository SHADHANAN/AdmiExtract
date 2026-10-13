import pytest
import pytest_asyncio
import os
import io
from datetime import datetime, timezone
from beanie import PydanticObjectId
from motor.motor_asyncio import AsyncIOMotorClient

from app.core.config import settings
from app.models.user import User, UserRole
from app.models.batch import AdmissionBatch
from app.models.student_submission import StudentSubmission, StudentDocumentMeta
from app.models.student_document import StudentDocument, DocumentVersion
from app.models.wanted_field_config import DocumentFieldConfiguration, WantedFieldItem
from app.models.batch_extraction import BatchExtractionRequest, BatchExtractionStatus, BatchVerificationStatus
from app.models.document_verification import DocumentFieldVerification, VerificationFieldStatus
from app.services.batch_extraction_service import BatchExtractionService
from app.services.field_source_rules import (
    DOCUMENT_TYPE_ALIASES,
    normalize_document_type,
    resolve_canonical_document_type,
)


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    import app.db.database as db_mod

    db_mod.client = AsyncIOMotorClient(
        settings.MONGODB_URI, serverSelectionTimeoutMS=2000
    )
    db_mod.db = db_mod.client[settings.DATABASE_NAME]
    await db_mod._run_db_setup()


@pytest.mark.asyncio
async def test_canonical_document_type_normalization():
    """Verify that all document type aliases and raw formats resolve to canonical keys."""
    assert resolve_canonical_document_type("Aadhaar Card") == "AADHAAR"
    assert resolve_canonical_document_type("AADHAR") == "AADHAAR"
    assert resolve_canonical_document_type("UID") == "AADHAAR"
    assert resolve_canonical_document_type("6ac34fc1702867860a21957d", "Aadhaar Card") == "AADHAAR"

    assert resolve_canonical_document_type("Community Certificate") == "COMMUNITY"
    assert resolve_canonical_document_type("CASTE") == "COMMUNITY"
    assert resolve_canonical_document_type("6ac34fc1702867860a219581", "Community Certificate") == "COMMUNITY"

    assert resolve_canonical_document_type("Transfer Certificate (TC)") == "TRANSFER_CERTIFICATE"
    assert resolve_canonical_document_type("TC") == "TRANSFER_CERTIFICATE"
    assert resolve_canonical_document_type("6ac34fc1702867860a219583", "Transfer Certificate (TC)") == "TRANSFER_CERTIFICATE"

    assert resolve_canonical_document_type("Income Certificate") == "INCOME"
    assert resolve_canonical_document_type("Bank Passbook") == "BANK_PASSBOOK"
    assert resolve_canonical_document_type("PASSBOOK") == "BANK_PASSBOOK"
    assert resolve_canonical_document_type("SSLC / 10th Marksheet") == "SSLC"
    assert resolve_canonical_document_type("10TH") == "SSLC"
    assert resolve_canonical_document_type("HSC / 12th Marksheet") == "HSC"
    assert resolve_canonical_document_type("Birth Certificate") == "BIRTH_CERTIFICATE"


@pytest.mark.asyncio
async def test_document_matching_and_partial_extraction(tmp_path):
    """
    Create a student with stored documents for:
    - AADHAAR
    - COMMUNITY
    - TRANSFER_CERTIFICATE
    - BANK_PASSBOOK
    (INCOME is missing / not uploaded)

    Run extraction:
    - Aadhaar, Community, TC, Passbook fields must be FOUND and extracted.
    - Only Income fields must be marked as NOT_AVAILABLE.
    - Only INCOME must be recorded in missing_documents.
    - Pending verification count must be 1 (because usable data exists).
    """
    batch_id = "test_matching_batch_01"
    reg_no = "REG_MATCH_001"
    actor = User(name="Admin", password="pw", username="admin_tester", role=UserRole.SUPER_ADMIN, email="admin@test.com")

    # Create batch
    batch = AdmissionBatch(
        id=batch_id,
        name="Test Matching Batch",
        academic_year="2026-2027",
        department_id="CSE",
        created_by="admin_user",
    )
    await batch.save()

    # Create dummy files on disk
    aadhaar_file = tmp_path / "aadhaar.pdf"
    aadhaar_file.write_bytes(b"%PDF-1.4 dummy aadhaar content")

    comm_file = tmp_path / "community.pdf"
    comm_file.write_bytes(b"%PDF-1.4 dummy community content")

    tc_file = tmp_path / "tc.pdf"
    tc_file.write_bytes(b"%PDF-1.4 dummy tc content")

    passbook_file = tmp_path / "passbook.pdf"
    passbook_file.write_bytes(b"%PDF-1.4 dummy passbook content")

    # Store StudentDocuments with ObjectId-like raw document_types (simulating real world legacy data)
    doc_aadhaar = StudentDocument(
        student_id=reg_no,
        batch_id=batch_id,
        document_type="6AC34E9BE101C45EF2E3E7B8",  # raw requirement ID
        document_name="Aadhaar Card",
        versions=[
            DocumentVersion(
                version_number=1,
                file_path=str(aadhaar_file),
                original_filename="aadhaar.pdf",
                file_size_bytes=len(aadhaar_file.read_bytes()),
            )
        ],
    )
    await doc_aadhaar.save()

    doc_comm = StudentDocument(
        student_id=reg_no,
        batch_id=batch_id,
        document_type="COMMUNITY_CERTIFICATE",
        document_name="Community Certificate",
        versions=[
            DocumentVersion(
                version_number=1,
                file_path=str(comm_file),
                original_filename="community.pdf",
                file_size_bytes=len(comm_file.read_bytes()),
            )
        ],
    )
    await doc_comm.save()

    doc_tc = StudentDocument(
        student_id=reg_no,
        batch_id=batch_id,
        document_type="TC",
        document_name="Transfer Certificate (TC)",
        versions=[
            DocumentVersion(
                version_number=1,
                file_path=str(tc_file),
                original_filename="tc.pdf",
                file_size_bytes=len(tc_file.read_bytes()),
            )
        ],
    )
    await doc_tc.save()

    doc_passbook = StudentDocument(
        student_id=reg_no,
        batch_id=batch_id,
        document_type="PASSBOOK",
        document_name="Bank Passbook",
        versions=[
            DocumentVersion(
                version_number=1,
                file_path=str(passbook_file),
                original_filename="passbook.pdf",
                file_size_bytes=len(passbook_file.read_bytes()),
            )
        ],
    )
    await doc_passbook.save()

    # Create submission
    sub = StudentSubmission(
        batch_id=batch_id,
        register_number=reg_no,
        student_name="Test Student",
        mobile_number="9876543210",
        submission_status="Submitted",
        documents=[
            StudentDocumentMeta(document_name="Aadhaar Card", document_type="AADHAAR", file_path=str(aadhaar_file), status="Uploaded"),
            StudentDocumentMeta(document_name="Community Certificate", document_type="COMMUNITY", file_path=str(comm_file), status="Uploaded"),
            StudentDocumentMeta(document_name="Transfer Certificate (TC)", document_type="TRANSFER_CERTIFICATE", file_path=str(tc_file), status="Uploaded"),
            StudentDocumentMeta(document_name="Bank Passbook", document_type="BANK_PASSBOOK", file_path=str(passbook_file), status="Uploaded"),
            StudentDocumentMeta(document_name="Income Certificate", document_type="INCOME", file_path=None, status="Not Available"),
        ],
    )
    await sub.save()

    from unittest.mock import patch

    def mock_gemini_extract(*args, **kwargs):
        return {
            "success": True,
            "extracted_data": {
                "aadhaar_number": "123456789012",
                "gender": "MALE",
                "student_name": "Test Student",
                "community_category": "BC",
                "caste": "Vadugar",
                "emis_id": "2015743426",
                "account_number": "1718155000062336",
            },
            "fields": {
                "aadhaar_number": {"value": "123456789012", "confidence": 95},
                "gender": {"value": "MALE", "confidence": 95},
                "student_name": {"value": "Test Student", "confidence": 95},
                "community_category": {"value": "BC", "confidence": 95},
                "caste": {"value": "Vadugar", "confidence": 95},
                "emis_id": {"value": "2015743426", "confidence": 95},
                "account_number": {"value": "1718155000062336", "confidence": 95},
            },
            "confidence": 95.0,
        }

    # Run extraction
    service = BatchExtractionService()
    req_fields = [
        "aadhaar_number",
        "student_name",
        "gender",
        "community_category",
        "caste",
        "annual_family_income",  # missing doc (INCOME)
        "emis_id",
        "account_number",
    ]

    with patch("app.services.gemini_service.GeminiService.extract_from_file", side_effect=mock_gemini_extract), \
         patch("app.services.gemini_service.GeminiService.extract_from_bytes", side_effect=mock_gemini_extract):
        summary = await service.create_and_run_batch_extraction(
            batch_id=batch_id,
            requested_columns=[f.replace("_", " ").title() for f in req_fields],
            requested_fields=req_fields,
            actor=actor,
        )

    # Verify summary counts
    assert summary.total_students == 1
    assert summary.processed_count == 1
    assert summary.successful_count == 0  # Income was missing, so not fully successful
    assert summary.missing_docs_count == 1
    assert summary.failed_count == 0
    assert summary.pending_verification_count == 1  # But usable fields exist, so verification is pending!

    # Get details
    detail = await service.get_extraction_details(summary.extraction_request_id, actor)
    assert len(detail.students) == 1
    stud_res = detail.students[0]

    assert stud_res.student_id == reg_no
    assert stud_res.verification_status == "PENDING_VERIFICATION"
    assert stud_res.missing_documents == ["INCOME"]  # Only INCOME, not Aadhaar or Community or TC or Passbook!

    # Verify extracted values
    assert stud_res.fields["aadhaar_number"].ai_value == "123456789012"
    assert stud_res.fields["aadhaar_number"].source_document_type == "AADHAAR"
    assert stud_res.fields["gender"].ai_value == "MALE"
    assert stud_res.fields["community_category"].ai_value == "BC"
    assert stud_res.fields["caste"].ai_value == "Vadugar"
    assert stud_res.fields["emis_id"].ai_value == "2015743426"
    assert stud_res.fields["account_number"].ai_value == "1718155000062336"

    # Only annual_income must be NOT_AVAILABLE
    assert stud_res.fields["annual_income"].ai_value == "NOT_AVAILABLE"
    assert stud_res.fields["annual_income"].is_available is False


@pytest.mark.asyncio
async def test_all_documents_missing_verification_state():
    """
    When all requested documents are missing and 0 usable fields are extracted:
    - Total: 1, Processed: 1, Successful: 0, Missing Docs: 1, Failed: 0
    - Pending Verification MUST be 0!
    - Student verification status MUST be EXTRACTION_INCOMPLETE / MISSING_DOCUMENTS.
    - No meaningless verification session token created.
    """
    batch_id = "test_all_missing_batch_02"
    reg_no = "REG_ALL_MISS_002"
    actor = User(name="Admin", password="pw", username="admin_tester2", role=UserRole.SUPER_ADMIN, email="admin2@test.com")

    # Create batch
    batch = AdmissionBatch(
        id=batch_id,
        name="Test All Missing Batch",
        academic_year="2026-2027",
        department_id="ECE",
        created_by="admin_user",
    )
    await batch.save()

    # Create submission with NO uploaded documents
    sub = StudentSubmission(
        batch_id=batch_id,
        register_number=reg_no,
        student_name="No Docs Student",
        mobile_number="9876543211",
        submission_status="Submitted",
        documents=[],
    )
    await sub.save()

    service = BatchExtractionService()
    req_fields = ["aadhaar_number", "annual_family_income", "community_category"]

    summary = await service.create_and_run_batch_extraction(
        batch_id=batch_id,
        requested_columns=[f.replace("_", " ").title() for f in req_fields],
        requested_fields=req_fields,
        actor=actor,
    )

    # All source documents missing -> pending_verification_count MUST be 0
    assert summary.total_students == 1
    assert summary.processed_count == 1
    assert summary.successful_count == 0
    assert summary.missing_docs_count == 1
    assert summary.pending_verification_count == 0

    detail = await service.get_extraction_details(summary.extraction_request_id, actor)
    stud_res = detail.students[0]

    assert stud_res.verification_status == "EXTRACTION_INCOMPLETE"
    assert stud_res.final_status == "MISSING_DOCUMENTS"
    assert stud_res.verification_token is None
    assert stud_res.verification_link is None

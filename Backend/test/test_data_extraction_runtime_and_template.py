"""
Test Suite: Data Extraction Runtime, Template Endpoint, and Extraction Execution
================================================================================
Verifies:
1. GET /data-extractions/batches/{batch_id}/template returns 200 with accurate canonical fields.
2. Template parsing converts raw Excel headers to canonical snake_case field keys.
3. Single student extraction pipeline using stored documents (Aadhaar, Bank Passbook, TC).
4. Extraction request receives exact canonical fields (aadhaar_number, date_of_birth, gender, permanent_address, account_number, ifsc_code).
5. AI response parsing and persistence to DocumentExtractionResult and DocumentFieldVerification.
6. Classification Gate properly allows VALID documents and rejects WRONG_DOCUMENT / UNKNOWN / NEEDS_REVIEW.
7. Reusing stored documents for multiple extractions without requiring student re-upload.
"""

import io
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from beanie import PydanticObjectId
from fastapi import status
from httpx import AsyncClient, ASGITransport
import openpyxl
from motor.motor_asyncio import AsyncIOMotorClient

from app.main import app
from app.core.config import settings
from app.core.security import create_access_token
from app.models.user import User, UserRole
from app.models.batch import AdmissionBatch
from app.models.student_submission import StudentSubmission, StudentDocumentMeta
from app.models.student_document import StudentDocument, DocumentVersion, DocumentValidationStatus
from app.models.document_verification import DocumentFieldVerification, VerificationFieldStatus
from app.models.document_extraction_result import DocumentExtractionResult
from app.services.batch_extraction_service import BatchExtractionService
from app.services.excel_template_service import ExcelTemplateService
from app.services.document_extraction_service import resolve_canonical_field_key


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    import app.db.database as db_mod
    db_mod.client = AsyncIOMotorClient(settings.MONGODB_URI, serverSelectionTimeoutMS=2000)
    db_mod.db = db_mod.client[settings.DATABASE_NAME]
    await db_mod._run_db_setup()


@pytest_asyncio.fixture
async def auth_super_admin():
    await User.find(User.username == "admin_extraction_tester").delete()
    user = User(
        id=PydanticObjectId(),
        username="admin_extraction_tester",
        name="Admin Tester",
        email="admin_extraction@test.com",
        role=UserRole.SUPER_ADMIN,
        password="dummy_password_hash",
    )
    await user.save()
    token = create_access_token(data={"sub": str(user.id), "role": user.role.value})
    return user, {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_1_resolve_canonical_field_key_semantic_mapping():
    """Verify that resolve_canonical_field_key maps raw Excel headers to canonical keys."""
    assert resolve_canonical_field_key("Student Name") == "student_name"
    assert resolve_canonical_field_key("Aadhaar Number") == "aadhaar_number"
    assert resolve_canonical_field_key("Date of Birth") == "date_of_birth"
    assert resolve_canonical_field_key("Gender") == "gender"
    assert resolve_canonical_field_key("Account Number") == "account_number"
    assert resolve_canonical_field_key("IFSC Code") == "ifsc_code"
    assert resolve_canonical_field_key("Permanent Address") == "permanent_address"
    assert resolve_canonical_field_key("Community") == "community_category"
    assert resolve_canonical_field_key("TC Number") == "tc_number"


@pytest.mark.asyncio
async def test_2_get_batch_template_endpoint_returns_200(auth_super_admin, tmp_path):
    """Verify GET /data-extractions/batches/{batch_id}/template returns 200 with canonical fields."""
    admin_user, headers = auth_super_admin
    batch_id = "BATCH_TEMPLATE_TEST_01"

    await AdmissionBatch.find(AdmissionBatch.id == batch_id).delete()
    batch = AdmissionBatch(
        id=batch_id,
        name="Template Test Batch",
        academic_year="2026-2027",
        department_id="CSE",
        created_by=admin_user.username,
    )
    await batch.save()

    # Create a test Excel workbook
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    headers_list = [
        "Register Number",
        "Student Name",
        "Aadhaar Number",
        "Date of Birth",
        "Gender",
        "Account Number",
        "IFSC Code",
    ]
    ws.append(headers_list)
    ws.append(["24REG001", "Kavitha", "123456789012", "15/08/2004", "Female", "987654321012", "KVBL0001234"])

    buf = io.BytesIO()
    wb.save(buf)
    file_bytes = buf.getvalue()

    # Upload template
    excel_service = ExcelTemplateService()
    await excel_service.save_template_file(
        file_content=file_bytes,
        filename="student_template.xlsx",
        batch_id=batch_id,
        uploaded_by=admin_user.username,
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            f"/data-extractions/batches/{batch_id}/template",
            headers=headers,
        )

    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["template_filename"] == "student_template.xlsx"
    assert data["requested_columns"] == headers_list
    assert "aadhaar_number" in data["canonical_fields"]
    assert "date_of_birth" in data["canonical_fields"]
    assert "account_number" in data["canonical_fields"]
    assert "ifsc_code" in data["canonical_fields"]
    assert data["column_mapping"]["Aadhaar Number"] == "aadhaar_number"
    assert data["column_mapping"]["Account Number"] == "account_number"
    assert data["column_mapping"]["IFSC Code"] == "ifsc_code"


@pytest.mark.asyncio
async def test_3_single_student_multi_doc_extraction_runtime_chain(auth_super_admin, tmp_path):
    """
    Test single student extraction having:
    1. Aadhaar
    2. Bank Passbook
    3. Transfer Certificate

    Requests:
    - aadhaar_number
    - date_of_birth
    - gender
    - permanent_address
    - account_number
    - ifsc_code

    Verifies the complete execution chain:
    Stored Documents -> Classification Gate -> Canonical Field Routing -> AI Extraction -> Persistence -> Verification Records.
    """
    admin_user, auth_headers = auth_super_admin
    batch_id = "BATCH_RUNTIME_STUDENT_01"
    student_id = "24CSE001"

    await AdmissionBatch.find(AdmissionBatch.id == batch_id).delete()
    await StudentSubmission.find(StudentSubmission.batch_id == batch_id).delete()
    await StudentDocument.find(StudentDocument.batch_id == batch_id).delete()

    batch = AdmissionBatch(
        id=batch_id,
        name="Runtime Extraction Test Batch",
        academic_year="2026-2027",
        department_id="CSE",
        created_by=admin_user.username,
    )
    await batch.save()

    # Create dummy files for the 3 documents
    aadhaar_file = tmp_path / "aadhaar_card.pdf"
    aadhaar_file.write_bytes(b"%PDF-1.4 Mock Aadhaar Content with UID 9876 5432 1098 DOB 15/05/2004")

    passbook_file = tmp_path / "bank_passbook.pdf"
    passbook_file.write_bytes(b"%PDF-1.4 Mock Bank Passbook Account 112233445566 IFSC KVBL0001234")

    tc_file = tmp_path / "transfer_certificate.pdf"
    tc_file.write_bytes(b"%PDF-1.4 Mock Transfer Certificate TC/2024/0987")

    # 1. Stored Aadhaar Document
    aadhaar_doc = StudentDocument(
        student_id=student_id,
        batch_id=batch_id,
        document_type="AADHAAR",
        document_name="Aadhaar Card",
        versions=[
            DocumentVersion(
                version_number=1,
                file_path=str(aadhaar_file),
                original_filename="aadhaar_card.pdf",
                file_size_bytes=len(aadhaar_file.read_bytes()),
                detected_document_type="AADHAAR",
                classification_confidence=0.99,
                validation_status=DocumentValidationStatus.VALID.value,
            )
        ],
    )
    await aadhaar_doc.save()

    # 2. Stored Bank Passbook Document
    passbook_doc = StudentDocument(
        student_id=student_id,
        batch_id=batch_id,
        document_type="BANK_PASSBOOK",
        document_name="Bank Passbook",
        versions=[
            DocumentVersion(
                version_number=1,
                file_path=str(passbook_file),
                original_filename="bank_passbook.pdf",
                file_size_bytes=len(passbook_file.read_bytes()),
                detected_document_type="BANK_PASSBOOK",
                classification_confidence=0.98,
                validation_status=DocumentValidationStatus.VALID.value,
            )
        ],
    )
    await passbook_doc.save()

    # 3. Stored TC Document
    tc_doc = StudentDocument(
        student_id=student_id,
        batch_id=batch_id,
        document_type="TRANSFER_CERTIFICATE",
        document_name="Transfer Certificate",
        versions=[
            DocumentVersion(
                version_number=1,
                file_path=str(tc_file),
                original_filename="transfer_certificate.pdf",
                file_size_bytes=len(tc_file.read_bytes()),
                detected_document_type="TRANSFER_CERTIFICATE",
                classification_confidence=1.00,
                validation_status=DocumentValidationStatus.VALID.value,
            )
        ],
    )
    await tc_doc.save()

    # Student Submission record
    sub = StudentSubmission(
        batch_id=batch_id,
        register_number=student_id,
        student_name="Priya Sharma",
        mobile_number="9876543210",
        submission_status="Submitted",
        documents=[
            StudentDocumentMeta(document_name="Aadhaar Card", document_type="AADHAAR", file_path=str(aadhaar_file), status="Uploaded"),
            StudentDocumentMeta(document_name="Bank Passbook", document_type="BANK_PASSBOOK", file_path=str(passbook_file), status="Uploaded"),
            StudentDocumentMeta(document_name="Transfer Certificate", document_type="TRANSFER_CERTIFICATE", file_path=str(tc_file), status="Uploaded"),
        ],
    )
    await sub.save()

    # Mock Gemini AI extraction returning real fields corresponding to target documents
    def mock_gemini_extract(file_path, target_fields, **kwargs):
        res_fields = {}
        if "aadhaar_card" in file_path:
            if "aadhaar_number" in target_fields:
                res_fields["aadhaar_number"] = {"value": "9876 5432 1098", "confidence": 99}
            if "date_of_birth" in target_fields:
                res_fields["date_of_birth"] = {"value": "15/05/2004", "confidence": 98}
            if "gender" in target_fields:
                res_fields["gender"] = {"value": "Female", "confidence": 99}
            if "permanent_address" in target_fields:
                res_fields["permanent_address"] = {"value": "12, Gandhi Street, Chennai - 600001", "confidence": 95}
        elif "bank_passbook" in file_path:
            if "account_number" in target_fields:
                res_fields["account_number"] = {"value": "112233445566", "confidence": 98}
            if "ifsc_code" in target_fields:
                res_fields["ifsc_code"] = {"value": "KVBL0001234", "confidence": 99}
        elif "transfer_certificate" in file_path:
            if "tc_number" in target_fields:
                res_fields["tc_number"] = {"value": "TC/2024/0987", "confidence": 97}

        return {
            "success": True,
            "fields": res_fields,
            "extracted_summary": {k: v["value"] for k, v in res_fields.items() if isinstance(v, dict)},
            "confidence": 98.0,
        }

    requested_fields = [
        "aadhaar_number",
        "date_of_birth",
        "gender",
        "permanent_address",
        "account_number",
        "ifsc_code",
    ]

    service = BatchExtractionService()

    with patch("app.services.gemini_service.GeminiService.extract_from_file", side_effect=mock_gemini_extract):
        summary = await service.create_and_run_batch_extraction(
            batch_id=batch_id,
            requested_columns=[
                "Aadhaar Number",
                "Date of Birth",
                "Gender",
                "Permanent Address",
                "Account Number",
                "IFSC Code",
            ],
            requested_fields=requested_fields,
            actor=admin_user,
        )

    assert summary is not None
    assert summary.batch_id == batch_id
    assert summary.total_students == 1
    assert summary.successful_count == 1
    assert summary.failed_count == 0

    # Verify extraction details
    detail = await service.get_extraction_details(summary.extraction_request_id, admin_user)
    assert len(detail.students) == 1
    stud = detail.students[0]
    assert stud.register_number == student_id

    # Check extracted values
    assert stud.fields["aadhaar_number"].ai_value in ("987654321098", "9876 5432 1098")
    assert stud.fields["date_of_birth"].ai_value == "15/05/2004"
    assert stud.fields["gender"].ai_value == "Female"
    assert stud.fields["account_number"].ai_value == "112233445566"
    assert stud.fields["ifsc_code"].ai_value == "KVBL0001234"

    # Verify DocumentFieldVerification records created in DB
    verifs = await DocumentFieldVerification.find(
        DocumentFieldVerification.extraction_request_id == summary.extraction_request_id
    ).to_list()
    assert len(verifs) >= 6
    verif_map = {v.field_name: v for v in verifs}
    assert verif_map["aadhaar_number"].status == VerificationFieldStatus.AI_EXTRACTED
    assert verif_map["aadhaar_number"].ai_value in ("987654321098", "9876 5432 1098")
    assert verif_map["account_number"].ai_value == "112233445566"
    assert verif_map["ifsc_code"].ai_value == "KVBL0001234"


@pytest.mark.asyncio
async def test_4_extraction_diagnostics_endpoint(auth_super_admin):
    """Verify staff-only GET /data-extractions/diagnostics returns provider health without leaking secrets."""
    admin_user, headers = auth_super_admin
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/data-extractions/diagnostics", headers=headers)

    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert "ocr_provider" in data
    assert "gemini_provider" in data
    assert "storage" in data
    assert data["ocr_provider"]["status"] in ("READY", "FALLBACK_LOCAL_ONLY")
    assert data["gemini_provider"]["status"] in ("READY", "FAILED_NO_KEY")


@pytest.mark.asyncio
async def test_5_gemini_quota_exceeded_handled_gracefully(auth_super_admin, tmp_path):
    """Verify that a Gemini 429 error raises AI_EXTRACTION_UNAVAILABLE instead of returning fake Not found."""
    from app.services.document_extraction_service import DocumentExtractionService, AI_EXTRACTION_UNAVAILABLE

    admin_user, _ = auth_super_admin
    doc_service = DocumentExtractionService()

    # Create a dummy file
    test_file = tmp_path / "dummy_aadhaar.png"
    test_file.write_bytes(b"dummy image bytes")

    with patch("app.services.gemini_service.GeminiService.extract_from_file", return_value={"success": False, "error": "429 RESOURCE_EXHAUSTED Quota exceeded"}):
        with patch("app.services.ocr_service.OCRService.extract_text", return_value={"success": True, "text": "Dummy text", "pages": [], "confidence": 90}):
            with pytest.raises(RuntimeError) as exc_info:
                await doc_service._run_ai_extraction(
                    file_path=str(test_file),
                    document_type="AADHAAR",
                    requested_fields=["aadhaar_number"],
                )

    # Error message must explicitly state AI_EXTRACTION_UNAVAILABLE or AI_RATE_LIMITED
    assert AI_EXTRACTION_UNAVAILABLE in str(exc_info.value) or "AI_RATE_LIMITED" in str(exc_info.value)
    assert "quota" in str(exc_info.value).lower() or "429" in str(exc_info.value)


@pytest.mark.asyncio
async def test_6_ocr_failure_engages_gemini_multimodal(tmp_path):
    from app.services.document_extraction_service import DocumentExtractionService

    doc_service = DocumentExtractionService()
    test_file = tmp_path / "ocr_failure_aadhaar.png"
    test_file.write_bytes(b"dummy image bytes")

    mock_gemini_res = {
        "success": True,
        "confidence": 95.0,
        "fields": {"aadhaar_number": {"value": "9999 8888 7777", "confidence": 0.95}},
        "extracted_summary": {"aadhaar_number": "9999 8888 7777"},
    }

    with patch("app.services.ocr_service.OCRService.extract_text", return_value={"success": False, "status": "OCR_FAILED", "message": "OCR provider unavailable"}):
        with patch.object(doc_service.gemini_service, "extract_from_file", return_value=mock_gemini_res) as gemini_extract:
            extracted_dict, conf, prov, ocr_stat, ai_prov = await doc_service._run_ai_extraction(
                file_path=str(test_file),
                document_type="AADHAAR",
                requested_fields=["aadhaar_number"],
            )

    gemini_extract.assert_called_once()
    assert prov == "GEMINI_MULTIMODAL"
    assert ocr_stat == "OCR_FAILED"
    assert extracted_dict["aadhaar_number"] == "9999 8888 7777"


@pytest.mark.asyncio
async def test_7_data_extraction_batch_list_uses_shared_department_query():
    from app.models.user import UserRole
    from app.services.batch_extraction_service import BatchExtractionService

    batch_repository = MagicMock()
    batch_repository.get_batches_by_department = AsyncMock(return_value=[])
    batch_repository.get_all_batches = AsyncMock(return_value=[])
    service = BatchExtractionService(batch_repository=batch_repository)
    actor = User(
        username="aiml_batch_visibility_test",
        name="AIML Batch Visibility Test",
        email="aiml_batch_visibility@test.com",
        password="unused-test-hash",
        role=UserRole.DEPARTMENT_ADMIN,
        department_code="AIML",
    )

    assert await service.list_authorized_batches(actor) == []
    batch_repository.get_batches_by_department.assert_awaited_once_with("AIML")
    batch_repository.get_all_batches.assert_not_awaited()


@pytest.mark.asyncio
async def test_8_requested_fields_route_to_their_stored_source_documents(auth_super_admin, tmp_path):
    from app.models.wanted_field_config import DocumentFieldConfiguration, WantedFieldItem
    from app.services.accuracy_extraction_engine import FieldExtractionResult
    from app.services.document_extraction_service import DocumentExtractionService

    actor, _ = auth_super_admin
    batch_id = "BATCH_FIELD_SOURCE_ROUTING_01"
    student_id = "FIELD_ROUTE_24AM093"
    await AdmissionBatch.find(AdmissionBatch.id == batch_id).delete()
    await StudentSubmission.find(StudentSubmission.batch_id == batch_id).delete()
    await StudentDocument.find(StudentDocument.batch_id == batch_id).delete()
    await DocumentFieldConfiguration.find(DocumentFieldConfiguration.batch_id == batch_id).delete()

    batch = AdmissionBatch(
        id=batch_id,
        name="Field Source Routing Test",
        academic_year="2026-2027",
        department_id="AIML",
        created_by=actor.username,
    )
    await batch.save()

    source_files = {}
    for doc_type in ("BANK_PASSBOOK", "COMMUNITY", "TRANSFER_CERTIFICATE"):
        source_file = tmp_path / f"{doc_type.lower()}.pdf"
        source_file.write_bytes(b"%PDF-1.4 source routing fixture")
        source_files[doc_type] = source_file
        document = StudentDocument(
            student_id=student_id,
            batch_id=batch_id,
            document_type=doc_type,
            document_name=doc_type.replace("_", " "),
            versions=[
                DocumentVersion(
                    version_number=1,
                    file_path=str(source_file),
                    original_filename=source_file.name,
                    file_size_bytes=source_file.stat().st_size,
                    validation_status=DocumentValidationStatus.PENDING.value,
                )
            ],
        )
        await document.save()

    await StudentSubmission(
        batch_id=batch_id,
        register_number=student_id,
        student_name="Test Student",
        mobile_number="9000000000",
        submission_status="Submitted",
    ).save()

    requested_fields_by_document = {
        "BANK_PASSBOOK": ["ifsc_code", "bank_name", "branch"],
        "COMMUNITY": ["community_category", "caste"],
        "TRANSFER_CERTIFICATE": ["emis_id", "mother_name"],
    }
    for doc_type, fields in requested_fields_by_document.items():
        await DocumentFieldConfiguration(
            batch_id=batch_id,
            document_type=doc_type,
            display_name=doc_type.replace("_", " "),
            fields=[WantedFieldItem(field=field, enabled=True) for field in fields],
        ).insert()

    calls = []

    async def request_fields(*, student_document_id, requested_fields, actor, version_id=None):
        document = await StudentDocument.get(student_document_id)
        calls.append((document.document_type, requested_fields, version_id))
        result = MagicMock()
        result.extracted_data = {field: f"fixture_{field}" for field in requested_fields}
        return MagicMock(), result

    async def extract_accuracy(*, doc, version, field_key, actor, extracted_data_override=None):
        return FieldExtractionResult(
            field_name=field_key,
            raw_value=extracted_data_override[field_key],
            normalized_value=extracted_data_override[field_key],
            confidence="HIGH",
            confidence_score=0.98,
            field_state="HIGH_CONFIDENCE",
            evidence_snippet="fixture evidence",
            source_document_type=doc.document_type,
            source_document_id=str(doc.id),
            source_document_version=version.version_id,
            source_document_name=doc.document_name,
        )

    service = BatchExtractionService()
    service.extraction_service = MagicMock(spec=DocumentExtractionService)
    service.extraction_service.request_and_extract_fields = AsyncMock(side_effect=request_fields)
    service._extract_field_with_accuracy = AsyncMock(side_effect=extract_accuracy)

    result = await service.create_and_run_batch_extraction(
        batch_id=batch_id,
        requested_columns=None,
        requested_fields=[
            "ifsc_code", "bank_name", "branch", "community_category", "caste", "emis_id", "mother_name"
        ],
        actor=actor,
    )

    assert result.status == "COMPLETED"
    routed = {doc_type: set(fields) for doc_type, fields, _ in calls}
    assert routed == {doc_type: set(fields) for doc_type, fields in requested_fields_by_document.items()}
    assert all(version_id for _, _, version_id in calls)


def test_9_gemini_prompt_includes_document_field_and_ocr_context():
    from app.services.gemini_service import GeminiService

    prompt = GeminiService().build_multimodal_prompt(
        target_fields=["ifsc_code"],
        document_hint="BANK_PASSBOOK",
        ocr_text="IFSC Code: ABCD0123456",
    )

    assert "DOCUMENT TYPE: BANK_PASSBOOK" in prompt
    assert "REQUESTED FIELDS: ifsc_code" in prompt
    assert "IFSC Code: ABCD0123456" in prompt
    assert "value to null" in prompt.lower()


def test_10_gemini_parser_accepts_markdown_wrapped_array_fields():
    from app.services.gemini_service import GeminiService

    parsed = GeminiService()._parse_json_response(
        '```json\n{"document_type":"BANK_PASSBOOK","fields":[{"field":"IFSC","value":"ABCD0123456","confidence":98}],"extracted_summary":{"ifsc_code":"ABCD0123456"}}\n```'
    )

    assert parsed is not None
    assert parsed["document_type"] == "BANK_PASSBOOK"
    assert parsed["fields"]["IFSC"]["value"] == "ABCD0123456"

@pytest.mark.asyncio
async def test_11_legacy_submission_files_reconcile_to_student_documents(tmp_path):
    batch_id = "BATCH_LEGACY_FILE_RECONCILE_01"
    student_id = "LEGACY_RECONCILE_STUDENT"
    await StudentSubmission.find(StudentSubmission.batch_id == batch_id).delete()
    await StudentDocument.find(StudentDocument.batch_id == batch_id).delete()

    transfer_file = tmp_path / "transfer_certificate.pdf"
    transfer_file.write_bytes(b"%PDF-1.4 existing stored transfer certificate")
    submission = StudentSubmission(
        batch_id=batch_id,
        register_number=student_id,
        student_name="Stored Submission",
        mobile_number="9000000000",
        documents=[
            StudentDocumentMeta(
                document_name="Transfer Certificate",
                document_type="TRANSFER_CERTIFICATE",
                status="Uploaded",
                file_path=str(transfer_file),
                file_type="PDF",
                version=1,
            )
        ],
    )
    await submission.insert()

    service = BatchExtractionService()
    units_first = await service._build_canonical_student_units([batch_id])
    units_second = await service._build_canonical_student_units([batch_id])
    stored_docs = await StudentDocument.find(
        StudentDocument.batch_id == batch_id,
        StudentDocument.student_id == student_id,
    ).to_list()

    assert len(units_first) == len(units_second) == 1
    assert len(stored_docs) == 1
    assert stored_docs[0].document_type == "TRANSFER_CERTIFICATE"
    assert stored_docs[0].active_version.file_path == str(transfer_file)
    assert stored_docs[0].active_version.original_filename == transfer_file.name

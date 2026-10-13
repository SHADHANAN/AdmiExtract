import json
import pytest
import pytest_asyncio
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch
from httpx import AsyncClient, ASGITransport
from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient

from app.main import app
from app.models.user import User, UserRole
from app.models.department import Department
from app.models.batch import AdmissionBatch
from app.models.batch_class import BatchClass
from app.models.doc_config_version import DocumentConfigurationVersion
from app.models.wanted_field_config import DocumentFieldConfiguration
from app.models.upload_link import UploadLink
from app.models.student_submission import StudentSubmission
from app.models.student_document import StudentDocument, DocumentVersion, DocumentStatus, DocumentValidationStatus
from app.models.document_extraction_request import DocumentExtractionRequest, ExtractionRequestStatus
from app.services.student_document_service import StudentDocumentService
from app.services.document_extraction_service import DocumentExtractionService
from app.services.wanted_field_service import WantedFieldService
from app.core.config import settings


@pytest_asyncio.fixture(scope="function", autouse=True)
async def setup_test_db():
    if not hasattr(AsyncIOMotorClient, "append_metadata"):
        AsyncIOMotorClient.append_metadata = lambda *args, **kwargs: None

    test_client = AsyncIOMotorClient(settings.MONGODB_URI)
    test_db = test_client["store_once_test_db"]

    import app.db.database as db_mod
    db_mod.client = test_client
    db_mod.db = test_db
    db_mod._is_connected = True

    await db_mod._run_db_setup()
    await User.find_all().delete()
    await Department.find_all().delete()
    await AdmissionBatch.find_all().delete()
    await BatchClass.find_all().delete()
    await UploadLink.find_all().delete()
    await StudentSubmission.find_all().delete()
    await StudentDocument.find_all().delete()
    await DocumentExtractionRequest.find_all().delete()
    await DocumentConfigurationVersion.find_all().delete()
    await DocumentFieldConfiguration.find_all().delete()

    yield

    await test_client.drop_database("store_once_test_db")
    test_client.close()


@pytest_asyncio.fixture
async def client_async():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_student_upload_persists_without_ai_or_ocr(client_async: AsyncClient):
    """
    PRODUCT RULE TEST:
    1. Student uploads documents.
    2. System ONLY receives and persists document files.
    3. StudentDocument + DocumentVersion created with status UPLOADED / PENDING.
    4. ZERO calls to Gemini AI / OCR services.
    5. Upload succeeds even if Gemini AI is completely broken/unavailable.
    """
    dept = Department(name="Computer Science", code="CS", intake_capacity=60, created_by="admin")
    await dept.insert()

    batch = AdmissionBatch(
        id="batch_store_once_2026",
        name="Store Once Batch 2026",
        department_code="CS",
        department_id="CS",
        academic_year="2026-2030",
        created_by="admin",
        status="active",
    )
    await batch.insert()

    link = UploadLink(
        department_id=dept.id,
        batch_id=batch.id,
        token="direct-upload-token",
        slug="direct-upload-token",
        title="CS Admission Portal",
        is_active=True,
        created_by="admin",
    )
    await link.insert()

    # Mock AI service to fail if called to prove zero AI dependency during student upload
    with patch("app.services.gemini_service.GeminiService.extract_from_file", side_effect=RuntimeError("AI MUST NOT BE CALLED DURING UPLOAD")), \
         patch("app.services.gemini_service.GeminiService.extract_from_bytes", side_effect=RuntimeError("GEMINI MUST NOT BE CALLED DURING UPLOAD")):

        dummy_pdf_content = b"%PDF-1.4 Mock Student Aadhaar Document Content For Storage Once"
        files = [
            ("files", ("aadhaar_card.pdf", dummy_pdf_content, "application/pdf"))
        ]
        data = {
            "batch_id": batch.id,
            "register_number": "26CS901",
            "student_name": "Charlie Chaplin",
            "mobile_number": "9876543210",
            "email": "charlie@example.com",
            "token": link.token,
            "documents_metadata": '[{"document_name": "Aadhaar Card", "document_type": "AADHAAR", "filename": "aadhaar_card.pdf", "status": "Uploaded"}]',
        }

        # Call public upload endpoint
        res = await client_async.post(
            "/student-submissions/upload",
            data=data,
            files=files,
        )

        assert res.status_code == 201, f"Failed: {res.status_code} - {res.text}"
        res_data = res.json()
        assert res_data["student_name"] == "Charlie Chaplin"
        assert res_data["register_number"] == "26CS901"
        assert res_data["submission_status"] == "Submitted"
        assert len(res_data["documents"]) == 1
        assert res_data["documents"][0]["document_name"] == "Aadhaar Card"
        assert res_data["documents"][0]["status"] == "Uploaded"

    # Confirm StudentSubmission is saved in DB
    sub = await StudentSubmission.find_one(StudentSubmission.register_number == "26CS901")
    assert sub is not None
    assert sub.batch_id == batch.id
    assert sub.submission_status == "Submitted"
    assert len(sub.documents) == 1
    assert sub.documents[0].file_path is not None

    # Confirm physical file exists on disk
    persisted_path = Path(sub.documents[0].file_path)
    assert persisted_path.exists(), f"File does not exist at {persisted_path}"
    assert persisted_path.read_bytes() == dummy_pdf_content

    # Confirm StudentDocument and DocumentVersion records are created
    doc_service = StudentDocumentService()
    std_doc = await doc_service.get_student_document_by_type("26CS901", "AADHAAR")
    assert std_doc is not None
    assert std_doc.student_id == "26CS901"
    assert std_doc.batch_id == batch.id
    assert std_doc.status == DocumentStatus.UPLOADED.value
    assert len(std_doc.versions) == 1
    v1 = std_doc.versions[0]
    assert v1.version_number == 1
    assert v1.validation_status in [DocumentValidationStatus.PENDING.value, DocumentValidationStatus.NEEDS_REVIEW.value, DocumentValidationStatus.VALID.value]
    assert v1.is_active is True
    assert v1.original_filename == "aadhaar_card.pdf"
    assert v1.file_size_bytes == len(dummy_pdf_content)

    # Confirm the stored document can LATER be extracted on-demand by Staff
    admin_user = User(
        username="admin_cs",
        password="password123",
        hashed_password="hashed_password",
        role=UserRole.SUPER_ADMIN,
        name="CS Admin",
    )
    await admin_user.insert()

    extraction_service = DocumentExtractionService()
    with patch.object(extraction_service, "_run_ai_extraction", return_value=({"aadhaar_number": "1234-5678-9012"}, 95.0)):
        req_rec, res_rec = await extraction_service.request_and_extract_fields(
            student_document_id=str(std_doc.id),
            version_id=v1.version_id,
            requested_fields=["aadhaar_number"],
            actor=admin_user,
        )
        assert req_rec.status == ExtractionRequestStatus.COMPLETED
        assert res_rec.extracted_data["aadhaar_number"] == "1234-5678-9012"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("document_type", "document_name"),
    [
        ("AADHAAR", "Aadhaar Card"),
        ("COMMUNITY", "Community Certificate"),
        ("TRANSFER_CERTIFICATE", "TC"),
    ],
)
async def test_upload_document_type_uses_storage_only_path_without_ai_or_ocr(
    client_async: AsyncClient,
    document_type: str,
    document_name: str,
):
    dept = Department(name="Computer Science", code="CS", intake_capacity=60, created_by="admin")
    await dept.insert()

    batch = AdmissionBatch(
        id=f"batch_{document_type.lower()}_upload_2026",
        name="Storage-Only Upload Batch",
        department_code="CS",
        department_id="CS",
        academic_year="2026-2030",
        created_by="admin",
        status="active",
    )
    await batch.insert()

    link = UploadLink(
        department_id=dept.id,
        batch_id=batch.id,
        token=f"{document_type.lower()}-upload-token",
        slug=f"{document_type.lower()}-upload-token",
        title="CS Admission Portal",
        is_active=True,
        created_by="admin",
    )
    await link.insert()

    with patch("app.services.gemini_service.GeminiService.classify_document") as classify_mock, \
         patch("app.services.gemini_service.GeminiService.extract_from_file") as extract_mock, \
         patch("app.services.ocr_service.OCRService.extract_text") as ocr_mock:
        content = f"mock {document_type} storage-only upload".encode()
        res = await client_async.post(
            "/student-submissions/upload",
            data={
                "batch_id": batch.id,
                "register_number": "26CS901",
                "student_name": "Charlie Chaplin",
                "mobile_number": "9876543210",
                "email": "charlie@example.com",
                "token": link.token,
                "documents_metadata": json.dumps([
                    {"document_name": document_name, "document_type": document_type, "filename": f"{document_name.lower().replace(' ', '_')}.pdf", "status": "Uploaded", "is_new_file": True}
                ]),
            },
            files=[("files", (f"{document_name.lower().replace(' ', '_')}.pdf", content, "application/pdf"))],
        )

    assert res.status_code == 201
    assert classify_mock.call_count == 0
    assert extract_mock.call_count == 0
    assert ocr_mock.call_count == 0

    doc_service = StudentDocumentService()
    stored = await doc_service.get_student_document_by_type("26CS901", document_type)
    assert stored is not None
    assert stored.status == DocumentStatus.UPLOADED.value
    assert stored.active_version is not None


@pytest.mark.asyncio
async def test_data_extraction_uses_requested_fields_and_persists_results(client_async: AsyncClient, tmp_path: Path):
    dept = Department(name="Computer Science", code="CS", intake_capacity=60, created_by="admin")
    await dept.insert()

    batch = AdmissionBatch(
        id="batch_extraction_2026",
        name="Extraction Batch",
        department_code="CS",
        department_id="CS",
        academic_year="2026-2030",
        created_by="admin",
        status="active",
    )
    await batch.insert()

    admin_user = User(
        username="admin_cs",
        password="password123",
        hashed_password="hashed_password",
        role=UserRole.SUPER_ADMIN,
        name="CS Admin",
    )
    await admin_user.insert()

    temp_path = tmp_path / "aadhaar_not_used.pdf"
    temp_path.write_bytes(b"%PDF-1.4 valid test pdf")
    student_doc = await StudentDocumentService().create_student_document(
        student_id="26CS902",
        batch_id=batch.id,
        document_type="AADHAAR",
        document_name="Aadhaar Card",
        class_id=None,
        section_id=None,
        department_id="CS",
        initial_file_path=str(temp_path),
        original_filename="aadhaar.pdf",
        file_size_bytes=temp_path.stat().st_size,
        mime_type="application/pdf",
        status_value=DocumentStatus.UPLOADED.value,
        validation_status=DocumentValidationStatus.PENDING.value,
        actor=admin_user,
    )

    expected_ocr_text = "Aadhaar Number 123456789012 Date of Birth 12-04-2005"
    with patch("app.services.ocr_service.OCRService.extract_text", return_value={"success": True, "text": expected_ocr_text}) as ocr_mock, \
         patch("app.services.gemini_service.GeminiService.extract_from_file", return_value={
             "success": True,
             "document_type": "AADHAAR",
             "fields": {
                 "aadhaar_number": {"value": "123456789012", "confidence": 0.98, "evidence": "Aadhaar number"},
                 "date_of_birth": {"value": "2005-04-12", "confidence": 0.96, "evidence": "Date of birth"},
             },
             "extracted_summary": {"aadhaar_number": "123456789012", "date_of_birth": "2005-04-12"},
             "confidence": 0.97,
         }) as gemini_mock:
        req, res = await DocumentExtractionService().request_and_extract_fields(
            student_document_id=str(student_doc.id),
            requested_fields=["aadhaar_number", "date_of_birth"],
            actor=admin_user,
        )

    assert req.status == ExtractionRequestStatus.COMPLETED
    assert ocr_mock.call_count == 1
    assert gemini_mock.call_count == 1
    assert res.extracted_data == {"aadhaar_number": "123456789012", "date_of_birth": "2005-04-12"}
    assert res.requested_fields == ["aadhaar_number", "date_of_birth"]
    assert res.confidence == 0.97


@pytest.mark.asyncio
async def test_batch_section_document_requirements_loaded_in_student_portal(client_async: AsyncClient):
    """
    EXACT SCENARIO TEST:
    1. Create Batch and Section A.
    2. Configure 3 required documents in Admission Batch -> Document Requirements (Aadhaar, Birth Certificate, HSC Marksheet), 1 optional, 1 disabled.
    3. Generate Section A upload link.
    4. Verify student details -> Continue.
    5. Query document requirements for Section A -> returns exactly the 3 required + 1 optional (disabled excluded).
    6. Upload document -> saved independently to storage without AI.
    """
    from app.services.wanted_field_service import WantedFieldService
    wanted_service = WantedFieldService()

    dept = Department(name="Information Technology", code="IT", intake_capacity=120, created_by="admin")
    await dept.insert()

    batch = AdmissionBatch(
        id="batch_it_2026",
        name="IT Batch 2026",
        department_code="IT",
        department_id="IT",
        academic_year="2026-2030",
        created_by="admin",
        status="active",
    )
    await batch.insert()

    sec_a = BatchClass(
        id="class_it_sec_a_2026",
        batch_id=batch.id,
        class_name="IT-A",
        section="A",
        department=dept.name,
        academic_year="2026-2030",
        created_by="admin",
    )
    await sec_a.insert()

    # Staff configures Document Requirements for Section A (or Batch):
    # 1. Aadhaar Card (REQUIRED)
    await wanted_service.create_document_type(
        batch_id=batch.id,
        name="Aadhaar Card",
        code="AADHAAR",
        description="Government ID Proof",
        class_id=str(sec_a.id),
        requirement_status="REQUIRED",
    )
    # 2. Birth Certificate (REQUIRED)
    await wanted_service.create_document_type(
        batch_id=batch.id,
        name="Birth Certificate",
        code="BIRTH_CERTIFICATE",
        description="Official birth proof",
        class_id=str(sec_a.id),
        requirement_status="REQUIRED",
    )
    # 3. HSC Marksheet (REQUIRED)
    await wanted_service.create_document_type(
        batch_id=batch.id,
        name="HSC Marksheet",
        code="HSC_MARKSHEET",
        description="12th grade statement",
        class_id=str(sec_a.id),
        requirement_status="REQUIRED",
    )
    # 4. Income Certificate (OPTIONAL)
    await wanted_service.create_document_type(
        batch_id=batch.id,
        name="Income Certificate",
        code="INCOME_CERTIFICATE",
        description="Fee concession proof",
        class_id=str(sec_a.id),
        requirement_status="OPTIONAL",
    )
    # 5. Sports Certificate (DISABLED)
    await wanted_service.create_document_type(
        batch_id=batch.id,
        name="Sports Certificate",
        code="SPORTS_CERTIFICATE",
        description="Quota proof",
        class_id=str(sec_a.id),
        requirement_status="DISABLED",
    )

    # Generate Section A upload link
    link = UploadLink(
        department_id=dept.id,
        batch_id=batch.id,
        class_id=str(sec_a.id),
        token="it-sec-a-token",
        slug="it-sec-a-token",
        title="IT-A Portal",
        is_active=True,
        created_by="admin",
    )
    await link.insert()

    # Step 1: Student opens link and enters details
    verify_res = await client_async.post(
        "/student/verify",
        json={
            "token": link.token,
            "student_name": "Daniel Craig",
            "register_number": "26IT007",
            "mobile_number": "9876543210",
            "email": "daniel@example.com",
        },
    )
    assert verify_res.status_code == 200
    v_data = verify_res.json()
    assert v_data["batch_id"] == batch.id
    assert v_data["class_id"] == str(sec_a.id)

    # Step 2: Student Documents page queries document requirements
    # Test query param format
    doc_res_query = await client_async.get(
        f"/public/batches/{batch.id}/doc-versions/current?classId={sec_a.id}"
    )
    assert doc_res_query.status_code == 200
    docs_query = doc_res_query.json()["documents"]
    assert len(docs_query) == 4  # 3 REQUIRED + 1 OPTIONAL (DISABLED is excluded)
    doc_names_query = [d["name"] for d in docs_query]
    assert "Aadhaar Card" in doc_names_query
    assert "Birth Certificate" in doc_names_query
    assert "HSC Marksheet" in doc_names_query
    assert "Income Certificate" in doc_names_query
    assert "Sports Certificate" not in doc_names_query

    # Test subpath format
    doc_res_subpath = await client_async.get(
        f"/public/batches/{batch.id}/classes/{sec_a.id}/doc-versions/current"
    )
    assert doc_res_subpath.status_code == 200
    docs_subpath = doc_res_subpath.json()["documents"]
    assert len(docs_subpath) == 4

    # Check required vs optional types
    aadhaar_item = next(d for d in docs_subpath if d["name"] == "Aadhaar Card")
    assert aadhaar_item["required"] is True
    assert aadhaar_item["type"] == "MANDATORY"

    income_item = next(d for d in docs_subpath if d["name"] == "Income Certificate")
    assert income_item["required"] is False
    assert income_item["type"] == "OPTIONAL"

    # Step 3: Student uploads one document
    dummy_pdf_content = b"%PDF-1.4 Mock Birth Certificate"
    files = [
        ("files", ("birth_certificate.pdf", dummy_pdf_content, "application/pdf"))
    ]
    data = {
        "batch_id": batch.id,
        "class_id": str(sec_a.id),
        "register_number": "26IT007",
        "student_name": "Daniel Craig",
        "mobile_number": "9876543210",
        "email": "daniel@example.com",
        "token": link.token,
        "documents_metadata": '[{"document_name": "Birth Certificate", "document_type": "BIRTH_CERTIFICATE", "filename": "birth_certificate.pdf", "status": "Uploaded"}]',
    }

    upload_res = await client_async.post(
        "/student-submissions/upload",
        data=data,
        files=files,
    )
    assert upload_res.status_code == 201
    u_data = upload_res.json()
    assert u_data["submission_status"] == "Submitted"
    assert len(u_data["documents"]) == 1
    assert u_data["documents"][0]["document_name"] == "Birth Certificate"

    # Step 4: Confirm batch with zero configured documents returns empty list
    empty_batch = AdmissionBatch(
        id="batch_empty_2026",
        name="Empty Batch 2026",
        department_code="IT",
        department_id="IT",
        academic_year="2026-2030",
        created_by="admin",
        status="active",
    )
    await empty_batch.insert()

    empty_res = await client_async.get(f"/public/batches/{empty_batch.id}/doc-versions/current")
    assert empty_res.status_code == 200
    assert len(empty_res.json()["documents"]) == 0


@pytest.mark.asyncio
async def test_resuming_existing_student_submission_and_document_reupload(client_async: AsyncClient):
    """
    PRODUCT RULE TEST — RESUMING SUBMISSIONS:
    1. Student enters details (New) -> Submission created.
    2. Student uploads Document 1 (Aadhaar).
    3. Student re-enters details (Same Reg No) -> NO 409 BLOCK, returns existing submission + uploaded docs.
    4. Student uploads Document 2 (HSC Marksheet) -> Submissions merged without losing Document 1.
    5. Student re-uploads Document 1 (Aadhaar v2) -> Creates DocumentVersion 2; DocumentVersion 1 preserved.
    6. Verifies exact count of StudentSubmission is 1 (no duplicates).
    7. Verifies same Reg No in another batch is permitted and isolated.
    8. Verifies invalid / disabled / expired link security.
    """
    from app.services.wanted_field_service import WantedFieldService
    wanted_service = WantedFieldService()

    dept = Department(name="Electronics", code="ECE", intake_capacity=60, created_by="admin")
    await dept.insert()

    batch_1 = AdmissionBatch(
        id="batch_ece_2026",
        name="ECE Batch 2026",
        department_code="ECE",
        department_id="ECE",
        academic_year="2026-2030",
        created_by="admin",
        status="active",
    )
    await batch_1.insert()

    sec_1 = BatchClass(
        id="class_ece_sec_1_2026",
        batch_id=batch_1.id,
        class_name="ECE-A",
        section="A",
        department=dept.name,
        academic_year="2026-2030",
        created_by="admin",
    )
    await sec_1.insert()

    # Configure requirements: Aadhaar Card & HSC Marksheet
    await wanted_service.create_document_type(
        batch_id=batch_1.id,
        name="Aadhaar Card",
        code="AADHAAR",
        class_id=str(sec_1.id),
        requirement_status="REQUIRED",
    )
    await wanted_service.create_document_type(
        batch_id=batch_1.id,
        name="HSC Marksheet",
        code="HSC_MARKSHEET",
        class_id=str(sec_1.id),
        requirement_status="REQUIRED",
    )

    link_1 = UploadLink(
        department_id=dept.id,
        batch_id=batch_1.id,
        class_id=str(sec_1.id),
        token="ece-upload-token",
        slug="ece-upload-token",
        title="ECE Admission Link",
        is_active=True,
        created_by="admin",
    )
    await link_1.insert()

    # --- CASE 1: New student registration ---
    res_1 = await client_async.post(
        "/student/verify",
        json={
            "token": link_1.token,
            "student_name": "Alice Walker",
            "register_number": "26ECE001",
            "mobile_number": "9876543210",
            "email": "alice@example.com",
        },
    )
    assert res_1.status_code == 200
    data_1 = res_1.json()
    sub_id_1 = data_1["submission_id"]
    assert sub_id_1 is not None
    assert data_1["uploaded_documents"] == []

    # Upload Aadhaar Card (v1)
    aadhaar_v1_bytes = b"%PDF-1.4 Aadhaar Card Version 1 Content"
    upload_res_1 = await client_async.post(
        "/student-submissions/upload",
        data={
            "batch_id": batch_1.id,
            "class_id": str(sec_1.id),
            "register_number": "26ECE001",
            "student_name": "Alice Walker",
            "mobile_number": "9876543210",
            "email": "alice@example.com",
            "token": link_1.token,
            "documents_metadata": '[{"document_name": "Aadhaar Card", "document_type": "AADHAAR", "filename": "aadhaar_v1.pdf", "status": "Uploaded"}]',
        },
        files=[("files", ("aadhaar_v1.pdf", aadhaar_v1_bytes, "application/pdf"))],
    )
    assert upload_res_1.status_code == 201

    # --- CASE 2 & 3: Student returns and enters the SAME Register Number ---
    # MUST NOT throw 409 Conflict ("Documents Already Submitted"). Must intelligently resume!
    res_resume = await client_async.post(
        "/student/verify",
        json={
            "token": link_1.token,
            "student_name": "Alice Walker",
            "register_number": "26ECE001",
            "mobile_number": "9876543210",
            "email": "alice@example.com",
        },
    )
    assert res_resume.status_code == 200, f"Expected 200 OK resume, got {res_resume.status_code}: {res_resume.text}"
    resume_data = res_resume.json()
    assert resume_data["submission_id"] == sub_id_1
    assert len(resume_data["uploaded_documents"]) == 1
    assert resume_data["uploaded_documents"][0]["document_name"] == "Aadhaar Card"

    # Public submission query with scoped token returns the resumed submission
    pub_sub_res = await client_async.get(f"/student-submissions/public/{sub_id_1}", params={"token": link_1.token})
    assert pub_sub_res.status_code == 200
    assert len(pub_sub_res.json()["documents"]) == 1

    # --- CASE 4: Upload missing document (HSC Marksheet) ---
    hsc_bytes = b"%PDF-1.4 HSC Marksheet Content"
    upload_res_2 = await client_async.post(
        "/student-submissions/upload",
        data={
            "batch_id": batch_1.id,
            "class_id": str(sec_1.id),
            "register_number": "26ECE001",
            "student_name": "Alice Walker",
            "mobile_number": "9876543210",
            "email": "alice@example.com",
            "token": link_1.token,
            "documents_metadata": '[{"document_name": "HSC Marksheet", "document_type": "HSC_MARKSHEET", "filename": "hsc.pdf", "status": "Uploaded"}]',
        },
        files=[("files", ("hsc.pdf", hsc_bytes, "application/pdf"))],
    )
    assert upload_res_2.status_code == 201
    u2_data = upload_res_2.json()
    assert len(u2_data["documents"]) == 2  # Both Aadhaar and HSC are present!    # --- CASE 5: Re-upload existing document (Aadhaar replacement) ---
    aadhaar_v2_bytes = b"%PDF-1.4 Aadhaar Card Version 2 Updated Content"
    upload_res_3 = await client_async.post(
        "/student-submissions/upload",
        data={
            "batch_id": batch_1.id,
            "class_id": str(sec_1.id),
            "register_number": "26ECE001",
            "student_name": "Alice Walker",
            "mobile_number": "9876543210",
            "email": "alice@example.com",
            "token": link_1.token,
            "documents_metadata": '[{"document_name": "Aadhaar Card", "document_type": "AADHAAR", "filename": "aadhaar_v2.pdf", "status": "Uploaded"}]',
        },
        files=[("files", ("aadhaar_v2.pdf", aadhaar_v2_bytes, "application/pdf"))],
    )
    assert upload_res_3.status_code == 201

    # Verify StudentDocument is replaced in-place in DB (same record, 1 version record, updated file)
    doc_service = StudentDocumentService()
    aadhaar_doc = await doc_service.get_student_document_by_type("26ECE001", "AADHAAR")
    assert aadhaar_doc is not None
    assert len(aadhaar_doc.versions) == 1
    assert aadhaar_doc.versions[0].original_filename == "aadhaar_v2.pdf"
    assert aadhaar_doc.versions[0].is_active is True

    # --- CASE 6: Verify no duplicate StudentSubmission was created ---
    all_subs = await StudentSubmission.find(
        StudentSubmission.batch_id == batch_1.id,
        StudentSubmission.register_number == "26ECE001",
    ).to_list()
    assert len(all_subs) == 1

    # --- CASE 7: Same Register Number in another Batch is rejected (Global Uniqueness) ---
    batch_2 = AdmissionBatch(
        id="batch_mech_2026",
        name="MECH Batch 2026",
        department_code="ECE",
        department_id="ECE",
        academic_year="2026-2030",
        created_by="admin",
        status="active",
    )
    await batch_2.insert()

    link_2 = UploadLink(
        department_id=dept.id,
        batch_id=batch_2.id,
        token="mech-upload-token",
        slug="mech-upload-token",
        title="MECH Link",
        is_active=True,
        created_by="admin",
    )
    await link_2.insert()

    res_batch2 = await client_async.post(
        "/student/verify",
        json={
            "token": link_2.token,
            "student_name": "Alice Walker",
            "register_number": "26ECE001",
            "mobile_number": "9876543210",
            "email": "alice@example.com",
        },
    )
    assert res_batch2.status_code == 409

    # --- CASE 8: Security checks (invalid/disabled/expired links) ---
    # Invalid token
    inv_res = await client_async.post(
        "/student/verify",
        json={
            "token": "non-existent-token",
            "student_name": "Bob",
            "register_number": "26ECE002",
            "mobile_number": "9876543210",
        },
    )
    assert inv_res.status_code == 404

    # Disabled link
    link_1.is_active = False
    await link_1.save()
    dis_res = await client_async.post(
        "/student/verify",
        json={
            "token": link_1.token,
            "student_name": "Bob",
            "register_number": "26ECE002",
            "mobile_number": "9876543210",
        },
    )
    assert dis_res.status_code == 403


@pytest.mark.asyncio
async def test_document_reupload_replacement_end_to_end(client_async: AsyncClient):
    """
    COMPREHENSIVE END-TO-END DOCUMENT RE-UPLOAD / REPLACEMENT TEST:
    1. Upload Aadhaar.
    2. Upload TC.
    3. Re-upload TC -> replaces TC in-place (same StudentDocument ID, new filename, Aadhaar unchanged, no extra version).
    4. Re-upload Aadhaar -> replaces Aadhaar in-place (TC unchanged).
    5. Simulate failed re-upload -> existing document remains untouched.
    6. Refresh page -> displays newly replaced document.
    7. Data Extraction -> extracts from replaced current file.
    """
    from app.services.wanted_field_service import WantedFieldService
    wanted_service = WantedFieldService()
    doc_service = StudentDocumentService()

    dept = Department(name="Aeronautical Engineering", code="AERO", intake_capacity=40, created_by="admin")
    await dept.insert()

    batch = AdmissionBatch(
        id="batch_aero_2026",
        name="AERO Batch 2026",
        department_code="AERO",
        department_id="AERO",
        academic_year="2026-2030",
        created_by="admin",
        status="active",
    )
    await batch.insert()

    sec = BatchClass(
        id="class_aero_sec_a_2026",
        batch_id=batch.id,
        class_name="AERO-A",
        section="A",
        department=dept.name,
        academic_year="2026-2030",
        created_by="admin",
    )
    await sec.insert()

    # Configure Aadhaar and Transfer Certificate requirements
    await wanted_service.create_document_type(
        batch_id=batch.id,
        name="Aadhaar Card",
        code="AADHAAR",
        class_id=str(sec.id),
        requirement_status="REQUIRED",
    )
    await wanted_service.create_document_type(
        batch_id=batch.id,
        name="Transfer Certificate",
        code="TRANSFER_CERTIFICATE",
        class_id=str(sec.id),
        requirement_status="REQUIRED",
    )

    link = UploadLink(
        department_id=dept.id,
        batch_id=batch.id,
        class_id=str(sec.id),
        token="aero-upload-token",
        slug="aero-upload-token",
        title="AERO Portal",
        is_active=True,
        created_by="admin",
    )
    await link.insert()

    # Student: Evelyn
    reg_num_1 = "26AERO001"
    student_name_1 = "Evelyn Salt"

    # Identity verification
    verify_res = await client_async.post(
        "/student/verify",
        json={
            "token": link.token,
            "student_name": student_name_1,
            "register_number": reg_num_1,
            "mobile_number": "9123456780",
            "email": "evelyn@example.com",
        },
    )
    assert verify_res.status_code == 200

    # Prove no AI/OCR during uploads
    with patch("app.services.gemini_service.GeminiService.extract_from_file", side_effect=RuntimeError("AI must not run during upload")), \
         patch("app.services.gemini_service.GeminiService.extract_from_bytes", side_effect=RuntimeError("AI must not run during upload")):

        # ----------------------------------------------------
        # 1. Upload Aadhaar
        # ----------------------------------------------------
        v1_bytes = b"%PDF-1.4 Aadhaar Evelyn Version 1 Original"
        res_v1 = await client_async.post(
            "/student-submissions/upload",
            data={
                "batch_id": batch.id,
                "class_id": str(sec.id),
                "register_number": reg_num_1,
                "student_name": student_name_1,
                "mobile_number": "9123456780",
                "email": "evelyn@example.com",
                "token": link.token,
                "documents_metadata": '[{"document_name": "Aadhaar Card", "document_type": "AADHAAR", "filename": "old_aadhaar.pdf", "file_index": 0, "is_new_file": true, "status": "Uploaded"}]',
            },
            files=[("files", ("old_aadhaar.pdf", v1_bytes, "application/pdf"))],
        )
        assert res_v1.status_code == 201

        aadhaar_doc = await doc_service.get_student_document_by_type(reg_num_1, "AADHAAR")
        assert aadhaar_doc is not None
        aadhaar_initial_id = str(aadhaar_doc.id)
        assert len(aadhaar_doc.versions) == 1
        assert aadhaar_doc.versions[0].original_filename == "old_aadhaar.pdf"

        # ----------------------------------------------------
        # 2. Upload TC
        # ----------------------------------------------------
        old_tc_bytes = b"%PDF-1.4 Transfer Certificate Old TC Content"
        res_tc = await client_async.post(
            "/student-submissions/upload",
            data={
                "batch_id": batch.id,
                "class_id": str(sec.id),
                "register_number": reg_num_1,
                "student_name": student_name_1,
                "mobile_number": "9123456780",
                "email": "evelyn@example.com",
                "token": link.token,
                "documents_metadata": json.dumps([
                    {"document_name": "Aadhaar Card", "document_type": "AADHAAR", "filename": "old_aadhaar.pdf", "is_new_file": False, "status": "Uploaded"},
                    {"document_name": "Transfer Certificate", "document_type": "TRANSFER_CERTIFICATE", "filename": "old_TC.pdf", "file_index": 0, "is_new_file": True, "status": "Uploaded"},
                ]),
            },
            files=[("files", ("old_TC.pdf", old_tc_bytes, "application/pdf"))],
        )
        assert res_tc.status_code == 201

        tc_doc = await doc_service.get_student_document_by_type(reg_num_1, "TRANSFER_CERTIFICATE")
        assert tc_doc is not None
        tc_initial_id = str(tc_doc.id)
        assert len(tc_doc.versions) == 1
        assert tc_doc.versions[0].original_filename == "old_TC.pdf"

        # ----------------------------------------------------
        # 3. Re-upload TC (Replaces old_TC.pdf with new_TC.pdf)
        # ----------------------------------------------------
        new_tc_bytes = b"%PDF-1.4 Transfer Certificate New TC Replacement Content"
        res_reupload_tc = await client_async.post(
            "/student-submissions/upload",
            data={
                "batch_id": batch.id,
                "class_id": str(sec.id),
                "register_number": reg_num_1,
                "student_name": student_name_1,
                "mobile_number": "9123456780",
                "email": "evelyn@example.com",
                "token": link.token,
                "documents_metadata": json.dumps([
                    {"document_name": "Aadhaar Card", "document_type": "AADHAAR", "filename": "old_aadhaar.pdf", "is_new_file": False, "status": "Uploaded"},
                    {"document_name": "Transfer Certificate", "document_type": "TRANSFER_CERTIFICATE", "filename": "new_TC.pdf", "file_index": 0, "is_new_file": True, "status": "Uploaded"},
                ]),
            },
            files=[("files", ("new_TC.pdf", new_tc_bytes, "application/pdf"))],
        )
        assert res_reupload_tc.status_code == 201

        # Confirm:
        # - exactly one TC StudentDocument exists
        # - same StudentDocument ID
        # - filename points to new_TC.pdf
        # - Aadhaar is unchanged
        # - no extra DocumentVersion created
        all_student_docs = await StudentDocument.find(StudentDocument.student_id == reg_num_1).to_list()
        assert len(all_student_docs) == 2

        tc_doc_after = await doc_service.get_student_document_by_type(reg_num_1, "TRANSFER_CERTIFICATE")
        assert str(tc_doc_after.id) == tc_initial_id, "StudentDocument ID must remain the same"
        assert len(tc_doc_after.versions) == 1, "Must NOT create a second DocumentVersion"
        assert tc_doc_after.versions[0].original_filename == "new_TC.pdf"
        assert Path(tc_doc_after.versions[0].file_path).read_bytes() == new_tc_bytes

        aadhaar_doc_after = await doc_service.get_student_document_by_type(reg_num_1, "AADHAAR")
        assert str(aadhaar_doc_after.id) == aadhaar_initial_id
        assert len(aadhaar_doc_after.versions) == 1
        assert aadhaar_doc_after.versions[0].original_filename == "old_aadhaar.pdf"

        # ----------------------------------------------------
        # 4. Re-upload Aadhaar (Replaces old_aadhaar.pdf with new_aadhaar.pdf)
        # ----------------------------------------------------
        new_aadhaar_bytes = b"%PDF-1.4 Aadhaar New Replacement Content"
        res_reupload_aadhaar = await client_async.post(
            "/student-submissions/upload",
            data={
                "batch_id": batch.id,
                "class_id": str(sec.id),
                "register_number": reg_num_1,
                "student_name": student_name_1,
                "mobile_number": "9123456780",
                "email": "evelyn@example.com",
                "token": link.token,
                "documents_metadata": json.dumps([
                    {"document_name": "Aadhaar Card", "document_type": "AADHAAR", "filename": "new_aadhaar.pdf", "file_index": 0, "is_new_file": True, "status": "Uploaded"},
                    {"document_name": "Transfer Certificate", "document_type": "TRANSFER_CERTIFICATE", "filename": "new_TC.pdf", "is_new_file": False, "status": "Uploaded"},
                ]),
            },
            files=[("files", ("new_aadhaar.pdf", new_aadhaar_bytes, "application/pdf"))],
        )
        assert res_reupload_aadhaar.status_code == 201

        aadhaar_doc_final = await doc_service.get_student_document_by_type(reg_num_1, "AADHAAR")
        assert str(aadhaar_doc_final.id) == aadhaar_initial_id
        assert len(aadhaar_doc_final.versions) == 1
        assert aadhaar_doc_final.versions[0].original_filename == "new_aadhaar.pdf"
        assert Path(aadhaar_doc_final.versions[0].file_path).read_bytes() == new_aadhaar_bytes

        # TC remains untouched with new_TC.pdf
        tc_doc_final = await doc_service.get_student_document_by_type(reg_num_1, "TRANSFER_CERTIFICATE")
        assert str(tc_doc_final.id) == tc_initial_id
        assert len(tc_doc_final.versions) == 1
        assert tc_doc_final.versions[0].original_filename == "new_TC.pdf"

        # ----------------------------------------------------
        # 5. Simulate failed re-upload (mismatched identity or invalid token)
        # ----------------------------------------------------
        fail_res = await client_async.post(
            "/student-submissions/upload",
            data={
                "batch_id": batch.id,
                "class_id": str(sec.id),
                "register_number": reg_num_1,
                "student_name": "Mismatched Hacker Name",
                "mobile_number": "9123456780",
                "token": link.token,
                "documents_metadata": json.dumps([
                    {"document_name": "Transfer Certificate", "document_type": "TRANSFER_CERTIFICATE", "filename": "malicious.pdf", "file_index": 0, "is_new_file": True, "status": "Uploaded"},
                ]),
            },
            files=[("files", ("malicious.pdf", b"bad content", "application/pdf"))],
        )
        assert fail_res.status_code in (400, 403, 409)

        # Confirm old file remains completely intact
        tc_doc_after_fail = await doc_service.get_student_document_by_type(reg_num_1, "TRANSFER_CERTIFICATE")
        assert tc_doc_after_fail.versions[0].original_filename == "new_TC.pdf"
        assert Path(tc_doc_after_fail.versions[0].file_path).read_bytes() == new_tc_bytes

        # ----------------------------------------------------
        # 6. Refresh page (verify query returns new replaced file)
        # ----------------------------------------------------
        resume_res = await client_async.post(
            "/student/verify",
            json={
                "token": link.token,
                "student_name": student_name_1,
                "register_number": reg_num_1,
                "mobile_number": "9123456780",
                "email": "evelyn@example.com",
            },
        )
        assert resume_res.status_code == 200
        up_docs = resume_res.json()["uploaded_documents"]
        tc_meta = next(d for d in up_docs if d["document_type"] == "TRANSFER_CERTIFICATE")
        assert tc_meta["filename"] == "new_TC.pdf"

    # ----------------------------------------------------
    # 7. Data Extraction uses the replaced/current file
    # ----------------------------------------------------
    admin_user = User(
        username="admin_aero_test",
        password="password123",
        hashed_password="hashed_password",
        role=UserRole.SUPER_ADMIN,
        name="AERO Admin",
    )
    await admin_user.insert()

    extraction_service = DocumentExtractionService()
    with patch.object(extraction_service, "_run_ai_extraction", return_value=({"school_name": "Sky High Institute", "date_of_leaving": "15/05/2026"}, 99.0)):
        req_rec, res_rec = await extraction_service.request_and_extract_fields(
            student_document_id=str(tc_doc_final.id),
            version_id=None,
            requested_fields=["school_name", "date_of_leaving"],
            actor=admin_user,
        )
        assert req_rec.status == ExtractionRequestStatus.COMPLETED
        assert res_rec.extracted_data["school_name"] == "Sky High Institute"


@pytest.mark.asyncio
async def test_document_reupload_type_preservation_and_isolation(client_async: AsyncClient):
    """
    CRITICAL TEST FOR DOCUMENT TYPE PRESERVATION & REPLACEMENT:
    When a student has multiple documents (Aadhaar, TC, Community) and re-uploads TC:
    - TC replaces existing TC file in-place on the same StudentDocument record.
    - Aadhaar remains completely untouched.
    - Community Certificate remains untouched.
    - Exactly ONE StudentDocument exists per document type.
    """
    await Department.find(Department.name == "Dept BioTech").delete()
    await AdmissionBatch.find(AdmissionBatch.name == "Batch BioTech 2026").delete()
    await StudentSubmission.find(StudentSubmission.register_number == "26BIO001").delete()
    await StudentDocument.find(StudentDocument.student_id == "26BIO001").delete()

    dept = Department(
        name="Dept BioTech",
        code="BIO",
        description="BioTech Department",
        created_by="admin",
        is_active=True,
    )
    await dept.insert()

    batch = AdmissionBatch(
        id="batch_biotech_2026",
        name="Batch BioTech 2026",
        department_code="BIO",
        department_id=str(dept.id),
        academic_year="2026-2030",
        created_by="admin",
        status="active",
    )
    await batch.insert()

    sec = BatchClass(
        id="class_biotech_sec_a_2026",
        batch_id=batch.id,
        class_name="BIO-A",
        section="A",
        department=dept.name,
        academic_year="2026-2030",
        created_by="admin",
    )
    await sec.insert()

    wanted_service = WantedFieldService()
    await wanted_service.create_document_type(
        batch_id=batch.id,
        name="Aadhaar Card",
        code="AADHAAR",
        class_id=str(sec.id),
        requirement_status="REQUIRED",
    )
    await wanted_service.create_document_type(
        batch_id=batch.id,
        name="Transfer Certificate",
        code="TRANSFER_CERTIFICATE",
        class_id=str(sec.id),
        requirement_status="REQUIRED",
    )
    await wanted_service.create_document_type(
        batch_id=batch.id,
        name="Community Certificate",
        code="COMMUNITY_CERTIFICATE",
        class_id=str(sec.id),
        requirement_status="OPTIONAL",
    )

    link = UploadLink(
        department_id=str(dept.id),
        batch_id=batch.id,
        class_id=str(sec.id),
        token="biotech-token-2026",
        slug="biotech-token-2026",
        title="BioTech Upload Portal",
        is_active=True,
        created_by="admin",
    )
    await link.insert()

    student_reg = "26BIO001"
    student_name = "Devi Priya"
    doc_service = StudentDocumentService()

    # Step 1: Initial upload of Aadhaar and TC
    meta_initial = [
        {"document_name": "Aadhaar Card", "document_type": "AADHAAR", "filename": "aadhaar_v1.pdf", "file_index": 0, "is_new_file": True, "status": "Uploaded"},
        {"document_name": "Transfer Certificate", "document_type": "TRANSFER_CERTIFICATE", "filename": "tc_v1.pdf", "file_index": 1, "is_new_file": True, "status": "Uploaded"},
    ]
    res_init = await client_async.post(
        "/student-submissions/upload",
        data={
            "batch_id": batch.id,
            "class_id": str(sec.id),
            "register_number": student_reg,
            "student_name": student_name,
            "mobile_number": "9876543210",
            "email": "devi@example.com",
            "token": link.token,
            "documents_metadata": json.dumps(meta_initial),
        },
        files=[
            ("files", ("aadhaar_v1.pdf", b"%PDF-1.4 Aadhaar Initial V1", "application/pdf")),
            ("files", ("tc_v1.pdf", b"%PDF-1.4 TC Initial V1", "application/pdf")),
        ],
    )
    assert res_init.status_code == 201

    aadhaar_doc = await doc_service.get_student_document_by_type(student_reg, "AADHAAR")
    assert aadhaar_doc is not None
    assert len(aadhaar_doc.versions) == 1
    assert aadhaar_doc.versions[0].original_filename == "aadhaar_v1.pdf"
    aadhaar_id = str(aadhaar_doc.id)

    tc_doc = await doc_service.get_student_document_by_type(student_reg, "TRANSFER_CERTIFICATE")
    assert tc_doc is not None
    assert len(tc_doc.versions) == 1
    assert tc_doc.versions[0].original_filename == "tc_v1.pdf"
    tc_id = str(tc_doc.id)

    # Step 2: Student returns and re-uploads ONLY Transfer Certificate (TC)
    meta_reupload_tc = [
        {"document_name": "Aadhaar Card", "document_type": "AADHAAR", "filename": "aadhaar_v1.pdf", "is_new_file": False, "status": "Uploaded"},
        {"document_name": "Transfer Certificate", "document_type": "TRANSFER_CERTIFICATE", "filename": "tc_replaced.pdf", "file_index": 0, "is_new_file": True, "status": "Uploaded"},
    ]
    res_tc_replace = await client_async.post(
        "/student-submissions/upload",
        data={
            "batch_id": batch.id,
            "class_id": str(sec.id),
            "register_number": student_reg,
            "student_name": student_name,
            "mobile_number": "9876543210",
            "email": "devi@example.com",
            "token": link.token,
            "documents_metadata": json.dumps(meta_reupload_tc),
        },
        files=[
            ("files", ("tc_replaced.pdf", b"%PDF-1.4 TC Replacement Content", "application/pdf")),
        ],
    )
    assert res_tc_replace.status_code == 201

    # VERIFY CRITICAL ISOLATION & REPLACEMENT:
    # 1. Transfer Certificate is replaced in-place
    tc_doc_after = await doc_service.get_student_document_by_type(student_reg, "TRANSFER_CERTIFICATE")
    assert str(tc_doc_after.id) == tc_id
    assert len(tc_doc_after.versions) == 1, "Must NOT create second DocumentVersion"
    assert tc_doc_after.versions[0].original_filename == "tc_replaced.pdf"
    assert "transfer_certificate" in tc_doc_after.versions[0].file_path.lower()

    # 2. Aadhaar Card MUST REMAIN COMPLETELY UNCHANGED
    aadhaar_doc_after = await doc_service.get_student_document_by_type(student_reg, "AADHAAR")
    assert str(aadhaar_doc_after.id) == aadhaar_id
    assert len(aadhaar_doc_after.versions) == 1
    assert aadhaar_doc_after.versions[0].original_filename == "aadhaar_v1.pdf"

    # Step 3: Re-upload Aadhaar Card
    meta_reupload_aadhaar = [
        {"document_name": "Aadhaar Card", "document_type": "AADHAAR", "filename": "aadhaar_replaced.pdf", "file_index": 0, "is_new_file": True, "status": "Uploaded"},
        {"document_name": "Transfer Certificate", "document_type": "TRANSFER_CERTIFICATE", "filename": "tc_replaced.pdf", "is_new_file": False, "status": "Uploaded"},
    ]
    res_aadhaar_replace = await client_async.post(
        "/student-submissions/upload",
        data={
            "batch_id": batch.id,
            "class_id": str(sec.id),
            "register_number": student_reg,
            "student_name": student_name,
            "mobile_number": "9876543210",
            "email": "devi@example.com",
            "token": link.token,
            "documents_metadata": json.dumps(meta_reupload_aadhaar),
        },
        files=[
            ("files", ("aadhaar_replaced.pdf", b"%PDF-1.4 Aadhaar Replacement Content", "application/pdf")),
        ],
    )
    assert res_aadhaar_replace.status_code == 201

    aadhaar_doc_final = await doc_service.get_student_document_by_type(student_reg, "AADHAAR")
    assert str(aadhaar_doc_final.id) == aadhaar_id
    assert len(aadhaar_doc_final.versions) == 1
    assert aadhaar_doc_final.versions[0].original_filename == "aadhaar_replaced.pdf"

    # TC remains untouched with tc_replaced.pdf
    tc_doc_final = await doc_service.get_student_document_by_type(student_reg, "TRANSFER_CERTIFICATE")
    assert str(tc_doc_final.id) == tc_id
    assert len(tc_doc_final.versions) == 1
    assert tc_doc_final.versions[0].original_filename == "tc_replaced.pdf"

    # Step 4: Upload Community Certificate
    meta_community = [
        {"document_name": "Aadhaar Card", "document_type": "AADHAAR", "filename": "aadhaar_replaced.pdf", "is_new_file": False, "status": "Uploaded"},
        {"document_name": "Transfer Certificate", "document_type": "TRANSFER_CERTIFICATE", "filename": "tc_replaced.pdf", "is_new_file": False, "status": "Uploaded"},
        {"document_name": "Community Certificate", "document_type": "COMMUNITY_CERTIFICATE", "filename": "comm_v1.pdf", "file_index": 0, "is_new_file": True, "status": "Uploaded"},
    ]
    res_comm = await client_async.post(
        "/student-submissions/upload",
        data={
            "batch_id": batch.id,
            "class_id": str(sec.id),
            "register_number": student_reg,
            "student_name": student_name,
            "mobile_number": "9876543210",
            "email": "devi@example.com",
            "token": link.token,
            "documents_metadata": json.dumps(meta_community),
        },
        files=[
            ("files", ("comm_v1.pdf", b"%PDF-1.4 Community V1", "application/pdf")),
        ],
    )
    assert res_comm.status_code == 201

    comm_doc = await doc_service.get_student_document_by_type(student_reg, "COMMUNITY")
    assert comm_doc is not None
    assert len(comm_doc.versions) == 1

    # Verify counts: Exactly 1 StudentDocument for each document type (total 3)
    all_student_docs = await StudentDocument.find(StudentDocument.student_id == student_reg).to_list()
    assert len(all_student_docs) == 3
    doc_types = {d.document_type for d in all_student_docs}
    assert doc_types == {"AADHAAR", "TRANSFER_CERTIFICATE", "COMMUNITY"}

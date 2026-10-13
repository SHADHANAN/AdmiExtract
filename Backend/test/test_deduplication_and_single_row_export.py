import pytest
import pytest_asyncio
import os
import io
import openpyxl
from datetime import datetime, timezone
from beanie import PydanticObjectId
from motor.motor_asyncio import AsyncIOMotorClient

from app.core.config import settings
from app.models.user import User, UserRole
from app.models.batch import AdmissionBatch
from app.models.student_submission import StudentSubmission, StudentDocumentMeta
from app.models.student_document import StudentDocument, DocumentVersion
from app.models.document_extraction_result import DocumentExtractionResult
from app.models.batch_extraction import BatchExtractionRequest, BatchExtractionStatus
from app.models.document_verification import DocumentFieldVerification, VerificationFieldStatus
from app.services.batch_extraction_service import BatchExtractionService, CanonicalStudentUnit


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    import app.db.database as db_mod

    db_mod.client = AsyncIOMotorClient(
        settings.MONGODB_URI, serverSelectionTimeoutMS=2000
    )
    db_mod.db = db_mod.client[settings.DATABASE_NAME]
    await db_mod._run_db_setup()


@pytest.mark.asyncio
async def test_single_student_multiple_documents_produces_one_row(tmp_path):
    """
    Test Case 1 & 6:
    1 student + 4 documents (Aadhaar, Community, Passbook, TC)
    - Must produce exactly ONE CanonicalStudentUnit
    - Must produce exactly ONE DocumentExtractionResult
    - Must produce exactly ONE set of verification records for that student
    - Must export exactly ONE Excel row (plus 1 header row)
    """
    dept_id = f"DEDUP_DEPT_{PydanticObjectId()}"
    batch_id = f"BATCH_{PydanticObjectId()}"
    batch = AdmissionBatch(
        id=batch_id,
        name="Dedup_Test_Batch_1",
        academic_year="2025-2026",
        department_id=dept_id,
        created_by=f"admin_{PydanticObjectId()}",
        created_at=datetime.now(timezone.utc),
    )
    await batch.insert()

    uname = f"admin_{PydanticObjectId()}"
    actor = User(
        name="Admin User",
        username=uname,
        email=f"{uname}@test.com",
        password="hash",
        role=UserRole.DEPARTMENT_ADMIN,
        department_code=dept_id,
        department_id=dept_id,
        is_active=True,
    )
    await actor.insert()

    # Create dummy files
    aadhaar_file = str(tmp_path / "aadhaar.pdf")
    with open(aadhaar_file, "wb") as f:
        f.write(b"%PDF-1.4 Aadhaar Dummy Content")

    community_file = str(tmp_path / "community.pdf")
    with open(community_file, "wb") as f:
        f.write(b"%PDF-1.4 Community Dummy Content")

    passbook_file = str(tmp_path / "passbook.pdf")
    with open(passbook_file, "wb") as f:
        f.write(b"%PDF-1.4 Passbook Dummy Content")

    tc_file = str(tmp_path / "tc.pdf")
    with open(tc_file, "wb") as f:
        f.write(b"%PDF-1.4 TC Dummy Content")

    sub = StudentSubmission(
        batch_id=batch_id,
        register_number="TEST_DEDUP_093",
        student_name="Shadhanan.S",
        mobile_number="9876543210",
        department_id=dept_id,
        documents=[
            StudentDocumentMeta(document_name="Aadhaar Card", document_type="AADHAAR", file_path=aadhaar_file, file_name="aadhaar.pdf"),
            StudentDocumentMeta(document_name="Community Certificate", document_type="COMMUNITY", file_path=community_file, file_name="community.pdf"),
            StudentDocumentMeta(document_name="Bank Passbook", document_type="BANK_PASSBOOK", file_path=passbook_file, file_name="passbook.pdf"),
            StudentDocumentMeta(document_name="Transfer Certificate", document_type="TRANSFER_CERTIFICATE", file_path=tc_file, file_name="tc.pdf"),
        ],
        created_at=datetime.now(timezone.utc),
    )
    await sub.insert()

    # Create stored documents for this student with mixed student_id / submission_id references
    doc1 = StudentDocument(
        batch_id=batch_id,
        student_id="TEST_DEDUP_093",
        submission_id=str(sub.id),
        document_type="AADHAAR",
        document_name="Aadhaar Card",
        versions=[
            DocumentVersion(
                version_number=1,
                version_id="v1",
                file_path=aadhaar_file,
                original_filename="aadhaar.pdf",
                uploaded_at=datetime.now(timezone.utc),
                is_active=True,
            )
        ],
        active_version_id="v1",
    )
    await doc1.insert()

    doc2 = StudentDocument(
        batch_id=batch_id,
        student_id=str(sub.id),  # Stored with ObjectId as student_id
        submission_id=str(sub.id),
        document_type="COMMUNITY",
        document_name="Community Certificate",
        versions=[
            DocumentVersion(
                version_number=1,
                version_id="v1",
                file_path=community_file,
                original_filename="community.pdf",
                uploaded_at=datetime.now(timezone.utc),
                is_active=True,
            )
        ],
        active_version_id="v1",
    )
    await doc2.insert()

    doc3 = StudentDocument(
        batch_id=batch_id,
        student_id="test_dedup_093",  # Lowercase variation
        submission_id=str(sub.id),
        document_type="BANK_PASSBOOK",
        document_name="Bank Passbook",
        versions=[
            DocumentVersion(
                version_number=1,
                version_id="v1",
                file_path=passbook_file,
                original_filename="passbook.pdf",
                uploaded_at=datetime.now(timezone.utc),
                is_active=True,
            )
        ],
        active_version_id="v1",
    )
    await doc3.insert()

    doc4 = StudentDocument(
        batch_id=batch_id,
        student_id="TEST_DEDUP_093",
        submission_id=str(sub.id),
        document_type="TRANSFER_CERTIFICATE",
        document_name="Transfer Certificate",
        versions=[
            DocumentVersion(
                version_number=1,
                version_id="v1",
                file_path=tc_file,
                original_filename="tc.pdf",
                uploaded_at=datetime.now(timezone.utc),
                is_active=True,
            )
        ],
        active_version_id="v1",
    )
    await doc4.insert()

    service = BatchExtractionService()

    # 1. Test canonical units resolution
    units = await service._build_canonical_student_units([batch_id])
    assert len(units) == 1, f"Expected 1 canonical student unit, got {len(units)}"
    assert units[0].canonical_id == "TEST_DEDUP_093"
    assert len(units[0].documents) == 4, f"Expected 4 documents linked to student, got {len(units[0].documents)}"

    # 2. Run extraction
    fields = [
        "register_number",
        "student_name",
        "gender",
        "community",
        "bank_account_number",
        "ifsc_code",
    ]
    summary = await service.create_and_run_batch_extraction(
        batch_id=batch_id,
        requested_columns=None,
        requested_fields=fields,
        actor=actor,
    )

    assert summary.total_students == 1
    assert summary.processed_count == 1

    # 3. Assert exactly ONE DocumentExtractionResult
    ext_results = await DocumentExtractionResult.find(
        DocumentExtractionResult.extraction_request_id == summary.extraction_request_id
    ).to_list()
    assert len(ext_results) == 1, f"Expected 1 extraction result in DB, got {len(ext_results)}"

    # 4. Assert exactly ONE student row in details
    details = await service.get_extraction_details(
        extraction_request_id=summary.extraction_request_id,
        actor=actor,
    )
    assert len(details.students) == 1, f"Expected 1 student row in details, got {len(details.students)}"
    assert details.students[0].register_number == "TEST_DEDUP_093"

    # 5. Export to Excel and verify strictly ONE data row
    excel_stream, filename = await service.export_verified_excel(
        extraction_request_id=summary.extraction_request_id,
        actor=actor,
    )
    wb = openpyxl.load_workbook(excel_stream)
    ws = wb.active

    # Row 1 is header, Row 2 is Student 1, Row 3 must NOT exist
    assert ws.max_row == 2, f"Expected exactly 2 rows (1 header + 1 student), got {ws.max_row}"
    assert ws.cell(row=2, column=1).value == "TEST_DEDUP_093"


@pytest.mark.asyncio
async def test_multiple_students_with_multiple_documents_and_retry(tmp_path):
    """
    Test Case 3, 4, 5, 9:
    3 distinct students, each with multiple documents
    - Must produce exactly 3 extraction results
    - Must produce exactly 3 student rows in get_extraction_details
    - Must export exactly 3 student rows in Excel
    - Retrying one student's extraction must NOT increase the total student count
    - Exporting twice produces identical 3 student rows
    """
    dept_id = f"DEDUP_DEPT_{PydanticObjectId()}"
    batch_id = f"BATCH_{PydanticObjectId()}"
    batch = AdmissionBatch(
        id=batch_id,
        name="Dedup_Test_Batch_3",
        academic_year="2025-2026",
        department_id=dept_id,
        created_by=f"admin_{PydanticObjectId()}",
        created_at=datetime.now(timezone.utc),
    )
    await batch.insert()

    uname = f"admin_{PydanticObjectId()}"
    actor = User(
        name="Admin User",
        username=uname,
        email=f"{uname}@test.com",
        password="hash",
        role=UserRole.DEPARTMENT_ADMIN,
        department_code=dept_id,
        department_id=dept_id,
        is_active=True,
    )
    await actor.insert()

    student_data = [
        ("24AM101", "Student One"),
        ("24AM102", "Student Two"),
        ("24AM103", "Student Three"),
    ]

    for reg_no, s_name in student_data:
        sub = StudentSubmission(
            batch_id=batch_id,
            register_number=reg_no,
            student_name=s_name,
            mobile_number="9876543210",
            department_id=dept_id,
            created_at=datetime.now(timezone.utc),
        )
        await sub.insert()

        # Add 3 documents per student
        for dtype in ["AADHAAR", "COMMUNITY", "TRANSFER_CERTIFICATE"]:
            fpath = str(tmp_path / f"{reg_no}_{dtype}.pdf")
            with open(fpath, "wb") as f:
                f.write(f"%PDF Dummy {reg_no} {dtype}".encode("utf-8"))

            doc = StudentDocument(
                batch_id=batch_id,
                student_id=reg_no,
                submission_id=str(sub.id),
                document_type=dtype,
                document_name=f"{dtype} Document",
                versions=[
                    DocumentVersion(
                        version_number=1,
                        version_id="v1",
                        file_path=fpath,
                        original_filename=f"{dtype}.pdf",
                        uploaded_at=datetime.now(timezone.utc),
                        is_active=True,
                    )
                ],
                active_version_id="v1",
            )
            await doc.insert()

    service = BatchExtractionService()

    # 1. Run extraction for the 3 students
    fields = ["register_number", "student_name", "community", "gender"]
    summary = await service.create_and_run_batch_extraction(
        batch_id=batch_id,
        requested_columns=["Register Number", "Student Name", "Community", "Gender"],
        requested_fields=fields,
        actor=actor,
    )

    assert summary.total_students == 3
    assert summary.processed_count == 3

    # 2. Check extraction results count in DB
    ext_results = await DocumentExtractionResult.find(
        DocumentExtractionResult.extraction_request_id == summary.extraction_request_id
    ).to_list()
    assert len(ext_results) == 3, f"Expected 3 extraction results in DB, got {len(ext_results)}"

    # 3. Check details API
    details = await service.get_extraction_details(
        extraction_request_id=summary.extraction_request_id,
        actor=actor,
    )
    assert len(details.students) == 3, f"Expected 3 student rows, got {len(details.students)}"
    reg_nos_in_details = [s.register_number for s in details.students]
    assert sorted(reg_nos_in_details) == ["24AM101", "24AM102", "24AM103"]

    # 4. Retry extraction for student 24AM102
    retry_resp = await service.retry_student_extraction(
        extraction_request_id=summary.extraction_request_id,
        student_id="24AM102",
        actor=actor,
    )
    assert retry_resp.register_number == "24AM102"

    # Verify count did NOT increase after retry
    details_after_retry = await service.get_extraction_details(
        extraction_request_id=summary.extraction_request_id,
        actor=actor,
    )
    assert len(details_after_retry.students) == 3, f"Expected 3 rows after retry, got {len(details_after_retry.students)}"

    # 5. Export Excel (First time)
    stream1, fn1 = await service.export_verified_excel(
        extraction_request_id=summary.extraction_request_id,
        actor=actor,
    )
    wb1 = openpyxl.load_workbook(stream1)
    ws1 = wb1.active
    assert ws1.max_row == 4, f"Expected 4 rows (1 header + 3 students), got {ws1.max_row}"

    exported_reg_nos = [ws1.cell(row=r, column=1).value for r in range(2, 5)]
    assert sorted(exported_reg_nos) == ["24AM101", "24AM102", "24AM103"]

    # 6. Export Excel (Second time)
    stream2, fn2 = await service.export_verified_excel(
        extraction_request_id=summary.extraction_request_id,
        actor=actor,
    )
    wb2 = openpyxl.load_workbook(stream2)
    ws2 = wb2.active
    assert ws2.max_row == 4, f"Expected 4 rows on second export, got {ws2.max_row}"

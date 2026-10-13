import pytest
import pytest_asyncio
from typing import Any, cast
from httpx import AsyncClient, ASGITransport
from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient

from app.main import app
from app.models.user import User, UserRole
from app.models.department import Department
from app.models.batch import AdmissionBatch
from app.models.batch_class import BatchClass
from app.models.upload_link import UploadLink
from app.models.student_submission import StudentSubmission, StudentDocumentMeta
from app.models.student_document import StudentDocument, DocumentVersion, DocumentStatus
from app.models.doc_config_version import DocumentConfigurationVersion
from app.models.wanted_field_config import DocumentFieldConfiguration, WantedFieldItem
from app.models.batch_extraction import BatchExtractionRequest
from app.models.document_verification import DocumentFieldVerification
from app.core.config import settings
from app.core.security import create_access_token


@pytest_asyncio.fixture(scope="function", autouse=True)
async def setup_test_db():
    if not hasattr(AsyncIOMotorClient, "append_metadata"):
        AsyncIOMotorClient.append_metadata = lambda *args, **kwargs: None

    import app.db.database as db_mod
    test_client = AsyncIOMotorClient(settings.MONGODB_URI)
    test_db = test_client["automate_test_db"]

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
    await DocumentConfigurationVersion.find_all().delete()
    await DocumentFieldConfiguration.find_all().delete()
    await BatchExtractionRequest.find_all().delete()
    await DocumentFieldVerification.find_all().delete()

    yield

    await test_client.drop_database("automate_test_db")
    test_client.close()


@pytest_asyncio.fixture
async def client_async():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_acceptance_test_batch_and_section_student_scope_consistency(client_async: AsyncClient):
    """
    Acceptance Test specified in prompt:
    1. Create TEST batch
    2. Create AIML - Section A
    3. 3 students: 24AM093, 24AM095, 24AM076 (initially without class_id / unassigned)
    4. Verify Batch TEST Students = 3, Section A Students = 3
    5. Verify Data Extraction: ALL STUDENTS = 3, SECTION A = 3
    6. Run extraction: All 3 students must be included, none disappear.
    """
    admin_user = User(
        name="Admin Test",
        username="admin_test",
        email="admin@college.edu",
        password="hash",
        role=UserRole.SUPER_ADMIN,
        is_active=True,
    )
    await admin_user.insert()
    token = create_access_token({"sub": str(admin_user.id), "role": UserRole.SUPER_ADMIN.value})
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Create TEST batch
    batch = AdmissionBatch(
        id="TEST",
        name="TEST",
        department_id="AIML",
        academic_year="2025-2029",
        status="active",
        created_by="admin_test",
    )
    await batch.insert()

    # 2. Create Section A
    section_a = BatchClass(
        id="class_TEST_aiml_section_a",
        batch_id="TEST",
        class_name="AIML - Section A",
        department="AIML",
        section="A",
        academic_year="2025-2029",
    )
    await section_a.insert()

    # 3. Create 3 students belonging to batch TEST (some initially missing class_id to test healing)
    sub1 = StudentSubmission(
        batch_id="TEST",
        student_name="Student One",
        register_number="24AM093",
        mobile_number="9876543210",
        submission_status="Verified",
        class_id=None,  # missing class_id
        class_name=None,
    )
    await sub1.insert()

    sub2 = StudentSubmission(
        batch_id="TEST",
        student_name="Student Two",
        register_number="24AM095",
        mobile_number="9876543211",
        submission_status="Submitted",
        class_id="",  # empty class_id
        class_name="",
    )
    await sub2.insert()

    sub3 = StudentSubmission(
        batch_id="TEST",
        student_name="Student Three",
        register_number="24AM076",
        mobile_number="9876543212",
        submission_status="Submitted",
        class_id=section_a.id,
        class_name=section_a.class_name,
    )
    await sub3.insert()

    # Create associated student documents
    for reg, sub in [("24AM093", sub1), ("24AM095", sub2), ("24AM076", sub3)]:
        doc = StudentDocument(
            student_id=reg,
            submission_id=str(sub.id),
            batch_id="TEST",
            document_type="AADHAAR",
            document_name="Aadhaar Card",
            current_version=1,
            versions=[
                DocumentVersion(
                    version_number=1,
                    file_path=f"storage/{reg}/aadhaar.pdf",
                    original_filename="aadhaar.pdf",
                    validation_status="VALID",
                    is_active=True,
                )
            ],
        )
        await doc.insert()

    # 4. Check Section API count and stats
    res_sec = await client_async.get(f"/classes/{section_a.id}", headers=headers)
    assert res_sec.status_code == 200, res_sec.text
    sec_data = res_sec.json()
    assert sec_data["stats"]["students"] == 3

    res_sec_list = await client_async.get("/batches/TEST/classes", headers=headers)
    assert res_sec_list.status_code == 200
    classes_data = res_sec_list.json()
    assert len(classes_data) == 1
    assert classes_data[0]["stats"]["students"] == 3

    # Check Section Students API
    res_students = await client_async.get(f"/classes/{section_a.id}/students", headers=headers)
    assert res_students.status_code == 200
    stud_list = res_students.json()
    assert len(stud_list) == 3
    returned_regs = {s["register_number"] for s in stud_list}
    assert returned_regs == {"24AM093", "24AM095", "24AM076"}

    # Verify DB was healed
    updated_sub1 = await StudentSubmission.get(sub1.id)
    assert updated_sub1.class_id == section_a.id
    assert updated_sub1.class_name == section_a.class_name

    updated_sub2 = await StudentSubmission.get(sub2.id)
    assert updated_sub2.class_id == section_a.id
    assert updated_sub2.class_name == section_a.class_name

    # 5. Check Data Extraction Scope
    from app.services.batch_extraction_service import BatchExtractionService
    extraction_svc = BatchExtractionService()

    # Scope ALL STUDENTS
    units_all = await extraction_svc._build_canonical_student_units(["TEST"], clean_class_id=None)
    assert len(units_all) == 3
    assert {u.register_number for u in units_all} == {"24AM093", "24AM095", "24AM076"}

    # Scope SECTION A
    units_sec = await extraction_svc._build_canonical_student_units(["TEST"], clean_class_id=section_a.id)
    assert len(units_sec) == 3
    assert {u.register_number for u in units_sec} == {"24AM093", "24AM095", "24AM076"}

    # 6. Configure document fields and run extraction with Section Scope
    from app.models.wanted_field_config import WantedFieldItem
    doc_config = DocumentFieldConfiguration(
        batch_id="TEST",
        document_type="AADHAAR",
        display_name="Aadhaar Card",
        requirement_status="REQUIRED",
        version=1,
        fields=[
            WantedFieldItem(
                field="Student Name",
                enabled=True,
                excel_header="Student Name",
                extraction_rules=["student_name"],
            ),
            WantedFieldItem(
                field="Aadhaar Number",
                enabled=True,
                excel_header="Aadhaar Number",
                extraction_rules=["aadhaar_number"],
            ),
        ],
    )
    await doc_config.insert()

    ext_job = await extraction_svc.create_and_run_batch_extraction(
        batch_id="TEST",
        requested_fields=["student_name", "aadhaar_number"],
        requested_columns=["Student Name", "Aadhaar Number"],
        column_mapping={"Student Name": "student_name", "Aadhaar Number": "aadhaar_number"},
        actor=admin_user,
        class_id=section_a.id,
    )

    assert ext_job.total_students == 3

    # Check request record in DB
    req_doc = await BatchExtractionRequest.find_one(
        BatchExtractionRequest.extraction_request_id == ext_job.extraction_request_id
    )
    assert req_doc is not None
    assert req_doc.total_students == 3
    assert req_doc.result_count == 3

    # Check verifications in DB
    verifs = await DocumentFieldVerification.find(
        DocumentFieldVerification.extraction_request_id == ext_job.extraction_request_id
    ).to_list()
    assert len(verifs) > 0
    verif_regs = {v.student_id for v in verifs}
    assert verif_regs == {"24AM093", "24AM095", "24AM076"}


@pytest.mark.asyncio
async def test_multi_section_unassigned_isolation_and_reassignment(client_async: AsyncClient):
    """
    Test that when multiple sections exist in a batch:
    - Students without section_id remain unassigned (do not guess).
    - Section A only counts its assigned students.
    - Section B only counts its assigned students.
    - Staff can assign unassigned student to Section B using assign-section endpoint.
    """
    admin_user = User(
        name="Admin Multi",
        username="admin_multi",
        email="admin_multi@college.edu",
        password="hash",
        role=UserRole.SUPER_ADMIN,
        is_active=True,
    )
    await admin_user.insert()
    token = create_access_token({"sub": str(admin_user.id), "role": UserRole.SUPER_ADMIN.value})
    headers = {"Authorization": f"Bearer {token}"}

    # Create Batch
    batch = AdmissionBatch(
        id="BATCH_MULTI",
        name="Batch Multi",
        department_id="CSE",
        academic_year="2025-2029",
        status="active",
        created_by="admin_multi",
    )
    await batch.insert()

    # Create Section A and Section B
    sec_a = BatchClass(
        id="class_multi_sec_a",
        batch_id="BATCH_MULTI",
        class_name="CSE - Section A",
        department="CSE",
        section="A",
        academic_year="2025-2029",
    )
    await sec_a.insert()

    sec_b = BatchClass(
        id="class_multi_sec_b",
        batch_id="BATCH_MULTI",
        class_name="CSE - Section B",
        department="CSE",
        section="B",
        academic_year="2025-2029",
    )
    await sec_b.insert()

    # Student 1 in Section A
    s1 = StudentSubmission(
        batch_id="BATCH_MULTI",
        student_name="Student Alpha",
        register_number="25CS001",
        mobile_number="9000000001",
        submission_status="Verified",
        class_id=sec_a.id,
        class_name=sec_a.class_name,
    )
    await s1.insert()

    # Student 2 in Section B
    s2 = StudentSubmission(
        batch_id="BATCH_MULTI",
        student_name="Student Beta",
        register_number="25CS002",
        mobile_number="9000000002",
        submission_status="Submitted",
        class_id=sec_b.id,
        class_name=sec_b.class_name,
    )
    await s2.insert()

    # Student 3 Unassigned (no class_id)
    s3 = StudentSubmission(
        batch_id="BATCH_MULTI",
        student_name="Student Gamma",
        register_number="25CS003",
        mobile_number="9000000003",
        submission_status="Submitted",
        class_id=None,
        class_name=None,
    )
    await s3.insert()

    # Section A should only count 1
    res_a = await client_async.get(f"/classes/{sec_a.id}", headers=headers)
    assert res_a.status_code == 200
    assert res_a.json()["stats"]["students"] == 1

    # Section B should only count 1
    res_b = await client_async.get(f"/classes/{sec_b.id}", headers=headers)
    assert res_b.status_code == 200
    assert res_b.json()["stats"]["students"] == 1

    # Reassign Student 3 to Section B via PUT /student-submissions/{id}/assign-section
    res_assign = await client_async.put(
        f"/student-submissions/{s3.id}/assign-section",
        headers=headers,
        json={"class_id": sec_b.id},
    )
    assert res_assign.status_code == 200, res_assign.text
    assert res_assign.json()["class_id"] == sec_b.id
    assert res_assign.json()["class_name"] == sec_b.class_name

    # Now Section B should have 2 students
    res_b2 = await client_async.get(f"/classes/{sec_b.id}", headers=headers)
    assert res_b2.status_code == 200
    assert res_b2.json()["stats"]["students"] == 2

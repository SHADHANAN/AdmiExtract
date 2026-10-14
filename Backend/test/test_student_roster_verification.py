import pytest
import pytest_asyncio
from datetime import datetime, timezone, timedelta
from typing import Any, cast
from unittest.mock import MagicMock, AsyncMock, patch
from httpx import AsyncClient, ASGITransport
from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient

from app.main import app
from app.models.user import User
from app.models.department import Department
from app.models.batch import AdmissionBatch
from app.models.batch_class import BatchClass
from app.models.doc_config_version import DocumentConfigurationVersion
from app.models.wanted_field_config import DocumentFieldConfiguration
from app.models.upload_link import UploadLink
from app.models.student_submission import StudentSubmission
from app.core.config import settings


@pytest_asyncio.fixture(scope="function", autouse=True)
async def setup_test_db():
    if not hasattr(AsyncIOMotorClient, "append_metadata"):
        AsyncIOMotorClient.append_metadata = lambda *args, **kwargs: None

    test_client = AsyncIOMotorClient(settings.MONGODB_URI)
    test_db = test_client["roster_test_db"]

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
    await DocumentConfigurationVersion.find_all().delete()
    await DocumentFieldConfiguration.find_all().delete()

    yield

    await test_client.drop_database("roster_test_db")
    test_client.close()


@pytest_asyncio.fixture
async def client_async():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_student_verify_succeeds_directly_without_roster(client_async: AsyncClient):
    """Student identity verification succeeds directly without any candidate roster."""
    dept = Department(name="Computer Science", code="CS", intake_capacity=60, created_by="admin")
    await dept.insert()

    batch = AdmissionBatch(
        id="batch_cs_2026",
        name="CS Batch 2026",
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
        token="cs-direct-link",
        slug="cs-direct-link",
        title="CS Admission Portal",
        is_active=True,
        created_by="admin",
    )
    await link.insert()

    res = await client_async.post(
        "/student/verify",
        json={
            "token": link.token,
            "student_name": "Alice Smith",
            "register_number": "26CS001",
            "mobile_number": "9876543210",
            "email": "alice@example.com",
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["batch_id"] == batch.id
    assert data["batch_name"] == batch.name
    assert data["token"] == link.token


@pytest.mark.asyncio
async def test_student_verify_section_scoped(client_async: AsyncClient):
    """Verify that section-specific links correctly resolve class_id and class_name."""
    dept = Department(name="Computer Science", code="CS", intake_capacity=60, created_by="admin")
    await dept.insert()

    batch = AdmissionBatch(
        id="batch_cs_2026",
        name="CS Batch 2026",
        department_code="CS",
        department_id="CS",
        academic_year="2026-2030",
        created_by="admin",
        status="active",
    )
    await batch.insert()

    sec_a = BatchClass(
        id="class_cs_a_2026",
        batch_id=batch.id,
        class_name="CS-A",
        section="A",
        department=dept.name,
        academic_year="2026-2030",
        created_by="admin",
    )
    await sec_a.insert()

    link = UploadLink(
        department_id=dept.id,
        batch_id=batch.id,
        class_id=str(sec_a.id),
        token="cs-sec-a-link",
        slug="cs-sec-a-link",
        title="CS-A Portal",
        is_active=True,
        created_by="admin",
    )
    await link.insert()

    res = await client_async.post(
        "/student/verify",
        json={
            "token": link.token,
            "student_name": "Alice Smith",
            "register_number": "26CS001",
            "mobile_number": "9876543210",
            "email": "alice@example.com",
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["class_id"] == str(sec_a.id)
    assert data["class_name"] == "CS-A"


@pytest.mark.asyncio
async def test_submission_and_document_creation_without_roster(client_async: AsyncClient):
    """Verify that student can submit documents and profile is created without any roster."""
    dept = Department(name="Information Tech", code="IT", intake_capacity=60, created_by="admin")
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

    link = UploadLink(
        department_id=dept.id,
        batch_id=batch.id,
        token="it-no-roster-link",
        slug="it-no-roster-link",
        title="IT Portal",
        is_active=True,
        created_by="admin",
    )
    await link.insert()

    # Step 1: Verify identity succeeds without roster
    verify_res = await client_async.post(
        "/student/verify",
        json={
            "token": link.token,
            "student_name": "Bob Builder",
            "register_number": "26IT099",
            "mobile_number": "9876543210",
            "email": "bob.builder@example.com",
        },
    )
    assert verify_res.status_code == 200
    v_data = verify_res.json()
    assert v_data["batch_id"] == batch.id

    # Step 2: Create submission without roster
    sub_res = await client_async.post(
        "/student-submissions",
        json={
            "batch_id": batch.id,
            "student_name": "Bob Builder",
            "register_number": "26IT099",
            "mobile_number": "9876543210",
            "email": "bob.builder@example.com",
            "documents": [
                {
                    "document_name": "Aadhaar Card",
                    "file_path": "/tmp/mock_aadhaar.pdf",
                    "file_size_mb": 1.5,
                }
            ],
        },
    )
    assert sub_res.status_code == 201, f"Failed: {sub_res.status_code} - {sub_res.text}"
    created_sub = sub_res.json()
    assert created_sub["student_name"] == "Bob Builder"
    assert created_sub["register_number"] == "26IT099"

    # Step 3: Re-entering details resumes the existing submission
    resume_res = await client_async.post(
        "/student/verify",
        json={
            "token": link.token,
            "student_name": "Bob Builder",
            "register_number": "26IT099",
            "mobile_number": "9876543210",
            "email": "bob.builder@example.com",
        },
    )
    assert resume_res.status_code == 200
    resumed_data = resume_res.json()
    assert resumed_data["submission_id"] == created_sub["id"]
    assert len(resumed_data["uploaded_documents"]) == 1



@pytest.mark.asyncio
async def test_invalid_or_expired_link_security(client_async: AsyncClient):
    """Ensure that invalid or expired upload links are rejected."""
    dept = Department(name="Mechanical Eng", code="MECH", intake_capacity=60, created_by="admin")
    await dept.insert()

    batch = AdmissionBatch(
        id="batch_mech_2026",
        name="MECH Batch 2026",
        department_code="MECH",
        department_id="MECH",
        academic_year="2026-2030",
        created_by="admin",
        status="active",
    )
    await batch.insert()

    # 1. Invalid token
    invalid_res = await client_async.post(
        "/student/verify",
        json={
            "token": "non-existent-token",
            "student_name": "Charlie",
            "register_number": "26ME001",
            "mobile_number": "9876543210",
            "email": "charlie@example.com",
        },
    )
    assert invalid_res.status_code == 404

    # 2. Inactive link
    inactive_link = UploadLink(
        department_id=dept.id,
        batch_id=batch.id,
        token="mech-inactive",
        slug="mech-inactive",
        title="MECH Portal",
        is_active=False,
        created_by="admin",
    )
    await inactive_link.insert()

    inactive_res = await client_async.post(
        "/student/verify",
        json={
            "token": inactive_link.token,
            "student_name": "Charlie",
            "register_number": "26ME001",
            "mobile_number": "9876543210",
            "email": "charlie@example.com",
        },
    )
    assert inactive_res.status_code == 403

    # 3. Expired link
    expired_link = UploadLink(
        department_id=dept.id,
        batch_id=batch.id,
        token="mech-expired",
        slug="mech-expired",
        title="MECH Portal",
        is_active=True,
        expires_at=datetime.now(timezone.utc) - timedelta(days=1),
        created_by="admin",
    )
    await expired_link.insert()

    expired_res = await client_async.post(
        "/student/verify",
        json={
            "token": expired_link.token,
            "student_name": "Charlie",
            "register_number": "26ME001",
            "mobile_number": "9876543210",
            "email": "charlie@example.com",
        },
    )
    assert expired_res.status_code == 410


@pytest.mark.asyncio
async def test_admission_batch_zero_preconfigured_students_full_flow(client_async: AsyncClient):
    """
    Comprehensive proof of the student admission flow:
    1. Admission Batch has ZERO pre-configured students / no candidate roster.
    2. Staff configured document requirements: Aadhaar=Required, Birth Cert=Required, Community=Required, HSC=Required, TC=Optional.
    3. Student opens link and enters Student Name, Register Number, Mobile, and Email manually.
    4. Continue succeeds directly without any roster check.
    5. Configured document requirements are automatically loaded.
    6. Student submits documents and submission is saved with the entered details and document snapshot.
    7. No roster lookup or candidate pre-registration lookup occurs.
    """
    dept = Department(name="Electrical Eng", code="EEE", intake_capacity=60, created_by="admin")
    await dept.insert()

    batch = AdmissionBatch(
        id="batch_eee_2026",
        name="EEE Batch 2026",
        department_code="EEE",
        department_id="EEE",
        academic_year="2026-2030",
        created_by="admin",
        status="active",
    )
    await batch.insert()

    # Staff configures document requirements for the batch
    from app.services.wanted_field_service import WantedFieldService

    wanted_service = WantedFieldService()
    await wanted_service.create_document_type(batch_id=batch.id, name="Aadhaar Card", code="AADHAAR", requirement_status="REQUIRED")
    await wanted_service.create_document_type(batch_id=batch.id, name="Birth Certificate", code="BIRTH_CERT", requirement_status="REQUIRED")
    await wanted_service.create_document_type(batch_id=batch.id, name="Community Certificate", code="COMMUNITY_CERT", requirement_status="REQUIRED")
    await wanted_service.create_document_type(batch_id=batch.id, name="HSC Marksheet", code="HSC_MARKSHEET", requirement_status="REQUIRED")
    await wanted_service.create_document_type(batch_id=batch.id, name="Transfer Certificate", code="TC", requirement_status="OPTIONAL")

    # Upload link generated for this batch
    link = UploadLink(
        department_id=dept.id,
        batch_id=batch.id,
        token="eee-admission-2026",
        slug="eee-admission-2026",
        title="EEE Admission Document Portal",
        is_active=True,
        created_by="admin",
    )
    await link.insert()

    # Verify zero pre-configured students exist
    assert await StudentSubmission.find(StudentSubmission.batch_id == batch.id).count() == 0

    # 1 & 2 & 3: Student enters details manually and clicks Continue
    continue_res = await client_async.post(
        "/student/verify",
        json={
            "token": link.token,
            "student_name": "Devi Raman",
            "register_number": "26EE105",
            "mobile_number": "9876543210",
            "email": "devi.raman@example.com",
        },
    )
    # 4: Continue succeeds without any roster check
    assert continue_res.status_code == 200
    continue_data = continue_res.json()
    assert continue_data["batch_id"] == batch.id
    assert continue_data["batch_name"] == batch.name
    assert continue_data["token"] == link.token

    # 5: Configured document requirements are automatically loaded
    reqs_res = await client_async.get(f"/public/batches/{batch.id}/doc-versions/current")
    assert reqs_res.status_code == 200
    reqs_data = reqs_res.json()
    loaded_docs = reqs_data["documents"]
    assert len(loaded_docs) == 5

    loaded_names = {d["name"]: d["required"] for d in loaded_docs}
    assert loaded_names["Aadhaar Card"] is True
    assert loaded_names["Birth Certificate"] is True
    assert loaded_names["Community Certificate"] is True
    assert loaded_names["HSC Marksheet"] is True
    assert loaded_names["Transfer Certificate"] is False

    # 6: Student proceeds to upload documents and submit
    sub_res = await client_async.post(
        "/student-submissions",
        json={
            "batch_id": batch.id,
            "student_name": "Devi Raman",
            "register_number": "26EE105",
            "mobile_number": "9876543210",
            "email": "devi.raman@example.com",
            "upload_link_id": str(link.id),
            "documents": [
                {
                    "document_name": "Aadhaar Card",
                    "file_path": "/tmp/mock_devi_aadhaar.pdf",
                    "file_size_mb": 1.2,
                    "status": "Uploaded",
                },
                {
                    "document_name": "Birth Certificate",
                    "file_path": "/tmp/mock_devi_birth.pdf",
                    "file_size_mb": 0.8,
                    "status": "Uploaded",
                },
                {
                    "document_name": "Community Certificate",
                    "file_path": "/tmp/mock_devi_comm.pdf",
                    "file_size_mb": 0.9,
                    "status": "Uploaded",
                },
                {
                    "document_name": "HSC Marksheet",
                    "file_path": "/tmp/mock_devi_hsc.pdf",
                    "file_size_mb": 1.4,
                    "status": "Uploaded",
                },
            ],
        },
    )
    assert sub_res.status_code == 201
    created = sub_res.json()
    assert created["student_name"] == "Devi Raman"
    assert created["register_number"] == "26EE105"
    assert len(created["documents"]) == 4

    # 7: Verify submission is saved in DB
    saved_sub = await StudentSubmission.find_one(StudentSubmission.register_number == "26EE105")
    assert saved_sub is not None
    assert saved_sub.student_name == "Devi Raman"
    assert saved_sub.batch_id == batch.id
    assert saved_sub.document_version == 1
    assert len(saved_sub.document_requirements_snapshot) == 5


@pytest.mark.asyncio
async def test_exact_admission_upload_flow_user_scenario(client_async: AsyncClient):
    """
    Test the exact failing user scenario:
    Batch with NO roster, NO pre-configured students, configured required documents, and an active upload link.
    Student enters:
      Student Name: Shadhanan
      Register Number: 24AM093
      Mobile Number: 9876543210
      Email: shadhanan@example.com
    Continue succeeds, submission is automatically created, batch+section association is saved,
    configured document requirements are loaded, and student proceeds to upload documents.
    """
    dept = Department(name="Artificial Intelligence", code="AI", intake_capacity=60, created_by="admin")
    await dept.insert()

    batch = AdmissionBatch(
        id="batch_ai_2025",
        name="AIML 2025",
        department_code="AI",
        department_id="AI",
        academic_year="2025-2029",
        created_by="admin",
        status="active",
    )
    await batch.insert()

    sec = BatchClass(
        id="class_ai_a_2025",
        batch_id=batch.id,
        class_name="AIML-A",
        section="A",
        department=dept.name,
        academic_year="2025-2029",
        created_by="admin",
    )
    await sec.insert()

    # Staff configures document requirements for batch
    from app.services.wanted_field_service import WantedFieldService
    wanted_service = WantedFieldService()
    await wanted_service.create_document_type(batch_id=batch.id, name="Aadhaar Card", code="AADHAAR", requirement_status="REQUIRED")
    await wanted_service.create_document_type(batch_id=batch.id, name="10th Marksheet", code="SSLC", requirement_status="REQUIRED")
    await wanted_service.create_document_type(batch_id=batch.id, name="12th Marksheet", code="HSC", requirement_status="REQUIRED")
    await wanted_service.create_document_type(batch_id=batch.id, name="Transfer Certificate", code="TC", requirement_status="OPTIONAL")

    link = UploadLink(
        department_id=dept.id,
        batch_id=batch.id,
        class_id=str(sec.id),
        token="aiml-2025-sec-a",
        slug="aiml-2025-sec-a",
        title="AIML 2025 Section A Upload Gateway",
        is_active=True,
        created_by="admin",
    )
    await link.insert()

    # Verify zero pre-configured students exist
    assert await StudentSubmission.find(StudentSubmission.batch_id == batch.id).count() == 0

    # Student enters details manually and clicks Continue
    continue_res = await client_async.post(
        "/student/verify",
        json={
            "token": link.token,
            "student_name": "Shadhanan",
            "register_number": "24AM093",
            "mobile_number": "9876543210",
            "email": "shadhanan@example.com",
        },
    )
    assert continue_res.status_code == 200
    res_data = continue_res.json()
    assert res_data["batch_id"] == batch.id
    assert res_data["batch_name"] == batch.name
    assert res_data["class_id"] == str(sec.id)
    assert res_data["class_name"] == "AIML-A"
    assert res_data["submission_id"] is not None

    # Submission is automatically created in MongoDB
    sub = await StudentSubmission.get(res_data["submission_id"])
    assert sub is not None
    assert sub.student_name == "Shadhanan"
    assert sub.register_number == "24AM093"
    assert sub.mobile_number == "9876543210"
    assert sub.email == "shadhanan@example.com"
    assert sub.batch_id == batch.id
    assert sub.class_id == str(sec.id)
    assert sub.class_name == "AIML-A"

    # Configured document requirements are loaded
    reqs_res = await client_async.get(f"/public/batches/{batch.id}/doc-versions/current?classId={sec.id}")
    assert reqs_res.status_code == 200
    reqs_docs = reqs_res.json()["documents"]
    assert len(reqs_docs) == 4
    doc_map = {d["name"]: d["required"] for d in reqs_docs}
    assert doc_map["Aadhaar Card"] is True
    assert doc_map["10th Marksheet"] is True
    assert doc_map["12th Marksheet"] is True
    assert doc_map["Transfer Certificate"] is False

    # Student can retry / continue again without failure (idempotent submission session)
    retry_res = await client_async.post(
        "/student/verify",
        json={
            "token": link.token,
            "student_name": "Shadhanan",
            "register_number": "24AM093",
            "mobile_number": "9876543210",
            "email": "shadhanan@example.com",
        },
    )
    assert retry_res.status_code == 200
    assert retry_res.json()["submission_id"] == str(sub.id)

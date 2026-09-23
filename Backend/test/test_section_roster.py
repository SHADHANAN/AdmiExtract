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
from app.models.student_submission import StudentSubmission
from app.models.doc_config_version import DocumentConfigurationVersion
from app.models.excel_template import ExcelBatchTemplate
from app.models.wanted_field_config import DocumentFieldConfiguration
from app.core.config import settings
from app.core.security import create_access_token


@pytest_asyncio.fixture(scope="function", autouse=True)
async def setup_test_db():
    if not hasattr(AsyncIOMotorClient, "append_metadata"):
        AsyncIOMotorClient.append_metadata = lambda *args, **kwargs: None

    test_client = AsyncIOMotorClient(settings.MONGODB_URI)
    test_db = test_client["automate_test_db"]

    import app.db.database
    app.db.database.client = test_client
    app.db.database.db = test_db
    app.db.database._is_connected = True

    await init_beanie(
        database=cast(Any, test_db),
        document_models=[
            User,
            Department,
            AdmissionBatch,
            BatchClass,
            UploadLink,
            StudentSubmission,
            DocumentConfigurationVersion,
            ExcelBatchTemplate,
            DocumentFieldConfiguration,
        ],
    )
    await User.find_all().delete()
    await Department.find_all().delete()
    await AdmissionBatch.find_all().delete()
    await BatchClass.find_all().delete()
    await UploadLink.find_all().delete()
    await StudentSubmission.find_all().delete()
    await DocumentConfigurationVersion.find_all().delete()
    await ExcelBatchTemplate.find_all().delete()
    await DocumentFieldConfiguration.find_all().delete()

    yield

    await test_client.drop_database("automate_test_db")
    test_client.close()


@pytest_asyncio.fixture
async def client_async():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_section_roster_association_and_isolation(client_async: AsyncClient):
    """
    Test:
    1. Upload link creation tied to Section A.
    2. Confirm submission deriving class_id from link token.
    3. Section A query returns Section A submission.
    4. Section B query isolates and does not leak Section A student.
    """
    # 1. Seed Admin User & Auth Token
    admin = User(
        username="admin_user",
        name="Admin User",
        email="admin@test.edu",
        password="hashedpassword",
        role=UserRole.SUPER_ADMIN,
        is_active=True,
    )
    await admin.insert()
    admin_token = create_access_token(data={"sub": str(admin.id), "role": "super_admin"})
    auth_headers = {"Authorization": f"Bearer {admin_token}"}

    dept = Department(name="Artificial Intelligence", code="AIML", intake_capacity=60, created_by=admin.username)
    await dept.insert()

    # 2. Seed Batch & Two Sections (Section A, Section B)
    batch = AdmissionBatch(
        id="batch_aiml_2024",
        name="AIML-2024-2028",
        department_id="AIML",
        academic_year="2024-2028",
        is_active=True,
        created_by=admin.username,
    )
    await batch.insert()

    sec_a = BatchClass(
        id="class_batch_aiml_sec_a",
        batch_id="batch_aiml_2024",
        class_name="Section A",
        department="AIML",
        section="A",
        academic_year="2024-2028",
    )
    await sec_a.insert()

    sec_b = BatchClass(
        id="class_batch_aiml_sec_b",
        batch_id="batch_aiml_2024",
        class_name="Section B",
        department="AIML",
        section="B",
        academic_year="2024-2028",
    )
    await sec_b.insert()

    # 3. Create Upload Link for Section A
    link_a = UploadLink(
        department_id=dept.id,
        batch_id=batch.id,
        class_id=sec_a.id,
        token="token_sec_a",
        slug="portal-sec-a",
        title="Section A Upload Portal",
        is_active=True,
        created_by=admin.username,
    )
    await link_a.insert()

    # 4. Create Upload Link for Section B
    link_b = UploadLink(
        department_id=dept.id,
        batch_id=batch.id,
        class_id=sec_b.id,
        token="token_sec_b",
        slug="portal-sec-b",
        title="Section B Upload Portal",
        is_active=True,
        created_by=admin.username,
    )
    await link_b.insert()

    # 5. Submit Student 1 via Section A token (without frontend passing class_id to verify server resolution)
    payload_student_1 = {
        "batch_id": "batch_aiml_2024",
        "batch_name": "AIML-2024-2028",
        "token": "token_sec_a",
        "student_name": "Arun Kumar",
        "register_number": "AIML24001",
        "mobile_number": "9876543210",
        "email": "arun@test.edu",
        "submission_status": "Verified",
        "documents": [
            {
                "document_name": "10th Marksheet",
                "status": "Uploaded",
                "file_path": "uploads/batch_aiml_2024/AIML24001/10th.pdf",
            }
        ],
        "extracted_data": {"Name": "Arun Kumar", "Reg No": "AIML24001"},
    }
    resp1 = await client_async.post("/student-submissions/confirm", json=payload_student_1)
    assert resp1.status_code == 200, f"Submission failed: {resp1.text}"
    sub1_data = resp1.json()
    # Server must have derived Section A's class_id and upload_link_id from the token
    assert sub1_data["class_id"] == sec_a.id
    assert sub1_data["class_name"] == "Section A"
    assert sub1_data["upload_link_id"] == str(link_a.id)

    # 6. Submit Student 2 via Section B token
    payload_student_2 = {
        "batch_id": "batch_aiml_2024",
        "batch_name": "AIML-2024-2028",
        "token": "token_sec_b",
        "student_name": "Bala Murugan",
        "register_number": "AIML24002",
        "mobile_number": "9876543211",
        "email": "bala@test.edu",
        "submission_status": "Verified",
        "documents": [
            {
                "document_name": "10th Marksheet",
                "status": "Uploaded",
                "file_path": "uploads/batch_aiml_2024/AIML24002/10th.pdf",
            }
        ],
        "extracted_data": {"Name": "Bala Murugan", "Reg No": "AIML24002"},
    }
    resp2 = await client_async.post("/student-submissions/confirm", json=payload_student_2)
    assert resp2.status_code == 200, f"Submission failed: {resp2.text}"
    sub2_data = resp2.json()
    assert sub2_data["class_id"] == sec_b.id
    assert sub2_data["class_name"] == "Section B"

    # 7. Query Section A students endpoint
    resp_a = await client_async.get(f"/classes/{sec_a.id}/students", headers=auth_headers)
    assert resp_a.status_code == 200
    sec_a_students = resp_a.json()
    assert len(sec_a_students) == 1
    assert sec_a_students[0]["register_number"] == "AIML24001"
    assert sec_a_students[0]["student_name"] == "Arun Kumar"
    assert sec_a_students[0]["class_id"] == sec_a.id

    # 8. Query Section B students endpoint
    resp_b = await client_async.get(f"/classes/{sec_b.id}/students", headers=auth_headers)
    assert resp_b.status_code == 200
    sec_b_students = resp_b.json()
    assert len(sec_b_students) == 1
    assert sec_b_students[0]["register_number"] == "AIML24002"
    assert sec_b_students[0]["student_name"] == "Bala Murugan"
    assert sec_b_students[0]["class_id"] == sec_b.id

    # 9. Verify Section B students NEVER appear in Section A (Zero Leaks)
    sec_a_reg_nums = [s["register_number"] for s in sec_a_students]
    assert "AIML24002" not in sec_a_reg_nums

    # 10. Query Section A upload links endpoint
    resp_links_a = await client_async.get(f"/classes/{sec_a.id}/upload-links", headers=auth_headers)
    assert resp_links_a.status_code == 200
    links_a = resp_links_a.json()
    assert len(links_a) == 1
    assert links_a[0]["token"] == "token_sec_a"
    assert links_a[0]["class_id"] == sec_a.id


@pytest.mark.asyncio
async def test_section_card_statistics(client_async: AsyncClient):
    """
    Verify:
    1. Section card statistics (students, pending, verified, rejected) are computed strictly
       from MongoDB based on batch_id + class_id.
    2. Section A counts never mix with Section B counts.
    3. Both GET /batches/{batch_id}/classes and GET /classes/{class_id}/stats return exact figures.
    """
    admin = User(
        username="admin_user2",
        name="Admin User 2",
        email="admin2@test.edu",
        password="hashedpassword",
        role=UserRole.SUPER_ADMIN,
        is_active=True,
    )
    await admin.insert()
    admin_token = create_access_token(data={"sub": str(admin.id), "role": "super_admin"})
    auth_headers = {"Authorization": f"Bearer {admin_token}"}

    dept = Department(name="Artificial Intelligence", code="AIML", intake_capacity=60, created_by=admin.username)
    await dept.insert()

    batch = AdmissionBatch(
        id="batch_stats_test",
        name="AIML-2024-2028",
        department_id="AIML",
        academic_year="2024-2028",
        is_active=True,
        created_by=admin.username,
    )
    await batch.insert()

    sec_a = BatchClass(
        id="class_stats_sec_a",
        batch_id="batch_stats_test",
        class_name="Section A",
        department="AIML",
        section="A",
        academic_year="2024-2028",
    )
    await sec_a.insert()

    sec_b = BatchClass(
        id="class_stats_sec_b",
        batch_id="batch_stats_test",
        class_name="Section B",
        department="AIML",
        section="B",
        academic_year="2024-2028",
    )
    await sec_b.insert()

    link_a = UploadLink(
        department_id=dept.id,
        batch_id=batch.id,
        class_id=sec_a.id,
        token="token_stats_a",
        slug="portal-stats-a",
        title="Section A Upload Portal",
        is_active=True,
        created_by=admin.username,
    )
    await link_a.insert()

    link_b = UploadLink(
        department_id=dept.id,
        batch_id=batch.id,
        class_id=sec_b.id,
        token="token_stats_b",
        slug="portal-stats-b",
        title="Section B Upload Portal",
        is_active=True,
        created_by=admin.username,
    )
    await link_b.insert()

    # Section A: 3 submissions (1 Verified, 1 Pending/Submitted, 1 Rejected)
    sub_a1 = StudentSubmission(
        batch_id=batch.id,
        class_id=sec_a.id,
        student_name="Student A1",
        register_number="REG_A1",
        mobile_number="1111111111",
        submission_status="Verified",
    )
    await sub_a1.insert()

    sub_a2 = StudentSubmission(
        batch_id=batch.id,
        class_id=sec_a.id,
        student_name="Student A2",
        register_number="REG_A2",
        mobile_number="2222222222",
        submission_status="Submitted",
    )
    await sub_a2.insert()

    sub_a3 = StudentSubmission(
        batch_id=batch.id,
        class_id=sec_a.id,
        student_name="Student A3",
        register_number="REG_A3",
        mobile_number="3333333333",
        submission_status="Rejected",
    )
    await sub_a3.insert()

    # Section B: 2 submissions (1 Verified, 1 Verification Pending)
    sub_b1 = StudentSubmission(
        batch_id=batch.id,
        class_id=sec_b.id,
        student_name="Student B1",
        register_number="REG_B1",
        mobile_number="4444444444",
        submission_status="Verified",
    )
    await sub_b1.insert()

    sub_b2 = StudentSubmission(
        batch_id=batch.id,
        class_id=sec_b.id,
        student_name="Student B2",
        register_number="REG_B2",
        mobile_number="5555555555",
        submission_status="Verification Pending",
    )
    await sub_b2.insert()

    # 1. Test GET /batches/{batch_id}/classes returns stats for both sections
    resp = await client_async.get(f"/batches/{batch.id}/classes", headers=auth_headers)
    assert resp.status_code == 200
    classes = resp.json()
    assert len(classes) == 2

    class_a_data = next(c for c in classes if c["id"] == sec_a.id)
    assert class_a_data["stats"]["students"] == 3
    assert class_a_data["stats"]["pending"] == 1
    assert class_a_data["stats"]["verified"] == 1
    assert class_a_data["stats"]["rejected"] == 1

    class_b_data = next(c for c in classes if c["id"] == sec_b.id)
    assert class_b_data["stats"]["students"] == 2
    assert class_b_data["stats"]["pending"] == 1
    assert class_b_data["stats"]["verified"] == 1
    assert class_b_data["stats"]["rejected"] == 0

    # 2. Test GET /classes/{sec_a.id}/stats returns exact stats
    resp_stats_a = await client_async.get(f"/classes/{sec_a.id}/stats", headers=auth_headers)
    assert resp_stats_a.status_code == 200
    stats_a = resp_stats_a.json()
    assert stats_a == {"students": 3, "pending": 1, "verified": 1, "rejected": 1}

    # 3. Test GET /classes/{sec_b.id}/stats returns exact stats
    resp_stats_b = await client_async.get(f"/classes/{sec_b.id}/stats", headers=auth_headers)
    assert resp_stats_b.status_code == 200
    stats_b = resp_stats_b.json()
    assert stats_b == {"students": 2, "pending": 1, "verified": 1, "rejected": 0}


"""
Regression Test Suite for Production-Only Bugs:
1. Data Extraction page: /data-extractions/batches endpoint availability, RBAC, and department isolation.
2. Student document upload: /student/verify and /student-submissions/upload succeed without pre-configured student roster or Excel template.
"""

import io
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from motor.motor_asyncio import AsyncIOMotorClient

from app.main import app
from app.core.config import settings
from app.core.security import create_access_token, get_password_hash
from app.models.user import User, UserRole
from app.models.batch import AdmissionBatch
from app.models.department import Department
from app.models.upload_link import UploadLink
from app.models.student_submission import StudentSubmission
from app.models.student_document import StudentDocument


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    import app.db.database as db_mod
    db_mod.client = AsyncIOMotorClient(settings.MONGODB_URI, serverSelectionTimeoutMS=2000)
    db_mod.db = db_mod.client[settings.DATABASE_NAME]
    await db_mod._run_db_setup()


@pytest_asyncio.fixture
async def client_async():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_regression_data_extractions_batches_endpoint_available_and_authorized(client_async: AsyncClient):
    """
    Issue 1 Regression:
    Ensure /data-extractions/batches exists and is NOT a 404 Not Found.
    Ensure unauthenticated requests are rejected with 401 Unauthorized.
    Ensure authenticated Super Admin and Department Admin receive 200 OK with authorized batches.
    """
    # 1. Unauthenticated request must return 401, NEVER 404 Not Found
    res_unauth = await client_async.get("/data-extractions/batches")
    assert res_unauth.status_code == 401, f"Expected 401 Unauthorized, got {res_unauth.status_code}: {res_unauth.text}"
    assert res_unauth.json().get("detail") != "Not Found"

    # Setup test departments and batches
    await AdmissionBatch.find(AdmissionBatch.id == "batch_aiml_prod_bug").delete()
    await AdmissionBatch.find(AdmissionBatch.id == "batch_cse_prod_bug").delete()
    await User.find(User.username == "test_super_admin_bug").delete()
    await User.find(User.username == "test_dept_admin_bug").delete()

    b_aiml = AdmissionBatch(
        id="batch_aiml_prod_bug",
        name="AIML Batch 2026",
        department_id="AIML",
        academic_year="2026-2027",
        created_by="admin",
        status="active",
    )
    await b_aiml.save()

    b_cse = AdmissionBatch(
        id="batch_cse_prod_bug",
        name="CSE Batch 2026",
        department_id="CSE",
        academic_year="2026-2027",
        created_by="admin",
        status="active",
    )
    await b_cse.save()

    # 2. Super Admin receives all batches
    super_user = User(
        username="test_super_admin_bug",
        name="Super Admin Tester",
        password=get_password_hash("pass123"),
        role=UserRole.SUPER_ADMIN,
        is_active=True,
    )
    await super_user.save()

    super_admin_token = create_access_token({"sub": str(super_user.id), "role": super_user.role.value})
    headers_super = {"Authorization": f"Bearer {super_admin_token}"}
    res_super = await client_async.get("/data-extractions/batches", headers=headers_super)
    assert res_super.status_code == 200, f"Expected 200, got {res_super.status_code}: {res_super.text}"
    data_super = res_super.json()
    batch_ids_super = [b["batch_id"] for b in data_super]
    assert "batch_aiml_prod_bug" in batch_ids_super
    assert "batch_cse_prod_bug" in batch_ids_super

    # 3. Department Admin (AIML) only receives AIML batches (department-level access control)
    dept_user = User(
        username="test_dept_admin_bug",
        name="AIML Admin Tester",
        password=get_password_hash("pass123"),
        role=UserRole.DEPARTMENT_ADMIN,
        department_code="AIML",
        is_active=True,
    )
    await dept_user.save()

    dept_admin_token = create_access_token({
        "sub": str(dept_user.id),
        "role": dept_user.role.value,
        "department_code": "AIML",
    })
    headers_dept = {"Authorization": f"Bearer {dept_admin_token}"}
    res_dept = await client_async.get("/data-extractions/batches", headers=headers_dept)
    assert res_dept.status_code == 200, f"Expected 200, got {res_dept.status_code}: {res_dept.text}"
    data_dept = res_dept.json()
    batch_ids_dept = [b["batch_id"] for b in data_dept]
    assert "batch_aiml_prod_bug" in batch_ids_dept
    assert "batch_cse_prod_bug" not in batch_ids_dept, "Department isolation breached: CSE batch visible to AIML admin"


@pytest.mark.asyncio
async def test_regression_student_upload_without_preconfigured_roster_or_excel(client_async: AsyncClient):
    """
    Issue 2 Regression:
    Ensure student document upload flow succeeds without requiring a pre-uploaded
    Excel template or student roster.
    Prevents the 'Student list has not been configured for this batch' 503 error.
    """
    # Create department, batch, and upload link without any student roster or Excel template
    dept = await Department.find_one(Department.code == "ECE")
    if not dept:
        dept = Department(name="Electronics & Communication", code="ECE", created_by="admin", is_active=True)
        await dept.save()

    batch_id = "batch_ece_no_roster"
    await AdmissionBatch.find(AdmissionBatch.id == batch_id).delete()
    await StudentSubmission.find(StudentSubmission.batch_id == batch_id).delete()
    await StudentDocument.find(StudentDocument.batch_id == batch_id).delete()
    await UploadLink.find(UploadLink.slug == "ece-open-upload-link").delete()

    batch = AdmissionBatch(
        id=batch_id,
        name="ECE Open Batch 2026",
        department_id="ECE",
        academic_year="2026-2030",
        created_by="admin",
        status="active",
    )
    await batch.save()

    link = UploadLink(
        department_id=dept.id,
        batch_id=batch.id,
        token="ece-open-token-2026",
        slug="ece-open-upload-link",
        title="ECE Open Document Portal",
        is_active=True,
        created_by="admin",
    )
    await link.save()

    # Step 1: Student verification with NO pre-configured students / roster
    verify_payload = {
        "token": link.slug,
        "student_name": "Kavitha Sundaram",
        "register_number": "26EC501",
        "mobile_number": "9876543210",
        "email": "kavitha.s@example.com",
    }
    res_verify = await client_async.post("/student/verify", json=verify_payload)
    # MUST return 200 OK, NEVER 503 "Student list has not been configured"
    assert res_verify.status_code == 200, f"Expected 200 OK, got {res_verify.status_code}: {res_verify.text}"
    verify_data = res_verify.json()
    assert verify_data["batch_id"] == batch_id
    assert verify_data["batch_name"] == batch.name
    assert verify_data["submission_id"] is not None

    # Step 2: Student document upload via multipart form
    sample_file_bytes = b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n%%EOF"
    upload_files = [
        ("files", ("aadhaar.pdf", io.BytesIO(sample_file_bytes), "application/pdf")),
    ]
    metadata_json = '[{"document_name": "Aadhaar Card", "document_type": "AADHAAR", "filename": "aadhaar.pdf", "file_index": 0, "is_new_file": true, "status": "Uploaded"}]'
    form_data = {
        "batch_id": batch_id,
        "register_number": "26EC501",
        "student_name": "Kavitha Sundaram",
        "mobile_number": "9876543210",
        "email": "kavitha.s@example.com",
        "token": link.slug,
        "documents_metadata": metadata_json,
    }

    res_upload = await client_async.post("/student-submissions/upload", data=form_data, files=upload_files)
    assert res_upload.status_code == 201, f"Expected 201 Created, got {res_upload.status_code}: {res_upload.text}"
    upload_data = res_upload.json()
    assert upload_data["register_number"] == "26EC501"
    assert upload_data["student_name"] == "Kavitha Sundaram"
    assert len(upload_data["documents"]) == 1
    assert upload_data["documents"][0]["document_name"] == "Aadhaar Card"
    assert upload_data["documents"][0]["status"] == "Uploaded"

    # Step 3: Verify StudentDocument record exists and is mapped to student and batch
    saved_doc = await StudentDocument.find_one(
        StudentDocument.student_id == "26EC501",
        StudentDocument.batch_id == batch_id,
    )
    assert saved_doc is not None
    assert saved_doc.current_version == 1
    assert saved_doc.active_version is not None
    assert saved_doc.active_version.original_filename == "aadhaar.pdf"

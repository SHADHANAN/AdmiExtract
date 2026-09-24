import io
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from pypdf import PdfReader
from bson import ObjectId

from app.main import app
from app.db.database import _run_db_setup
from app.core.security import create_access_token, get_password_hash
from app.models.user import User, UserRole
from app.models.student_submission import StudentSubmission, StudentDocumentMeta
from app.models.audit_log import AuditLog


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    import app.db.database as db_mod
    from app.core.config import settings
    from motor.motor_asyncio import AsyncIOMotorClient
    
    db_mod.client = AsyncIOMotorClient(settings.MONGODB_URI, serverSelectionTimeoutMS=2000)
    db_mod.db = db_mod.client[settings.DATABASE_NAME]
    await db_mod._run_db_setup()


@pytest_asyncio.fixture
async def client_async():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_download_all_documents_full_flow(client_async: AsyncClient):
    """
    Test that authenticated staff can download all documents for a student as a merged PDF.
    Validates:
      - 200 OK
      - Content-Type: application/pdf
      - Content-Disposition: attachment; filename="Shadhanan_24AM093_All_Documents.pdf"
      - Merged PDF contains all valid pages (image converted to PDF + PDF documents)
      - Unavailable documents are skipped without creating fake pages
      - AuditLog record is created
    """
    # 1. Super Admin user and token
    admin_user = await User.find_one({"role": UserRole.SUPER_ADMIN})
    if not admin_user:
        admin_user = await User(
            username="admin_download_test",
            name="Super Admin",
            password=get_password_hash("admin123"),
            role=UserRole.SUPER_ADMIN,
        ).insert()

    admin_token = create_access_token(
        data={"sub": str(admin_user.id), "role": UserRole.SUPER_ADMIN.value}
    )

    # 2. Get Shadhanan submission (has 4 uploaded, 2 unavailable)
    sub = await StudentSubmission.find_one({"register_number": "24AM093"})
    assert sub is not None, "Shadhanan test submission not found"
    sub_id = str(sub.id)

    # Clear previous audit logs for this test
    await AuditLog.find({"submission_id": sub_id, "action": "DOWNLOAD_ALL_DOCUMENTS"}).delete()

    # 3. GET /student-submissions/{sub_id}/documents/download-all
    res = await client_async.get(
        f"/student-submissions/{sub_id}/documents/download-all",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert res.status_code == 200
    assert res.headers.get("content-type") == "application/pdf"
    assert "attachment" in res.headers.get("content-disposition", "")
    assert "Shadhanan_24AM093_All_Documents.pdf" in res.headers.get("content-disposition", "")
    assert res.content.startswith(b"%PDF")

    # 4. Verify merged PDF structure
    reader = PdfReader(io.BytesIO(res.content))
    # Shadhanan has:
    # - Aadhaar Card: 1 PNG image -> 1 PDF page
    # - Community Certificate: 1 PDF page
    # - Passbook: 2 PDF pages
    # - Transfer Certificate: 1 PDF page
    # Total = 5 pages
    assert len(reader.pages) == 5

    # 5. Verify AuditLog was created
    audit = await AuditLog.find_one({"submission_id": sub_id, "action": "DOWNLOAD_ALL_DOCUMENTS"})
    assert audit is not None
    assert audit.action == "DOWNLOAD_ALL_DOCUMENTS"
    assert audit.student_name == sub.student_name
    assert audit.register_number == sub.register_number
    assert audit.documents_count == 4
    assert audit.result == "SUCCESS"


@pytest.mark.asyncio
async def test_download_all_documents_alias_endpoint(client_async: AsyncClient):
    """Test that /submissions/{sub_id}/documents/download-all alias functions identically."""
    admin_user = await User.find_one({"role": UserRole.SUPER_ADMIN})
    admin_token = create_access_token(
        data={"sub": str(admin_user.id), "role": UserRole.SUPER_ADMIN.value}
    )

    sub = await StudentSubmission.find_one({"register_number": "24AM093"})
    assert sub is not None
    sub_id = str(sub.id)

    res = await client_async.get(
        f"/submissions/{sub_id}/documents/download-all",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 200
    assert res.headers.get("content-type") == "application/pdf"
    assert res.content.startswith(b"%PDF")


@pytest.mark.asyncio
async def test_download_all_documents_security_unauthenticated(client_async: AsyncClient):
    """Test that unauthenticated requests are rejected with 401."""
    sub = await StudentSubmission.find_one({"register_number": "24AM093"})
    assert sub is not None

    res = await client_async.get(f"/student-submissions/{str(sub.id)}/documents/download-all")
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_download_all_documents_security_student_role_forbidden(client_async: AsyncClient):
    """Test that student users cannot call Download All (403 Forbidden)."""
    student_user = await User.find_one({"role": UserRole.STUDENT})
    if not student_user:
        student_user = await User(
            username="test_student_dl",
            name="Test Student",
            password=get_password_hash("pass123"),
            role=UserRole.STUDENT,
        ).insert()

    student_token = create_access_token(
        data={"sub": str(student_user.id), "role": UserRole.STUDENT.value}
    )

    sub = await StudentSubmission.find_one({"register_number": "24AM093"})
    assert sub is not None

    res = await client_async.get(
        f"/student-submissions/{str(sub.id)}/documents/download-all",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_download_all_documents_security_department_isolation(client_async: AsyncClient):
    """Test that department admin from another department cannot download student's documents."""
    await User.find({"username": "dept_admin_other_test"}).delete()
    other_dept_admin = await User(
        username="dept_admin_other_test",
        name="Other Dept Admin",
        password=get_password_hash("pass123"),
        role=UserRole.DEPARTMENT_ADMIN,
        department_code="OTHER_DEPT",
    ).insert()

    other_token = create_access_token(
        data={"sub": str(other_dept_admin.id), "role": UserRole.DEPARTMENT_ADMIN.value}
    )

    sub = await StudentSubmission.find_one({"register_number": "24AM093"})
    assert sub is not None

    res = await client_async.get(
        f"/student-submissions/{str(sub.id)}/documents/download-all",
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert res.status_code == 403

    # Cleanup
    await other_dept_admin.delete()


@pytest.mark.asyncio
async def test_download_all_documents_empty_case(client_async: AsyncClient):
    """Test that a student submission with zero uploaded documents returns 404 with appropriate message."""
    admin_user = await User.find_one({"role": UserRole.SUPER_ADMIN})
    admin_token = create_access_token(
        data={"sub": str(admin_user.id), "role": UserRole.SUPER_ADMIN.value}
    )

    # Create dummy submission with no uploaded documents
    empty_sub = await StudentSubmission(
        batch_id="batch_empty_test",
        student_name="No Docs Student",
        register_number="EMPTY001",
        mobile_number="9999999999",
        documents=[
            StudentDocumentMeta(document_name="Aadhaar Card", status="Not Available"),
            StudentDocumentMeta(document_name="Transfer Certificate", status="Pending"),
        ],
    ).insert()

    res = await client_async.get(
        f"/student-submissions/{str(empty_sub.id)}/documents/download-all",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 404
    assert "No documents available for download" in res.json().get("detail", "")

    # Cleanup
    await empty_sub.delete()

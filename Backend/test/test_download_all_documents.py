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


async def ensure_shadhanan_student() -> StudentSubmission:
    sub = await StudentSubmission.find_one({"register_number": "24AM093"})

    from pathlib import Path
    from PIL import Image
    from pypdf import PdfWriter

    base_dir = Path(__file__).resolve().parent.parent / "uploads" / "students" / "24AM093" / "documents"
    base_dir.mkdir(parents=True, exist_ok=True)

    # 1. Aadhaar PNG
    aadhaar_dir = base_dir / "AADHAAR"
    aadhaar_dir.mkdir(parents=True, exist_ok=True)
    aadhaar_path = aadhaar_dir / "aadhaar.png"
    img = Image.new("RGB", (200, 200), color="blue")
    img.save(aadhaar_path)

    # 2. Community PDF (1 page)
    comm_dir = base_dir / "COMMUNITY_CERTIFICATE"
    comm_dir.mkdir(parents=True, exist_ok=True)
    comm_path = comm_dir / "community.pdf"
    writer1 = PdfWriter()
    writer1.add_blank_page(width=200, height=200)
    with open(comm_path, "wb") as f:
        writer1.write(f)

    # 3. Passbook PDF (2 pages)
    pb_dir = base_dir / "PASSBOOK"
    pb_dir.mkdir(parents=True, exist_ok=True)
    pb_path = pb_dir / "passbook.pdf"
    writer2 = PdfWriter()
    writer2.add_blank_page(width=200, height=200)
    writer2.add_blank_page(width=200, height=200)
    with open(pb_path, "wb") as f:
        writer2.write(f)

    # 4. Transfer Certificate PDF (1 page)
    tc_dir = base_dir / "TRANSFER_CERTIFICATE"
    tc_dir.mkdir(parents=True, exist_ok=True)
    tc_path = tc_dir / "tc.pdf"
    writer3 = PdfWriter()
    writer3.add_blank_page(width=200, height=200)
    with open(tc_path, "wb") as f:
        writer3.write(f)

    if not sub:
        sub = StudentSubmission(
            batch_id="batch_shadhanan_test",
            department_id="CS_DEPT",
            student_name="Shadhanan",
            register_number="24AM093",
            mobile_number="9876543210",
            submission_status="Submitted",
            documents=[
                StudentDocumentMeta(document_name="Aadhaar Card", document_type="AADHAAR", status="Uploaded", file_path=str(aadhaar_path), file_size_mb=0.1),
                StudentDocumentMeta(document_name="Community Certificate", document_type="COMMUNITY_CERTIFICATE", status="Uploaded", file_path=str(comm_path), file_size_mb=0.1),
                StudentDocumentMeta(document_name="Passbook", document_type="PASSBOOK", status="Uploaded", file_path=str(pb_path), file_size_mb=0.1),
                StudentDocumentMeta(document_name="Transfer Certificate", document_type="TRANSFER_CERTIFICATE", status="Uploaded", file_path=str(tc_path), file_size_mb=0.1),
                StudentDocumentMeta(document_name="HSC Marksheet", document_type="HSC_MARKSHEET", status="Not Available"),
                StudentDocumentMeta(document_name="SSLC Marksheet", document_type="SSLC_MARKSHEET", status="Not Available"),
            ],
        )
        await sub.insert()
    else:
        sub.department_id = "CS_DEPT"
        sub.documents = [
            StudentDocumentMeta(document_name="Aadhaar Card", document_type="AADHAAR", status="Uploaded", file_path=str(aadhaar_path), file_size_mb=0.1),
            StudentDocumentMeta(document_name="Community Certificate", document_type="COMMUNITY_CERTIFICATE", status="Uploaded", file_path=str(comm_path), file_size_mb=0.1),
            StudentDocumentMeta(document_name="Passbook", document_type="PASSBOOK", status="Uploaded", file_path=str(pb_path), file_size_mb=0.1),
            StudentDocumentMeta(document_name="Transfer Certificate", document_type="TRANSFER_CERTIFICATE", status="Uploaded", file_path=str(tc_path), file_size_mb=0.1),
            StudentDocumentMeta(document_name="HSC Marksheet", document_type="HSC_MARKSHEET", status="Not Available"),
            StudentDocumentMeta(document_name="SSLC Marksheet", document_type="SSLC_MARKSHEET", status="Not Available"),
        ]
        await sub.save()

    return sub


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
    sub = await ensure_shadhanan_student()
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

    sub = await ensure_shadhanan_student()
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
    sub = await ensure_shadhanan_student()
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

    sub = await ensure_shadhanan_student()
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

    sub = await ensure_shadhanan_student()
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

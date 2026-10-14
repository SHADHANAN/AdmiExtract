from pathlib import Path
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient

from app.main import app
from app.core.config import settings
from app.core.security import create_access_token, get_password_hash
from app.models.user import UserRole
from app.utils.file_security import (
    format_document_download_filename,
    build_content_disposition_header,
)


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


@pytest_asyncio.fixture
async def db_client():
    client = AsyncIOMotorClient(settings.MONGODB_URI)
    db = client[settings.DATABASE_NAME]
    yield db
    client.close()


# ==============================================================================
# 1. UNIT TESTS: Filename Formatting, Sanitization, Unicode, and Fallbacks
# ==============================================================================

def test_filename_formatting_exact_specification_examples():
    """Verify the exact format: RegisterNumber_StudentName_DocumentName.extension"""
    # Example 1: 23CS001_Arun_Kumar_Aadhaar_Card.jpg
    fn1 = format_document_download_filename(
        register_number="23CS001",
        student_name="Arun Kumar",
        document_name="Aadhaar Card",
        original_filename="scan101.jpg",
    )
    assert fn1 == "23CS001_Arun_Kumar_Aadhaar_Card.jpg"

    # Example 2: 23CS001_Arun_Kumar_Community_Certificate.pdf
    fn2 = format_document_download_filename(
        register_number="23CS001",
        student_name="Arun Kumar",
        document_name="Community Certificate",
        original_filename="comm_cert.pdf",
    )
    assert fn2 == "23CS001_Arun_Kumar_Community_Certificate.pdf"

    # Example 3: 23CS001_Arun_Kumar_12th_HSC_Marksheet.jpg
    fn3 = format_document_download_filename(
        register_number="23CS001",
        student_name="Arun Kumar",
        document_name="12th HSC Marksheet",
        original_filename="marksheet.jpg",
    )
    assert fn3 == "23CS001_Arun_Kumar_12th_HSC_Marksheet.jpg"


def test_filename_extension_preservation():
    """Verify various file extensions are preserved correctly."""
    fn_pdf = format_document_download_filename("REG101", "Jane Doe", "Doc", original_filename="my.doc.PDF")
    assert fn_pdf == "REG101_Jane_Doe_Doc.pdf"

    fn_png = format_document_download_filename("REG102", "Jane Doe", "Doc", original_filename="photo.PNG")
    assert fn_png == "REG102_Jane_Doe_Doc.png"

    fn_jpeg = format_document_download_filename("REG103", "Jane Doe", "Doc", original_filename="photo.jpeg")
    assert fn_jpeg == "REG103_Jane_Doe_Doc.jpeg"

    # Fallback to mime_type extension when original_filename has no extension
    fn_mime = format_document_download_filename("REG104", "Jane Doe", "Doc", original_filename="blob", mime_type="image/jpeg")
    assert fn_mime == "REG104_Jane_Doe_Doc.jpg"


def test_filename_sanitization_unsafe_characters():
    """Verify illegal OS filename characters (slash, colon, quotes, pipe, etc.) are sanitized safely."""
    fn = format_document_download_filename(
        register_number="23/CS:001",
        student_name='Arun "Super" Kumar?',
        document_name="10th / SSC * Marksheet <Final>",
        original_filename="upload.pdf",
    )
    assert fn == "23_CS_001_Arun_Super_Kumar_10th_SSC_Marksheet_Final.pdf"


def test_filename_preserves_unicode_and_non_english_names():
    """Verify non-English and Unicode characters (e.g., Tamil, accented Latin) are preserved."""
    fn_tamil = format_document_download_filename(
        register_number="23CS009",
        student_name="அருண் குமார்",
        document_name="சான்றிதழ்",
        original_filename="tamil_doc.pdf",
    )
    assert fn_tamil == "23CS009_அருண்_குமார்_சான்றிதழ்.pdf"

    fn_accent = format_document_download_filename(
        register_number="23CS010",
        student_name="José García",
        document_name="Identificación Oficial",
        original_filename="doc.pdf",
    )
    assert fn_accent == "23CS010_José_García_Identificación_Oficial.pdf"


def test_filename_strips_version_suffix():
    """Verify version numbers like ' (v2)' in document names are cleaned from filename."""
    fn = format_document_download_filename(
        register_number="23CS001",
        student_name="Arun Kumar",
        document_name="10th Marksheet (v2)",
        original_filename="marks.pdf",
    )
    assert fn == "23CS001_Arun_Kumar_10th_Marksheet.pdf"


def test_filename_missing_fields_safe_fallbacks():
    """Verify safe fallbacks when register_number, student_name, or document_name are missing."""
    # Missing register number
    fn_no_reg = format_document_download_filename(
        register_number=None,
        student_name="Arun Kumar",
        document_name="Aadhaar Card",
        original_filename="doc.pdf",
    )
    assert fn_no_reg == "STUDENT_Arun_Kumar_Aadhaar_Card.pdf"

    # Missing student name
    fn_no_name = format_document_download_filename(
        register_number="23CS001",
        student_name=None,
        document_name="Aadhaar Card",
        original_filename="doc.pdf",
    )
    assert fn_no_name == "23CS001_UNKNOWN_Aadhaar_Card.pdf"

    # Missing document name
    fn_no_doc = format_document_download_filename(
        register_number="23CS001",
        student_name="Arun Kumar",
        document_name="",
        original_filename="doc.pdf",
    )
    assert fn_no_doc == "23CS001_Arun_Kumar_Document.pdf"

    # All fields missing
    fn_all_missing = format_document_download_filename(
        register_number="",
        student_name="",
        document_name=None,
        original_filename=None,
    )
    assert fn_all_missing == "STUDENT_UNKNOWN_Document.pdf"


def test_content_disposition_header_rfc_encoding():
    """Verify RFC 6266 / RFC 5987 header formatting."""
    # ASCII filename
    h_ascii = build_content_disposition_header("23CS001_Arun_Kumar_Aadhaar_Card.jpg", disposition_type="inline")
    assert h_ascii == 'inline; filename="23CS001_Arun_Kumar_Aadhaar_Card.jpg"'

    # Unicode filename
    h_uni = build_content_disposition_header("23CS009_அருண்_குமார்_சான்றிதழ்.pdf", disposition_type="attachment")
    assert "attachment;" in h_uni
    assert "filename*=UTF-8''" in h_uni
    assert "%E0%AE%85%E0%AE%B0%E0%AF%81%E0%AE%A3%E0%AF%8D" in h_uni


# ==============================================================================
# 2. INTEGRATION TESTS: Student Submission Document Download & Security
# ==============================================================================

@pytest.mark.asyncio
async def test_student_submission_download_filename_and_security(client_async: AsyncClient, db_client):
    backend_root = Path(__file__).resolve().parent.parent
    uploads_dir = backend_root / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)

    test_file = uploads_dir / "test_download_filename_aadhaar.pdf"
    content = b"%PDF-1.4\n" + b"TEST_CONTENT_FOR_DOWNLOAD" * 50 + b"\n%%EOF"
    test_file.write_bytes(content)

    # Setup department admins
    cs_user = await db_client["users"].find_one({"username": "test_cs_filename_admin"})
    if not cs_user:
        res_cs = await db_client["users"].insert_one({
            "username": "test_cs_filename_admin",
            "name": "CS Admin",
            "email": "cs_fn_admin@test.com",
            "password": get_password_hash("admin123"),
            "role": UserRole.DEPARTMENT_ADMIN.value,
            "department_code": "CS",
        })
        cs_id = str(res_cs.inserted_id)
    else:
        cs_id = str(cs_user["_id"])

    mech_user = await db_client["users"].find_one({"username": "test_mech_filename_admin"})
    if not mech_user:
        res_mech = await db_client["users"].insert_one({
            "username": "test_mech_filename_admin",
            "name": "Mech Admin",
            "email": "mech_fn_admin@test.com",
            "password": get_password_hash("admin123"),
            "role": UserRole.DEPARTMENT_ADMIN.value,
            "department_code": "MECH",
        })
        mech_id = str(res_mech.inserted_id)
    else:
        mech_id = str(mech_user["_id"])

    cs_token = create_access_token(data={"sub": cs_id, "role": UserRole.DEPARTMENT_ADMIN.value})
    mech_token = create_access_token(data={"sub": mech_id, "role": UserRole.DEPARTMENT_ADMIN.value})

    # Insert student submission in CS department
    ins = await db_client["student_submissions"].insert_one({
        "batch_id": "batch_fn_test",
        "department_id": "CS",
        "student_name": "Arun Kumar",
        "register_number": "23CS001",
        "normalized_register_number": "23cs001",
        "mobile_number": "9876543210",
        "submission_status": "Submitted",
        "documents": [
            {
                "document_name": "Aadhaar Card",
                "status": "Uploaded",
                "file_path": str(test_file),
            },
        ],
    })
    sub_id = str(ins.inserted_id)

    try:
        # 1. Unauthenticated download -> 401
        res_unauth = await client_async.get(f"/student-submissions/{sub_id}/documents/0/file")
        assert res_unauth.status_code == 401

        # 2. Unauthorized cross-department admin -> 403
        res_cross = await client_async.get(
            f"/student-submissions/{sub_id}/documents/0/file",
            headers={"Authorization": f"Bearer {mech_token}"},
        )
        assert res_cross.status_code == 403

        # 3. Authorized CS department admin -> 200 with exact filename format
        res_auth = await client_async.get(
            f"/student-submissions/{sub_id}/documents/0/file",
            headers={"Authorization": f"Bearer {cs_token}"},
        )
        assert res_auth.status_code == 200
        cd = res_auth.headers.get("content-disposition", "")
        assert "23CS001_Arun_Kumar_Aadhaar_Card.pdf" in cd
        assert res_auth.content == content

    finally:
        await db_client["student_submissions"].delete_one({"_id": ObjectId(sub_id)})
        if test_file.exists():
            try:
                test_file.unlink()
            except Exception:
                pass


# ==============================================================================
# 3. INTEGRATION TESTS: Student Document Version File Download
# ==============================================================================

@pytest.mark.asyncio
async def test_student_document_version_download_filename(client_async: AsyncClient, db_client):
    backend_root = Path(__file__).resolve().parent.parent
    uploads_dir = backend_root / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)

    version_file = uploads_dir / "test_version_file.jpg"
    version_content = b"\xFF\xD8\xFF\xE0" + b"VERSION_FILE_TEST" * 40 + b"\xFF\xD9"
    version_file.write_bytes(version_content)

    # Super admin token
    admin_token = create_access_token(
        data={"sub": "6aa1e3b0da8b07991d686499", "role": UserRole.SUPER_ADMIN.value}
    )

    doc_id = str(ObjectId())
    version_id = str(ObjectId())

    # Insert a student document version record
    await db_client["student_documents"].insert_one({
        "_id": ObjectId(doc_id),
        "student_id": "23CS001",
        "batch_id": "batch_ver_test",
        "department_code": "CS",
        "document_name": "12th HSC Marksheet",
        "document_type": "12TH_MARKSHEET",
        "active_version_id": version_id,
        "versions": [
            {
                "version_id": version_id,
                "version_number": 1,
                "file_path": str(version_file),
                "original_filename": "marksheet_scan.jpg",
                "mime_type": "image/jpeg",
                "uploaded_by": "Staff",
            }
        ],
    })

    # Also insert corresponding student submission so student_name can be looked up
    await db_client["student_submissions"].insert_one({
        "batch_id": "batch_ver_test",
        "department_id": "CS",
        "student_name": "Arun Kumar",
        "register_number": "23CS001",
        "normalized_register_number": "23cs001_ver",
        "mobile_number": "9876543219",
        "submission_status": "Submitted",
        "documents": [],
    })

    try:
        # Request file from student-documents version endpoint
        res = await client_async.get(
            f"/student-documents/{doc_id}/versions/{version_id}/file",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert res.status_code == 200
        cd = res.headers.get("content-disposition", "")
        # Expected: 23CS001_Arun_Kumar_12th_HSC_Marksheet.jpg
        assert "23CS001_Arun_Kumar_12th_HSC_Marksheet.jpg" in cd
        assert res.content == version_content

    finally:
        await db_client["student_documents"].delete_one({"_id": ObjectId(doc_id)})
        await db_client["student_submissions"].delete_one({"normalized_register_number": "23cs001_ver"})
        if version_file.exists():
            try:
                version_file.unlink()
            except Exception:
                pass

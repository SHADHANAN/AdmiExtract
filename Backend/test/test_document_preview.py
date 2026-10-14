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


@pytest.mark.asyncio
async def test_document_preview_full_flow(client_async: AsyncClient, db_client):
    backend_root = Path(__file__).resolve().parent.parent
    uploads_dir = backend_root / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)

    pdf1 = uploads_dir / "test_preview_doc_aadhaar.pdf"
    pdf2 = uploads_dir / "test_preview_doc_comm.pdf"
    jpg1 = uploads_dir / "test_preview_doc_photo.jpg"
    png1 = uploads_dir / "test_preview_doc_sign.png"

    # Create test dummy files with valid magic headers and >1000 bytes
    pdf_content = b"%PDF-1.4\n" + b"A" * 1500 + b"\n%%EOF"
    jpg_content = b"\xFF\xD8\xFF\xE0" + b"B" * 1500 + b"\xFF\xD9"
    png_content = b"\x89PNG\r\n\x1a\n" + b"C" * 1500

    pdf1.write_bytes(pdf_content)
    pdf2.write_bytes(pdf_content)
    jpg1.write_bytes(jpg_content)
    png1.write_bytes(png_content)

    # 1. Super Admin token
    admin_token = create_access_token(
        data={"sub": "6aa1e3b0da8b07991d686499", "role": UserRole.SUPER_ADMIN.value}
    )

    # 2. Insert test submissions
    ins_main = await db_client["student_submissions"].insert_one({
        "batch_id": "batch_preview_test",
        "department_id": "AIML",
        "student_name": "Preview Test Student",
        "register_number": "PREV_REG_01",
        "mobile_number": "9876543210",
        "submission_status": "Submitted",
        "documents": [
            {
                "document_name": "Aadhaar Card",
                "status": "Uploaded",
                "file_path": str(pdf1),
            },
            {
                "document_name": "Community Certificate",
                "status": "Uploaded",
                "file_path": str(pdf2),
            },
        ],
    })
    sub_id = str(ins_main.inserted_id)

    ins_jpg = await db_client["student_submissions"].insert_one({
        "batch_id": "batch_preview_test",
        "department_id": "AIML",
        "student_name": "JPG Student",
        "register_number": "PREV_REG_02",
        "mobile_number": "9876543211",
        "submission_status": "Submitted",
        "documents": [
            {
                "document_name": "Photo",
                "status": "Uploaded",
                "file_path": str(jpg1),
            },
        ],
    })
    jpg_sub_id = str(ins_jpg.inserted_id)

    ins_png = await db_client["student_submissions"].insert_one({
        "batch_id": "batch_preview_test",
        "department_id": "AIML",
        "student_name": "PNG Student",
        "register_number": "PREV_REG_03",
        "mobile_number": "9876543212",
        "submission_status": "Submitted",
        "documents": [
            {
                "document_name": "Signature",
                "status": "Uploaded",
                "file_path": str(png1),
            },
        ],
    })
    png_sub_id = str(ins_png.inserted_id)

    try:
        # Test PDF Preview (Aadhaar Card)
        res_pdf = await client_async.get(
            f"/student-submissions/{sub_id}/documents/0/file",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert res_pdf.status_code == 200
        assert res_pdf.headers.get("content-type") == "application/pdf"
        assert "inline" in res_pdf.headers.get("content-disposition", "")
        assert "Aadhaar_Card.pdf" in res_pdf.headers.get("content-disposition", "")
        assert len(res_pdf.content) > 1000
        assert res_pdf.content.startswith(b"%PDF")

        # Test Community Certificate PDF (Doc index 1)
        res_comm = await client_async.get(
            f"/student-submissions/{sub_id}/documents/1/file",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert res_comm.status_code == 200
        assert res_comm.headers.get("content-type") == "application/pdf"
        assert len(res_comm.content) > 1000

        # Test Image Preview (JPG)
        res_jpg = await client_async.get(
            f"/student-submissions/{jpg_sub_id}/documents/0/file",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert res_jpg.status_code == 200
        assert res_jpg.headers.get("content-type") == "image/jpeg"
        assert len(res_jpg.content) > 1000

        # Test Image Preview (PNG)
        res_png = await client_async.get(
            f"/student-submissions/{png_sub_id}/documents/0/file",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert res_png.status_code == 200
        assert res_png.headers.get("content-type") == "image/png"
        assert len(res_png.content) > 1000
    finally:
        await db_client["student_submissions"].delete_one({"_id": ObjectId(sub_id)})
        await db_client["student_submissions"].delete_one({"_id": ObjectId(jpg_sub_id)})
        await db_client["student_submissions"].delete_one({"_id": ObjectId(png_sub_id)})
        for f in [pdf1, pdf2, jpg1, png1]:
            if f.exists():
                try:
                    f.unlink()
                except Exception:
                    pass


@pytest.mark.asyncio
async def test_document_preview_security(client_async: AsyncClient, db_client):
    backend_root = Path(__file__).resolve().parent.parent
    uploads_dir = backend_root / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    pdf_sec = uploads_dir / "test_preview_sec_doc.pdf"
    pdf_sec.write_bytes(b"%PDF-1.4\n" + b"SEC" * 500 + b"\n%%EOF")

    # 1. Ensure Department Admins exist in DB
    aiml_user = await db_client["users"].find_one({"username": "test_aiml_preview_admin"})
    if not aiml_user:
        res_aiml = await db_client["users"].insert_one({
            "username": "test_aiml_preview_admin",
            "name": "AIML Admin",
            "email": "aiml_preview_admin@test.com",
            "password": get_password_hash("admin123"),
            "role": UserRole.DEPARTMENT_ADMIN.value,
            "department_code": "AIML",
        })
        aiml_id = str(res_aiml.inserted_id)
    else:
        aiml_id = str(aiml_user["_id"])

    civil_user = await db_client["users"].find_one({"username": "test_civil_preview_admin"})
    if not civil_user:
        res_civil = await db_client["users"].insert_one({
            "username": "test_civil_preview_admin",
            "name": "Civil Admin",
            "email": "civil_preview_admin@test.com",
            "password": get_password_hash("admin123"),
            "role": UserRole.DEPARTMENT_ADMIN.value,
            "department_code": "CIVIL",
        })
        civil_id = str(res_civil.inserted_id)
    else:
        civil_id = str(civil_user["_id"])

    # 2. Insert test submission under AIML department
    ins = await db_client["student_submissions"].insert_one({
        "batch_id": "batch_preview_sec",
        "department_id": "AIML",
        "student_name": "AIML Preview Student",
        "register_number": "SEC_PREV_01",
        "mobile_number": "9876543210",
        "submission_status": "Submitted",
        "documents": [
            {
                "document_name": "Aadhaar Card",
                "status": "Uploaded",
                "file_path": str(pdf_sec),
            },
        ],
    })
    sub_id = str(ins.inserted_id)

    other_dept_token = create_access_token(
        data={"sub": civil_id, "role": UserRole.DEPARTMENT_ADMIN.value}
    )
    aiml_token = create_access_token(
        data={"sub": aiml_id, "role": UserRole.DEPARTMENT_ADMIN.value}
    )

    try:
        # 1. Unauthenticated -> 401
        res_unauth = await client_async.get(f"/student-submissions/{sub_id}/documents/0/file")
        assert res_unauth.status_code == 401

        # 2. Different Department Admin -> 403
        res_forbidden = await client_async.get(
            f"/student-submissions/{sub_id}/documents/0/file",
            headers={"Authorization": f"Bearer {other_dept_token}"},
        )
        assert res_forbidden.status_code == 403

        # 3. Same Department Admin (AIML) -> 200
        res_allowed = await client_async.get(
            f"/student-submissions/{sub_id}/documents/0/file",
            headers={"Authorization": f"Bearer {aiml_token}"},
        )
        assert res_allowed.status_code == 200

        # 4. Out of bounds index -> 404
        res_oob = await client_async.get(
            f"/student-submissions/{sub_id}/documents/999/file",
            headers={"Authorization": f"Bearer {aiml_token}"},
        )
        assert res_oob.status_code == 404

        # 5. Non-existent submission -> 404
        res_nosub = await client_async.get(
            "/student-submissions/000000000000000000000000/documents/0/file",
            headers={"Authorization": f"Bearer {aiml_token}"},
        )
        assert res_nosub.status_code == 404
    finally:
        await db_client["student_submissions"].delete_one({"_id": ObjectId(sub_id)})
        if pdf_sec.exists():
            try:
                pdf_sec.unlink()
            except Exception:
                pass

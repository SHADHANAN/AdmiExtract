import pytest
import pytest_asyncio
from httpx import AsyncClient
from app.core.security import create_access_token
from app.models.user import UserRole


@pytest_asyncio.fixture
async def client_async():
    async with AsyncClient(base_url="http://127.0.0.1:8000") as ac:
        yield ac


@pytest.mark.asyncio
async def test_document_preview_full_flow(client_async: AsyncClient):
    # 1. Super Admin token
    admin_token = create_access_token(
        data={"sub": "6aa1e3b0da8b07991d686499", "role": UserRole.SUPER_ADMIN.value}
    )

    # 2. Student praveen (has uploaded documents including real aadhar.pdf)
    sub_id = "6aa519c1b75402822fce8f97"

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

    # Test Image Preview (Praveen 24am0765 - JPG)
    praveen2_id = "6aa93c994b019acec2edc2e4"
    res_jpg = await client_async.get(
        f"/student-submissions/{praveen2_id}/documents/0/file",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_jpg.status_code == 200
    assert res_jpg.headers.get("content-type") == "image/jpeg"
    assert len(res_jpg.content) > 1000

    # Test Image Preview (Shadhanan - PNG)
    shadh_id = "6aa93c964b019acec2edc2e3"
    res_png = await client_async.get(
        f"/student-submissions/{shadh_id}/documents/0/file",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_png.status_code == 200
    assert res_png.headers.get("content-type") == "image/png"
    assert len(res_png.content) > 1000


@pytest.mark.asyncio
async def test_document_preview_security(client_async: AsyncClient):
    sub_id = "6aa519c1b75402822fce8f97"  # AIML batch student

    # 1. Unauthenticated -> 401
    res_unauth = await client_async.get(f"/student-submissions/{sub_id}/documents/0/file")
    assert res_unauth.status_code == 401

    # 2. Different Department Admin -> 403
    other_dept_token = create_access_token(
        data={"sub": "6aa25241c4857be10f71b126", "role": UserRole.DEPARTMENT_ADMIN.value}
    )
    res_forbidden = await client_async.get(
        f"/student-submissions/{sub_id}/documents/0/file",
        headers={"Authorization": f"Bearer {other_dept_token}"},
    )
    assert res_forbidden.status_code == 403

    # 3. Same Department Admin (AIML) -> 200
    aiml_token = create_access_token(
        data={"sub": "6aa1e3b0da8b07991d68649a", "role": UserRole.DEPARTMENT_ADMIN.value}
    )
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

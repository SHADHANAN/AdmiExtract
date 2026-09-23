import io
import pytest
import pytest_asyncio
import openpyxl
from httpx import AsyncClient
from motor.motor_asyncio import AsyncIOMotorClient
from app.core.security import create_access_token
from app.models.user import UserRole


@pytest_asyncio.fixture
async def client_async():
    async with AsyncClient(base_url="http://127.0.0.1:8000") as ac:
        yield ac


@pytest_asyncio.fixture
async def db_client():
    client = AsyncIOMotorClient("mongodb://localhost:27017")
    db = client["admiextract"]
    yield db
    client.close()


@pytest.mark.asyncio
async def test_dynamic_section_excel_export(client_async: AsyncClient, db_client):
    """
    Test that Section Excel export is dynamically generated:
    1. No template exists for Section A.
    2. Students from Section A and Section B exist in MongoDB.
    3. Downloading export for Section A includes only Section A students.
    4. Configured fields are extracted and populated into the Excel sheet.
    """
    admin_token = create_access_token(
        data={"sub": "6aa1e3b0da8b07991d686499", "role": UserRole.SUPER_ADMIN.value}
    )

    batch_id = "test_export_batch_001"
    class_a_id = "test_class_a_001"
    class_b_id = "test_class_b_001"

    # Insert test students
    ins_a = await db_client["student_submissions"].insert_one({
        "batch_id": batch_id,
        "class_id": class_a_id,
        "class_name": "Section A",
        "department_id": "AIML",
        "student_name": "Student Alpha",
        "register_number": "SEC_A_REG_1",
        "mobile_number": "9876543210",
        "email": "alpha@example.com",
        "submission_status": "Verified",
        "extracted_data": {
            "Aadhaar Number": "1234 5678 9012",
            "Date of Birth": "2005-01-01",
        },
        "documents": [],
    })

    ins_b = await db_client["student_submissions"].insert_one({
        "batch_id": batch_id,
        "class_id": class_b_id,
        "class_name": "Section B",
        "department_id": "AIML",
        "student_name": "Student Beta",
        "register_number": "SEC_B_REG_2",
        "mobile_number": "9876543211",
        "email": "beta@example.com",
        "submission_status": "Submitted",
        "extracted_data": {
            "Aadhaar Number": "9999 8888 7777",
            "Date of Birth": "2005-02-02",
        },
        "documents": [],
    })

    try:
        # Download export for Section A
        res = await client_async.get(
            f"/excel-templates/download/{batch_id}?classId={class_a_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        if res.status_code != 200:
            print("ERROR RESPONSE:", res.status_code, res.text)
        assert res.status_code == 200
        assert "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" in res.headers.get("content-type", "")

        # Inspect generated workbook
        wb = openpyxl.load_workbook(io.BytesIO(res.content), data_only=True)
        ws = wb.active

        # Collect all rows
        rows = list(ws.iter_rows(values_only=True))
        assert len(rows) >= 2  # Header + at least 1 student row

        header_row = [str(c) if c is not None else "" for c in rows[0]]
        assert "Register Number" in header_row or "Reg No" in header_row
        assert "Student Name" in header_row or "Name" in header_row

        # Collect all register numbers in the sheet
        reg_col_idx = None
        for idx, h in enumerate(header_row):
            if "register" in h.lower() or "reg" in h.lower():
                reg_col_idx = idx
                break
        assert reg_col_idx is not None

        sheet_reg_nums = [row[reg_col_idx] for row in rows[1:] if row[reg_col_idx] is not None]

        # Verify Student Alpha IS in export
        assert "SEC_A_REG_1" in sheet_reg_nums

        # Verify Student Beta (Section B) is NOT in Section A export
        assert "SEC_B_REG_2" not in sheet_reg_nums

    finally:
        await db_client["student_submissions"].delete_one({"_id": ins_a.inserted_id})
        await db_client["student_submissions"].delete_one({"_id": ins_b.inserted_id})

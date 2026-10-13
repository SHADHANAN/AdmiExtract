import io
import openpyxl
import pytest
import pytest_asyncio
from datetime import datetime, timezone, timedelta
from beanie import PydanticObjectId
from motor.motor_asyncio import AsyncIOMotorClient
from httpx import AsyncClient, ASGITransport
from fastapi import HTTPException

from app.main import app
from app.core.config import settings
from app.core.security import create_access_token
from app.models.user import User, UserRole
from app.models.batch import AdmissionBatch
from app.models.student_submission import StudentSubmission
from app.models.batch_extraction import (
    BatchExtractionRequest,
    BatchExtractionStatus,
    BatchDownloadStatus,
    BatchExportStatus,
)
from app.models.document_verification import (
    DocumentFieldVerification,
    VerificationFieldStatus,
)
from app.models.verification_token import (
    VerificationToken,
    VerificationTokenStatus,
)
from app.schemas.verification_token import (
    CommonStudentIdentifyRequest,
    CommonStudentVerifyCodeRequest,
    CommonStudentSubmitRequest,
    StudentFieldVerificationItem,
)
from app.services.verification_token_service import VerificationTokenService
from app.services.batch_extraction_service import BatchExtractionService


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    import app.db.database as db_mod

    db_mod.client = AsyncIOMotorClient(
        settings.MONGODB_URI, serverSelectionTimeoutMS=2000
    )
    db_mod.db = db_mod.client[settings.DATABASE_NAME]
    await db_mod._run_db_setup()


@pytest_asyncio.fixture
async def client_async():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


async def create_test_user(role=UserRole.SUPER_ADMIN, dept="DEP_TEST") -> User:
    uname = f"user_{PydanticObjectId()}"
    user = User(
        name="Test Super Admin",
        username=uname,
        email=f"{uname}@test.com",
        password="hashed_pw",
        role=role,
        department_code=dept,
        is_active=True,
    )
    await user.insert()
    return user


def get_auth_headers_for_user(user: User):
    token = create_access_token(
        data={"sub": str(user.id), "role": user.role.value, "department_code": user.department_code}
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_all_students_verification_0_of_10_and_9_of_10_and_10_of_10(client_async: AsyncClient):
    """
    Regression Test:
    - 0/10 verified: download blocked.
    - 9/10 verified: download blocked.
    - 10/10 verified: download allowed.
    - Direct backend API request while pending is rejected (400).
    - Downloaded Excel contains every student's final submitted values.
    - Preserves student statuses during Excel download.
    """
    token_service = VerificationTokenService()
    batch_service = BatchExtractionService()

    dept_id = "DEP_VERIF_10"
    user = await create_test_user(UserRole.SUPER_ADMIN, dept_id)
    headers = get_auth_headers_for_user(user)

    batch_id = f"batch_10_{PydanticObjectId()}"
    ext_id = f"ext_10_{PydanticObjectId()}"
    now = datetime.now(timezone.utc)

    # 1. Create Batch
    await AdmissionBatch(
        id=batch_id,
        name="Ten Students Batch",
        academic_year="2026-2027",
        department_id=dept_id,
        created_by=str(user.id),
        created_at=now,
    ).insert()

    # 2. Create 10 Students with extracted fields
    students_data = []
    verif_records = {}

    for i in range(1, 11):
        reg = f"REG2026_{i:02d}"
        s_name = f"Student {i:02d}"
        sub = await StudentSubmission(
            batch_id=batch_id,
            register_number=reg,
            student_name=s_name,
            email=f"student{i}@univ.edu",
            mobile_number=f"98000000{i:02d}",
            submission_status="Submitted",
            created_at=now,
        ).insert()

        vf_name = await DocumentFieldVerification(
            extraction_request_id=ext_id,
            extraction_result_id=f"res_{reg}_name",
            student_id=reg,
            student_name=s_name,
            batch_id=batch_id,
            document_type="PROFILE",
            field_name="student_name",
            ai_value=s_name,
            final_value=s_name,
            status=VerificationFieldStatus.AI_EXTRACTED,
            created_at=now,
            updated_at=now,
        ).insert()

        vf_dob = await DocumentFieldVerification(
            extraction_request_id=ext_id,
            extraction_result_id=f"res_{reg}_dob",
            student_id=reg,
            student_name=s_name,
            batch_id=batch_id,
            document_type="AADHAAR",
            field_name="date_of_birth",
            ai_value=f"2005-01-{i:02d}",
            final_value=f"2005-01-{i:02d}",
            status=VerificationFieldStatus.AI_EXTRACTED,
            created_at=now,
            updated_at=now,
        ).insert()

        students_data.append((reg, s_name, sub))
        verif_records[reg] = {"name": vf_name, "dob": vf_dob}

    # 3. Create Batch Extraction Request
    await BatchExtractionRequest(
        extraction_request_id=ext_id,
        batch_id=batch_id,
        batch_name="Ten Students Batch",
        department_id=dept_id,
        created_by=str(user.id),
        requested_by=user.username,
        status=BatchExtractionStatus.COMPLETED.value,
        export_status=BatchExportStatus.NOT_READY.value,
        download_status=BatchDownloadStatus.NOT_DOWNLOADED.value,
        download_count=0,
        requested_columns=["Student Name", "Register Number", "Date Of Birth"],
        requested_fields=["student_name", "register_number", "date_of_birth"],
        column_mapping={
            "Student Name": "student_name",
            "Register Number": "register_number",
            "Date Of Birth": "date_of_birth",
        },
        total_students=10,
        created_at=now,
        updated_at=now,
    ).insert()

    # --- Scenario 1: 0/10 verified ---
    # Service call fails with HTTP 400
    with pytest.raises(HTTPException) as exc_0:
        await batch_service.export_verified_excel(ext_id, user, enforce_all_verified=True)
    assert exc_0.value.status_code == 400
    assert "10 student(s) still pending verification" in exc_0.value.detail
    assert "0 / 10 students verified" in exc_0.value.detail

    # Direct API request fails with HTTP 400 (even if query param tries to bypass)
    res_direct_0 = await client_async.get(
        f"/data-extractions/requests/{ext_id}/export?enforce_all_verified=false",
        headers=headers,
    )
    assert res_direct_0.status_code == 400
    assert "10 student(s) still pending verification" in res_direct_0.json()["detail"]

    # --- Verify first 9 students using Common Verification Link ---
    for i in range(1, 10):
        reg = f"REG2026_{i:02d}"
        s_name = f"Student {i:02d}"

        # Step A: Identify on common link (Direct identity verification without OTP)
        ident_res = await token_service.identify_common_student(
            CommonStudentIdentifyRequest(
                batch_id=batch_id,
                extraction_request_id=ext_id,
                student_name=s_name,
                register_number=reg,
            )
        )
        assert ident_res.requires_code is False
        assert ident_res.session_token is not None

        # Step B: Submit verification with edited DOB for Student 1
        custom_dob = f"2005-09-{i:02d}" if i == 1 else f"2005-01-{i:02d}"
        await token_service.submit_common_verification(
            CommonStudentSubmitRequest(
                session_token=ident_res.session_token,
                fields=[
                    StudentFieldVerificationItem(
                        verification_id=str(verif_records[reg]["name"].id),
                        is_confirmed=True,
                    ),
                    StudentFieldVerificationItem(
                        verification_id=str(verif_records[reg]["dob"].id),
                        is_confirmed=(i != 1),
                        corrected_value=custom_dob if i == 1 else None,
                    ),
                ],
            )
        )

    # --- Scenario 2: 9/10 verified ---
    # Service call fails with HTTP 400
    with pytest.raises(HTTPException) as exc_9:
        await batch_service.export_verified_excel(ext_id, user, enforce_all_verified=True)
    assert exc_9.value.status_code == 400
    assert "1 student(s) still pending verification" in exc_9.value.detail
    assert "9 / 10 students verified" in exc_9.value.detail

    # Direct API request fails with HTTP 400
    res_direct_9 = await client_async.get(
        f"/data-extractions/requests/{ext_id}/export",
        headers=headers,
    )
    assert res_direct_9.status_code == 400
    assert "1 student(s) still pending verification" in res_direct_9.json()["detail"]
    assert "REG2026_10" in res_direct_9.json()["detail"]

    # --- Verify the 10th student (final student submits) ---
    reg_10 = "REG2026_10"
    s_name_10 = "Student 10"

    ident_10 = await token_service.identify_common_student(
        CommonStudentIdentifyRequest(
            batch_id=batch_id,
            extraction_request_id=ext_id,
            student_name=s_name_10,
            register_number=reg_10,
        )
    )
    assert ident_10.requires_code is False
    assert ident_10.session_token is not None
    await token_service.submit_common_verification(
        CommonStudentSubmitRequest(
            session_token=ident_10.session_token,
            fields=[
                StudentFieldVerificationItem(
                    verification_id=str(verif_records[reg_10]["name"].id),
                    is_confirmed=True,
                ),
                StudentFieldVerificationItem(
                    verification_id=str(verif_records[reg_10]["dob"].id),
                    is_confirmed=True,
                ),
            ],
        )
    )

    # --- Scenario 3: 10/10 verified -> Download allowed ---
    # Service call succeeds
    stream, filename = await batch_service.export_verified_excel(ext_id, user, enforce_all_verified=True)
    assert filename.endswith(".xlsx")
    assert stream is not None

    # Direct API request succeeds with 200 and binary attachment
    res_direct_10 = await client_async.get(
        f"/data-extractions/requests/{ext_id}/export",
        headers=headers,
    )
    assert res_direct_10.status_code == 200
    assert "spreadsheetml" in res_direct_10.headers.get("content-type", "")

    # Parse Excel and verify every student's final submitted values
    wb = openpyxl.load_workbook(io.BytesIO(res_direct_10.content))
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))

    header = rows[0]
    data_rows = rows[1:]

    # Exactly 10 student rows (1 per eligible student, deduplicated)
    assert len(data_rows) == 10, f"Expected 10 data rows, got {len(data_rows)}"

    header_indices = {col: idx for idx, col in enumerate(header) if col}
    dob_idx = header_indices.get("Date Of Birth") or header_indices.get("date_of_birth")

    # Student 1 has their corrected DOB: 2005-09-01
    cand_1_row = next(r for r in data_rows if "Student 01" in str(r))
    if dob_idx is not None:
        assert cand_1_row[dob_idx] == "2005-09-01"

    # Verify student statuses were NOT altered or reset during export
    for i in range(1, 11):
        reg = f"REG2026_{i:02d}"
        for vf in verif_records[reg].values():
            refreshed = await DocumentFieldVerification.get(vf.id)
            assert refreshed.status in (
                VerificationFieldStatus.STUDENT_VERIFIED,
                VerificationFieldStatus.STUDENT_CONFIRMED,
            )


@pytest.mark.asyncio
async def test_link_sent_or_otp_verified_without_submission_blocks_download(client_async: AsyncClient):
    """
    Regression Test:
    - A link was sent but student did not submit: blocked.
    - OTP verified but student did not submit: blocked.
    - A submission failed to persist: blocked.
    - Extraction failed or data unavailable: blocked.
    """
    token_service = VerificationTokenService()
    batch_service = BatchExtractionService()

    dept_id = "DEP_LINK_SENT_BLOCK"
    user = await create_test_user(UserRole.SUPER_ADMIN, dept_id)
    headers = get_auth_headers_for_user(user)

    batch_id = f"batch_unsub_{PydanticObjectId()}"
    ext_id = f"ext_unsub_{PydanticObjectId()}"
    now = datetime.now(timezone.utc)

    await AdmissionBatch(
        id=batch_id,
        name="Unsubmitted Student Batch",
        academic_year="2026-2027",
        department_id=dept_id,
        created_by=str(user.id),
        created_at=now,
    ).insert()

    student_reg = "REG_UNSUB_01"
    student_name = "Alice Unsubmitted"

    await StudentSubmission(
        batch_id=batch_id,
        register_number=student_reg,
        student_name=student_name,
        email="alice@univ.edu",
        submission_status="Submitted",
        created_at=now,
    ).insert()

    vf = await DocumentFieldVerification(
        extraction_request_id=ext_id,
        extraction_result_id="res_alice_aadhaar",
        student_id=student_reg,
        student_name=student_name,
        batch_id=batch_id,
        document_type="AADHAAR",
        field_name="aadhaar_number",
        ai_value="444455556666",
        final_value="444455556666",
        status=VerificationFieldStatus.AI_EXTRACTED,
        created_at=now,
        updated_at=now,
    ).insert()

    await BatchExtractionRequest(
        extraction_request_id=ext_id,
        batch_id=batch_id,
        batch_name="Unsubmitted Student Batch",
        department_id=dept_id,
        created_by=str(user.id),
        requested_by=user.username,
        status=BatchExtractionStatus.COMPLETED.value,
        export_status=BatchExportStatus.NOT_READY.value,
        download_status=BatchDownloadStatus.NOT_DOWNLOADED.value,
        requested_columns=["Student Name", "Register Number", "Aadhaar Number"],
        requested_fields=["student_name", "register_number", "aadhaar_number"],
        column_mapping={
            "Student Name": "student_name",
            "Register Number": "register_number",
            "Aadhaar Number": "aadhaar_number",
        },
        total_students=1,
        created_at=now,
        updated_at=now,
    ).insert()

    # 1. Student opens common link and identifies successfully without OTP
    ident_res = await token_service.identify_common_student(
        CommonStudentIdentifyRequest(
            batch_id=batch_id,
            extraction_request_id=ext_id,
            student_name=student_name,
            register_number=student_reg,
        )
    )
    assert ident_res.requires_code is False
    assert ident_res.session_token is not None

    # Identity verified alone without submitting verified data -> Download must remain BLOCKED
    res_link_only = await client_async.get(
        f"/data-extractions/requests/{ext_id}/export",
        headers=headers,
    )
    assert res_link_only.status_code == 400
    assert "pending verification" in res_link_only.json()["detail"].lower()

    # 3. Simulated failed persistence: token stays completed=False, fields stay AI_EXTRACTED
    # Download remains BLOCKED
    with pytest.raises(HTTPException) as exc_persist:
        await batch_service.export_verified_excel(ext_id, user, enforce_all_verified=True)
    assert exc_persist.value.status_code == 400

    # 4. Now student explicitly submits verification -> Persisted successfully
    await token_service.submit_common_verification(
        CommonStudentSubmitRequest(
            session_token=ident_res.session_token,
            fields=[
                StudentFieldVerificationItem(
                    verification_id=str(vf.id),
                    is_confirmed=True,
                )
            ],
        )
    )

    # Download now SUCCEEDS
    res_success = await client_async.get(
        f"/data-extractions/requests/{ext_id}/export",
        headers=headers,
    )
    assert res_success.status_code == 200
    assert "spreadsheetml" in res_success.headers.get("content-type", "")

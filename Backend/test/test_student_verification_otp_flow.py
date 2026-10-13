import io
import pytest
import pytest_asyncio
import openpyxl
from datetime import datetime, timezone, timedelta
from httpx import AsyncClient, ASGITransport
from motor.motor_asyncio import AsyncIOMotorClient

from app.core.config import settings
from app.main import app
from app.models.batch import AdmissionBatch
from app.models.batch_extraction import (
    BatchExtractionRequest,
    BatchExtractionStatus,
    BatchExportStatus,
    BatchDownloadStatus,
)
from app.models.student_submission import StudentSubmission
from app.models.document_verification import (
    DocumentFieldVerification,
    VerificationFieldStatus,
)
from app.models.verification_token import VerificationToken, VerificationTokenStatus
from app.models.user import User, UserRole
from app.core.security import get_password_hash


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    import app.db.database as db_mod

    db_mod.client = AsyncIOMotorClient(
        settings.MONGODB_URI, serverSelectionTimeoutMS=2000
    )
    db_mod.db = db_mod.client[settings.DATABASE_NAME]
    await db_mod._run_db_setup()


@pytest.mark.asyncio
async def test_direct_identity_validation_without_otp():
    """
    Requirement 1: Remove OTP verification.
    - Valid registered name & register number validates on backend against student record & batch.
    - requires_code is False, no OTP sent.
    - Student immediately accesses only their extracted fields.
    """
    batch_id = "batch_direct_test_01"
    reg_no = "REG_DIRECT_001"

    await AdmissionBatch.find({"_id": batch_id}).delete()
    await StudentSubmission.find({"$or": [{"batch_id": batch_id}, {"register_number": reg_no}]}).delete()
    await DocumentFieldVerification.find({"$or": [{"batch_id": batch_id}, {"student_id": reg_no}]}).delete()
    await VerificationToken.find({"$or": [{"batch_id": batch_id}, {"student_id": reg_no}]}).delete()

    batch = AdmissionBatch(
        id=batch_id,
        name="Batch Direct Test 1",
        academic_year="2026-2027",
        department_id="DEP_CSE",
        created_by="admin",
    )
    await batch.insert()

    sub = StudentSubmission(
        batch_id=batch_id,
        student_name="Priya Sharma",
        register_number=reg_no,
        email="priya.sharma@example.edu",
        mobile_number="+919876500001",
        submission_status="Submitted",
        extracted_data={"student_name": "Priya Sharma", "community": "OBC"},
    )
    await sub.insert()

    vf = DocumentFieldVerification(
        extraction_result_id="ext_direct_01",
        extraction_request_id="ext_req_direct_01",
        student_id=reg_no,
        document_id="doc_direct_01",
        document_version_id="ver_01",
        batch_id=batch_id,
        document_type="TRANSFER_CERTIFICATE",
        field_name="community",
        ai_value="OBC",
        final_value="OBC",
        status=VerificationFieldStatus.AI_EXTRACTED,
    )
    await vf.insert()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(
            "/public/student-verification/identify",
            json={
                "student_name": "Priya Sharma",
                "register_number": reg_no,
                "batch_id": batch_id,
            },
        )
        assert res.status_code == 200
        data = res.json()
        assert data["requires_code"] is False
        assert data["session_token"]
        assert data["dev_code"] is None

        # Verify token in DB is active and verified
        token_doc = await VerificationToken.find_one(
            VerificationToken.token == data["session_token"]
        )
        assert token_doc is not None
        assert token_doc.is_verified is True
        assert token_doc.verification_code is None
        assert token_doc.status == VerificationTokenStatus.ACTIVE.value

        # Direct access to extraction data without entering OTP
        data_res = await ac.get(f"/public/verification/{data['session_token']}")
        assert data_res.status_code == 200
        verif_data = data_res.json()
        assert verif_data["valid"] is True
        assert verif_data["student_name"] == "Priya Sharma"
        assert verif_data["student_id"] == reg_no
        assert len(verif_data["fields"]) >= 1
        assert verif_data["fields"][0]["ai_value"] == "OBC"


@pytest.mark.asyncio
async def test_invalid_name_or_register_number_rejected_with_rate_limiting():
    """
    Requirement 1: Security & isolation.
    - Invalid name or register number is rejected with HTTP 401.
    - Failed attempts are rate limited (5 max attempts in 15 mins -> HTTP 429).
    """
    batch_id = "batch_direct_test_02"
    reg_no = "REG_DIRECT_002"

    await AdmissionBatch.find({"_id": batch_id}).delete()
    await StudentSubmission.find({"$or": [{"batch_id": batch_id}, {"register_number": reg_no}]}).delete()
    await DocumentFieldVerification.find({"$or": [{"batch_id": batch_id}, {"student_id": reg_no}]}).delete()
    await VerificationToken.find({"$or": [{"batch_id": batch_id}, {"student_id": reg_no}]}).delete()

    batch = AdmissionBatch(
        id=batch_id,
        name="Batch Direct Test 2",
        academic_year="2026-2027",
        department_id="DEP_CSE",
        created_by="admin",
    )
    await batch.insert()

    sub = StudentSubmission(
        batch_id=batch_id,
        student_name="Rahul Varma",
        register_number=reg_no,
        email="rahul.varma@example.edu",
        mobile_number="+919876500002",
        submission_status="Submitted",
        extracted_data={"student_name": "Rahul Varma"},
    )
    await sub.insert()

    vf = DocumentFieldVerification(
        extraction_result_id="ext_direct_02",
        extraction_request_id="ext_req_direct_02",
        student_id=reg_no,
        document_id="doc_direct_02",
        document_version_id="ver_02",
        batch_id=batch_id,
        document_type="TRANSFER_CERTIFICATE",
        field_name="student_name",
        ai_value="Rahul Varma",
        status=VerificationFieldStatus.AI_EXTRACTED,
    )
    await vf.insert()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Invalid register number
        res_bad_reg = await ac.post(
            "/public/student-verification/identify",
            json={
                "student_name": "Rahul Varma",
                "register_number": "WRONG_REG",
                "batch_id": batch_id,
            },
        )
        assert res_bad_reg.status_code == 401

        # Mismatched student name
        res_bad_name = await ac.post(
            "/public/student-verification/identify",
            json={
                "student_name": "Wrong Name",
                "register_number": reg_no,
                "batch_id": batch_id,
            },
        )
        assert res_bad_name.status_code == 401

        # Exceed rate limit (5 attempts)
        for _ in range(4):
            await ac.post(
                "/public/student-verification/identify",
                json={
                    "student_name": "Wrong Name",
                    "register_number": reg_no,
                    "batch_id": batch_id,
                },
            )

        res_rate = await ac.post(
            "/public/student-verification/identify",
            json={
                "student_name": "Rahul Varma",
                "register_number": reg_no,
                "batch_id": batch_id,
            },
        )
        assert res_rate.status_code == 429
        assert "Too many failed verification attempts" in res_rate.json()["detail"]


@pytest.mark.asyncio
async def test_session_token_expiry_enforcement():
    """
    Requirement 1: Token expiry enforcement.
    Expired tokens must return HTTP 410.
    """
    batch_id = "batch_direct_test_03"
    reg_no = "REG_DIRECT_003"

    await AdmissionBatch.find({"_id": batch_id}).delete()
    await StudentSubmission.find({"batch_id": batch_id}).delete()
    await DocumentFieldVerification.find({"batch_id": batch_id}).delete()
    await VerificationToken.find({"batch_id": batch_id}).delete()

    batch = AdmissionBatch(
        id=batch_id,
        name="Batch Direct Test 3",
        academic_year="2026-2027",
        department_id="DEP_CSE",
        created_by="admin",
    )
    await batch.insert()

    sub = StudentSubmission(
        batch_id=batch_id,
        student_name="Kavita Iyer",
        register_number=reg_no,
        email="kavita.iyer@example.edu",
        submission_status="Submitted",
        extracted_data={"student_name": "Kavita Iyer"},
    )
    await sub.insert()

    vf = DocumentFieldVerification(
        extraction_result_id="ext_direct_03",
        extraction_request_id="ext_req_direct_03",
        student_id=reg_no,
        document_id="doc_direct_03",
        document_version_id="ver_03",
        batch_id=batch_id,
        document_type="TRANSFER_CERTIFICATE",
        field_name="student_name",
        ai_value="Kavita Iyer",
        status=VerificationFieldStatus.AI_EXTRACTED,
    )
    await vf.insert()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res_id = await ac.post(
            "/public/student-verification/identify",
            json={
                "student_name": "Kavita Iyer",
                "register_number": reg_no,
                "batch_id": batch_id,
            },
        )
        session_token = res_id.json()["session_token"]

        # Force token expiry in database
        token_doc = await VerificationToken.find_one(VerificationToken.token == session_token)
        token_doc.expires_at = datetime.now(timezone.utc) - timedelta(minutes=5)
        await token_doc.save()

        # Accessing expired session -> 410
        res_exp = await ac.get(f"/public/verification/{session_token}")
        assert res_exp.status_code == 410


@pytest.mark.asyncio
async def test_successful_submission_persists_final_values_and_marks_student_verified():
    """
    Requirement 2: Successful submission
    - Validates and persists all submitted values.
    - Preserves original AI values and stores student-submitted final values separately.
    - Marks student STUDENT_VERIFIED only after persistence succeeds.
    - Idempotent resubmission succeeds.
    - Prevent further edits to a completed verification session unless a new session is issued.
    """
    batch_id = "batch_direct_test_04"
    reg_no = "REG_DIRECT_004"

    await AdmissionBatch.find({"_id": batch_id}).delete()
    await StudentSubmission.find({"batch_id": batch_id}).delete()
    await DocumentFieldVerification.find({"batch_id": batch_id}).delete()
    await VerificationToken.find({"batch_id": batch_id}).delete()

    batch = AdmissionBatch(
        id=batch_id,
        name="Batch Direct Test 4",
        academic_year="2026-2027",
        department_id="DEP_CSE",
        created_by="admin",
    )
    await batch.insert()

    sub = StudentSubmission(
        batch_id=batch_id,
        student_name="Anand Kumar",
        register_number=reg_no,
        email="anand.kumar@example.edu",
        submission_status="Submitted",
        extracted_data={"student_name": "Anand Kumar", "date_of_birth": "2005-01-01"},
    )
    await sub.insert()

    vf1 = DocumentFieldVerification(
        extraction_result_id="ext_direct_04",
        extraction_request_id="ext_req_direct_04",
        student_id=reg_no,
        document_id="doc_direct_04",
        document_version_id="ver_04",
        batch_id=batch_id,
        document_type="TRANSFER_CERTIFICATE",
        field_name="student_name",
        ai_value="Anand Kumar",
        status=VerificationFieldStatus.AI_EXTRACTED,
    )
    await vf1.insert()

    vf2 = DocumentFieldVerification(
        extraction_result_id="ext_direct_04",
        extraction_request_id="ext_req_direct_04",
        student_id=reg_no,
        document_id="doc_direct_04",
        document_version_id="ver_04",
        batch_id=batch_id,
        document_type="TRANSFER_CERTIFICATE",
        field_name="date_of_birth",
        ai_value="2005-01-01",
        status=VerificationFieldStatus.AI_EXTRACTED,
    )
    await vf2.insert()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Step 1: Identify
        res_id = await ac.post(
            "/public/student-verification/identify",
            json={
                "student_name": "Anand Kumar",
                "register_number": reg_no,
                "batch_id": batch_id,
            },
        )
        assert res_id.status_code == 200
        session_token = res_id.json()["session_token"]

        # Before submission: fields are still AI_EXTRACTED, student is PENDING
        db_vf2_before = await DocumentFieldVerification.get(vf2.id)
        assert db_vf2_before.status == VerificationFieldStatus.AI_EXTRACTED

        # Step 2: Submit verified data (Confirm name, edit DOB)
        res_submit = await ac.post(
            "/public/student-verification/submit",
            json={
                "session_token": session_token,
                "fields": [
                    {
                        "verification_id": str(vf1.id),
                        "is_confirmed": True,
                        "corrected_value": "Anand Kumar",
                    },
                    {
                        "verification_id": str(vf2.id),
                        "is_confirmed": False,
                        "corrected_value": "2005-02-14",
                    },
                ],
                "general_comment": "DOB corrected according to certificate",
            },
        )
        assert res_submit.status_code == 200

        # Step 3: Check persistence
        # Original AI values must be preserved
        db_vf2 = await DocumentFieldVerification.get(vf2.id)
        assert db_vf2.ai_value == "2005-01-01"
        assert db_vf2.student_value == "2005-02-14"
        assert db_vf2.final_value == "2005-02-14"
        assert db_vf2.status == VerificationFieldStatus.STUDENT_VERIFIED
        assert db_vf2.student_updated_at is not None

        # StudentSubmission is updated
        db_sub = await StudentSubmission.get(sub.id)
        assert db_sub.submission_status == "Student Verified"
        assert db_sub.extracted_data.get("date_of_birth") == "2005-02-14"

        # VerificationToken is marked COMPLETED
        tok = await VerificationToken.find_one(VerificationToken.token == session_token)
        assert tok.status == VerificationTokenStatus.COMPLETED.value
        assert tok.completed_at is not None

        # Step 4: Duplicate idempotent submission returns 200
        res_dup = await ac.post(
            "/public/student-verification/submit",
            json={
                "session_token": session_token,
                "fields": [
                    {
                        "verification_id": str(vf1.id),
                        "is_confirmed": True,
                        "corrected_value": "Anand Kumar",
                    },
                    {
                        "verification_id": str(vf2.id),
                        "is_confirmed": False,
                        "corrected_value": "2005-02-14",
                    },
                ],
            },
        )
        assert res_dup.status_code == 200

        # Step 5: Modifying values after completion is rejected with HTTP 400
        res_tamper = await ac.post(
            "/public/student-verification/submit",
            json={
                "session_token": session_token,
                "fields": [
                    {
                        "verification_id": str(vf2.id),
                        "is_confirmed": False,
                        "corrected_value": "1999-12-31",
                    },
                ],
            },
        )
        assert res_tamper.status_code == 400
        assert "already completed" in res_tamper.json()["detail"].lower()


@pytest.mark.asyncio
async def test_all_students_verification_gates_final_excel_export():
    """
    Requirement 3: Final Excel workflow
    - Enable final Excel download only when every eligible student has successfully submitted verification.
    - Export persisted student-submitted final values.
    - Enforced on backend download endpoint.
    """
    batch_id = "batch_direct_test_05"
    ext_id = "ext_req_direct_05"
    now = datetime.now(timezone.utc)

    await AdmissionBatch.find({"_id": batch_id}).delete()
    await StudentSubmission.find({"batch_id": batch_id}).delete()
    await DocumentFieldVerification.find({"batch_id": batch_id}).delete()
    await VerificationToken.find({"batch_id": batch_id}).delete()
    await BatchExtractionRequest.find({"extraction_request_id": ext_id}).delete()

    from beanie import PydanticObjectId
    from app.core.security import create_access_token

    admin = User(
        name="Excel Admin",
        username=f"admin_direct_{PydanticObjectId()}",
        email="admin_direct@example.com",
        password=get_password_hash("pass123"),
        role=UserRole.SUPER_ADMIN,
        department_code="DEP_CSE",
        is_active=True,
    )
    await admin.insert()

    token = create_access_token(
        data={"sub": str(admin.id), "role": admin.role.value, "department_code": admin.department_code}
    )
    auth_headers = {"Authorization": f"Bearer {token}"}

    batch = AdmissionBatch(
        id=batch_id,
        name="Batch Direct Test 5",
        academic_year="2026-2027",
        department_id="DEP_CSE",
        created_by="admin",
    )
    await batch.insert()

    # Create 2 students
    sub1 = await StudentSubmission(
        batch_id=batch_id,
        student_name="Student One",
        register_number="REG_EXCEL_01",
        email="one@example.edu",
        mobile_number="+919876500011",
        submission_status="Submitted",
    ).insert()

    sub2 = await StudentSubmission(
        batch_id=batch_id,
        student_name="Student Two",
        register_number="REG_EXCEL_02",
        email="two@example.edu",
        mobile_number="+919876500012",
        submission_status="Submitted",
    ).insert()

    vf1 = await DocumentFieldVerification(
        extraction_request_id=ext_id,
        extraction_result_id="res_ex_01",
        student_id="REG_EXCEL_01",
        batch_id=batch_id,
        document_id="doc_01",
        document_version_id="v1",
        field_name="student_name",
        ai_value="Student One",
        final_value="Student One",
        status=VerificationFieldStatus.AI_EXTRACTED,
    ).insert()

    vf2 = await DocumentFieldVerification(
        extraction_request_id=ext_id,
        extraction_result_id="res_ex_02",
        student_id="REG_EXCEL_02",
        batch_id=batch_id,
        document_id="doc_02",
        document_version_id="v1",
        field_name="student_name",
        ai_value="Student Two Raw",
        final_value="Student Two Raw",
        status=VerificationFieldStatus.AI_EXTRACTED,
    ).insert()

    req = await BatchExtractionRequest(
        extraction_request_id=ext_id,
        batch_id=batch_id,
        batch_name="Batch Direct Test 5",
        department_id="DEP_CSE",
        created_by="admin",
        requested_by=admin.username,
        status=BatchExtractionStatus.COMPLETED.value,
        export_status=BatchExportStatus.NOT_READY.value,
        download_status=BatchDownloadStatus.NOT_DOWNLOADED.value,
        requested_columns=["Student Name", "Register Number"],
        requested_fields=["student_name", "register_number"],
        column_mapping={"Student Name": "student_name", "Register Number": "register_number"},
        total_students=2,
        created_at=now,
        updated_at=now,
    ).insert()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Step 1: 0/2 verified -> Download blocked (HTTP 400)
        res_dl_0 = await ac.get(
            f"/data-extractions/requests/{ext_id}/export",
            headers=auth_headers,
        )
        assert res_dl_0.status_code == 400
        assert "pending verification" in res_dl_0.json()["detail"].lower()

        # Step 2: Student 1 identifies & submits
        id1 = await ac.post(
            "/public/student-verification/identify",
            json={
                "student_name": "Student One",
                "register_number": "REG_EXCEL_01",
                "batch_id": batch_id,
                "extraction_request_id": ext_id,
            },
        )
        assert id1.status_code == 200
        t1 = id1.json()["session_token"]
        sub1_res = await ac.post(
            "/public/student-verification/submit",
            json={
                "session_token": t1,
                "fields": [{"verification_id": str(vf1.id), "is_confirmed": True}],
            },
        )
        assert sub1_res.status_code == 200

        # Step 3: 1/2 verified -> Download STILL blocked (HTTP 400)
        res_dl_1 = await ac.get(
            f"/data-extractions/requests/{ext_id}/export",
            headers=auth_headers,
        )
        assert res_dl_1.status_code == 400
        assert "1 student(s) still pending verification" in res_dl_1.json()["detail"]

        # Step 4: Student 2 identifies & submits with an edit
        id2 = await ac.post(
            "/public/student-verification/identify",
            json={
                "student_name": "Student Two",
                "register_number": "REG_EXCEL_02",
                "batch_id": batch_id,
                "extraction_request_id": ext_id,
            },
        )
        assert id2.status_code == 200
        t2 = id2.json()["session_token"]
        sub2_res = await ac.post(
            "/public/student-verification/submit",
            json={
                "session_token": t2,
                "fields": [
                    {
                        "verification_id": str(vf2.id),
                        "is_confirmed": False,
                        "corrected_value": "Student Two Final Verified",
                    }
                ],
            },
        )
        assert sub2_res.status_code == 200

        # Step 5: 2/2 verified -> Download is UNBLOCKED (HTTP 200)
        res_dl_2 = await ac.get(
            f"/data-extractions/requests/{ext_id}/export",
            headers=auth_headers,
        )
        assert res_dl_2.status_code == 200
        assert "spreadsheetml" in res_dl_2.headers.get("content-type", "")

        # Step 6: Verify exported Excel contents contain student final values
        wb = openpyxl.load_workbook(io.BytesIO(res_dl_2.content))
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        data_rows = rows[1:]
        assert len(data_rows) == 2
        # Student 2 row contains the submitted edited value
        row_s2 = next(r for r in data_rows if "REG_EXCEL_02" in str(r))
        assert "Student Two Final Verified" in str(row_s2)

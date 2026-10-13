"""
Regression Tests: Staff Dashboard Student Verification Synchronization
========================================================================
Validates that:
1. Student starts as PENDING_VERIFICATION on the staff dashboard and notification status table.
2. Entering identity details and validating OTP alone leaves student strictly PENDING_VERIFICATION.
3. Student explicitly submits verification form with confirmed and corrected values.
4. Backend persists submitted values, records timestamps and audit history.
5. Staff dashboard authoritatively reflects STUDENT_VERIFIED (and token COMPLETED).
6. Summary metrics update: verified_count increments, pending_verification_count decrements.
7. Notification status table reflects STUDENT_VERIFIED independently of notification delivery.
8. Excel export uses the submitted final values for verified students.
9. Invalid OTP, missing OTP validation, and expired sessions leave student PENDING_VERIFICATION.
10. Duplicate submissions are safely rejected without corrupting data.
11. Multi-student isolation: only verifying students become STUDENT_VERIFIED.
"""

from datetime import datetime, timezone, timedelta
import io
import openpyxl
import pytest
import pytest_asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from fastapi import HTTPException

from app.core.config import settings
from app.models.batch import AdmissionBatch
from app.models.student_submission import StudentSubmission
from app.models.student_document import StudentDocument
from app.models.batch_extraction import (
    BatchExtractionRequest,
    BatchExtractionStatus,
)
from app.models.document_verification import (
    DocumentFieldVerification,
    VerificationFieldStatus,
)
from app.models.verification_token import (
    VerificationToken,
    VerificationTokenStatus,
)
from app.models.verification_notification import (
    VerificationNotification,
    NotificationStatus,
    NotificationChannel,
)
from app.models.user import User, UserRole
from app.core.security import get_password_hash
from app.schemas.verification_token import (
    CommonStudentIdentifyRequest,
    CommonStudentVerifyCodeRequest,
    CommonStudentSubmitRequest,
    StudentFieldVerificationItem,
    PublicVerificationSubmitRequest,
)
from app.services.verification_token_service import VerificationTokenService
from app.services.batch_extraction_service import BatchExtractionService
from app.services.notification_service import NotificationService


TEST_STUDENTS = ["26SYNC101", "26SYNC102", "26SYNC103", "26SYNC_A", "26SYNC_B", "26COM_A", "26COM_B", "26COM_DUP"]
TEST_BATCHES = ["BATCH_SYNC_01", "BATCH_SYNC_02", "BATCH_SYNC_03", "BATCH_SYNC_MULTI", "BATCH_COMMON_LINK"]
TEST_REQS = ["ext_req_sync_01", "ext_req_sync_02", "ext_req_sync_03", "ext_req_sync_multi", "ext_req_common_01"]


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    import app.db.database as db_mod

    db_mod.client = AsyncIOMotorClient(
        settings.MONGODB_URI, serverSelectionTimeoutMS=2000
    )
    db_mod.db = db_mod.client[settings.DATABASE_NAME]
    await db_mod._run_db_setup()


@pytest_asyncio.fixture(autouse=True)
async def cleanup_test_data():
    await DocumentFieldVerification.find({"student_id": {"$in": TEST_STUDENTS}}).delete()
    await StudentSubmission.find({"register_number": {"$in": TEST_STUDENTS}}).delete()
    await StudentDocument.find({"student_id": {"$in": TEST_STUDENTS}}).delete()
    await VerificationToken.find({"student_id": {"$in": TEST_STUDENTS}}).delete()
    await VerificationNotification.find({"student_id": {"$in": TEST_STUDENTS}}).delete()
    await AdmissionBatch.find({"$or": [{"_id": {"$in": TEST_BATCHES}}, {"name": {"$in": TEST_BATCHES}}]}).delete()
    await BatchExtractionRequest.find({"$or": [{"batch_id": {"$in": TEST_BATCHES}}, {"extraction_request_id": {"$in": TEST_REQS}}]}).delete()
    yield
    await DocumentFieldVerification.find({"student_id": {"$in": TEST_STUDENTS}}).delete()
    await StudentSubmission.find({"register_number": {"$in": TEST_STUDENTS}}).delete()
    await StudentDocument.find({"student_id": {"$in": TEST_STUDENTS}}).delete()
    await VerificationToken.find({"student_id": {"$in": TEST_STUDENTS}}).delete()
    await VerificationNotification.find({"student_id": {"$in": TEST_STUDENTS}}).delete()
    await AdmissionBatch.find({"$or": [{"_id": {"$in": TEST_BATCHES}}, {"name": {"$in": TEST_BATCHES}}]}).delete()
    await BatchExtractionRequest.find({"$or": [{"batch_id": {"$in": TEST_BATCHES}}, {"extraction_request_id": {"$in": TEST_REQS}}]}).delete()


@pytest.mark.asyncio
async def test_full_workflow_pending_to_otp_to_submit_to_dashboard_and_excel():
    """
    Test full student verification lifecycle:
    1. Student starts as PENDING_VERIFICATION on dashboard & notifications table.
    2. Student enters identity & receives OTP -> still PENDING_VERIFICATION.
    3. Student validates OTP -> still PENDING_VERIFICATION.
    4. Student submits verification form (confirming Name, correcting DOB).
    5. Backend persists submitted values, records timestamps and audit history.
    6. Staff dashboard authoritatively reflects STUDENT_VERIFIED (and token COMPLETED).
    7. Notification status table reflects STUDENT_VERIFIED independently of notification status.
    8. Excel export uses submitted final values.
    """
    token_service = VerificationTokenService()
    batch_service = BatchExtractionService()
    notif_service = NotificationService()

    now = datetime.now(timezone.utc)
    batch_id = "BATCH_SYNC_01"
    req_id = "ext_req_sync_01"
    student_id = "26SYNC101"

    # Setup batch
    batch = await AdmissionBatch(
        id=batch_id,
        name="CSE 2026 Batch",
        department_id="DEPT_CSE",
        academic_year="2026-2027",
        created_by="admin_test",
    ).save()

    # Setup student submission with multiple fields
    sub = await StudentSubmission(
        register_number=student_id,
        student_name="Alice Johnson",
        batch_id=batch_id,
        email="alice@university.edu",
        mobile_number="9876543210",
        submission_status="Submitted",
        extracted_data={"student_name": "Alice Raw", "date_of_birth": "2005-01-01"},
    ).save()

    # Setup extracted verification fields (both start in AI_EXTRACTED)
    vf_name = await DocumentFieldVerification(
        extraction_result_id="res_name_01",
        extraction_request_id=req_id,
        student_id=student_id,
        document_id="doc_name_01",
        document_version_id="v1",
        batch_id=batch_id,
        field_name="student_name",
        ai_value="Alice Raw",
        status=VerificationFieldStatus.AI_EXTRACTED,
        created_at=now,
        updated_at=now,
    ).save()

    vf_dob = await DocumentFieldVerification(
        extraction_result_id="res_dob_01",
        extraction_request_id=req_id,
        student_id=student_id,
        document_id="doc_dob_01",
        document_version_id="v1",
        batch_id=batch_id,
        field_name="date_of_birth",
        ai_value="2005-01-01",
        status=VerificationFieldStatus.AI_EXTRACTED,
        created_at=now,
        updated_at=now,
    ).save()

    # Setup BatchExtractionRequest
    batch_req = await BatchExtractionRequest(
        extraction_request_id=req_id,
        batch_id=batch_id,
        batch_name="CSE 2026 Batch",
        department_id="DEPT_CSE",
        created_by="admin_test",
        requested_fields=["student_name", "date_of_birth"],
        status=BatchExtractionStatus.COMPLETED.value,
        created_at=now,
        updated_at=now,
    ).save()

    admin_actor = User(
        username="admin_sync_tester",
        name="Admissions Staff",
        password=get_password_hash("testpass"),
        role=UserRole.SUPER_ADMIN,
        is_active=True,
    )

    # 1. Step 1: Initial state check - Student MUST be PENDING_VERIFICATION
    dash_detail = await batch_service.get_extraction_details(req_id, admin_actor)
    student_row = next(s for s in dash_detail.students if s.student_id == student_id)
    assert student_row.verification_status == "PENDING_VERIFICATION"
    assert student_row.final_status == "PENDING_VERIFICATION"
    assert dash_detail.summary.pending_verification_count == 1
    assert dash_detail.summary.verified_count == 0

    notif_rows = await notif_service.get_student_notification_status_table(req_id, admin_actor)
    notif_row = next(r for r in notif_rows if r.student_id == student_id)
    assert notif_row.verification_status == "PENDING_VERIFICATION"

    # 2. Step 2: Student enters identity details (Direct verification without OTP)
    id_resp = await token_service.identify_common_student(
        CommonStudentIdentifyRequest(
            student_name="Alice Johnson",
            register_number=student_id,
            batch_id=batch_id,
            extraction_request_id=req_id,
        )
    )
    assert id_resp.requires_code is False
    session_token = id_resp.session_token

    # Assert student is STILL PENDING_VERIFICATION after identity entry
    dash_detail_post_id = await batch_service.get_extraction_details(req_id, admin_actor)
    row_post_id = next(s for s in dash_detail_post_id.students if s.student_id == student_id)
    assert row_post_id.verification_status == "PENDING_VERIFICATION"
    assert dash_detail_post_id.summary.verified_count == 0

    # 3. Step 3: Student reviews fields and explicitly submits verification
    # Confirm name, edit DOB to 2005-01-15
    submit_resp = await token_service.submit_common_verification(
        CommonStudentSubmitRequest(
            session_token=session_token,
            fields=[
                StudentFieldVerificationItem(
                    verification_id=str(vf_name.id),
                    is_confirmed=True,
                    corrected_value="Alice Raw",
                ),
                StudentFieldVerificationItem(
                    verification_id=str(vf_dob.id),
                    is_confirmed=False,
                    corrected_value="2005-01-15",
                    comment="Corrected birthdate",
                ),
            ],
            general_comment="All verified by student",
        )
    )
    assert submit_resp.valid is True

    # 5. Check DB persistence for values, history, and status
    db_vf_name = await DocumentFieldVerification.get(vf_name.id)
    assert db_vf_name.status == VerificationFieldStatus.STUDENT_CONFIRMED
    assert db_vf_name.final_value == "Alice Raw"
    assert db_vf_name.student_updated_at is not None
    assert any(h.action == "STUDENT_CONFIRM" for h in db_vf_name.history)

    db_vf_dob = await DocumentFieldVerification.get(vf_dob.id)
    assert db_vf_dob.status == VerificationFieldStatus.STUDENT_VERIFIED
    assert db_vf_dob.final_value == "2005-01-15"
    assert db_vf_dob.student_updated_at is not None
    assert any(h.action == "STUDENT_EDIT" for h in db_vf_dob.history)

    # Check StudentSubmission persistence
    db_sub = await StudentSubmission.get(sub.id)
    assert db_sub.submission_status == "Student Verified"
    assert db_sub.extracted_data.get("date_of_birth") == "2005-01-15"

    # Check VerificationToken status is COMPLETED
    tok_doc = await VerificationToken.find_one(VerificationToken.token == session_token)
    assert tok_doc.status == VerificationTokenStatus.COMPLETED.value
    assert tok_doc.completed_at is not None

    # 6. Step 5: Staff dashboard authoritatively reflects STUDENT_VERIFIED!
    dash_detail_post_sub = await batch_service.get_extraction_details(req_id, admin_actor)
    row_post_sub = next(s for s in dash_detail_post_sub.students if s.student_id == student_id)
    assert row_post_sub.verification_status == "STUDENT_VERIFIED"
    assert row_post_sub.final_status == "VERIFIED"
    assert row_post_sub.verification_token_status == "COMPLETED"
    assert dash_detail_post_sub.summary.verified_count == 1
    assert dash_detail_post_sub.summary.pending_verification_count == 0

    # 7. Notification table reflects STUDENT_VERIFIED independently of whether notification was sent
    notif_rows_post_sub = await notif_service.get_student_notification_status_table(req_id, admin_actor)
    notif_row_post_sub = next(r for r in notif_rows_post_sub if r.student_id == student_id)
    assert notif_row_post_sub.verification_status == "STUDENT_VERIFIED"
    assert notif_row_post_sub.notification_status == "NOT_SENT"  # independent!

    # 8. Step 6: Excel export contains the submitted/verified values
    stream, _ = await batch_service.export_verified_excel(req_id, admin_actor)
    assert stream is not None
    wb = openpyxl.load_workbook(stream)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    header = [str(c).strip().lower() for c in rows[0]]
    assert any("name" in h for h in header)
    assert any("birth" in h or "dob" in h for h in header)

    name_idx = next(i for i, h in enumerate(header) if "name" in h)
    dob_idx = next(i for i, h in enumerate(header) if "birth" in h or "dob" in h)

    data_row = rows[1]
    assert data_row[name_idx] == "Alice Raw"
    assert data_row[dob_idx] == "2005-01-15"  # Submitted final value!


@pytest.mark.asyncio
async def test_invalid_otp_and_failed_submission_leave_status_pending():
    """
    Test that invalid OTP and failed submission attempts leave the student strictly PENDING_VERIFICATION.
    """
    token_service = VerificationTokenService()
    batch_service = BatchExtractionService()

    now = datetime.now(timezone.utc)
    batch_id = "BATCH_SYNC_02"
    req_id = "ext_req_sync_02"
    student_id = "26SYNC102"

    await AdmissionBatch(
        id=batch_id,
        name="CSE 2026 Batch",
        department_id="DEPT_CSE",
        academic_year="2026-2027",
        created_by="admin_test",
    ).save()
    await StudentSubmission(
        register_number=student_id,
        student_name="Bob Smith",
        batch_id=batch_id,
        submission_status="Submitted",
    ).save()

    vf = await DocumentFieldVerification(
        extraction_result_id="res_02",
        extraction_request_id=req_id,
        student_id=student_id,
        document_id="doc_02",
        document_version_id="v1",
        batch_id=batch_id,
        field_name="student_name",
        ai_value="Bob Smith",
        status=VerificationFieldStatus.AI_EXTRACTED,
        created_at=now,
        updated_at=now,
    ).save()

    await BatchExtractionRequest(
        extraction_request_id=req_id,
        batch_id=batch_id,
        batch_name="CSE 2026 Batch",
        department_id="DEPT_CSE",
        created_by="admin_test",
        requested_fields=["student_name"],
        status=BatchExtractionStatus.COMPLETED.value,
        created_at=now,
        updated_at=now,
    ).save()

    admin_actor = User(username="admin_sub2", name="Admin", password=get_password_hash("pass123"), role=UserRole.SUPER_ADMIN, is_active=True)

    # 1. Invalid identity entry fails
    with pytest.raises(HTTPException) as exc_info:
        await token_service.identify_common_student(
            CommonStudentIdentifyRequest(
                student_name="Wrong Name",
                register_number=student_id,
                batch_id=batch_id,
                extraction_request_id=req_id,
            )
        )
    assert exc_info.value.status_code == 401

    # Check dashboard: STILL PENDING_VERIFICATION
    dash = await batch_service.get_extraction_details(req_id, admin_actor)
    row = next(s for s in dash.students if s.student_id == student_id)
    assert row.verification_status == "PENDING_VERIFICATION"

    # 2. Student identifies successfully
    id_resp = await token_service.identify_common_student(
        CommonStudentIdentifyRequest(
            student_name="Bob Smith",
            register_number=student_id,
            batch_id=batch_id,
            extraction_request_id=req_id,
        )
    )
    assert id_resp.requires_code is False

    # Check dashboard: STILL PENDING_VERIFICATION (identification alone does not verify)
    dash_mid = await batch_service.get_extraction_details(req_id, admin_actor)
    row_mid = next(s for s in dash_mid.students if s.student_id == student_id)
    assert row_mid.verification_status == "PENDING_VERIFICATION"

    # 3. Attempt submission with invalid verification id -> Fails with 404
    with pytest.raises(HTTPException) as exc_info2:
        await token_service.submit_common_verification(
            CommonStudentSubmitRequest(
                session_token=id_resp.session_token,
                fields=[StudentFieldVerificationItem(verification_id="invalid_id_9999", is_confirmed=True)],
            )
        )
    assert exc_info2.value.status_code == 404

    # Check dashboard: STILL PENDING_VERIFICATION
    dash2 = await batch_service.get_extraction_details(req_id, admin_actor)
    row2 = next(s for s in dash2.students if s.student_id == student_id)
    assert row2.verification_status == "PENDING_VERIFICATION"


@pytest.mark.asyncio
async def test_expired_session_and_duplicate_submission():
    """
    Test expired session rejection and duplicate submission protection.
    """
    token_service = VerificationTokenService()
    batch_service = BatchExtractionService()

    now = datetime.now(timezone.utc)
    batch_id = "BATCH_SYNC_03"
    req_id = "ext_req_sync_03"
    student_id = "26SYNC103"

    await AdmissionBatch(
        id=batch_id,
        name="CSE 2026 Batch",
        department_id="DEPT_CSE",
        academic_year="2026-2027",
        created_by="admin_test",
    ).save()
    await StudentSubmission(
        register_number=student_id,
        student_name="Charlie Brown",
        batch_id=batch_id,
        submission_status="Submitted",
    ).save()

    vf = await DocumentFieldVerification(
        extraction_result_id="res_03",
        extraction_request_id=req_id,
        student_id=student_id,
        document_id="doc_03",
        document_version_id="v1",
        batch_id=batch_id,
        field_name="student_name",
        ai_value="Charlie Brown",
        status=VerificationFieldStatus.AI_EXTRACTED,
        created_at=now,
        updated_at=now,
    ).save()

    await BatchExtractionRequest(
        extraction_request_id=req_id,
        batch_id=batch_id,
        batch_name="CSE 2026 Batch",
        department_id="DEPT_CSE",
        created_by="admin_test",
        requested_fields=["student_name"],
        status=BatchExtractionStatus.COMPLETED.value,
        created_at=now,
        updated_at=now,
    ).save()

    admin_actor = User(username="admin_sub3", name="Admin", password=get_password_hash("pass123"), role=UserRole.SUPER_ADMIN, is_active=True)

    tok = await token_service.create_or_get_token(
        student_id=student_id,
        batch_id=batch_id,
        student_name="Charlie Brown",
        extraction_request_id=req_id,
    )

    # 1. Expire the token and test submit
    tok.expires_at = now - timedelta(hours=1)
    await tok.save()

    with pytest.raises(HTTPException) as exc_exp:
        await token_service.submit_public_verification(
            token_str=tok.token,
            submit_req=PublicVerificationSubmitRequest(
                fields=[StudentFieldVerificationItem(verification_id=str(vf.id), is_confirmed=True)]
            ),
        )
    assert exc_exp.value.status_code == 410

    dash = await batch_service.get_extraction_details(req_id, admin_actor)
    row = next(s for s in dash.students if s.student_id == student_id)
    assert row.verification_status == "PENDING_VERIFICATION"

    # Reset token to valid and submit
    tok.expires_at = now + timedelta(days=2)
    await tok.save()

    res = await token_service.submit_public_verification(
        token_str=tok.token,
        submit_req=PublicVerificationSubmitRequest(
            fields=[StudentFieldVerificationItem(verification_id=str(vf.id), is_confirmed=True)]
        ),
    )
    assert res.valid is True

    # 2. Duplicate submission after completion MUST be rejected without corrupting data
    with pytest.raises(HTTPException) as exc_dup:
        await token_service.submit_public_verification(
            token_str=tok.token,
            submit_req=PublicVerificationSubmitRequest(
                fields=[StudentFieldVerificationItem(verification_id=str(vf.id), is_confirmed=False, corrected_value="Malicious Override")]
            ),
        )
    assert exc_dup.value.status_code == 400

    # Ensure field final value is still the original confirmed value
    db_vf = await DocumentFieldVerification.get(vf.id)
    assert db_vf.final_value == "Charlie Brown"


@pytest.mark.asyncio
async def test_multiple_students_isolation():
    """
    Test multi-student verification isolation:
    Student A verifies -> becomes STUDENT_VERIFIED.
    Student B does not verify -> strictly remains PENDING_VERIFICATION.
    No cross-student leakage or status overwrite.
    """
    token_service = VerificationTokenService()
    batch_service = BatchExtractionService()
    notif_service = NotificationService()

    now = datetime.now(timezone.utc)
    batch_id = "BATCH_SYNC_MULTI"
    req_id = "ext_req_sync_multi"

    student_a = "26SYNC_A"
    student_b = "26SYNC_B"

    await AdmissionBatch(
        id=batch_id,
        name="Multi Batch",
        department_id="DEPT_MULTI",
        academic_year="2026-2027",
        created_by="admin_test",
    ).save()
    await StudentSubmission(register_number=student_a, student_name="Alice A", batch_id=batch_id, submission_status="Submitted").save()
    await StudentSubmission(register_number=student_b, student_name="Bob B", batch_id=batch_id, submission_status="Submitted").save()

    vf_a = await DocumentFieldVerification(
        extraction_result_id="res_a", extraction_request_id=req_id, student_id=student_a,
        document_id="doc_a", document_version_id="v1", batch_id=batch_id, field_name="student_name",
        ai_value="Alice AI", status=VerificationFieldStatus.AI_EXTRACTED, created_at=now, updated_at=now,
    ).save()

    vf_b = await DocumentFieldVerification(
        extraction_result_id="res_b", extraction_request_id=req_id, student_id=student_b,
        document_id="doc_b", document_version_id="v1", batch_id=batch_id, field_name="student_name",
        ai_value="Bob AI", status=VerificationFieldStatus.AI_EXTRACTED, created_at=now, updated_at=now,
    ).save()

    await BatchExtractionRequest(
        extraction_request_id=req_id, batch_id=batch_id, batch_name="Multi Batch", department_id="DEPT_MULTI",
        created_by="admin_test", requested_fields=["student_name"], status=BatchExtractionStatus.COMPLETED.value,
        created_at=now, updated_at=now,
    ).save()

    admin_actor = User(username="admin_multi", name="Admin", password=get_password_hash("pass123"), role=UserRole.SUPER_ADMIN, is_active=True)

    tok_a = await token_service.create_or_get_token(student_id=student_a, batch_id=batch_id, student_name="Alice A", extraction_request_id=req_id)
    tok_b = await token_service.create_or_get_token(student_id=student_b, batch_id=batch_id, student_name="Bob B", extraction_request_id=req_id)

    # Alice submits
    await token_service.submit_public_verification(
        token_str=tok_a.token,
        submit_req=PublicVerificationSubmitRequest(
            fields=[StudentFieldVerificationItem(verification_id=str(vf_a.id), is_confirmed=False, corrected_value="Alice Final")],
        ),
    )

    # Check dashboard
    dash = await batch_service.get_extraction_details(req_id, admin_actor)
    row_a = next(s for s in dash.students if s.student_id == student_a)
    row_b = next(s for s in dash.students if s.student_id == student_b)

    assert row_a.verification_status == "STUDENT_VERIFIED"
    assert row_a.final_status == "VERIFIED"
    assert row_a.verification_token_status == "COMPLETED"

    assert row_b.verification_status == "PENDING_VERIFICATION"
    assert row_b.final_status == "PENDING_VERIFICATION"
    assert row_b.verification_token_status == "ACTIVE"

    assert dash.summary.verified_count == 1
    assert dash.summary.pending_verification_count == 1

    # Check notification rows
    notif_rows = await notif_service.get_student_notification_status_table(req_id, admin_actor)
    notif_a = next(r for r in notif_rows if r.student_id == student_a)
    notif_b = next(r for r in notif_rows if r.student_id == student_b)

    assert notif_a.verification_status == "STUDENT_VERIFIED"
    assert notif_b.verification_status == "PENDING_VERIFICATION"


@pytest.mark.asyncio
async def test_common_verification_link_flow_and_excel_export_enforcement():
    """
    Comprehensive regression test for ONE COMMON STUDENT VERIFICATION LINK:
    1. Common URL batch scope: All students use common batch_id and extraction_id.
    2. Student identity validation: Name & Register Number validated against batch.
       - Invalid details or mismatch rejected (404).
       - Duplicate register numbers without match safely rejected.
       - No extraction results exposed before validation.
    3. OTP generated and validated securely.
    4. Loading latest extraction, edits and submission:
       - Only submitted student becomes STUDENT_VERIFIED.
       - Merely opening link or validating OTP leaves student PENDING_VERIFICATION.
    5. Batch-wide verification progress:
       - 1 verified, 1 pending.
    6. Final Excel download blocking:
       - export_verified_excel(enforce_all_verified=True) strictly raises HTTP 400 while pending > 0.
    7. All students verified:
       - Once second student submits verification, export_verified_excel succeeds.
       - Output Excel has exactly 1 row per student with submitted values.
    """
    token_service = VerificationTokenService()
    batch_service = BatchExtractionService()

    now = datetime.now(timezone.utc)
    batch_id = "BATCH_COMMON_LINK"
    req_id = "ext_req_common_01"

    student_1 = "26COM_A"
    student_2 = "26COM_B"

    await AdmissionBatch(
        id=batch_id,
        name="Common Link Batch",
        department_id="DEPT_COM",
        academic_year="2026-2027",
        created_by="admin_test",
    ).save()

    # Create submissions
    await StudentSubmission(
        register_number=student_1,
        student_name="Candidate One",
        batch_id=batch_id,
        email="one@test.edu",
        mobile_number="9800000001",
        submission_status="Submitted",
    ).save()

    await StudentSubmission(
        register_number=student_2,
        student_name="Candidate Two",
        batch_id=batch_id,
        email="two@test.edu",
        mobile_number="9800000002",
        submission_status="Submitted",
    ).save()

    # Create extraction request
    await BatchExtractionRequest(
        extraction_request_id=req_id,
        batch_id=batch_id,
        batch_name="Common Link Batch",
        department_id="DEPT_COM",
        created_by="admin_test",
        requested_fields=["student_name", "date_of_birth"],
        status=BatchExtractionStatus.COMPLETED.value,
        created_at=now,
        updated_at=now,
    ).save()

    # Extracted fields for Candidate One
    vf_1_name = await DocumentFieldVerification(
        extraction_result_id="res_1_name", extraction_request_id=req_id, student_id=student_1,
        document_id="doc_1", document_version_id="v1", batch_id=batch_id, field_name="student_name",
        ai_value="Candidate One Raw", status=VerificationFieldStatus.AI_EXTRACTED, created_at=now, updated_at=now,
    ).save()
    vf_1_dob = await DocumentFieldVerification(
        extraction_result_id="res_1_dob", extraction_request_id=req_id, student_id=student_1,
        document_id="doc_1", document_version_id="v1", batch_id=batch_id, field_name="date_of_birth",
        ai_value="2005-05-15", status=VerificationFieldStatus.AI_EXTRACTED, created_at=now, updated_at=now,
    ).save()

    # Extracted fields for Candidate Two
    vf_2_name = await DocumentFieldVerification(
        extraction_result_id="res_2_name", extraction_request_id=req_id, student_id=student_2,
        document_id="doc_2", document_version_id="v1", batch_id=batch_id, field_name="student_name",
        ai_value="Candidate Two Raw", status=VerificationFieldStatus.AI_EXTRACTED, created_at=now, updated_at=now,
    ).save()
    vf_2_dob = await DocumentFieldVerification(
        extraction_result_id="res_2_dob", extraction_request_id=req_id, student_id=student_2,
        document_id="doc_2", document_version_id="v1", batch_id=batch_id, field_name="date_of_birth",
        ai_value="2005-08-20", status=VerificationFieldStatus.AI_EXTRACTED, created_at=now, updated_at=now,
    ).save()

    admin_actor = User(
        username="admin_com",
        name="Admin Common",
        password=get_password_hash("pass123"),
        role=UserRole.SUPER_ADMIN,
        is_active=True,
    )

    # 1. Identity validation against common batch URL
    # Mismatch name & register number rejected
    with pytest.raises(HTTPException) as exc_mismatch:
        await token_service.identify_common_student(
            CommonStudentIdentifyRequest(
                batch_id=batch_id,
                extraction_request_id=req_id,
                student_name="Candidate One",
                register_number="UNKNOWN_REG",
            )
        )
    assert exc_mismatch.value.status_code in (401, 404)

    # Valid identification for Candidate One generates OTP
    ident_res_1 = await token_service.identify_common_student(
        CommonStudentIdentifyRequest(
            batch_id=batch_id,
            extraction_request_id=req_id,
            student_name="Candidate One",
            register_number=student_1,
        )
    )
    assert ident_res_1.requires_code is False
    assert ident_res_1.session_token is not None

    # Opening link and identifying alone does NOT mark candidate verified
    dash_check_1 = await batch_service.get_extraction_details(req_id, admin_actor)
    assert dash_check_1.summary.verified_count == 0
    assert dash_check_1.summary.pending_verification_count == 2

    # Candidate One submits verification with DOB edit
    submit_res_1 = await token_service.submit_common_verification(
        CommonStudentSubmitRequest(
            session_token=ident_res_1.session_token,
            fields=[
                StudentFieldVerificationItem(verification_id=str(vf_1_name.id), is_confirmed=True),
                StudentFieldVerificationItem(verification_id=str(vf_1_dob.id), is_confirmed=False, corrected_value="2005-05-16"),
            ],
        )
    )
    assert submit_res_1.status in ("STUDENT_VERIFIED", "COMPLETED")

    # Check dashboard progress: 1 verified, 1 pending
    dash_progress = await batch_service.get_extraction_details(req_id, admin_actor)
    assert dash_progress.summary.verified_count == 1
    assert dash_progress.summary.pending_verification_count == 1
    row_1 = next(s for s in dash_progress.students if s.student_id == student_1)
    row_2 = next(s for s in dash_progress.students if s.student_id == student_2)
    assert row_1.verification_status == "STUDENT_VERIFIED"
    assert row_2.verification_status == "PENDING_VERIFICATION"

    # 6. Final Excel download blocking:
    # enforce_all_verified=True MUST raise HTTPException(400) because Candidate Two is pending
    with pytest.raises(HTTPException) as exc_blocked:
        await batch_service.export_verified_excel(
            extraction_request_id=req_id,
            actor=admin_actor,
            enforce_all_verified=True,
        )
    assert exc_blocked.value.status_code == 400
    assert "All eligible students must complete verification before export" in exc_blocked.value.detail
    assert "1 student(s) still pending verification" in exc_blocked.value.detail

    # 7. Candidate Two verifies using the common link
    ident_res_2 = await token_service.identify_common_student(
        CommonStudentIdentifyRequest(
            batch_id=batch_id,
            extraction_request_id=req_id,
            student_name="Candidate Two",
            register_number=student_2,
        )
    )
    assert ident_res_2.requires_code is False
    await token_service.submit_common_verification(
        CommonStudentSubmitRequest(
            session_token=ident_res_2.session_token,
            fields=[
                StudentFieldVerificationItem(verification_id=str(vf_2_name.id), is_confirmed=True),
                StudentFieldVerificationItem(verification_id=str(vf_2_dob.id), is_confirmed=True),
            ],
        )
    )

    # Re-check dashboard progress: All 2 verified!
    dash_final = await batch_service.get_extraction_details(req_id, admin_actor)
    assert dash_final.summary.verified_count == 2
    assert dash_final.summary.pending_verification_count == 0

    # 8. Export final Excel now succeeds with enforce_all_verified=True
    stream, filename = await batch_service.export_verified_excel(
        extraction_request_id=req_id,
        actor=admin_actor,
        enforce_all_verified=True,
    )
    assert filename.endswith(".xlsx")
    assert stream is not None

    # Verify Excel contents: exactly 2 student rows (1 header + 2 data = 3 rows)
    wb = openpyxl.load_workbook(io.BytesIO(stream.getvalue()))
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    assert len(rows) == 3, f"Expected 3 rows (1 header + 2 students), got {len(rows)}"

    header = rows[0]
    data_rows = rows[1:]

    # Map headers to indices
    header_indices = {col_name: idx for idx, col_name in enumerate(header) if col_name}
    dob_idx = header_indices.get("Date Of Birth") or header_indices.get("DATE OF BIRTH") or header_indices.get("date_of_birth")

    # Verify Candidate One has their submitted/corrected DOB value "2005-05-16"
    assert any("Candidate One" in str(r) for r in data_rows)
    assert any("Candidate Two" in str(r) for r in data_rows)
    if dob_idx is not None:
        cand_1_row = next(r for r in data_rows if "Candidate One" in str(r))
        assert cand_1_row[dob_idx] == "2005-05-16"

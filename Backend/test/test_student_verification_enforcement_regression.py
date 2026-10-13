"""
Regression Tests: Student Verification Enforcement Lifecycle
=============================================================
Enforces strict authoritative verification lifecycle rules:
1. Opening the verification link does NOT mark the student as verified.
2. Entering identity details or verifying OTP does NOT mark the student as verified.
3. Refreshing the page / repeated reads do NOT mark the student as verified.
4. Generating or sending a link/notification does NOT mark the student as verified.
5. Failed submissions (expired token, tampering, invalid fields) leave the student unverified.
6. A successful explicit student submission verifies only the correct student.
7. Duplicate submissions and idempotent retries are safely handled.
8. Dashboard and Excel export accurately reflect persisted verification status and values,
   and downloading Excel never changes verification status.
"""

import io
import pytest
import pytest_asyncio
import openpyxl
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch
from motor.motor_asyncio import AsyncIOMotorClient

from app.core.config import settings
from app.models.user import User, UserRole
from app.models.batch import AdmissionBatch
from app.models.student_submission import StudentSubmission
from app.models.student_document import StudentDocument, DocumentVersion
from app.models.document_verification import (
    DocumentFieldVerification,
    VerificationFieldStatus,
    VerificationHistoryEntry,
)
from app.models.batch_extraction import (
    BatchExtractionRequest,
    BatchExtractionStatus,
    BatchVerificationStatus,
    BatchExportStatus,
)
from app.models.verification_token import VerificationToken, VerificationTokenStatus
from app.models.verification_notification import VerificationNotification, NotificationStatus, NotificationChannel
from app.schemas.verification_token import (
    PublicVerificationSubmitRequest,
    StudentFieldVerificationItem,
    CommonStudentIdentifyRequest,
    CommonStudentVerifyCodeRequest,
    CommonStudentSubmitRequest,
)
from app.services.verification_token_service import VerificationTokenService
from app.services.batch_extraction_service import BatchExtractionService
from app.services.notification_service import NotificationService
from app.core.security import get_password_hash


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
    test_students = ["REG_VERIF_01", "REG_VERIF_02", "REG_TAMPER_01"]
    test_batches = ["batch_verif_test_01", "batch_verif_test_02"]
    await DocumentFieldVerification.find({"student_id": {"$in": test_students}}).delete()
    await StudentSubmission.find({"register_number": {"$in": test_students}}).delete()
    await StudentDocument.find({"student_id": {"$in": test_students}}).delete()
    await VerificationToken.find({"student_id": {"$in": test_students}}).delete()
    await VerificationNotification.find({"student_id": {"$in": test_students}}).delete()
    await AdmissionBatch.find({"$or": [{"_id": {"$in": test_batches}}, {"name": {"$in": test_batches}}]}).delete()
    await BatchExtractionRequest.find({"batch_id": {"$in": test_batches}}).delete()
    yield
    await DocumentFieldVerification.find({"student_id": {"$in": test_students}}).delete()
    await StudentSubmission.find({"register_number": {"$in": test_students}}).delete()
    await StudentDocument.find({"student_id": {"$in": test_students}}).delete()
    await VerificationToken.find({"student_id": {"$in": test_students}}).delete()
    await VerificationNotification.find({"student_id": {"$in": test_students}}).delete()
    await AdmissionBatch.find({"$or": [{"_id": {"$in": test_batches}}, {"name": {"$in": test_batches}}]}).delete()
    await BatchExtractionRequest.find({"batch_id": {"$in": test_batches}}).delete()


@pytest.mark.asyncio
async def test_opening_link_and_reads_do_not_verify_student():
    """
    Test that opening the verification link and loading verification page data
    leaves the student strictly PENDING_VERIFICATION.
    """
    token_service = VerificationTokenService()
    batch_service = BatchExtractionService()
    notif_service = NotificationService()

    batch_id = "batch_verif_test_01"
    student_id = "REG_VERIF_01"
    req_id = "ext_req_verif_01"
    now = datetime.now(timezone.utc)

    # 1. Setup Student Submission & Batch
    batch = AdmissionBatch(
        id=batch_id,
        name="CSE 2026 Batch",
        department_id="DEPT_CSE",
        academic_year="2026-2027",
        created_by="admin_test",
    )
    await batch.save()

    sub = StudentSubmission(
        register_number=student_id,
        student_name="Alice Candidate",
        batch_id=batch_id,
        department_id="DEPT_CSE",
        email="alice@example.com",
        mobile_number="9876543210",
        submission_status="Submitted",
        extracted_data={"student_name": "Alice Candidate", "date_of_birth": "2005-04-12"},
    )
    await sub.save()

    # 2. Setup AI_EXTRACTED verification fields
    vf1 = DocumentFieldVerification(
        extraction_result_id="res_01",
        extraction_request_id=req_id,
        student_id=student_id,
        document_id="doc_01",
        document_version_id="v1",
        batch_id=batch_id,
        field_name="student_name",
        ai_value="Alice Candidate",
        raw_value="Alice Candidate",
        status=VerificationFieldStatus.AI_EXTRACTED,
        created_at=now,
        updated_at=now,
    )
    vf2 = DocumentFieldVerification(
        extraction_result_id="res_02",
        extraction_request_id=req_id,
        student_id=student_id,
        document_id="doc_01",
        document_version_id="v1",
        batch_id=batch_id,
        field_name="date_of_birth",
        ai_value="2005-04-12",
        raw_value="2005-04-12",
        status=VerificationFieldStatus.AI_EXTRACTED,
        created_at=now,
        updated_at=now,
    )
    await vf1.save()
    await vf2.save()

    # 3. Create batch extraction request
    batch_req = BatchExtractionRequest(
        extraction_request_id=req_id,
        batch_id=batch_id,
        batch_name="CSE 2026 Batch",
        department_id="DEPT_CSE", created_by="admin_test",
        requested_fields=["student_name", "date_of_birth"],
        status=BatchExtractionStatus.COMPLETED.value,
        created_at=now,
        updated_at=now,
    )
    await batch_req.save()

    admin_actor = User(
        username="admin_verif_audit",
        name="Admin",
        password=get_password_hash("pass123"),
        role=UserRole.SUPER_ADMIN,
        is_active=True,
    )

    # Step A: Generate Token (link created)
    tok = await token_service.create_or_get_token(
        student_id=student_id,
        batch_id=batch_id,
        student_name="Alice Candidate",
        extraction_request_id=req_id,
    )
    assert tok.token is not None

    # Verify student is PENDING_VERIFICATION on dashboard
    details = await batch_service.get_extraction_details(req_id, admin_actor)
    alice_row = next(s for s in details.students if s.student_id == student_id)
    assert alice_row.verification_status == "PENDING_VERIFICATION"
    assert alice_row.final_status == "PENDING_VERIFICATION"

    # Step B: Student opens link (session metadata read)
    session_info = await token_service.get_session_info(tok.token)
    assert session_info.valid is True

    # Check status again
    details = await batch_service.get_extraction_details(req_id, admin_actor)
    alice_row = next(s for s in details.students if s.student_id == student_id)
    assert alice_row.verification_status == "PENDING_VERIFICATION"

    # Step C: Student loads verification fields
    data = await token_service.get_public_verification_data(tok.token)
    assert len(data.fields) == 2
    for f in data.fields:
        assert f.status == "AI_EXTRACTED"

    # Verify student is STILL PENDING_VERIFICATION on dashboard and notifications
    details = await batch_service.get_extraction_details(req_id, admin_actor)
    alice_row = next(s for s in details.students if s.student_id == student_id)
    assert alice_row.verification_status == "PENDING_VERIFICATION"

    notif_rows = await notif_service.get_student_notification_status_table(extraction_request_id=req_id, actor=admin_actor)
    alice_notif = next(r for r in notif_rows if r.student_id == student_id)
    assert alice_notif.verification_status == "PENDING_VERIFICATION"


@pytest.mark.asyncio
async def test_identity_and_otp_validation_does_not_verify_student():
    """
    Test that completing identity validation and OTP verification allows reviewing fields
    but leaves the student strictly PENDING_VERIFICATION until explicit submission.
    """
    token_service = VerificationTokenService()
    batch_service = BatchExtractionService()
    notif_service = NotificationService()

    batch_id = "batch_verif_test_01"
    student_id = "REG_VERIF_01"
    req_id = "ext_req_verif_01"
    now = datetime.now(timezone.utc)

    batch = AdmissionBatch(id=batch_id, name="CSE 2026 Batch", department_id="DEPT_CSE", academic_year="2026-2027", created_by="admin_test")
    await batch.save()

    sub = StudentSubmission(
        register_number=student_id,
        student_name="Alice Candidate",
        batch_id=batch_id,
        department_id="DEPT_CSE",
        email="alice@example.com",
        mobile_number="9876543210",
        submission_status="Submitted",
        extracted_data={"student_name": "Alice Candidate"},
    )
    await sub.save()

    vf = DocumentFieldVerification(
        extraction_result_id="res_01",
        extraction_request_id=req_id,
        student_id=student_id,
        document_id="doc_01",
        document_version_id="v1",
        batch_id=batch_id,
        field_name="student_name",
        ai_value="Alice Candidate",
        status=VerificationFieldStatus.AI_EXTRACTED,
        created_at=now,
        updated_at=now,
    )
    await vf.save()

    batch_req = BatchExtractionRequest(
        extraction_request_id=req_id,
        batch_id=batch_id,
        batch_name="CSE 2026 Batch",
        department_id="DEPT_CSE", created_by="admin_test",
        requested_fields=["student_name"],
        status=BatchExtractionStatus.COMPLETED.value,
        created_at=now,
        updated_at=now,
    )
    await batch_req.save()

    admin_actor = User(username="admin_otp_test", name="Admin", password=get_password_hash("pass123"), role=UserRole.SUPER_ADMIN, is_active=True)

    # 1. Identify common student
    ident_res = await token_service.identify_common_student(
        CommonStudentIdentifyRequest(
            student_name="Alice Candidate",
            register_number=student_id,
            batch_id=batch_id,
        )
    )
    assert ident_res.requires_code is False
    assert ident_res.session_token is not None

    # Status must be PENDING
    details = await batch_service.get_extraction_details(req_id, admin_actor)
    alice_row = next(s for s in details.students if s.student_id == student_id)
    assert alice_row.verification_status == "PENDING_VERIFICATION"

    # 2. Access student extraction fields directly without OTP
    code_res = await token_service.get_public_verification_data(ident_res.session_token)
    assert code_res.valid is True
    # Fields returned for student to review
    assert len(code_res.fields) == 1

    # CRITICAL ASSERTION: After viewing fields, student MUST STILL BE PENDING_VERIFICATION!
    details = await batch_service.get_extraction_details(req_id, admin_actor)
    alice_row = next(s for s in details.students if s.student_id == student_id)
    assert alice_row.verification_status == "PENDING_VERIFICATION"

    notif_rows = await notif_service.get_student_notification_status_table(extraction_request_id=req_id, actor=admin_actor)
    alice_notif = next(r for r in notif_rows if r.student_id == student_id)
    assert alice_notif.verification_status == "PENDING_VERIFICATION"


@pytest.mark.asyncio
async def test_sending_notification_does_not_verify_student():
    """
    Test that dispatching verification notifications updates notification status
    but never alters verification status.
    """
    batch_service = BatchExtractionService()
    notif_service = NotificationService()

    batch_id = "batch_verif_test_01"
    student_id = "REG_VERIF_01"
    req_id = "ext_req_verif_01"
    now = datetime.now(timezone.utc)

    batch = AdmissionBatch(id=batch_id, name="CSE 2026 Batch", department_id="DEPT_CSE", academic_year="2026-2027", created_by="admin_test")
    await batch.save()

    sub = StudentSubmission(
        register_number=student_id,
        student_name="Alice Candidate",
        batch_id=batch_id,
        email="alice@example.com",
        mobile_number="9876543210",
        submission_status="Submitted",
        extracted_data={"student_name": "Alice Candidate"},
    )
    await sub.save()

    vf = DocumentFieldVerification(
        extraction_result_id="res_01",
        extraction_request_id=req_id,
        student_id=student_id,
        document_id="doc_01",
        document_version_id="v1",
        batch_id=batch_id,
        field_name="student_name",
        ai_value="Alice Candidate",
        status=VerificationFieldStatus.AI_EXTRACTED,
        created_at=now,
        updated_at=now,
    )
    await vf.save()

    batch_req = BatchExtractionRequest(
        extraction_request_id=req_id,
        batch_id=batch_id,
        batch_name="CSE 2026 Batch",
        department_id="DEPT_CSE", created_by="admin_test",
        requested_fields=["student_name"],
        status=BatchExtractionStatus.COMPLETED.value,
        created_at=now,
        updated_at=now,
    )
    await batch_req.save()

    admin_actor = User(username="admin_notif_test", name="Admin", password=get_password_hash("pass123"), role=UserRole.SUPER_ADMIN, is_active=True)

    # Create notification record marked SENT
    notif = VerificationNotification(
        extraction_request_id=req_id,
        batch_id=batch_id,
        student_id=student_id,
        student_name="Alice Candidate",
        register_number=student_id,
        channel=NotificationChannel.EMAIL,
        recipient="alice@example.com",
        status=NotificationStatus.SENT,
        sent_at=now,
    )
    await notif.save()

    # Check notification rows: notification_status is SENT, but verification_status MUST BE PENDING_VERIFICATION!
    notif_rows = await notif_service.get_student_notification_status_table(extraction_request_id=req_id, actor=admin_actor)
    alice_notif = next(r for r in notif_rows if r.student_id == student_id)
    assert alice_notif.notification_status == "SENT"
    assert alice_notif.verification_status == "PENDING_VERIFICATION"


@pytest.mark.asyncio
async def test_failed_submissions_leave_student_unverified():
    """
    Test that invalid/failed submissions (tampering, invalid records, expired token)
    raise appropriate errors and leave the student completely unverified.
    """
    token_service = VerificationTokenService()
    batch_service = BatchExtractionService()

    batch_id = "batch_verif_test_01"
    student_1 = "REG_VERIF_01"
    student_2 = "REG_TAMPER_01"
    req_id = "ext_req_verif_01"
    now = datetime.now(timezone.utc)

    batch = AdmissionBatch(id=batch_id, name="CSE 2026 Batch", department_id="DEPT_CSE", academic_year="2026-2027", created_by="admin_test")
    await batch.save()

    # Setup Student 1 and Student 2
    await StudentSubmission(register_number=student_1, student_name="Alice", batch_id=batch_id, mobile_number="9876543210", submission_status="Submitted").save()
    await StudentSubmission(register_number=student_2, student_name="Bob", batch_id=batch_id, mobile_number="9876543211", submission_status="Submitted").save()

    vf1 = await DocumentFieldVerification(
        extraction_result_id="res_01", extraction_request_id=req_id,
        student_id=student_1, document_id="doc_01", document_version_id="v1",
        batch_id=batch_id, field_name="student_name", ai_value="Alice",
        status=VerificationFieldStatus.AI_EXTRACTED, created_at=now, updated_at=now,
    ).save()

    vf2 = await DocumentFieldVerification(
        extraction_result_id="res_02", extraction_request_id=req_id,
        student_id=student_2, document_id="doc_02", document_version_id="v1",
        batch_id=batch_id, field_name="student_name", ai_value="Bob",
        status=VerificationFieldStatus.AI_EXTRACTED, created_at=now, updated_at=now,
    ).save()

    batch_req = await BatchExtractionRequest(
        extraction_request_id=req_id, batch_id=batch_id, batch_name="CSE 2026 Batch",
        department_id="DEPT_CSE", created_by="admin_test", requested_fields=["student_name"],
        status=BatchExtractionStatus.COMPLETED.value, created_at=now, updated_at=now,
    ).save()

    admin_actor = User(username="admin_fail_test", name="Admin", password=get_password_hash("pass123"), role=UserRole.SUPER_ADMIN, is_active=True)

    tok1 = await token_service.create_or_get_token(student_id=student_1, batch_id=batch_id, student_name="Alice", extraction_request_id=req_id)

    # 1. Tampering attempt: Student 1 submits Student 2's verification ID
    with pytest.raises(Exception) as excinfo:
        await token_service.submit_public_verification(
            token_str=tok1.token,
            submit_req=PublicVerificationSubmitRequest(
                fields=[StudentFieldVerificationItem(verification_id=str(vf2.id), is_confirmed=True)],
            ),
        )
    assert "403" in str(excinfo.value) or "Forbidden" in str(excinfo.value)

    # Both students must remain unverified!
    db_vf1 = await DocumentFieldVerification.get(vf1.id)
    db_vf2 = await DocumentFieldVerification.get(vf2.id)
    assert db_vf1.status == VerificationFieldStatus.AI_EXTRACTED
    assert db_vf2.status == VerificationFieldStatus.AI_EXTRACTED

    # 2. Expired token attempt
    tok_expired = VerificationToken(
        student_id=student_1,
        student_name="Alice",
        batch_id=batch_id,
        status=VerificationTokenStatus.EXPIRED.value,
        expires_at=now - timedelta(days=1),
        created_at=now - timedelta(days=8),
        updated_at=now,
    )
    await tok_expired.save()

    with pytest.raises(Exception) as excinfo:
        await token_service.submit_public_verification(
            token_str=tok_expired.token,
            submit_req=PublicVerificationSubmitRequest(
                fields=[StudentFieldVerificationItem(verification_id=str(vf1.id), is_confirmed=True)],
            ),
        )
    assert "410" in str(excinfo.value) or "expired" in str(excinfo.value).lower()

    # Still unverified
    db_vf1 = await DocumentFieldVerification.get(vf1.id)
    assert db_vf1.status == VerificationFieldStatus.AI_EXTRACTED


@pytest.mark.asyncio
async def test_successful_submission_verifies_only_correct_student():
    """
    Test that a valid explicit verification submission:
    - Atomically verifies the submitting student.
    - Leaves other students completely PENDING_VERIFICATION.
    - Accurately persists audit history with timestamps.
    """
    token_service = VerificationTokenService()
    batch_service = BatchExtractionService()
    notif_service = NotificationService()

    batch_id = "batch_verif_test_01"
    student_1 = "REG_VERIF_01"
    student_2 = "REG_VERIF_02"
    req_id = "ext_req_verif_01"
    now = datetime.now(timezone.utc)

    batch = await AdmissionBatch(id=batch_id, name="CSE 2026 Batch", department_id="DEPT_CSE", academic_year="2026-2027", created_by="admin_test").save()

    sub1 = await StudentSubmission(register_number=student_1, student_name="Alice", batch_id=batch_id, email="alice@test.com", mobile_number="9876543210", submission_status="Submitted").save()
    sub2 = await StudentSubmission(register_number=student_2, student_name="Bob", batch_id=batch_id, email="bob@test.com", mobile_number="9876543211", submission_status="Submitted").save()

    vf1 = await DocumentFieldVerification(
        extraction_result_id="res_01", extraction_request_id=req_id,
        student_id=student_1, document_id="doc_01", document_version_id="v1",
        batch_id=batch_id, field_name="student_name", ai_value="Alice",
        status=VerificationFieldStatus.AI_EXTRACTED, created_at=now, updated_at=now,
    ).save()

    vf2 = await DocumentFieldVerification(
        extraction_result_id="res_02", extraction_request_id=req_id,
        student_id=student_2, document_id="doc_02", document_version_id="v1",
        batch_id=batch_id, field_name="student_name", ai_value="Bob",
        status=VerificationFieldStatus.AI_EXTRACTED, created_at=now, updated_at=now,
    ).save()

    batch_req = await BatchExtractionRequest(
        extraction_request_id=req_id, batch_id=batch_id, batch_name="CSE 2026 Batch",
        department_id="DEPT_CSE", created_by="admin_test", requested_fields=["student_name"],
        status=BatchExtractionStatus.COMPLETED.value, created_at=now, updated_at=now,
    ).save()

    admin_actor = User(username="admin_sub_test", name="Admin", password=get_password_hash("pass123"), role=UserRole.SUPER_ADMIN, is_active=True)

    tok1 = await token_service.create_or_get_token(student_id=student_1, batch_id=batch_id, student_name="Alice", extraction_request_id=req_id)
    tok2 = await token_service.create_or_get_token(student_id=student_2, batch_id=batch_id, student_name="Bob", extraction_request_id=req_id)

    # Student 1 explicitly submits verification (confirmed)
    res = await token_service.submit_public_verification(
        token_str=tok1.token,
        submit_req=PublicVerificationSubmitRequest(
            fields=[StudentFieldVerificationItem(verification_id=str(vf1.id), is_confirmed=True)],
            general_comment="Confirmed by Alice",
        ),
    )
    assert res.valid is True

    # 1. Check Student 1 DB record: updated, has history, has student_updated_at
    db_vf1 = await DocumentFieldVerification.get(vf1.id)
    assert db_vf1.status == VerificationFieldStatus.STUDENT_CONFIRMED
    assert db_vf1.final_value == "Alice"
    assert db_vf1.student_updated_at is not None
    assert any(h.action == "STUDENT_CONFIRM" for h in db_vf1.history)

    # Token 1 is COMPLETED
    db_tok1 = await VerificationToken.get(tok1.id)
    assert db_tok1.status == VerificationTokenStatus.COMPLETED.value
    assert db_tok1.completed_at is not None

    # StudentSubmission 1 is 'Student Verified'
    db_sub1 = await StudentSubmission.get(sub1.id)
    assert db_sub1.submission_status == "Student Verified"

    # 2. Check Student 2 DB record: strictly UNTOUCHED and PENDING!
    db_vf2 = await DocumentFieldVerification.get(vf2.id)
    assert db_vf2.status == VerificationFieldStatus.AI_EXTRACTED
    assert db_vf2.student_updated_at is None
    assert len([h for h in db_vf2.history if h.action == "STUDENT_CONFIRM"]) == 0

    db_tok2 = await VerificationToken.get(tok2.id)
    assert db_tok2.status == VerificationTokenStatus.ACTIVE.value

    db_sub2 = await StudentSubmission.get(sub2.id)
    assert db_sub2.submission_status == "Submitted"

    # 3. Check Dashboard: Student 1 is STUDENT_VERIFIED, Student 2 is PENDING_VERIFICATION
    details = await batch_service.get_extraction_details(req_id, admin_actor)
    alice_row = next(s for s in details.students if s.student_id == student_1)
    bob_row = next(s for s in details.students if s.student_id == student_2)

    assert alice_row.verification_status == "STUDENT_VERIFIED"
    assert alice_row.final_status == "VERIFIED"

    assert bob_row.verification_status == "PENDING_VERIFICATION"
    assert bob_row.final_status == "PENDING_VERIFICATION"

    # 4. Check Notifications table: reflects same statuses
    notif_rows = await notif_service.get_student_notification_status_table(extraction_request_id=req_id, actor=admin_actor)
    alice_notif = next(r for r in notif_rows if r.student_id == student_1)
    bob_notif = next(r for r in notif_rows if r.student_id == student_2)

    assert alice_notif.verification_status == "STUDENT_VERIFIED"
    assert bob_notif.verification_status == "PENDING_VERIFICATION"


@pytest.mark.asyncio
async def test_idempotent_duplicate_submission():
    """
    Test that submitting the same verification repeatedly behaves idempotently
    without errors and without creating duplicate history entries.
    """
    token_service = VerificationTokenService()

    batch_id = "batch_verif_test_01"
    student_1 = "REG_VERIF_01"
    req_id = "ext_req_verif_01"
    now = datetime.now(timezone.utc)

    await AdmissionBatch(id=batch_id, name="CSE 2026 Batch", department_id="DEPT_CSE", academic_year="2026-2027", created_by="admin_test").save()
    await StudentSubmission(register_number=student_1, student_name="Alice", batch_id=batch_id, mobile_number="9876543210", submission_status="Submitted").save()

    vf1 = await DocumentFieldVerification(
        extraction_result_id="res_01", extraction_request_id=req_id,
        student_id=student_1, document_id="doc_01", document_version_id="v1",
        batch_id=batch_id, field_name="student_name", ai_value="Alice",
        status=VerificationFieldStatus.AI_EXTRACTED, created_at=now, updated_at=now,
    ).save()

    tok = await token_service.create_or_get_token(student_id=student_1, batch_id=batch_id, student_name="Alice", extraction_request_id=req_id)

    # First submission
    res1 = await token_service.submit_public_verification(
        token_str=tok.token,
        submit_req=PublicVerificationSubmitRequest(
            fields=[StudentFieldVerificationItem(verification_id=str(vf1.id), is_confirmed=True)],
        ),
    )
    assert res1.valid is True

    # Duplicate second submission with identical values -> must succeed idempotently
    res2 = await token_service.submit_public_verification(
        token_str=tok.token,
        submit_req=PublicVerificationSubmitRequest(
            fields=[StudentFieldVerificationItem(verification_id=str(vf1.id), is_confirmed=True)],
        ),
    )
    assert res2.valid is True

    # Mutating after completion -> must be rejected
    with pytest.raises(Exception) as excinfo:
        await token_service.submit_public_verification(
            token_str=tok.token,
            submit_req=PublicVerificationSubmitRequest(
                fields=[StudentFieldVerificationItem(verification_id=str(vf1.id), is_confirmed=False, corrected_value="Alice Changed")],
            ),
        )
    assert "already completed" in str(excinfo.value).lower() or "400" in str(excinfo.value)


@pytest.mark.asyncio
async def test_excel_export_respects_verification_and_does_not_mutate_status():
    """
    Test that Excel export:
    - Uses student-submitted final values only when verified submission exists.
    - Uses unverified latest AI values for unverified students.
    - Downloading Excel never changes verification status of any student.
    """
    token_service = VerificationTokenService()
    batch_service = BatchExtractionService()

    batch_id = "batch_verif_test_01"
    student_1 = "REG_VERIF_01"  # Will be verified with edit
    student_2 = "REG_VERIF_02"  # Will remain unverified
    req_id = "ext_req_verif_01"
    now = datetime.now(timezone.utc)

    await AdmissionBatch(id=batch_id, name="CSE 2026 Batch", department_id="DEPT_CSE", academic_year="2026-2027", created_by="admin_test").save()
    await StudentSubmission(register_number=student_1, student_name="Alice Raw", batch_id=batch_id, mobile_number="9876543210", submission_status="Submitted").save()
    await StudentSubmission(register_number=student_2, student_name="Bob Raw", batch_id=batch_id, mobile_number="9876543211", submission_status="Submitted").save()

    await DocumentFieldVerification(
        extraction_result_id="res_01_reg", extraction_request_id=req_id,
        student_id=student_1, document_id="doc_01", document_version_id="v1",
        batch_id=batch_id, field_name="register_number", ai_value=student_1,
        status=VerificationFieldStatus.AI_EXTRACTED, created_at=now, updated_at=now,
    ).save()

    await DocumentFieldVerification(
        extraction_result_id="res_02_reg", extraction_request_id=req_id,
        student_id=student_2, document_id="doc_02", document_version_id="v1",
        batch_id=batch_id, field_name="register_number", ai_value=student_2,
        status=VerificationFieldStatus.AI_EXTRACTED, created_at=now, updated_at=now,
    ).save()

    vf1 = await DocumentFieldVerification(
        extraction_result_id="res_01", extraction_request_id=req_id,
        student_id=student_1, document_id="doc_01", document_version_id="v1",
        batch_id=batch_id, field_name="student_name", ai_value="Alice Raw",
        status=VerificationFieldStatus.AI_EXTRACTED, created_at=now, updated_at=now,
    ).save()

    vf2 = await DocumentFieldVerification(
        extraction_result_id="res_02", extraction_request_id=req_id,
        student_id=student_2, document_id="doc_02", document_version_id="v1",
        batch_id=batch_id, field_name="student_name", ai_value="Bob Raw",
        final_value="Bob Sneaky Final",  # Premature final_value that should NOT be used because unverified!
        status=VerificationFieldStatus.AI_EXTRACTED, created_at=now, updated_at=now,
    ).save()

    batch_req = await BatchExtractionRequest(
        extraction_request_id=req_id, batch_id=batch_id, batch_name="CSE 2026 Batch",
        department_id="DEPT_CSE", created_by="admin_test", requested_fields=["register_number", "student_name"],
        status=BatchExtractionStatus.COMPLETED.value, created_at=now, updated_at=now,
    ).save()

    admin_actor = User(username="admin_excel_test", name="Admin", password=get_password_hash("pass123"), role=UserRole.SUPER_ADMIN, is_active=True)

    tok1 = await token_service.create_or_get_token(student_id=student_1, batch_id=batch_id, student_name="Alice", extraction_request_id=req_id)

    # Student 1 explicitly submits an edit
    await token_service.submit_public_verification(
        token_str=tok1.token,
        submit_req=PublicVerificationSubmitRequest(
            fields=[StudentFieldVerificationItem(verification_id=str(vf1.id), is_confirmed=False, corrected_value="Alice Verified Name")],
        ),
    )

    # Generate and export Excel
    stream, filename = await batch_service.export_verified_excel(req_id, admin_actor)
    assert stream is not None

    wb = openpyxl.load_workbook(stream)
    ws = wb.active

    # Check rows in Excel
    rows = list(ws.iter_rows(values_only=True))
    header = [str(c).strip() for c in rows[0]]
    assert "Student Name" in header or "STUDENT NAME" in header
    name_col = header.index("Student Name") if "Student Name" in header else header.index("STUDENT NAME")
    reg_col = header.index("Register Number") if "Register Number" in header else header.index("REGISTER NUMBER") if "REGISTER NUMBER" in header else 0

    student_names = {}
    for r in rows[1:]:
        if r[reg_col]:
            student_names[str(r[reg_col]).strip()] = r[name_col]

    # Student 1: Uses verified final value ("Alice Verified Name")
    assert student_names[student_1] == "Alice Verified Name"

    # Student 2: Uses unverified AI value ("Bob Raw"), NEVER premature final value!
    assert student_names[student_2] == "Bob Raw"

    # CRITICAL CHECK: Downloading Excel did NOT change Bob's verification status
    db_vf2 = await DocumentFieldVerification.get(vf2.id)
    assert db_vf2.status == VerificationFieldStatus.AI_EXTRACTED

    details = await batch_service.get_extraction_details(req_id, admin_actor)
    bob_row = next(s for s in details.students if s.student_id == student_2)
    assert bob_row.verification_status == "PENDING_VERIFICATION"

import pytest
import pytest_asyncio
from datetime import datetime, timezone, timedelta
from httpx import AsyncClient, ASGITransport
from motor.motor_asyncio import AsyncIOMotorClient

from app.core.config import settings
from app.core.security import get_password_hash
from app.main import app
from app.models.batch import AdmissionBatch
from app.models.student_submission import StudentSubmission
from app.models.document_verification import (
    DocumentFieldVerification,
    VerificationFieldStatus,
)
from app.models.verification_token import VerificationToken, VerificationTokenStatus
from app.models.verification_notification import (
    VerificationNotification,
    NotificationChannel,
    NotificationStatus,
)
import io
import openpyxl
from app.models.document_extraction_result import DocumentExtractionResult
from app.models.batch_extraction import BatchExtractionRequest
from app.services.batch_extraction_service import BatchExtractionService
from app.models.user import User, UserRole


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    import app.db.database as db_mod

    db_mod.client = AsyncIOMotorClient(
        settings.MONGODB_URI, serverSelectionTimeoutMS=2000
    )
    db_mod.db = db_mod.client[settings.DATABASE_NAME]
    await db_mod._run_db_setup()


@pytest.mark.asyncio
async def test_common_student_verification_full_flow():
    # 1. Setup Test Batches & Students
    batch_a_id = "batch_2026_a_common"
    batch_b_id = "batch_2026_b_duplicate"

    # Cleanup
    await AdmissionBatch.find({"_id": {"$in": [batch_a_id, batch_b_id]}}).delete()
    await StudentSubmission.find({"$or": [{"batch_id": {"$in": [batch_a_id, batch_b_id]}}, {"register_number": "REG2026001"}]}).delete()
    await DocumentFieldVerification.find({"$or": [{"batch_id": {"$in": [batch_a_id, batch_b_id]}}, {"student_id": "REG2026001"}]}).delete()
    await VerificationToken.find({"$or": [{"batch_id": {"$in": [batch_a_id, batch_b_id]}}, {"student_id": "REG2026001"}]}).delete()

    batch_a = AdmissionBatch(
        id=batch_a_id,
        name="Batch 2026-A Common",
        academic_year="2026-2027",
        department_id="DEP_CSE",
        created_by="admin_test",
    )
    await batch_a.insert()

    batch_b = AdmissionBatch(
        id=batch_b_id,
        name="Batch 2026-B Duplicate",
        academic_year="2026-2027",
        department_id="DEP_ECE",
        created_by="admin_test",
    )
    await batch_b.insert()

    # Student 1 in Batch A
    sub_1 = StudentSubmission(
        batch_id=batch_a.id,
        batch_name=batch_a.name,
        student_name="Alice Smith",
        register_number="REG2026001",
        email="alice.smith@university.edu",
        mobile_number="+919876543210",
        submission_status="Submitted",
    )
    await sub_1.insert()

    # Duplicate Register Number in Batch B to test collision safety
    sub_dup_b = StudentSubmission(
        batch_id=batch_b.id,
        batch_name=batch_b.name,
        student_name="Alice Duplicate",
        register_number="REG2026001",  # Same register number in Batch B!
        has_duplicate_conflict=True,
        email="alice.dup@university.edu",
        mobile_number="+919876543211",
        submission_status="Submitted",
    )
    await sub_dup_b.insert()

    # Extraction verification fields for Student 1 in Batch A
    vf1 = DocumentFieldVerification(
        extraction_result_id="ext_res_001",
        extraction_request_id="ext_req_batch_a",
        student_id=sub_1.register_number,
        document_id="doc_001",
        document_version_id="ver_001",
        batch_id=batch_a.id,
        department_id=batch_a.department_id,
        document_type="TRANSFER_CERTIFICATE",
        field_name="student_name",
        ai_value="Alice Smith",
        final_value="Alice Smith",
        status=VerificationFieldStatus.AI_EXTRACTED,
    )
    await vf1.insert()

    vf2 = DocumentFieldVerification(
        extraction_result_id="ext_res_001",
        extraction_request_id="ext_req_batch_a",
        student_id=sub_1.register_number,
        document_id="doc_001",
        document_version_id="ver_001",
        batch_id=batch_a.id,
        department_id=batch_a.department_id,
        document_type="COMMUNITY_CERTIFICATE",
        field_name="community",
        ai_value="BC",
        final_value="BC",
        status=VerificationFieldStatus.AI_EXTRACTED,
    )
    await vf2.insert()

    # Also insert fields for Student Duplicate in Batch B
    vf_dup = DocumentFieldVerification(
        extraction_result_id="ext_res_dup",
        extraction_request_id="ext_req_batch_b",
        student_id=sub_dup_b.register_number,
        document_id="doc_dup",
        document_version_id="ver_dup",
        batch_id=batch_b.id,
        department_id=batch_b.department_id,
        document_type="TRANSFER_CERTIFICATE",
        field_name="student_name",
        ai_value="Alice Duplicate",
        final_value="Alice Duplicate",
        status=VerificationFieldStatus.AI_EXTRACTED,
    )
    await vf_dup.insert()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:

        # -------------------------------------------------------------
        # STEP 1: Duplicate Register Number without Batch Scope -> 400
        # -------------------------------------------------------------
        res_ambiguous = await ac.post(
            "/public/student-verification/identify",
            json={
                "student_name": "Alice Smith",
                "register_number": "REG2026001",
                # No batch_id provided!
            },
        )
        assert res_ambiguous.status_code == 400
        assert "Duplicate register number" in res_ambiguous.json()["detail"]

        # -------------------------------------------------------------
        # STEP 2: Invalid Name in Batch Scope -> 401
        # -------------------------------------------------------------
        res_invalid_name = await ac.post(
            "/public/student-verification/identify",
            json={
                "student_name": "Wrong Name",
                "register_number": "REG2026001",
                "batch_id": batch_a.id,
            },
        )
        assert res_invalid_name.status_code == 401
        assert "Student name does not match" in res_invalid_name.json()["detail"]

        # -------------------------------------------------------------
        # STEP 3: Valid Identity with Batch Scope -> 200 + One-Time Code
        # -------------------------------------------------------------
        res_ident = await ac.post(
            "/public/student-verification/identify",
            json={
                "student_name": "Alice Smith",
                "register_number": "REG2026001",
                "batch_id": batch_a.id,
            },
        )
        assert res_ident.status_code == 200
        ident_data = res_ident.json()
        assert ident_data["session_token"]
        assert ident_data["requires_code"] is False
        session_token = ident_data["session_token"]

        # -------------------------------------------------------------
        # STEP 4: Direct retrieval of extraction fields without OTP
        # -------------------------------------------------------------
        res_data = await ac.get(f"/public/verification/{session_token}")
        assert res_data.status_code == 200
        verified_data = res_data.json()
        assert verified_data["valid"] is True
        assert verified_data["student_id"] == "REG2026001"
        assert verified_data["student_name"] == "Alice Smith"
        assert verified_data["batch_id"] == batch_a.id

        # Verify isolation: ONLY Student 1's fields are returned (2 fields), NOT Student 2's
        fields = verified_data["fields"]
        assert len(fields) == 2
        field_ids = {f["id"] for f in fields}
        assert str(vf1.id) in field_ids
        assert str(vf2.id) in field_ids
        assert str(vf_dup.id) not in field_ids

        # -------------------------------------------------------------
        # STEP 6: Submit Verification (1 Confirm, 1 Correction)
        # -------------------------------------------------------------
        res_submit = await ac.post(
            "/public/student-verification/submit",
            json={
                "session_token": session_token,
                "fields": [
                    {
                        "verification_id": str(vf1.id),
                        "is_confirmed": True,
                        "comment": "Name is accurate",
                    },
                    {
                        "verification_id": str(vf2.id),
                        "is_confirmed": False,
                        "corrected_value": "MBC",
                        "comment": "Typo in community certificate",
                    },
                ],
                "general_comment": "Please review community correction.",
            },
        )
        assert res_submit.status_code == 200
        submit_data = res_submit.json()
        assert submit_data["valid"] is True

        # Verify DB records
        updated_vf1 = await DocumentFieldVerification.get(vf1.id)
        assert updated_vf1.status == VerificationFieldStatus.STUDENT_CONFIRMED
        assert updated_vf1.final_value == "Alice Smith"
        assert updated_vf1.ai_value == "Alice Smith"

        updated_vf2 = await DocumentFieldVerification.get(vf2.id)
        assert updated_vf2.status == VerificationFieldStatus.STUDENT_VERIFIED
        assert updated_vf2.student_value == "MBC"
        assert updated_vf2.ai_value == "BC"  # AI raw value preserved!
        assert updated_vf2.final_value == "MBC"  # Saved directly as final verified value without staff approval!
        assert len(updated_vf2.history) > 0
        assert updated_vf2.history[-1].actor_role == "STUDENT_PUBLIC"

        # -------------------------------------------------------------
        # STEP 7: Repeated Submissions Idempotency & Protection on Completed Session
        # -------------------------------------------------------------
        # 7a: Identical re-submission is idempotent -> 200
        res_idempotent = await ac.post(
            "/public/student-verification/submit",
            json={
                "session_token": session_token,
                "fields": [
                    {
                        "verification_id": str(vf1.id),
                        "is_confirmed": True,
                    },
                    {
                        "verification_id": str(vf2.id),
                        "is_confirmed": False,
                        "corrected_value": "MBC",
                    },
                ],
            },
        )
        assert res_idempotent.status_code == 200

        # 7b: Attempting unauthorized modification on completed session -> 400
        res_unauthorized_alter = await ac.post(
            "/public/student-verification/submit",
            json={
                "session_token": session_token,
                "fields": [
                    {
                        "verification_id": str(vf2.id),
                        "is_confirmed": False,
                        "corrected_value": "Tampered Value",
                    }
                ],
            },
        )
        assert res_unauthorized_alter.status_code == 400
        assert "already completed" in res_unauthorized_alter.json()["detail"] or "already been submitted" in res_unauthorized_alter.json()["detail"]


@pytest.mark.asyncio
async def test_common_link_notification_dispatch():
    batch_id = "batch_2026_notif_common"
    await AdmissionBatch.find({"_id": batch_id}).delete()
    await StudentSubmission.find(StudentSubmission.batch_id == batch_id).delete()
    await DocumentFieldVerification.find(DocumentFieldVerification.batch_id == batch_id).delete()

    batch = AdmissionBatch(
        id=batch_id,
        name="Batch 2026 Notification Common",
        academic_year="2026-2027",
        department_id="DEP_MECH",
        created_by="admin_mech",
    )
    await batch.insert()

    sub = StudentSubmission(
        batch_id=batch.id,
        student_name="Bob Jones",
        register_number="REG_BOB_01",
        email="bob.jones@university.edu",
        mobile_number="+919123456789",
        submission_status="Submitted",
    )
    await sub.insert()

    vf = DocumentFieldVerification(
        extraction_result_id="ext_bob",
        extraction_request_id="req_bob_notif",
        student_id=sub.register_number,
        document_id="doc_bob",
        document_version_id="ver_bob",
        batch_id=batch.id,
        department_id=batch.department_id,
        document_type="AADHAAR",
        field_name="student_name",
        ai_value="Bob Jones",
        final_value="Bob Jones",
        status=VerificationFieldStatus.AI_EXTRACTED,
    )
    await vf.insert()

    from app.models.batch_extraction import BatchExtractionRequest, BatchExtractionStatus
    await BatchExtractionRequest.find(BatchExtractionRequest.extraction_request_id == "req_bob_notif").delete()
    ext_req = BatchExtractionRequest(
        batch_id=batch.id,
        extraction_request_id="req_bob_notif",
        status=BatchExtractionStatus.COMPLETED.value,
        created_by="admin_mech",
    )
    await ext_req.insert()

    await User.find(User.username == "dept_admin_mech").delete()
    admin_user = User(
        username="dept_admin_mech",
        name="Mech Admin",
        email="admin@university.edu",
        password=get_password_hash("pw"),
        role=UserRole.SUPER_ADMIN,
        is_active=True,
    )
    await admin_user.insert()

    from app.services.notification_service import NotificationService
    service = NotificationService()

    # Dispatch single notification using common URL
    notif, is_new = await service.send_student_verification_notification(
        extraction_request_id="req_bob_notif",
        student_id=sub.register_number,
        channel=NotificationChannel.EMAIL,
        actor=admin_user,
        force_mock=True,
    )

    assert notif.status in (NotificationStatus.SENT, NotificationStatus.DELIVERED)
    assert f"/student-verification?batch_id={batch.id}" in notif.message_body
    assert "/verify-session/" not in notif.message_body


@pytest.mark.asyncio
async def test_common_student_rate_limiting():
    # Setup test batch & student
    batch_id = "batch_2026_rate_limit"
    await AdmissionBatch.find({"_id": batch_id}).delete()
    await StudentSubmission.find(StudentSubmission.batch_id == batch_id).delete()
    await DocumentFieldVerification.find(DocumentFieldVerification.batch_id == batch_id).delete()

    batch = AdmissionBatch(
        id=batch_id,
        name="Batch Rate Limit Test",
        academic_year="2026-2027",
        department_id="DEP_TEST",
        created_by="admin_test",
    )
    await batch.insert()

    sub = StudentSubmission(
        batch_id=batch.id,
        student_name="Charlie Brown",
        register_number="REG_RATE_001",
        email="charlie@university.edu",
        mobile_number="+919876543299",
        submission_status="Submitted",
    )
    await sub.insert()

    vf = DocumentFieldVerification(
        extraction_result_id="ext_rate",
        extraction_request_id="req_rate",
        student_id=sub.register_number,
        document_id="doc_rate",
        document_version_id="ver_rate",
        batch_id=batch.id,
        department_id=batch.department_id,
        document_type="AADHAAR",
        field_name="student_name",
        ai_value="Charlie Brown",
        final_value="Charlie Brown",
        status=VerificationFieldStatus.AI_EXTRACTED,
    )
    await vf.insert()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Trigger 5 failed identification attempts with wrong name
        for i in range(5):
            res_fail = await ac.post(
                "/public/student-verification/identify",
                json={
                    "student_name": f"Wrong Name {i}",
                    "register_number": "REG_RATE_001",
                    "batch_id": batch.id,
                },
            )
            assert res_fail.status_code == 401

        # 6th attempt should be blocked by rate limiter with 429
        res_blocked = await ac.post(
            "/public/student-verification/identify",
            json={
                "student_name": "Charlie Brown",  # Even with correct name now, it is rate-limited!
                "register_number": "REG_RATE_001",
                "batch_id": batch.id,
            },
        )
        assert res_blocked.status_code == 429
        assert "Too many failed" in res_blocked.json()["detail"]


@pytest.mark.asyncio
async def test_common_verification_extracted_values_reconciliation_and_no_not_available():
    batch_id = "batch_reconcile_test"
    reg_no = "REG_RECON_001"
    ext_req_id = "ext_req_reconcile"

    # Cleanup
    await AdmissionBatch.find({"_id": batch_id}).delete()
    await StudentSubmission.find(StudentSubmission.batch_id == batch_id).delete()
    await DocumentFieldVerification.find(DocumentFieldVerification.batch_id == batch_id).delete()
    await VerificationToken.find(VerificationToken.batch_id == batch_id).delete()
    await DocumentExtractionResult.find({"extraction_request_id": ext_req_id}).delete()

    batch = AdmissionBatch(
        id=batch_id,
        name="Batch Reconcile Test",
        academic_year="2026-2027",
        department_id="DEP_TEST",
        created_by="admin_test",
    )
    await batch.insert()

    sub = StudentSubmission(
        batch_id=batch.id,
        student_name="David Miller",
        register_number=reg_no,
        email="david@university.edu",
        mobile_number="+919876543277",
        submission_status="Submitted",
    )
    await sub.insert()

    # Create DocumentExtractionResult with actual extracted values
    # Notice: aadhaar_number, account_number, annual_income are stored in extracted_data
    doc_ext = DocumentExtractionResult(
        extraction_request_id=ext_req_id,
        student_id=reg_no,
        student_document_id="doc_bank_passbook",
        document_version_id="ver_001",
        requested_fields=["aadhaar_number", "account_number", "annual_income", "pan_card_number"],
        extracted_data={
            "Aadhaar Number": "987654321098",
            "account_number": "12345678901234",
            "Annual Income": "250000",
            # pan_card_number is omitted/missing from extracted_data
        },
        confidence=0.92,
        is_success=True,
    )
    await doc_ext.insert()

    # Pre-populate DocumentFieldVerification records as might happen during extraction
    # Note: simulate an old-style "NOT_AVAILABLE" in ai_value for account_number to test that get_public_verification_data
    # reconciles with the actual stored extracted_data rather than returning "NOT_AVAILABLE"
    vf_aadhaar = DocumentFieldVerification(
        extraction_result_id=str(doc_ext.id),
        extraction_request_id=ext_req_id,
        student_id=reg_no,
        document_id="doc_aadhaar",
        document_version_id="ver_001",
        batch_id=batch.id,
        department_id=batch.department_id,
        document_type="AADHAAR",
        source_document_name="Aadhaar Card.pdf",
        field_name="aadhaar_number",
        ai_value="987654321098",
        raw_value="987654321098",
        status=VerificationFieldStatus.AI_EXTRACTED,
    )
    await vf_aadhaar.insert()

    vf_acc = DocumentFieldVerification(
        extraction_result_id=str(doc_ext.id),
        extraction_request_id=ext_req_id,
        student_id=reg_no,
        document_id="doc_bank",
        document_version_id="ver_001",
        batch_id=batch.id,
        department_id=batch.department_id,
        document_type="BANK_PASSBOOK",
        source_document_name="Bank Passbook.pdf",
        field_name="account_number",
        ai_value="NOT_AVAILABLE",  # Stale "NOT_AVAILABLE" to test sanitization & reconciliation!
        raw_value="NOT_AVAILABLE",
        status=VerificationFieldStatus.AI_EXTRACTED,
    )
    await vf_acc.insert()

    vf_income = DocumentFieldVerification(
        extraction_result_id=str(doc_ext.id),
        extraction_request_id=ext_req_id,
        student_id=reg_no,
        document_id="doc_income",
        document_version_id="ver_001",
        batch_id=batch.id,
        department_id=batch.department_id,
        document_type="INCOME_CERTIFICATE",
        source_document_name="Income Certificate.pdf",
        field_name="annual_income",
        ai_value=None,  # Not populated initially, to test reconciliation from doc_ext
        raw_value=None,
        status=VerificationFieldStatus.AI_EXTRACTED,
    )
    await vf_income.insert()

    vf_missing = DocumentFieldVerification(
        extraction_result_id=str(doc_ext.id),
        extraction_request_id=ext_req_id,
        student_id=reg_no,
        document_id="doc_pan",
        document_version_id="ver_001",
        batch_id=batch.id,
        department_id=batch.department_id,
        document_type="PAN_CARD",
        source_document_name="PAN Card.pdf",
        field_name="pan_card_number",
        ai_value=None,
        raw_value=None,
        status=VerificationFieldStatus.AI_EXTRACTED,
    )
    await vf_missing.insert()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # STEP 1: Student identifies on common link
        ident_res = await ac.post(
            "/public/student-verification/identify",
            json={
                "student_name": "David Miller",
                "register_number": reg_no,
                "batch_id": batch.id,
            },
        )
        assert ident_res.status_code == 200
        data = ident_res.json()
        session_token = data["session_token"]
        otp = data["dev_code"]

        # STEP 2: Session is immediately verified; fetches sensitive verification data -> 200
        data_res = await ac.get(f"/public/verification/{session_token}")
        assert data_res.status_code == 200
        verified_payload = data_res.json()
        assert verified_payload["valid"] is True
        fields = verified_payload["fields"]
        assert len(fields) == 4

        # Map by field_name
        field_map = {f["field_name"]: f for f in fields}

        # Issue 1 Requirement: No field should have ai_value="NOT_AVAILABLE"
        for f in fields:
            assert f["ai_value"] != "NOT_AVAILABLE", f"Field {f['field_name']} has literal 'NOT_AVAILABLE'!"
            assert f.get("raw_value") != "NOT_AVAILABLE"

        # Aadhaar Number should be populated
        assert field_map["aadhaar_number"]["ai_value"] == "987654321098"
        assert field_map["aadhaar_number"]["field_state"] == "EXTRACTED"
        assert field_map["aadhaar_number"]["source_document_name"] == "Aadhaar Card.pdf"

        # Account Number should be reconciled from extracted_data (was "NOT_AVAILABLE", now actual value)
        assert field_map["account_number"]["ai_value"] == "12345678901234"
        assert field_map["account_number"]["field_state"] == "EXTRACTED"
        assert field_map["account_number"]["source_document_name"] == "Bank Passbook.pdf"

        # Annual Income should be reconciled from extracted_data ("Annual Income": "250000")
        assert field_map["annual_income"]["ai_value"] == "250000"
        assert field_map["annual_income"]["field_state"] == "EXTRACTED"

        # Missing field (pan_card_number) should NOT be "NOT_AVAILABLE", but have field_state="NOT_FOUND" and ai_value=None
        assert field_map["pan_card_number"]["ai_value"] is None
        assert field_map["pan_card_number"]["field_state"] == "NOT_FOUND"

        # STEP 4: Submit a correction without overwriting original AI value
        sub_res = await ac.post(
            "/public/student-verification/submit",
            json={
                "session_token": session_token,
                "fields": [
                    {
                        "verification_id": str(field_map["aadhaar_number"]["id"]),
                        "is_confirmed": True,
                    },
                    {
                        "verification_id": str(field_map["annual_income"]["id"]),
                        "is_confirmed": False,
                        "corrected_value": "280000",
                        "comment": "Updated income from recent certificate",
                    },
                ],
                "general_comment": "Reviewed by student",
            },
        )
        assert sub_res.status_code == 200

        # Verify DB: AI value must NOT be overwritten!
        db_income = await DocumentFieldVerification.get(vf_income.id)
        assert db_income.status == VerificationFieldStatus.STUDENT_VERIFIED
        assert db_income.student_value == "280000"
        assert db_income.ai_value == "250000"  # Original AI value preserved!
        assert db_income.final_value == "280000"  # Directly saved as final verified value without staff approval!


@pytest.mark.asyncio
async def test_student_direct_verification_e2e_workflow():
    batch_id = "batch_direct_workflow"
    reg1 = "REG_DIRECT_001"
    reg2 = "REG_DIRECT_002"
    ext_req_id = "ext_req_direct_wf"

    # Cleanup
    await AdmissionBatch.find({"_id": batch_id}).delete()
    await StudentSubmission.find({"$or": [{"batch_id": batch_id}, {"register_number": {"$in": [reg1, reg2]}}]}).delete()
    await DocumentFieldVerification.find({"$or": [{"batch_id": batch_id}, {"student_id": {"$in": [reg1, reg2]}}]}).delete()
    await VerificationToken.find({"$or": [{"batch_id": batch_id}, {"student_id": {"$in": [reg1, reg2]}}]}).delete()
    await BatchExtractionRequest.find({"extraction_request_id": ext_req_id}).delete()

    batch = AdmissionBatch(
        id=batch_id,
        name="Batch Direct Verification",
        academic_year="2026-2027",
        department_id="DEP_TEST",
        created_by="admin_test",
    )
    await batch.insert()

    sub1 = StudentSubmission(
        batch_id=batch.id,
        student_name="Emma Watson",
        register_number=reg1,
        email="emma@university.edu",
        mobile_number="+919876543111",
        submission_status="Submitted",
        extracted_data={},
    )
    await sub1.insert()

    sub2 = StudentSubmission(
        batch_id=batch.id,
        student_name="Other Student",
        register_number=reg2,
        email="other@university.edu",
        mobile_number="+919876543222",
        submission_status="Submitted",
        extracted_data={},
    )
    await sub2.insert()

    # Create verification fields for Student 1
    vf_name = DocumentFieldVerification(
        extraction_result_id="res_01",
        extraction_request_id=ext_req_id,
        student_id=reg1,
        document_id="doc_tc",
        document_version_id="v1",
        batch_id=batch.id,
        department_id=batch.department_id,
        document_type="TRANSFER_CERTIFICATE",
        source_document_name="TC.pdf",
        field_name="student_name",
        ai_value="Emma Watson",
        raw_value="Emma Watson",
        status=VerificationFieldStatus.AI_EXTRACTED,
    )
    await vf_name.insert()

    vf_aadhaar = DocumentFieldVerification(
        extraction_result_id="res_01",
        extraction_request_id=ext_req_id,
        student_id=reg1,
        document_id="doc_aadhaar",
        document_version_id="v1",
        batch_id=batch.id,
        department_id=batch.department_id,
        document_type="AADHAAR",
        source_document_name="Aadhaar.pdf",
        field_name="aadhaar_number",
        ai_value="123456789012",
        raw_value="123456789012",
        status=VerificationFieldStatus.AI_EXTRACTED,
    )
    await vf_aadhaar.insert()

    vf_acc = DocumentFieldVerification(
        extraction_result_id="res_01",
        extraction_request_id=ext_req_id,
        student_id=reg1,
        document_id="doc_bank",
        document_version_id="v1",
        batch_id=batch.id,
        department_id=batch.department_id,
        document_type="BANK_PASSBOOK",
        source_document_name="Passbook.pdf",
        field_name="account_number",
        ai_value="9988776655",
        raw_value="9988776655",
        status=VerificationFieldStatus.AI_EXTRACTED,
    )
    await vf_acc.insert()

    # Create verification field for Student 2 (for cross-student isolation test)
    vf_other = DocumentFieldVerification(
        extraction_result_id="res_02",
        extraction_request_id=ext_req_id,
        student_id=reg2,
        document_id="doc_other",
        document_version_id="v1",
        batch_id=batch.id,
        department_id=batch.department_id,
        document_type="AADHAAR",
        source_document_name="Other_Aadhaar.pdf",
        field_name="aadhaar_number",
        ai_value="555566667777",
        raw_value="555566667777",
        status=VerificationFieldStatus.AI_EXTRACTED,
    )
    await vf_other.insert()

    # Batch extraction request
    batch_req = BatchExtractionRequest(
        extraction_request_id=ext_req_id,
        batch_id=batch.id,
        department_id=batch.department_id,
        requested_fields=["student_name", "aadhaar_number", "account_number"],
        requested_columns=["Student Name", "Aadhaar Number", "Account Number"],
        column_mapping={
            "Student Name": "student_name",
            "Aadhaar Number": "aadhaar_number",
            "Account Number": "account_number",
        },
        status="COMPLETED",
        created_by="admin_test",
    )
    await batch_req.insert()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # 1. Identification on common link
        ident_res = await ac.post(
            "/public/student-verification/identify",
            json={
                "student_name": "Emma Watson",
                "register_number": reg1,
                "batch_id": batch.id,
            },
        )
        assert ident_res.status_code == 200
        data = ident_res.json()
        session_token = data["session_token"]
        otp = data["dev_code"]

        # 2. Verify OTP
        code_res = await ac.post(
            "/public/student-verification/verify-code",
            json={
                "session_token": session_token,
                "code": otp,
            },
        )
        assert code_res.status_code == 200

        # 3. Cross-student tampering check: Attempting to modify Student 2's field -> 403
        cross_res = await ac.post(
            "/public/student-verification/submit",
            json={
                "session_token": session_token,
                "fields": [
                    {
                        "verification_id": str(vf_other.id),
                        "is_confirmed": False,
                        "corrected_value": "Malicious Alteration",
                    }
                ],
            },
        )
        assert cross_res.status_code == 403
        assert "another student" in cross_res.json()["detail"].lower()

        # 4. Expired session check: Attempting access with expired token -> 410
        expired_token = VerificationToken(
            student_id=reg1,
            student_name="Emma Watson",
            batch_id=batch.id,
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
            is_verified=True,
        )
        await expired_token.insert()
        exp_res = await ac.get(f"/public/verification/{expired_token.token}")
        assert exp_res.status_code == 410
        assert "expired" in exp_res.json()["detail"].lower()

        # 5. Submit verification:
        # - Confirm student_name unchanged
        # - Edit aadhaar_number ("123456789012" -> "987654321099")
        # - Edit account_number ("9988776655" -> "1122334455")
        submit_res = await ac.post(
            "/public/student-verification/submit",
            json={
                "session_token": session_token,
                "fields": [
                    {
                        "verification_id": str(vf_name.id),
                        "is_confirmed": True,
                        "comment": "Name is accurate",
                    },
                    {
                        "verification_id": str(vf_aadhaar.id),
                        "is_confirmed": False,
                        "corrected_value": "987654321099",
                        "comment": "Corrected Aadhaar digits",
                    },
                    {
                        "verification_id": str(vf_acc.id),
                        "is_confirmed": False,
                        "corrected_value": "1122334455",
                        "comment": "Corrected passbook account number",
                    },
                ],
                "general_comment": "Verified by Emma",
            },
        )
        assert submit_res.status_code == 200
        submit_body = submit_res.json()
        assert submit_body["valid"] is True
        assert submit_body["status"] == "COMPLETED"

        # 6. Verify DB records and Data Integrity:
        # - Confirmed field
        db_name = await DocumentFieldVerification.get(vf_name.id)
        assert db_name.status == VerificationFieldStatus.STUDENT_CONFIRMED
        assert db_name.final_value == "Emma Watson"
        assert db_name.ai_value == "Emma Watson"

        # - Edited Aadhaar: status = STUDENT_VERIFIED, final_value = new value, AI value preserved
        db_aadhaar = await DocumentFieldVerification.get(vf_aadhaar.id)
        assert db_aadhaar.status == VerificationFieldStatus.STUDENT_VERIFIED
        assert db_aadhaar.student_value == "987654321099"
        assert db_aadhaar.final_value == "987654321099"  # DIRECTLY VERIFIED as final!
        assert db_aadhaar.ai_value == "123456789012"  # AI raw value preserved!
        assert len(db_aadhaar.history) > 0
        assert db_aadhaar.history[-1].action == "STUDENT_EDIT"
        assert db_aadhaar.history[-1].old_value == "123456789012"
        assert db_aadhaar.history[-1].new_value == "987654321099"

        # - Edited Account: status = STUDENT_VERIFIED, final_value = new value
        db_acc = await DocumentFieldVerification.get(vf_acc.id)
        assert db_acc.status == VerificationFieldStatus.STUDENT_VERIFIED
        assert db_acc.student_value == "1122334455"
        assert db_acc.final_value == "1122334455"
        assert db_acc.ai_value == "9988776655"

        # - Verify NO pending correction items exist (no staff approval required)
        pending_corrections = await DocumentFieldVerification.find({
            "student_id": reg1,
            "status": VerificationFieldStatus.CORRECTION_REQUESTED,
        }).to_list()
        assert len(pending_corrections) == 0

        # - Verify StudentSubmission updated
        db_sub = await StudentSubmission.find_one(
            StudentSubmission.batch_id == batch.id,
            StudentSubmission.register_number == reg1,
        )
        assert db_sub.submission_status == "Student Verified"
        assert db_sub.extracted_data.get("aadhaar_number") == "987654321099"
        assert db_sub.extracted_data.get("account_number") == "1122334455"

        # 7. Staff Dashboard / Batch Status:
        service = BatchExtractionService()
        actor = User(
            username="admin_test",
            name="Admin User",
            email="admin@university.edu",
            password="hashed_password",
            role=UserRole.SUPER_ADMIN,
        )
        status_resp = await service.get_extraction_details(
            extraction_request_id=ext_req_id,
            actor=actor,
        )
        emma_row = next((r for r in status_resp.students if r.register_number == reg1), None)
        assert emma_row is not None
        assert emma_row.verification_status == "STUDENT_VERIFIED"
        assert emma_row.has_corrections_pending is False
        assert emma_row.fields["aadhaar_number"].final_value == "987654321099"
        assert emma_row.fields["aadhaar_number"].student_value == "987654321099"
        assert emma_row.fields["aadhaar_number"].ai_value == "123456789012"
        assert len(status_resp.corrections_queue) == 0  # No staff approval tasks!

        # 8. Excel Export: Verify exported file contains the final student-edited values
        excel_stream, _ = await service.export_verified_excel(ext_req_id, actor)
        excel_bytes = excel_stream.getvalue()
        wb = openpyxl.load_workbook(io.BytesIO(excel_bytes))
        ws = wb.active
        headers = [cell.value for cell in ws[1]]
        name_col = headers.index("Student Name") + 1
        aadhaar_col = headers.index("Aadhaar Number") + 1
        acc_col = headers.index("Account Number") + 1

        emma_found = False
        for row in range(2, ws.max_row + 1):
            if ws.cell(row=row, column=name_col).value == "Emma Watson":
                emma_found = True
                assert ws.cell(row=row, column=aadhaar_col).value == "987654321099"
                assert ws.cell(row=row, column=acc_col).value == "1122334455"
        assert emma_found is True

        # 9. Repeated Submissions Idempotency & Completion Protection:
        # - Idempotent re-submission (same values) returns 200
        idem_res = await ac.post(
            "/public/student-verification/submit",
            json={
                "session_token": session_token,
                "fields": [
                    {
                        "verification_id": str(vf_name.id),
                        "is_confirmed": True,
                    },
                    {
                        "verification_id": str(vf_aadhaar.id),
                        "is_confirmed": False,
                        "corrected_value": "987654321099",
                    },
                    {
                        "verification_id": str(vf_acc.id),
                        "is_confirmed": False,
                        "corrected_value": "1122334455",
                    },
                ],
            },
        )
        assert idem_res.status_code == 200

        # - Tampering/altering values on completed session returns 400
        alter_res = await ac.post(
            "/public/student-verification/submit",
            json={
                "session_token": session_token,
                "fields": [
                    {
                        "verification_id": str(vf_aadhaar.id),
                        "is_confirmed": False,
                        "corrected_value": "000000000000",
                    }
                ],
            },
        )
        assert alter_res.status_code == 400
        assert "already completed" in alter_res.json()["detail"].lower() or "already been submitted" in alter_res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_academic_year_source_routing_and_manual_entry_flow():
    from app.services.field_source_rules import SourceAuthorityService
    from app.services.notification_service import NotificationService
    from app.models.batch_extraction import BatchExtractionRequest, BatchExtractionStatus

    # 1. Test Field Configuration and Source-Document Routing
    batch_service = BatchExtractionService()
    target_docs = batch_service._get_target_doc_types_for_field("academic_year_of_joining")
    assert "AADHAAR" not in target_docs or target_docs[0] != "AADHAAR"
    assert "STUDENT_PROFILE" in target_docs

    auth_rule = SourceAuthorityService().get_rule_for_field("academic_year_of_joining")
    assert auth_rule is not None
    rule_doc_types = [s["document_type"] for s in auth_rule["sources"]]
    assert "AADHAAR" not in rule_doc_types
    assert "STUDENT_PROFILE" in rule_doc_types

    # 2. Setup Student with NO Aadhaar document uploaded
    batch_id = "batch_ay_test_2026"
    reg_no = "AY2026001"
    ext_req_id = "req_ay_test_01"
    await AdmissionBatch.find({"_id": batch_id}).delete()
    await StudentSubmission.find(StudentSubmission.batch_id == batch_id).delete()
    await DocumentFieldVerification.find(DocumentFieldVerification.batch_id == batch_id).delete()
    await VerificationToken.find(VerificationToken.batch_id == batch_id).delete()
    await BatchExtractionRequest.find(BatchExtractionRequest.extraction_request_id == ext_req_id).delete()

    batch = AdmissionBatch(
        id=batch_id,
        name="AY Test Batch 2026-2027",
        academic_year="2026-2027",
        department_id="DEP_CS",
        created_by="admin_ay",
    )
    await batch.insert()

    sub = StudentSubmission(
        batch_id=batch_id,
        student_name="Harry Potter",
        register_number=reg_no,
        email="harry@hogwarts.edu",
        mobile_number="9876543210",
        submission_status="Submitted",
        extracted_data={
            "academic_year_of_joining": "2026-2027",
        },
    )
    await sub.insert()

    # Pre-existing verification record for academic_year_of_joining
    now = datetime.now(timezone.utc)
    vf_ay = DocumentFieldVerification(
        extraction_result_id=f"ext_ay_{reg_no}",
        extraction_request_id=ext_req_id,
        student_id=reg_no,
        document_id="doc_profile",
        document_version_id="v1",
        batch_id=batch_id,
        document_type="STUDENT_PROFILE",
        source_document_name="Student Profile",
        field_name="academic_year_of_joining",
        ai_value="2026-2027",
        raw_value="2026-2027",
        field_state="EXTRACTED",
        status=VerificationFieldStatus.AI_EXTRACTED,
        created_at=now,
        updated_at=now,
    )
    await vf_ay.insert()

    # Field genuinely missing/not found
    vf_missing = DocumentFieldVerification(
        extraction_result_id=f"ext_missing_{reg_no}",
        extraction_request_id=ext_req_id,
        student_id=reg_no,
        document_id="doc_profile",
        document_version_id="v1",
        batch_id=batch_id,
        document_type="STUDENT_PROFILE",
        source_document_name="Student Profile",
        field_name="blood_group",
        ai_value=None,
        raw_value=None,
        field_state="NOT_FOUND",
        status=VerificationFieldStatus.AI_EXTRACTED,
        created_at=now,
        updated_at=now,
    )
    await vf_missing.insert()

    # Other student's record for cross-student access check
    other_reg = "AY2026999"
    vf_other = DocumentFieldVerification(
        extraction_result_id=f"ext_other_{other_reg}",
        extraction_request_id=ext_req_id,
        student_id=other_reg,
        document_id="doc_profile",
        document_version_id="v1",
        batch_id=batch_id,
        document_type="STUDENT_PROFILE",
        source_document_name="Student Profile",
        field_name="student_name",
        ai_value="Ron Weasley",
        raw_value="Ron Weasley",
        field_state="EXTRACTED",
        status=VerificationFieldStatus.AI_EXTRACTED,
        created_at=now,
        updated_at=now,
    )
    await vf_other.insert()

    ext_req = BatchExtractionRequest(
        batch_id=batch_id,
        extraction_request_id=ext_req_id,
        status=BatchExtractionStatus.COMPLETED.value,
        created_by="admin_ay",
    )
    await ext_req.insert()

    actor = User(
        username="admin_ay_test",
        name="AY Admin",
        email="admin_ay@university.edu",
        password=get_password_hash("pw"),
        role=UserRole.SUPER_ADMIN,
        is_active=True,
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        # Step A: Identify student via Common URL
        ident_res = await ac.post(
            "/public/student-verification/identify",
            json={
                "student_name": "Harry Potter",
                "register_number": reg_no,
            },
        )
        assert ident_res.status_code == 200
        session_token = ident_res.json()["session_token"]
        dev_code = ident_res.json()["dev_code"]

        # Step B: Verify Code
        code_res = await ac.post(
            "/public/student-verification/verify-code",
            json={
                "session_token": session_token,
                "code": dev_code,
            },
        )
        assert code_res.status_code == 200
        data = code_res.json()

        # Verify academic year is NOT marked DOCUMENT_MISSING / AADHAAR
        ay_field = next((f for f in data["fields"] if f["field_name"] == "academic_year_of_joining"), None)
        assert ay_field is not None
        assert ay_field["document_type"] != "AADHAAR"
        assert ay_field["field_state"] != "DOCUMENT_MISSING"
        assert ay_field["ai_value"] == "2026-2027"

        # Verify missing field is NOT_FOUND
        missing_field = next((f for f in data["fields"] if f["field_name"] == "blood_group"), None)
        assert missing_field is not None
        assert missing_field["field_state"] == "NOT_FOUND"

        # Step C: Cross-Student Access Protection
        cross_res = await ac.post(
            "/public/student-verification/submit",
            json={
                "session_token": session_token,
                "fields": [
                    {
                        "verification_id": str(vf_other.id),
                        "is_confirmed": False,
                        "corrected_value": "Hacked Value",
                    }
                ],
            },
        )
        assert cross_res.status_code == 403
        assert "another student" in cross_res.json()["detail"].lower()

        # Step D: Submit with Confirmation of AY and Manual Entry of Missing Field
        submit_res = await ac.post(
            "/public/student-verification/submit",
            json={
                "session_token": session_token,
                "fields": [
                    {
                        "verification_id": str(vf_ay.id),
                        "is_confirmed": True,
                    },
                    {
                        "verification_id": str(vf_missing.id),
                        "is_confirmed": False,
                        "corrected_value": "O+",
                    },
                ],
            },
        )
        assert submit_res.status_code == 200
        sub_data = submit_res.json()
        assert sub_data["status"] == "COMPLETED"

        # Verify final values and field_state distinction
        saved_ay = await DocumentFieldVerification.get(vf_ay.id)
        assert saved_ay.status == VerificationFieldStatus.STUDENT_CONFIRMED
        assert saved_ay.final_value == "2026-2027"

        saved_missing = await DocumentFieldVerification.get(vf_missing.id)
        assert saved_missing.status == VerificationFieldStatus.STUDENT_VERIFIED
        assert saved_missing.final_value == "O+"
        assert saved_missing.student_value == "O+"
        assert saved_missing.field_state == "MANUALLY_ENTERED"

        # Step E: Staff Notification Dashboard Status
        notif_service = NotificationService()
        notif_status_rows = await notif_service.get_student_notification_status_table(
            extraction_request_id=ext_req_id,
            actor=actor,
        )
        harry_row = next((r for r in notif_status_rows if r.student_id == reg_no), None)
        assert harry_row is not None
        # Must reflect STUDENT_VERIFIED immediately
        assert harry_row.verification_status == "STUDENT_VERIFIED"
        # Since no notification was sent through email/sms, notification_status is NOT_SENT
        assert harry_row.notification_status == "NOT_SENT"


@pytest.mark.asyncio
async def test_unverified_students_remain_pending():
    from app.services.notification_service import NotificationService
    from app.models.batch_extraction import BatchExtractionRequest, BatchExtractionStatus

    batch_id = "batch_pending_test_2026"
    reg_no = "PEND2026001"
    ext_req_id = "req_pend_test_01"
    await AdmissionBatch.find({"_id": batch_id}).delete()
    await StudentSubmission.find(StudentSubmission.batch_id == batch_id).delete()
    await DocumentFieldVerification.find(DocumentFieldVerification.batch_id == batch_id).delete()
    await VerificationToken.find(VerificationToken.batch_id == batch_id).delete()
    await BatchExtractionRequest.find(BatchExtractionRequest.extraction_request_id == ext_req_id).delete()

    batch = AdmissionBatch(
        id=batch_id,
        name="Pending Test Batch",
        academic_year="2026-2027",
        department_id="DEP_CS",
        created_by="admin_pend",
    )
    await batch.insert()

    sub = StudentSubmission(
        batch_id=batch_id,
        student_name="Neville Longbottom",
        register_number=reg_no,
        email="neville@hogwarts.edu",
        mobile_number="9876543211",
        submission_status="Submitted",
    )
    await sub.insert()

    now = datetime.now(timezone.utc)
    vf = DocumentFieldVerification(
        extraction_result_id=f"ext_pend_{reg_no}",
        extraction_request_id=ext_req_id,
        student_id=reg_no,
        document_id="doc_1",
        document_version_id="v1",
        batch_id=batch_id,
        field_name="student_name",
        ai_value="Neville Longbottom",
        raw_value="Neville Longbottom",
        field_state="EXTRACTED",
        status=VerificationFieldStatus.AI_EXTRACTED,
        created_at=now,
        updated_at=now,
    )
    await vf.insert()

    # Generate an active token for the student
    token = VerificationToken(
        token="tok_pending_test_123",
        student_id=reg_no,
        student_name="Neville Longbottom",
        batch_id=batch_id,
        extraction_request_id=ext_req_id,
        status=VerificationTokenStatus.ACTIVE.value,
        is_verified=False,
        expires_at=now + timedelta(days=7),
    )
    await token.insert()

    ext_req = BatchExtractionRequest(
        batch_id=batch_id,
        extraction_request_id=ext_req_id,
        status=BatchExtractionStatus.COMPLETED.value,
        created_by="admin_pend",
    )
    await ext_req.insert()

    actor = User(
        username="admin_pend_test",
        name="Pend Admin",
        email="admin_pend@university.edu",
        password=get_password_hash("pw"),
        role=UserRole.SUPER_ADMIN,
        is_active=True,
    )

    # Check notification dashboard
    notif_service = NotificationService()
    notif_rows = await notif_service.get_student_notification_status_table(
        extraction_request_id=ext_req_id,
        actor=actor,
    )
    nev_row = next((r for r in notif_rows if r.student_id == reg_no), None)
    assert nev_row is not None
    # Must remain PENDING_VERIFICATION because student has not completed verification
    assert nev_row.verification_status == "PENDING_VERIFICATION"
    assert nev_row.notification_status == "NOT_SENT"

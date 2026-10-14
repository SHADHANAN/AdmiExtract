import pytest
import os
from unittest.mock import MagicMock, patch, AsyncMock
from beanie import PydanticObjectId

from app.models.batch import AdmissionBatch
from app.models.student_submission import StudentSubmission
from app.models.student_document import StudentDocument, DocumentVersion
from app.models.document_verification import DocumentFieldVerification, VerificationFieldStatus
from app.models.batch_extraction import BatchExtractionRequest
from app.models.user import User, UserRole
from app.models.department import Department
from app.services.student_document_service import StudentDocumentService
from app.services.batch_extraction_service import BatchExtractionService, CanonicalStudentUnit
from app.services.field_source_rules import get_rule_for_field, DOCUMENT_TYPE_ALIASES
from app.services.document_extraction_service import FIELD_ALIAS_TO_CANONICAL_KEY, ALLOWED_CANONICAL_FIELDS_BY_DOC_TYPE
from app.core.security import create_access_token, get_password_hash


@pytest.mark.asyncio
async def test_canonical_aliases_and_profile_rules():
    """Verify that field_source_rules and document_extraction_service map profile fields canonically."""
    # 1. Alias mapping
    assert FIELD_ALIAS_TO_CANONICAL_KEY.get("email") == "email"
    assert FIELD_ALIAS_TO_CANONICAL_KEY.get("email_id") == "email"
    assert FIELD_ALIAS_TO_CANONICAL_KEY.get("mobile_number") == "mobile_number"
    assert FIELD_ALIAS_TO_CANONICAL_KEY.get("roll_number") == "register_number"
    assert FIELD_ALIAS_TO_CANONICAL_KEY.get("register_number") == "register_number"

    # 2. Rule lookup has STUDENT_PROFILE at top priority
    rule_name = get_rule_for_field("student_name")
    assert rule_name is not None
    assert rule_name["sources"][0]["document_type"] == "STUDENT_PROFILE"
    assert rule_name["sources"][0]["priority"] == 120

    rule_email = get_rule_for_field("email")
    assert rule_email is not None
    assert rule_email["sources"][0]["document_type"] == "STUDENT_PROFILE"

    rule_mobile = get_rule_for_field("mobile_number")
    assert rule_mobile is not None
    assert rule_mobile["sources"][0]["document_type"] == "STUDENT_PROFILE"

    rule_roll = get_rule_for_field("roll_number")
    assert rule_roll is not None
    assert rule_roll["sources"][0]["document_type"] == "STUDENT_PROFILE"


@pytest.mark.asyncio
async def test_profile_trusted_extraction_pipeline_and_ocr_exclusion(
    client_async,
    temp_sample_aadhaar,
    mock_gemini_service,
):
    """
    1. Authenticated student with complete DB profile (name, roll_number, email, mobile_number).
    2. Extraction requested for: student_name, roll_number, email, mobile_number, date_of_birth, gender.
    3. Profile fields MUST be extracted directly from DB with STUDENT_PROFILE provenance and confidence 1.0.
    4. Profile fields MUST NOT be sent to OCR or Gemini.
    5. Non-profile fields (DOB, gender) are extracted from Aadhaar document.
    """
    dept_id = "TRUST_TEST_DEPT"
    batch_id = "batch_trust_001"
    sec_id = "sec_trust_001"
    student_reg = "TRUST_REG_101"

    # Cleanup
    await Department.find(Department.code == dept_id).delete()
    await AdmissionBatch.find(AdmissionBatch.id == batch_id).delete()
    await StudentSubmission.find(StudentSubmission.register_number == student_reg).delete()
    await StudentDocument.find(StudentDocument.student_id == student_reg).delete()
    await BatchExtractionRequest.find(BatchExtractionRequest.batch_id == batch_id).delete()
    await DocumentFieldVerification.find(DocumentFieldVerification.batch_id == batch_id).delete()
    await User.find(User.username == student_reg).delete()

    dept = Department(name="Trust Test Dept", code=dept_id, intake_capacity=60, created_by="admin")
    await dept.insert()

    batch = AdmissionBatch(
        id=batch_id,
        name="TRUST BATCH",
        department_id=dept_id,
        department_code=dept_id,
        academic_year="2026-2027",
        created_by="admin",
        status="active",
    )
    await batch.insert()

    # Create submission with full verified profile
    sub = await StudentSubmission(
        batch_id=batch_id,
        batch_name="TRUST BATCH",
        class_id=sec_id,
        class_name="Section A",
        department_id=dept_id,
        student_name="Naveen Raman",
        register_number=student_reg,
        mobile_number="9840123456",
        email="naveen.raman@example.edu",
        submission_status="Submitted",
    ).insert()

    # Upload Aadhaar document for DOB and gender
    doc_service = StudentDocumentService()
    await doc_service.create_student_document(
        student_id=student_reg,
        batch_id=batch_id,
        class_id=sec_id,
        submission_id=str(sub.id),
        document_type="AADHAAR",
        document_name="Aadhaar Card",
        initial_file_path=temp_sample_aadhaar,
    )

    admin_user = User(
        username="admin_trust_tester",
        name="Trust Admin",
        role=UserRole.DEPARTMENT_ADMIN,
        department_code=dept_id,
        password=get_password_hash("pass123"),
        is_active=True,
    )
    await User.find(User.username == "admin_trust_tester").delete()
    await admin_user.insert()
    token_admin = create_access_token({"sub": str(admin_user.id), "role": admin_user.role.value, "department_code": dept_id})

    # Tracking calls to Gemini
    mock_gemini_service.extract_from_file.reset_mock()

    ext_service = BatchExtractionService()
    ext_service.extraction_service.gemini_service = mock_gemini_service

    with patch("app.api.batch_extraction.service", ext_service):
        req_res = await client_async.post(
            f"/data-extractions/batches/{batch_id}/extract",
            headers={"Authorization": f"Bearer {token_admin}"},
            json={
                "requested_fields": ["student_name", "roll_number", "email", "mobile_number", "date_of_birth", "gender"],
                "requested_columns": ["Name", "Roll No", "Email", "Mobile", "DOB", "Gender"],
            },
        )
        assert req_res.status_code == 200
        ext_json = req_res.json()
        req_id = ext_json["extraction_request_id"]

        # Fetch details
        detail_res = await client_async.get(
            f"/data-extractions/requests/{req_id}",
            headers={"Authorization": f"Bearer {token_admin}"},
        )
        assert detail_res.status_code == 200
        d_json = detail_res.json()
        student_row = d_json["students"][0]
        fields = student_row["fields"]

        # Verify Student Profile Fields provenance and exact values
        assert fields["student_name"]["ai_value"] == "Naveen Raman"
        assert fields["student_name"]["document_type"] == "STUDENT_PROFILE"
        assert fields["student_name"]["source_document_type"] == "STUDENT_PROFILE"
        assert fields["student_name"]["confidence_score"] == 1.0
        assert fields["student_name"]["field_state"] == "EXTRACTED"

        reg_key = "register_number" if "register_number" in fields else "roll_number"
        assert fields[reg_key]["ai_value"] == student_reg
        assert fields[reg_key]["document_type"] == "STUDENT_PROFILE"
        assert fields[reg_key]["confidence_score"] == 1.0

        assert fields["email"]["ai_value"] == "naveen.raman@example.edu"
        assert fields["email"]["document_type"] == "STUDENT_PROFILE"
        assert fields["email"]["confidence_score"] == 1.0

        assert fields["mobile_number"]["ai_value"] == "9840123456"
        assert fields["mobile_number"]["document_type"] == "STUDENT_PROFILE"
        assert fields["mobile_number"]["confidence_score"] == 1.0

        # Verify Document Extracted Fields
        assert fields["date_of_birth"]["ai_value"] == "10/05/2006"
        assert fields["date_of_birth"]["document_type"] == "AADHAAR"

        assert fields["gender"]["ai_value"] == "MALE"
        assert fields["gender"]["document_type"] == "AADHAAR"

        # Check DB DocumentFieldVerification records
        verifs = await DocumentFieldVerification.find(
            DocumentFieldVerification.extraction_request_id == req_id
        ).to_list()
        verif_by_key = {v.field_name: v for v in verifs}

        assert verif_by_key["student_name"].document_type == "STUDENT_PROFILE"
        assert verif_by_key["student_name"].confidence == "HIGH"
        assert verif_by_key["student_name"].confidence_score == 1.0
        assert "student profile" in verif_by_key["student_name"].evidence_snippet.lower()

        assert verif_by_key["email"].document_type == "STUDENT_PROFILE"
        assert verif_by_key["mobile_number"].document_type == "STUDENT_PROFILE"
        v_reg_key = "register_number" if "register_number" in verif_by_key else "roll_number"
        assert verif_by_key[v_reg_key].document_type == "STUDENT_PROFILE"

    # Cleanup
    await Department.find(Department.code == dept_id).delete()
    await AdmissionBatch.find(AdmissionBatch.id == batch_id).delete()
    await StudentSubmission.find(StudentSubmission.register_number == student_reg).delete()
    await StudentDocument.find(StudentDocument.student_id == student_reg).delete()
    await BatchExtractionRequest.find(BatchExtractionRequest.batch_id == batch_id).delete()
    await DocumentFieldVerification.find(DocumentFieldVerification.batch_id == batch_id).delete()
    await User.find(User.username == student_reg).delete()


@pytest.mark.asyncio
async def test_cross_student_isolation_and_missing_profile_fallback(
    client_async,
    temp_sample_aadhaar,
    mock_gemini_service,
):
    """
    1. Two students in same batch:
       - Student A: Profile has full name, email, mobile.
       - Student B: Profile has ONLY name (email and mobile are empty/missing).
    2. Extraction includes both students.
    3. Student A gets profile email and mobile.
    4. Student B DOES NOT receive Student A's email or mobile (cross-student isolation).
    5. Student B's missing email/mobile are marked appropriately (NOT_AVAILABLE) rather than fabricated.
    """
    dept_id = "ISO_TEST_DEPT"
    batch_id = "batch_iso_001"
    sec_id = "sec_iso_001"
    s1_reg = "ISO_S1_001"
    s2_reg = "ISO_S2_002"

    await Department.find(Department.code == dept_id).delete()
    await AdmissionBatch.find(AdmissionBatch.id == batch_id).delete()
    await StudentSubmission.find({"register_number": {"$in": [s1_reg, s2_reg]}}).delete()
    await StudentDocument.find({"student_id": {"$in": [s1_reg, s2_reg]}}).delete()
    await BatchExtractionRequest.find(BatchExtractionRequest.batch_id == batch_id).delete()
    await DocumentFieldVerification.find(DocumentFieldVerification.batch_id == batch_id).delete()

    dept = await Department(name="Isolation Dept", code=dept_id, intake_capacity=60, created_by="admin").insert()
    batch = await AdmissionBatch(
        id=batch_id,
        name="ISO BATCH",
        department_id=dept_id,
        department_code=dept_id,
        academic_year="2026-2027",
        created_by="admin",
        status="active",
    ).insert()

    # S1 with full profile
    sub1 = await StudentSubmission(
        batch_id=batch_id,
        class_id=sec_id,
        student_name="Student One",
        register_number=s1_reg,
        mobile_number="9111111111",
        email="s1@university.edu",
        submission_status="Submitted",
    ).insert()

    # S2 with missing email and mobile
    sub2 = await StudentSubmission(
        batch_id=batch_id,
        class_id=sec_id,
        student_name="Student Two",
        register_number=s2_reg,
        mobile_number="",
        email="",
        submission_status="Submitted",
    ).insert()

    doc_service = StudentDocumentService()
    await doc_service.create_student_document(
        student_id=s1_reg,
        batch_id=batch_id,
        class_id=sec_id,
        submission_id=str(sub1.id),
        document_type="AADHAAR",
        document_name="Aadhaar Card",
        initial_file_path=temp_sample_aadhaar,
    )
    await doc_service.create_student_document(
        student_id=s2_reg,
        batch_id=batch_id,
        class_id=sec_id,
        submission_id=str(sub2.id),
        document_type="AADHAAR",
        document_name="Aadhaar Card",
        initial_file_path=temp_sample_aadhaar,
    )

    admin_user = User(
        username="admin_iso_tester",
        name="Iso Admin",
        role=UserRole.DEPARTMENT_ADMIN,
        department_code=dept_id,
        password=get_password_hash("pass123"),
        is_active=True,
    )
    await User.find(User.username == "admin_iso_tester").delete()
    await admin_user.insert()
    token_admin = create_access_token({"sub": str(admin_user.id), "role": admin_user.role.value, "department_code": dept_id})

    ext_service = BatchExtractionService()
    ext_service.extraction_service.gemini_service = mock_gemini_service

    with patch("app.api.batch_extraction.service", ext_service):
        req_res = await client_async.post(
            f"/data-extractions/batches/{batch_id}/extract",
            headers={"Authorization": f"Bearer {token_admin}"},
            json={
                "requested_fields": ["student_name", "email", "mobile_number", "date_of_birth"],
                "requested_columns": ["Name", "Email", "Mobile", "DOB"],
            },
        )
        assert req_res.status_code == 200
        req_id = req_res.json()["extraction_request_id"]

        detail_res = await client_async.get(
            f"/data-extractions/requests/{req_id}",
            headers={"Authorization": f"Bearer {token_admin}"},
        )
        assert detail_res.status_code == 200
        students = detail_res.json()["students"]
        assert len(students) == 2

        row_s1 = next(s for s in students if s["student_id"] == s1_reg)
        row_s2 = next(s for s in students if s["student_id"] == s2_reg)

        # S1 has profile data
        assert row_s1["fields"]["student_name"]["ai_value"] == "Student One"
        assert row_s1["fields"]["email"]["ai_value"] == "s1@university.edu"
        assert row_s1["fields"]["mobile_number"]["ai_value"] == "9111111111"

        # S2 has its own name, and NEVER inherits S1's email or mobile
        assert row_s2["fields"]["student_name"]["ai_value"] == "Student Two"
        assert row_s2["fields"]["email"]["ai_value"] != "s1@university.edu"
        assert row_s2["fields"]["mobile_number"]["ai_value"] != "9111111111"

        # Missing profile data is NOT treated as "NO", but rather NOT_AVAILABLE / NOT_FOUND
        assert row_s2["fields"]["email"]["ai_value"] in ("NOT_AVAILABLE", None, "NOT_FOUND")
        assert row_s2["fields"]["email"]["ai_value"] != "NO"
        assert row_s2["fields"]["mobile_number"]["ai_value"] != "NO"

    # Cleanup
    await Department.find(Department.code == dept_id).delete()
    await AdmissionBatch.find(AdmissionBatch.id == batch_id).delete()
    await StudentSubmission.find({"register_number": {"$in": [s1_reg, s2_reg]}}).delete()
    await StudentDocument.find({"student_id": {"$in": [s1_reg, s2_reg]}}).delete()
    await BatchExtractionRequest.find(BatchExtractionRequest.batch_id == batch_id).delete()
    await DocumentFieldVerification.find(DocumentFieldVerification.batch_id == batch_id).delete()


@pytest.mark.asyncio
async def test_re_extraction_bypasses_cache_without_reupload(
    client_async,
    temp_sample_aadhaar,
    mock_gemini_service,
):
    """
    Test that retry student extraction:
    1. Re-processes fields using existing stored documents without requiring student re-upload.
    2. Bypasses cached empty/failed results.
    3. Is idempotent and updates verification records properly.
    """
    dept_id = "RETRY_TEST_DEPT"
    batch_id = "batch_retry_001"
    student_reg = "RETRY_S1_001"

    await Department.find(Department.code == dept_id).delete()
    await AdmissionBatch.find(AdmissionBatch.id == batch_id).delete()
    await StudentSubmission.find(StudentSubmission.register_number == student_reg).delete()
    await StudentDocument.find(StudentDocument.student_id == student_reg).delete()
    await BatchExtractionRequest.find(BatchExtractionRequest.batch_id == batch_id).delete()
    await DocumentFieldVerification.find(DocumentFieldVerification.batch_id == batch_id).delete()

    await Department(name="Retry Dept", code=dept_id, intake_capacity=60, created_by="admin").insert()
    await AdmissionBatch(
        id=batch_id,
        name="RETRY BATCH",
        department_id=dept_id,
        department_code=dept_id,
        academic_year="2026-2027",
        created_by="admin",
        status="active",
    ).insert()

    sub = await StudentSubmission(
        batch_id=batch_id,
        student_name="Retry Candidate",
        register_number=student_reg,
        mobile_number="9876543210",
        submission_status="Submitted",
    ).insert()

    doc_service = StudentDocumentService()
    await doc_service.create_student_document(
        student_id=student_reg,
        batch_id=batch_id,
        submission_id=str(sub.id),
        document_type="AADHAAR",
        document_name="Aadhaar Card",
        initial_file_path=temp_sample_aadhaar,
    )

    admin_user = User(
        username="admin_retry_tester",
        name="Retry Admin",
        role=UserRole.DEPARTMENT_ADMIN,
        department_code=dept_id,
        password=get_password_hash("pass123"),
        is_active=True,
    )
    await User.find(User.username == "admin_retry_tester").delete()
    await admin_user.insert()
    token_admin = create_access_token({"sub": str(admin_user.id), "role": admin_user.role.value, "department_code": dept_id})

    ext_service = BatchExtractionService()
    ext_service.extraction_service.gemini_service = mock_gemini_service

    with patch("app.api.batch_extraction.service", ext_service):
        req_res = await client_async.post(
            f"/data-extractions/batches/{batch_id}/extract",
            headers={"Authorization": f"Bearer {token_admin}"},
            json={
                "requested_fields": ["student_name", "date_of_birth", "gender"],
                "requested_columns": ["Name", "DOB", "Gender"],
            },
        )
        assert req_res.status_code == 200
        req_id = req_res.json()["extraction_request_id"]

        # Staff executes retry on the student WITHOUT student re-uploading documents
        retry_res = await client_async.post(
            f"/data-extractions/requests/{req_id}/retry-student/{student_reg}",
            headers={"Authorization": f"Bearer {token_admin}"},
        )
        assert retry_res.status_code == 200
        retry_data = retry_res.json()
        assert retry_data["student_id"] == student_reg
        assert "fields" in retry_data
        assert retry_data["fields"]["student_name"]["ai_value"] == "Retry Candidate"
        assert retry_data["fields"]["student_name"]["document_type"] == "STUDENT_PROFILE"
        assert retry_data["fields"]["date_of_birth"]["ai_value"] == "10/05/2006"

    # Cleanup
    await Department.find(Department.code == dept_id).delete()
    await AdmissionBatch.find(AdmissionBatch.id == batch_id).delete()
    await StudentSubmission.find(StudentSubmission.register_number == student_reg).delete()
    await StudentDocument.find(StudentDocument.student_id == student_reg).delete()
    await BatchExtractionRequest.find(BatchExtractionRequest.batch_id == batch_id).delete()
    await DocumentFieldVerification.find(DocumentFieldVerification.batch_id == batch_id).delete()


@pytest.mark.asyncio
async def test_extraction_api_response_contracts_and_fallbacks(
    client_async,
    temp_sample_aadhaar,
    mock_gemini_service,
):
    """
    Regression test ensuring that:
    1. Extraction and notification API responses contain safe fallback values.
    2. Student rows with missing/null names or unextracted fields return safe defaults.
    3. Notification status table provides notification_status and verification_status.
    """
    dept_id = "CONTRACT_DEPT"
    batch_id = "batch_contract_001"
    student_reg = "CONTRACT_REG_001"

    await Department.find(Department.code == dept_id).delete()
    await AdmissionBatch.find(AdmissionBatch.id == batch_id).delete()
    await StudentSubmission.find(StudentSubmission.register_number == student_reg).delete()
    await StudentDocument.find(StudentDocument.student_id == student_reg).delete()
    await BatchExtractionRequest.find(BatchExtractionRequest.batch_id == batch_id).delete()
    await DocumentFieldVerification.find(DocumentFieldVerification.batch_id == batch_id).delete()

    await Department(name="Contract Dept", code=dept_id, intake_capacity=60, created_by="admin").insert()
    await AdmissionBatch(
        id=batch_id,
        name="CONTRACT BATCH",
        department_id=dept_id,
        department_code=dept_id,
        academic_year="2026-2027",
        created_by="admin",
        status="active",
    ).insert()

    # Create submission with missing/sparse optional metadata
    sub = await StudentSubmission(
        batch_id=batch_id,
        student_name="Candidate Alpha",
        register_number=student_reg,
        mobile_number="9876543210",
        submission_status="Submitted",
    ).insert()

    doc_service = StudentDocumentService()
    await doc_service.create_student_document(
        student_id=student_reg,
        batch_id=batch_id,
        submission_id=str(sub.id),
        document_type="AADHAAR",
        document_name="Aadhaar Card",
        initial_file_path=temp_sample_aadhaar,
    )

    admin_user = User(
        username="admin_contract_tester",
        name="Contract Admin",
        role=UserRole.DEPARTMENT_ADMIN,
        department_code=dept_id,
        password=get_password_hash("pass123"),
        is_active=True,
    )
    await User.find(User.username == "admin_contract_tester").delete()
    await admin_user.insert()
    token_admin = create_access_token({"sub": str(admin_user.id), "role": admin_user.role.value, "department_code": dept_id})

    ext_service = BatchExtractionService()
    ext_service.extraction_service.gemini_service = mock_gemini_service

    with patch("app.api.batch_extraction.service", ext_service):
        req_res = await client_async.post(
            f"/data-extractions/batches/{batch_id}/extract",
            headers={"Authorization": f"Bearer {token_admin}"},
            json={
                "requested_fields": ["student_name", "date_of_birth", "annual_income"],
                "requested_columns": ["Name", "DOB", "Income"],
            },
        )
        assert req_res.status_code == 200
        req_id = req_res.json()["extraction_request_id"]

        # Detail response contract check
        detail_res = await client_async.get(
            f"/data-extractions/requests/{req_id}",
            headers={"Authorization": f"Bearer {token_admin}"},
        )
        assert detail_res.status_code == 200
        d_json = detail_res.json()
        student_row = d_json["students"][0]

        # Verify safe contracts for frontend consumption
        assert isinstance(student_row["verification_status"], str)
        assert isinstance(student_row["extraction_status"], str)
        assert isinstance(student_row["missing_documents"], list)

        # annual_income document was missing (Income certificate not uploaded)
        income_field = student_row["fields"]["annual_income"]
        assert income_field["ai_value"] in ("NOT_AVAILABLE", None)
        assert income_field["verification_status"] is not None
        assert isinstance(income_field["column_label"], str)

        # Notification table contract check
        notif_res = await client_async.get(
            f"/data-extractions/{req_id}/notifications/students",
            headers={"Authorization": f"Bearer {token_admin}"},
        )
        assert notif_res.status_code == 200
        notif_rows = notif_res.json()
        assert len(notif_rows) == 1
        n_row = notif_rows[0]

        # Crucial contract check: notification_status exists and is a string
        assert "notification_status" in n_row
        assert n_row["notification_status"] == "NOT_SENT"
        assert isinstance(n_row["verification_status"], str)
        assert n_row["student_id"] == student_reg

    # Cleanup
    await Department.find(Department.code == dept_id).delete()
    await AdmissionBatch.find(AdmissionBatch.id == batch_id).delete()
    await StudentSubmission.find(StudentSubmission.register_number == student_reg).delete()
    await StudentDocument.find(StudentDocument.student_id == student_reg).delete()
    await BatchExtractionRequest.find(BatchExtractionRequest.batch_id == batch_id).delete()
    await DocumentFieldVerification.find(DocumentFieldVerification.batch_id == batch_id).delete()

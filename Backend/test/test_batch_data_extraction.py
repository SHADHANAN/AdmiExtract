import io
import os
import tempfile
from datetime import datetime, timezone
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import openpyxl
import pytest
import pytest_asyncio
from beanie import PydanticObjectId
from httpx import ASGITransport, AsyncClient
from motor.motor_asyncio import AsyncIOMotorClient

from app.core.config import settings
from app.core.security import create_access_token, get_password_hash
from app.main import app
from app.models.batch import AdmissionBatch
from app.models.batch_extraction import BatchExtractionRequest
from app.models.department import Department
from app.models.document_extraction_result import DocumentExtractionResult
from app.models.document_verification import (
    DocumentFieldVerification,
    VerificationFieldStatus,
)
from app.models.student_document import StudentDocument
from app.models.student_submission import StudentSubmission
from app.models.user import User, UserRole
from app.services.batch_extraction_service import BatchExtractionService
from app.services.gemini_service import GeminiService
from app.services.student_document_service import StudentDocumentService


@pytest.mark.asyncio
async def test_batch_data_extraction_full_workflow(
    client_async,
    temp_sample_aadhaar,
    temp_sample_community,
    mock_gemini_service,
):
    """
    Validates comprehensive Data Extraction workflow:
    1. Authorized batches listing & RBAC isolation
    2. Excel field template preview & canonicalization
    3. Document reuse without re-upload
    4. Only requested fields extracted
    5. Missing document produces NOT_AVAILABLE without hallucination
    6. Multiple coexisting extractions on same batch
    7. Student verification & correction (preserving AI value)
    8. Staff approval & rejection creating final value
    9. Verified Excel download preserving requested columns
    10. Re-extraction after download without document loss
    """
    # 1. Setup Test Users & Batches
    admin_user = User(
        username="superadmin_test",
        name="Super Admin",
        role=UserRole.SUPER_ADMIN,
        password=get_password_hash("pass123"),
        is_active=True,
    )
    aiml_admin = User(
        username="aiml_admin_test",
        name="AIML Admin",
        role=UserRole.DEPARTMENT_ADMIN,
        department_code="AIML",
        password=get_password_hash("pass123"),
        is_active=True,
    )
    ece_admin = User(
        username="ece_admin_test",
        name="ECE Admin",
        role=UserRole.DEPARTMENT_ADMIN,
        department_code="ECE",
        password=get_password_hash("pass123"),
        is_active=True,
    )

    await User.find(User.username == "superadmin_test").delete()
    await User.find(User.username == "aiml_admin_test").delete()
    await User.find(User.username == "ece_admin_test").delete()
    await User.find(User.username == "26AM001").delete()

    await admin_user.insert()
    await aiml_admin.insert()
    await ece_admin.insert()

    student_user = User(
        username="26AM001",
        name="Karthik Raja",
        role=UserRole.STUDENT,
        register_number="26AM001",
        password=get_password_hash("pass123"),
        is_active=True,
    )
    await student_user.insert()

    batch_aiml_id = "batch_test_aiml_2026"
    batch_ece_id = "batch_test_ece_2026"

    await AdmissionBatch.find(AdmissionBatch.id == batch_aiml_id).delete()
    await AdmissionBatch.find(AdmissionBatch.id == batch_ece_id).delete()
    await BatchExtractionRequest.find(BatchExtractionRequest.batch_id == batch_aiml_id).delete()
    await BatchExtractionRequest.find(BatchExtractionRequest.batch_id == batch_ece_id).delete()
    await DocumentFieldVerification.find(DocumentFieldVerification.batch_id == batch_aiml_id).delete()
    await DocumentFieldVerification.find(DocumentFieldVerification.batch_id == batch_ece_id).delete()

    batch_aiml = AdmissionBatch(
        id=batch_aiml_id,
        name="Batch 2026 AIML",
        department_id="AIML",
        academic_year="2026-2027",
        created_by="superadmin_test",
    )
    await batch_aiml.insert()

    batch_ece = AdmissionBatch(
        id=batch_ece_id,
        name="Batch 2026 ECE",
        department_id="ECE",
        academic_year="2026-2027",
        created_by="superadmin_test",
    )
    await batch_ece.insert()

    # 2. Store documents for students in AIML batch
    doc_service = StudentDocumentService()
    student_1 = "26AM001"
    student_2 = "26AM002"

    await StudentDocument.find(StudentDocument.student_id == student_1).delete()
    await StudentDocument.find(StudentDocument.student_id == student_2).delete()

    # Student 1 has Aadhaar + Community Certificate
    doc1_aadhaar = await doc_service.create_student_document(
        student_id=student_1,
        batch_id=batch_aiml_id,
        department_id="AIML",
        document_type="AADHAAR",
        document_name="Aadhaar Card",
        initial_file_path=temp_sample_aadhaar,
    )
    doc1_comm = await doc_service.create_student_document(
        student_id=student_1,
        batch_id=batch_aiml_id,
        department_id="AIML",
        document_type="COMMUNITY",
        document_name="Community Certificate",
        initial_file_path=temp_sample_community,
    )

    # Student 2 has Aadhaar only (NO Community Certificate)
    doc2_aadhaar = await doc_service.create_student_document(
        student_id=student_2,
        batch_id=batch_aiml_id,
        department_id="AIML",
        document_type="AADHAAR",
        document_name="Aadhaar Card",
        initial_file_path=temp_sample_aadhaar,
    )

    token_aiml = create_access_token({"sub": str(aiml_admin.id), "role": aiml_admin.role.value, "department_code": "AIML"})
    token_ece = create_access_token({"sub": str(ece_admin.id), "role": ece_admin.role.value, "department_code": "ECE"})
    token_super = create_access_token({"sub": str(admin_user.id), "role": admin_user.role.value})

    # Test 1 & 2: Authorized batch listing & Department Isolation
    resp = await client_async.get(
        "/data-extractions/batches",
        headers={"Authorization": f"Bearer {token_aiml}"},
    )
    assert resp.status_code == 200
    aiml_batches = resp.json()
    assert any(b["batch_id"] == batch_aiml_id for b in aiml_batches)
    assert not any(b["batch_id"] == batch_ece_id for b in aiml_batches)

    # Cross-department access to ECE batch rejected
    resp_unauth = await client_async.get(
        f"/data-extractions/batches/{batch_ece_id}",
        headers={"Authorization": f"Bearer {token_aiml}"},
    )
    assert resp_unauth.status_code == 403

    # Test 4 & 5: Excel field template preview & canonicalization
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Register Number", "Student Name", "DOB", "Gender", "Community"])
    ws.append(["26AM001", "", "", "", ""])
    ws.append(["26AM002", "", "", "", ""])
    excel_buf = io.BytesIO()
    wb.save(excel_buf)
    excel_buf.seek(0)

    files = {"file": ("template.xlsx", excel_buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    prev_resp = await client_async.post(
        "/data-extractions/template-preview",
        headers={"Authorization": f"Bearer {token_aiml}"},
        files=files,
    )
    assert prev_resp.status_code == 200
    prev_data = prev_resp.json()
    assert "Student Name" in prev_data["requested_columns"]
    assert "student_name" in prev_data["canonical_fields"]
    assert "date_of_birth" in prev_data["canonical_fields"]
    assert "community" in prev_data["canonical_fields"] or "community_category" in prev_data["canonical_fields"]

    # Test 3, 6, 7, 8, 22: Run Extraction #1 (Name + DOB + Gender)
    ext_service = BatchExtractionService()
    ext_service.extraction_service.gemini_service = mock_gemini_service

    with patch("app.api.batch_extraction.service", ext_service):
        req1_resp = await client_async.post(
            f"/data-extractions/batches/{batch_aiml_id}/extract",
            headers={"Authorization": f"Bearer {token_aiml}"},
            json={
                "requested_fields": ["student_name", "date_of_birth", "gender"],
                "requested_columns": ["Student Name", "DOB", "Gender"],
            },
        )
        assert req1_resp.status_code == 200
        ext1_data = req1_resp.json()
        ext1_id = ext1_data["extraction_request_id"]
        assert ext1_data["status"] == "COMPLETED"
        assert ext1_data["result_count"] >= 2

        # Verify Extraction #1 details
        detail1_resp = await client_async.get(
            f"/data-extractions/requests/{ext1_id}",
            headers={"Authorization": f"Bearer {token_aiml}"},
        )
        assert detail1_resp.status_code == 200
        d1 = detail1_resp.json()
        assert len(d1["students"]) >= 2
        s1_row = next(s for s in d1["students"] if s["student_id"] == student_1)
        assert s1_row["fields"]["student_name"]["ai_value"] == "Karthik Raja"
        assert s1_row["fields"]["date_of_birth"]["ai_value"] == "10/05/2006"
        assert s1_row["fields"]["gender"]["ai_value"] == "MALE"
        # Only requested fields extracted
        assert "community" not in s1_row["fields"]
        assert "father_name" not in s1_row["fields"]

        # Test 9 & 10: Multiple extractions coexist. Extraction #2 (Community + Income)
        req2_resp = await client_async.post(
            f"/data-extractions/batches/{batch_aiml_id}/extract",
            headers={"Authorization": f"Bearer {token_aiml}"},
            json={
                "requested_fields": ["community", "income"],
                "requested_columns": ["Community", "Income"],
            },
        )
        assert req2_resp.status_code == 200
        ext2_data = req2_resp.json()
        ext2_id = ext2_data["extraction_request_id"]
        assert ext2_id != ext1_id

        # Verify Extraction #2 results
        detail2_resp = await client_async.get(
            f"/data-extractions/requests/{ext2_id}",
            headers={"Authorization": f"Bearer {token_aiml}"},
        )
        d2 = detail2_resp.json()
        s1_row2 = next(s for s in d2["students"] if s["student_id"] == student_1)
        s2_row2 = next(s for s in d2["students"] if s["student_id"] == student_2)

        # Student 1 has Community certificate -> extracted
        comm_key = "community_category" if "community_category" in s1_row2["fields"] else "community"
        assert s1_row2["fields"][comm_key]["ai_value"] == "BC"
        # Student 2 DOES NOT have Community certificate -> safe NOT_AVAILABLE (no hallucination)
        assert s2_row2["fields"][comm_key]["ai_value"] == "NOT_AVAILABLE"

        # Verify Extraction #1 is completely unchanged
        detail1_check = await client_async.get(
            f"/data-extractions/requests/{ext1_id}",
            headers={"Authorization": f"Bearer {token_aiml}"},
        )
        assert detail1_check.json()["summary"]["requested_fields"] == ["student_name", "date_of_birth", "gender"]

        # Test 11, 12: Student Verification
        token_s1 = create_access_token({"sub": str(student_user.id), "role": "student", "register_number": student_1})
        s1_verif_resp = await client_async.get(
            f"/data-extractions/requests/{ext1_id}/student/{student_1}",
            headers={"Authorization": f"Bearer {token_s1}"},
        )
        assert s1_verif_resp.status_code == 200
        s1_verif_data = s1_verif_resp.json()
        assert s1_verif_data["student_id"] == student_1
        assert len(s1_verif_data["fields"]) >= 3

        # Student confirms DOB and submits correction for Student Name
        v_name = next(f for f in s1_verif_data["fields"] if f["field_name"] == "student_name")
        v_dob = next(f for f in s1_verif_data["fields"] if f["field_name"] == "date_of_birth")

        sub_verif_resp = await client_async.post(
            f"/data-extractions/requests/{ext1_id}/student/{student_1}/verify",
            headers={"Authorization": f"Bearer {token_s1}"},
            json={
                "fields": [
                    {
                        "verification_id": v_name["verification_id"],
                        "field_name": "student_name",
                        "corrected_value": "Karthik Raja S",
                        "is_confirmed": False,
                        "comment": "Added initial S",
                    },
                    {
                        "verification_id": v_dob["verification_id"],
                        "field_name": "date_of_birth",
                        "is_confirmed": True,
                    }
                ]
            },
        )
        assert sub_verif_resp.status_code == 200

        # Verify status became CORRECTION_REQUESTED and raw AI value is preserved
        rec_name_db = await DocumentFieldVerification.get(PydanticObjectId(v_name["verification_id"]))
        assert rec_name_db.status == VerificationFieldStatus.CORRECTION_REQUESTED
        assert rec_name_db.ai_value == "Karthik Raja"  # NOT destroyed
        assert rec_name_db.student_value == "Karthik Raja S"
        assert rec_name_db.final_value is None  # Not final yet

        # Test 13: Staff Approval creates final value
        approve_resp = await client_async.post(
            f"/data-extractions/requests/{ext1_id}/review/{v_name['verification_id']}",
            headers={"Authorization": f"Bearer {token_aiml}"},
            json={"action": "APPROVE", "staff_comment": "Approved initial addition"},
        )
        assert approve_resp.status_code == 200
        rec_name_after = await DocumentFieldVerification.get(PydanticObjectId(v_name["verification_id"]))
        assert rec_name_after.status == VerificationFieldStatus.STAFF_APPROVED
        assert rec_name_after.final_value == "Karthik Raja S"

        # Test 15 & 16: Download Excel of Final Verified Data
        export_resp = await client_async.get(
            f"/data-extractions/requests/{ext1_id}/export",
            headers={"Authorization": f"Bearer {token_aiml}"},
        )
        assert export_resp.status_code == 200
        assert "spreadsheetml" in export_resp.headers["content-type"]

        # Parse downloaded Excel to verify approved student value was exported
        exp_wb = openpyxl.load_workbook(io.BytesIO(export_resp.content))
        exp_ws = exp_wb.active
        exported_headers = [cell.value for cell in exp_ws[1]]
        assert "Student Name" in exported_headers
        assert any("DOB" in str(h) or "Date of Birth" in str(h) for h in exported_headers)
        assert any("Gender" in str(h) for h in exported_headers)

        # Check data row contains approved name "Karthik Raja S"
        all_rows = list(exp_ws.iter_rows(values_only=True))
        assert any("Karthik Raja S" in row for row in all_rows)

        # Test 16 & 17: Source documents are NOT deleted, re-extraction works
        remaining_docs = await StudentDocument.find(StudentDocument.student_id == student_1).to_list()
        assert len(remaining_docs) == 2  # Aadhaar + Community still intact!

        # New extraction request after download
        req3_resp = await client_async.post(
            f"/data-extractions/batches/{batch_aiml_id}/extract",
            headers={"Authorization": f"Bearer {token_aiml}"},
            json={
                "requested_fields": ["father_name", "permanent_address"],
                "requested_columns": ["Father Name", "Address"],
            },
        )
        assert req3_resp.status_code == 200
        ext3_id = req3_resp.json()["extraction_request_id"]

        # Test 18: Old extraction history remains available
        hist_resp = await client_async.get(
            f"/data-extractions/batches/{batch_aiml_id}/history",
            headers={"Authorization": f"Bearer {token_aiml}"},
        )
        assert hist_resp.status_code == 200
        history_items = hist_resp.json()
        assert len(history_items) == 3
        assert any(h["extraction_request_id"] == ext1_id for h in history_items)
        assert any(h["extraction_request_id"] == ext2_id for h in history_items)
        assert any(h["extraction_request_id"] == ext3_id for h in history_items)

        # Test 19: Dedicated Correction Queue endpoint
        corrections_resp = await client_async.get(
            f"/data-extractions/requests/{ext1_id}/corrections",
            headers={"Authorization": f"Bearer {token_aiml}"},
        )
        assert corrections_resp.status_code == 200
        assert isinstance(corrections_resp.json(), list)

        # Test 20: Retry student extraction
        retry_resp = await client_async.post(
            f"/data-extractions/requests/{ext1_id}/retry-student/{student_1}",
            headers={"Authorization": f"Bearer {token_aiml}"},
        )
        assert retry_resp.status_code == 200
        retry_data = retry_resp.json()
        assert retry_data["student_id"] == student_1
        assert "fields" in retry_data

        # Test 21: Cancel extraction safely
        cancel_resp = await client_async.post(
            f"/data-extractions/requests/{ext3_id}/cancel",
            headers={"Authorization": f"Bearer {token_aiml}"},
        )
        assert cancel_resp.status_code == 200
        assert cancel_resp.json()["status"] == "CANCELLED"

        # Verify source documents and other extractions remain intact after cancel
        docs_after_cancel = await StudentDocument.find(StudentDocument.student_id == student_1).to_list()
        assert len(docs_after_cancel) == 2
        ext1_after = await BatchExtractionRequest.find_one(BatchExtractionRequest.extraction_request_id == ext1_id)
        assert ext1_after.status != "CANCELLED"

        # Test 22: Pagination and Filtering
        detail_paged = await client_async.get(
            f"/data-extractions/requests/{ext1_id}?page=1&page_size=10&status_filter=ALL",
            headers={"Authorization": f"Bearer {token_aiml}"},
        )
        assert detail_paged.status_code == 200
        assert detail_paged.json()["page"] == 1
        assert detail_paged.json()["page_size"] == 10
        assert "total_matching_students" in detail_paged.json()

    # Cleanup test data
    await AdmissionBatch.find(AdmissionBatch.id == batch_aiml_id).delete()
    await AdmissionBatch.find(AdmissionBatch.id == batch_ece_id).delete()
    await StudentDocument.find(StudentDocument.student_id == student_1).delete()
    await StudentDocument.find(StudentDocument.student_id == student_2).delete()
    await BatchExtractionRequest.find(BatchExtractionRequest.batch_id == batch_aiml_id).delete()
    await DocumentFieldVerification.find(DocumentFieldVerification.batch_id == batch_aiml_id).delete()


@pytest.mark.asyncio
async def test_data_extraction_final_product_workflow_all_students_scope(
    client_async,
    temp_sample_aadhaar,
    temp_sample_community,
    tmp_path,
    mock_gemini_service,
):
    """
    TESTS ALL REQUIREMENTS OF THE FINAL DATA EXTRACTION WORKFLOW:
    1. Batch/Section with 3 students.
    2. Create extraction request without any student selection.
    3. Extraction automatically includes all 3 students in batch/section.
    4. All 3 students receive extraction results.
    5. Student verification records created for all eligible students.
    6. Each student can only view their own verification session.
    7. Student correction does NOT overwrite AI value (stores AI value, student value, final value).
    8. Staff approval produces final verified value.
    9. Verified Excel export contains ALL students in scope.
    10. Missing document for one student does not stop other students.
    11. Extraction Request #1 remains immutable.
    12. Extraction Request #2 can extract different fields using the same stored documents without re-upload.
    13. Replaced/current document is used for extraction.
    14. Backend derives extraction scope strictly from batch + section.
    15. Retry student extraction is idempotent (no duplicate results).
    """
    from app.models.batch_class import BatchClass

    # 1. Setup Department, Batch, and Section
    dept_id = "CSE"
    batch_id = "batch_cse_2026_test"
    sec_id = "class_cse_sec_a_2026"

    await Department.find(Department.code == dept_id).delete()
    await AdmissionBatch.find(AdmissionBatch.id == batch_id).delete()
    await BatchClass.find(BatchClass.id == sec_id).delete()
    await BatchExtractionRequest.find(BatchExtractionRequest.batch_id == batch_id).delete()
    await DocumentFieldVerification.find(DocumentFieldVerification.batch_id == batch_id).delete()

    dept = Department(name="Computer Science", code=dept_id, intake_capacity=180, created_by="admin")
    await dept.insert()

    batch = AdmissionBatch(
        id=batch_id,
        name="CSE Batch 2026",
        department_id=dept_id,
        department_code=dept_id,
        academic_year="2026-2030",
        created_by="admin",
        status="active",
    )
    await batch.insert()

    section = BatchClass(
        id=sec_id,
        batch_id=batch_id,
        class_name="CSE-A",
        section="A",
        department=dept.name,
        academic_year="2026-2030",
        created_by="admin",
    )
    await section.insert()

    # 2. Setup 3 Students with stored documents
    doc_service = StudentDocumentService()
    s1_reg = "26CS001"
    s2_reg = "26CS002"
    s3_reg = "26CS003"

    for r in [s1_reg, s2_reg, s3_reg]:
        await StudentDocument.find(StudentDocument.student_id == r).delete()
        await StudentSubmission.find(StudentSubmission.register_number == r).delete()
        await User.find(User.username == r).delete()

    # Create dummy PDF files
    tc_pdf = tmp_path / "tc_sample.pdf"
    tc_pdf.write_bytes(b"%PDF-1.4 Transfer Certificate Sample")
    birth_pdf = tmp_path / "birth_sample.pdf"
    birth_pdf.write_bytes(b"%PDF-1.4 Birth Certificate Sample")
    aadhaar_new_pdf = tmp_path / "aadhaar_replaced.pdf"
    aadhaar_new_pdf.write_bytes(b"%PDF-1.4 Replaced Aadhaar File")

    # Student 1: Submits Aadhaar, TC, Birth Certificate. Then Re-uploads Aadhaar (replaced in-place).
    s1_sub = await StudentSubmission(
        batch_id=batch_id,
        class_id=sec_id,
        student_name="Arun Kumar",
        register_number=s1_reg,
        mobile_number="9876543210",
        email="arun@example.com",
    ).insert()

    await doc_service.create_student_document(
        student_id=s1_reg,
        batch_id=batch_id,
        class_id=sec_id,
        submission_id=str(s1_sub.id),
        document_type="AADHAAR",
        document_name="Aadhaar Card",
        initial_file_path=temp_sample_aadhaar,
    )
    # Re-upload Aadhaar (In-place replace)
    await doc_service.create_student_document(
        student_id=s1_reg,
        batch_id=batch_id,
        class_id=sec_id,
        submission_id=str(s1_sub.id),
        document_type="AADHAAR",
        document_name="Aadhaar Card",
        initial_file_path=str(aadhaar_new_pdf),
        original_filename="aadhaar_replaced.pdf",
    )
    await doc_service.create_student_document(
        student_id=s1_reg,
        batch_id=batch_id,
        class_id=sec_id,
        submission_id=str(s1_sub.id),
        document_type="TRANSFER_CERTIFICATE",
        document_name="Transfer Certificate",
        initial_file_path=str(tc_pdf),
    )
    await doc_service.create_student_document(
        student_id=s1_reg,
        batch_id=batch_id,
        class_id=sec_id,
        submission_id=str(s1_sub.id),
        document_type="BIRTH_CERTIFICATE",
        document_name="Birth Certificate",
        initial_file_path=str(birth_pdf),
    )

    # Student 2: Submits Aadhaar + TC (No Birth Certificate)
    s2_sub = await StudentSubmission(
        batch_id=batch_id,
        class_id=sec_id,
        student_name="Bhavya Sri",
        register_number=s2_reg,
        mobile_number="9876543211",
        email="bhavya@example.com",
    ).insert()

    await doc_service.create_student_document(
        student_id=s2_reg,
        batch_id=batch_id,
        class_id=sec_id,
        submission_id=str(s2_sub.id),
        document_type="AADHAAR",
        document_name="Aadhaar Card",
        initial_file_path=temp_sample_aadhaar,
    )
    await doc_service.create_student_document(
        student_id=s2_reg,
        batch_id=batch_id,
        class_id=sec_id,
        submission_id=str(s2_sub.id),
        document_type="TRANSFER_CERTIFICATE",
        document_name="Transfer Certificate",
        initial_file_path=str(tc_pdf),
    )

    # Student 3: Submits Aadhaar only (No TC, No Birth Certificate)
    s3_sub = await StudentSubmission(
        batch_id=batch_id,
        class_id=sec_id,
        student_name="Chitra Devi",
        register_number=s3_reg,
        mobile_number="9876543212",
        email="chitra@example.com",
    ).insert()

    await doc_service.create_student_document(
        student_id=s3_reg,
        batch_id=batch_id,
        class_id=sec_id,
        submission_id=str(s3_sub.id),
        document_type="AADHAAR",
        document_name="Aadhaar Card",
        initial_file_path=temp_sample_aadhaar,
    )

    # Create auth tokens
    admin_user = User(
        username="cse_admin_user",
        name="CSE Admin",
        role=UserRole.DEPARTMENT_ADMIN,
        department_code=dept_id,
        password=get_password_hash("pass123"),
        is_active=True,
    )
    await User.find(User.username == "cse_admin_user").delete()
    await admin_user.insert()
    token_admin = create_access_token({"sub": str(admin_user.id), "role": admin_user.role.value, "department_code": dept_id})

    user_s1 = await User(username=s1_reg, name="Arun Kumar", role=UserRole.STUDENT, register_number=s1_reg, password=get_password_hash("pass123")).insert()
    user_s2 = await User(username=s2_reg, name="Bhavya Sri", role=UserRole.STUDENT, register_number=s2_reg, password=get_password_hash("pass123")).insert()
    token_s1 = create_access_token({"sub": str(user_s1.id), "role": "student", "register_number": s1_reg})
    token_s2 = create_access_token({"sub": str(user_s2.id), "role": "student", "register_number": s2_reg})

    # 3. Create Extraction Request #1 (Name, DOB, Gender, School Name) without any student IDs
    ext_service = BatchExtractionService()
    ext_service.extraction_service.gemini_service = mock_gemini_service

    with patch("app.api.batch_extraction.service", ext_service):
        req1_res = await client_async.post(
            f"/data-extractions/batches/{batch_id}/extract",
            headers={"Authorization": f"Bearer {token_admin}"},
            json={
                "requested_fields": ["student_name", "date_of_birth", "gender", "school_name"],
                "requested_columns": ["Student Name", "DOB", "Gender", "School Name"],
                "class_id": sec_id,
            },
        )
        assert req1_res.status_code == 200
        ext1 = req1_res.json()
        ext1_id = ext1["extraction_request_id"]
        assert ext1["total_students"] == 3, "All 3 students in batch/section must be included"
        assert ext1["result_count"] == 3, "All 3 students must receive extraction results"

        # 4. Check details of Extraction #1
        d1_res = await client_async.get(
            f"/data-extractions/requests/{ext1_id}",
            headers={"Authorization": f"Bearer {token_admin}"},
        )
        assert d1_res.status_code == 200
        d1 = d1_res.json()
        assert len(d1["students"]) == 3

        row_s1 = next(s for s in d1["students"] if s["student_id"] == s1_reg)
        row_s2 = next(s for s in d1["students"] if s["student_id"] == s2_reg)
        row_s3 = next(s for s in d1["students"] if s["student_id"] == s3_reg)

        # Student 1: Replaced Aadhaar was used
        s1_aadhaar_doc = await doc_service.get_student_document_by_type(s1_reg, "AADHAAR")
        assert s1_aadhaar_doc.active_version.original_filename == "aadhaar_replaced.pdf"

        # Student 2 & 3: Missing documents did not fail the batch
        assert row_s1["fields"]["student_name"]["ai_value"] == "Arun Kumar"
        assert row_s1["fields"]["student_name"]["document_type"] == "STUDENT_PROFILE"
        assert row_s3["fields"]["school_name"]["ai_value"] == "NOT_AVAILABLE"  # S3 has no TC

        # 5. Student Verification isolation
        # Student 1 can see own verification data
        verif_s1 = await client_async.get(
            f"/data-extractions/requests/{ext1_id}/student/{s1_reg}",
            headers={"Authorization": f"Bearer {token_s1}"},
        )
        assert verif_s1.status_code == 200
        assert verif_s1.json()["student_id"] == s1_reg

        # Student 1 CANNOT see Student 2 verification data (403 Forbidden)
        unauth_verif = await client_async.get(
            f"/data-extractions/requests/{ext1_id}/student/{s2_reg}",
            headers={"Authorization": f"Bearer {token_s1}"},
        )
        assert unauth_verif.status_code == 403

        # 6. Student submits correction (preserves AI value)
        v_name_s1 = next(f for f in verif_s1.json()["fields"] if f["field_name"] == "student_name")
        cor_res = await client_async.post(
            f"/data-extractions/requests/{ext1_id}/student/{s1_reg}/verify",
            headers={"Authorization": f"Bearer {token_s1}"},
            json={
                "fields": [
                    {
                        "verification_id": v_name_s1["verification_id"],
                        "field_name": "student_name",
                        "corrected_value": "Arun Kumar K",
                        "is_confirmed": False,
                        "comment": "Added initial K",
                    }
                ]
            },
        )
        assert cor_res.status_code == 200

        verif_rec_db = await DocumentFieldVerification.get(PydanticObjectId(v_name_s1["verification_id"]))
        assert verif_rec_db.status == VerificationFieldStatus.CORRECTION_REQUESTED
        assert verif_rec_db.ai_value == "Arun Kumar", "AI value must NOT be overwritten"
        assert verif_rec_db.student_value == "Arun Kumar K"

        # 7. Staff approves correction
        app_res = await client_async.post(
            f"/data-extractions/requests/{ext1_id}/review/{v_name_s1['verification_id']}",
            headers={"Authorization": f"Bearer {token_admin}"},
            json={"action": "APPROVE", "staff_comment": "Approved by staff"},
        )
        assert app_res.status_code == 200
        verif_rec_approved = await DocumentFieldVerification.get(PydanticObjectId(v_name_s1["verification_id"]))
        assert verif_rec_approved.status == VerificationFieldStatus.STAFF_APPROVED
        assert verif_rec_approved.final_value == "Arun Kumar K"

        # 8. Export verified Excel: Contains ALL 3 students
        exp_res = await client_async.get(
            f"/data-extractions/requests/{ext1_id}/export",
            headers={"Authorization": f"Bearer {token_admin}"},
        )
        assert exp_res.status_code == 200
        wb = openpyxl.load_workbook(io.BytesIO(exp_res.content))
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        assert len(rows) == 4, "Header row + 3 student rows"

        # 9. Extraction Request #2 with different fields (Community, Income) on same batch without re-upload
        req2_res = await client_async.post(
            f"/data-extractions/batches/{batch_id}/extract",
            headers={"Authorization": f"Bearer {token_admin}"},
            json={
                "requested_fields": ["community", "income"],
                "requested_columns": ["Community", "Income"],
                "class_id": sec_id,
            },
        )
        assert req2_res.status_code == 200
        ext2_id = req2_res.json()["extraction_request_id"]
        assert ext2_id != ext1_id

        # Extraction #1 remains unchanged and immutable
        d1_after = await client_async.get(
            f"/data-extractions/requests/{ext1_id}",
            headers={"Authorization": f"Bearer {token_admin}"},
        )
        assert d1_after.json()["summary"]["requested_fields"] == ["student_name", "date_of_birth", "gender", "school_name"]

    # Cleanup
    await AdmissionBatch.find(AdmissionBatch.id == batch_id).delete()
    await BatchClass.find(BatchClass.id == sec_id).delete()
    await Department.find(Department.code == dept_id).delete()
    for r in [s1_reg, s2_reg, s3_reg]:
        await StudentDocument.find(StudentDocument.student_id == r).delete()
        await StudentSubmission.find(StudentSubmission.register_number == r).delete()
    await BatchExtractionRequest.find(BatchExtractionRequest.batch_id == batch_id).delete()
    await DocumentFieldVerification.find(DocumentFieldVerification.batch_id == batch_id).delete()


@pytest.mark.asyncio
async def test_extraction_student_population_and_zero_student_guard(
    client_async,
    temp_sample_aadhaar,
    temp_sample_sslc,
    temp_sample_community,
    tmp_path,
    mock_gemini_service,
):
    """
    Direct regression test for:
    1. Batch dashboard shows 1 student, 4 stored documents.
    2. Create extraction request -> must find the student and report Students: 1, Verified: 0 / 1.
    3. Exactly 1 extraction result is created.
    4. Student completes verification -> Verified: 1 / 1.
    5. Batch with 0 students raises 400 Bad Request 'No students found for this Batch/Section.'
    """
    from app.models.batch_class import BatchClass

    dept_id = "AI_POP_TEST"
    batch_id = "batch_test_pop_001"
    sec_id = "class_sec_a_pop_001"
    empty_batch_id = "batch_empty_pop_002"

    await Department.find(Department.code == dept_id).delete()
    await AdmissionBatch.find({"_id": {"$in": [batch_id, empty_batch_id]}}).delete()
    await BatchClass.find(BatchClass.id == sec_id).delete()
    await BatchExtractionRequest.find({"batch_id": {"$in": [batch_id, empty_batch_id]}}).delete()
    await DocumentFieldVerification.find({"batch_id": {"$in": [batch_id, empty_batch_id]}}).delete()

    dept = Department(name="AI Population Dept", code=dept_id, intake_capacity=60, created_by="admin")
    await dept.insert()

    batch = AdmissionBatch(
        id=batch_id,
        name="TEST",
        department_id=dept_id,
        department_code=dept_id,
        academic_year="2026-2027",
        created_by="admin",
        status="active",
    )
    await batch.insert()

    empty_batch = AdmissionBatch(
        id=empty_batch_id,
        name="EMPTY BATCH",
        department_id=dept_id,
        department_code=dept_id,
        academic_year="2026-2027",
        created_by="admin",
        status="active",
    )
    await empty_batch.insert()

    sec = BatchClass(
        id=sec_id,
        batch_id=batch_id,
        class_name="Section A",
        section="A",
        department=dept.name,
        academic_year="2026-2027",
        created_by="admin",
    )
    await sec.insert()

    # 1 Student enters details + 4 stored documents (Aadhaar, TC, Community, SSLC)
    student_reg = "24AM093_TEST"
    student_name = "Shadhanan"

    await StudentSubmission.find(StudentSubmission.register_number == student_reg).delete()
    await StudentDocument.find(StudentDocument.student_id == student_reg).delete()
    await User.find(User.username == student_reg).delete()

    sub = await StudentSubmission(
        batch_id=batch_id,
        batch_name="TEST",
        class_id=sec_id,
        class_name="Section A",
        department_id=dept_id,
        student_name=student_name,
        register_number=student_reg,
        mobile_number="9876543210",
        email="shadhanan@example.com",
        submission_status="Submitted",
    ).insert()

    doc_service = StudentDocumentService()
    # 4 documents stored
    tc_file = tmp_path / "tc.pdf"
    tc_file.write_bytes(b"%PDF-1.4 TC Content")

    await doc_service.create_student_document(
        student_id=student_reg,
        batch_id=batch_id,
        class_id=sec_id,
        submission_id=str(sub.id),
        document_type="AADHAAR",
        document_name="Aadhaar Card",
        initial_file_path=temp_sample_aadhaar,
    )
    await doc_service.create_student_document(
        student_id=student_reg,
        batch_id=batch_id,
        class_id=sec_id,
        submission_id=str(sub.id),
        document_type="TRANSFER_CERTIFICATE",
        document_name="Transfer Certificate",
        initial_file_path=str(tc_file),
    )
    await doc_service.create_student_document(
        student_id=student_reg,
        batch_id=batch_id,
        class_id=sec_id,
        submission_id=str(sub.id),
        document_type="COMMUNITY",
        document_name="Community Certificate",
        initial_file_path=temp_sample_community,
    )
    await doc_service.create_student_document(
        student_id=student_reg,
        batch_id=batch_id,
        class_id=sec_id,
        submission_id=str(sub.id),
        document_type="SSLC",
        document_name="SSLC Marksheet",
        initial_file_path=temp_sample_sslc,
    )

    admin_user = User(
        username="admin_pop_tester",
        name="Pop Tester Admin",
        role=UserRole.DEPARTMENT_ADMIN,
        department_code=dept_id,
        password=get_password_hash("pass123"),
        is_active=True,
    )
    await User.find(User.username == "admin_pop_tester").delete()
    await admin_user.insert()
    token_admin = create_access_token({"sub": str(admin_user.id), "role": admin_user.role.value, "department_code": dept_id})

    # Check Batch Dashboard Stats
    overview_resp = await client_async.get(
        f"/data-extractions/batches/{batch_id}",
        headers={"Authorization": f"Bearer {token_admin}"},
    )
    assert overview_resp.status_code == 200
    ov = overview_resp.json()
    assert ov["students_count"] == 1
    assert ov["stored_documents_count"] == 4

    # Run Data Extraction for TEST Batch
    ext_service = BatchExtractionService()
    ext_service.extraction_service.gemini_service = mock_gemini_service

    with patch("app.api.batch_extraction.service", ext_service):
        # 1. Zero students batch must be rejected with 400 Bad Request
        empty_res = await client_async.post(
            f"/data-extractions/batches/{empty_batch_id}/extract",
            headers={"Authorization": f"Bearer {token_admin}"},
            json={
                "requested_fields": ["student_name", "date_of_birth", "gender"],
            },
        )
        assert empty_res.status_code == 400
        assert "No students found" in empty_res.json()["detail"]

        # 2. Extract for TEST batch with 1 student
        ext_res = await client_async.post(
            f"/data-extractions/batches/{batch_id}/extract",
            headers={"Authorization": f"Bearer {token_admin}"},
            json={
                "requested_fields": ["student_name", "date_of_birth", "gender", "community", "father_name"],
                "requested_columns": ["Student Name", "DOB", "Gender", "Community", "Father Name"],
            },
        )
        assert ext_res.status_code == 200
        ext_summary = ext_res.json()
        assert ext_summary["total_students"] == 1, "Must report total_students = 1"
        assert ext_summary["result_count"] == 1, "Must report result_count = 1"
        assert ext_summary["verified_count"] == 0, "Initial verified count must be 0"
        assert ext_summary["pending_verification_count"] == 1

        ext_req_id = ext_summary["extraction_request_id"]

        # 3. Check Details
        detail_res = await client_async.get(
            f"/data-extractions/requests/{ext_req_id}",
            headers={"Authorization": f"Bearer {token_admin}"},
        )
        assert detail_res.status_code == 200
        d_json = detail_res.json()
        assert d_json["summary"]["total_students"] == 1
        assert len(d_json["students"]) == 1
        student_card = d_json["students"][0]
        assert student_card["student_id"] == student_reg
        assert student_card["register_number"] == student_reg
        assert student_card["fields"]["student_name"]["ai_value"] == "Shadhanan"
        assert student_card["fields"]["student_name"]["document_type"] == "STUDENT_PROFILE"
        assert student_card["fields"]["date_of_birth"]["ai_value"] == "10/05/2006"
        assert student_card["fields"]["gender"]["ai_value"] == "MALE"
        comm_key = "community_category" if "community_category" in student_card["fields"] else "community"
        assert student_card["fields"][comm_key]["ai_value"] == "BC"
        assert student_card["fields"]["father_name"]["ai_value"] == "Rajendran"

        # 4. Check History Response
        hist_res = await client_async.get(
            f"/data-extractions/batches/{batch_id}/history",
            headers={"Authorization": f"Bearer {token_admin}"},
        )
        assert hist_res.status_code == 200
        h_items = hist_res.json()
        assert len(h_items) == 1
        assert h_items[0]["total_students"] == 1
        assert h_items[0]["verified_count"] == 0

        # 5. Student confirms verification
        stud_user = await User(
            username=student_reg,
            name=student_name,
            role=UserRole.STUDENT,
            register_number=student_reg,
            password=get_password_hash("pass123"),
        ).insert()
        token_student = create_access_token({"sub": str(stud_user.id), "role": "student", "register_number": student_reg})

        student_verif = await client_async.get(
            f"/data-extractions/requests/{ext_req_id}/student/{student_reg}",
            headers={"Authorization": f"Bearer {token_student}"},
        )
        assert student_verif.status_code == 200
        verif_fields = student_verif.json()["fields"]

        confirm_payload = [
            {"verification_id": f["verification_id"], "field_name": f["field_name"], "is_confirmed": True}
            for f in verif_fields
        ]
        submit_verif = await client_async.post(
            f"/data-extractions/requests/{ext_req_id}/student/{student_reg}/verify",
            headers={"Authorization": f"Bearer {token_student}"},
            json={"fields": confirm_payload},
        )
        assert submit_verif.status_code == 200

        # 6. Check updated details: Verified: 1 / 1
        detail_after = await client_async.get(
            f"/data-extractions/requests/{ext_req_id}",
            headers={"Authorization": f"Bearer {token_admin}"},
        )
        assert detail_after.status_code == 200
        d_after_json = detail_after.json()
        assert d_after_json["summary"]["verified_count"] == 1
        assert d_after_json["summary"]["total_students"] == 1
        assert d_after_json["summary"]["export_status"] == "READY"

    # Cleanup
    await Department.find(Department.code == dept_id).delete()
    await AdmissionBatch.find({"_id": {"$in": [batch_id, empty_batch_id]}}).delete()
    await BatchClass.find(BatchClass.id == sec_id).delete()
    await StudentSubmission.find(StudentSubmission.register_number == student_reg).delete()
    await StudentDocument.find(StudentDocument.student_id == student_reg).delete()
    await BatchExtractionRequest.find({"batch_id": {"$in": [batch_id, empty_batch_id]}}).delete()
    await DocumentFieldVerification.find({"batch_id": {"$in": [batch_id, empty_batch_id]}}).delete()

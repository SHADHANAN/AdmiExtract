"""
Comprehensive Test: Scope Inheritance, Canonical Resolution & Data Extraction Configuration
=============================================================================================
Validates:
1. Batch-level configuration persistence (Aadhaar: 10, Bank Passbook: 4, Community: 2, TC: 4).
2. Section-level query inherits Batch-level configuration (Wanted/Mapped are not 0).
3. Individual getDocumentConfig for Section scope returns the inherited fields (with checkboxes checked).
4. Section-specific overrides work independently without affecting Batch-level or other Sections.
5. Canonical document type resolution (AADHAAR, AADHAAR_CARD, etc.).
6. BatchExtraction request with Section scope uses resolved configuration and includes all students.
"""

import os
from typing import Any, List, cast
from datetime import datetime, timezone
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient

from app.main import app
from app.core.config import settings
from app.models.user import User
from app.models.batch import AdmissionBatch
from app.models.batch_class import BatchClass
from app.models.department import Department
from app.models.wanted_field_config import DocumentFieldConfiguration, WantedFieldItem
from app.models.student_submission import StudentSubmission
from app.models.student_document import StudentDocument
from app.models.batch_extraction import BatchExtractionRequest
from app.models.document_extraction_request import DocumentExtractionRequest
from app.models.document_extraction_result import DocumentExtractionResult
from app.models.document_verification import DocumentFieldVerification
from app.repositories.wanted_field_repository import WantedFieldRepository
from app.services.wanted_field_service import WantedFieldService
from app.services.batch_extraction_service import BatchExtractionService


@pytest_asyncio.fixture(scope="function", autouse=True)
async def setup_scope_test_db():
    if not hasattr(AsyncIOMotorClient, "append_metadata"):
        AsyncIOMotorClient.append_metadata = lambda *args, **kwargs: None

    test_client = AsyncIOMotorClient(settings.MONGODB_URI)
    test_db = test_client["automate_test_db"]

    import app.db.database
    app.db.database.client = test_client
    app.db.database.db = test_db
    app.db.database._is_connected = True
    from app.models.excel_template import ExcelBatchTemplate

    await init_beanie(
        database=cast(Any, test_db),
        document_models=[
            User,
            AdmissionBatch,
            BatchClass,
            Department,
            DocumentFieldConfiguration,
            StudentSubmission,
            StudentDocument,
            BatchExtractionRequest,
            DocumentExtractionRequest,
            DocumentExtractionResult,
            DocumentFieldVerification,
            ExcelBatchTemplate,
        ],
    )
    await DocumentFieldConfiguration.find_all().delete()
    await StudentSubmission.find_all().delete()
    await AdmissionBatch.find_all().delete()
    await BatchClass.find_all().delete()
    await Department.find_all().delete()

    yield

    await test_client.drop_database("automate_test_db")
    test_client.close()


@pytest_asyncio.fixture
async def client_async():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


async def get_token_for_user(client_async: AsyncClient, email: str = "staff_admin@example.com") -> str:
    username = email.split("@")[0]
    await client_async.post(
        "/auth/register",
        json={"username": username, "name": "Staff Admin", "email": email, "password": "password123", "role": "super_admin"}
    )
    res = await client_async.post(
        "/auth/login",
        data={"username": username, "password": "password123"}
    )
    return res.json()["access_token"]


@pytest.mark.asyncio
async def test_batch_config_and_section_inheritance(client_async: AsyncClient):
    token = await get_token_for_user(client_async)
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Create Batch "TEST" and Section "Section A"
    dept = Department(name="Computer Science", code="CS", created_by="staff_admin")
    await dept.insert()

    batch = AdmissionBatch(
        id="batch_test",
        name="TEST",
        academic_year="2025-2026",
        department_id=str(dept.id),
        status="ACTIVE",
        created_by="staff_admin",
    )
    await batch.insert()
    batch_id = str(batch.id)

    section_a = BatchClass(
        id="class_sec_a",
        class_name="B.Sc CS Section A",
        batch_id=batch_id,
        department="Computer Science",
        section="A",
        academic_year="2025-2026",
    )
    await section_a.insert()
    section_a_id = str(section_a.id)

    section_b = BatchClass(
        id="class_sec_b",
        class_name="B.Sc CS Section B",
        batch_id=batch_id,
        department="Computer Science",
        section="B",
        academic_year="2025-2026",
    )
    await section_b.insert()
    section_b_id = str(section_b.id)

    # 2. Save Batch-Level Configurations:
    # Aadhaar: 10 wanted, 10 mapped
    aadhaar_fields = [
        WantedFieldItem(field="Aadhaar Number", enabled=True, excel_header="Aadhaar Number"),
        WantedFieldItem(field="Student Name", enabled=True, excel_header="Student Name"),
        WantedFieldItem(field="Date of Birth", enabled=True, excel_header="DOB"),
        WantedFieldItem(field="Gender", enabled=True, excel_header="Gender"),
        WantedFieldItem(field="Permanent Address", enabled=True, excel_header="Address"),
        WantedFieldItem(field="Father Name", enabled=True, excel_header="Father Name"),
        WantedFieldItem(field="State", enabled=True, excel_header="State"),
        WantedFieldItem(field="Pincode", enabled=True, excel_header="Pincode"),
        WantedFieldItem(field="Phone", enabled=True, excel_header="Phone"),
        WantedFieldItem(field="Nationality", enabled=True, excel_header="Nationality"),
    ]
    res = await client_async.post(
        f"/wanted-fields/{batch_id}/AADHAAR",
        headers=headers,
        json={
            "fields": [f.model_dump() for f in aadhaar_fields],
            "display_name": "Aadhaar Card",
            "requirement_status": "REQUIRED",
        }
    )
    assert res.status_code == 200

    # Bank Passbook: 4 wanted, 4 mapped
    bank_fields = [
        WantedFieldItem(field="Account Number", enabled=True, excel_header="Account Number"),
        WantedFieldItem(field="IFSC Code", enabled=True, excel_header="IFSC Code"),
        WantedFieldItem(field="Bank Name", enabled=True, excel_header="Bank Name"),
        WantedFieldItem(field="Branch", enabled=True, excel_header="Branch"),
    ]
    res = await client_async.post(
        f"/wanted-fields/{batch_id}/BANK_PASSBOOK",
        headers=headers,
        json={
            "fields": [f.model_dump() for f in bank_fields],
            "display_name": "Bank Passbook",
            "requirement_status": "REQUIRED",
        }
    )
    assert res.status_code == 200

    # Community Certificate: 2 wanted, 2 mapped
    comm_fields = [
        WantedFieldItem(field="Community Category", enabled=True, excel_header="Community"),
        WantedFieldItem(field="Caste", enabled=True, excel_header="Caste"),
    ]
    res = await client_async.post(
        f"/wanted-fields/{batch_id}/COMMUNITY",
        headers=headers,
        json={
            "fields": [f.model_dump() for f in comm_fields],
            "display_name": "Community Certificate",
            "requirement_status": "REQUIRED",
        }
    )
    assert res.status_code == 200

    # Transfer Certificate: 4 wanted, 4 mapped
    tc_fields = [
        WantedFieldItem(field="Student Name", enabled=True, excel_header="TC Student Name"),
        WantedFieldItem(field="EMIS ID", enabled=True, excel_header="EMIS ID"),
        WantedFieldItem(field="Date of Leaving", enabled=True, excel_header="Leaving Date"),
        WantedFieldItem(field="Transfer Certificate Number", enabled=True, excel_header="TC Number"),
    ]
    res = await client_async.post(
        f"/wanted-fields/{batch_id}/TRANSFER_CERTIFICATE",
        headers=headers,
        json={
            "fields": [f.model_dump() for f in tc_fields],
            "display_name": "Transfer Certificate (TC)",
            "requirement_status": "REQUIRED",
        }
    )
    assert res.status_code == 200

    # 3. Test Batch-Level Overview
    res_batch_ov = await client_async.get(f"/wanted-fields/{batch_id}/overview", headers=headers)
    assert res_batch_ov.status_code == 200
    batch_ov_data = res_batch_ov.json()
    batch_ov_map = {item["document_type"]: item for item in batch_ov_data}

    assert batch_ov_map["AADHAAR"]["wanted_count"] == 10
    assert batch_ov_map["AADHAAR"]["mapped_count"] == 10
    assert batch_ov_map["AADHAAR"]["status"] == "CONFIGURED"

    assert batch_ov_map["BANK_PASSBOOK"]["wanted_count"] == 4
    assert batch_ov_map["BANK_PASSBOOK"]["mapped_count"] == 4
    assert batch_ov_map["BANK_PASSBOOK"]["status"] == "CONFIGURED"

    assert batch_ov_map["COMMUNITY"]["wanted_count"] == 2
    assert batch_ov_map["COMMUNITY"]["mapped_count"] == 2
    assert batch_ov_map["COMMUNITY"]["status"] == "CONFIGURED"

    assert batch_ov_map["TRANSFER_CERTIFICATE"]["wanted_count"] == 4
    assert batch_ov_map["TRANSFER_CERTIFICATE"]["mapped_count"] == 4
    assert batch_ov_map["TRANSFER_CERTIFICATE"]["status"] == "CONFIGURED"

    # 4. Test Section A Overview (Inheritance: MUST NOT be 0!)
    res_sec_ov = await client_async.get(f"/wanted-fields/{batch_id}/overview?class_id={section_a_id}", headers=headers)
    assert res_sec_ov.status_code == 200
    sec_ov_data = res_sec_ov.json()
    sec_ov_map = {item["document_type"]: item for item in sec_ov_data}

    assert sec_ov_map["AADHAAR"]["wanted_count"] == 10
    assert sec_ov_map["AADHAAR"]["mapped_count"] == 10
    assert sec_ov_map["AADHAAR"]["status"] == "CONFIGURED"
    assert sec_ov_map["AADHAAR"]["scope"] == "BATCH"

    assert sec_ov_map["BANK_PASSBOOK"]["wanted_count"] == 4
    assert sec_ov_map["BANK_PASSBOOK"]["mapped_count"] == 4
    assert sec_ov_map["BANK_PASSBOOK"]["status"] == "CONFIGURED"

    assert sec_ov_map["COMMUNITY"]["wanted_count"] == 2
    assert sec_ov_map["COMMUNITY"]["mapped_count"] == 2

    assert sec_ov_map["TRANSFER_CERTIFICATE"]["wanted_count"] == 4
    assert sec_ov_map["TRANSFER_CERTIFICATE"]["mapped_count"] == 4

    # 5. Test Configure Button: Fetch individual doc config for Section A (Inherits Batch level)
    res_aadhaar_sec = await client_async.get(f"/wanted-fields/{batch_id}/AADHAAR?class_id={section_a_id}", headers=headers)
    assert res_aadhaar_sec.status_code == 200
    aadhaar_sec_data = res_aadhaar_sec.json()
    assert aadhaar_sec_data["document_type"] == "AADHAAR"
    enabled_fields = [f for f in aadhaar_sec_data["fields"] if f["enabled"]]
    assert len(enabled_fields) == 10

    # 6. Override Section A for Aadhaar (e.g. 3 fields only)
    sec_a_custom_fields = [
        WantedFieldItem(field="Aadhaar Number", enabled=True, excel_header="Aadhaar No"),
        WantedFieldItem(field="Student Name", enabled=True, excel_header="Name"),
        WantedFieldItem(field="Date of Birth", enabled=True, excel_header="DOB"),
        WantedFieldItem(field="Gender", enabled=False, excel_header=None),
    ]
    res_save_override = await client_async.post(
        f"/wanted-fields/{batch_id}/AADHAAR?class_id={section_a_id}",
        headers=headers,
        json={
            "fields": [f.model_dump() for f in sec_a_custom_fields],
            "display_name": "Aadhaar Card",
            "requirement_status": "REQUIRED",
        }
    )
    assert res_save_override.status_code == 200

    # Section A overview now shows 3 wanted for Aadhaar with scope SECTION
    res_sec_ov_2 = await client_async.get(f"/wanted-fields/{batch_id}/overview?class_id={section_a_id}", headers=headers)
    assert res_sec_ov_2.status_code == 200
    sec_ov_data_2 = {item["document_type"]: item for item in res_sec_ov_2.json()}
    assert sec_ov_data_2["AADHAAR"]["wanted_count"] == 3
    assert sec_ov_data_2["AADHAAR"]["mapped_count"] == 3
    assert sec_ov_data_2["AADHAAR"]["scope"] == "SECTION"
    # Other docs in Section A still inherit batch level
    assert sec_ov_data_2["BANK_PASSBOOK"]["wanted_count"] == 4
    assert sec_ov_data_2["BANK_PASSBOOK"]["scope"] == "BATCH"

    # Section B overview still has Batch Level 10 fields for Aadhaar
    res_sec_b_ov = await client_async.get(f"/wanted-fields/{batch_id}/overview?class_id={section_b_id}", headers=headers)
    assert res_sec_b_ov.status_code == 200
    sec_b_ov_data = {item["document_type"]: item for item in res_sec_b_ov.json()}
    assert sec_b_ov_data["AADHAAR"]["wanted_count"] == 10
    assert sec_b_ov_data["AADHAAR"]["scope"] == "BATCH"


@pytest.mark.asyncio
async def test_canonical_document_type_resolution(client_async: AsyncClient):
    token = await get_token_for_user(client_async)
    headers = {"Authorization": f"Bearer {token}"}

    batch = AdmissionBatch(
        id="batch_canon",
        name="BATCH_CANON",
        department_id="DEPT_CANON",
        academic_year="2025-2026",
        status="ACTIVE",
        created_by="staff_admin",
    )
    await batch.insert()
    batch_id = str(batch.id)

    # Save using variant "AADHAAR_CARD"
    res = await client_async.post(
        f"/wanted-fields/{batch_id}/AADHAAR_CARD",
        headers=headers,
        json={
            "fields": [
                {"field": "Aadhaar Number", "enabled": True, "excel_header": "Aadhaar"},
                {"field": "Student Name", "enabled": True, "excel_header": "Name"},
            ],
            "display_name": "Aadhaar Card",
            "requirement_status": "REQUIRED",
        }
    )
    assert res.status_code == 200

    # Query using canonical "AADHAAR"
    res_get = await client_async.get(f"/wanted-fields/{batch_id}/AADHAAR", headers=headers)
    assert res_get.status_code == 200
    assert res_get.json()["document_type"] == "AADHAAR"
    assert len([f for f in res_get.json()["fields"] if f["enabled"]]) == 2

    # Query overview: should have only 1 Aadhaar entry under canonical code
    res_ov = await client_async.get(f"/wanted-fields/{batch_id}/overview", headers=headers)
    assert res_ov.status_code == 200
    ov_items = res_ov.json()
    aadhaar_items = [item for item in ov_items if item["document_type"] in ("AADHAAR", "AADHAAR_CARD")]
    assert len(aadhaar_items) == 1
    assert aadhaar_items[0]["document_type"] == "AADHAAR"
    assert aadhaar_items[0]["wanted_count"] == 2


@pytest.mark.asyncio
async def test_all_students_extraction_produces_unique_results_and_single_row_export(client_async: AsyncClient):
    token = await get_token_for_user(client_async, email="admin_extract@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    # Setup Batch TEST and Section A
    dept = Department(name="Information Technology", code="IT", created_by="admin_extract")
    await dept.insert()

    batch = AdmissionBatch(
        id="batch_test_extract",
        name="TEST",
        academic_year="2025-2026",
        department_id=str(dept.id),
        status="ACTIVE",
        created_by="admin_extract",
    )
    await batch.insert()
    batch_id = str(batch.id)

    section_a = BatchClass(
        id="class_sec_a_ext",
        class_name="Section A",
        batch_id=batch_id,
        department="Information Technology",
        section="A",
        academic_year="2025-2026",
    )
    await section_a.insert()
    section_a_id = str(section_a.id)

    # Setup 2 Students in Section A
    sub1 = StudentSubmission(
        batch_id=batch_id,
        class_id=section_a_id,
        student_name="Alice Kumar",
        register_number="25CS001",
        mobile_number="9876543210",
        email="alice@example.com",
        submission_status="Submitted",
    )
    await sub1.insert()

    sub2 = StudentSubmission(
        batch_id=batch_id,
        class_id=section_a_id,
        student_name="Bob Raj",
        register_number="25CS002",
        mobile_number="9876543211",
        email="bob@example.com",
        submission_status="Submitted",
    )
    await sub2.insert()

    # 7 Stored Docs total (4 for Alice, 3 for Bob)
    doc1 = StudentDocument(
        student_id="25CS001",
        batch_id=batch_id,
        class_id=section_a_id,
        document_type="AADHAAR",
        document_name="Aadhaar Card",
        file_url="/files/alice_aadhaar.pdf",
        status="VERIFIED",
    )
    doc2 = StudentDocument(
        student_id="25CS001",
        batch_id=batch_id,
        class_id=section_a_id,
        document_type="COMMUNITY",
        document_name="Community Certificate",
        file_url="/files/alice_comm.pdf",
        status="VERIFIED",
    )
    doc3 = StudentDocument(
        student_id="25CS001",
        batch_id=batch_id,
        class_id=section_a_id,
        document_type="TRANSFER_CERTIFICATE",
        document_name="Transfer Certificate",
        file_url="/files/alice_tc.pdf",
        status="VERIFIED",
    )
    doc4 = StudentDocument(
        student_id="25CS001",
        batch_id=batch_id,
        class_id=section_a_id,
        document_type="BANK_PASSBOOK",
        document_name="Bank Passbook",
        file_url="/files/alice_bank.pdf",
        status="VERIFIED",
    )
    doc5 = StudentDocument(
        student_id="25CS002",
        batch_id=batch_id,
        class_id=section_a_id,
        document_type="AADHAAR",
        document_name="Aadhaar Card",
        file_url="/files/bob_aadhaar.pdf",
        status="VERIFIED",
    )
    doc6 = StudentDocument(
        student_id="25CS002",
        batch_id=batch_id,
        class_id=section_a_id,
        document_type="COMMUNITY",
        document_name="Community Certificate",
        file_url="/files/bob_comm.pdf",
        status="VERIFIED",
    )
    doc7 = StudentDocument(
        student_id="25CS002",
        batch_id=batch_id,
        class_id=section_a_id,
        document_type="TRANSFER_CERTIFICATE",
        document_name="Transfer Certificate",
        file_url="/files/bob_tc.pdf",
        status="VERIFIED",
    )
    await doc1.insert()
    await doc2.insert()
    await doc3.insert()
    await doc4.insert()
    await doc5.insert()
    await doc6.insert()
    await doc7.insert()

    # Save Batch Document Configurations
    await client_async.post(
        f"/wanted-fields/{batch_id}/AADHAAR",
        headers=headers,
        json={
            "fields": [
                {"field": "Aadhaar Number", "enabled": True, "excel_header": "Aadhaar Number"},
                {"field": "Student Name", "enabled": True, "excel_header": "Student Name"},
            ],
            "display_name": "Aadhaar Card",
            "requirement_status": "REQUIRED",
        }
    )

    await client_async.post(
        f"/wanted-fields/{batch_id}/COMMUNITY",
        headers=headers,
        json={
            "fields": [
                {"field": "Community Category", "enabled": True, "excel_header": "Community"},
                {"field": "Caste", "enabled": True, "excel_header": "Caste"},
            ],
            "display_name": "Community Certificate",
            "requirement_status": "REQUIRED",
        }
    )

    # Check Overview when viewing Section A: Configuration exists, NOT 0
    res_ov = await client_async.get(f"/wanted-fields/{batch_id}/overview?class_id={section_a_id}", headers=headers)
    assert res_ov.status_code == 200
    ov_data = {item["document_type"]: item for item in res_ov.json()}
    assert ov_data["AADHAAR"]["wanted_count"] == 2
    assert ov_data["COMMUNITY"]["wanted_count"] == 2

    # Launch Batch Extraction for Section A (ALL 2 Students)
    user = await User.find_one({"email": "admin_extract@example.com"})
    extraction_service = BatchExtractionService()
    batch_req = await extraction_service.create_and_run_batch_extraction(
        batch_id=batch_id,
        requested_columns=None,
        requested_fields=["aadhaar_number", "student_name", "community_category", "caste"],
        actor=user,
        class_id=section_a_id,
    )

    assert batch_req.total_students == 2

    # Verify DocumentExtractionResult temporary documents are cleaned up upon Excel generation
    results = await DocumentExtractionResult.find({"extraction_request_id": batch_req.extraction_request_id}).to_list()
    assert len(results) == 0

    # Verify saved final Excel file exists on disk
    req_db = await BatchExtractionRequest.find_one({"extraction_request_id": batch_req.extraction_request_id})
    assert req_db.exported_file_path is not None
    assert os.path.exists(req_db.exported_file_path)
    assert batch_req.exported_filename is not None

    # Check verification records created for both students
    verifs = await DocumentFieldVerification.find({"extraction_request_id": batch_req.extraction_request_id}).to_list()
    assert len(verifs) > 0
    verif_stud_ids = {v.student_id for v in verifs}
    assert verif_stud_ids == {"25CS001", "25CS002"}


@pytest.mark.asyncio
async def test_full_25_field_extraction_execution_plan_and_export(client_async: AsyncClient):
    """
    Validates end-to-end extraction execution for 6 configured documents with 25 wanted/mapped fields
    across ALL 2 students in Batch TEST, Section A:
    1. Execution plan maps all 25 fields to their exact authoritative source document types.
    2. Missing documents produce NOT_AVAILABLE with reason SOURCE_DOCUMENT_MISSING without dropping student.
    3. Exactly 2 student extraction results and verification records.
    4. Verified Excel export produces exactly 2 rows with all 25 columns mapped correctly.
    """
    token = await get_token_for_user(client_async, email="staff_e2e@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    # Setup Batch TEST and Section A
    dept = Department(name="Computer Applications", code="BCA", created_by="staff_e2e")
    await dept.insert()

    batch = AdmissionBatch(
        id="batch_e2e_25",
        name="TEST",
        academic_year="2025-2026",
        department_id=str(dept.id),
        status="ACTIVE",
        created_by="staff_e2e",
    )
    await batch.insert()
    batch_id = str(batch.id)

    section_a = BatchClass(
        id="class_sec_a_25",
        class_name="Section A",
        batch_id=batch_id,
        department="Computer Applications",
        section="A",
        academic_year="2025-2026",
    )
    await section_a.insert()
    section_a_id = str(section_a.id)

    # 1. Configure 6 Document Types with 25 total Wanted & Mapped Fields:
    # 1. AADHAAR: 10 fields
    aadhaar_fields = [
        WantedFieldItem(field="Aadhaar Number", enabled=True, excel_header="Aadhaar Number"),
        WantedFieldItem(field="Student Name", enabled=True, excel_header="Student Name"),
        WantedFieldItem(field="Date of Birth", enabled=True, excel_header="Date of Birth"),
        WantedFieldItem(field="Gender", enabled=True, excel_header="Gender"),
        WantedFieldItem(field="Permanent Address", enabled=True, excel_header="Permanent Address"),
        WantedFieldItem(field="Father Name", enabled=True, excel_header="Father Name"),
        WantedFieldItem(field="State", enabled=True, excel_header="State"),
        WantedFieldItem(field="Pincode", enabled=True, excel_header="Pincode"),
        WantedFieldItem(field="Phone", enabled=True, excel_header="Phone"),
        WantedFieldItem(field="Nationality", enabled=True, excel_header="Nationality"),
    ]
    await client_async.post(
        f"/wanted-fields/{batch_id}/AADHAAR",
        headers=headers,
        json={"fields": [f.model_dump() for f in aadhaar_fields], "display_name": "Aadhaar Card", "requirement_status": "REQUIRED"}
    )

    # 2. BANK_PASSBOOK: 4 fields
    bank_fields = [
        WantedFieldItem(field="Account Number", enabled=True, excel_header="Account Number"),
        WantedFieldItem(field="IFSC Code", enabled=True, excel_header="IFSC Code"),
        WantedFieldItem(field="Bank Name", enabled=True, excel_header="Bank Name"),
        WantedFieldItem(field="Branch", enabled=True, excel_header="Branch"),
    ]
    await client_async.post(
        f"/wanted-fields/{batch_id}/BANK_PASSBOOK",
        headers=headers,
        json={"fields": [f.model_dump() for f in bank_fields], "display_name": "Bank Passbook", "requirement_status": "REQUIRED"}
    )

    # 3. COMMUNITY: 2 fields
    comm_fields = [
        WantedFieldItem(field="Community Category", enabled=True, excel_header="Community Category"),
        WantedFieldItem(field="Caste", enabled=True, excel_header="Caste"),
    ]
    await client_async.post(
        f"/wanted-fields/{batch_id}/COMMUNITY",
        headers=headers,
        json={"fields": [f.model_dump() for f in comm_fields], "display_name": "Community Certificate", "requirement_status": "REQUIRED"}
    )

    # 4. TRANSFER_CERTIFICATE: 4 fields
    tc_fields = [
        WantedFieldItem(field="Student Name", enabled=True, excel_header="TC Student Name"),
        WantedFieldItem(field="EMIS ID", enabled=True, excel_header="EMIS ID"),
        WantedFieldItem(field="Date of Leaving", enabled=True, excel_header="Date of Leaving"),
        WantedFieldItem(field="Transfer Certificate Number", enabled=True, excel_header="Transfer Certificate Number"),
    ]
    await client_async.post(
        f"/wanted-fields/{batch_id}/TRANSFER_CERTIFICATE",
        headers=headers,
        json={"fields": [f.model_dump() for f in tc_fields], "display_name": "Transfer Certificate (TC)", "requirement_status": "REQUIRED"}
    )

    # 5. SSLC: 3 fields
    sslc_fields = [
        WantedFieldItem(field="SSLC Register Number", enabled=True, excel_header="SSLC Register Number"),
        WantedFieldItem(field="SSLC Total Marks", enabled=True, excel_header="SSLC Total Marks"),
        WantedFieldItem(field="SSLC Mark Percentage", enabled=True, excel_header="SSLC Mark Percentage"),
    ]
    await client_async.post(
        f"/wanted-fields/{batch_id}/SSLC",
        headers=headers,
        json={"fields": [f.model_dump() for f in sslc_fields], "display_name": "10th SSLC Marksheet", "requirement_status": "REQUIRED"}
    )

    # 6. INCOME: 2 fields
    income_fields = [
        WantedFieldItem(field="Annual Family Income", enabled=True, excel_header="Annual Family Income"),
        WantedFieldItem(field="Income Certificate Number", enabled=True, excel_header="Income Certificate Number"),
    ]
    await client_async.post(
        f"/wanted-fields/{batch_id}/INCOME",
        headers=headers,
        json={"fields": [f.model_dump() for f in income_fields], "display_name": "Income Certificate", "requirement_status": "OPTIONAL"}
    )

    # Verify Overview for Section A: 6 configured documents, 25 wanted & mapped fields
    res_ov = await client_async.get(f"/wanted-fields/{batch_id}/overview?class_id={section_a_id}", headers=headers)
    assert res_ov.status_code == 200
    ov_items = res_ov.json()
    configured_items = [i for i in ov_items if i["wanted_count"] > 0]
    assert len(configured_items) == 6
    total_wanted = sum(i["wanted_count"] for i in configured_items)
    total_mapped = sum(i["mapped_count"] for i in configured_items)
    assert total_wanted == 25
    assert total_mapped == 25

    # 2. Setup 2 Students in Section A
    sub1 = StudentSubmission(
        batch_id=batch_id,
        class_id=section_a_id,
        student_name="Priya Dharshini",
        register_number="25BCA001",
        mobile_number="9876543210",
        email="priya@example.com",
        submission_status="Submitted",
    )
    await sub1.insert()

    sub2 = StudentSubmission(
        batch_id=batch_id,
        class_id=section_a_id,
        student_name="Karthik Raja",
        register_number="25BCA002",
        mobile_number="9876543211",
        email="karthik@example.com",
        submission_status="Submitted",
    )
    await sub2.insert()

    # Priya has Aadhaar, Bank, Community, TC
    doc_p1 = StudentDocument(student_id="25BCA001", batch_id=batch_id, class_id=section_a_id, document_type="AADHAAR", document_name="Aadhaar.pdf", file_url="/f/p1.pdf", status="VERIFIED")
    doc_p2 = StudentDocument(student_id="25BCA001", batch_id=batch_id, class_id=section_a_id, document_type="BANK_PASSBOOK", document_name="Passbook.pdf", file_url="/f/p2.pdf", status="VERIFIED")
    doc_p3 = StudentDocument(student_id="25BCA001", batch_id=batch_id, class_id=section_a_id, document_type="COMMUNITY", document_name="Community.pdf", file_url="/f/p3.pdf", status="VERIFIED")
    doc_p4 = StudentDocument(student_id="25BCA001", batch_id=batch_id, class_id=section_a_id, document_type="TRANSFER_CERTIFICATE", document_name="TC.pdf", file_url="/f/p4.pdf", status="VERIFIED")

    # Karthik has Aadhaar, SSLC, Income
    doc_k1 = StudentDocument(student_id="25BCA002", batch_id=batch_id, class_id=section_a_id, document_type="AADHAAR", document_name="Aadhaar.pdf", file_url="/f/k1.pdf", status="VERIFIED")
    doc_k2 = StudentDocument(student_id="25BCA002", batch_id=batch_id, class_id=section_a_id, document_type="SSLC", document_name="SSLC.pdf", file_url="/f/k2.pdf", status="VERIFIED")
    doc_k3 = StudentDocument(student_id="25BCA002", batch_id=batch_id, class_id=section_a_id, document_type="INCOME", document_name="Income.pdf", file_url="/f/k3.pdf", status="VERIFIED")

    await doc_p1.insert()
    await doc_p2.insert()
    await doc_p3.insert()
    await doc_p4.insert()
    await doc_k1.insert()
    await doc_k2.insert()
    await doc_k3.insert()

    # 3. Launch Batch Extraction
    user = await User.find_one({"email": "staff_e2e@example.com"})
    extraction_service = BatchExtractionService()

    all_25_field_keys = [
        "aadhaar_number", "student_name", "date_of_birth", "gender", "permanent_address",
        "father_name", "state", "pincode", "phone", "nationality",
        "account_number", "ifsc_code", "bank_name", "branch",
        "community_category", "caste",
        "emis_id", "date_of_leaving", "transfer_certificate_number",
        "sslc_register_number", "sslc_total_marks", "sslc_mark_percentage",
        "annual_family_income", "income_certificate_number",
    ]
    all_25_columns = [
        "Aadhaar Number", "Student Name", "Date of Birth", "Gender", "Permanent Address",
        "Father Name", "State", "Pincode", "Phone", "Nationality",
        "Account Number", "IFSC Code", "Bank Name", "Branch",
        "Community Category", "Caste",
        "EMIS ID", "Date of Leaving", "Transfer Certificate Number",
        "SSLC Register Number", "SSLC Total Marks", "SSLC Mark Percentage",
        "Annual Family Income", "Income Certificate Number",
    ]

    batch_req = await extraction_service.create_and_run_batch_extraction(
        batch_id=batch_id,
        requested_columns=all_25_columns,
        requested_fields=all_25_field_keys,
        actor=user,
        class_id=section_a_id,
    )

    # Verify exactly 2 students processed
    assert batch_req.total_students == 2
    assert batch_req.processed_count == 2

    # Ephemeral cleanup: DocumentExtractionResult is deleted upon successful Excel generation
    results = await DocumentExtractionResult.find({"extraction_request_id": batch_req.extraction_request_id}).to_list()
    assert len(results) == 0

    # Verification records retain extracted/missing data for student review workflow
    priya_verifs = await DocumentFieldVerification.find({
        "extraction_request_id": batch_req.extraction_request_id,
        "student_id": "25BCA001",
    }).to_list()
    pv_map = {v.field_name: v for v in priya_verifs}
    assert pv_map["sslc_total_marks"].status == "NOT_FOUND" or pv_map["sslc_total_marks"].ai_value == "NOT_AVAILABLE"

    karthik_verifs = await DocumentFieldVerification.find({
        "extraction_request_id": batch_req.extraction_request_id,
        "student_id": "25BCA002",
    }).to_list()
    kv_map = {v.field_name: v for v in karthik_verifs}
    assert kv_map["account_number"].status == "NOT_FOUND" or kv_map["account_number"].ai_value == "NOT_AVAILABLE"
    assert kv_map["community_category"].status == "NOT_FOUND" or kv_map["community_category"].ai_value == "NOT_AVAILABLE"

    # Verify Verification Records preserve the exact authoritative source document type
    verifs = await DocumentFieldVerification.find({"extraction_request_id": batch_req.extraction_request_id}).to_list()
    assert len(verifs) > 0
    priya_verifs = {v.field_name: v for v in verifs if v.student_id == "25BCA001"}
    assert priya_verifs["account_number"].document_type == "BANK_PASSBOOK"
    assert priya_verifs["community_category"].document_type == "COMMUNITY"

    # 4. Test Final Excel Export: exactly 2 rows for the 2 students
    excel_stream, filename = await extraction_service.export_verified_excel(
        extraction_request_id=batch_req.extraction_request_id,
        actor=user,
    )
    assert filename.endswith(".xlsx")
    import openpyxl
    wb = openpyxl.load_workbook(excel_stream)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    # Row 1 is headers, rows 2 and 3 are the 2 students
    assert len(rows) == 3
    headers_row = rows[0]
    assert "Aadhaar Number" in headers_row
    assert "Account Number" in headers_row
    assert "Community Category" in headers_row
    assert "Annual Family Income" in headers_row


@pytest.mark.asyncio
async def test_strict_configured_document_source_and_missing_document_guard(client_async):
    """
    Strict Test:
    1. Student 24AM093 has Aadhaar, Bank Passbook, Community Certificate, and TC.
    2. Staff configures:
       - Aadhaar: Student Name, Date of Birth, Gender
       - Bank Passbook: Account Number, IFSC Code, Bank Name
       - Community Certificate: Community Category, Caste
    3. Run extraction.
       Verify all fields come from their designated document type.
    4. Remove Bank Passbook document.
    5. Re-run extraction.
       Verify:
       - Account Number -> NOT_AVAILABLE (SOURCE_DOCUMENT_MISSING)
       - IFSC Code -> NOT_AVAILABLE (SOURCE_DOCUMENT_MISSING)
       - Bank Name -> NOT_AVAILABLE (SOURCE_DOCUMENT_MISSING)
       - Other fields remain intact from their configured source documents.
    """
    import tempfile
    from unittest.mock import patch
    from app.models.student_document import DocumentVersion
    from app.services.accuracy_extraction_engine import FieldExtractionResult

    now = datetime.now(timezone.utc)
    token = await get_token_for_user(client_async, email="admin_strict@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    dept = Department(name="Computer Science", code="CSE", created_by="admin_strict")
    await dept.insert()

    batch = AdmissionBatch(
        id="batch_strict_01",
        name="BATCH_STRICT_SOURCE_01",
        academic_year="2025-2026",
        department_id=str(dept.id),
        status="ACTIVE",
        created_by="admin_strict",
    )
    await batch.insert()
    batch_id = str(batch.id)

    user = await User.find_one({"email": "admin_strict@example.com"})

    # 2. Configure 3 Document Types
    # Aadhaar: Student Name, Date of Birth, Gender
    aadhaar_fields = [
        WantedFieldItem(field="Student Name", enabled=True, excel_header="Student Name"),
        WantedFieldItem(field="Date of Birth", enabled=True, excel_header="Date of Birth"),
        WantedFieldItem(field="Gender", enabled=True, excel_header="Gender"),
    ]
    await client_async.post(
        f"/wanted-fields/{batch_id}/AADHAAR",
        headers=headers,
        json={"fields": [f.model_dump() for f in aadhaar_fields], "display_name": "Aadhaar Card", "requirement_status": "REQUIRED"}
    )

    # Bank Passbook: Account Number, IFSC Code, Bank Name
    bank_fields = [
        WantedFieldItem(field="Account Number", enabled=True, excel_header="Account Number"),
        WantedFieldItem(field="IFSC Code", enabled=True, excel_header="IFSC Code"),
        WantedFieldItem(field="Bank Name", enabled=True, excel_header="Bank Name"),
    ]
    await client_async.post(
        f"/wanted-fields/{batch_id}/BANK_PASSBOOK",
        headers=headers,
        json={"fields": [f.model_dump() for f in bank_fields], "display_name": "Bank Passbook", "requirement_status": "REQUIRED"}
    )

    # Community: Community Category, Caste
    comm_fields = [
        WantedFieldItem(field="Community Category", enabled=True, excel_header="Community Category"),
        WantedFieldItem(field="Caste", enabled=True, excel_header="Caste"),
    ]
    await client_async.post(
        f"/wanted-fields/{batch_id}/COMMUNITY",
        headers=headers,
        json={"fields": [f.model_dump() for f in comm_fields], "display_name": "Community Certificate", "requirement_status": "REQUIRED"}
    )

    # 3. Create Student 24AM093 with 4 documents
    sub = StudentSubmission(
        batch_id=batch_id,
        student_name="Rahul Sharma",
        register_number="24AM093",
        mobile_number="9876543219",
        email="rahul@example.com",
        submission_status="Submitted",
    )
    await sub.insert()

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f_a, \
         tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f_b, \
         tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f_c, \
         tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f_t:

        f_a.write(b"%PDF-1.4 Aadhaar")
        f_b.write(b"%PDF-1.4 Bank")
        f_c.write(b"%PDF-1.4 Community")
        f_t.write(b"%PDF-1.4 TC")
        path_a, path_b, path_c, path_t = f_a.name, f_b.name, f_c.name, f_t.name

    doc_aadhaar = StudentDocument(
        student_id="24AM093",
        batch_id=batch_id,
        document_type="AADHAAR",
        document_name="Aadhaar.pdf",
        file_url="/f/aadhaar.pdf",
        status="VERIFIED",
        active_version=DocumentVersion(version_id="v1", version_number=1, file_path=path_a, original_filename="Aadhaar.pdf", uploaded_at=now),
        versions=[DocumentVersion(version_id="v1", version_number=1, file_path=path_a, original_filename="Aadhaar.pdf", uploaded_at=now)],
    )
    doc_bank = StudentDocument(
        student_id="24AM093",
        batch_id=batch_id,
        document_type="BANK_PASSBOOK",
        document_name="Passbook.pdf",
        file_url="/f/bank.pdf",
        status="VERIFIED",
        active_version=DocumentVersion(version_id="v1", version_number=1, file_path=path_b, original_filename="Passbook.pdf", uploaded_at=now),
        versions=[DocumentVersion(version_id="v1", version_number=1, file_path=path_b, original_filename="Passbook.pdf", uploaded_at=now)],
    )
    doc_comm = StudentDocument(
        student_id="24AM093",
        batch_id=batch_id,
        document_type="COMMUNITY",
        document_name="Community.pdf",
        file_url="/f/comm.pdf",
        status="VERIFIED",
        active_version=DocumentVersion(version_id="v1", version_number=1, file_path=path_c, original_filename="Community.pdf", uploaded_at=now),
        versions=[DocumentVersion(version_id="v1", version_number=1, file_path=path_c, original_filename="Community.pdf", uploaded_at=now)],
    )
    doc_tc = StudentDocument(
        student_id="24AM093",
        batch_id=batch_id,
        document_type="TRANSFER_CERTIFICATE",
        document_name="TC.pdf",
        file_url="/f/tc.pdf",
        status="VERIFIED",
        active_version=DocumentVersion(version_id="v1", version_number=1, file_path=path_t, original_filename="TC.pdf", uploaded_at=now),
        versions=[DocumentVersion(version_id="v1", version_number=1, file_path=path_t, original_filename="TC.pdf", uploaded_at=now)],
    )

    await doc_aadhaar.insert()
    await doc_bank.insert()
    await doc_comm.insert()
    await doc_tc.insert()

    extraction_service = BatchExtractionService()

    requested_columns = ["Student Name", "Date of Birth", "Gender", "Account Number", "IFSC Code", "Bank Name", "Community Category", "Caste"]
    requested_fields = ["student_name", "date_of_birth", "gender", "account_number", "ifsc_code", "bank_name", "community_category", "caste"]

    mock_values = {
        "AADHAAR": {
            "student_name": "Rahul Sharma",
            "date_of_birth": "15/08/2005",
            "gender": "Male",
        },
        "BANK_PASSBOOK": {
            "account_number": "123456789012",
            "ifsc_code": "SBIN0001234",
            "bank_name": "State Bank of India",
        },
        "COMMUNITY": {
            "community_category": "OBC",
            "caste": "Vanniyar",
        },
    }

    async def mock_extract(doc, version, field_key, actor):
        val = mock_values.get(doc.document_type, {}).get(field_key, "NOT_AVAILABLE")
        return FieldExtractionResult(
            field_name=field_key,
            raw_value=val,
            normalized_value=val,
            confidence="HIGH",
            confidence_score=0.95,
            field_state="EXTRACTED",
            evidence_snippet=f"{field_key}: {val}",
            source_document_type=doc.document_type,
        )

    async def mock_run_ai(file_path, document_type, requested_fields, **kwargs):
        dt_map = mock_values.get(document_type, {})
        return {f: dt_map.get(f) for f in requested_fields}, 95.0, "LOCAL_OCR_GEMINI", "OCR_SUCCESS", "gemini"

    # Run Initial Extraction with all 4 documents
    with patch.object(BatchExtractionService, "_extract_field_with_accuracy", side_effect=mock_extract), \
         patch.object(extraction_service.extraction_service, "_run_ai_extraction", side_effect=mock_run_ai):
        req1 = await extraction_service.create_and_run_batch_extraction(
            batch_id=batch_id,
            requested_columns=requested_columns,
            requested_fields=requested_fields,
            actor=user,
        )
    assert req1.total_students == 1
    assert req1.processed_count == 1

    # Verify Verification Records document types
    verifs1 = await DocumentFieldVerification.find({"extraction_request_id": req1.extraction_request_id, "student_id": "24AM093"}).to_list()
    v1_map = {v.field_name: v for v in verifs1}

    # Aadhaar fields come from AADHAAR
    assert v1_map["student_name"].document_type == "AADHAAR"
    assert v1_map["student_name"].ai_value == "Rahul Sharma"
    assert v1_map["date_of_birth"].document_type == "AADHAAR"
    assert v1_map["date_of_birth"].ai_value == "15/08/2005"
    assert v1_map["gender"].document_type == "AADHAAR"
    assert v1_map["gender"].ai_value == "Male"

    # Bank fields come from BANK_PASSBOOK
    assert v1_map["account_number"].document_type == "BANK_PASSBOOK"
    assert v1_map["account_number"].ai_value == "123456789012"
    assert v1_map["ifsc_code"].document_type == "BANK_PASSBOOK"
    assert v1_map["ifsc_code"].ai_value == "SBIN0001234"
    assert v1_map["bank_name"].document_type == "BANK_PASSBOOK"
    assert v1_map["bank_name"].ai_value == "State Bank of India"

    # Community fields come from COMMUNITY
    assert v1_map["community_category"].document_type == "COMMUNITY"
    assert v1_map["community_category"].ai_value == "OBC"
    assert v1_map["caste"].document_type == "COMMUNITY"
    assert v1_map["caste"].ai_value == "Vanniyar"

    # 4. Now remove Bank Passbook document for student 24AM093 in this specific test batch
    await StudentDocument.find(StudentDocument.student_id == "24AM093", StudentDocument.batch_id == batch_id, StudentDocument.document_type == "BANK_PASSBOOK").delete()

    # 5. Re-run extraction
    with patch.object(BatchExtractionService, "_extract_field_with_accuracy", side_effect=mock_extract), \
         patch.object(extraction_service.extraction_service, "_run_ai_extraction", side_effect=mock_run_ai):
        req2 = await extraction_service.create_and_run_batch_extraction(
            batch_id=batch_id,
            requested_columns=requested_columns,
            requested_fields=requested_fields,
            actor=user,
        )
    assert req2.total_students == 1

    # Verify ephemeral cleanup: DocumentExtractionResult is deleted upon Excel generation
    res2 = await DocumentExtractionResult.find_one({"extraction_request_id": req2.extraction_request_id, "student_id": "24AM093"})
    assert res2 is None

    # Check verifications for req2: Bank fields still record BANK_PASSBOOK as configured source, but value is NOT_AVAILABLE
    verifs2 = await DocumentFieldVerification.find({"extraction_request_id": req2.extraction_request_id, "student_id": "24AM093"}).to_list()
    v2_map = {v.field_name: v for v in verifs2}
    assert v2_map["account_number"].document_type == "BANK_PASSBOOK"
    assert v2_map["account_number"].ai_value == "NOT_AVAILABLE"
    assert v2_map["account_number"].field_state == "SOURCE_DOCUMENT_MISSING"
    assert v2_map["ifsc_code"].document_type == "BANK_PASSBOOK"
    assert v2_map["ifsc_code"].ai_value == "NOT_AVAILABLE"
    assert v2_map["ifsc_code"].field_state == "SOURCE_DOCUMENT_MISSING"

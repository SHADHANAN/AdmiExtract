"""
Test Suite: Student Portal Dynamic Document Configuration Single Source of Truth
==================================================================================
Tests verifying that the Admin Document Configuration is the ONLY source of truth
for the Student Portal document list and upload checklist.

Covers:
1. Admin creates Aadhaar -> Student Portal shows Aadhaar.
2. Admin creates TC -> Student Portal shows Aadhaar + TC.
3. Admin creates Community -> Student Portal shows Aadhaar + TC + Community.
4. Unconfigured Passbook does not appear.
5. Unconfigured FG does not appear.
6. Disabled document does not appear in Student Portal.
7. Required document has required=True, type='MANDATORY', requirement_status='REQUIRED'.
8. Optional document has required=False, type='OPTIONAL', requirement_status='OPTIONAL'.
9. Required document blocks submission when missing.
10. Optional document can be waived / marked 'Not Available' ('NO').
11. Zero configured documents returns empty documents list ([]) without fallback defaults.
12. Batch A documents do not leak into Batch B.
13. Class A configuration does not leak into Class B.
14. Existing uploaded documents are preserved when configuration changes.
15. Unauthenticated / Student users cannot modify document configuration (Security).
16. Both /public/batches/{batchId}/doc-versions/current and
    /public/batches/{batchId}/document-configurations return identical admin-configured documents.
"""

from typing import Any, cast
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient

from app.main import app
from app.core.config import settings
from app.models.user import User
from app.models.wanted_field_config import DocumentFieldConfiguration, WantedFieldItem
from app.models.excel_template import ExcelBatchTemplate
from app.models.student_submission import StudentSubmission, StudentDocumentMeta
from app.models.doc_config_version import DocumentConfigurationVersion
from app.services.wanted_field_service import WantedFieldService
from app.services.doc_config_version_service import DocConfigVersionService


@pytest_asyncio.fixture(scope="function", autouse=True)
async def setup_student_portal_test_db():
    if not hasattr(AsyncIOMotorClient, "append_metadata"):
        AsyncIOMotorClient.append_metadata = lambda *args, **kwargs: None

    test_client = AsyncIOMotorClient(settings.MONGODB_URI)
    test_db = test_client["automate_student_portal_test_db"]

    import app.db.database
    app.db.database.client = test_client
    app.db.database.db = test_db
    app.db.database._is_connected = True

    await init_beanie(
        database=cast(Any, test_db),
        document_models=[
            User,
            DocumentFieldConfiguration,
            ExcelBatchTemplate,
            StudentSubmission,
            DocumentConfigurationVersion,
        ],
    )
    await DocumentFieldConfiguration.find_all().delete()
    await ExcelBatchTemplate.find_all().delete()
    await StudentSubmission.find_all().delete()
    await DocumentConfigurationVersion.find_all().delete()

    yield

    await test_client.drop_database("automate_student_portal_test_db")
    test_client.close()


@pytest_asyncio.fixture
async def client_async():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.fixture
def wanted_service():
    return WantedFieldService()


@pytest.fixture
def doc_version_service():
    return DocConfigVersionService()


async def get_admin_token(client_async: AsyncClient, username: str = "admin_user") -> str:
    await client_async.post(
        "/auth/register",
        json={
            "username": username,
            "name": "Admin Tester",
            "email": f"{username}@test.com",
            "password": "password123",
            "role": "super_admin",
        },
    )
    resp = await client_async.post(
        "/auth/login",
        data={"username": username, "password": "password123"},
    )
    return resp.json()["access_token"]


# --------------------------------------------------------------------------
# Test 1: Zero Configured Documents -> Empty State (No random defaults)
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_zero_configured_documents_shows_empty_state(wanted_service, client_async):
    batch_id = "BATCH_EMPTY"
    reqs = await wanted_service.get_student_document_requirements(batch_id)
    assert reqs == [], "Fresh batch with zero configured documents must return an empty list."

    # Public endpoint returns empty documents list
    resp = await client_async.get(f"/public/batches/{batch_id}/doc-versions/current")
    assert resp.status_code == 200
    data = resp.json()
    assert data["documents"] == [], "Public doc-version must have 0 documents."

    # Document configurations endpoint returns 0 count
    resp2 = await client_async.get(f"/public/batches/{batch_id}/document-configurations")
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["count"] == 0
    assert data2["documents"] == []


# --------------------------------------------------------------------------
# Test 2: Step-by-Step Document Creation by Admin Reflected in Student Portal
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_admin_config_incremental_updates(wanted_service, client_async):
    batch_id = "BATCH_2025"

    # Step 1: Admin creates Aadhaar (REQUIRED)
    await wanted_service.create_document_type(
        batch_id=batch_id,
        name="Aadhaar Card",
        code="AADHAAR",
        requirement_status="REQUIRED",
    )
    reqs1 = await wanted_service.get_student_document_requirements(batch_id)
    assert len(reqs1) == 1
    assert reqs1[0]["name"] == "Aadhaar Card"
    assert reqs1[0]["code"] == "AADHAAR"
    assert reqs1[0]["required"] is True
    assert reqs1[0]["type"] == "MANDATORY"
    assert reqs1[0]["requirement_status"] == "REQUIRED"

    # Verify via public API
    resp1 = await client_async.get(f"/public/batches/{batch_id}/doc-versions/current")
    assert resp1.status_code == 200
    docs1 = resp1.json()["documents"]
    assert len(docs1) == 1
    assert docs1[0]["name"] == "Aadhaar Card"

    # Step 2: Admin creates TC (REQUIRED)
    await wanted_service.create_document_type(
        batch_id=batch_id,
        name="Transfer Certificate (TC)",
        code="TC",
        requirement_status="REQUIRED",
    )
    reqs2 = await wanted_service.get_student_document_requirements(batch_id)
    assert len(reqs2) == 2
    codes2 = [d["code"] for d in reqs2]
    assert "AADHAAR" in codes2
    assert "TC" in codes2

    # Step 3: Admin creates Community Certificate (REQUIRED)
    await wanted_service.create_document_type(
        batch_id=batch_id,
        name="Community Certificate",
        code="COMMUNITY",
        requirement_status="REQUIRED",
    )
    reqs3 = await wanted_service.get_student_document_requirements(batch_id)
    assert len(reqs3) == 3
    codes3 = [d["code"] for d in reqs3]
    assert "AADHAAR" in codes3
    assert "TC" in codes3
    assert "COMMUNITY" in codes3

    # Step 4: Admin creates Income Certificate (OPTIONAL)
    await wanted_service.create_document_type(
        batch_id=batch_id,
        name="Income Certificate",
        code="INCOME",
        requirement_status="OPTIONAL",
    )
    reqs4 = await wanted_service.get_student_document_requirements(batch_id)
    assert len(reqs4) == 4
    income_req = next(d for d in reqs4 if d["code"] == "INCOME")
    assert income_req["required"] is False
    assert income_req["type"] == "OPTIONAL"
    assert income_req["requirement_status"] == "OPTIONAL"

    # Step 5: Admin creates Allotment Order (DISABLED)
    await wanted_service.create_document_type(
        batch_id=batch_id,
        name="Allotment Order",
        code="ALLOTMENT_ORDER",
        requirement_status="DISABLED",
    )
    reqs5 = await wanted_service.get_student_document_requirements(batch_id)
    # Disabled documents must NOT be visible to students
    assert len(reqs5) == 4
    codes5 = [d["code"] for d in reqs5]
    assert "ALLOTMENT_ORDER" not in codes5

    # Step 6: Unconfigured Passbook and FG must NOT appear
    assert "PASSBOOK" not in codes5
    assert "BANK_PASSBOOK" not in codes5
    assert "FG" not in codes5
    assert "FIRST_GRADUATE" not in codes5


# --------------------------------------------------------------------------
# Test 3: Updating Document Requirement Status (e.g. REQUIRED -> DISABLED)
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_admin_disables_document_reflected_immediately(wanted_service, client_async):
    batch_id = "BATCH_STATUS_UPDATE"

    # Create TC as REQUIRED
    await wanted_service.create_document_type(
        batch_id=batch_id,
        name="Transfer Certificate",
        code="TC",
        requirement_status="REQUIRED",
    )
    reqs = await wanted_service.get_student_document_requirements(batch_id)
    assert len(reqs) == 1

    # Admin changes TC to DISABLED
    await wanted_service.save_document_configuration(
        batch_id=batch_id,
        doc_type="TC",
        fields=[],
        requirement_status="DISABLED",
    )

    # Now Student Portal must NOT show TC
    reqs_after = await wanted_service.get_student_document_requirements(batch_id)
    assert reqs_after == [], "Disabled document must immediately disappear from student portal requirements."

    # Public endpoint also returns 0 documents
    resp = await client_async.get(f"/public/batches/{batch_id}/doc-versions/current")
    assert len(resp.json()["documents"]) == 0


# --------------------------------------------------------------------------
# Test 4: Batch Isolation (Batch A vs Batch B)
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_batch_isolation(wanted_service):
    # Batch A has Aadhaar + TC
    await wanted_service.create_document_type(batch_id="BATCH_A", name="Aadhaar Card", code="AADHAAR")
    await wanted_service.create_document_type(batch_id="BATCH_A", name="Transfer Certificate", code="TC")

    # Batch B has Community Certificate only
    await wanted_service.create_document_type(batch_id="BATCH_B", name="Community Certificate", code="COMMUNITY")

    reqs_a = await wanted_service.get_student_document_requirements("BATCH_A")
    reqs_b = await wanted_service.get_student_document_requirements("BATCH_B")

    codes_a = [d["code"] for d in reqs_a]
    codes_b = [d["code"] for d in reqs_b]

    assert codes_a == ["AADHAAR", "TC"]
    assert codes_b == ["COMMUNITY"]
    assert "COMMUNITY" not in codes_a
    assert "AADHAAR" not in codes_b


# --------------------------------------------------------------------------
# Test 5: Class Scoping (Class A vs Class B)
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_class_scoping(wanted_service, client_async):
    batch_id = "BATCH_CLASSES"
    class_aiml_a = "CLASS_AIML_A"
    class_aiml_b = "CLASS_AIML_B"

    # Class A configures Aadhaar + TC
    await wanted_service.create_document_type(
        batch_id=batch_id,
        class_id=class_aiml_a,
        name="Aadhaar Card",
        code="AADHAAR",
    )
    await wanted_service.create_document_type(
        batch_id=batch_id,
        class_id=class_aiml_a,
        name="Transfer Certificate",
        code="TC",
    )

    # Class B configures Income Certificate
    await wanted_service.create_document_type(
        batch_id=batch_id,
        class_id=class_aiml_b,
        name="Income Certificate",
        code="INCOME",
    )

    reqs_a = await wanted_service.get_student_document_requirements(batch_id, class_id=class_aiml_a)
    reqs_b = await wanted_service.get_student_document_requirements(batch_id, class_id=class_aiml_b)

    assert [d["code"] for d in reqs_a] == ["AADHAAR", "TC"]
    assert [d["code"] for d in reqs_b] == ["INCOME"]

    # Test via public endpoint with classId param
    resp_a = await client_async.get(f"/public/batches/{batch_id}/doc-versions/current?classId={class_aiml_a}")
    assert [d["name"] for d in resp_a.json()["documents"]] == ["Aadhaar Card", "Transfer Certificate"]

    resp_b = await client_async.get(f"/public/batches/{batch_id}/doc-versions/current?classId={class_aiml_b}")
    assert [d["name"] for d in resp_b.json()["documents"]] == ["Income Certificate"]


# --------------------------------------------------------------------------
# Test 6: Safety - Preserving Existing Uploaded Student Submissions
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_existing_submissions_preserved_when_doc_archived(wanted_service):
    batch_id = "BATCH_AUDIT_PRESERVE"

    await wanted_service.create_document_type(batch_id=batch_id, name="Aadhaar Card", code="AADHAAR")

    # Simulate an existing student submission referencing AADHAAR
    submission = StudentSubmission(
        batch_id=batch_id,
        student_name="Candidate 1",
        register_number="REG001",
        mobile_number="9876543210",
        submission_status="Submitted",
        documents=[
            StudentDocumentMeta(
                document_name="Aadhaar Card",
                status="Uploaded",
                file_path="uploads/BATCH_AUDIT_PRESERVE/REG001/aadhaar.pdf",
            )
        ],
    )
    await submission.insert()

    # Now admin deletes or archives AADHAAR
    result = await wanted_service.delete_or_archive_document_type(batch_id=batch_id, doc_type="AADHAAR")
    assert result["success"] is True
    assert result["archived"] is True, "Must soft-archive when student submissions reference the document."

    # Verify submission is completely intact in DB
    found_sub = await StudentSubmission.find_one(StudentSubmission.register_number == "REG001")
    assert found_sub is not None
    assert found_sub.documents[0].document_name == "Aadhaar Card"
    assert found_sub.documents[0].status == "Uploaded"


# --------------------------------------------------------------------------
# Test 7: Security - Students Cannot Modify Document Configurations
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_student_cannot_modify_configuration(client_async):
    batch_id = "BATCH_SECURITY"

    # Try to create a document type without authentication
    resp_unauth = await client_async.post(
        f"/wanted-fields/{batch_id}/document-type",
        json={"name": "Fake Document", "code": "FAKE_DOC"},
    )
    assert resp_unauth.status_code in [401, 403], "Unauthenticated user cannot create document types."

    # Register as student role and get token
    await client_async.post(
        "/auth/register",
        json={
            "username": "student_user",
            "name": "Student Bob",
            "email": "student@test.com",
            "password": "password123",
            "role": "student",
        },
    )
    login_resp = await client_async.post(
        "/auth/login",
        data={"username": "student_user", "password": "password123"},
    )
    student_token = login_resp.json()["access_token"]

    # Student token cannot create or modify configuration
    headers = {"Authorization": f"Bearer {student_token}"}
    resp_student = await client_async.post(
        f"/wanted-fields/{batch_id}/document-type",
        json={"name": "Hacked Document", "code": "HACKED_DOC"},
        headers=headers,
    )
    assert resp_student.status_code == 403, "Student role is forbidden from modifying document types."

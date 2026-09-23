"""
Regression Test Suite: Document Configuration & Student Portal Duplication Prevention
======================================================================================
Tests verifying:
1. Adding document as REQUIRED -> appears once.
2. Adding document as OPTIONAL -> appears once.
3. Changing REQUIRED -> OPTIONAL -> still appears once.
4. Changing OPTIONAL -> REQUIRED -> still appears once.
5. Saving the same document twice -> still one configuration.
6. Reload / get overview -> exactly one configuration.
7. Student Portal requirements -> document appears exactly once.
8. Section isolation: Class A vs Class B have distinct configurations without leakage.
9. Defensive deduplication: if duplicate records exist, student portal API returns exactly one.
10. Safe database cleanup: detects and consolidates duplicates without touching student submissions.
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
from scripts.cleanup_duplicate_doc_configs import run_cleanup


@pytest_asyncio.fixture(scope="function", autouse=True)
async def setup_regression_test_db():
    if not hasattr(AsyncIOMotorClient, "append_metadata"):
        AsyncIOMotorClient.append_metadata = lambda *args, **kwargs: None

    test_client = AsyncIOMotorClient(settings.MONGODB_URI)
    test_db = test_client["automate_doc_dup_regression_test_db"]

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

    await test_client.drop_database("automate_doc_dup_regression_test_db")
    test_client.close()


@pytest_asyncio.fixture
async def client_async():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.fixture
def wanted_service():
    return WantedFieldService()


# --------------------------------------------------------------------------
# Test 1 & 2: Add document as REQUIRED and as OPTIONAL -> appears once
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_add_document_required_and_optional_appears_once(wanted_service, client_async):
    batch_id = "BATCH_DUP_1"

    # Step 1: Add Aadhaar Card as REQUIRED
    doc1 = await wanted_service.create_document_type(
        batch_id=batch_id,
        name="Aadhaar Card",
        code="AADHAAR",
        requirement_status="REQUIRED",
    )
    assert doc1.document_type == "AADHAAR"
    assert doc1.requirement_status == "REQUIRED"

    overview1 = await wanted_service.get_batch_overview(batch_id)
    assert len(overview1) == 1
    assert overview1[0]["document_type"] == "AADHAAR"
    assert overview1[0]["requirement_status"] == "REQUIRED"

    reqs1 = await wanted_service.get_student_document_requirements(batch_id)
    assert len(reqs1) == 1
    assert reqs1[0]["code"] == "AADHAAR"
    assert reqs1[0]["required"] is True

    # Step 2: Add Income Certificate as OPTIONAL
    doc2 = await wanted_service.create_document_type(
        batch_id=batch_id,
        name="Income Certificate",
        code="INCOME",
        requirement_status="OPTIONAL",
    )
    assert doc2.document_type == "INCOME"
    assert doc2.requirement_status == "OPTIONAL"

    overview2 = await wanted_service.get_batch_overview(batch_id)
    assert len(overview2) == 2
    income_ov = next(d for d in overview2 if d["document_type"] == "INCOME")
    assert income_ov["requirement_status"] == "OPTIONAL"

    # Verify student portal requirements
    reqs2 = await wanted_service.get_student_document_requirements(batch_id)
    assert len(reqs2) == 2
    income_req = next(d for d in reqs2 if d["code"] == "INCOME")
    assert income_req["required"] is False
    assert income_req["type"] == "OPTIONAL"
    assert income_req["requirement_status"] == "OPTIONAL"

    # Public endpoint test
    resp = await client_async.get(f"/public/batches/{batch_id}/document-configurations")
    assert resp.status_code == 200
    docs = resp.json()["documents"]
    assert len(docs) == 2
    doc_codes = [d["code"] for d in docs]
    assert doc_codes.count("INCOME") == 1
    assert doc_codes.count("AADHAAR") == 1


# --------------------------------------------------------------------------
# Test 3 & 4: Changing REQUIRED <-> OPTIONAL updates in place (still appears once)
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_changing_requirement_status_updates_in_place(wanted_service, client_async):
    batch_id = "BATCH_STATUS_TOGGLE"

    # Create Aadhaar as REQUIRED
    await wanted_service.create_document_type(
        batch_id=batch_id,
        name="Aadhaar Card",
        code="AADHAAR",
        requirement_status="REQUIRED",
    )
    overview1 = await wanted_service.get_batch_overview(batch_id)
    assert len(overview1) == 1
    assert overview1[0]["requirement_status"] == "REQUIRED"

    # Change REQUIRED -> OPTIONAL via save_document_configuration
    await wanted_service.save_document_configuration(
        batch_id=batch_id,
        doc_type="AADHAAR",
        fields=[],
        requirement_status="OPTIONAL",
        display_name="Aadhaar Card",
    )

    # Must STILL be exactly 1 document in overview and requirements
    overview2 = await wanted_service.get_batch_overview(batch_id)
    assert len(overview2) == 1, "Changing REQUIRED -> OPTIONAL must not create duplicate entries."
    assert overview2[0]["requirement_status"] == "OPTIONAL"

    reqs2 = await wanted_service.get_student_document_requirements(batch_id)
    assert len(reqs2) == 1
    assert reqs2[0]["requirement_status"] == "OPTIONAL"
    assert reqs2[0]["required"] is False

    # Change OPTIONAL -> REQUIRED via re-adding / create_document_type
    await wanted_service.create_document_type(
        batch_id=batch_id,
        name="Aadhaar Card",
        code="AADHAAR",
        requirement_status="REQUIRED",
    )

    overview3 = await wanted_service.get_batch_overview(batch_id)
    assert len(overview3) == 1, "Changing OPTIONAL -> REQUIRED must update in-place without duplicating."
    assert overview3[0]["requirement_status"] == "REQUIRED"

    reqs3 = await wanted_service.get_student_document_requirements(batch_id)
    assert len(reqs3) == 1
    assert reqs3[0]["requirement_status"] == "REQUIRED"
    assert reqs3[0]["required"] is True

    # Database count must be exactly 1
    db_count = await DocumentFieldConfiguration.find(DocumentFieldConfiguration.batch_id == batch_id).count()
    assert db_count == 1, f"Expected 1 document record in DB, found {db_count}."


# --------------------------------------------------------------------------
# Test 5 & 6: Save same document twice -> idempotent, single configuration
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_saving_same_document_twice_is_idempotent(wanted_service):
    batch_id = "BATCH_IDEMPOTENT"

    # Save document configuration
    await wanted_service.create_document_type(
        batch_id=batch_id,
        name="Transfer Certificate",
        code="TC",
        requirement_status="OPTIONAL",
    )
    # Save again with same code and name
    await wanted_service.create_document_type(
        batch_id=batch_id,
        name="Transfer Certificate",
        code="TC",
        requirement_status="OPTIONAL",
    )

    # Save configuration via save_document_configuration twice
    await wanted_service.save_document_configuration(
        batch_id=batch_id,
        doc_type="TC",
        fields=[],
        requirement_status="OPTIONAL",
    )
    await wanted_service.save_document_configuration(
        batch_id=batch_id,
        doc_type="TC",
        fields=[],
        requirement_status="OPTIONAL",
    )

    overview = await wanted_service.get_batch_overview(batch_id)
    assert len(overview) == 1
    assert overview[0]["document_type"] == "TC"
    assert overview[0]["requirement_status"] == "OPTIONAL"

    db_count = await DocumentFieldConfiguration.find(DocumentFieldConfiguration.batch_id == batch_id).count()
    assert db_count == 1, "Saving same document repeatedly must not produce duplicate DB records."


# --------------------------------------------------------------------------
# Test 7: Section isolation - Class A vs Class B without cross-leakage
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_section_isolation_prevents_cross_leakage(wanted_service):
    batch_id = "BATCH_SECTIONS"
    class_a = "SEC_AIML_A"
    class_b = "SEC_AIML_B"

    # Configure Aadhaar at batch level
    await wanted_service.create_document_type(
        batch_id=batch_id,
        name="Aadhaar Card",
        code="AADHAAR",
        requirement_status="REQUIRED",
    )

    # Section A configures Transfer Certificate
    await wanted_service.create_document_type(
        batch_id=batch_id,
        class_id=class_a,
        name="Transfer Certificate",
        code="TC",
        requirement_status="OPTIONAL",
    )

    # Section B configures Community Certificate
    await wanted_service.create_document_type(
        batch_id=batch_id,
        class_id=class_b,
        name="Community Certificate",
        code="COMMUNITY",
        requirement_status="REQUIRED",
    )

    # Batch-level query (class_id=None) must return ONLY Aadhaar
    batch_overview = await wanted_service.get_batch_overview(batch_id, class_id=None)
    batch_codes = [d["document_type"] for d in batch_overview]
    assert batch_codes == ["AADHAAR"], f"Batch level must only have AADHAAR, got {batch_codes}"

    # Section A query must return only Section A's documents
    sec_a_reqs = await wanted_service.get_student_document_requirements(batch_id, class_id=class_a)
    sec_a_codes = [d["code"] for d in sec_a_reqs]
    assert sec_a_codes == ["TC"], f"Section A must only have TC, got {sec_a_codes}"

    # Section B query must return only Section B's documents
    sec_b_reqs = await wanted_service.get_student_document_requirements(batch_id, class_id=class_b)
    sec_b_codes = [d["code"] for d in sec_b_reqs]
    assert sec_b_codes == ["COMMUNITY"], f"Section B must only have COMMUNITY, got {sec_b_codes}"


# --------------------------------------------------------------------------
# Test 8: Defensive deduplication when DB has raw duplicates
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_defensive_deduplication_of_corrupt_database_records(wanted_service, client_async):
    batch_id = "BATCH_RAW_DUPS"

    # Intentionally insert duplicate records directly into MongoDB
    doc1 = DocumentFieldConfiguration(
        batch_id=batch_id,
        class_id=None,
        document_type="AADHAAR",
        display_name="Aadhaar Card",
        requirement_status="REQUIRED",
        version=1,
    )
    doc2 = DocumentFieldConfiguration(
        batch_id=batch_id,
        class_id=None,
        document_type="AADHAAR",
        display_name="Aadhaar Card",
        requirement_status="OPTIONAL",
        version=2,
    )
    await doc1.insert()
    await doc2.insert()

    # Verify that raw DB has 2 records
    raw_count = await DocumentFieldConfiguration.find(DocumentFieldConfiguration.batch_id == batch_id).count()
    assert raw_count == 2

    # Overview must return exactly 1 deduplicated record (the latest version 2)
    overview = await wanted_service.get_batch_overview(batch_id)
    assert len(overview) == 1
    assert overview[0]["document_type"] == "AADHAAR"
    assert overview[0]["version"] == 2
    assert overview[0]["requirement_status"] == "OPTIONAL"

    # Student portal requirements must return exactly 1 document
    reqs = await wanted_service.get_student_document_requirements(batch_id)
    assert len(reqs) == 1
    assert reqs[0]["code"] == "AADHAAR"

    # Public endpoint must return count=1 and 1 document
    resp = await client_async.get(f"/public/batches/{batch_id}/document-configurations")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
    assert len(data["documents"]) == 1


# --------------------------------------------------------------------------
# Test 9: Safe Database Cleanup Script
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_safe_database_cleanup_utility():
    batch_id = "BATCH_CLEANUP"

    # Create 3 duplicates for AADHAAR with different wanted fields
    d1 = DocumentFieldConfiguration(
        batch_id=batch_id,
        class_id=None,
        document_type="AADHAAR",
        display_name="Aadhaar Card",
        requirement_status="REQUIRED",
        fields=[WantedFieldItem(field="Aadhaar Number", enabled=True, excel_header="Aadhaar No")],
        version=1,
    )
    d2 = DocumentFieldConfiguration(
        batch_id=batch_id,
        class_id=None,
        document_type="AADHAAR",
        display_name="Aadhaar Card",
        requirement_status="OPTIONAL",
        fields=[WantedFieldItem(field="Date of Birth", enabled=True, excel_header="DOB")],
        version=2,
    )
    await d1.insert()
    await d2.insert()

    # Create an associated student submission referencing Aadhaar Card
    sub = StudentSubmission(
        batch_id=batch_id,
        student_name="Alice Candidate",
        register_number="REG_ALICE",
        mobile_number="9876543210",
        submission_status="Submitted",
        documents=[
            StudentDocumentMeta(
                document_name="Aadhaar Card",
                status="Uploaded",
                file_path="uploads/BATCH_CLEANUP/REG_ALICE/aadhaar.pdf",
            )
        ],
    )
    await sub.insert()

    # 1. Run in dry-run mode
    dry_result = await run_cleanup(dry_run=True)
    assert dry_result["duplicate_groups_count"] == 1
    assert dry_result["removed_ids_count"] == 1

    # In dry-run mode, 2 records still exist
    assert await DocumentFieldConfiguration.find(DocumentFieldConfiguration.batch_id == batch_id).count() == 2

    # 2. Run live cleanup
    live_result = await run_cleanup(dry_run=False)
    assert live_result["duplicate_groups_count"] == 1
    assert live_result["removed_ids_count"] == 1

    # After cleanup, exactly 1 consolidated record exists
    remaining = await DocumentFieldConfiguration.find(DocumentFieldConfiguration.batch_id == batch_id).to_list()
    assert len(remaining) == 1
    canonical = remaining[0]
    assert canonical.document_type == "AADHAAR"
    assert canonical.requirement_status == "OPTIONAL"
    # Merged wanted fields: both Aadhaar Number and Date of Birth
    field_names = [f.field for f in canonical.fields]
    assert "Aadhaar Number" in field_names
    assert "Date of Birth" in field_names

    # CRITICAL: Student submission is completely untouched and intact
    found_sub = await StudentSubmission.find_one(StudentSubmission.register_number == "REG_ALICE")
    assert found_sub is not None
    assert found_sub.student_name == "Alice Candidate"
    assert len(found_sub.documents) == 1
    assert found_sub.documents[0].file_path == "uploads/BATCH_CLEANUP/REG_ALICE/aadhaar.pdf"

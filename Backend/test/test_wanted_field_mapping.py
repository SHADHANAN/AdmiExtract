"""
Comprehensive Test Suite: Admin-Created Document Types & Wanted Field Mapping System
=====================================================================================
Validates all requirements from user specification:
1. New configuration starts with zero document types.
2. Add Aadhaar Card successfully.
3. Aadhaar initially has zero wanted fields.
4. Select wanted fields.
5. Map selected fields to Excel columns.
6. Save configuration.
7. Reload configuration.
8. Configuration persists.
9. Add TC independently.
10. Aadhaar configuration does not overwrite TC.
11. Custom document can be created.
12. Duplicate document code is rejected.
13. Duplicate document name/code is handled safely.
14. New batch does not inherit documents unexpectedly.
15. Existing configurations remain intact.
16. Unselected fields are not requested for extraction (dynamic prompt & pipeline filter).
17. Archive/delete safety: documents with student files cannot be hard-deleted.
18. API endpoints for document type creation, overview, fields, and deletion.
"""

from typing import Any, List, cast
from unittest.mock import MagicMock
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
from app.models.student_submission import StudentSubmission
from app.services.wanted_field_service import (
    DOCUMENT_AVAILABLE_FIELDS_CATALOG,
    DOCUMENT_DISPLAY_NAMES,
    WantedFieldService,
)
from app.services.gemini_service import GeminiService
from app.services.document_processing_pipeline import DocumentProcessingPipeline
from app.utils.performance_profiler import DocumentTimer


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------

@pytest_asyncio.fixture(scope="function", autouse=True)
async def setup_wanted_test_db():
    if not hasattr(AsyncIOMotorClient, "append_metadata"):
        AsyncIOMotorClient.append_metadata = lambda *args, **kwargs: None

    test_client = AsyncIOMotorClient(settings.MONGODB_URI)
    test_db = test_client["automate_test_db"]

    import app.db.database
    app.db.database.client = test_client
    app.db.database.db = test_db
    app.db.database._is_connected = True

    await init_beanie(
        database=cast(Any, test_db),
        document_models=[User, DocumentFieldConfiguration, ExcelBatchTemplate, StudentSubmission],
    )
    await DocumentFieldConfiguration.find_all().delete()
    await ExcelBatchTemplate.find_all().delete()
    await StudentSubmission.find_all().delete()

    yield

    await test_client.drop_database("automate_test_db")
    test_client.close()


@pytest_asyncio.fixture
async def client_async():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.fixture
def service():
    return WantedFieldService()


@pytest.fixture
def pipeline():
    return DocumentProcessingPipeline()


async def get_token_for_user(client_async: AsyncClient, name: str = "Test Staff", email: str = "staff@example.com") -> str:
    username = email.split("@")[0]
    await client_async.post(
        "/auth/register",
        json={"username": username, "name": name, "email": email, "password": "password123", "role": "super_admin"}
    )
    response = await client_async.post(
        "/auth/login",
        data={"username": username, "password": "password123"}
    )
    return response.json()["access_token"]


# --------------------------------------------------------------------------
# Requirement 1: New Configuration Starts with Zero Document Types
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_01_new_configuration_starts_with_zero_document_types(service):
    """When a new batch has no configured documents, get_batch_overview must return an empty list."""
    overview = await service.get_batch_overview("fresh_batch_001")
    assert overview == [], "Fresh batch must start with ZERO document types!"

    # Directly getting a doc type from an unconfigured batch returns None
    config = await service.get_document_configuration("fresh_batch_001", "AADHAAR")
    assert config is None, "Must not auto-synthesize default documents!"


# --------------------------------------------------------------------------
# Requirement 2 & 3: Add Aadhaar Card Successfully with Zero Wanted Fields
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_02_and_03_add_aadhaar_with_zero_wanted_fields(service):
    """Adding Aadhaar Card creates it with 0 wanted fields initially (all checkboxes unchecked)."""
    doc = await service.create_document_type(
        batch_id="batch_001",
        name="Aadhaar Card",
        code="AADHAAR",
        description="Government ID",
    )
    assert doc is not None
    assert doc.display_name == "Aadhaar Card"
    assert doc.document_type == "AADHAAR"

    # Crucial requirement: Wanted fields count must be 0!
    enabled_fields = [f for f in doc.fields if f.enabled]
    assert len(enabled_fields) == 0, "Aadhaar must initially have ZERO enabled wanted fields!"

    # Available fields should be populated from catalog, but all enabled=False
    assert len(doc.fields) == len(DOCUMENT_AVAILABLE_FIELDS_CATALOG["AADHAAR"])
    for f in doc.fields:
        assert f.enabled is False
        assert f.excel_header is None

    # Verify overview shows 0 wanted fields and NO_WANTED_FIELDS status
    overview = await service.get_batch_overview("batch_001")
    assert len(overview) == 1
    item = overview[0]
    assert item["document_type"] == "AADHAAR"
    assert item["display_name"] == "Aadhaar Card"
    assert item["wanted_count"] == 0
    assert item["mapped_count"] == 0
    assert item["status"] == "NO_WANTED_FIELDS"


# --------------------------------------------------------------------------
# Requirement 4, 5, 6, 7, 8: Select Wanted Fields, Map to Excel, Save & Persist
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_04_to_08_select_map_save_reload_persists(service):
    """Select wanted fields, assign Excel columns, save and reload, verifying persistence."""
    # 1. Create document type
    await service.create_document_type(
        batch_id="batch_002",
        name="Aadhaar Card",
        code="AADHAAR",
    )

    # 2. Select wanted fields and map to Excel
    updated_fields = [
        WantedFieldItem(field="Aadhaar Number", enabled=True, excel_header="Aadhaar Number"),
        WantedFieldItem(field="Date of Birth", enabled=True, excel_header="DOB"),
        WantedFieldItem(field="Permanent Address", enabled=True, excel_header="Address"),
        WantedFieldItem(field="District", enabled=True, excel_header="District"),
        WantedFieldItem(field="Taluk", enabled=False, excel_header=None),  # Unselected
    ]

    # 3. Save configuration
    saved = await service.save_document_configuration(
        batch_id="batch_002",
        doc_type="AADHAAR",
        fields=updated_fields,
    )
    assert saved.version == 2

    # 4. Reload configuration from database
    reloaded = await service.get_document_configuration("batch_002", "AADHAAR")
    assert reloaded is not None
    assert len(reloaded.fields) == 5

    enabled_reloaded = [f for f in reloaded.fields if f.enabled]
    assert len(enabled_reloaded) == 4
    assert enabled_reloaded[0].field == "Aadhaar Number"
    assert enabled_reloaded[0].excel_header == "Aadhaar Number"
    assert enabled_reloaded[1].field == "Date of Birth"
    assert enabled_reloaded[1].excel_header == "DOB"

    # 5. Check overview stats
    overview = await service.get_batch_overview("batch_002")
    assert len(overview) == 1
    assert overview[0]["wanted_count"] == 4
    assert overview[0]["mapped_count"] == 4
    assert overview[0]["unmapped_count"] == 0
    assert overview[0]["status"] == "CONFIGURED"


# --------------------------------------------------------------------------
# Requirement 9 & 10: Add TC Independently & No Overwrite
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_09_and_10_add_tc_independently_no_overwrite(service):
    """Add TC independently. Aadhaar configuration must not overwrite or interfere with TC."""
    # 1. Create Aadhaar and configure it
    await service.create_document_type("batch_multi", name="Aadhaar Card", code="AADHAAR")
    await service.save_document_configuration(
        "batch_multi",
        "AADHAAR",
        [WantedFieldItem(field="Aadhaar Number", enabled=True, excel_header="Aadhaar Number")],
    )

    # 2. Add TC independently
    await service.create_document_type("batch_multi", name="Transfer Certificate", code="TC")
    tc_config = await service.get_document_configuration("batch_multi", "TC")
    assert tc_config is not None
    assert len([f for f in tc_config.fields if f.enabled]) == 0

    # Configure TC
    await service.save_document_configuration(
        "batch_multi",
        "TC",
        [
            WantedFieldItem(field="EMIS ID", enabled=True, excel_header="EMIS ID"),
            WantedFieldItem(field="Transfer Certificate Number", enabled=True, excel_header="TC No"),
        ],
    )

    # 3. Verify Aadhaar is completely intact and unchanged
    aadhaar_config = await service.get_document_configuration("batch_multi", "AADHAAR")
    assert aadhaar_config is not None
    assert len([f for f in aadhaar_config.fields if f.enabled]) == 1
    assert aadhaar_config.fields[0].field == "Aadhaar Number"

    # Verify both documents exist in overview
    overview = await service.get_batch_overview("batch_multi")
    assert len(overview) == 2
    types = {item["document_type"] for item in overview}
    assert types == {"AADHAAR", "TC"}


# --------------------------------------------------------------------------
# Requirement 11: Custom Documents and Custom Fields
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_11_custom_document_and_custom_field_creation(service):
    """Support custom document types and dynamic addition of custom fields."""
    # Create custom document
    doc = await service.create_document_type(
        batch_id="batch_custom",
        name="Residence Certificate",
        code="RESIDENCE_CERTIFICATE",
        description="Local government proof of residency",
    )
    assert doc.document_type == "RESIDENCE_CERTIFICATE"
    assert doc.display_name == "Residence Certificate"
    assert doc.description == "Local government proof of residency"
    assert len(doc.fields) == 0  # Brand new custom document starts with 0 fields

    # Add custom fields to this document
    updated_doc = await service.add_field_to_document(
        batch_id="batch_custom",
        doc_type="RESIDENCE_CERTIFICATE",
        field_name="Residential Address",
    )
    assert len(updated_doc.fields) == 1
    assert updated_doc.fields[0].field == "Residential Address"
    assert updated_doc.fields[0].enabled is False  # Must start unchecked!

    # Add another field
    updated_doc2 = await service.add_field_to_document(
        batch_id="batch_custom",
        doc_type="RESIDENCE_CERTIFICATE",
        field_name="Years of Residence",
    )
    assert len(updated_doc2.fields) == 2
    assert updated_doc2.fields[1].field == "Years of Residence"
    assert updated_doc2.fields[1].enabled is False


# --------------------------------------------------------------------------
# Requirement 12 & 13: Duplicate Document Code / Name Handling
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_12_and_13_duplicate_code_rejection(service):
    """Duplicate document code or duplicate display name within the same batch must be rejected."""
    await service.create_document_type(
        batch_id="batch_dup",
        name="Aadhaar Card",
        code="AADHAAR",
    )

    # 1. Duplicate code with different case / spaces (normalized check)
    with pytest.raises(ValueError) as exc1:
        await service.create_document_type(
            batch_id="batch_dup",
            name="Another Aadhaar",
            code="aadhaar ",  # Normalizes to AADHAAR
        )
    assert "already exists for this batch" in str(exc1.value)

    # 2. Duplicate display name with different code
    with pytest.raises(ValueError) as exc2:
        await service.create_document_type(
            batch_id="batch_dup",
            name="  Aadhaar Card  ",
            code="AADHAAR_2",
        )
    assert "already exists for this batch" in str(exc2.value)


# --------------------------------------------------------------------------
# Requirement 14: New Batch Does Not Inherit Documents Unexpectedly
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_14_batch_isolation(service):
    """Batch A configuration must never appear in Batch B."""
    await service.create_document_type(
        batch_id="batch_alpha",
        name="Passport",
        code="PASSPORT",
    )

    overview_beta = await service.get_batch_overview("batch_beta")
    assert len(overview_beta) == 0, "Batch B must have 0 documents!"

    passport_in_beta = await service.get_document_configuration("batch_beta", "PASSPORT")
    assert passport_in_beta is None


# --------------------------------------------------------------------------
# Requirement 15: Existing Configurations Remain Intact
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_15_existing_configurations_intact(service):
    """Existing configurations stored in the database remain readable and intact."""
    # Pre-populate a configuration directly in DB as if created previously
    existing = DocumentFieldConfiguration(
        batch_id="batch_existing",
        document_type="COMMUNITY",
        display_name="Community Certificate",
        version=3,
        fields=[
            WantedFieldItem(field="Community Category", enabled=True, excel_header="Community"),
            WantedFieldItem(field="Caste Name", enabled=True, excel_header="Caste"),
        ],
    )
    await existing.insert()

    reloaded = await service.get_document_configuration("batch_existing", "COMMUNITY")
    assert reloaded is not None
    assert reloaded.version == 3
    assert len(reloaded.fields) == 2
    assert reloaded.fields[0].field == "Community Category"

    overview = await service.get_batch_overview("batch_existing")
    assert len(overview) == 1
    assert overview[0]["document_type"] == "COMMUNITY"
    assert overview[0]["wanted_count"] == 2


# --------------------------------------------------------------------------
# Requirement 16: Unselected Fields Not Requested & Extraction Short-Circuit
# --------------------------------------------------------------------------

def test_16_gemini_dynamic_prompt_requests_wanted_only():
    """Gemini multimodal prompt only includes wanted fields in instructions and output schema."""
    gemini = GeminiService()
    wanted = ["Aadhaar Number", "Date of Birth"]
    prompt = gemini.build_multimodal_prompt(target_fields=wanted)

    assert "CRITICAL INSTRUCTION: You must ONLY extract the following WANTED FIELDS" in prompt
    assert "- Aadhaar Number" in prompt
    assert "- Date of Birth" in prompt
    assert '"aadhaar_number": "string or null"' in prompt
    assert '"date_of_birth": "string or null"' in prompt

    # Unwanted fields omitted
    assert '"student_name": "string or null"' not in prompt
    assert '"annual_income": "string or null"' not in prompt


def test_16_pipeline_zero_wanted_fields_short_circuit(pipeline, tmp_path):
    """Pipeline short-circuits with NO_WANTED_FIELDS_CONFIGURED when 0 wanted fields are selected."""
    pipeline.gemini_service.extract_from_bytes = MagicMock()

    batch_wanted_configs = {
        "AADHAAR": []  # 0 wanted fields
    }

    doc_timer = DocumentTimer("aadhaar_card.pdf")
    res = pipeline._process_single_document(
        filename="aadhaar_card.pdf",
        file_bytes=b"fake_pdf_bytes",
        excel_headers=["Aadhaar Number", "Name"],
        uploads_dir=tmp_path,
        doc_timer=doc_timer,
        batch_wanted_configs=batch_wanted_configs,
    )

    pipeline.gemini_service.extract_from_bytes.assert_not_called()
    assert res["ai_response_status"] == "NO_WANTED_FIELDS_CONFIGURED"
    assert res["doc_extracted"] == {}
    assert res["doc_type"] == "AADHAAR"


# --------------------------------------------------------------------------
# Requirement 17: Delete / Archive Safety
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_17_delete_archive_safety(service):
    """Deleting a document type with active student submissions archives it rather than hard-deleting."""
    # 1. Create document type
    await service.create_document_type(
        batch_id="batch_archive",
        name="Birth Certificate",
        code="BIRTH_CERTIFICATE",
    )

    # 2. Simulate student submission having uploaded this document
    student = StudentSubmission(
        batch_id="batch_archive",
        student_name="John Doe",
        register_number="REG001",
        mobile_number="9876543210",
        email="john@example.com",
        documents=[
            {
                "document_name": "BIRTH_CERTIFICATE",
                "file_path": "/uploads/birth.pdf",
            }
        ],
    )
    await student.insert()

    # 3. Attempt delete
    result = await service.delete_or_archive_document_type("batch_archive", "BIRTH_CERTIFICATE")
    assert result["success"] is True
    assert result["archived"] is True
    assert "has been archived" in result["message"]

    # In overview, archived document is excluded by default
    overview = await service.get_batch_overview("batch_archive")
    assert len(overview) == 0

    # In database, the document is still preserved with is_archived = True
    db_doc = await DocumentFieldConfiguration.find_one(
        DocumentFieldConfiguration.batch_id == "batch_archive",
        DocumentFieldConfiguration.document_type == "BIRTH_CERTIFICATE",
    )
    assert db_doc is not None
    assert db_doc.is_archived is True


# --------------------------------------------------------------------------
# REST API Endpoints Tests
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_18_api_endpoints_full_lifecycle(client_async):
    """Test full REST API lifecycle: overview (0) -> create doc -> overview (1) -> add field -> save -> delete."""
    token = await get_token_for_user(client_async, "Admin User", "admin@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    batch_id = "batch_api_lifecycle"

    # 1. Initial overview must be empty (0 documents)
    res = await client_async.get(f"/wanted-fields/{batch_id}/overview", headers=headers)
    assert res.status_code == 200
    assert res.json() == []

    # 2. Create Aadhaar document
    create_payload = {
        "name": "Aadhaar Card",
        "code": "AADHAAR",
        "description": "Unique Identification Authority of India ID",
    }
    res = await client_async.post(f"/wanted-fields/{batch_id}/document-type", json=create_payload, headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["display_name"] == "Aadhaar Card"
    assert data["document_type"] == "AADHAAR"
    assert len([f for f in data["fields"] if f["enabled"]]) == 0

    # 3. Overview now has 1 document
    res = await client_async.get(f"/wanted-fields/{batch_id}/overview", headers=headers)
    assert res.status_code == 200
    overview = res.json()
    assert len(overview) == 1
    assert overview[0]["wanted_count"] == 0

    # 4. Add custom field
    res = await client_async.post(
        f"/wanted-fields/{batch_id}/AADHAAR/fields",
        json={"field_name": "Virtual ID"},
        headers=headers,
    )
    assert res.status_code == 200
    assert any(f["field"] == "Virtual ID" for f in res.json()["fields"])

    # 5. Save wanted field configuration
    save_payload = {
        "document_type": "AADHAAR",
        "fields": [
            {"field": "Aadhaar Number", "enabled": True, "excel_header": "Aadhaar Number"},
            {"field": "Date of Birth", "enabled": True, "excel_header": "DOB"},
        ],
    }
    res = await client_async.put(f"/wanted-fields/{batch_id}/AADHAAR", json=save_payload, headers=headers)
    assert res.status_code == 200
    assert res.json()["version"] >= 1

    # 6. Delete document
    res = await client_async.delete(f"/wanted-fields/{batch_id}/AADHAAR", headers=headers)
    assert res.status_code == 200
    assert res.json()["success"] is True

    # 7. Overview returns to 0
    res = await client_async.get(f"/wanted-fields/{batch_id}/overview", headers=headers)
    assert res.status_code == 200
    assert res.json() == []

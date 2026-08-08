import pytest
import pytest_asyncio
from typing import Any, cast
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.models.user import User
from app.models.department import Department
from app.models.batch import AdmissionBatch
from app.models.doc_config_version import DocumentConfigurationVersion, DocumentRequirementItem
from app.models.student_submission import StudentSubmission
from app.core.config import settings
from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient

from app.models.excel_template import ExcelBatchTemplate

@pytest_asyncio.fixture(scope="function", autouse=True)
async def setup_test_db():
    if not hasattr(AsyncIOMotorClient, "append_metadata"):
        AsyncIOMotorClient.append_metadata = lambda *args, **kwargs: None

    test_client = AsyncIOMotorClient(settings.MONGODB_URI)
    test_db = test_client["automate_test_db"]
    
    import app.db.database
    app.db.database.client = test_client
    app.db.database.db = test_db

    await init_beanie(
        database=cast(Any, test_db),
        document_models=[User, Department, AdmissionBatch, DocumentConfigurationVersion, StudentSubmission, ExcelBatchTemplate]
    )
    await User.find_all().delete()
    await Department.find_all().delete()
    await AdmissionBatch.find_all().delete()
    await DocumentConfigurationVersion.find_all().delete()
    await StudentSubmission.find_all().delete()
    await ExcelBatchTemplate.find_all().delete()
    
    yield
    
    await test_client.drop_database("automate_test_db")
    test_client.close()


@pytest_asyncio.fixture
async def client_async():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_extract_logging_pipeline_development(client_async: AsyncClient, capsys):
    # Set APP_ENV to development
    original_env = settings.APP_ENV
    settings.APP_ENV = "development"
    
    try:
        # Create a mock batch in DB
        batch = AdmissionBatch(
            id="test-batch-id",
            name="Test Batch",
            department_id="DEPT1",
            academic_year="2027-2028",
            status="active",
            created_by="test-user"
        )
        await batch.insert()
        
        # Create a mock doc config version for the batch
        doc_config = DocumentConfigurationVersion(
            batch_id=str(batch.id),
            version=1,
            documents=[
                DocumentRequirementItem(id="doc-1", name="Aadhaar Card", required=True, allowed_types=["pdf"], max_size_mb=5, type="aadhaar"),
                DocumentRequirementItem(id="doc-2", name="Birth Certificate", required=True, allowed_types=["pdf"], max_size_mb=5, type="dob")
            ]
        )
        await doc_config.insert()

        # Call /student-submissions/extract endpoint
        files = [
            ("files", ("test.pdf", b"pdf content", "application/pdf"))
        ]
        data = {
            "batch_id": str(batch.id),
            "register_number": "REG123",
            "student_name": "John Doe"
        }
        
        response = await client_async.post(
            "/student-submissions/extract",
            data=data,
            files=files
        )
        
        assert response.status_code == 200
        
        # Capture stdout
        captured = capsys.readouterr()
        stdout_output = captured.out
        
        # Verify Step 10 logging sections are printed
        assert "UPLOADED FILES" in stdout_output
        assert "REQUIRED EXCEL COLUMNS" in stdout_output
        assert "DETECTED DOCUMENT TYPES" in stdout_output
        assert "MERGED JSON" in stdout_output
        assert "ALIAS MAPPING" in stdout_output
        assert "FINAL RESPONSE" in stdout_output

        # Verify sequential order:
        up_idx = stdout_output.index("UPLOADED FILES")
        col_idx = stdout_output.index("REQUIRED EXCEL COLUMNS")
        det_idx = stdout_output.index("DETECTED DOCUMENT TYPES")
        final_idx = stdout_output.index("FINAL RESPONSE")

        assert up_idx < col_idx < det_idx < final_idx
        
    finally:
        settings.APP_ENV = original_env


@pytest.mark.asyncio
async def test_extract_logging_pipeline_production(client_async: AsyncClient, capsys):
    # Set APP_ENV to production
    original_env = settings.APP_ENV
    settings.APP_ENV = "production"
    
    try:
        # Create a mock batch in DB
        batch = AdmissionBatch(
            id="test-batch-id-production",
            name="Test Batch Production",
            department_id="DEPT2",
            academic_year="2027-2028",
            status="active",
            created_by="test-user"
        )
        await batch.insert()
        
        # Create a mock doc config version for the batch
        doc_config = DocumentConfigurationVersion(
            batch_id=str(batch.id),
            version=1,
            documents=[
                DocumentRequirementItem(id="doc-1", name="Aadhaar Card", required=True, allowed_types=["pdf"], max_size_mb=5, type="aadhaar")
            ]
        )
        await doc_config.insert()

        # Call /student-submissions/extract endpoint
        files = [
            ("files", ("test.pdf", b"pdf content", "application/pdf"))
        ]
        data = {
            "batch_id": str(batch.id),
            "register_number": "REG456",
            "student_name": "Jane Doe"
        }
        
        response = await client_async.post(
            "/student-submissions/extract",
            data=data,
            files=files
        )
        
        assert response.status_code == 200
        
        # Capture stdout
        captured = capsys.readouterr()
        stdout_output = captured.out
        
        # In production mode, we should not have any of these debug logs
        assert "OCR TEXT" not in stdout_output
        assert "AI PROMPT" not in stdout_output
        assert "AI RESPONSE" not in stdout_output
        assert "FINAL JSON" not in stdout_output
        
    finally:
        settings.APP_ENV = original_env


def test_filter_extracted_data_by_excel_headers():
    from app.utils.field_canonicalizer import filter_extracted_data_by_excel_headers

    excel_headers = [
        "Student Name",
        "Register Number",
        "Mobile Number",
        "Aadhaar Number",
        "Community Category",
        "Income",
    ]

    extracted_raw = {
        "Student Name": {"value": "John Doe", "confidence": 100},
        "Register Number": {"value": "24AM101", "confidence": 100},
        "Mobile Number": {"value": "9876543210", "confidence": 100},
        "Aadhaar Card": {"value": "1234 5678 9012", "confidence": 95},
        "Community Code": {"value": "BC", "confidence": 100},
        "Community Name": {"value": "24 Manai Telugu Chetty", "confidence": 100},
        "Community Category": {"value": "Backward Class", "confidence": 100},
        "DOB": {"value": "01/01/2000", "confidence": 90},
        "Gender": {"value": "Male", "confidence": 90},
    }

    filtered = filter_extracted_data_by_excel_headers(extracted_raw, excel_headers)

    # 1. Document extraction results contain ONLY document fields (Profile fields Student Name, Register Number, Mobile Number excluded)
    assert set(filtered.keys()) == {"Aadhaar Number", "Community Category", "Income"}

    # 2. Matched document values
    assert filtered["Aadhaar Number"]["value"] == "1234 5678 9012"
    assert filtered["Community Category"]["value"] == "Backward Class"

    # 3. Unextracted document Excel column should be initialized with null/0
    assert filtered["Income"]["value"] is None
    assert filtered["Income"]["confidence"] == 0

    # 4. Profile fields and unlisted AI fields must NOT be in document extraction results
    assert "Student Name" not in filtered
    assert "Register Number" not in filtered
    assert "Mobile Number" not in filtered
    assert "Community Code" not in filtered
    assert "Community Name" not in filtered
    assert "DOB" not in filtered
    assert "Gender" not in filtered


def test_alias_based_excel_field_mapping():
    from app.utils.field_canonicalizer import filter_extracted_data_by_excel_headers

    excel_headers = ["Community", "Aadhaar Number", "Annual Income"]

    extracted_raw = {
        "Community Category": {"value": "Backward Class", "confidence": 100},
        "Community Code": {"value": "BC", "confidence": 100},
        "Community Name": {"value": "24 Manai Telugu Chetty", "confidence": 100},
        "Aadhaar Card": {"value": "4152 6075 0523", "confidence": 95},
        "Income": {"value": "150000", "confidence": 90},
    }

    filtered = filter_extracted_data_by_excel_headers(extracted_raw, excel_headers)

    # 1. Alias priority matching: "Community Category" preferred over "Community Code"
    assert filtered["Community"] == {
        "value": "Backward Class",
        "confidence": 100,
    }

    # 2. Aadhaar Card alias matched to Aadhaar Number
    assert filtered["Aadhaar Number"] == {
        "value": "4152 6075 0523",
        "confidence": 95,
    }

    # 3. Income alias matched to Annual Income
    assert filtered["Annual Income"] == {
        "value": "150000",
        "confidence": 90,
    }


def test_tc_classified_as_tc_not_community():
    from app.services.document_classifier_service import DocumentClassifierService

    classifier = DocumentClassifierService()
    ocr_tc_refer_community = (
        "TRANSFER CERTIFICATE\n"
        "Admission No: 4892\n"
        "EMIS ID: 220918239012\n"
        "Name of School: Govt Higher Secondary School\n"
        "Community: Refer Community Certificate\n"
        "Reason for leaving: Completed Course\n"
    )

    res = classifier.classify(ocr_tc_refer_community, filename="tc_student.pdf")
    assert res["success"] is True
    assert res["document_type"] == "TRANSFER_CERTIFICATE"


@pytest.mark.asyncio
async def test_dynamic_extraction_fields_from_doc_config(setup_test_db):
    from app.services.doc_config_version_service import DocConfigVersionService
    from app.schemas.doc_config_version import DocRequirementSchema

    doc_service = DocConfigVersionService()
    batch_id = "batch_test_dynamic_fields"

    # Create new configuration with custom documents (Transfer Certificate & Migration Certificate)
    documents = [
        DocRequirementSchema(
            id="req_tc",
            name="Transfer Certificate",
            required=True,
            extraction_fields=["Transfer Certificate Number", "School Name", "Admission Number", "Issue Date", "Leaving Date"],
        ),
        DocRequirementSchema(
            id="req_migration",
            name="Migration Certificate",
            required=False,
            extraction_fields=["Migration Number", "University", "Year"],
        ),
    ]

    await doc_service.create_new_version(
        batch_id=batch_id,
        documents=documents,
        change_summary="Added Migration & Transfer Certificate",
    )

    fields = await doc_service.get_batch_extraction_fields(batch_id)

    assert "Transfer Certificate Number" in fields
    assert "School Name" in fields
    assert "Admission Number" in fields
    assert "Issue Date" in fields
    assert "Leaving Date" in fields
    assert "Migration Number" in fields
    assert "University" in fields
    assert "Year" in fields


def test_address_extraction_exact_alignment():
    from app.services.ocr_preprocessor import OCRPreprocessor

    preprocessor = OCRPreprocessor()

    ocr_sample = (
        "Address:\n"
        "3/331,\n"
        "Srinivasa Nagar,\n"
        "Pattanam,\n"
        "VTC: Pattanam,\n"
        "PO: Pattanam,\n"
        "District: Coimbatore,\n"
        "State: Tamil Nadu,\n"
        "PIN Code: 641016\n"
    )

    result = preprocessor.extract_address_from_ocr(ocr_sample)
    assert result is not None
    assert result["value"] == "3/331, Srinivasa Nagar, Pattanam, VTC: Pattanam, PO: Pattanam, District: Coimbatore, State: Tamil Nadu - 641016"
    assert result["confidence"] == 100

    # Test null when no address is present
    no_address_ocr = "Government of India\nUnique Identification Authority of India\nJohn Doe\n"
    assert preprocessor.extract_address_from_ocr(no_address_ocr) is None


def test_aadhaar_only_address_rule():
    from app.utils.field_canonicalizer import is_address_field

    assert is_address_field("Address") is True
    assert is_address_field("Full Address") is True
    assert is_address_field("Permanent Address") is True
    assert is_address_field("Postal Address") is True
    assert is_address_field("Community") is False
    assert is_address_field("Aadhaar Number") is False


import pytest
import pytest_asyncio
from typing import Any, cast
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.models.user import User
from app.models.department import Department
from app.models.batch import AdmissionBatch
from app.models.batch_class import BatchClass
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
    app.db.database._is_connected = True

    await init_beanie(
        database=cast(Any, test_db),
        document_models=[User, Department, AdmissionBatch, BatchClass, DocumentConfigurationVersion, StudentSubmission, ExcelBatchTemplate]
    )
    await User.find_all().delete()
    await Department.find_all().delete()
    await AdmissionBatch.find_all().delete()
    await BatchClass.find_all().delete()
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
            batch_id=batch.id,
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
            "batch_id": batch.id,
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
            batch_id=batch.id,
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
            "batch_id": batch.id,
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

    # 3. Unextracted document Excel column should be initialized with NO / confidence 0
    assert filtered["Income"]["value"] == "NO"
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


def test_strict_source_document_rules():
    from app.utils.field_canonicalizer import (
        get_allowed_sources_for_field,
        is_document_authorized_for_field,
        ADDRESS_SOURCE_PRIORITY,
    )


    assert get_allowed_sources_for_field("Address") == ADDRESS_SOURCE_PRIORITY
    assert get_allowed_sources_for_field("Community Category") == ["COMMUNITY"]
    assert get_allowed_sources_for_field("Transfer Certificate Number") == ["TRANSFER_CERTIFICATE"]
    assert get_allowed_sources_for_field("Annual Family Income") == ["INCOME"]

    # Cross-document checks for non-address fields MUST return False
    assert is_document_authorized_for_field("AADHAAR", "Community Category") is False
    assert is_document_authorized_for_field("TRANSFER_CERTIFICATE", "Annual Family Income") is False
    assert is_document_authorized_for_field("UNKNOWN", "Address") is False

    # Allowed document checks MUST return True
    assert is_document_authorized_for_field("AADHAAR", "Address") is True
    assert is_document_authorized_for_field("COMMUNITY", "Address") is True

    assert is_document_authorized_for_field("COMMUNITY", "Community Category") is True
    assert is_document_authorized_for_field("TRANSFER_CERTIFICATE", "Transfer Certificate Number") is True
    assert is_document_authorized_for_field("INCOME", "Annual Family Income") is True


def test_excel_writer_sanitizes_placeholders():
    from app.services.excel_template_service import ExcelTemplateService

    service = ExcelTemplateService()
    test_data = {
        "Address": "Not detected",
        "Community Category": "N/A",
        "EMIS ID": None,
        "Aadhaar Number": "4152 6075 0523",
    }

    assert service._resolve_header_value("Address", test_data) is None
    assert service._resolve_header_value("Community Category", test_data) is None
    assert service._resolve_header_value("EMIS ID", test_data) is None
    assert service._resolve_header_value("Aadhaar Number", test_data) == "4152 6075 0523"


def test_boolean_field_and_expanded_source_rules():
    from app.utils.field_canonicalizer import (
        is_address_field,
        get_allowed_sources_for_field,
        is_document_authorized_for_field,
    )

    # Question fields must not be treated as address text fields
    assert is_address_field("Communication address same as permanent address") is False
    assert is_address_field("Permanent Address") is True

    # Extended source rules support for personal & location fields
    assert "AADHAAR" in get_allowed_sources_for_field("Gender")
    assert "AADHAAR" in get_allowed_sources_for_field("Father's Name")
    assert "AADHAAR" in get_allowed_sources_for_field("State")
    assert "AADHAAR" in get_allowed_sources_for_field("District")
    assert "AADHAAR" in get_allowed_sources_for_field("Taluk")
    assert "AADHAAR" in get_allowed_sources_for_field("Village")
    assert "AADHAAR" in get_allowed_sources_for_field("Country")

    from app.utils.field_canonicalizer import (
        is_yes_no_question_field,
        normalize_yes_no_value,
    )

    assert is_yes_no_question_field("Orphan Category (Yes/No)") is True
    assert is_yes_no_question_field("Is EMIS ID Available") is True
    assert is_yes_no_question_field("Is the student the first graduate in the family?") is True
    assert is_yes_no_question_field("Did you come under any special admission Quota?") is True
    assert is_yes_no_question_field("Did you belong to differently abled category?") is True

    assert normalize_yes_no_value("Yes") == "Yes"
    assert normalize_yes_no_value("true") == "Yes"
    assert normalize_yes_no_value("AVAILABLE") == "Yes"
    assert normalize_yes_no_value("No") == "No"
    assert normalize_yes_no_value("false") == "No"
    assert normalize_yes_no_value("not detected") is None


def test_optional_document_rules():
    from app.utils.field_canonicalizer import (
        is_optional_requirement,
        get_doc_type_for_requirement,
        is_field_belonging_to_optional_doc,
    )
    from app.models.doc_config_version import DocumentRequirementItem

    opt_item = DocumentRequirementItem(
        id="req_income",
        name="Income Certificate",
        required=False,
        type="OPTIONAL",
        extraction_fields=["Annual Income", "Income Certificate Number"],
    )

    req_item = DocumentRequirementItem(
        id="req_sslc",
        name="SSLC Marksheet",
        required=True,
        type="MANDATORY",
        extraction_fields=["SSLC Mark Percentage"],
    )

    doc_requirements = [opt_item, req_item]

    assert is_optional_requirement(opt_item) is True
    assert is_optional_requirement(req_item) is False

    assert get_doc_type_for_requirement("Income Certificate") == "INCOME"
    assert get_doc_type_for_requirement("Aadhaar Card") == "AADHAAR"

    is_opt, doc_type = is_field_belonging_to_optional_doc("Annual Income", doc_requirements)
    assert is_opt is True
    assert doc_type == "INCOME"

    is_opt_req, req_doc_type = is_field_belonging_to_optional_doc("SSLC Mark Percentage", doc_requirements)
    assert is_opt_req is False


def test_excel_writer_handles_optional_no_and_missing_null():
    from app.services.excel_template_service import ExcelTemplateService

    service = ExcelTemplateService()
    test_data = {
        "Annual Income": {"value": "No", "confidence": 0},
        "Income Certificate Number": "No",
        "SSLC Mark Percentage": {"value": None, "confidence": 0},
        "Aadhaar Number": "1234 5678 9012",
    }

    assert service._resolve_header_value("Annual Income", test_data) == "No"
    assert service._resolve_header_value("Income Certificate Number", test_data) == "No"
    assert service._resolve_header_value("SSLC Mark Percentage", test_data) is None
    assert service._resolve_header_value("Aadhaar Number", test_data) == "1234 5678 9012"


def test_aadhaar_address_location_parsing_and_isolation():
    from app.utils.field_canonicalizer import (
        parse_location_components_from_address,
        get_allowed_sources_for_field,
        ADDRESS_SOURCE_PRIORITY,
    )

    # 1. Test complete address parsing
    addr_str = "12 Gandhi Street, Kallupatti Village, Usilampatti Taluk, Madurai District, Tamil Nadu 625532"
    loc = parse_location_components_from_address(addr_str)

    assert loc["Village"]["value"] == "Kallupatti"
    assert loc["Taluk"]["value"] == "Usilampatti"
    assert loc["District"]["value"] == "Madurai"
    assert loc["State"]["value"] == "Tamil Nadu"
    assert loc["Pincode"]["value"] == "625532"

    # 2. Test address source priority order (Aadhaar is #1, followed by Residence, Nativity, Community, TC)
    assert ADDRESS_SOURCE_PRIORITY[0] == "AADHAAR"
    assert any(r in ADDRESS_SOURCE_PRIORITY for r in ["RESIDENCE", "RESIDENCE_CERTIFICATE"])
    assert "NATIVITY" in ADDRESS_SOURCE_PRIORITY
    assert "COMMUNITY" in ADDRESS_SOURCE_PRIORITY
    assert "TRANSFER_CERTIFICATE" in ADDRESS_SOURCE_PRIORITY

    for field in ["Address", "Village", "Taluk", "District", "State", "Pincode"]:
        sources = get_allowed_sources_for_field(field)
        assert sources == ADDRESS_SOURCE_PRIORITY

    # 3. Test PIN Code Lookup for unwritten Taluk
    example_addr = "3/331, Srinivasa Nagar, Pattanam, PO: Pattanam, District: Coimbatore, State: Tamil Nadu, PIN Code: 641016"
    res = parse_location_components_from_address(example_addr)

    assert res["Village"]["value"] == "Pattanam"
    assert res["Taluk"]["value"] == "Sulur"
    assert res["District"]["value"] == "Coimbatore"
    assert res["State"]["value"] == "Tamil Nadu"
    assert res["Pincode"]["value"] == "641016"


def test_emis_id_strict_extraction_rules():
    from app.utils.field_canonicalizer import (
        get_allowed_sources_for_field,
        is_document_authorized_for_field,
    )
    from app.services.ocr_preprocessor import OCRPreprocessor
    from app.services.ai_extraction_service import AIExtractionService

    # Rule 1 & 6: Search ONLY Transfer Certificate (TC) for EMIS ID
    allowed_sources = get_allowed_sources_for_field("EMIS ID")
    assert allowed_sources == ["TRANSFER_CERTIFICATE"]

    assert is_document_authorized_for_field("TRANSFER_CERTIFICATE", "EMIS ID") is True
    assert is_document_authorized_for_field("SSLC", "EMIS ID") is False
    assert is_document_authorized_for_field("HSC", "EMIS ID") is False
    assert is_document_authorized_for_field("AADHAAR", "EMIS ID") is False
    assert is_document_authorized_for_field("COMMUNITY", "EMIS ID") is False
    assert is_document_authorized_for_field("INCOME", "EMIS ID") is False

    # Regex Preprocessor Test for labeled EMIS ID
    preprocessor = OCRPreprocessor()
    tc_ocr = "TRANSFER CERTIFICATE\nSchool: Govt HR SEC School\nEMIS ID: 9876543210\nAdmission No: 54321\nUDISE Code: 33260100101"
    regex_res = preprocessor.extract_regex_fields(tc_ocr)
    assert "EMIS ID" in regex_res
    assert regex_res["EMIS ID"]["value"] == "9876543210"
    assert regex_res["EMIS ID"]["confidence"] == 100

    # Prompt generation test: special EMIS hint included
    ai_service = AIExtractionService()
    prompt = ai_service.build_prompt("TRANSFER_CERTIFICATE", tc_ocr, ["EMIS ID"])
    assert "SPECIAL EMIS ID EXTRACTION RULE" in prompt
    assert "Transfer Certificate (TC) ONLY" in prompt
    assert "Do NOT extract Admission Number" in prompt


def test_strict_non_hallucination_and_no_return_rules():
    from app.services.ai_extraction_service import AIExtractionService
    from app.utils.field_canonicalizer import parse_location_components_from_address

    ai_service = AIExtractionService()

    # 1. Prompt includes strict non-hallucination policy and NO return instructions
    prompt = ai_service.build_prompt("AADHAAR", "Name: Ramesh", ["Occupation", "EMIS ID"])
    assert "STRICT EXTRACTION POLICY & RULES" in prompt
    assert 'IF A REQUESTED FIELD IS NOT EXPLICITLY PRESENT OR FOUND IN THE DOCUMENT, YOU MUST RETURN:' in prompt
    assert '"value": "NO", "confidence": 0' in prompt
    assert "PRIORITIZE ACCURACY OVER COMPLETENESS" in prompt

    # 2. Validation of missing / empty / null / ungrounded fields returns {"value": "NO", "confidence": 0}
    raw_llm_json = '{"Occupation": {"value": null, "confidence": 0}, "EMIS ID": {"value": "NOT DETECTED", "confidence": 0}, "Caste": "N/A"}'
    validated = ai_service._validate_and_format_json(raw_llm_json, ["Occupation", "EMIS ID", "Caste", "Mother Name"])
    assert validated is not None

    assert validated["Occupation"] == {"value": "NO", "confidence": 0}
    assert validated["EMIS ID"] == {"value": "NO", "confidence": 0}
    assert validated["Caste"] == {"value": "NO", "confidence": 0}
    assert validated["Mother Name"] == {"value": "NO", "confidence": 0}

    # 3. Address location components missing return NO with confidence 0
    loc_res = parse_location_components_from_address("")
    assert loc_res["Village"] == {"value": "NO", "confidence": 0}
    assert loc_res["Taluk"] == {"value": "NO", "confidence": 0}
    assert loc_res["District"] == {"value": "NO", "confidence": 0}
    assert loc_res["State"] == {"value": "NO", "confidence": 0}
    assert loc_res["Pincode"] == {"value": "NO", "confidence": 0}


@pytest.mark.asyncio
async def test_common_batch_level_document_configuration(setup_test_db):
    from app.services.doc_config_version_service import DocConfigVersionService
    from app.models.batch_class import BatchClass

    doc_service = DocConfigVersionService()
    batch_id = "batch_aiml_2025_2029"

    # 1. Fetching doc config for batch returns shared Version 1
    v1 = await doc_service.get_or_create_current_version(batch_id)
    assert v1.batch_id == batch_id
    assert v1.version == 1
    assert v1.is_current is True

    # 2. Sections/Classes under this batch inherit the same shared doc config
    class_a = BatchClass(id="class_sec_a", batch_id=batch_id, class_name="Section A", department="AIML", section="A", academic_year="2025-2029")
    await class_a.insert()

    class_b = BatchClass(id="class_sec_b", batch_id=batch_id, class_name="Section B", department="AIML", section="B", academic_year="2025-2029")
    await class_b.insert()

    doc_a = await doc_service.get_or_create_current_version(class_a.batch_id)
    doc_b = await doc_service.get_or_create_current_version(class_b.batch_id)

    assert doc_a.id == doc_b.id == v1.id

    # 3. Editing batch doc config updates the shared config for all sections in the batch
    from app.schemas.doc_config_version import DocRequirementSchema
    updated_docs = [
        DocRequirementSchema(id="req_1", name="Aadhaar Card", required=True, type="MANDATORY", allowed_types=["PDF"]),
        DocRequirementSchema(id="req_2", name="Community Certificate", required=True, type="MANDATORY", allowed_types=["PDF"]),
        DocRequirementSchema(id="req_3", name="First Graduate Certificate", required=False, type="OPTIONAL", allowed_types=["PDF"]),
    ]
    v2 = await doc_service.create_new_version(batch_id=batch_id, documents=updated_docs, change_summary="Added First Graduate")
    assert v2.version == 2

    active_config = await doc_service.get_or_create_current_version(batch_id)
    assert active_config.version == 2
    assert len(active_config.documents) == 3
    assert active_config.documents[2].name == "First Graduate Certificate"


def test_gender_inference_from_salutation_and_logging_rules():
    from app.utils.field_canonicalizer import infer_gender_from_salutation

    # 1. Mr. / Master -> Male with confidence 95, source Salutation
    res_mr = infer_gender_from_salutation(salutation_val="Mr. Ramesh")
    assert res_mr is not None
    assert res_mr["value"] == "Male"
    assert res_mr["confidence"] == 95
    assert res_mr["source"] == "Salutation"
    assert res_mr["rule_applied"] == "Mr. -> Male"

    res_master = infer_gender_from_salutation(salutation_val="Master Suresh")
    assert res_master is not None
    assert res_master["value"] == "Male"
    assert res_master["confidence"] == 95
    assert res_master["source"] == "Salutation"
    assert res_master["rule_applied"] == "Master -> Male"

    # 2. Mrs. / Ms. / Miss -> Female with confidence 95, source Salutation
    res_mrs = infer_gender_from_salutation(salutation_val="Mrs. Kavitha")
    assert res_mrs is not None
    assert res_mrs["value"] == "Female"
    assert res_mrs["confidence"] == 95
    assert res_mrs["source"] == "Salutation"
    assert res_mrs["rule_applied"] == "Mrs. -> Female"

    res_ms = infer_gender_from_salutation(salutation_val="Ms. Priya")
    assert res_ms is not None
    assert res_ms["value"] == "Female"
    assert res_ms["confidence"] == 95

    res_miss = infer_gender_from_salutation(salutation_val="Miss Ananya")
    assert res_miss is not None
    assert res_miss["value"] == "Female"
    assert res_miss["confidence"] == 95

    # 3. Ambiguous titles (Dr., Prof., Rev., Er., Shri, Smt.) -> MUST NOT infer, return None
    assert infer_gender_from_salutation(salutation_val="Dr. Rajesh") is None
    assert infer_gender_from_salutation(salutation_val="Prof. Suresh") is None
    assert infer_gender_from_salutation(salutation_val="Rev. Father") is None
    assert infer_gender_from_salutation(salutation_val="Er. Anand") is None
    assert infer_gender_from_salutation(salutation_val="Shri Kumar") is None

    # 4. Name alone without title -> MUST NOT infer, return None
    assert infer_gender_from_salutation(name_val="Ramesh Kumar") is None
    assert infer_gender_from_salutation(name_val="Priya Dharshini") is None


def test_smart_lookup_engine_architecture_and_providers():
    from app.services.smart_lookup_service import SmartLookupEngine

    engine = SmartLookupEngine()

    initial_fields = {
        "Student Name": {"value": "Ramesh Kumar", "confidence": 100},
        "Gender": {"value": "NO", "confidence": 0},
        "Pincode": {"value": "641016", "confidence": 100},
        "Taluk": {"value": "NO", "confidence": 0},
        "District": {"value": "NO", "confidence": 0},
        "State": {"value": "NO", "confidence": 0},
        "Blood Group": {"value": "NO", "confidence": 0},
        "EMIS ID": {"value": "NO", "confidence": 0},
    }

    all_extracted = {
        "Salutation": {"value": "Mr.", "confidence": 100},
        "Pincode": {"value": "641016", "confidence": 100},
        "Address": {"value": "3/331, Pattanam, Coimbatore, Tamil Nadu - 641016", "confidence": 100},
    }

    detected_docs = ["AADHAAR"]

    processed = engine.process_lookup(
        verification_fields=initial_fields,
        all_extracted_pool=all_extracted,
        detected_documents=detected_docs,
    )

    # 1. PIN Lookup Provider derived location sub-fields with source "PIN Lookup" / "Address Parsing"
    assert processed["Taluk"]["value"] == "Sulur"
    assert processed["Taluk"]["confidence"] >= 90
    assert processed["Taluk"]["source"] in ["PIN Lookup", "Address Parsing"]

    assert processed["District"]["value"] == "Coimbatore"
    assert processed["District"]["confidence"] >= 90

    assert processed["State"]["value"] == "Tamil Nadu"
    assert processed["State"]["confidence"] >= 90

    # 2. Salutation Provider derived Gender with source "Salutation Rule"
    assert processed["Gender"]["value"] == "Male"
    assert processed["Gender"]["confidence"] == 95
    assert processed["Gender"]["source"] == "Salutation Rule"

    # 3. Strict No-Inference Guard for Blood Group returns "NO" with confidence 0 and source "Not Found"
    assert processed["Blood Group"]["value"] == "NO"
    assert processed["Blood Group"]["confidence"] == 0
    assert processed["Blood Group"]["source"] == "Not Found"

    # 4. Strict Guard for EMIS ID (not in TC) returns "NO" with confidence 0 and source "Not Found"
    assert processed["EMIS ID"]["value"] == "NO"
    assert processed["EMIS ID"]["confidence"] == 0
    assert processed["EMIS ID"]["source"] == "Not Found"


def test_ifsc_code_extraction_and_canonicalization():
    from app.services.ocr_preprocessor import OCRPreprocessor
    from app.utils.field_canonicalizer import filter_extracted_data_by_excel_headers, get_canonical_field_name

    # 1. Canonical field mapping test
    assert get_canonical_field_name("ifsc") == "IFSC Code"
    assert get_canonical_field_name("ifsc code") == "IFSC Code"
    assert get_canonical_field_name("ifsc_code") == "IFSC Code"
    assert get_canonical_field_name("bank name") == "Bank Name"

    # 2. Regex preprocessor extraction test for IFSC code
    preprocessor = OCRPreprocessor()
    bank_ocr = "Bank Passbook\nState Bank of India\nBranch: Main Branch\nIFSC Code: SBIN0001234\nA/c No: 123456789012"
    regex_res = preprocessor.extract_regex_fields(bank_ocr)

    assert "IFSC Code" in regex_res
    assert regex_res["IFSC Code"]["value"] == "SBIN0001234"
    assert regex_res["IFSC Code"]["confidence"] == 100

    # 3. Filtering by Excel template headers test
    excel_headers = ["IFSC CODE", "Bank Name", "Aadhaar Number"]
    extracted_raw = {
        "IFSC Code": {"value": "SBIN0001234", "confidence": 100},
        "Aadhaar Card": {"value": "1234 5678 9012", "confidence": 95},
    }
    filtered = filter_extracted_data_by_excel_headers(extracted_raw, excel_headers)

    assert filtered["IFSC CODE"]["value"] == "SBIN0001234"
    assert filtered["IFSC CODE"]["confidence"] == 100
    assert filtered["Bank Name"]["value"] == "NO"
    assert filtered["Bank Name"]["confidence"] == 0











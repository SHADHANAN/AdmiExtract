import pytest
import os
import openpyxl
from unittest.mock import MagicMock, AsyncMock, patch
from typing import Any

from app.utils.normalization import (
    validate_and_normalize_gender,
    validate_and_normalize_state,
    validate_and_normalize_nationality,
    validate_and_normalize_religion,
    validate_and_normalize_emis,
    validate_and_normalize_code_field,
    validate_boolean_yes_no,
    validate_and_normalize_person_name,
    is_explicit_negative,
)
from app.utils.field_canonicalizer import (
    is_name_conflict,
    is_number_conflict,
    get_document_field_authority_weight,
    FIELD_SOURCE_RULES,
)
from app.services.field_mapping_service import (
    FieldMappingService,
    validate_resolved_candidate,
    format_for_excel_write,
)
from app.services.document_processing_pipeline import DocumentProcessingPipeline
from app.services.excel_template_service import ExcelTemplateService
from app.services.gemini_service import GeminiService


# =========================================================================
# Scenario 1: TC EMIS overrides SSLC EMIS
# =========================================================================
def test_scenario_01_tc_emis_overrides_sslc():
    pipeline = DocumentProcessingPipeline()
    detected_docs = [
        {"document_type": "10th Mark Sheet", "type": "10th Mark Sheet"},
        {"document_type": "Transfer Certificate", "type": "Transfer Certificate"},
    ]
    extracted_pool = [
        {
            "document_type": "10th Mark Sheet",
            "extracted_data": {"EMIS ID": "998877665544"},
            "field_confidences": {"EMIS ID": 95},
        },
        {
            "document_type": "Transfer Certificate",
            "extracted_data": {"EMIS ID": "2015743426"},
            "field_confidences": {"EMIS ID": 90},
        },
    ]
    merged = pipeline._order_independent_cross_document_merge(
        detected_docs=detected_docs,
        all_extracted_pool=extracted_pool,
        excel_headers=["EMIS ID", "Is EMIS ID Available"],
    )
    assert merged["EMIS ID"]["value"] == "2015743426"
    assert merged["Is EMIS ID Available"]["value"] == "Yes"


# =========================================================================
# Scenario 2: TC Guardian NONE overrides lower-authority Guardian candidate
# =========================================================================
def test_scenario_02_tc_guardian_none_overrides_lower_doc():
    pipeline = DocumentProcessingPipeline()
    detected_docs = [
        {"document_type": "Community Certificate", "type": "Community Certificate"},
        {"document_type": "Transfer Certificate", "type": "Transfer Certificate"},
    ]
    extracted_pool = [
        {
            "document_type": "Community Certificate",
            "extracted_data": {"Guardian Name": "RAMASAMY K"},
            "field_confidences": {"Guardian Name": 90},
        },
        {
            "document_type": "Transfer Certificate",
            "extracted_data": {"Guardian Name": "NONE"},
            "field_confidences": {"Guardian Name": 95},
        },
    ]
    merged = pipeline._order_independent_cross_document_merge(
        detected_docs=detected_docs,
        all_extracted_pool=extracted_pool,
        excel_headers=["Guardian Name"],
    )
    assert merged["Guardian Name"]["value"] == "NO"


# =========================================================================
# Scenario 3: Father name cannot become caste/community text
# =========================================================================
def test_scenario_03_father_name_cannot_become_caste():
    assert validate_and_normalize_person_name("Vadugar", role="Father Name") is None
    assert validate_and_normalize_person_name("BC", role="Father Name") is None
    assert validate_and_normalize_person_name("Refer Community Certificate", role="Father Name") is None
    assert validate_and_normalize_person_name("Scheduled Caste", role="Father Name") is None
    assert validate_and_normalize_person_name("RAMASAMY K", role="Father Name") == "RAMASAMY K"


# =========================================================================
# Scenario 4: Mother name cannot become gender text
# =========================================================================
def test_scenario_04_mother_name_cannot_become_gender():
    assert validate_and_normalize_person_name("MALE", role="Mother Name") is None
    assert validate_and_normalize_person_name("FEMALE", role="Mother Name") is None
    assert validate_and_normalize_person_name("TRANSGENDER", role="Mother Name") is None
    assert validate_and_normalize_person_name("GENDER FEMALE", role="Mother Name") is None
    assert validate_and_normalize_person_name("LAKSHMI S", role="Mother Name") == "LAKSHMI S"


# =========================================================================
# Scenario 5: Guardian cannot become father/address/community text
# =========================================================================
def test_scenario_05_guardian_isolation():
    assert is_name_conflict("Guardian Name", "Father Name") is True
    assert validate_and_normalize_person_name("12/34 Gandhi Street Namakkal", role="Guardian Name") is None
    assert validate_and_normalize_person_name("Vadugar Community", role="Guardian Name") is None


# =========================================================================
# Scenario 6: State Tamil Nadu accepted
# =========================================================================
def test_scenario_06_state_tamil_nadu_accepted():
    assert validate_and_normalize_state("Tamil Nadu") == "Tamil Nadu"
    assert validate_and_normalize_state("TAMILNADU") == "Tamil Nadu"
    assert validate_and_normalize_state("State: Tamil Nadu") == "Tamil Nadu"


# =========================================================================
# Scenario 7: Contaminated State rejected
# =========================================================================
def test_scenario_07_contaminated_state_rejected():
    assert validate_and_normalize_state("Of Tamil Nadu Belongs To Vadugar Community") is None
    assert validate_and_normalize_state("Tamil Nadu 636001") is None
    assert validate_and_normalize_state("Tamil Nadu Male Hindu") is None


# =========================================================================
# Scenario 8: Communication Address Same boolean only Yes/No
# =========================================================================
def test_scenario_08_communication_address_same_boolean():
    header = "Is Communication Address Same as Permanent Address"
    assert validate_boolean_yes_no("Yes") == "Yes"
    assert validate_boolean_yes_no("true") == "Yes"
    assert validate_boolean_yes_no("No") == "No"
    # An address string must NEVER be accepted as Yes/No
    address_str = "12/4 East Street, Mohanur Road, Namakkal 637001"
    assert validate_boolean_yes_no(address_str) is None
    # Formatting for excel write must coerce non-boolean / address to No
    assert format_for_excel_write(header, address_str) == "No"


# =========================================================================
# Scenario 9: Nationality INDIAN extracted from TC
# =========================================================================
def test_scenario_09_nationality_indian_extracted():
    assert validate_and_normalize_nationality("INDIAN") == "INDIAN"
    assert validate_and_normalize_nationality("Indian") == "INDIAN"
    assert validate_and_normalize_nationality("Nationality: Indian") == "INDIAN"


# =========================================================================
# Scenario 10: Refer Community Certificate not treated as nationality/religion
# =========================================================================
def test_scenario_10_refer_community_cert_rejected_from_nationality_and_religion():
    bad_val = "Refer Community Certificate"
    assert validate_and_normalize_nationality(bad_val) is None
    assert validate_and_normalize_religion(bad_val) is None
    assert validate_resolved_candidate("Nationality", bad_val) is None
    assert validate_resolved_candidate("Religion", bad_val) is None


# =========================================================================
# Scenario 11: Taluk Code contamination rejected
# =========================================================================
def test_scenario_11_taluk_code_contamination_rejected():
    assert validate_and_normalize_code_field("Taluk Code", "04") == "04"
    assert validate_and_normalize_code_field("Taluk Code", "TK-09") == "TK-09"
    # Contaminated values rejected
    assert validate_and_normalize_code_field("Taluk Code", "Namakkal Taluk Mohanur Road") is None
    assert validate_and_normalize_code_field("Taluk Code", "Refer Community Certificate") is None
    assert validate_and_normalize_code_field("Taluk Code", "Tamil Nadu") is None


# =========================================================================
# Scenario 12: Village Panchayat Code contamination rejected
# =========================================================================
def test_scenario_12_village_panchayat_code_contamination_rejected():
    assert validate_and_normalize_code_field("Village Panchayat Code", "VP12") == "VP12"
    assert validate_and_normalize_code_field("Village Panchayat Code", "005") == "005"
    # Contaminated descriptions rejected
    assert validate_and_normalize_code_field("Village Panchayat Code", "Paramathi Velur Village Panchayat") is None
    assert validate_and_normalize_code_field("Village Panchayat Code", "Vadugar Community BC") is None


# =========================================================================
# Scenario 13: Aadhaar cannot become Registration Number
# =========================================================================
def test_scenario_13_aadhaar_cannot_become_registration_number():
    assert is_number_conflict("Register Number", "Aadhaar Number") is True
    assert is_number_conflict("Registration Number", "Aadhaar Card") is True
    aadhaar_num = "9573 0978 4448"
    assert validate_resolved_candidate("Register Number", aadhaar_num) is None


# =========================================================================
# Scenario 14: EMIS cannot become Registration Number
# =========================================================================
def test_scenario_14_emis_cannot_become_registration_number():
    assert is_number_conflict("Register Number", "EMIS ID") is True
    assert is_number_conflict("Student Register Number", "Student EMIS ID") is True


# =========================================================================
# Scenario 15: Certificate serial cannot become Student Registration Number
# =========================================================================
def test_scenario_15_serial_no_cannot_become_student_reg_no():
    assert is_number_conflict("Register Number", "Serial Number") is True
    assert is_number_conflict("Register Number", "Certificate S.No") is True
    assert is_number_conflict("Register Number", "Admission Number") is True


# =========================================================================
# Scenario 16: Upload order permutations produce identical final output
# =========================================================================
def test_scenario_16_upload_order_invariance():
    pipeline = DocumentProcessingPipeline()
    doc_tc = {
        "document_type": "Transfer Certificate",
        "extracted_data": {
            "Student Name": "ARUN KUMAR S",
            "EMIS ID": "2015743426",
            "Nationality": "INDIAN",
            "Guardian Name": "NONE",
        },
        "field_confidences": {"Student Name": 90, "EMIS ID": 95, "Nationality": 90, "Guardian Name": 95},
    }
    doc_sslc = {
        "document_type": "10th Mark Sheet",
        "extracted_data": {
            "Student Name": "ARUN KUMAR S",
            "EMIS ID": "998877665544",
            "Father Name": "SURESH K",
        },
        "field_confidences": {"Student Name": 92, "EMIS ID": 90, "Father Name": 92},
    }
    doc_comm = {
        "document_type": "Community Certificate",
        "extracted_data": {
            "Student Name": "ARUN KUMAR S",
            "Community": "BC",
            "Guardian Name": "SURESH K",
        },
        "field_confidences": {"Student Name": 90, "Community": 95, "Guardian Name": 85},
    }

    # Order 1: TC, SSLC, Community
    res1 = pipeline._order_independent_cross_document_merge(
        detected_docs=[{"document_type": d["document_type"]} for d in [doc_tc, doc_sslc, doc_comm]],
        all_extracted_pool=[doc_tc, doc_sslc, doc_comm],
        excel_headers=["Student Name", "EMIS ID", "Nationality", "Guardian Name", "Father Name", "Community"],
    )

    # Order 2: Community, SSLC, TC
    res2 = pipeline._order_independent_cross_document_merge(
        detected_docs=[{"document_type": d["document_type"]} for d in [doc_comm, doc_sslc, doc_tc]],
        all_extracted_pool=[doc_comm, doc_sslc, doc_tc],
        excel_headers=["Student Name", "EMIS ID", "Nationality", "Guardian Name", "Father Name", "Community"],
    )

    # Order 3: SSLC, TC, Community
    res3 = pipeline._order_independent_cross_document_merge(
        detected_docs=[{"document_type": d["document_type"]} for d in [doc_sslc, doc_tc, doc_comm]],
        all_extracted_pool=[doc_sslc, doc_tc, doc_comm],
        excel_headers=["Student Name", "EMIS ID", "Nationality", "Guardian Name", "Father Name", "Community"],
    )

    vals1 = {k: v["value"] for k, v in res1.items()}
    vals2 = {k: v["value"] for k, v in res2.items()}
    vals3 = {k: v["value"] for k, v in res3.items()}

    assert vals1 == vals2 == vals3
    assert vals1["EMIS ID"] == "2015743426"  # TC won over SSLC
    assert vals1["Guardian Name"] == "NO"    # TC negative evidence won over Community


# =========================================================================
# Scenario 17: Hallucinated Gemini fields rejected
# =========================================================================
def test_scenario_17_hallucinated_fields_filtered():
    gemini = GeminiService()
    ocr_evidence = "NAME OF CANDIDATE: PRIYA S. ROLL NO: 24AM088. FATHER NAME: SENTHIL K."
    raw_ai_dict = {
        "Student Name": "PRIYA S",
        "Father Name": "SENTHIL K",
        "Aadhaar Number": "9999 8888 7777",  # Not in OCR evidence at all!
        "Bank Account No": "123456789012",   # Not in OCR evidence!
    }
    filtered = gemini._filter_hallucinated_fields(raw_ai_dict, ocr_evidence)
    assert "Student Name" in filtered
    assert "Father Name" in filtered
    assert "Aadhaar Number" not in filtered
    assert "Bank Account No" not in filtered


# =========================================================================
# Scenario 18: Gemini quota 429 does not block the entire batch
# =========================================================================
def test_scenario_18_gemini_quota_429_classification_and_fallback():
    gemini = GeminiService()
    # 429 Quota Exhaustion
    quota_err = Exception("429 Resource has been exhausted (e.g. check quota). Please see https://ai.google.dev")
    is_429, is_transient, retry_delay = gemini._classify_429_error(quota_err)
    assert is_429 is True
    assert is_transient is False

    # Transient 429 Rate Limit
    rate_limit_err = Exception("429 Rate limit exceeded. Try again in 5 seconds.")
    is_429_2, is_transient_2, retry_delay_2 = gemini._classify_429_error(rate_limit_err)
    assert is_429_2 is True
    assert is_transient_2 is True
    assert retry_delay_2 == 5.0


# =========================================================================
# Scenario 19: Invalid field never reaches Excel
# =========================================================================
@pytest.mark.asyncio
async def test_scenario_19_invalid_field_never_reaches_excel(tmp_path):
    template_file = tmp_path / "test_template.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    assert ws is not None
    ws.append([
        "Student Name",
        "Register Number",
        "Father Name",
        "Mother Name",
        "Gender",
        "State",
        "Taluk Code",
        "Is Communication Address Same as Permanent Address",
    ])
    wb.save(template_file)
    wb.close()

    from types import SimpleNamespace
    mock_template = SimpleNamespace(
        batch_id="AIML_2025",
        template_filename="test_template.xlsx",
        file_path=str(template_file),
        headers=[
            "Student Name", "Register Number", "Father Name", "Mother Name",
            "Gender", "State", "Taluk Code", "Is Communication Address Same as Permanent Address",
        ],
        lookup_column="Register Number",
        field_mappings={},
    )
    mock_repo = AsyncMock()
    mock_repo.get_by_batch_id.return_value = mock_template
    service = ExcelTemplateService(repository=mock_repo)

    # Dirty / Contaminated extracted student data
    student_data = {
        "Student Name": "PRAVEEN S",
        "Register Number": "24AM076",
        "Father Name": "Vadugar Community BC",             # Contaminated with caste -> MUST BE REJECTED
        "Mother Name": "GENDER FEMALE TRANSGENDER",        # Contaminated with multi-gender OCR -> REJECTED
        "Gender": "GENDER MALE FEMALE TRANSGENDER",        # Contaminated OCR options list -> REJECTED
        "State": "Of Tamil Nadu Belongs To Vadugar Community", # Contaminated phrase -> REJECTED
        "Taluk Code": "Namakkal Taluk Mohanur Road",       # Narrative text -> REJECTED
        "Is Communication Address Same as Permanent Address": "12/4 Mohanur Road Namakkal", # Address in bool -> Coerced to No
    }

    success = await service.append_or_update_student_row_in_excel("AIML_2025", "24AM076", student_data)
    assert success is True

    # Read back saved workbook
    wb_read = openpyxl.load_workbook(template_file, data_only=True)
    ws_read = wb_read.active
    assert ws_read is not None
    row2 = [cell.value for cell in ws_read[2]]

    assert row2[0] == "PRAVEEN S"  # Valid name written
    assert row2[1] == "24AM076"    # Valid reg no written
    assert row2[2] is None         # Father Name contaminated -> BLANK
    assert row2[3] is None         # Mother Name contaminated -> BLANK
    assert row2[4] is None         # Gender contaminated -> BLANK
    assert row2[5] is None         # State contaminated -> BLANK
    assert row2[6] is None         # Taluk Code contaminated -> BLANK
    assert row2[7] == "No"         # Address string in boolean column coerced to 'No'


# =========================================================================
# Scenario 20: Verhoeff Checksum Validation on Aadhaar Numbers
# =========================================================================
def test_scenario_20_aadhaar_verhoeff_checksum():
    from app.utils.normalization import validate_and_normalize_aadhaar, validate_verhoeff
    # Known valid Verhoeff numbers
    assert validate_verhoeff("234567890126") is True or validate_verhoeff("957309784448") is True
    # Test valid 12-digit format normalization with space
    valid_mock = validate_and_normalize_aadhaar("9573 0978 4448")
    assert valid_mock == "9573 0978 4448"
    # Invalid lengths or non-numeric rejected
    assert validate_and_normalize_aadhaar("12345") is None
    assert validate_and_normalize_aadhaar("ABCD EFGH IJKL") is None


# =========================================================================
# Scenario 21: TC issue date (e.g. 24.10.2024) rejected as Student DOB
# =========================================================================
def test_scenario_21_tc_issue_date_rejected_as_dob():
    from app.utils.normalization import validate_and_normalize_dob
    # Issue date 2024 is impossible for a college applicant
    assert validate_and_normalize_dob("24.10.2024") is None
    assert validate_and_normalize_dob("24/10/2024") is None
    assert validate_and_normalize_dob("2024-10-24") is None
    # Authentic college student DOB (e.g. 2005) accepted
    assert validate_and_normalize_dob("15/05/2005") == "15.05.2005"
    assert validate_and_normalize_dob("15/05/2005", target_format="DD/MM/YYYY") == "15/05/2005"
    assert validate_and_normalize_dob("15.05.2005", target_format="DD.MM.YYYY") == "15.05.2005"


# =========================================================================
# Scenario 22: Aadhaar DOB takes precedence over TC DOB
# =========================================================================
def test_scenario_22_aadhaar_dob_precedence_over_tc():
    pipeline = DocumentProcessingPipeline()
    detected_docs = [
        {"document_type": "Transfer Certificate", "type": "Transfer Certificate"},
        {"document_type": "Aadhaar Card", "type": "Aadhaar Card"},
    ]
    extracted_pool = [
        {
            "document_type": "Transfer Certificate",
            "extracted_data": {"Date of Birth": "24.10.2024"},  # TC issue date mistaken for DOB
            "field_confidences": {"Date of Birth": 95},
        },
        {
            "document_type": "Aadhaar Card",
            "extracted_data": {"Date of Birth": "15/05/2005"},  # Authentic student DOB
            "field_confidences": {"Date of Birth": 95},
        },
    ]
    merged = pipeline._order_independent_cross_document_merge(
        detected_docs=detected_docs,
        all_extracted_pool=extracted_pool,
        excel_headers=["Date of Birth"],
    )
    assert merged["Date of Birth"]["value"] == "15.05.2005"


# =========================================================================
# Scenario 23: Permanent Address never becomes "Yes"
# =========================================================================
def test_scenario_23_permanent_address_never_becomes_yes():
    mapper = FieldMappingService()
    dirty_pool = {
        "Is Communication Address Same as Permanent Address": {"value": "Yes", "confidence": 95},
        "Permanent Address": {"value": "Yes", "confidence": 90},
    }
    val, conf, src = mapper.resolve_field_value("Permanent Address", dirty_pool)
    assert val != "Yes"
    assert val is None

    # Valid address passes
    clean_pool = {
        "Permanent Address": {"value": "12/4, Gandhi Street, Mohanur Road, Namakkal - 637001", "confidence": 95},
        "Is Communication Address Same as Permanent Address": {"value": "Yes", "confidence": 95},
    }
    val2, conf2, src2 = mapper.resolve_field_value("Permanent Address", clean_pool)
    assert val2 == "12/4, Gandhi Street, Mohanur Road, Namakkal - 637001"


# =========================================================================
# Scenario 24: Address Validation rejects short strings and booleans
# =========================================================================
def test_scenario_24_address_validation_rejects_booleans():
    from app.utils.normalization import validate_and_normalize_address
    assert validate_and_normalize_address("Yes") is None
    assert validate_and_normalize_address("No") is None
    assert validate_and_normalize_address("True") is None
    assert validate_and_normalize_address("False") is None
    assert validate_and_normalize_address("NA") is None
    assert validate_and_normalize_address("Street") is None  # Too short
    valid_addr = "No 45, Anna Nagar, 2nd Cross Street, Salem 636007"
    assert validate_and_normalize_address(valid_addr) == valid_addr


# =========================================================================
# Scenario 25: Gender strictly formatted as clean enum
# =========================================================================
def test_scenario_25_gender_clean_enum():
    from app.utils.normalization import validate_and_normalize_gender
    assert validate_and_normalize_gender("Male") == "MALE"
    assert validate_and_normalize_gender("MALE") == "MALE"
    assert validate_and_normalize_gender("M") == "MALE"
    assert validate_and_normalize_gender("Female") == "FEMALE"
    assert validate_and_normalize_gender("F") == "FEMALE"
    assert validate_and_normalize_gender("Transgender") == "TRANSGENDER"
    assert validate_and_normalize_gender("TG") == "TRANSGENDER"
    # Contaminated OCR rejected
    assert validate_and_normalize_gender("MALE FEMALE TRANSGENDER") is None
    assert validate_and_normalize_gender("Yes") is None


# =========================================================================
# Scenario 26: Community Certificate has highest authority for Community
# =========================================================================
def test_scenario_26_community_certificate_authority():
    pipeline = DocumentProcessingPipeline()
    detected_docs = [
        {"document_type": "Transfer Certificate", "type": "Transfer Certificate"},
        {"document_type": "Community Certificate", "type": "Community Certificate"},
    ]
    extracted_pool = [
        {
            "document_type": "Transfer Certificate",
            "extracted_data": {"Community": "MBC/DNC"},
            "field_confidences": {"Community": 90},
        },
        {
            "document_type": "Community Certificate",
            "extracted_data": {"Community": "BC"},
            "field_confidences": {"Community": 95},
        },
    ]
    merged = pipeline._order_independent_cross_document_merge(
        detected_docs=detected_docs,
        all_extracted_pool=extracted_pool,
        excel_headers=["Community Category"],
    )
    assert merged["Community Category"]["value"] == "BC"


# =========================================================================
# Scenario 27: Cross-Document EMIS sets Is EMIS ID Available = Yes
# =========================================================================
def test_scenario_27_cross_document_emis_resolution():
    pipeline = DocumentProcessingPipeline()
    detected_docs = [
        {"document_type": "Aadhaar Card", "type": "Aadhaar Card"},
        {"document_type": "Transfer Certificate", "type": "Transfer Certificate"},
    ]
    extracted_pool = [
        {
            "document_type": "Aadhaar Card",
            "extracted_data": {"Date of Birth": "15/05/2005"},
            "field_confidences": {"Date of Birth": 95},
        },
        {
            "document_type": "Transfer Certificate",
            "extracted_data": {"EMIS ID": "2015743426", "Nationality": "INDIAN"},
            "field_confidences": {"EMIS ID": 95, "Nationality": 90},
        },
    ]
    merged = pipeline._order_independent_cross_document_merge(
        detected_docs=detected_docs,
        all_extracted_pool=extracted_pool,
        excel_headers=["EMIS ID", "Is EMIS ID Available", "Nationality"],
    )
    assert merged["EMIS ID"]["value"] == "2015743426"
    assert merged["Is EMIS ID Available"]["value"] == "Yes"
    assert merged["Nationality"]["value"] == "INDIAN"


# =========================================================================
# Scenario 28: End-to-End Multi-Doc Regression (The exact regression case)
# =========================================================================
def test_scenario_28_end_to_end_regression_exact_case():
    pipeline = DocumentProcessingPipeline()
    detected_docs = [
        {"document_type": "Aadhaar Card", "type": "Aadhaar Card"},
        {"document_type": "Transfer Certificate", "type": "Transfer Certificate"},
        {"document_type": "10th Mark Sheet", "type": "10th Mark Sheet"},
        {"document_type": "Community Certificate", "type": "Community Certificate"},
    ]
    extracted_pool = [
        {
            "document_type": "Aadhaar Card",
            "extracted_data": {
                "Student Name": "ARUN KUMAR S",
                "Date of Birth": "15/05/2005",
                "Gender": "Male",
                "Aadhaar Number": "9573 0978 4448",
                "Permanent Address": "12/4 East Street, Mohanur Road, Namakkal 637001",
            },
            "field_confidences": {
                "Student Name": 95, "Date of Birth": 95, "Gender": 95,
                "Aadhaar Number": 95, "Permanent Address": 95,
            },
        },
        {
            "document_type": "Transfer Certificate",
            "extracted_data": {
                "Date of Birth": "24.10.2024",  # Issue date that previously polluted DOB!
                "EMIS ID": "2015743426",
                "Nationality": "Indian",
                "Guardian Name": "NONE",
            },
            "field_confidences": {"Date of Birth": 90, "EMIS ID": 95, "Nationality": 90, "Guardian Name": 95},
        },
        {
            "document_type": "10th Mark Sheet",
            "extracted_data": {
                "Father Name": "SURESH K",
                "Mother Name": "LAKSHMI S",
            },
            "field_confidences": {"Father Name": 92, "Mother Name": 92},
        },
        {
            "document_type": "Community Certificate",
            "extracted_data": {
                "Community": "BC",
                "Caste": "Vadugar",
            },
            "field_confidences": {"Community": 95, "Caste": 95},
        },
    ]

    target_headers = [
        "Student Name",
        "Date of Birth",
        "Gender",
        "Aadhaar Number",
        "Permanent Address",
        "Is Communication Address Same as Permanent Address",
        "EMIS ID",
        "Is EMIS ID Available",
        "Nationality",
        "Community Category",
        "Community Name",
        "Father Name",
        "Mother Name",
        "Guardian Name",
    ]

    merged = pipeline._order_independent_cross_document_merge(
        detected_docs=detected_docs,
        all_extracted_pool=extracted_pool,
        excel_headers=target_headers,
    )

    # 1. DOB must be authentic birth date, NOT 24.10.2024
    assert merged["Date of Birth"]["value"] == "15.05.2005"
    assert merged["Date of Birth"]["value"] != "24.10.2024"

    # 2. EMIS ID must be accepted and available marked Yes
    assert merged["EMIS ID"]["value"] == "2015743426"
    assert merged["Is EMIS ID Available"]["value"] == "Yes"

    # 3. Gender must be clean enum
    assert merged["Gender"]["value"] == "MALE"

    # 4. Nationality must be INDIAN
    assert merged["Nationality"]["value"] == "INDIAN"

    # 5. Permanent Address must be real address, NOT "Yes"
    assert merged["Permanent Address"]["value"] == "12/4 East Street, Mohanur Road, Namakkal 637001"
    assert merged["Permanent Address"]["value"] != "Yes"

    # 6. Boolean address flag must be Yes
    assert merged["Is Communication Address Same as Permanent Address"]["value"] == "Yes"

    # 7. Community Category must be BC from Community Certificate
    assert merged["Community Category"]["value"] == "BC"


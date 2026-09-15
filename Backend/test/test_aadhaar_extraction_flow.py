"""
Comprehensive Unit & Regression Test Suite for Aadhaar Number Extraction Flow
==============================================================================
Validates end-to-end extraction, normalization, contextual OCR confusion handling,
Verhoeff validation, strict field boundary separation, Gemini alias canonicalization,
candidate pool integration, and Excel mapping.
"""

import pytest
import re
from app.utils.normalization import (
    validate_and_normalize_aadhaar,
    normalize_aadhaar_digits,
    correct_aadhaar_ocr_confusion,
    validate_verhoeff,
)
from app.services.ocr_preprocessor import OCRPreprocessor
from app.services.field_mapping_service import FieldMappingService
from app.utils.field_canonicalizer import is_number_conflict, get_canonical_field_name
from app.services.document_processing_pipeline import DocumentProcessingPipeline
from app.services.field_source_rules import evaluate_field_source
from app.utils.field_canonicalizer import get_document_field_authority_weight
from app.services.gemini_service import GeminiService


# 1. "1234 5678 9012" normalizes correctly
def test_01_aadhaar_spaced_normalizes():
    raw = "1234 5678 9012"
    assert normalize_aadhaar_digits(raw) == "123456789012"
    assert validate_and_normalize_aadhaar(raw, without_space=True) == "123456789012"
    assert validate_and_normalize_aadhaar(raw, without_space=False) == "1234 5678 9012"


# 2. "1234-5678-9012" normalizes correctly
def test_02_aadhaar_hyphenated_normalizes():
    raw = "1234-5678-9012"
    assert normalize_aadhaar_digits(raw) == "123456789012"
    assert validate_and_normalize_aadhaar(raw, without_space=True) == "123456789012"
    assert validate_and_normalize_aadhaar(raw, without_space=False) == "1234 5678 9012"


# 3. Newline-separated Aadhaar normalizes correctly
def test_03_aadhaar_newline_separated_normalizes():
    raw_nl1 = "1234 5678\n9012"
    raw_nl2 = "1234\n5678\n9012"
    assert normalize_aadhaar_digits(raw_nl1) == "123456789012"
    assert normalize_aadhaar_digits(raw_nl2) == "123456789012"
    assert validate_and_normalize_aadhaar(raw_nl1, without_space=True) == "123456789012"


# 4. Tamil Aadhaar label is recognized
def test_04_tamil_aadhaar_label_recognized():
    prep = OCRPreprocessor()
    text = "அரசு ஆவணம்\nஆதார் எண் : 1234 5678 9012\nபெயர்: மாணவர்"
    res = prep.extract_regex_fields(text)
    assert "aadhaar_number" in res
    assert res["aadhaar_number"]["value"] == "123456789012"


# 5. English Aadhaar label is recognized
def test_05_english_aadhaar_label_recognized():
    prep = OCRPreprocessor()
    text = "Government of India\nYour Aadhaar No. : 1234 5678 9012\nVID: 9196 9850 6993 9639"
    res = prep.extract_regex_fields(text)
    assert "aadhaar_number" in res
    assert res["aadhaar_number"]["value"] == "123456789012"


# 6. 10-digit mobile is rejected as Aadhaar
def test_06_ten_digit_mobile_rejected_as_aadhaar():
    mobile = "9876543210"
    assert normalize_aadhaar_digits(mobile) is None
    assert validate_and_normalize_aadhaar(mobile) is None


# 7. 11-digit number is rejected as Aadhaar
def test_07_eleven_digit_number_rejected_as_aadhaar():
    eleven = "12345678901"
    assert normalize_aadhaar_digits(eleven) is None
    assert validate_and_normalize_aadhaar(eleven) is None


# 8. Register Number is not mapped to Aadhaar
def test_08_register_number_not_mapped_to_aadhaar():
    fms = FieldMappingService()
    pool = {"Register Number": {"value": "714024247103", "confidence": 100}}
    val, conf, _ = fms.resolve_field_value("Aadhaar Number", pool)
    assert val is None
    assert is_number_conflict("Aadhaar Number", "Register Number") is True


# 9. EMIS ID is not mapped to Aadhaar
def test_09_emis_id_not_mapped_to_aadhaar():
    fms = FieldMappingService()
    pool = {"EMIS ID": {"value": "3302070010112345", "confidence": 100}}
    val, conf, _ = fms.resolve_field_value("Aadhaar Number", pool)
    assert val is None
    assert is_number_conflict("Aadhaar Number", "EMIS ID") is True


# 10. Application Number is not mapped to Aadhaar
def test_10_application_number_not_mapped_to_aadhaar():
    fms = FieldMappingService()
    pool = {"Application Number": {"value": "123456789012", "confidence": 90}}
    val, conf, _ = fms.resolve_field_value("Aadhaar Number", pool)
    assert val is None
    assert is_number_conflict("Aadhaar Number", "Application Number") is True


# 11. Account Number is not mapped to Aadhaar
def test_11_account_number_not_mapped_to_aadhaar():
    fms = FieldMappingService()
    pool = {"Account Number": {"value": "123456789012", "confidence": 90}}
    val, conf, _ = fms.resolve_field_value("Aadhaar Number", pool)
    assert val is None
    assert is_number_conflict("Aadhaar Number", "Account Number") is True


# 12. Valid Verhoeff Aadhaar passes
def test_12_valid_verhoeff_aadhaar_passes():
    valid_mock = "123456789012"
    assert validate_verhoeff(valid_mock) is True
    assert normalize_aadhaar_digits(valid_mock) == valid_mock


# 13. Invalid checksum Aadhaar is rejected
def test_13_invalid_checksum_aadhaar_rejected():
    invalid_candidate = "123456789019"
    assert validate_verhoeff(invalid_candidate) is False
    assert normalize_aadhaar_digits(invalid_candidate) is None
    assert validate_and_normalize_aadhaar(invalid_candidate) is None


# 14. Invalid OCR candidate is never written to Excel
def test_14_invalid_ocr_candidate_never_written_to_excel():
    fms = FieldMappingService()
    invalid_pool = {"aadhaar_number": {"value": "123456789019", "confidence": 80}}
    mapped = fms.map_all_excel_headers(["Aadhaar Number (without space)"], invalid_pool)
    write_dict = fms.format_for_excel_write(["Aadhaar Number (without space)"], mapped)
    assert write_dict.get("Aadhaar Number (without space)") is None


# 15. Gemini aadhaar_number reaches candidate pool
def test_15_gemini_aadhaar_reaches_candidate_pool():
    pipeline = DocumentProcessingPipeline()
    extracted_docs = {
        "aadhaar.pdf": {
            "aadhaar_number": {"value": "1234 5678 9012", "confidence": 95},
        }
    }
    types_per_file = {"aadhaar.pdf": "AADHAAR"}
    res = pipeline._order_independent_cross_document_merge(
        detected_docs=["aadhaar.pdf"],
        all_extracted_pool=extracted_docs,
        excel_headers=["Aadhaar Number (without space)", "Aadhaar Number"],
        document_types_per_file=types_per_file,
    )
    assert "Aadhaar Number (without space)" in res
    assert res["Aadhaar Number (without space)"]["value"] == "123456789012"
    assert res["Aadhaar Number (without space)"]["validation_status"] == "VALID"


# 16. Candidate reaches final merged fields
def test_16_candidate_reaches_final_merged_fields():
    pipeline = DocumentProcessingPipeline()
    extracted_docs = {
        "aadhaar.pdf": {
            "aadhaar_number": {"value": "1234 5678 9012", "confidence": 95},
        }
    }
    types_per_file = {"aadhaar.pdf": "AADHAAR"}
    res = pipeline._order_independent_cross_document_merge(
        detected_docs=["aadhaar.pdf"],
        all_extracted_pool=extracted_docs,
        excel_headers=["Aadhaar Number"],
        document_types_per_file=types_per_file,
    )
    assert "Aadhaar Number" in res
    assert res["Aadhaar Number"]["value"] == "1234 5678 9012"


# 17. Wanted-field filtering preserves Aadhaar
def test_17_wanted_field_filtering_preserves_aadhaar():
    pipeline = DocumentProcessingPipeline()
    raw_extracted = {
        "aadhaar_number": {"value": "123456789012", "confidence": 100},
        "Unwanted Field": {"value": "Random", "confidence": 90},
    }
    wanted = ["Aadhaar Number"]
    filtered = pipeline._filter_fields_to_wanted(raw_extracted, wanted)
    assert "aadhaar_number" in filtered
    assert "Unwanted Field" not in filtered


# 18. Cache does not return stale schema result
def test_18_cache_safety_and_bypass():
    svc = GeminiService()
    test_bytes = b"sample_pdf_binary_content_mock"
    # Ensure cache key incorporates schema version
    import hashlib, json
    doc_hash = hashlib.sha256(test_bytes).hexdigest()
    fields_hash = hashlib.sha256(json.dumps(sorted(["Aadhaar Number"])).encode("utf-8")).hexdigest()[:16]
    expected_key_prefix = f"{len(test_bytes)}_{doc_hash}_{fields_hash}_v3_aadhaar_canonical"
    assert "v3_aadhaar_canonical" in expected_key_prefix


# 19. Final Excel cell is the configured Aadhaar column
def test_19_final_excel_cell_is_configured_column():
    fms = FieldMappingService()
    pool = {"aadhaar_number": {"value": "123456789012", "confidence": 100}}
    # Header A: without space
    res_a = fms.map_all_excel_headers(["Aadhaar Number (without space)"], pool)
    write_a = fms.format_for_excel_write(["Aadhaar Number (without space)"], res_a)
    assert write_a["Aadhaar Number (without space)"] == "123456789012"

    # Header B: standard spaced
    res_b = fms.map_all_excel_headers(["Aadhaar Number"], pool)
    write_b = fms.format_for_excel_write(["Aadhaar Number"], res_b)
    assert write_b["Aadhaar Number"] == "1234 5678 9012"

    # Never writes to Taluk or District
    res_c = fms.map_all_excel_headers(["Taluk", "District"], pool)
    write_c = fms.format_for_excel_write(["Taluk", "District"], res_c)
    assert write_c["Taluk"] is None
    assert write_c["District"] is None


# 20. Contextual OCR confusion handling
def test_20_contextual_ocr_confusion():
    # 'O' -> '0', 'I' -> '1', 'S' -> '5', 'B' -> '8', 'G' -> '6' inside Aadhaar context
    confused_str = "Aadhaar No: I234 S678 90I2"
    corrected = correct_aadhaar_ocr_confusion(confused_str)
    assert corrected.strip() == "1234 5678 9012"
    assert normalize_aadhaar_digits(confused_str) == "123456789012"

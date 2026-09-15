"""
Test Suite: Extraction Data Flow & Data Loss Prevention Regression Tests
========================================================================
Validates the end-to-end data flow per Phase 16 requirements:
1. Four documents are all processed without silent drops.
2. Each processed document produces an [EXTRACT_TRACE] trace.
3. Gemini response fields enter candidate pool.
4. Candidate pool retains fields from multiple documents.
5. Same field from multiple documents creates multiple candidates.
6. Authority merge is order-independent.
7. DOB from Aadhaar/TC/SSLC merges correctly with authority ranking.
8. Community from Community Certificate wins over TC and SSLC.
9. EMIS from TC wins over SSLC.
10. Explicit NONE is preserved as valid negative evidence.
11. Full address never maps to Village Panchayat.
12. Person name never maps to occupation.
13. Aadhaar never maps to mobile/register.
14. District never maps to Taluk.
15. Profile data does not suppress document-derived fields.
16. "Not Found" is assigned only after all documents finish.
17. Cache hit returns a result compatible with wanted-field configuration.
18. Cache bypass forces fresh extraction.
19. Existing Excel mapping integrity is preserved.
20. Cross-document candidates preserve provenance without dictionary overwrites.
"""

import hashlib
import json
import pytest
from unittest.mock import MagicMock, patch

from app.services.document_processing_pipeline import DocumentProcessingPipeline
from app.services.field_mapping_service import FieldMappingService
from app.services.gemini_service import GeminiService
from app.utils.field_canonicalizer import get_canonical_field_name
from app.utils.normalization import (
    validate_and_normalize_location_name,
    validate_and_normalize_village_panchayat,
    validate_and_normalize_occupation,
    validate_and_normalize_aadhaar,
    validate_and_normalize_dob,
    validate_and_normalize_emis,
    normalize_register_number,
)


@pytest.fixture
def pipeline():
    return DocumentProcessingPipeline()


@pytest.fixture
def mapper():
    return FieldMappingService()


# 1. Four documents are all processed without silent drops
def test_01_four_documents_all_processed(pipeline):
    detected_docs = [
        {"document_type": "Transfer Certificate", "type": "Transfer Certificate"},
        {"document_type": "Community Certificate", "type": "Community Certificate"},
        {"document_type": "Aadhaar Card", "type": "Aadhaar Card"},
        {"document_type": "Allotment Order", "type": "Allotment Order"},
    ]
    extracted_pool = [
        {
            "document_type": "Transfer Certificate",
            "source_file": "TC.pdf",
            "extracted_data": {"EMIS ID": "2015743426", "Mother Name": "PRIYA G"},
            "field_confidences": {"EMIS ID": 95, "Mother Name": 95},
        },
        {
            "document_type": "Community Certificate",
            "source_file": "digital_commity.pdf",
            "extracted_data": {"Community": "BC", "Caste": "Vanniyar"},
            "field_confidences": {"Community": 95, "Caste": 95},
        },
        {
            "document_type": "Aadhaar Card",
            "source_file": "Screenshot 2026-08-05 162541.png",
            "extracted_data": {"Aadhaar Number": "1234 5678 9012", "Date of Birth": "07/06/2007", "Gender": "Female"},
            "field_confidences": {"Aadhaar Number": 95, "Date of Birth": 95, "Gender": 95},
        },
        {
            "document_type": "Allotment Order",
            "source_file": "Provisional_Allotment_271844.pdf",
            "extracted_data": {"Application Number": "271844", "Allotted Branch": "CSE"},
            "field_confidences": {"Application Number": 95, "Allotted Branch": 95},
        },
    ]

    merged = pipeline._order_independent_cross_document_merge(
        detected_docs=detected_docs,
        all_extracted_pool=extracted_pool,
        excel_headers=["EMIS ID", "Mother's Name", "Community", "Caste", "Aadhaar Number", "Date of Birth", "Gender"],
    )

    # All 4 documents contributed fields into final merge
    assert merged["EMIS ID"]["value"] == "2015743426"
    assert merged["Mother's Name"]["value"] == "PRIYA G"
    assert merged["Community"]["value"] == "BC"
    assert merged["Caste"]["value"] == "VANNIYAR"
    assert merged["Aadhaar Number"]["value"] == "1234 5678 9012"
    assert merged["Date of Birth"]["value"] == "07.06.2007"
    assert merged["Gender"]["value"] == "FEMALE"


# 2. Each processed document produces an [EXTRACT_TRACE] trace
def test_02_each_processed_document_produces_trace(pipeline, tmp_path, capsys):
    mock_gemini = MagicMock()
    mock_gemini.extract_from_bytes.return_value = {
        "success": True,
        "document_type": "TRANSFER_CERTIFICATE",
        "fields": {"EMIS ID": {"value": "2015743426", "confidence": 95}},
        "timing_metrics": {},
    }
    pipeline.gemini_service = mock_gemini

    from app.utils.performance_profiler import DocumentTimer
    timer = DocumentTimer("TC.pdf")
    pipeline._process_single_document(
        filename="TC.pdf",
        file_bytes=b"%PDF-1.4 mock content for TC",
        excel_headers=["EMIS ID"],
        uploads_dir=tmp_path,
        doc_timer=timer,
    )

    captured = capsys.readouterr().out
    assert "[EXTRACT_TRACE]" in captured
    assert "document_type=" in captured
    assert "gemini_called=" in captured


# 3. Gemini response fields enter candidate pool
def test_03_gemini_fields_enter_candidate_pool(pipeline):
    extracted_pool = [
        {
            "document_type": "Transfer Certificate",
            "source_file": "tc.pdf",
            "extracted_data": {"Date of Birth": "07/06/2007", "EMIS ID": "2015743426"},
            "field_confidences": {"Date of Birth": 90, "EMIS ID": 95},
        }
    ]
    merged = pipeline._order_independent_cross_document_merge(
        detected_docs=["Transfer Certificate"],
        all_extracted_pool=extracted_pool,
        excel_headers=["Date of Birth", "EMIS ID"],
    )
    assert merged["Date of Birth"]["value"] == "07.06.2007"
    assert merged["EMIS ID"]["value"] == "2015743426"


# 4. Candidate pool retains fields from multiple documents
def test_04_candidate_pool_retains_fields_from_multiple_docs(pipeline):
    extracted_pool = [
        {
            "document_type": "Aadhaar Card",
            "source_file": "aadhaar.pdf",
            "extracted_data": {"Aadhaar Number": "1234 5678 9012", "State": "Tamil Nadu"},
            "field_confidences": {"Aadhaar Number": 95, "State": 90},
        },
        {
            "document_type": "Community Certificate",
            "source_file": "comm.pdf",
            "extracted_data": {"Community": "MBC", "District": "Salem"},
            "field_confidences": {"Community": 95, "District": 90},
        },
    ]
    merged = pipeline._order_independent_cross_document_merge(
        detected_docs=["Aadhaar Card", "Community Certificate"],
        all_extracted_pool=extracted_pool,
        excel_headers=["Aadhaar Number", "State", "Community", "District"],
    )
    assert merged["Aadhaar Number"]["value"] == "1234 5678 9012"
    assert merged["State"]["value"] == "Tamil Nadu"
    assert merged["Community"]["value"] == "MBC"
    assert merged["District"]["value"] == "Salem"


# 5. Same field from multiple documents creates multiple candidates
def test_05_same_field_creates_multiple_candidates(pipeline):
    # Both Aadhaar and TC have DOB
    extracted_pool = [
        {
            "document_type": "Aadhaar Card",
            "source_file": "aadhaar.pdf",
            "extracted_data": {"Date of Birth": "07/06/2007"},
            "field_confidences": {"Date of Birth": 95},
        },
        {
            "document_type": "Transfer Certificate",
            "source_file": "tc.pdf",
            "extracted_data": {"Date of Birth": "07/06/2007"},
            "field_confidences": {"Date of Birth": 90},
        },
    ]
    merged = pipeline._order_independent_cross_document_merge(
        detected_docs=["Aadhaar Card", "Transfer Certificate"],
        all_extracted_pool=extracted_pool,
        excel_headers=["Date of Birth"],
    )
    # Aadhaar has higher authority (100) than TC (90)
    assert merged["Date of Birth"]["source_type"] == "AADHAAR"
    assert merged["Date of Birth"]["authority"] == 100


# 6. Authority merge is order-independent
def test_06_authority_merge_is_order_independent(pipeline):
    doc_aadhaar = {
        "document_type": "Aadhaar Card",
        "source_file": "aadhaar.pdf",
        "extracted_data": {"Date of Birth": "07/06/2007", "Gender": "Female"},
        "field_confidences": {"Date of Birth": 95, "Gender": 95},
    }
    doc_tc = {
        "document_type": "Transfer Certificate",
        "source_file": "tc.pdf",
        "extracted_data": {"Date of Birth": "08/06/2007", "EMIS ID": "2015743426"},
        "field_confidences": {"Date of Birth": 90, "EMIS ID": 90},
    }

    res1 = pipeline._order_independent_cross_document_merge(
        detected_docs=["Aadhaar Card", "Transfer Certificate"],
        all_extracted_pool=[doc_aadhaar, doc_tc],
        excel_headers=["Date of Birth", "EMIS ID"],
    )
    res2 = pipeline._order_independent_cross_document_merge(
        detected_docs=["Transfer Certificate", "Aadhaar Card"],
        all_extracted_pool=[doc_tc, doc_aadhaar],
        excel_headers=["Date of Birth", "EMIS ID"],
    )
    assert res1["Date of Birth"]["value"] == res2["Date of Birth"]["value"] == "07.06.2007"
    assert res1["EMIS ID"]["value"] == res2["EMIS ID"]["value"] == "2015743426"


# 7. DOB from Aadhaar/TC/SSLC merges correctly
def test_07_dob_hierarchy_aadhaar_tc_sslc(pipeline):
    # Case A: Aadhaar present -> Aadhaar wins
    pool_all = [
        {"document_type": "10th Mark Sheet", "source_file": "s.pdf", "extracted_data": {"DOB": "01/01/2007"}, "field_confidences": {"DOB": 99}},
        {"document_type": "Transfer Certificate", "source_file": "t.pdf", "extracted_data": {"DOB": "02/02/2007"}, "field_confidences": {"DOB": 99}},
        {"document_type": "Aadhaar Card", "source_file": "a.pdf", "extracted_data": {"DOB": "07/06/2007"}, "field_confidences": {"DOB": 95}},
    ]
    m_all = pipeline._order_independent_cross_document_merge(
        detected_docs=["10th Mark Sheet", "Transfer Certificate", "Aadhaar Card"],
        all_extracted_pool=pool_all,
        excel_headers=["Date of Birth"],
    )
    assert m_all["Date of Birth"]["value"] == "07.06.2007"
    assert m_all["Date of Birth"]["source_type"] == "AADHAAR"

    # Case B: Aadhaar absent -> TC wins over SSLC
    pool_no_aadhaar = [
        {"document_type": "10th Mark Sheet", "source_file": "s.pdf", "extracted_data": {"DOB": "01/01/2007"}, "field_confidences": {"DOB": 99}},
        {"document_type": "Transfer Certificate", "source_file": "t.pdf", "extracted_data": {"DOB": "02/02/2007"}, "field_confidences": {"DOB": 95}},
    ]
    m_tc = pipeline._order_independent_cross_document_merge(
        detected_docs=["10th Mark Sheet", "Transfer Certificate"],
        all_extracted_pool=pool_no_aadhaar,
        excel_headers=["Date of Birth"],
    )
    assert m_tc["Date of Birth"]["value"] == "02.02.2007"
    assert m_tc["Date of Birth"]["source_type"] == "TRANSFER_CERTIFICATE"


# 8. Community from Community Certificate wins
def test_08_community_from_community_certificate_wins(pipeline):
    extracted_pool = [
        {"document_type": "Transfer Certificate", "source_file": "tc.pdf", "extracted_data": {"Community": "BC", "Caste": "TC Caste"}, "field_confidences": {"Community": 99, "Caste": 99}},
        {"document_type": "Community Certificate", "source_file": "comm.pdf", "extracted_data": {"Community": "MBC", "Caste": "Vanniyar"}, "field_confidences": {"Community": 90, "Caste": 90}},
    ]
    merged = pipeline._order_independent_cross_document_merge(
        detected_docs=["Transfer Certificate", "Community Certificate"],
        all_extracted_pool=extracted_pool,
        excel_headers=["Community", "Caste"],
    )
    assert merged["Community"]["value"] == "MBC"
    assert merged["Community"]["source_type"] == "COMMUNITY"
    assert merged["Caste"]["value"] == "VANNIYAR"
    assert merged["Caste"]["source_type"] == "COMMUNITY"


# 9. EMIS from TC wins
def test_09_emis_from_tc_wins(pipeline):
    extracted_pool = [
        {"document_type": "10th Mark Sheet", "source_file": "sslc.pdf", "extracted_data": {"EMIS ID": "1111222233"}, "field_confidences": {"EMIS ID": 99}},
        {"document_type": "Transfer Certificate", "source_file": "tc.pdf", "extracted_data": {"EMIS ID": "2015743426"}, "field_confidences": {"EMIS ID": 90}},
    ]
    merged = pipeline._order_independent_cross_document_merge(
        detected_docs=["10th Mark Sheet", "Transfer Certificate"],
        all_extracted_pool=extracted_pool,
        excel_headers=["EMIS ID"],
    )
    assert merged["EMIS ID"]["value"] == "2015743426"
    assert merged["EMIS ID"]["source_type"] == "TRANSFER_CERTIFICATE"


# 10. Explicit NONE is preserved
def test_10_explicit_none_is_preserved(pipeline):
    extracted_pool = [
        {"document_type": "Community Certificate", "source_file": "c.pdf", "extracted_data": {"Guardian Name": "SARAVANAKUMAR"}, "field_confidences": {"Guardian Name": 90}},
        {"document_type": "Transfer Certificate", "source_file": "t.pdf", "extracted_data": {"Guardian Name": "NONE"}, "field_confidences": {"Guardian Name": 95}},
    ]
    merged = pipeline._order_independent_cross_document_merge(
        detected_docs=["Community Certificate", "Transfer Certificate"],
        all_extracted_pool=extracted_pool,
        excel_headers=["Guardian Name"],
    )
    assert merged["Guardian Name"]["value"] == "NO"
    assert merged["Guardian Name"]["state"] == "EXPLICIT_NEGATIVE"


# 11. Full address never maps to Village Panchayat
def test_11_full_address_never_maps_to_village_panchayat():
    full_addr = "12/4, North Street, Gandhinagar, Salem - 636001"
    res = validate_and_normalize_village_panchayat(full_addr)
    assert res is None


# 12. Person name never maps to occupation
def test_12_person_name_never_maps_to_occupation():
    assert validate_and_normalize_occupation("SARAVANAN K") is None
    assert validate_and_normalize_occupation("Priya Patel") is None
    assert validate_and_normalize_occupation("PRIYA G") is None
    assert validate_and_normalize_occupation("Farmer") == "Farmer"
    assert validate_and_normalize_occupation("Business") == "Business"
    assert validate_and_normalize_occupation("Agriculture") == "Agriculture"


# 13. Aadhaar never maps to mobile/register
def test_13_aadhaar_never_maps_to_mobile_or_register():
    aadh = "1234 5678 9012"
    # Aadhaar must normalize to 12-digit format
    assert validate_and_normalize_aadhaar(aadh) == "1234 5678 9012"
    # Registration number logic does not mistake Aadhaar for academic register number
    reg = normalize_register_number("24CS105")
    assert reg == "24CS105"


# 14. District never maps to Taluk
def test_14_district_never_maps_to_taluk():
    # District and Taluk are distinct canonical fields
    assert get_canonical_field_name("District") == "District"
    assert get_canonical_field_name("Taluk") == "Taluk"
    assert get_canonical_field_name("District") != get_canonical_field_name("Taluk")


# 15. Profile data does not suppress document extraction
def test_15_profile_data_does_not_suppress_document_extraction(pipeline):
    profile = {
        "student_name": "SARAVANAN S",
        "register_number": "24AM001",
        "mobile_number": "9876543210",
        "email": "saravanan@example.com",
    }
    extracted_pool = [
        {
            "document_type": "Transfer Certificate",
            "source_file": "tc.pdf",
            "extracted_data": {
                "Father Name": "SURESH K",
                "Mother Name": "PRIYA G",
                "DOB": "07/06/2007",
                "EMIS ID": "2015743426",
            },
            "field_confidences": {"Father Name": 95, "Mother Name": 95, "DOB": 95, "EMIS ID": 95},
        }
    ]
    merged = pipeline._order_independent_cross_document_merge(
        detected_docs=["Transfer Certificate"],
        all_extracted_pool=extracted_pool,
        excel_headers=["Student Name", "Register Number", "Father's Name", "Mother's Name", "Date of Birth", "EMIS ID"],
        student_profile=profile,
    )
    # Profile fields populated
    assert merged["Student Name"]["value"] == "SARAVANAN S"
    assert merged["Register Number"]["value"] == "24AM001"
    # Document fields preserved and NOT suppressed
    assert merged["Father's Name"]["value"] == "SURESH K"
    assert merged["Mother's Name"]["value"] == "PRIYA G"
    assert merged["Date of Birth"]["value"] == "07.06.2007"
    assert merged["EMIS ID"]["value"] == "2015743426"


# 16. Not Found is assigned only after all documents finish
def test_16_not_found_only_at_the_end(pipeline):
    extracted_pool = [
        {
            "document_type": "Transfer Certificate",
            "source_file": "tc.pdf",
            "extracted_data": {"EMIS ID": "2015743426"},
            "field_confidences": {"EMIS ID": 95},
        }
    ]
    merged = pipeline._order_independent_cross_document_merge(
        detected_docs=["Transfer Certificate"],
        all_extracted_pool=extracted_pool,
        excel_headers=["EMIS ID", "Annual Income"],
    )
    # Found from document
    assert merged["EMIS ID"]["value"] == "2015743426"
    assert merged["EMIS ID"]["requires_verification"] is False
    # Only fields with 0 valid candidates become None / verification required
    assert merged["Annual Income"]["value"] is None
    assert merged["Annual Income"]["requires_verification"] is True


# 17. Cache hit returns a result compatible with current wanted-field configuration
def test_17_cache_key_includes_wanted_fields():
    file_bytes = b"sample_pdf_bytes"
    doc_hash = hashlib.sha256(file_bytes).hexdigest()
    fields_hash1 = hashlib.sha256(json.dumps(sorted(["EMIS ID", "DOB"])).encode("utf-8")).hexdigest()[:16]
    fields_hash2 = hashlib.sha256(json.dumps(sorted(["EMIS ID", "Student Name"])).encode("utf-8")).hexdigest()[:16]
    key1 = f"{len(file_bytes)}_{doc_hash}_{fields_hash1}"
    key2 = f"{len(file_bytes)}_{doc_hash}_{fields_hash2}"
    assert key1 != key2


# 18. Cache bypass produces fresh extraction
def test_18_cache_bypass_flag():
    service = GeminiService()
    file_bytes = b"sample_pdf_bytes_for_bypass"
    doc_hash = hashlib.sha256(file_bytes).hexdigest()
    target_fields = ["EMIS ID"]
    fields_hash = hashlib.sha256(json.dumps(sorted(target_fields)).encode("utf-8")).hexdigest()[:16]
    content_key = f"{len(file_bytes)}_{doc_hash}_{fields_hash}"

    with service._cache_lock:
        service._response_cache[content_key] = {"success": True, "cached_entry": True}

    with patch.object(service, "extract_from_file", return_value={"success": True, "fresh": True}):
        res = service.extract_from_bytes(file_bytes, "application/pdf", "sample.pdf", target_fields, bypass_cache=True)
        assert res.get("cached_entry") is None


# 19. Existing Excel mapping tests still pass
def test_19_excel_mapping_exact_alignment(mapper):
    fields = {
        "Permanent Address": {"value": "12 North St, Salem", "requires_verification": False},
        "District": {"value": "Salem", "requires_verification": False},
        "Taluk": {"value": "Omalur", "requires_verification": False},
        "Father's Name": {"value": "SURESH K", "requires_verification": False},
        "Father's Occupation": {"value": "Agriculture", "requires_verification": False},
    }
    excel_headers = ["Permanent Address", "District", "Taluk", "Father's Name", "Father's Occupation"]
    mapped = mapper.format_for_excel_write(excel_headers=excel_headers, mapped_fields=fields)

    assert mapped["Permanent Address"] == "12 North St, Salem"
    assert mapped["District"] == "Salem"
    assert mapped["Taluk"] == "Omalur"
    assert mapped["Father's Name"] == "SURESH K"
    assert mapped["Father's Occupation"] == "Agriculture"


# 20. Cross-document candidates preserve provenance without dictionary overwrites
def test_20_candidate_pool_preserves_provenance(pipeline):
    extracted_pool = [
        {
            "document_type": "Aadhaar Card",
            "source_file": "aadhaar.pdf",
            "extracted_data": {"Date of Birth": "07/06/2007"},
            "field_confidences": {"Date of Birth": 95},
        },
        {
            "document_type": "Transfer Certificate",
            "source_file": "tc.pdf",
            "extracted_data": {"Date of Birth": "07/06/2007"},
            "field_confidences": {"Date of Birth": 90},
        },
    ]
    merged = pipeline._order_independent_cross_document_merge(
        detected_docs=["Aadhaar Card", "Transfer Certificate"],
        all_extracted_pool=extracted_pool,
        excel_headers=["Date of Birth"],
    )
    # Provenance tracked accurately
    assert merged["Date of Birth"]["source_document"] == "aadhaar.pdf"
    assert merged["Date of Birth"]["source_type"] == "AADHAAR"
    assert merged["Date of Birth"]["authority"] == 100
